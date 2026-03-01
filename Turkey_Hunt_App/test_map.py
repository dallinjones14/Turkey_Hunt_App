"""
Quick diagnostic: generates test_map.html from the same data pipeline as the app.
Open test_map.html directly in Chrome to test the map outside of Streamlit.

Usage:
    cd Turkey_Hunt_App
    python test_map.py
    # Then open test_map.html in Chrome
"""
import json
import sys
from pathlib import Path

# Ensure project root is on the import path
sys.path.insert(0, str(Path(__file__).parent))

from utils.data_loader import load_all_data
from utils.map_builder import build_mapbox_html

# Try to load token from .streamlit/secrets.toml
TOKEN = None
secrets_path = Path(".streamlit/secrets.toml")
if secrets_path.exists():
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # pip install tomli for Python < 3.11
    with open(secrets_path, "rb") as f:
        secrets = tomllib.load(f)
    TOKEN = secrets.get("mapbox", {}).get("token")

if not TOKEN:
    print("ERROR: Could not read Mapbox token from .streamlit/secrets.toml")
    sys.exit(1)

print("Loading data...")
data = load_all_data()

print("Building HTML...")
html = build_mapbox_html(
    mapbox_token          = TOKEN,
    turkey_gmu_geojson    = json.dumps(data["turkey_gmu"]),
    species_range_geojson = json.dumps(data["species_range"]),
    offices_geojson       = json.dumps(data["offices"]),
    access_yes_geojson    = json.dumps(data["access_yes"]),
    roads_geojson         = json.dumps(data["roads"]),
    water_geojson         = json.dumps(data["water"]),
    campgrounds_geojson   = json.dumps(data["campgrounds"]),
    closed_areas_geojson  = json.dumps(data["closed_areas"]),
    burned_areas_geojson  = json.dumps(data["burned_areas"]),
    logging_areas_geojson = json.dumps(data["logging_areas"]),
)

out = Path("test_map.html")
out.write_text(html, encoding="utf-8")
size_mb = out.stat().st_size / 1e6
print(f"Written: {out.absolute()}")
print(f"File size: {size_mb:.2f} MB")
print()
print("Open test_map.html directly in Chrome (File > Open) to test the map.")
print("If the map works there but not in Streamlit, the issue is Streamlit-side.")
