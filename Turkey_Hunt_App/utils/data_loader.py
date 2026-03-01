import json
from pathlib import Path
from shapely.geometry import shape, mapping  # shape/mapping still used by _load_geojson_lean

PROCESSED_DIR = Path(__file__).parent.parent / "pipelines" / "data" / "processed"
EMPTY_FC      = {"type": "FeatureCollection", "features": []}

# Files larger than this (bytes) get geometry simplification before inline embedding
_INLINE_SIZE_LIMIT = 3 * 1024 * 1024   # 3 MB

# Only show these GMU units in the app. Must match the normalized keys in
# master_turkey_gmu.geojson (i.e. what 01_build_turkey_gmu.py writes as "GMU" property).
# Set to None to show all GMUs.
TARGET_GMUS: set | None = {"32", "32A", "33", "38", "39", "49"}


def _load_geojson(filename: str) -> dict:
    path = PROCESSED_DIR / filename
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return EMPTY_FC


def _load_geojson_lean(filename: str, tolerance: float = 0.003) -> dict:
    """
    Load GeoJSON and simplify geometries if the file exceeds _INLINE_SIZE_LIMIT.
    Keeps all features but reduces vertex count so the data embeds safely inline.
    tolerance is in degrees (~300 m at Idaho latitudes).
    """
    path = PROCESSED_DIR / filename
    if not path.exists():
        return EMPTY_FC

    size = path.stat().st_size
    if size <= _INLINE_SIZE_LIMIT:
        with open(path) as f:
            return json.load(f)

    print(f"  ℹ️  {filename} is {size / 1e6:.1f} MB — simplifying geometries "
          f"at {tolerance}° tolerance before embedding.")

    with open(path) as f:
        data = json.load(f)

    simplified = []
    for feat in data.get("features", []):
        try:
            geom = shape(feat["geometry"]).simplify(tolerance, preserve_topology=True)
            if not geom.is_empty:
                simplified.append({**feat, "geometry": mapping(geom)})
        except Exception:
            simplified.append(feat)   # keep as-is on failure

    return {"type": "FeatureCollection", "features": simplified}



def load_all_data() -> dict:
    """
    Load all processed GeoJSON datasets into a single dict.
    Missing files return empty FeatureCollections so the app still renders.
    Run `python pipelines/run_pipelines.py` to (re)build all processed files.

    Keys returned:
        turkey_gmu        — master GMU (Controlled + Youth + General, Spring + Fall)
        species_range     — IDFG wild turkey species range polygons
        offices           — IDFG regional office point locations
        access_yes        — IDFG AccessYes program properties
        motorized_trails  — USFS MVUM motorized roads/trails
        trails            — USFS MVUM non-motorized trails
        water             — USGS NHD flowlines and waterbodies (auto-simplified if large)
        campgrounds       — USFS EDW campground sites
        closed_areas      — IDFG areas closed to turkey hunting
        burned_areas      — NIFC historic fire perimeters (2005+)
        logging_areas     — USFS timber harvest clearings
        public_access     — Idaho SMA land ownership polygons by agency
        idfg_wma          — IDFG Wildlife Management Area boundaries
    """
    # Master Turkey GMU — built by pipelines/01_build_turkey_gmu.py
    # Contains Controlled, Youth, and General hunt units for both Spring and Fall.
    # Each feature has: GMU, Season, Hunt_Type, Date, Hunt_Number,
    #                   Restrictions, area_acres, all_hunts_json
    raw_gmu = _load_geojson("master_turkey_gmu.geojson")
    if TARGET_GMUS:
        raw_gmu = {
            "type": "FeatureCollection",
            "features": [
                f for f in raw_gmu.get("features", [])
                if f.get("properties", {}).get("GMU") in TARGET_GMUS
            ],
        }

    return {
        "turkey_gmu":        raw_gmu,
        "species_range":     _load_geojson("species_range.geojson"),
        "offices":           _load_geojson("regional_offices.geojson"),
        "access_yes":        _load_geojson("access_yes.geojson"),
        "motorized_trails":  _load_geojson("mvum_motorized_trails.geojson"),
        "trails":            _load_geojson("mvum_trails.geojson"),
        "water":             _load_geojson_lean("water_features.geojson", tolerance=0.0003),
        "campgrounds":       _load_geojson("campgrounds.geojson"),
        "closed_areas":      _load_geojson("closed_areas.geojson"),
        "burned_areas":      _load_geojson("burned_areas.geojson"),
        "logging_areas":     _load_geojson("logging_areas.geojson"),
        "snow_cover":        _load_geojson("snow_cover.geojson"),
        "public_access":     _load_geojson_lean("public_access.geojson", tolerance=0.0005),
        "idfg_wma":          _load_geojson("idfg_wma.geojson"),
        "deciduous_forest":  _load_geojson("DeciduousForest.geojson"),
        "cropland":          _load_geojson("CropLand.geojson"),
    }


def compute_summary_stats(data: dict) -> dict:
    """Compute scalar summary metrics shown in the app header."""
    gmu_features = data["turkey_gmu"].get("features", [])
    offices      = data["offices"].get("features", [])
    access_yes   = data["access_yes"].get("features", [])
    water        = data["water"].get("features", [])

    # Count unique GMU identifiers (master has two entries per GMU: Spring + Fall)
    unique_gmus = len({
        f["properties"].get("GMU")
        for f in gmu_features
        if f.get("properties", {}).get("GMU")
    })

    total_acres = sum(
        f["properties"].get("acres", 0) or 0
        for f in access_yes
    )

    return {
        "hunt_unit_count":     unique_gmus,
        "office_count":        len(offices),
        "access_yes_count":    len(access_yes),
        "access_yes_acres":    round(total_acres),
        "water_feature_count": len(water),
    }
