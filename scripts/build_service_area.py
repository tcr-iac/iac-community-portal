#!/usr/bin/env python3
"""Precompute the real, current IAC full-service-area outline.

The old approach (convex hull of the 71 Service Center anchor points) was
blind to real gaps in the footprint and always overshot to the outermost
points — which is exactly why the map's green service area used to swallow
Bismarck, Minot, and Tomah even though none of their ZIPs are in our data.

files/geojson/Minneapolis-St Paul.geojson looked like a fix at first (it's
real zip-derived boundary data) but turned out to be stale: Precious noted
months ago that the zip list used to build the original static boundaries
was "too inclusive," and it still is — community_data.json today has zips
in the Bismarck/Minot area's 585xx/587xx ranges that aren't in that old
file's source list, and vice versa. It predates all of the ZIP corrections
made since.

So this fetches each ZIP's real polygon from the Census TIGERweb API using
today's actual community_data.json zip list (2,285 zips, source of truth,
maintained by Precious), dissolves them into one shape with Shapely, and
simplifies it for the browser. One-time offline precompute — this is
exactly why it can't run live in iac_map.html: fetching and unioning
thousands of ZIP polygons in-browser on every page load is what the
existing files/geojson/*.geojson comment already documented as too slow
(Seattle alone: ~47MB / 1.7M vertices for one region).

Needs: requests, shapely
Run from the repo root or anywhere:
    python scripts/build_service_area.py
"""
import json
import os
import time

import requests
from shapely.geometry import shape
from shapely.ops import unary_union

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
COMMUNITY_DATA_PATH = os.path.join(REPO_ROOT, "community_data.json")
OUTPUT_PATH = os.path.join(REPO_ROOT, "files", "iac_full_service_area.json")

TIGERWEB_URL = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer/2/query"
BATCH_SIZE = 150
SIMPLIFY_TOLERANCE = 0.004  # ~450m at this latitude


def fetch_batch(zips):
    where = "ZCTA5 IN (" + ",".join(f"'{z}'" for z in zips) + ")"
    params = {"where": where, "outFields": "ZCTA5", "f": "geojson", "outSR": "4326"}
    resp = requests.get(TIGERWEB_URL, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data.get("features", [])


def rings_to_latlng(geom):
    polygons = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    out = []
    for poly in polygons:
        rings = [list(poly.exterior.coords)] + [list(r.coords) for r in poly.interiors]
        out.append([[[round(lat, 5), round(lng, 5)] for lng, lat in ring] for ring in rings])
    return out


def main():
    with open(COMMUNITY_DATA_PATH, encoding="utf-8") as f:
        community_data = json.load(f)
    all_zips = sorted(community_data.keys())
    print(f"{len(all_zips)} zips in community_data.json")

    geoms = []
    missing = []
    for i in range(0, len(all_zips), BATCH_SIZE):
        batch = all_zips[i:i + BATCH_SIZE]
        try:
            features = fetch_batch(batch)
        except Exception as e:
            print(f"  batch {i // BATCH_SIZE + 1}: FAILED ({e}), skipping {len(batch)} zips")
            missing.extend(batch)
            continue
        found = {f["properties"]["ZCTA5"] for f in features}
        missing.extend(z for z in batch if z not in found)
        for feat in features:
            geoms.append(shape(feat["geometry"]))
        print(f"  batch {i // BATCH_SIZE + 1}/{(len(all_zips) - 1) // BATCH_SIZE + 1}: "
              f"{len(features)}/{len(batch)} zips returned ({len(geoms)} total so far)")
        time.sleep(0.2)  # be polite to the public API

    if missing:
        print(f"\n{len(missing)} zips had no TIGERweb boundary (invalid/retired ZCTAs, not a bug): "
              f"{missing[:15]}{'...' if len(missing) > 15 else ''}")

    print(f"\nDissolving {len(geoms)} zip polygons...")
    dissolved = unary_union(geoms)
    before_pts = sum(len(p.exterior.coords) + sum(len(r.coords) for r in p.interiors)
                      for p in ([dissolved] if dissolved.geom_type == "Polygon" else dissolved.geoms))

    simplified = dissolved.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
    after_pts = sum(len(p.exterior.coords) + sum(len(r.coords) for r in p.interiors)
                     for p in ([simplified] if simplified.geom_type == "Polygon" else simplified.geoms))

    rings = rings_to_latlng(simplified)

    with open(OUTPUT_PATH, "w") as f:
        json.dump(rings, f)

    size_kb = os.path.getsize(OUTPUT_PATH) / 1024
    print(f"{before_pts:,} points -> {after_pts:,} points ({simplified.geom_type}, "
          f"{len(rings)} polygon piece(s))")
    print(f"Wrote {OUTPUT_PATH} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
