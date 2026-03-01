"""
Fetch IDFG Regional Office locations.

Source: https://services.arcgis.com/FjJI5xHF2dUPVrgK/arcgis/rest/services/IDFG_Regional_Office_Locations/FeatureServer/0/query?outFields=*&where=1%3D1&f=geojson

Output: data/processed/regional_offices.geojson
"""
import requests
import geopandas as gpd
from pathlib import Path
from _gmu_clip import clip_to_master_gmu

BASE_URL = (
    "https://services.arcgis.com/FjJI5xHF2dUPVrgK/arcgis/rest/services/"
    "IDFG_Regional_Office_Locations/FeatureServer/0/query"
    "?outFields=*&where=1%3D1&f=geojson"
)
PAGE_SIZE = 500
_ROOT    = Path(__file__).parent.parent
OUT_PATH = _ROOT / "pipelines" / "data" / "processed" / "regional_offices.geojson"

FIELD_MAP = {
    "office_name": ["Office", "OfficeName", "OFFICE", "Name", "NAME", "Facility"],
    "region":      ["Region", "REGION", "RegionNum", "RegionNumber"],
    "address":     ["Address", "ADDRESS", "StreetAddress", "Street"],
    "city":        ["City", "CITY"],
    "state":       ["State", "STATE"],
    "zip":         ["Zip", "ZIP", "ZipCode", "ZIP_CODE"],
    "phone":       ["Phone", "PHONE", "PhoneNumber", "PHONE_NUM"],
    "email":       ["Email", "EMAIL"],
    "hours":       ["Hours", "HOURS", "OfficeHours", "Office_Hours"],
    "website":     ["Website", "WEBSITE", "URL"],
}


if __name__ == "__main__":
    print("=" * 60)
    print("  Fetching IDFG Regional Office Locations")
    print("=" * 60)

    features = []
    offset = 0
    while True:
        url = f"{BASE_URL}&resultRecordCount={PAGE_SIZE}&resultOffset={offset}"
        print(f"  GET offset={offset} ...")
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("features", [])
        features.extend(batch)
        print(f"    {len(batch)} features (total: {len(features)})")
        if not data.get("exceededTransferLimit") or len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")

    print(f"  {len(gdf)} offices fetched.")
    print(f"  Fields: {list(gdf.columns)}")

    gdf = gdf.to_crs("EPSG:4326")

    for standard, candidates in FIELD_MAP.items():
        for candidate in candidates:
            if candidate in gdf.columns:
                gdf = gdf.rename(columns={candidate: standard})
                break
        if standard not in gdf.columns:
            gdf[standard] = None

    gdf["full_address"] = gdf.apply(
        lambda r: ", ".join(
            str(v) for v in [r.get("address"), r.get("city"), "ID", r.get("zip")]
            if v and str(v) not in ("None", "")
        ),
        axis=1
    )

    keep = [
        "office_name", "region", "address", "city", "state",
        "zip", "phone", "email", "hours", "website", "full_address", "geometry"
    ]
    gdf = gdf[[c for c in keep if c in gdf.columns]]

    gdf = clip_to_master_gmu(gdf, geom_type="point")
    gdf.to_file(OUT_PATH, driver="GeoJSON")
    print(f"\n✅ Saved {len(gdf)} regional offices → {OUT_PATH}")
    print(gdf[["office_name", "city", "phone"]].to_string(index=False))
