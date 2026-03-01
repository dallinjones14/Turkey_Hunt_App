"""
Fetch Wild Turkey species range polygons.

Source: https://services.arcgis.com/FjJI5xHF2dUPVrgK/arcgis/rest/services/Species_Ranges/FeatureServer/1/query?outFields=*&where=1%3D1&f=geojson

Output: data/processed/species_range.geojson
"""
import requests
import geopandas as gpd
from pathlib import Path
from _gmu_clip import clip_to_master_gmu

BASE_URL  = (
    "https://services.arcgis.com/FjJI5xHF2dUPVrgK/arcgis/rest/services/"
    "Species_Ranges/FeatureServer/1/query"
)
PAGE_SIZE = 500
_ROOT    = Path(__file__).parent.parent
OUT_PATH = _ROOT / "pipelines" / "data" / "processed" / "species_range.geojson"
RAW_PATH = _ROOT / "pipelines" / "data" / "raw"       / "species_range_raw.geojson"

# Server-side WHERE candidates — tried in order until one returns data.
# The endpoint times out on where=1=1 (full table scan), so we push filters
# server-side to limit the result set before it reaches the wire.
TURKEY_FILTERS = [
    "COMMON_NAME LIKE '%Turkey%' AND COMMON_NAME NOT LIKE '%Vulture%'",
    "COMMON_NAME LIKE '%turkey%' AND COMMON_NAME NOT LIKE '%vulture%'",
    "Species LIKE '%Turkey%' AND Species NOT LIKE '%Vulture%'",
    "SpeciesName LIKE '%Turkey%' AND SpeciesName NOT LIKE '%Vulture%'",
    "SPP LIKE '%TUTR%'",
    "SPP LIKE '%TURL%'",
]


def fetch(where: str = TURKEY_FILTERS[0]) -> gpd.GeoDataFrame:
    """Fetch species range features with a server-side WHERE clause."""
    base_params = {
        "where":             where,
        "outFields":         "*",
        "f":                 "geojson",
        "outSR":             "4326",
        "resultRecordCount": PAGE_SIZE,
    }
    features = []
    offset = 0
    while True:
        params = {**base_params, "resultOffset": offset}
        print(f"  GET where={where!r} offset={offset} ...")
        resp = requests.get(BASE_URL, params=params, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("features", [])
        features.extend(batch)
        print(f"    {len(batch)} features (total: {len(features)})")
        if not data.get("exceededTransferLimit") or len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326") if features else gpd.GeoDataFrame()


def filter_turkey(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    str_cols = gdf.select_dtypes(include="object").columns
    include_mask = gdf[str_cols].apply(
        lambda col: col.str.contains("turkey", case=False, na=False)
    ).any(axis=1)
    exclude_mask = gdf[str_cols].apply(
        lambda col: col.str.contains("vulture", case=False, na=False)
    ).any(axis=1)
    result = gdf[include_mask & ~exclude_mask].copy()
    print(f"  Turkey filter: {len(result)}/{len(gdf)} features matched (vultures excluded).")
    return result


if __name__ == "__main__":
    print("=" * 60)
    print("  Fetching Wild Turkey Species Range")
    print("=" * 60)

    gdf = gpd.GeoDataFrame()
    for where_clause in TURKEY_FILTERS:
        try:
            gdf = fetch(where=where_clause)
        except Exception as e:
            print(f"  ⚠️  Filter {where_clause!r} failed: {e}")
            continue
        if not gdf.empty:
            print(f"  ✓ Filter {where_clause!r} returned {len(gdf)} features.")
            break
        print(f"  Filter {where_clause!r} returned 0 features, trying next...")

    if gdf.empty:
        print("\n❌ No turkey range features found with any filter.")
        print("   The endpoint may use different field/value names.")
        print("   Try fetching a small sample manually:")
        print(f"   {BASE_URL}?where=1%3D1&outFields=*&f=geojson&resultRecordCount=5")
        raise SystemExit(1)

    gdf.to_file(RAW_PATH, driver="GeoJSON")
    print(f"  {len(gdf)} features fetched → raw saved.")
    print(f"  Fields: {list(gdf.columns)}")
    for col in gdf.select_dtypes("object").columns[:4]:
        print(f"    {col}: {gdf[col].dropna().unique()[:6].tolist()}")

    # Secondary client-side filter in case the WHERE matched non-turkey records
    gdf = filter_turkey(gdf)
    if gdf.empty:
        print("\n⚠️  Server returned records but none matched 'turkey' client-side.")
        print("   Inspect data/raw/species_range_raw.geojson for species field names.")
        raise SystemExit(1)

    gdf = gdf.to_crs("EPSG:4326")

    rename = {
        "COMMON_NAME":  "common_name",
        "SPECIES_NAME": "species_name",
        "SPP":          "species_code",
        "Species":      "common_name",
        "SpeciesName":  "species_name",
    }
    gdf = gdf.rename(columns={k: v for k, v in rename.items() if k in gdf.columns})
    for col in ["common_name", "species_name", "species_code"]:
        if col not in gdf.columns:
            gdf[col] = "Wild Turkey"

    gdf["geometry"] = gdf.geometry.simplify(0.005, preserve_topology=True)
    gdf = gdf[~gdf.geometry.is_empty].reset_index(drop=True)

    gdf = clip_to_master_gmu(gdf, geom_type="polygon")
    gdf.to_file(OUT_PATH, driver="GeoJSON")
    print(f"\n✅ Saved {len(gdf)} turkey range features → {OUT_PATH}")
