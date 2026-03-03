"""
Clip the NIC IMS snow-cover raster to the master Turkey GMU boundary,
then vectorize snow pixels (value == 4) to a GeoJSON polygon layer.

Adds: edge softening for blocky raster-derived polygons via buffer/simplify/buffer.

NIC IMS pixel values:
  1 = open water
  2 = land (no snow)
  3 = sea ice
  4 = snow-covered land   ← we want this

Inputs:
  pipelines/data/raw/NIC.IMS_v3_20260227_1km.tif      (or any IMS GeoTIFF)
  pipelines/data/processed/master_turkey_gmu.geojson

Outputs:
  pipelines/data/processed/NIC.IMS_v3_20260227_1km_clipped_to_GMUs.tif  (intermediate)
  pipelines/data/processed/snow_cover.geojson
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.features import shapes
from shapely.geometry import shape
from shapely.ops import unary_union
from _gmu_clip import clip_to_master_gmu

# ── Paths ──────────────────────────────────────────────────────────────────────
_RASTER_DIR = Path(__file__).resolve().parent / "data" / "raw" / "Rasters"

def _find_tif() -> Path:
    """Return the newest (by modification time) IMS GeoTIFF in data/raw/Rasters/."""
    tifs = sorted(_RASTER_DIR.glob("*.tif"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not tifs:
        raise FileNotFoundError(
            f"No .tif files found in {_RASTER_DIR}\n"
            "Place the NIC IMS GeoTIFF there and re-run."
        )
    print(f"  Using raster: {tifs[0].name}")
    return tifs[0]

TIF_IN = _find_tif()

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "pipelines" / "data" / "processed"
MASTER_GMUS = PROCESSED / "master_turkey_gmu.geojson"

TIF_OUT = PROCESSED / (TIF_IN.stem + "_clipped_to_GMUs.tif")
SNOW_GEOJSON = PROCESSED / "snow_cover.geojson"

SNOW_VALUE = 4  # NIC IMS: snow-covered land

# Original simplify (degrees) – keep for final cleanup if you want
SIMPLIFY_DEG = 0.003  # ~300 m at Idaho latitudes

# NEW: soften raster stair-steps in meters (best done in projected CRS)
# For 1km pixels, start ~1500m. Increase for smoother, decrease for tighter edges.
SOFTEN_M = 1500.0
SOFTEN_SIMPLIFY_M = 250.0  # secondary simplification in meters during smoothing


# ── Step 1: clip raster to GMU footprint ──────────────────────────────────────
def clip_to_master_gmus(tif_in: Path, gmu_geojson: Path, tif_out: Path) -> None:
    if not tif_in.exists():
        raise FileNotFoundError(f"Raster not found: {tif_in}")
    if not gmu_geojson.exists():
        raise FileNotFoundError(f"GMU GeoJSON not found: {gmu_geojson}")

    print(f"Reading GMUs: {gmu_geojson}")
    gmus = gpd.read_file(gmu_geojson)
    gmus = gmus[gmus.geometry.notna() & ~gmus.geometry.is_empty].copy()
    if gmus.empty:
        raise RuntimeError("GMU GeoJSON has no valid geometries.")

    print(f"Opening raster: {tif_in}")
    with rasterio.open(tif_in) as src:
        if src.crs is None:
            raise RuntimeError("Input raster has no CRS.")

        gmus_proj = gmus.to_crs(src.crs)
        union_geom = unary_union(gmus_proj.geometry)

        print("Masking / cropping raster to GMU footprint …")
        out_img, out_transform = mask(
            src, [union_geom], crop=True, nodata=src.nodata, filled=True
        )

        out_meta = src.meta.copy()
        out_meta.update(
            {
                "driver": "GTiff",
                "height": out_img.shape[1],
                "width": out_img.shape[2],
                "transform": out_transform,
                "compress": "deflate",
                "tiled": True,
                "blockxsize": 512,
                "blockysize": 512,
            }
        )

        tif_out.parent.mkdir(parents=True, exist_ok=True)
        print(f"Writing clipped raster: {tif_out}")
        with rasterio.open(tif_out, "w", **out_meta) as dst:
            dst.write(out_img)

    print("✅ Raster clip done.")


# ── NEW: soften edges of raster-derived polygons ───────────────────────────────
def soften_edges(gdf_4326: gpd.GeoDataFrame, *, buffer_m: float, simplify_m: float) -> gpd.GeoDataFrame:
    """
    Softens blocky edges by buffering out, simplifying, then buffering back in.
    Works in meters using EPSG:5070 (CONUS Albers).
    """
    if gdf_4326.empty:
        return gdf_4326

    work = gdf_4326.to_crs("EPSG:5070").copy()

    # buffer out -> simplify -> buffer back
    work["geometry"] = (
        work.geometry
        .buffer(buffer_m, join_style=1)                 # round joins
        .simplify(simplify_m, preserve_topology=True)   # remove stair-steps
        .buffer(-buffer_m, join_style=1)
    )

    work = work[work.geometry.notna() & ~work.geometry.is_empty].copy()
    return work.to_crs("EPSG:4326")


# ── Step 2: vectorize snow pixels → GeoJSON ───────────────────────────────────
def vectorize_snow(tif_clipped: Path, snow_geojson: Path) -> None:
    print(f"\nVectorizing snow pixels from: {tif_clipped}")
    with rasterio.open(tif_clipped) as src:
        data = src.read(1)
        transform = src.transform
        crs = src.crs

    snow_mask = data == SNOW_VALUE
    n_pixels = int(snow_mask.sum())
    print(f"  Snow pixels found: {n_pixels}")

    if n_pixels == 0:
        print("  ⚠️  No snow pixels in GMU area. Writing empty FeatureCollection.")
        snow_geojson.write_text('{"type":"FeatureCollection","features":[]}')
        return

    polys = [
        shape(geom)
        for geom, val in shapes(
            snow_mask.astype(np.uint8), mask=snow_mask, transform=transform
        )
        if val == 1
    ]
    print(f"  Raw polygons from vectorization: {len(polys)}")

    # Dissolve all snow patches into one MultiPolygon
    snow_geom = unary_union(polys)

    gdf = gpd.GeoDataFrame(
        [{"snow": True, "source": "NIC_IMS", "date": TIF_IN.stem}],
        geometry=[snow_geom],
        crs=crs,
    )

    # Reproject to EPSG:4326 for smoothing+output
    gdf = gdf.to_crs("EPSG:4326")

    # Explode into parts before clipping/smoothing (optional; either order is fine)
    gdf = gdf.explode(index_parts=False).reset_index(drop=True)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()

    # Clip to master GMU boundary (removes raster edge artefacts)
    gdf = clip_to_master_gmu(gdf, geom_type="polygon")

    # NEW: soften edges
    if SOFTEN_M and SOFTEN_M > 0:
        print(f"  Softening edges (buffer {SOFTEN_M}m, simplify {SOFTEN_SIMPLIFY_M}m) …")
        gdf = soften_edges(gdf, buffer_m=SOFTEN_M, simplify_m=SOFTEN_SIMPLIFY_M)

        # Clip again (buffering can push tiny bits outside GMUs)
        gdf = clip_to_master_gmu(gdf, geom_type="polygon")

    # Optional final simplify in degrees (very light)
    if SIMPLIFY_DEG and SIMPLIFY_DEG > 0:
        gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY_DEG, preserve_topology=True)

    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    gdf.to_file(snow_geojson, driver="GeoJSON")
    print(f"✅ Snow cover saved: {len(gdf)} polygon(s) → {snow_geojson}")


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  Snow Cover — NIC IMS clip + vectorize (with softened edges)")
    print("=" * 60)

    clip_to_master_gmus(TIF_IN, MASTER_GMUS, TIF_OUT)
    vectorize_snow(TIF_OUT, SNOW_GEOJSON)