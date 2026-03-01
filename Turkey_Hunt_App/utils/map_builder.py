"""
Assembles the Mapbox GL JS map HTML from static asset files.

Static files (CSS, JS, controls HTML) live in utils/static/ and contain
__TOKEN__ placeholders that are replaced with live data before serving.
"""
import base64
from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"


def _img_data_url(path: Path) -> str:
    """Read a PNG file and return a base64 data URL, or empty string if missing."""
    if not path.exists():
        return ""
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"

_MAPBOX_GL_JS  = "https://api.mapbox.com/mapbox-gl-js/v3.3.0/mapbox-gl.js"
_MAPBOX_GL_CSS = "https://api.mapbox.com/mapbox-gl-js/v3.3.0/mapbox-gl.css"
_DRAW_JS       = "https://api.mapbox.com/mapbox-gl-js/plugins/mapbox-gl-draw/v1.4.3/mapbox-gl-draw.js"
_DRAW_CSS      = "https://api.mapbox.com/mapbox-gl-js/plugins/mapbox-gl-draw/v1.4.3/mapbox-gl-draw.css"
_GEOCODER_JS   = "https://api.mapbox.com/mapbox-gl-js/plugins/mapbox-gl-geocoder/v5.0.3/mapbox-gl-geocoder.min.js"
_GEOCODER_CSS  = "https://api.mapbox.com/mapbox-gl-js/plugins/mapbox-gl-geocoder/v5.0.3/mapbox-gl-geocoder.css"
_TURF_JS       = "https://cdn.jsdelivr.net/npm/@turf/turf@6/turf.min.js"


def build_mapbox_html(
    mapbox_token:          str,
    turkey_gmu_geojson:    str,
    species_range_geojson: str,
    offices_geojson:       str,
    access_yes_geojson:    str,
    motorized_trails_geojson: str,
    trails_geojson:           str,
    water_geojson:         str,
    campgrounds_geojson:   str,
    closed_areas_geojson:  str = '{"type":"FeatureCollection","features":[]}',
    burned_areas_geojson:  str = '{"type":"FeatureCollection","features":[]}',
    logging_areas_geojson: str = '{"type":"FeatureCollection","features":[]}',
    snow_cover_geojson:    str = '{"type":"FeatureCollection","features":[]}',
    public_access_geojson: str = '{"type":"FeatureCollection","features":[]}',
    idfg_wma_geojson:          str = '{"type":"FeatureCollection","features":[]}',
    deciduous_forest_geojson:  str = '{"type":"FeatureCollection","features":[]}',
    cropland_geojson:          str = '{"type":"FeatureCollection","features":[]}',
    center: list = [-116.1, 43.7],
    zoom:   float = 9.5,
) -> str:
    """
    Build a self-contained Mapbox GL JS HTML string.

    Reads CSS, JS, and controls HTML from utils/static/, replaces __TOKEN__
    placeholders with live GeoJSON data and config values, then assembles
    a complete HTML document.
    """
    css      = (STATIC_DIR / "map.css").read_text(encoding="utf-8")
    js_tmpl  = (STATIC_DIR / "map.js").read_text(encoding="utf-8")
    controls = (STATIC_DIR / "map_controls.html").read_text(encoding="utf-8")
    tom_marker_img = _img_data_url(STATIC_DIR / "markers" / "turkey_tom.png")

    # Replace all data/config tokens
    tokens = {
        "__MAPBOX_TOKEN__":    mapbox_token,
        "__TURKEY_GMU__":      turkey_gmu_geojson,
        "__SPECIES_RANGE__":   species_range_geojson,
        "__OFFICES__":         offices_geojson,
        "__ACCESS_YES__":      access_yes_geojson,
        "__MOTORIZED_TRAILS__": motorized_trails_geojson,
        "__TRAILS__":           trails_geojson,
        "__WATER__":           water_geojson,
        "__CAMPGROUNDS__":     campgrounds_geojson,
        "__CLOSED_AREAS__":    closed_areas_geojson,
        "__BURNED_AREAS__":    burned_areas_geojson,
        "__LOGGING_AREAS__":   logging_areas_geojson,
        "__SNOW_COVER__":      snow_cover_geojson,
        "__PUBLIC_ACCESS__":   public_access_geojson,
        "__IDFG_WMA__":           idfg_wma_geojson,
        "__DECIDUOUS_FOREST__":   deciduous_forest_geojson,
        "__CROPLAND__":           cropland_geojson,
        "__CENTER_LNG__":      str(center[0]),
        "__CENTER_LAT__":      str(center[1]),
        "__ZOOM__":            str(zoom),
        "__TOM_MARKER_IMG__":  tom_marker_img,
    }
    js = js_tmpl
    for token, value in tokens.items():
        js = js.replace(token, value)

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <link href='{_MAPBOX_GL_CSS}' rel='stylesheet'/>
  <link href='{_DRAW_CSS}' rel='stylesheet'/>
  <link href='{_GEOCODER_CSS}' rel='stylesheet'/>
  <script src='{_MAPBOX_GL_JS}'></script>
  <script src='{_DRAW_JS}'></script>
  <script src='{_GEOCODER_JS}'></script>
  <script src='{_TURF_JS}'></script>
  <style>{css}</style>
</head>
<body>
<div id='map'></div>
{controls}
<script>{js}</script>
</body>
</html>"""
