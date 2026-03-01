"""
Fetch IDFG "Closed to Turkey Hunting" areas.

Source (ArcGIS MapServer):
  https://gisportal-idfg.idaho.gov/hosting/rest/services/Hunting/MapServer/7

Output:
  pipelines/data/processed/closed_areas.geojson
"""

from __future__ import annotations

import json
import requests
import geopandas as gpd
from pathlib import Path
from shapely.geometry import shape
from _gmu_clip import clip_to_master_gmu

PAGE_SIZE = 500

_ROOT    = Path(__file__).resolve().parent.parent
OUT_PATH = _ROOT / "pipelines" / "data" / "processed" / "closed_areas.geojson"

BASE_URL = "https://gisportal-idfg.idaho.gov/hosting/rest/services/Hunting/MapServer/7/query"

FIELD_MAP = {
    "area_name": [
        "name", "Name", "NAME", "area_name", "AreaName", "AREA_NAME",
        "unit_name", "UnitName", "UNIT_NAME", "closure_name", "ClosureName",
        "CLOSURE_NAME", "label", "Label", "LABEL",
    ],
    "closure_type": [
        "type", "Type", "TYPE", "closure_type", "ClosureType", "CLOSURE_TYPE",
        "restriction", "Restriction", "RESTRICTION", "category", "Category",
    ],
    "season": [
        "season", "Season", "SEASON", "season_type", "SeasonType", "SEASON_TYPE",
        "open_date", "OpenDate", "close_date", "CloseDate",
    ],
    "notes": [
        "notes", "Notes", "NOTES", "description", "Description", "DESCRIPTION",
        "regulation", "Regulation", "comments", "Comments",
    ],
}


def _pick(props: dict, candidates: list[str]):
    for c in candidates:
        if c in props and props[c] not in (None, "", " "):
            return props[c]
    return None


def fetch_all() -> list[dict]:
    features = []
    offset   = 0

    while True:
        params = {
            "where":              "1=1",
            "outFields":          "*",
            "returnGeometry":     "true",
            "f":                  "geojson",
            "outSR":              "4326",
            "resultRecordCount":  PAGE_SIZE,
            "resultOffset":       offset,
        }
        r = requests.get(BASE_URL, params=params, timeout=120)
        r.raise_for_status()
        data = r.json()

        if "error" in data:
            raise RuntimeError(f"ArcGIS error: {data['error']}")

        batch = data.get("features", []) or []
        features.extend(batch)
        print(f"  fetched {len(batch)} features (offset={offset})")

        if not data.get("exceededTransferLimit") or len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return features


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("Fetching IDFG closed turkey hunting areas...")
    raw = fetch_all()
    print(f"  Total raw features: {len(raw)}")

    if not raw:
        print("⚠️  No features returned. Writing empty FeatureCollection.")
        OUT_PATH.write_text(json.dumps({"type": "FeatureCollection", "features": []}))
        return

    records = []
    for f in raw:
        geom = f.get("geometry")
        if not geom:
            continue
        try:
            if isinstance(geom, dict):
                geom = shape(geom)
        except Exception as e:
            print(f"  ⚠️ Skipping invalid geometry: {e}")
            continue
        records.append({"geometry": geom, **(f.get("properties") or {})})

    if not records:
        print("⚠️  No valid geometries. Writing empty FeatureCollection.")
        OUT_PATH.write_text(json.dumps({"type": "FeatureCollection", "features": []}))
        return

    geoms = [r.pop("geometry") for r in records]
    gdf   = gpd.GeoDataFrame(records, geometry=geoms, crs="EPSG:4326")

    # Standardize fields
    gdf["area_name"]    = gdf.apply(lambda row: _pick(dict(row), FIELD_MAP["area_name"])    or "Closed Area",              axis=1)
    gdf["closure_type"] = gdf.apply(lambda row: _pick(dict(row), FIELD_MAP["closure_type"]) or "Turkey Hunting Closure",    axis=1)
    gdf["season"]       = gdf.apply(lambda row: _pick(dict(row), FIELD_MAP["season"])       or "N/A",                      axis=1)
    gdf["notes"]        = gdf.apply(lambda row: _pick(dict(row), FIELD_MAP["notes"])        or "",                         axis=1)

    # Simplify and clean geometries
    gdf.geometry = gdf.geometry.simplify(0.0005, preserve_topology=True)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)

    gdf = clip_to_master_gmu(gdf, geom_type="polygon")
    gdf.to_file(OUT_PATH, driver="GeoJSON")
    print(f"\n✅ Wrote {len(gdf)} closed areas → {OUT_PATH}")
    print("Sample columns:", list(gdf.columns)[:20])


if __name__ == "__main__":
    main()
