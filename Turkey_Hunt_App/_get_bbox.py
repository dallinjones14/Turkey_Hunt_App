import json
from pathlib import Path
from shapely.geometry import shape

p = Path("pipelines/data/processed/master_turkey_gmu.geojson")
d = json.loads(p.read_text())
target = {"22", "31", "32", "32A", "38"}
print("Total features:", len(d["features"]))
print("Unique GMUs:", sorted(set(f["properties"].get("GMU") for f in d["features"])))
print("Target features:", sum(1 for f in d["features"] if f["properties"].get("GMU") in target))
xs, ys = [], []
for f in d["features"]:
    if f["properties"].get("GMU") in target:
        b = shape(f["geometry"]).bounds
        xs += [b[0], b[2]]
        ys += [b[1], b[3]]
print(f"Bbox: [{min(xs):.4f}, {min(ys):.4f}, {max(xs):.4f}, {max(ys):.4f}]")

# Also check feature counts for other datasets
for fname in ["access_roads.geojson","access_yes.geojson","campgrounds.geojson",
              "closed_areas.geojson","species_range.geojson"]:
    fp = Path("pipelines/data/processed") / fname
    if fp.exists():
        fc = json.loads(fp.read_text())
        print(f"{fname}: {len(fc.get('features', []))} features")
