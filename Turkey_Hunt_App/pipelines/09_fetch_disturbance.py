"""
Fetch disturbance areas (fire perimeters + timber harvest clearings) near Idaho
for the LAST 5 YEARS, then clip to master Turkey GMU boundary.

Sources (you specified):
  Fires:
    https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/InterAgencyFirePerimeterHistory_All_Years_View/FeatureServer/0/query
  Timber harvest:
    https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_TimberHarvest_01/MapServer/8/query

Outputs:
  pipelines/data/processed/burned_areas.geojson
  pipelines/data/processed/logging_areas.geojson

Notes:
  - Uses f=geojson for downloads (no ESRI-JSON parsing).
  - Tries to build an efficient server-side "last 5 years" WHERE clause by probing fields.
  - Never raises on service failure — writes empty GeoJSON instead.
  - bbox is derived from hunt_units.geojson if available; otherwise Idaho fallback bbox.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from _gmu_clip import clip_to_master_gmu

PAGE_SIZE = 500
TIMEOUT = 120

_ROOT = Path(__file__).resolve().parent.parent
UNITS_PATH = _ROOT / "pipelines" / "data" / "processed" / "hunt_units.geojson"
BURNED_PATH = _ROOT / "pipelines" / "data" / "processed" / "burned_areas.geojson"
LOGGING_PATH = _ROOT / "pipelines" / "data" / "processed" / "logging_areas.geojson"

# Idaho bounding box (fallback)
IDAHO_BBOX = (-117.3, 41.9, -111.0, 49.1)

FIRE_URL = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
    "InterAgencyFirePerimeterHistory_All_Years_View/FeatureServer/0/query"
)

HARVEST_URL = (
    "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_TimberHarvest_01/"
    "MapServer/8/query"
)

# Candidate fields to detect a "year" for filtering
FIRE_YEAR_FIELDS = ["FIRE_YEAR_INT", "FIRE_YEAR", "FIREYEAR", "YEAR", "Year", "FireYear"]
HARVEST_YEAR_FIELDS = ["YEAR", "Year", "ACTIVITY_YEAR", "Activity_Year", "CAL_YEAR", "FISCAL_YEAR", "FY"]
HARVEST_DATE_FIELDS = [
    "DATE_COMPLETED", "Date_Completed", "COMPLETION_DATE", "Completion_Date",
    "DATE_ACCOMPLISHED", "Date_Accomplished", "END_DATE", "End_Date", "DATE_DONE", "Date_Done"
]


def _get_idaho_bbox() -> tuple[float, float, float, float]:
    if not UNITS_PATH.exists():
        return IDAHO_BBOX
    try:
        units = gpd.read_file(UNITS_PATH)
        if units.empty:
            return IDAHO_BBOX
        if units.crs is None:
            units = units.set_crs("EPSG:4326", allow_override=True)
        units = units.to_crs("EPSG:4326")
        geom = units.geometry.union_all()
        minx, miny, maxx, maxy = geom.bounds
        buf = 0.1
        return (minx - buf, miny - buf, maxx + buf, maxy + buf)
    except Exception as e:
        print(f"  ⚠️ bbox from hunt_units failed: {e} — using Idaho fallback.")
        return IDAHO_BBOX


def _arcgis_get_json(url: str, params: dict, label: str) -> dict:
    r = requests.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"{label} ArcGIS error: {data['error']}")
    return data


def _probe_fields(url: str, label: str) -> set[str]:
    """
    Fetch 1 feature (attributes only) to determine field names available.
    """
    params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
        "resultRecordCount": 1,
    }
    try:
        data = _arcgis_get_json(url, params, label)
        feats = data.get("features", []) or []
        if not feats:
            return set()
        attrs = feats[0].get("attributes") or {}
        return set(attrs.keys())
    except Exception:
        return set()


def _where_last_5_years(url: str, label: str, year_fields: list[str], date_fields: list[str] | None = None) -> str:
    """
    Build a best-effort ArcGIS SQL where clause restricting to last 5 years.
    Prefers numeric year fields; falls back to date fields if present.
    """
    now_year = datetime.now().year
    cutoff_year = now_year - 4  # inclusive 5-year window

    fields = _probe_fields(url, f"{label} probe")
    if not fields:
        return "1=1"

    for yf in year_fields:
        if yf in fields:
            return f"{yf} >= {cutoff_year}"

    if date_fields:
        cutoff_date = f"{cutoff_year}-01-01"
        for df in date_fields:
            if df in fields:
                # Many ArcGIS services accept DATE 'YYYY-MM-DD'
                return f"{df} >= DATE '{cutoff_date}'"

    return "1=1"


def _paginate_geojson(url: str, base_params: dict, label: str) -> list[dict]:
    features: list[dict] = []
    offset = 0

    while True:
        params = {**base_params, "resultOffset": offset, "resultRecordCount": PAGE_SIZE}
        data = _arcgis_get_json(url, params, label)
        batch = data.get("features", []) or []
        features.extend(batch)
        print(f"  {label}: +{len(batch)} (total {len(features)})")

        if not data.get("exceededTransferLimit") and len(batch) < PAGE_SIZE:
            break
        if len(batch) < PAGE_SIZE:
            break

        offset += PAGE_SIZE

    return features


def _features_to_gdf(features: list[dict]) -> gpd.GeoDataFrame:
    if not features:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    return gdf


def fetch_fires(bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    minx, miny, maxx, maxy = bbox
    bbox_str = f"{minx},{miny},{maxx},{maxy}"

    where = _where_last_5_years(FIRE_URL, "Fires", FIRE_YEAR_FIELDS)
    print(f"  Fires WHERE: {where}")

    params = {
        "where": where,
        "outFields": "*",
        "returnGeometry": "true",
        "f": "geojson",
        "outSR": "4326",
        "geometry": bbox_str,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
    }

    feats = _paginate_geojson(FIRE_URL, params, "Fires (last 5 yrs)")
    return _features_to_gdf(feats)


def fetch_harvest(bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    minx, miny, maxx, maxy = bbox
    bbox_str = f"{minx},{miny},{maxx},{maxy}"

    where = _where_last_5_years(HARVEST_URL, "Harvest", HARVEST_YEAR_FIELDS, HARVEST_DATE_FIELDS)
    print(f"  Harvest WHERE: {where}")

    params = {
        "where": where,
        "outFields": "*",
        "returnGeometry": "true",
        "f": "geojson",
        "outSR": "4326",
        "geometry": bbox_str,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
    }

    feats = _paginate_geojson(HARVEST_URL, params, "Harvest (last 5 yrs)")
    return _features_to_gdf(feats)


def _write_empty(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": []}))


def save_gdf(gdf: gpd.GeoDataFrame, path: Path, label: str) -> None:
    if gdf is None or gdf.empty:
        print(f"⚠️  No {label} features. Writing empty output.")
        _write_empty(path)
        return

    gdf = gdf.copy()

    # Ensure 4326
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    else:
        gdf = gdf.to_crs("EPSG:4326")

    # Clean + simplify
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    gdf["geometry"] = gdf.geometry.simplify(0.0005, preserve_topology=True)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()

    # Clip to master Turkey GMU boundary
    gdf = clip_to_master_gmu(gdf, geom_type="polygon")

    # Make attribute values JSON-safe (drop columns that refuse)
    for col in list(gdf.columns):
        if col == "geometry":
            continue
        try:
            gdf[col] = gdf[col].where(pd.notnull(gdf[col]), None)
        except Exception:
            gdf = gdf.drop(columns=[col])

    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, driver="GeoJSON")
    print(f"✅ Wrote {len(gdf)} {label} → {path}")


def main() -> None:
    print("=" * 60)
    print("  Fetch Disturbance (Fires + Timber Harvest) — last 5 years")
    print("=" * 60)

    bbox = _get_idaho_bbox()
    print(f"Using bbox: {bbox}")

    # Fires
    print("\n── Fires ────────────────────────────────────────────────────────────")
    try:
        fires = fetch_fires(bbox)
        save_gdf(fires, BURNED_PATH, "fire perimeters")
    except Exception as e:
        print(f"  ✗ Fires failed: {e}")
        _write_empty(BURNED_PATH)
        print("  → Wrote empty burned_areas.geojson")

    # Timber harvest
    print("\n── Timber Harvest ────────────────────────────────────────────────────")
    try:
        harvest = fetch_harvest(bbox)
        save_gdf(harvest, LOGGING_PATH, "timber harvest areas")
    except Exception as e:
        print(f"  ✗ Harvest failed: {e}")
        _write_empty(LOGGING_PATH)
        print("  → Wrote empty logging_areas.geojson")

    print("\n✅ Disturbance pipeline complete.")


if __name__ == "__main__":
    main()