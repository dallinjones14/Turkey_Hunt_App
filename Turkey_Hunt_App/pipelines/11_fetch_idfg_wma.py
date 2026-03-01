"""
Fetch IDFG Wildlife Management Area (WMA) boundaries.

Source: https://services.arcgis.com/FjJI5xHF2dUPVrgK/arcgis/rest/services/WildlifeManagementAreas/FeatureServer/0/query

Fields:
  WMAID  — WMA identifier number
  Name   — WMA name
  Acres  — area in acres

Output: pipelines/data/processed/idfg_wma.geojson
"""
from __future__ import annotations

import json
import requests
import geopandas as gpd
from pathlib import Path
from _gmu_clip import clip_to_master_gmu

_ROOT    = Path(__file__).resolve().parent.parent
OUT_PATH = _ROOT / "pipelines" / "data" / "processed" / "idfg_wma.geojson"

BASE_URL  = (
    "https://services.arcgis.com/FjJI5xHF2dUPVrgK/arcgis/rest/services/"
    "WildlifeManagementAreas/FeatureServer/0/query"
)
PAGE_SIZE = 1000


def fetch_all() -> gpd.GeoDataFrame:
    """Paginate through the FeatureServer and return a single GeoDataFrame."""
    features: list[dict] = []
    offset = 0

    base_params = {
        "where":             "1=1",
        "outFields":         "WMAID,Name,Acres",
        "returnGeometry":    "true",
        "outSR":             "4326",
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
    print("  Fetching IDFG Wildlife Management Areas (WMA)")
    print("=" * 60)

    gdf = fetch_all()
    print(f"\n  Total fetched: {len(gdf)} polygons")

    if gdf.empty:
        print("⚠️  No features returned. Writing empty FeatureCollection.")
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
        if low == "wmaid":
            rename[col] = "wma_id"
        elif low == "name":
            rename[col] = "wma_name"
        elif low == "acres":
            rename[col] = "acres"
    if rename:
        gdf = gdf.rename(columns=rename)

    # Ensure required columns exist
    for col in ["wma_id", "wma_name", "acres"]:
        if col not in gdf.columns:
            gdf[col] = None

    # Keep valid geometries only
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()

    # Simplify to reduce file size (~50 m tolerance in degrees)
    gdf["geometry"] = gdf.geometry.simplify(0.0005, preserve_topology=True)
    gdf = gdf[~gdf.geometry.is_empty].reset_index(drop=True)

    # Clip to master Turkey GMU boundary
    gdf = clip_to_master_gmu(gdf, geom_type="polygon")

    # Keep only columns needed by the map
    keep = ["wma_id", "wma_name", "acres", "geometry"]
    gdf = gdf[[c for c in keep if c in gdf.columns]]

    gdf.to_file(OUT_PATH, driver="GeoJSON")
    print(f"\n✅ Saved {len(gdf)} WMA polygons → {OUT_PATH}")

    if "wma_name" in gdf.columns:
        print("\nWMA names found:")
        print(gdf["wma_name"].dropna().tolist())


if __name__ == "__main__":
    main()
