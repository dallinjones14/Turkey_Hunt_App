"""
Build water_features.geojson from NHD GeoJSON files.

Source files (must be present in data/raw/):
  Flowlines:   NHD_FlowLines.geojson
  Waterbodies: NHD_WaterBodies.geojson

Classifies features by NHD FCode (flowlines) and FType (waterbodies):
  water_type = "perennial_stream"   — year-round rivers and streams (FCode 46006)
             = "intermittent_stream"— spring runoff / ephemeral streams (FCode 46003, 46007)
             = "lake"               — lakes, ponds, and reservoirs (FType 390, 436)

Output: pipelines/data/processed/water_features.geojson

Schema:
  name         — water body name (from GNIS_Name / GNIS_NAME)
  feature_type — "flowline" | "waterbody"  (for GL JS layer type filters)
  perennial    — True | False              (for GL JS color expression)
  water_type   — "perennial_stream" | "intermittent_stream" | "lake"
  geometry     — LineString (flowlines) or Polygon (waterbodies)
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
from pathlib import Path
from _gmu_clip import clip_to_master_gmu

_ROOT    = Path(__file__).resolve().parent.parent
RAW_DIR  = _ROOT / "pipelines" / "data" / "raw"
OUT_PATH = _ROOT / "pipelines" / "data" / "processed" / "water_features.geojson"

FL_FILE = RAW_DIR / "NHD_FlowLines.geojson"
WB_FILE = RAW_DIR / "NHD_WaterBodies.geojson"

# ── NHD FCode classification ───────────────────────────────────────────────────
# Source: https://nhd.usgs.gov/userguide.html — NHD Feature Catalog
_FCODE_MAP: dict[int, tuple[bool, str]] = {
    # StreamRiver
    46000: (True,  "perennial_stream"),    # Unspecified — treat as perennial
    46006: (True,  "perennial_stream"),    # Perennial (Year Round)
    46003: (False, "intermittent_stream"), # Intermittent (Spring Runoff)
    46007: (False, "intermittent_stream"), # Ephemeral (Spring Runoff)
    # Artificial Path (follows perennial channel)
    55800: (True,  "perennial_stream"),
    # Canal / Ditch
    33400: (True,  "perennial_stream"),
    33401: (False, "intermittent_stream"),
    # Aqueduct
    33600: (True,  "perennial_stream"),
    33601: (False, "intermittent_stream"),
}
_DEFAULT_FLOW = (True, "perennial_stream")

# NHD FType values for lakes and reservoirs (waterbody layer)
_LAKE_FTYPES = {390, 436}   # 390 = LakePond, 436 = Reservoir

# NHD FType values to skip in flowlines (non-surface water)
_SKIP_FLOW_FTYPES = {420, 334, 428, 566}  # Underground Conduit, Connector, Pipeline, Shoreline

KEEP_COLS = ["name", "feature_type", "perennial", "water_type", "geometry"]


# ── Helpers ────────────────────────────────────────────────────────────────────

def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_empty(path: Path) -> None:
    ensure_parent_dir(path)
    path.write_text('{"type":"FeatureCollection","features":[]}')


def _name_series(gdf: gpd.GeoDataFrame) -> pd.Series:
    """Extract a cleaned name column from whichever GNIS/name field is present."""
    for col in gdf.columns:
        if col.upper() in ("GNIS_NAME", "GNIS_NM", "NAME"):
            s = gdf[col].astype(str).str.strip()
            return s.where(~s.isin({"", "nan", "None", "NaN"}), other=None)
    return pd.Series([None] * len(gdf), index=gdf.index)


def _int_field(gdf: gpd.GeoDataFrame, *candidates: str) -> pd.Series:
    """Return the first matching column (case-insensitive) as a nullable Int64 series."""
    for name in candidates:
        for col in gdf.columns:
            if col.upper() == name.upper():
                return pd.to_numeric(gdf[col], errors="coerce").astype("Int64")
    return pd.Series(pd.array([pd.NA] * len(gdf), dtype="Int64"), index=gdf.index)


# ── Loaders ────────────────────────────────────────────────────────────────────

def load_flowlines(path: Path) -> gpd.GeoDataFrame:
    """
    Load NHD flowlines and classify each feature as perennial_stream or
    intermittent_stream using FCode.  Skips non-surface-water FTypes.
    """
    print(f"  Loading flowlines: {path.name}")
    gdf = gpd.read_file(path)
    if gdf.empty:
        print("    (empty file)")
        return gdf
    print(f"    {len(gdf):,} raw features")

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    else:
        gdf = gdf.to_crs("EPSG:4326")

    # Drop non-surface-water FTypes when the field is present
    ftype = _int_field(gdf, "FType", "FTYPE")
    if ftype.notna().any():
        gdf = gdf[~ftype.isin(_SKIP_FLOW_FTYPES)].copy()
        print(f"    {len(gdf):,} after removing non-surface types")

    gdf["name"]         = _name_series(gdf)
    gdf["feature_type"] = "flowline"

    fcode = _int_field(gdf, "FCode", "FCODE")
    perennial_vals, water_type_vals = [], []
    for fc in fcode:
        per, wt = _FCODE_MAP.get(int(fc) if pd.notna(fc) else -1, _DEFAULT_FLOW)
        perennial_vals.append(per)
        water_type_vals.append(wt)

    gdf["perennial"]  = perennial_vals
    gdf["water_type"] = water_type_vals

    n_per = sum(perennial_vals)
    n_int = len(perennial_vals) - n_per
    print(f"    {n_per:,} year-round  |  {n_int:,} spring runoff / intermittent")
    return gdf


def load_waterbodies(path: Path) -> gpd.GeoDataFrame:
    """
    Load NHD waterbodies, keeping only lakes and reservoirs (FType 390, 436).
    Falls back to all polygon features when FType is unavailable.
    """
    print(f"  Loading waterbodies: {path.name}")
    gdf = gpd.read_file(path)
    if gdf.empty:
        print("    (empty file)")
        return gdf
    print(f"    {len(gdf):,} raw features")

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    else:
        gdf = gdf.to_crs("EPSG:4326")

    # Filter to lakes / reservoirs when FType is available
    ftype = _int_field(gdf, "FType", "FTYPE")
    if ftype.notna().any():
        lakes = gdf[ftype.isin(_LAKE_FTYPES)].copy()
        if not lakes.empty:
            print(f"    {len(lakes):,} lakes / reservoirs (FType 390, 436) of {len(gdf):,} total")
            gdf = lakes
        else:
            print("    ⚠️  No FType 390/436 found — keeping all waterbodies as fallback")

    gdf["name"]         = _name_series(gdf)
    gdf["feature_type"] = "waterbody"
    gdf["perennial"]    = True
    gdf["water_type"]   = "lake"
    return gdf


def prep(gdf: gpd.GeoDataFrame, geom_type: str) -> gpd.GeoDataFrame:
    """Trim to schema columns, simplify geometry, drop empties, clip to GMU."""
    gdf = gdf[[c for c in KEEP_COLS if c in gdf.columns]].copy()
    gdf["geometry"] = gdf.geometry.simplify(0.0003, preserve_topology=True)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if gdf.empty:
        return gdf
    print(f"\n── Clipping {geom_type}s to master GMU boundary ─────────")
    gdf = clip_to_master_gmu(gdf, geom_type=geom_type)
    return gdf.to_crs("EPSG:4326")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  Building Water Features from NHD GeoJSONs")
    print("=" * 60)

    if not FL_FILE.exists():
        print(f"\n⚠️  NHD_FlowLines.geojson not found in data/raw/")
    if not WB_FILE.exists():
        print(f"\n⚠️  NHD_WaterBodies.geojson not found in data/raw/")

    if not FL_FILE.exists() and not WB_FILE.exists():
        write_empty(OUT_PATH)
        return

    frames: list[gpd.GeoDataFrame] = []

    # ── Flowlines ──────────────────────────────────────────────────────────────
    if FL_FILE.exists():
        print(f"\n── Flowlines (rivers / streams) ──────────────────────")
        lines = load_flowlines(FL_FILE)
        if not lines.empty:
            lines = prep(lines, "line")
            if not lines.empty:
                frames.append(lines)
                n_per = int((lines["water_type"] == "perennial_stream").sum())
                n_int = int((lines["water_type"] == "intermittent_stream").sum())
                print(f"   → {n_per:,} year-round  |  {n_int:,} spring runoff  (after clip)")

    # ── Waterbodies ────────────────────────────────────────────────────────────
    if WB_FILE.exists():
        print(f"\n── Waterbodies (lakes / reservoirs) ──────────────────")
        polys = load_waterbodies(WB_FILE)
        if not polys.empty:
            polys = prep(polys, "polygon")
            if not polys.empty:
                frames.append(polys)
                print(f"   → {len(polys):,} lakes / reservoirs  (after clip)")

    if not frames:
        print("\n⚠️  No features survived clipping; writing empty GeoJSON.")
        write_empty(OUT_PATH)
        return

    water = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")
    ensure_parent_dir(OUT_PATH)
    water.to_file(OUT_PATH, driver="GeoJSON")
    print(f"\n✅ Saved {len(water):,} total features → {OUT_PATH.name}")

    _LABELS = {
        "perennial_stream":    "Year-Round Streams",
        "intermittent_stream": "Spring Runoff Streams",
        "lake":                "Lakes / Reservoirs",
    }
    if "water_type" in water.columns:
        for wt, grp in water.groupby("water_type"):
            named = int(grp["name"].notna().sum())
            print(f"     {_LABELS.get(str(wt), wt)}: {len(grp):,}  ({named} named)")


if __name__ == "__main__":
    main()
