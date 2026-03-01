"""
Fetch IDFG AccessYes program property boundaries.

Source: https://gisportal-idfg.idaho.gov/hosting/rest/services/Access/Access/MapServer/1/query?outFields=*&where=1%3D1&f=geojson

NOTE: gisportal-idfg.idaho.gov may restrict access from non-Idaho IPs.
      Verify the URL is reachable in your browser before running.

Output: data/processed/access_yes.geojson
"""
import requests
import geopandas as gpd
from pathlib import Path
from _gmu_clip import clip_to_master_gmu

BASE_URL = (
    "https://gisportal-idfg.idaho.gov/hosting/rest/services/"
    "Access/Access/MapServer/1/query"
    "?outFields=*&where=1%3D1&f=geojson"
)
PAGE_SIZE = 500
_ROOT    = Path(__file__).parent.parent
OUT_PATH = _ROOT / "pipelines" / "data" / "processed" / "access_yes.geojson"
RAW_PATH = _ROOT / "pipelines" / "data" / "raw"       / "access_yes_raw.geojson"

FIELD_MAP = {
    "property_name":   ["PropertyName", "PROPERTY_NAME", "Name", "NAME",
                        "SiteName", "SITE_NAME", "PropName"],
    "acres":           ["Acres", "ACRES", "GIS_Acres", "GIS_ACRES",
                        "Area_Acres", "TotalAcres"],
    "county":          ["County", "COUNTY", "CountyName"],
    "access_type":     ["AccessType", "Access_Type", "ACCESS_TYPE",
                        "HuntAccess", "Type"],
    "species_allowed": ["Species", "SPECIES", "SpeciesAllowed",
                        "Species_Allowed", "GameSpecies"],
    "contact":         ["Contact", "CONTACT", "LandownerContact"],
    "open_date":       ["OpenDate", "Open_Date", "OPEN_DATE", "AccessOpen"],
    "close_date":      ["CloseDate", "Close_Date", "CLOSE_DATE", "AccessClose"],
    "restrictions":    ["Restrictions", "RESTRICTIONS", "Notes", "NOTES"],
}


if __name__ == "__main__":
    print("=" * 60)
    print("  Fetching IDFG AccessYes Properties")
    print("=" * 60)

    features = []
    offset = 0
    while True:
        url = f"{BASE_URL}&resultRecordCount={PAGE_SIZE}&resultOffset={offset}"
        print(f"  GET offset={offset} ...")
        try:
            resp = requests.get(url, timeout=120)
            resp.raise_for_status()
        except Exception as e:
            print(f"\n❌ Fetch failed: {e}")
            print("   Verify the URL is reachable from your network:")
            print(f"   {BASE_URL}")
            raise SystemExit(1)
        data = resp.json()
        batch = data.get("features", [])
        features.extend(batch)
        print(f"    {len(batch)} features (total: {len(features)})")
        if not data.get("exceededTransferLimit") or len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    gdf.to_file(RAW_PATH, driver="GeoJSON")
    print(f"  {len(gdf)} properties fetched → raw saved.")
    print(f"  Fields: {list(gdf.columns)}")

    gdf = gdf.to_crs("EPSG:4326")

    for standard, candidates in FIELD_MAP.items():
        for candidate in candidates:
            if candidate in gdf.columns:
                gdf = gdf.rename(columns={candidate: standard})
                break
        if standard not in gdf.columns:
            gdf[standard] = None

    gdf_proj = gdf.to_crs("EPSG:5070")
    gdf["gis_acres"] = (gdf_proj.geometry.area / 4046.86).round(1)
    if gdf["acres"].isna().all():
        gdf["acres"] = gdf["gis_acres"]

    gdf["geometry"] = gdf.geometry.simplify(0.0005, preserve_topology=True)
    gdf = gdf[~gdf.geometry.is_empty].reset_index(drop=True)
    gdf = clip_to_master_gmu(gdf, geom_type="polygon")

    keep = [
        "property_name", "acres", "gis_acres", "county",
        "access_type", "species_allowed", "contact",
        "open_date", "close_date", "restrictions", "geometry"
    ]
    gdf = gdf[[c for c in keep if c in gdf.columns]]

    gdf.to_file(OUT_PATH, driver="GeoJSON")
    print(f"\n✅ Saved {len(gdf)} AccessYes properties → {OUT_PATH}")
    print(f"   Total enrolled acres: {gdf['acres'].sum():,.0f}")
