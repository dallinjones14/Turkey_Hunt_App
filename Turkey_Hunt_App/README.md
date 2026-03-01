# Idaho Turkey Hunt Map

Interactive web-based hunting map for Wild Turkey (Merriam's & Rio Grande)
in Idaho, built with Mapbox GL JS and Streamlit.

## Quick Start

### 1. Clone and install
    git clone https://github.com/yourusername/idaho-turkey-hunt-map
    cd idaho-turkey-hunt-map
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt

### 2. Add your Mapbox token
    cp .streamlit/secrets.toml.template .streamlit/secrets.toml
    # Edit secrets.toml and paste your Mapbox public token

### 3. Run the data pipeline
    python pipelines/run_pipelines.py

### 4. Launch the app
    streamlit run app.py

## Data Sources

| Layer | Endpoint |
|---|---|
| Hunt Units | IDFG ControlledHunts_All FeatureServer/0 |
| Species Range | IDFG Species_Ranges FeatureServer/1 |
| Regional Offices | IDFG Regional Office Locations FeatureServer/0 |
| AccessYes | IDFG AccessYes MapServer/1 |
| Roads | USFS MVUM + BLM |
| Water | USGS NHD |
| Habitat | Derived (NHD riparian buffers) |

## Deployment (Streamlit Cloud)

1. Push repo to GitHub (secrets.toml is gitignored)
2. Go to share.streamlit.io → New app → select repo → app.py
3. Settings → Secrets → paste your [mapbox] token block
4. Deploy

## Project Structure

    app.py                        ← Streamlit application
    requirements.txt
    utils/
        data_loader.py            ← Load processed GeoJSON files
        map_builder.py            ← Build Mapbox GL JS HTML
    pipelines/
        run_pipelines.py              ← Master runner
        01_fetch_hunt_units.py        ← IDFG turkey hunt units
        02_fetch_species_range.py     ← IDFG species range
        03_fetch_regional_offices.py
        04_fetch_access_yes.py        ← AccessYes properties
        05_fetch_roads.py             ← USFS MVUM + BLM roads
        06_fetch_water.py             ← USGS NHD water
        07_build_habitat_score.py     ← Roost habitat model
    data/
        raw/                      ← gitignored
        processed/                ← committed after pipeline runs
