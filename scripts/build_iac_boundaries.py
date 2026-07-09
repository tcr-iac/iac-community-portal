#!/usr/bin/env python3
"""Precompute convex-hull outlines for the IAC national map.

files/geojson/*.geojson are raw zip-code-derived boundaries — fragmented,
hole-riddled, and huge (Seattle alone is ~47MB / 1.7M vertices). Fetching
all ~30 of them on every page load is what makes iac_map.html slow and
what makes Seattle fail to render in the browser. This script reduces each
IAC to a single convex hull polygon, written once to files/iac_boundaries.json,
so the page fetches one small file instead of ~150MB of raw geometry.

Stdlib only. Run from the repo root or anywhere:
    python3 scripts/build_iac_boundaries.py
"""
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
GEOJSON_DIR = os.path.join(REPO_ROOT, "files", "geojson")
OUTPUT_PATH = os.path.join(REPO_ROOT, "files", "iac_boundaries.json")

# Four source files bundle a non-contiguous US territory's zips in with a
# mainland IAC's — not stray points, but tens of thousands of points each
# forming their own distinct, distant cluster with a clean gap (no
# ambiguous overlap) from the mainland data:
#   Seattle        -> Alaska (lat 51.8-71.3) + Guam/N.Mariana Is (lng 144-146,
#                      east of the date line); mainland is lat<=49.0, lng<0
#   Los Angeles    -> Hawaii (lat 18.9-22.2); mainland starts at lat 32.5
#   Miami          -> Puerto Rico / US Virgin Islands (lat 17.7-18.5);
#                      mainland (Florida) starts at lat 24.5
#   San Francisco  -> American Samoa (lat -14.4 to -11.1, southern
#                      hemisphere); mainland starts at lat 35.2
# Each cutoff below sits in the middle of its file's gap. One-off filters
# for these four files' known source-data issues, not general-purpose
# bounding boxes.
TERRITORY_FILTERS = {
    "Seattle": lambda lng, lat: lat <= 50.0 and lng < 0,
    "Los Angeles": lambda lng, lat: lat >= 30.0,
    "Miami": lambda lng, lat: lat >= 20.0,
    "San Francisco": lambda lng, lat: lat >= 30.0,
}


def cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def convex_hull(points):
    """Andrew's monotone chain. Points are (x, y) tuples; returns hull in
    the same (x, y) order, counter-clockwise, no repeated closing point."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def extract_points(geometry):
    """Walk every ring (exterior + holes) of a Polygon or MultiPolygon and
    return all [lng, lat] points as (x, y) tuples."""
    points = []
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "Polygon":
        rings = coords
    elif gtype == "MultiPolygon":
        rings = [ring for polygon in coords for ring in polygon]
    else:
        return points
    for ring in rings:
        for pt in ring:
            points.append((pt[0], pt[1]))
    return points


def points_from_geojson(data):
    points = []
    gtype = data.get("type")
    if gtype == "FeatureCollection":
        for feature in data.get("features", []):
            points.extend(extract_points(feature.get("geometry") or {}))
    elif gtype == "Feature":
        points.extend(extract_points(data.get("geometry") or {}))
    else:
        points.extend(extract_points(data))
    return points


def main():
    filenames = sorted(f for f in os.listdir(GEOJSON_DIR) if f.endswith(".geojson"))

    boundaries = {}
    for filename in filenames:
        name = filename[: -len(".geojson")]
        with open(os.path.join(GEOJSON_DIR, filename)) as f:
            data = json.load(f)

        points = points_from_geojson(data)
        if name in TERRITORY_FILTERS:
            before = len(points)
            keep = TERRITORY_FILTERS[name]
            points = [p for p in points if keep(p[0], p[1])]
            print(f"  ({name}: dropped {before - len(points):,} non-mainland territory points)")
        hull = convex_hull(points)
        # GeoJSON stores [lng, lat]; output as [lat, lng] for direct use
        # with Leaflet's L.polygon, rounded to 4 decimals (~11m precision).
        latlng_hull = [[round(lat, 4), round(lng, 4)] for lng, lat in hull]
        boundaries[name] = latlng_hull

        print(f"{name}: {len(points):>9,} points -> {len(latlng_hull):>3} hull points")

    with open(OUTPUT_PATH, "w") as f:
        json.dump(boundaries, f)

    size_kb = os.path.getsize(OUTPUT_PATH) / 1024
    print(f"\nWrote {OUTPUT_PATH}")
    print(f"{len(boundaries)} IACs, {size_kb:.1f} KB total")


if __name__ == "__main__":
    main()
