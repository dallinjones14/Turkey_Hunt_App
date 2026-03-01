"""
Merge NLCD polygons from two separate source files into single output features,
clipped to the master turkey GMU boundary.

Inputs:
  pipelines/data/raw/Dec_Forest_NLCD.geojson   (DN = 41, Deciduous Forest)
  pipelines/data/raw/Cropland_NLCD.geojson     (DN = 82, Cultivated Crops)

Outputs:
  pipelines/data/processed/DeciduousForest.geojson  — clipped, EPSG:4326
  pipelines/data/processed/CropLand.geojson         — clipped, EPSG:4326

Result:
  Exactly ONE merged polygon per output file, clipped to master GMU boundary.
  Output CRS = EPSG:4326
"""

from __future__ import annotations

from pathlib import Path
import json

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union
from _gmu_clip import clip_to_master_gmu


ROOT      = Path(__file__).resolve().parent.parent
RAW       = ROOT / "pipelines" / "data" / "raw"
PROCESSED = ROOT / "pipelines" / "data" / "processed"

# Each entry: (input_file, expected_DN, land_cover_label, output_file)
SOURCES = [
    (RAW / "Dec_Forest_NLCD.geojson", 41, "Deciduous Forest", PROCESSED / "DeciduousForest.geojson"),
    (RAW / "Cropland_NLCD.geojson",   82, "Cultivated Crops",  PROCESSED / "CropLand.geojson"),
]

CRS_OUT = "EPSG:4326"


def write_empty(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": []}))


def process(in_path: Path, dn_value: int, name: str, out_path: Path) -> None:
    print(f"\n── {name} (DN={dn_value}) ──────────────────────────")

    if not in_path.exists():
        print(f"  ⚠️  Input not found: {in_path.name} — writing empty output.")
        write_empty(out_path)
        return

    print(f"  Reading: {in_path.name}")
    gdf = gpd.read_file(in_path)
    print(f"  Features loaded: {len(gdf)}")

    if gdf.empty:
        print("  ⚠️  File is empty — writing empty output.")
        write_empty(out_path)
        return

    # Normalize DN column name (case-insensitive)
    dn_col = next((c for c in gdf.columns if c.upper() == "DN"), None)
    if dn_col is None:
        print(f"  ❌ No 'DN' column found. Columns: {list(gdf.columns)}")
        write_empty(out_path)
        return
    if dn_col != "DN":
        gdf = gdf.rename(columns={dn_col: "DN"})

    # Coerce to int so comparisons are reliable regardless of source type
    gdf["DN"] = pd.to_numeric(gdf["DN"], errors="coerce").astype("Int64")

    # Filter to target DN value
    sub = gdf[gdf["DN"] == dn_value].copy()
    sub = sub[sub.geometry.notna() & ~sub.geometry.is_empty]
    print(f"  Features matching DN={dn_value}: {len(sub)}")

    if sub.empty:
        print(f"  ⚠️  No valid features for DN={dn_value} — writing empty output.")
        write_empty(out_path)
        return

    # Ensure CRS
    if sub.crs is None:
        sub = sub.set_crs(CRS_OUT, allow_override=True)
    sub = sub.to_crs(CRS_OUT)

    print(f"  Merging {len(sub)} polygons…")
    try:
        merged_geom = unary_union(sub.geometry)
    except Exception as exc:
        print(f"  ❌ unary_union failed: {exc}")
        write_empty(out_path)
        return

    result = gpd.GeoDataFrame(
        [{"DN": int(dn_value), "LandCoverType": name, "geometry": merged_geom}],
        geometry="geometry",
        crs=CRS_OUT,
    )

    print(f"  Clipping to master GMU boundary…")
    result = clip_to_master_gmu(result, geom_type="polygon")
    result = result.to_crs(CRS_OUT)

    if result.empty:
        print(f"  ⚠️  Clip returned empty result — writing empty output.")
        write_empty(out_path)
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_file(out_path, driver="GeoJSON")
    print(f"  ✅ Wrote {len(result)} feature(s) → {out_path.name}")


def main() -> None:
    print("=" * 60)
    print("  Extracting NLCD Land Cover Classes")
    print("=" * 60)

    for in_path, dn_value, name, out_path in SOURCES:
        process(in_path, dn_value, name, out_path)

    print("\n✅ All done.")


if __name__ == "__main__":
    main()
