"""
Fetch Idaho Surface Management Agency (SMA) land ownership boundaries.

Source: https://gis1.idl.idaho.gov/arcgis/rest/services/Portal/Idaho_Surface_Management_Agency/FeatureServer/0/query

Fields used:
  AGNCY_NAME  — abbreviated agency name (BLM, USFS, NPS, IDL, IDFG, FWS, BOR, DOD, BIA …)
  MGMT_AGNCY  — management agency code
  GIS_ACRES   — polygon area in acres

Symbolized on the map by ownership agency.
Output: pipelines/data/processed/public_access.geojson
"""
from __future__ import annotations

import requests
import geopandas as gpd
from pathlib import Path
from _gmu_clip import clip_to_master_gmu

_ROOT    = Path(__file__).resolve().parent.parent
OUT_PATH = _ROOT / "pipelines" / "data" / "processed" / "public_access.geojson"

BASE_URL  = (
    "https://gis1.idl.idaho.gov/arcgis/rest/services/Portal/"
    "Idaho_Surface_Management_Agency/FeatureServer/0/query"
)
PAGE_SIZE = 2000   # max record count for this service

# Canonical agency labels (AGNCY_NAME raw value → display name used in map)
AGENCY_NORM: dict[str, str] = {
    "BLM":   "BLM",
    "USFS":  "USFS",
    "FS":    "USFS",
    "NPS":   "NPS",
    "FWS":   "FWS",
    "USFWS": "FWS",
    "IDL":   "IDL",
    "IDFG":  "IDFG",
    "BOR":   "BOR",
    "USBR":  "BOR",
    "DOD":   "DOD",
    "BIA":   "BIA",
    "OTHER": "Other",
}


def _normalize_agency(raw: str | None) -> str:
    if not raw:
        return "Other"
    return AGENCY_NORM.get(str(raw).strip().upper(), str(raw).strip())


def fetch_all() -> gpd.GeoDataFrame:
    """Paginate through the FeatureServer and return a single GeoDataFrame."""
    features: list[dict] = []
    offset = 0

    base_params = {
        "where":             "1=1",
        "outFields":         "AGNCY_NAME,MGMT_AGNCY,GIS_ACRES",
        "returnGeometry":    "true",
        "outSR":             "4326",   # request in WGS84 so no reprojection needed
        "f":                 "geojson",
        "resultRecordCount": PAGE_SIZE,
    }

    while True:
        params = {**base_params, "resultOffset": offset}
        print(f"  GET offset={offset} …")
        try:
            resp = requests.get(BASE_URL, params=params, timeout=120)
            resp.raise_for_status()
        except Exception as exc:
            print(f"\n❌ Fetch failed at offset={offset}: {exc}")
            break

        data = resp.json()

        if "error" in data:
            print(f"\n❌ ArcGIS error: {data['error']}")
            break

        batch = data.get("features", []) or []
        features.extend(batch)
        print(f"    {len(batch)} features (running total: {len(features)})")

        if not data.get("exceededTransferLimit") or len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    if not features:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  Fetching Idaho Surface Management Agency (Public Access)")
    print("=" * 60)

    gdf = fetch_all()
    print(f"\n  Total fetched: {len(gdf)} polygons")

    if gdf.empty:
        print("⚠️  No features returned. Writing empty FeatureCollection.")
        import json
        OUT_PATH.write_text(json.dumps({"type": "FeatureCollection", "features": []}))
        return

    # Ensure EPSG:4326
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    else:
        gdf = gdf.to_crs("EPSG:4326")

    # Normalize column names (case may vary)
    rename = {}
    for col in list(gdf.columns):
        low = col.lower()
        if low == "agncy_name":
            rename[col] = "agncy_name"
        elif low == "mgmt_agncy":
            rename[col] = "mgmt_agncy"
        elif low == "gis_acres":
            rename[col] = "gis_acres"
    if rename:
        gdf = gdf.rename(columns=rename)

    # Add standardized agency column used for map symbology
    raw_col = "agncy_name" if "agncy_name" in gdf.columns else "mgmt_agncy"
    if raw_col in gdf.columns:
        gdf["agency"] = gdf[raw_col].apply(_normalize_agency)
    else:
        gdf["agency"] = "Other"

    # Ensure acres column exists
    if "gis_acres" not in gdf.columns:
        gdf["gis_acres"] = None

    # Keep valid geometries only
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()

    # Simplify to reduce file size (~50 m tolerance in degrees)
    gdf["geometry"] = gdf.geometry.simplify(0.0005, preserve_topology=True)
    gdf = gdf[~gdf.geometry.is_empty].reset_index(drop=True)

    # Clip to master Turkey GMU boundary
    gdf = clip_to_master_gmu(gdf, geom_type="polygon")

    # Keep only columns needed by the map
    keep = ["agency", "agncy_name", "mgmt_agncy", "gis_acres", "geometry"]
    gdf = gdf[[c for c in keep if c in gdf.columns]]

    gdf.to_file(OUT_PATH, driver="GeoJSON")
    print(f"\n✅ Saved {len(gdf)} SMA polygons → {OUT_PATH}")

    if "agency" in gdf.columns:
        print("\nAgency breakdown:")
        print(gdf["agency"].value_counts().to_string())


if __name__ == "__main__":
    main()
