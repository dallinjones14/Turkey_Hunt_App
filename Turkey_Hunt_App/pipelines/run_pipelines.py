"""
Master pipeline runner.
Run from anywhere: python pipelines/run_pipelines.py
"""
import subprocess
import sys
from pathlib import Path

PIPELINES_DIR = Path(__file__).parent
PROJECT_ROOT  = PIPELINES_DIR.parent

STEPS = [
    ("01_build_turkey_gmu.py",       "Building master Turkey GMU from CSV + IDFG geometry"),
    ("02_fetch_species_range.py",    "Fetching wild turkey species range"),
    ("03_fetch_regional_offices.py", "Fetching IDFG regional office locations"),
    ("04_fetch_access_yes.py",       "Fetching AccessYes program properties"),
    ("05_fetch_roads.py",            "Fetching MVUM + BLM access roads"),
    ("06_fetch_water.py",            "Fetching NHD water features"),
    ("07_fetch_campgrounds.py",      "Fetching USFS campground sites"),
    ("08_fetch_closed_areas.py",     "Fetching IDFG closed to turkey hunting areas"),
    ("09_fetch_disturbance.py",      "Fetching burned areas and logging clearings"),
    ("10_fetch_public_access.py",    "Fetching Idaho Surface Management Agency (Public Access)"),
    ("11_fetch_idfg_wma.py",         "Fetching IDFG Wildlife Management Areas (WMA)"),
    ("12_clip_snow.py",              "Clipping NIC IMS snow raster + vectorizing snow cover"),
]


def run_step(script: str, description: str):
    print(f"\n{'='*60}")
    print(f"  {description}")
    print(f"{'='*60}")
    result = subprocess.run(
        [sys.executable, PIPELINES_DIR / script],
        capture_output=False
    )
    if result.returncode != 0:
        print(f"❌  {script} failed — stopping pipeline.")
        sys.exit(1)
    print(f"✅  {script} complete.")


if __name__ == "__main__":
    (PIPELINES_DIR / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (PIPELINES_DIR / "data" / "processed").mkdir(parents=True, exist_ok=True)
    for script, description in STEPS:
        run_step(script, description)
    print("\n🎉  Pipeline complete! Run: streamlit run app.py")
