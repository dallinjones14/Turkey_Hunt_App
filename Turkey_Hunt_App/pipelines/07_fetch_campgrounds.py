"""
Fetch Recreation structures (campgrounds / recreation) near Idaho turkey hunt units.

Source (ArcGIS FeatureServer):
  https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/Structures_Recreation_v1/FeatureServer/0/query

Clips results to hunt unit bounding box (+0.1° buffer).

Output:
  pipelines/data/processed/campgrounds.geojson
"""

from __future__ import annotations

import json
import requests
import geopandas as gpd
from pathlib import Path
from shapely.geometry import shape
from shapely.ops import unary_union
from _gmu_clip import clip_to_master_gmu

PAGE_SIZE = 1000

_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = _ROOT / "pipelines" / "data" / "processed" / "campgrounds.geojson"
UNITS_PATH = _ROOT / "pipelines" / "data" / "processed" / "hunt_units.geojson"

BASE_URL = "https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/Structures_Recreation_v1/FeatureServer/0/query"

# Best-effort field candidates (we’ll auto-pick what exists)
FIELD_MAP = {
    "site_name": [
        "name", "Name", "NAME", "site_name", "SiteName", "SITE_NAME",
        "structure_name", "StructureName", "STRUCTURE_NAME",
        "facility_name", "FacilityName", "FACILITY_NAME",
        "title", "Title", "TITLE",
    ],
    "site_type": [
        "type", "Type", "TYPE", "site_type", "SiteType", "SITE_TYPE",
        "structure_type", "StructureType", "STRUCTURE_TYPE",
        "category", "Category", "CATEGORY",
        "recreation_type", "RecreationType", "RECREATION_TYPE",
    ],
    "phone": [
        "phone", "Phone", "PHONE", "contact_phone", "CONTACT_PHONE",
        "tel", "Tel", "TEL",
    ],
    "url": [
        "url", "URL", "website", "Website", "WEBSITE",
        "link", "Link", "LINK",
        "reservation_url", "ReservationURL", "RESERVATION_URL",
    ],
}


def _pick(props: dict, candidates: list[str]):
    for c in candidates:
        if c in props and props[c] not in (None, "", " "):
            return props[c]
    return None


def _get_hunt_bbox_4326() -> tuple[float, float, float, float]:
    """
    Return (minx, miny, maxx, maxy) from hunt units in EPSG:4326 + 0.1° buffer.
    If hunt units missing, fallback to Idaho-ish bbox.
    """
    fallback = (-117.3, 41.9, -111.0, 49.1)

    if not UNITS_PATH.exists():
        return fallback

    units = gpd.read_file(UNITS_PATH)
    if units.empty:
        return fallback

    # Ensure bbox is lon/lat degrees
    if units.crs is None:
        raise ValueError("hunt_units.geojson has no CRS; set it before running.")
    units = units.to_crs("EPSG:4326")

    union = unary_union(units.geometry)
    minx, miny, maxx, maxy = union.bounds

    buf = 0.1
    return (minx - buf, miny - buf, maxx + buf, maxy + buf)


def fetch_structures_bbox(bbox_4326: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    minx, miny, maxx, maxy = bbox_4326

    base_params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "f": "geojson",
        "outSR": "4326",
        "geometry": f"{minx},{miny},{maxx},{maxy}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "resultRecordCount": PAGE_SIZE,
    }

    features = []
    offset = 0

    while True:
        params = {**base_params, "resultOffset": offset}
        r = requests.get(BASE_URL, params=params, timeout=120)
        r.raise_for_status()
        data = r.json()

        if "error" in data:
            raise RuntimeError(f"ArcGIS error: {data['error']}")

        batch = data.get("features", []) or []
        features.extend(batch)

        print(f"  fetched {len(batch)} features (offset={offset})")

        # ArcGIS uses exceededTransferLimit when paging is needed
        if not data.get("exceededTransferLimit") or len(batch) < PAGE_SIZE:
            break

        offset += PAGE_SIZE

    if not features:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")


def normalize_fields(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Add standardized columns: site_name, site_type, phone, url
    while keeping all original attributes.
    """
    if gdf.empty:
        for col in ["site_name", "site_type", "phone", "url"]:
            gdf[col] = None
        return gdf

    # properties are already columns in GeoDataFrame; just pick best candidates
    gdf = gdf.copy()
    gdf["site_name"] = gdf.apply(lambda row: _pick(row, FIELD_MAP["site_name"]), axis=1)
    gdf["site_type"] = gdf.apply(lambda row: _pick(row, FIELD_MAP["site_type"]), axis=1)
    gdf["phone"] = gdf.apply(lambda row: _pick(row, FIELD_MAP["phone"]), axis=1)
    gdf["url"] = gdf.apply(lambda row: _pick(row, FIELD_MAP["url"]), axis=1)

    # fallbacks
    gdf["site_name"] = gdf["site_name"].fillna("Recreation Site")
    gdf["site_type"] = gdf["site_type"].fillna("RECREATION")

    return gdf


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("Loading hunt unit bbox...")
    bbox = _get_hunt_bbox_4326()
    print(f"  Bbox (EPSG:4326): {bbox}")

    print("\nFetching recreation structures from ArcGIS service...")
    gdf = fetch_structures_bbox(bbox)
    print(f"  Total fetched: {len(gdf)}")

    if gdf.empty:
        print("⚠️  No features returned. Writing empty FeatureCollection.")
        OUT_PATH.write_text(json.dumps({"type": "FeatureCollection", "features": []}))
        return

    # keep geometry validity + CRS
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    else:
        gdf = gdf.to_crs("EPSG:4326")

    # Normalize standard fields
    gdf = normalize_fields(gdf)

    # Keep only points (common for structures). If you want polygons too, remove this filter.
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    gdf = gdf[gdf.geometry.geom_type == "Point"].copy()
    gdf = clip_to_master_gmu(gdf, geom_type="point")

    # Save
    gdf.to_file(OUT_PATH, driver="GeoJSON")
    print(f"\n✅ Wrote {len(gdf)} recreation structures → {OUT_PATH}")

    # Helpful debug: show some columns so you can refine FIELD_MAP if needed
    cols = list(gdf.columns)
    print("\nSample output columns (first 30):")
    print(cols[:30])


if __name__ == "__main__":
    main()