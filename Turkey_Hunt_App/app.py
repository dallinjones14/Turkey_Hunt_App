import streamlit as st
import json
from utils.data_loader import load_all_data
from utils.map_builder import build_mapbox_html

st.set_page_config(
    page_title="Turkey Hunt Insights - Southwest Idaho",
    page_icon="🦃",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Strip all Streamlit chrome and make the iframe fill the entire viewport
st.markdown("""
<style>
  #MainMenu, footer, header { display: none !important; }
  [data-testid="stSidebar"]       { display: none !important; }
  [data-testid="stDecoration"]    { display: none !important; }
  [data-testid="stStatusWidget"]  { display: none !important; }
  .block-container { padding: 0 !important; margin: 0 !important; max-width: 100% !important; }
  section[data-testid="stMain"] > div { padding: 0 !important; }
  html, body, [data-testid="stAppViewContainer"],
  [data-testid="stMain"], .main {
    height: 100% !important;
    overflow: hidden !important;
    background: #000 !important;
    padding: 0 !important;
    margin: 0 !important;
  }
  /* Pin the iframe to cover the full viewport */
  iframe {
    position: fixed !important;
    top: 0 !important; left: 0 !important;
    width: 100vw !important;
    height: 100vh !important;
    border: none !important;
    z-index: 9999 !important;
    display: block !important;
  }
</style>
""", unsafe_allow_html=True)

try:
    MAPBOX_TOKEN = st.secrets["mapbox"]["token"]
except (KeyError, FileNotFoundError):
    st.error("⚠️ Mapbox token not found. Add it to `.streamlit/secrets.toml`.")
    st.stop()


@st.cache_data(show_spinner="Loading hunt data...")
def get_data():
    return load_all_data()


data = get_data()

map_html = build_mapbox_html(
    mapbox_token          = MAPBOX_TOKEN,
    turkey_gmu_geojson    = json.dumps(data["turkey_gmu"]),
    species_range_geojson = json.dumps(data["species_range"]),
    offices_geojson       = json.dumps(data["offices"]),
    access_yes_geojson    = json.dumps(data["access_yes"]),
    motorized_trails_geojson = json.dumps(data["motorized_trails"]),
    trails_geojson           = json.dumps(data["trails"]),
    water_geojson         = json.dumps(data["water"]),
    campgrounds_geojson   = json.dumps(data["campgrounds"]),
    closed_areas_geojson  = json.dumps(data["closed_areas"]),
    burned_areas_geojson  = json.dumps(data["burned_areas"]),
    logging_areas_geojson = json.dumps(data["logging_areas"]),
    snow_cover_geojson    = json.dumps(data["snow_cover"]),
    public_access_geojson = json.dumps(data["public_access"]),
    idfg_wma_geojson          = json.dumps(data["idfg_wma"]),
    deciduous_forest_geojson  = json.dumps(data["deciduous_forest"]),
    cropland_geojson          = json.dumps(data["cropland"]),
)

st.components.v1.html(map_html, height=800, scrolling=False)
