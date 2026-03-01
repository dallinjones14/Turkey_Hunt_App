"""
Build master Turkey GMU GeoJSON from IDFG hunt CSV + IDFG geometry.

Geometry rules (per your requirement):
  - If CSV Hunt_Type in {"Controlled","Youth"}:
        geometry comes from ControlledHunts_All filtered to BigGame == 'Turkey'
        join key: CSV.GMU == Controlled.HuntArea
  - If CSV Hunt_Type == "General":
        geometry comes from GMU boundaries service (GMU_URL)
        join key: CSV.GMU == GMU.(NAME or Name)   # prefers NAME first

Output (single file):
  pipelines/data/processed/master_turkey_gmu.geojson

Feature granularity:
  - One feature per GMU per Season (Spring/Fall).
  - A "primary" hunt type per GMU+Season is selected by priority:
        Controlled > Youth > General
  - Geometry source follows the PRIMARY hunt type rule above.
  - all_hunts_json includes ALL CSV entries for that GMU+Season.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import shape

# ─────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────

PAGE_SIZE = 500
TIMEOUT = 120

_ROOT = Path(__file__).resolve().parent.parent
PROCESSED = _ROOT / "pipelines" / "data" / "processed"
RAW = _ROOT / "pipelines" / "data" / "raw"

CSV_PATH = RAW / "Turkey_GMU.csv"
MASTER_OUT = PROCESSED / "master_turkey_gmu.geojson"

# If not None, only include these normalized GMUs
TARGET_GMUS: set[str] | None = {"32", "32A", "33", "38", "39", "49"}

# Primary hunt type selection per GMU+Season
PRIORITY = {"Controlled": 3, "Youth": 2, "General": 1}

CTRL_URL = (
    "https://services.arcgis.com/FjJI5xHF2dUPVrgK/arcgis/rest/services/"
    "ControlledHunts_All/FeatureServer/0/query"
)

GMU_URL = (
    "https://gisportal-idfg.idaho.gov/hosting/rest/services/"
    "Hunting/MapServer/3/query"
)

# Controlled layer fields
CTRL_BIGGAME_FIELD = "BigGame"
CTRL_JOIN_FIELD = "HuntArea"  # join: CSV.GMU == Controlled.HuntArea

# General layer join field candidates (NAME is common in IDFG layers)
GEN_JOIN_FIELDS = ["NAME", "Name", "UNIT_NAME", "UnitName", "Label", "LABEL"]

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def normalize_gmu(val) -> str:
    """Normalize GMU ID: strip, uppercase, remove 'UNIT'/'GMU' prefix, keep leading digits+optional letter."""
    s = str(val).strip().upper()
    s = re.sub(r"^(HUNT\s*UNIT|UNIT|GMU)\s*", "", s)
    m = re.match(r"^(\d+[A-Z]?)", s)
    return m.group(1) if m else s


def safe_str(x) -> str:
    if x is None:
        return ""
    if isinstance(x, float) and pd.isna(x):
        return ""
    return str(x).strip()


def fetch_all_geojson_features(url: str) -> list[dict]:
    """Fetch all features from an ArcGIS REST query endpoint requesting f=geojson (paged)."""
    features: list[dict] = []
    offset = 0

    while True:
        params = {
            "where": "1=1",
            "outFields": "*",
            "f": "geojson",
            "resultRecordCount": PAGE_SIZE,
            "resultOffset": offset,
        }
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()

        batch = data.get("features", []) or []
        features.extend(batch)

        exceeded = bool(data.get("exceededTransferLimit"))
        if not exceeded or len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return features


def pick_prop(props: dict, candidates: list[str]) -> str | None:
    for c in candidates:
        v = props.get(c)
        if v not in (None, "", " "):
            return str(v)
    return None


def calc_area_acres(geom):
    """Area (acres) via EPSG:5070 equal-area projection."""
    try:
        import pyproj
        from shapely.ops import transform

        project = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform
        return round(transform(project, geom).area / 4046.86, 1)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# Step 1: Load CSV
# ─────────────────────────────────────────────────────────────

def load_csv() -> pd.DataFrame:
    if not CSV_PATH.exists():
        print(f"❌ CSV not found: {CSV_PATH}")
        sys.exit(1)

    df = pd.read_csv(CSV_PATH, dtype=str).fillna("")
    df.columns = [c.strip() for c in df.columns]
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()

    required = {"GMU", "Hunt_Type", "Season", "Date"}
    missing = required - set(df.columns)
    if missing:
        print(f"❌ CSV missing required columns: {missing}")
        sys.exit(1)

    if "Hunt_Number" not in df.columns:
        df["Hunt_Number"] = ""
    if "Restrictions" not in df.columns:
        df["Restrictions"] = ""

    df["_gmu_key"] = df["GMU"].apply(normalize_gmu)

    # normalize Hunt_Type + Season values
    df["Hunt_Type"] = df["Hunt_Type"].astype(str).str.strip().str.title()
    df["Season"] = df["Season"].astype(str).str.strip().str.title()

    if TARGET_GMUS:
        df = df[df["_gmu_key"].isin(TARGET_GMUS)].copy()

    print(f"  Loaded CSV: {len(df)} rows, {df['_gmu_key'].nunique()} unique GMUs")
    return df


# ─────────────────────────────────────────────────────────────
# Step 2: Controlled lookup (BigGame='Turkey', join by HuntArea)
# ─────────────────────────────────────────────────────────────

def fetch_controlled_lookup() -> dict[str, object]:
    feats = fetch_all_geojson_features(CTRL_URL)
    if not feats:
        print("  ⚠️ No controlled hunt features returned.")
        return {}

    gdf = gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326")

    # strict filter BigGame == Turkey
    if CTRL_BIGGAME_FIELD in gdf.columns:
        gdf = gdf[gdf[CTRL_BIGGAME_FIELD].astype(str).str.strip().str.lower() == "turkey"].copy()
    else:
        # fallback: keep anything mentioning turkey in string fields
        str_cols = gdf.select_dtypes(include="object").columns
        mask = gdf[str_cols].apply(lambda col: col.str.contains("turkey", case=False, na=False)).any(axis=1)
        gdf = gdf[mask].copy()

    if CTRL_JOIN_FIELD not in gdf.columns:
        print(f"  ⚠️ Controlled layer missing join field '{CTRL_JOIN_FIELD}'.")
        return {}

    # geometry cleanup
    gdf = gdf[~gdf.geometry.is_empty].copy()
    gdf["geometry"] = gdf.geometry.simplify(0.001, preserve_topology=True)
    gdf = gdf[~gdf.geometry.is_empty].reset_index(drop=True)

    lookup: dict[str, object] = {}
    for _, row in gdf.iterrows():
        key = normalize_gmu(row.get(CTRL_JOIN_FIELD, ""))
        if key and key not in lookup and row.geometry is not None and not row.geometry.is_empty:
            lookup[key] = row.geometry

    print(f"  Controlled turkey GMU keys: {len(lookup)} (join: HuntArea)")
    return lookup


# ─────────────────────────────────────────────────────────────
# Step 3: General lookup (SERVICE geojson; join by NAME/Name)
# ─────────────────────────────────────────────────────────────

def fetch_general_lookup_from_service() -> dict[str, object]:
    feats = fetch_all_geojson_features(GMU_URL)
    if not feats:
        print("  ⚠️ No GMU boundary features returned.")
        return {}

    # Print sample fields once to help debugging if join is still empty
    sample_props = (feats[0].get("properties") or {}) if feats else {}
    if sample_props:
        print(f"  GMU service sample fields: {list(sample_props.keys())}")

    lookup: dict[str, object] = {}
    missing_name = 0
    bad_geom = 0

    for f in feats:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            bad_geom += 1
            continue

        name_val = pick_prop(props, GEN_JOIN_FIELDS)
        if not name_val:
            missing_name += 1
            continue

        try:
            geom_shape = shape(geom)
        except Exception:
            bad_geom += 1
            continue

        if not geom_shape or geom_shape.is_empty:
            bad_geom += 1
            continue

        key = normalize_gmu(name_val)
        if key and key not in lookup:
            lookup[key] = geom_shape

    print(
        f"  General GMU keys: {len(lookup)} (join fields tried: {GEN_JOIN_FIELDS}) "
        f"| missing name: {missing_name} | bad/empty geom: {bad_geom}"
    )
    return lookup


# ─────────────────────────────────────────────────────────────
# Step 4: Build master features (one per GMU per Season)
# ─────────────────────────────────────────────────────────────

def geometry_for_hunt_type(hunt_type: str, gmu_key: str, ctrl_lookup: dict, gen_lookup: dict):
    """
    Your rule:
      Controlled/Youth => controlled geometry (HuntArea)
      General          => general geometry (NAME/Name from service)
    Always fall back to the other source if missing.
    """
    ht = safe_str(hunt_type).title()
    if ht in ("Controlled", "Youth"):
        return ctrl_lookup.get(gmu_key) or gen_lookup.get(gmu_key)
    return gen_lookup.get(gmu_key) or ctrl_lookup.get(gmu_key)


def build_master_features(df: pd.DataFrame, ctrl_lookup: dict, gen_lookup: dict) -> list[dict]:
    features: list[dict] = []
    skipped: list[str] = []

    for (gmu_key, season), group in df.groupby(["_gmu_key", "Season"]):
        types_present = [t for t in group["Hunt_Type"].dropna().unique().tolist() if safe_str(t)]
        primary_type = (
            max(types_present, key=lambda t: PRIORITY.get(safe_str(t).title(), 0))
            if types_present
            else "General"
        )

        geom = geometry_for_hunt_type(primary_type, gmu_key, ctrl_lookup, gen_lookup)
        if geom is None:
            skipped.append(f"{gmu_key} ({season})")
            continue

        primary_rows = group[group["Hunt_Type"].astype(str).str.title() == primary_type.title()].copy()

        primary_dates = "; ".join(sorted({safe_str(v) for v in primary_rows["Date"].tolist() if safe_str(v)}))
        primary_hunt_nums = ", ".join(sorted({safe_str(v) for v in primary_rows["Hunt_Number"].tolist() if safe_str(v)}))
        primary_restrictions = safe_str(primary_rows.iloc[0].get("Restrictions", "")) if not primary_rows.empty else ""
        primary_sex = "; ".join(sorted({safe_str(v) for v in primary_rows["Sex"].tolist() if safe_str(v)})) if "Sex" in primary_rows.columns else ""

        all_hunts = []
        for _, r in group.iterrows():
            all_hunts.append(
                {
                    "Hunt_Type":   safe_str(r.get("Hunt_Type")),
                    "Hunt_Number": safe_str(r.get("Hunt_Number")),
                    "Sex":         safe_str(r.get("Sex", "")),
                    "Date":        safe_str(r.get("Date")),
                    "Restrictions": safe_str(r.get("Restrictions")),
                }
            )

        features.append(
            {
                "type": "Feature",
                "geometry": geom.__geo_interface__,
                "properties": {
                    "GMU":          gmu_key,
                    "Season":       safe_str(season).title(),
                    "Hunt_Type":    primary_type.title(),
                    "Sex":          primary_sex,
                    "Date":         primary_dates,
                    "Hunt_Number":  primary_hunt_nums,
                    "Restrictions": primary_restrictions,
                    "area_acres":   calc_area_acres(geom),
                    "all_hunts_json": json.dumps(all_hunts),
                },
            }
        )

    if skipped:
        print(f"  ⚠️ No geometry for {len(skipped)} GMU+Season groups (first 25): {', '.join(skipped[:25])}")

    return features


# ─────────────────────────────────────────────────────────────
# Step 5: Write output
# ─────────────────────────────────────────────────────────────

def write_geojson(features: list[dict], out_path: Path) -> None:
    fc = {"type": "FeatureCollection", "features": features}
    out_path.write_text(json.dumps(fc, ensure_ascii=False))
    print(f"  ✅ Wrote {len(features)} features → {out_path}")


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main() -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)

    print("\n── Step 1: Load CSV ────────────────────────────────────────────────")
    df = load_csv()

    print("\n── Step 2: Controlled lookup (BigGame='Turkey', HuntArea join) ─────")
    try:
        ctrl_lookup = fetch_controlled_lookup()
    except Exception as e:
        print(f"  ⚠️ Controlled fetch failed: {e}")
        ctrl_lookup = {}

    print("\n── Step 3: General lookup (SERVICE, NAME/Name join) ─────────────────")
    try:
        gen_lookup = fetch_general_lookup_from_service()
    except Exception as e:
        print(f"  ⚠️ GMU boundary fetch failed: {e}")
        gen_lookup = {}

    if not ctrl_lookup and not gen_lookup:
        print("❌ No geometry returned from either source. Cannot build master.")
        sys.exit(1)

    print("\n── Step 4: Build master features ───────────────────────────────────")
    features = build_master_features(df, ctrl_lookup, gen_lookup)

    print("\n── Step 5: Write master geojson ────────────────────────────────────")
    write_geojson(features, MASTER_OUT)

    print("\n✅ Pipeline complete.")


if __name__ == "__main__":
    print("=" * 60)
    print("  Build Master Turkey GMU GeoJSON")
    print("=" * 60)
    main()