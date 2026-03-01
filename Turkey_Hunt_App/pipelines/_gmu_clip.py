"""
Shared helper: clip a GeoDataFrame to the master Turkey GMU boundary.

- If master_turkey_gmu.geojson is missing, returns input unchanged.
- Buffers the dissolved GMU boundary slightly to avoid hard edge clipping.
- Always returns EPSG:4326 (so processed GeoJSON outputs are consistent).
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.ops import unary_union

# Paths
_PROCESSED = Path(__file__).resolve().parent / "data" / "processed"
_MASTER_GMU = _PROCESSED / "master_turkey_gmu.geojson"

# ~0.02° ≈ ~1–2 km in Idaho; avoids hard edge clipping at GMU boundaries
_BUFFER_DEG = 0.02
_OUT_CRS = "EPSG:4326"


def _detect_geom_type(gdf: gpd.GeoDataFrame) -> str:
    """Return 'point' | 'line' | 'polygon' based on first non-empty geometry."""
    s = gdf.geometry
    s = s[s.notna() & ~s.is_empty]
    if s.empty:
        return "polygon"
    t = s.iloc[0].geom_type
    if "Point" in t:
        return "point"
    if "Line" in t:
        return "line"
    return "polygon"


def _load_clip_boundary() -> object | None:
    """Load, dissolve, and buffer the master GMU boundary. Returns shapely geometry or None."""
    if not _MASTER_GMU.exists():
        print("  ⚠️  _gmu_clip: master_turkey_gmu.geojson not found — skipping clip.")
        return None

    master = gpd.read_file(_MASTER_GMU)
    if master.empty:
        print("  ⚠️  _gmu_clip: master_turkey_gmu.geojson is empty — skipping clip.")
        return None

    if master.crs is None:
        master = master.set_crs(_OUT_CRS, allow_override=True)
    else:
        master = master.to_crs(_OUT_CRS)

    boundary = unary_union(master.geometry)
    if boundary.is_empty:
        print("  ⚠️  _gmu_clip: dissolved master boundary is empty — skipping clip.")
        return None

    return boundary.buffer(_BUFFER_DEG)


def clip_to_master_gmu(gdf: gpd.GeoDataFrame, geom_type: str = "auto") -> gpd.GeoDataFrame:
    """
    Clip *gdf* to the dissolved + buffered master Turkey GMU polygon.

    Parameters
    ----------
    gdf       : GeoDataFrame to clip
    geom_type : "point" | "line" | "polygon" | "auto"

    Returns
    -------
    GeoDataFrame in EPSG:4326. If master boundary is missing or clip yields 0 features,
    returns input (reprojected to EPSG:4326 if needed).
    """
    if gdf is None or gdf.empty:
        return gdf

    boundary = _load_clip_boundary()
    if boundary is None:
        # Still normalize output CRS for consistency
        if gdf.crs is None:
            return gdf.set_crs(_OUT_CRS, allow_override=True)
        return gdf.to_crs(_OUT_CRS)

    if geom_type == "auto":
        geom_type = _detect_geom_type(gdf)

    # Ensure EPSG:4326 for clip operation
    original_count = len(gdf)
    if gdf.crs is None:
        work = gdf.set_crs(_OUT_CRS, allow_override=True).copy()
    else:
        work = gdf.to_crs(_OUT_CRS).copy()

    try:
        if geom_type == "point":
            clipped = work[work.geometry.intersects(boundary)].copy()
        else:
            clipped = work.clip(boundary)
    except Exception as exc:
        print(f"  ⚠️  _gmu_clip: clip failed ({exc}); falling back to intersects filter.")
        clipped = work[work.geometry.intersects(boundary)].copy()

    clipped = clipped[clipped.geometry.notna() & ~clipped.geometry.is_empty].reset_index(drop=True)

    if clipped.empty:
        print(f"  ⚠️  _gmu_clip: clip produced 0 features (had {original_count}). "
              f"Returning empty — check that source data overlaps the GMU boundary.")
        return clipped   # return empty rather than unclipped data

    print(f"  ✂️  Clipped to master GMU: {original_count} → {len(clipped)} features")
    return clipped