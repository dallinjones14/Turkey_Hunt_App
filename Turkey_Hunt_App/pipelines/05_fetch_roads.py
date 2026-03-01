"""
Fetch USFS MVUM motorized roads/trails + BLM public motorized roads for Idaho turkey GMUs,
merge them into ONE output called Motorized Roads, and also export USFS trails separately.
Also fetches Boise/Ada County Parks & Trails open data and merges into the trails output.

Outputs:
  pipelines/data/processed/motorized_roads.geojson   (USFS MVUM Motorized + BLM Motorized Roads merged)
  pipelines/data/processed/mvum_trails.geojson       (USFS Trails + Boise Parks & Trails merged)

Schema (for BOTH outputs):
  route_name
  surface_type
  seasonal_closure
  jurisdiction
  mvum_class
  allowed_use
  source
  geometry

Notes:
  - Uses bbox from hunt_units.geojson (EPSG:4326).
  - Uses ArcGIS REST paging via exceededTransferLimit + resultOffset.
  - Standardizes schema across USFS + BLM before merging.
  - Clips to master GMU boundary via clip_to_master_gmu(gdf, geom_type="line").
"""

from __future__ import annotations

import requests
import geopandas as gpd
import pandas as pd
from pathlib import Path
from _gmu_clip import clip_to_master_gmu

PAGE_SIZE = 2000
TIMEOUT = 120

_ROOT = Path(__file__).resolve().parent.parent
HUNT_UNITS_PATH = _ROOT / "pipelines" / "data" / "processed" / "master_turkey_gmu.geojson"

OUT_MOTORIZED_ROADS = _ROOT / "pipelines" / "data" / "processed" / "motorized_roads.geojson"
OUT_TRAILS = _ROOT / "pipelines" / "data" / "processed" / "mvum_trails.geojson"

# USFS MVUM
MVUM_MOTORIZED_URL = "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_MVUM_02/MapServer/1/query"
MVUM_TRAILS_URL = "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_MVUM_02/MapServer/2/query"

# BLM Public Motorized Roads
BLM_ROADS_URL = (
    "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/"
    "BLM_Natl_GTLF_Public_Motorized_Roads/FeatureServer/3/query"
)

# Boise / Ada County Parks & Trails open data
BOISE_TRAILS_URL = (
    "https://services1.arcgis.com/WHM6qC35aMtyAAlN/arcgis/rest/services/"
    "Boise_Parks_Trails_Open_Data/FeatureServer/0/query"
)

KEEP_FIELDS = [
    "route_name",
    "final_class",
    "surface_type",
    "seasonal_closure",
    "jurisdiction",
    "mvum_class",
    "allowed_use",
    "source",
    "geometry",
]


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_empty_geojson(path: Path) -> None:
    ensure_parent_dir(path)
    path.write_text('{"type":"FeatureCollection","features":[]}')


def fetch_bbox(url: str, bbox: tuple[float, float, float, float], *, page_size: int = PAGE_SIZE) -> gpd.GeoDataFrame:
    """
    Fetch all features intersecting an envelope bbox from an ArcGIS REST /query endpoint.
    Uses paging via resultOffset + exceededTransferLimit.
    Requests f=geojson for easy GeoDataFrame creation.
    """
    minx, miny, maxx, maxy = bbox

    base_params = {
        "where": "1=1",
        "geometry": f"{minx},{miny},{maxx},{maxy}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
        "resultRecordCount": page_size,
    }

    features: list[dict] = []
    offset = 0

    while True:
        params = {**base_params, "resultOffset": offset}
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            raise RuntimeError(f"ArcGIS error from {url}: {data['error']}")

        batch = data.get("features", []) or []
        features.extend(batch)

        if not data.get("exceededTransferLimit") or len(batch) < page_size:
            break
        offset += page_size

    if not features:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")


def standardize_line_fields(gdf: gpd.GeoDataFrame, source_label: str) -> gpd.GeoDataFrame:
    """
    Best-effort normalization across USFS MVUM and BLM motorized roads.
    Ensures KEEP_FIELDS exist and are reasonably populated.
    """
    gdf = gdf.copy()

    rename_map = {
        # name-ish
        "NAME": "route_name",
        "Name": "route_name",
        "ROUTE_NAME": "route_name",
        "TRAIL_NAME": "route_name",
        "ROAD_NAME": "route_name",
        "RTE_NAME": "route_name",
        "RD_NAME": "route_name",
        "ROUTE": "route_name",

        # surface-ish
        "SURFACE_TYPE": "surface_type",
        "SurfaceType": "surface_type",
        "SURFACE": "surface_type",
        "RD_SURFACE": "surface_type",

        # seasonal closure-ish
        "SEASONAL_CLOSURE": "seasonal_closure",
        "SeasonalClosure": "seasonal_closure",
        "SEAS_CLSR": "seasonal_closure",
        "SEASONAL": "seasonal_closure",

        # jurisdiction-ish
        "JURISDICTION": "jurisdiction",
        "Jurisdiction": "jurisdiction",
        "ADMIN_AGENCY": "jurisdiction",
        "MANAGING_AGENCY": "jurisdiction",
        "OWNER": "jurisdiction",

        # mvum class-ish
        "MVUM_CLASS": "mvum_class",
        "MVUMClass": "mvum_class",
        "ROAD_CLASS": "mvum_class",
        "ROUTE_CLASS": "mvum_class",

        # final road class / planned transport mode
        "PLAN_MODE_TRNSPRT": "final_class",
        "PLANMODE": "final_class",
        "TRANSPORT_CLASS": "final_class",

        # allowed use-ish
        "ALLOWED_USE": "allowed_use",
        "AllowedUse": "allowed_use",
        "USE_TYPE": "allowed_use",
        "ACCESS": "allowed_use",
        "MOTOR_USE": "allowed_use",
        "VEHICLE_TYPE": "allowed_use",
    }

    for k, v in rename_map.items():
        if k in gdf.columns and v not in gdf.columns:
            gdf = gdf.rename(columns={k: v})

    # Ensure schema fields exist
    for col in KEEP_FIELDS:
        if col == "geometry":
            continue
        if col not in gdf.columns:
            gdf[col] = None

    # Derive final_class for USFS sources (BLM gets it directly from PLAN_MODE_TRNSPRT)
    if source_label.startswith("USFS"):
        # Prefer mvum_class; fall back to surface_type
        def _usfs_class(row):
            mc = str(row.get("mvum_class", "") or "").strip()
            st = str(row.get("surface_type", "") or "").strip()
            if mc and mc.upper() not in ("NONE", "NAN", ""):
                return mc
            if st and st.upper() not in ("NONE", "NAN", ""):
                return st
            return None
        empty_mask = gdf["final_class"].isna() | (gdf["final_class"].astype(str).str.upper().isin({"NONE", "NAN", ""}))
        if empty_mask.any():
            gdf.loc[empty_mask, "final_class"] = gdf[empty_mask].apply(_usfs_class, axis=1)

    # Fill jurisdiction defaults
    if source_label.startswith("USFS"):
        gdf["jurisdiction"] = gdf["jurisdiction"].where(
            gdf["jurisdiction"].astype(str).str.strip().ne(""),
            "USFS",
        )
    elif source_label.startswith("BLM"):
        gdf["jurisdiction"] = gdf["jurisdiction"].where(
            gdf["jurisdiction"].astype(str).str.strip().ne(""),
            "BLM",
        )

    gdf["source"] = source_label
    return gdf


def build_bbox_from_hunt_units() -> tuple[float, float, float, float]:
    if not HUNT_UNITS_PATH.exists():
        raise FileNotFoundError(f"Missing hunt units: {HUNT_UNITS_PATH}")

    units = gpd.read_file(HUNT_UNITS_PATH)
    if units.empty:
        raise RuntimeError("hunt_units.geojson is empty; cannot compute bbox.")
    if units.crs is None:
        raise ValueError("hunt_units.geojson has no CRS. Export with CRS or set it before running.")

    units_4326 = units.to_crs("EPSG:4326")
    return tuple(units_4326.total_bounds)


def fetch_process(url: str, source_label: str, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    gdf = fetch_bbox(url, bbox, page_size=PAGE_SIZE)
    if gdf.empty:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    else:
        gdf = gdf.to_crs("EPSG:4326")

    gdf = standardize_line_fields(gdf, source_label)

    # Clip to master GMU boundary
    gdf = clip_to_master_gmu(gdf, geom_type="line")

    # Simplify slightly (degrees)
    gdf["geometry"] = gdf.geometry.simplify(0.0005, preserve_topology=True)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()

    # Enforce schema
    for col in KEEP_FIELDS:
        if col not in gdf.columns:
            gdf[col] = None
    return gdf[KEEP_FIELDS].copy()


def fetch_boise_trails() -> gpd.GeoDataFrame:
    """
    Fetch Boise / Ada County Parks & Trails from the open data portal.
    No bbox filter needed — the dataset is small so we fetch all, then clip to GMU.

    Field mapping:
      TrailName / SystemName → route_name
      TrlSurface             → surface_type, final_class (for road-class symbolization)
      AgencyName             → jurisdiction
      Accessible + Ebike     → allowed_use
      source                 = "Boise Parks & Trails"
    """
    params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
        "resultRecordCount": 2000,
    }
    features: list[dict] = []
    offset = 0
    while True:
        resp = requests.get(BOISE_TRAILS_URL, params={**params, "resultOffset": offset}, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"ArcGIS error: {data['error']}")
        batch = data.get("features", []) or []
        features.extend(batch)
        if not data.get("exceededTransferLimit") or len(batch) < 2000:
            break
        offset += 2000

    if not features:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    if gdf.empty:
        return gdf

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    else:
        gdf = gdf.to_crs("EPSG:4326")

    # ── Field mapping ──────────────────────────────────────────────────────────
    def _col(name: str) -> pd.Series:
        """Return column if present, else an empty string series."""
        return gdf[name] if name in gdf.columns else pd.Series([""] * len(gdf), index=gdf.index)

    def _clean(s) -> str | None:
        v = str(s).strip()
        return None if v in ("", "None", "nan", "null", "<NA>") else v

    # route_name: prefer TrailName, fall back to SystemName
    trail_name  = _col("TrailName").apply(_clean)
    system_name = _col("SystemName").apply(_clean)
    gdf["route_name"] = trail_name.where(trail_name.notna(), system_name)

    gdf["surface_type"]     = _col("TrlSurface").apply(_clean)
    gdf["final_class"]      = gdf["surface_type"]   # surface drives symbolization
    gdf["jurisdiction"]     = _col("AgencyName").apply(_clean)
    gdf["seasonal_closure"] = None                  # TrailStatus is open/null, no seasonal detail
    gdf["mvum_class"]       = None

    # allowed_use: combine accessibility and e-bike flags where present
    accessible = _col("Accessible")
    ebike      = _col("Ebike")
    def _use(acc, eb) -> str:
        parts = ["Non-Motorized"]
        a, e = _clean(acc), _clean(eb)
        if a:
            parts.append(a)
        if e:
            parts.append(f"E-Bike: {e}")
        return " | ".join(parts)
    gdf["allowed_use"] = [_use(a, e) for a, e in zip(accessible, ebike)]
    gdf["source"]      = "Boise Parks & Trails"

    # ── Clip to master GMU boundary, simplify, enforce schema ─────────────────
    gdf = clip_to_master_gmu(gdf, geom_type="line")
    if gdf.empty:
        return gdf

    gdf["geometry"] = gdf.geometry.simplify(0.0005, preserve_topology=True)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()

    for col in KEEP_FIELDS:
        if col not in gdf.columns:
            gdf[col] = None
    return gdf[KEEP_FIELDS].copy()


def main() -> None:
    print("=" * 60)
    print("  Fetching Motorized Roads (USFS MVUM Motorized + BLM Motorized Roads)")
    print("=" * 60)

    bbox = build_bbox_from_hunt_units()
    print(f"Using bbox (EPSG:4326): {bbox}")

    # 1) Motorized Roads = USFS MVUM Motorized + BLM Roads
    frames = []

    print("\n── USFS MVUM Motorized ─────────────────────────────────────────────")
    try:
        usfs_motorized = fetch_process(MVUM_MOTORIZED_URL, "USFS MVUM Motorized", bbox)
        print(f"  +{len(usfs_motorized)} features")
        if not usfs_motorized.empty:
            frames.append(usfs_motorized)
    except Exception as e:
        print(f"  ⚠️ USFS MVUM Motorized failed: {e}")

    print("\n── BLM Public Motorized Roads ───────────────────────────────────────")
    try:
        blm_roads = fetch_process(BLM_ROADS_URL, "BLM Motorized Roads", bbox)
        print(f"  +{len(blm_roads)} features")
        if not blm_roads.empty:
            frames.append(blm_roads)
    except Exception as e:
        print(f"  ⚠️ BLM Motorized Roads failed: {e}")

    if frames:
        motorized = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")
        ensure_parent_dir(OUT_MOTORIZED_ROADS)
        motorized.to_file(OUT_MOTORIZED_ROADS, driver="GeoJSON")
        print(f"\n✅ Saved {len(motorized)} features → {OUT_MOTORIZED_ROADS.name}")
    else:
        print("\n⚠️ No motorized roads fetched; writing empty GeoJSON.")
        write_empty_geojson(OUT_MOTORIZED_ROADS)

    # 2) Trails = USFS MVUM Trails + Boise Parks & Trails
    print("\n" + "=" * 60)
    print("  Fetching Trails (USFS MVUM + Boise Parks & Trails)")
    print("=" * 60)
    trail_frames = []

    print("\n── USFS MVUM Trails ─────────────────────────────────────────────────")
    try:
        usfs_trails = fetch_process(MVUM_TRAILS_URL, "USFS MVUM Trails", bbox)
        if not usfs_trails.empty:
            trail_frames.append(usfs_trails)
            print(f"  +{len(usfs_trails)} features")
        else:
            print("  0 features within GMU bbox")
    except Exception as e:
        print(f"  ⚠️ USFS MVUM Trails failed: {e}")

    print("\n── Boise Parks & Trails ─────────────────────────────────────────────")
    try:
        boise_trails = fetch_boise_trails()
        if not boise_trails.empty:
            trail_frames.append(boise_trails)
            print(f"  +{len(boise_trails)} features within GMU boundary")
        else:
            print("  0 features within GMU boundary (Boise trails may not overlap GMU)")
    except Exception as e:
        print(f"  ⚠️ Boise Parks & Trails failed: {e}")

    if trail_frames:
        trails = gpd.GeoDataFrame(pd.concat(trail_frames, ignore_index=True), crs="EPSG:4326")
        ensure_parent_dir(OUT_TRAILS)
        trails.to_file(OUT_TRAILS, driver="GeoJSON")
        print(f"\n✅ Saved {len(trails)} total trail features → {OUT_TRAILS.name}")
        for src, grp in trails.groupby("source"):
            print(f"     {src}: {len(grp)} features")
    else:
        print("\n⚠️ No trails fetched; writing empty GeoJSON.")
        write_empty_geojson(OUT_TRAILS)
        print(f"  → Wrote empty {OUT_TRAILS.name}")

    print("\n✅ Roads/trails pipeline complete.")


if __name__ == "__main__":
    main()