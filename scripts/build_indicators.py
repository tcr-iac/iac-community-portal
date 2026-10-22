#!/usr/bin/env python3
"""Build the IAC Indicator Master + indicator values for the Lens.

Reads the researcher-editable source tables in data/indicators/ and writes
the JSON the frontend consumes in files/indicators/:

    data/indicators/components.csv          -> component list (7 + legacy group)
    data/indicators/indicator_master.csv    -> one row per indicator / measure
    data/indicators/sources.csv             -> one row per data source
    data/indicators/research/*.csv          -> long-format observations
                                               (indicator x geography x year)
    data/indicators/crosswalks/*.csv        -> optional geography allocation
                                               (e.g. school district -> ZIP)

    files/indicators/indicator_master.json  -> registry for selector / calculator
    files/indicators/values/<component>.json-> raw value + 1-10 score per geo/year

Nothing in community_data.json or service_centers.json is read for values or
modified: existing indicators stay where they are and are only *registered*
in the master (binding = legacy_zip_field / legacy_sc_field).

Same conventions as the other scripts in this folder: stdlib only, offline,
run from anywhere:
    python3 scripts/build_indicators.py           # validate + write
    python3 scripts/build_indicators.py --check   # validate only
    python3 scripts/build_indicators.py --src DIR --out DIR   # e.g. testing

Exit code 1 if any ERROR was found (nothing is written in that case).
"""
import argparse
import csv
import datetime
import glob
import json
import math
import os
import re
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
SRC_DIR = os.path.join(REPO_ROOT, "data", "indicators")
OUT_DIR = os.path.join(REPO_ROOT, "files", "indicators")
COMMUNITY_DATA_PATH = os.path.join(REPO_ROOT, "community_data.json")
SERVICE_CENTERS_PATH = os.path.join(REPO_ROOT, "files", "service_centers.json")

SCHEMA_VERSION = "1.0"

LEVELS = {"indicator", "measure"}
STATUSES = {"planned", "researching", "defined", "validated", "published"}
DIRECTIONS = {"higher_is_better", "lower_is_better", "neutral", ""}
BINDINGS = {"values_file", "legacy_zip_field", "legacy_sc_field"}
SCORING = {"linear_bands", "categorical", "UNKNOWN", ""}
GEO_LEVELS = {"zip", "service_center", "school_district", "county"}
PUBLISHED_GEO_LEVELS = {"zip", "service_center"}   # what the Lens map can draw
DERIVATIONS = {"", "mean_of_measures"}

REQUIRED_MASTER_COLS = ["indicator_id", "level", "component_id", "indicator_name", "status",
                        "geo_level", "binding", "scoring_method"]
REQUIRED_RESEARCH_COLS = ["indicator_id", "geo_level", "geo_id", "year", "raw_value", "source_id"]


class Log:
    def __init__(self):
        self.errors, self.warnings = [], []

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in reader]
        return reader.fieldnames or [], rows


def num(s):
    if s is None or s == "":
        return None
    try:
        v = float(str(s).replace(",", ""))
    except ValueError:
        return "NaN"
    return v if math.isfinite(v) else "NaN"


def years_list(s):
    return [int(y) for y in re.findall(r"\b(19\d\d|20\d\d)\b", s or "")]


def linear_band_score(x, worst, best):
    """Same rule the existing *_score fields follow (fitted to 98.7-99.5% of
    ZIPs): equal-width bands between `worst` (score 1) and `best` (score 10),
    tails clipped. Works for both directions because worst/best carry it."""
    v = 1 + 9 * (x - worst) / (best - worst)
    return max(1, min(10, int(math.floor(v + 0.5))))


def norm_geo_id(level, gid):
    gid = gid.strip()
    if level == "zip" and gid.isdigit() and len(gid) < 5:
        gid = gid.zfill(5)      # Excel strips leading zeros from ZIPs
    return gid


# --------------------------------------------------------------------------
def load_master(log):
    _, components = read_csv(os.path.join(SRC_DIR, "components.csv"))
    _, sources = read_csv(os.path.join(SRC_DIR, "sources.csv"))
    cols, master = read_csv(os.path.join(SRC_DIR, "indicator_master.csv"))

    for c in REQUIRED_MASTER_COLS:
        if c not in cols:
            log.error(f"indicator_master.csv: missing column '{c}'")
    comp_ids = {c["component_id"] for c in components}
    src_ids = {s["source_id"] for s in sources}

    seen = set()
    by_id = {}
    for i, r in enumerate(master, start=2):
        iid = r.get("indicator_id", "")
        where = f"indicator_master.csv line {i} ({iid or 'no id'})"
        if not re.fullmatch(r"[a-z0-9_]+", iid):
            log.error(f"{where}: indicator_id must be lowercase letters/digits/underscores")
        if iid in seen:
            log.error(f"{where}: duplicate indicator_id")
        seen.add(iid)
        by_id[iid] = r
        if r.get("level") not in LEVELS:
            log.error(f"{where}: level must be one of {sorted(LEVELS)}")
        if r.get("component_id") not in comp_ids:
            log.error(f"{where}: unknown component_id '{r.get('component_id')}'")
        if r.get("status") not in STATUSES:
            log.error(f"{where}: status must be one of {sorted(STATUSES)}")
        if r.get("direction", "") not in DIRECTIONS:
            log.error(f"{where}: direction must be one of {sorted(d for d in DIRECTIONS if d)}")
        if r.get("binding") not in BINDINGS:
            log.error(f"{where}: binding must be one of {sorted(BINDINGS)}")
        if r.get("geo_level") not in PUBLISHED_GEO_LEVELS:
            log.error(f"{where}: geo_level (published level) must be one of {sorted(PUBLISHED_GEO_LEVELS)}")
        if r.get("native_geo_level") and r["native_geo_level"] not in GEO_LEVELS:
            log.error(f"{where}: native_geo_level must be one of {sorted(GEO_LEVELS)}")
        if r.get("derivation", "") not in DERIVATIONS:
            log.error(f"{where}: derivation must be one of {sorted(d for d in DERIVATIONS if d)}")
        if r.get("source_id") and r["source_id"] not in src_ids:
            log.error(f"{where}: source_id '{r['source_id']}' not in sources.csv")
        sm = r.get("scoring_method", "")
        if sm not in SCORING:
            log.error(f"{where}: scoring_method must be one of {sorted(s for s in SCORING if s)}")
        if sm == "linear_bands":
            w, b = num(r.get("score_worst")), num(r.get("score_best"))
            if not isinstance(w, float) or not isinstance(b, float) or w == b:
                log.error(f"{where}: linear_bands needs numeric score_worst != score_best")
            elif r.get("direction") == "higher_is_better" and b < w:
                log.error(f"{where}: higher_is_better but score_best < score_worst")
            elif r.get("direction") == "lower_is_better" and b > w:
                log.error(f"{where}: lower_is_better but score_best > score_worst")
        if r.get("level") == "indicator" and r.get("status") in ("defined", "validated", "published") \
                and r.get("scoring_method") == "linear_bands":
            if not all(r.get(k) for k in ("legend_1", "legend_2", "legend_4", "legend_5")):
                log.warn(f"{where}: legend_1/2/4/5 missing; selector legend will be blank")
        if r.get("weight") and not isinstance(num(r["weight"]), float):
            log.error(f"{where}: weight must be numeric or blank")

    for iid, r in by_id.items():
        if r.get("level") == "measure":
            p = r.get("parent_indicator_id")
            if p not in by_id:
                log.error(f"indicator_master.csv ({iid}): parent_indicator_id '{p}' not found")
        if r.get("derivation") == "mean_of_measures":
            kids = [k for k, v in by_id.items() if v.get("parent_indicator_id") == iid]
            if not kids:
                log.error(f"indicator_master.csv ({iid}): mean_of_measures but no measures point to it")
    return components, sources, master, by_id


def load_crosswalks(log):
    """{(from_level, to_level): {from_id: [(to_id, weight), ...]}}"""
    xw = defaultdict(lambda: defaultdict(list))
    for path in sorted(glob.glob(os.path.join(SRC_DIR, "crosswalks", "*.csv"))):
        _, rows = read_csv(path)
        name = os.path.basename(path)
        for i, r in enumerate(rows, start=2):
            w = num(r.get("weight"))
            if not isinstance(w, float) or w < 0:
                log.error(f"crosswalks/{name} line {i}: weight must be a non-negative number")
                continue
            fl, tl = r.get("from_geo_level"), r.get("to_geo_level")
            xw[(fl, tl)][norm_geo_id(fl, r.get("from_geo_id", ""))].append(
                (norm_geo_id(tl, r.get("to_geo_id", "")), w))
    return xw


def load_research(log, by_id):
    obs = []   # dicts with indicator_id, geo_level, geo_id, year, raw, moe
    files = sorted(glob.glob(os.path.join(SRC_DIR, "research", "*.csv")))
    seen = {}
    for path in files:
        name = os.path.basename(path)
        cols, rows = read_csv(path)
        for c in REQUIRED_RESEARCH_COLS:
            if c not in cols:
                log.error(f"research/{name}: missing column '{c}'")
        if any(c not in cols for c in REQUIRED_RESEARCH_COLS):
            continue
        for i, r in enumerate(rows, start=2):
            where = f"research/{name} line {i}"
            iid = r["indicator_id"]
            m = by_id.get(iid)
            if not m:
                log.error(f"{where}: indicator_id '{iid}' is not in indicator_master.csv")
                continue
            if m.get("binding") != "values_file":
                log.error(f"{where}: '{iid}' is a legacy indicator; its values live in community_data.json")
                continue
            if m.get("derivation"):
                log.error(f"{where}: '{iid}' is derived ({m['derivation']}); supply its measures instead")
                continue
            lvl = r["geo_level"]
            if lvl not in GEO_LEVELS:
                log.error(f"{where}: geo_level '{lvl}' not in {sorted(GEO_LEVELS)}")
                continue
            gid = norm_geo_id(lvl, r["geo_id"])
            if lvl == "zip" and not re.fullmatch(r"\d{5}", gid):
                log.error(f"{where}: zip geo_id '{r['geo_id']}' is not a 5-digit ZIP")
                continue
            if not re.fullmatch(r"(19|20)\d\d", r["year"]):
                log.error(f"{where}: year '{r['year']}' must be a 4-digit year (use the data year / ACS end year)")
                continue
            raw = num(r["raw_value"])
            if not isinstance(raw, float):
                log.error(f"{where}: raw_value '{r['raw_value']}' is not a number"
                          + (" (leave the row out if the source suppresses it)" if r["raw_value"] else ""))
                continue
            if m.get("value_type") == "percent" and not (0 <= raw <= 100):
                log.error(f"{where}: percent value {raw} outside 0-100 (enter 21.3, not 0.213)")
                continue
            if r["source_id"] != m.get("source_id") and m.get("source_id"):
                log.warn(f"{where}: source_id '{r['source_id']}' differs from master source '{m['source_id']}'")
            key = (iid, lvl, gid, r["year"])
            if key in seen:
                log.error(f"{where}: duplicate of line {seen[key]} (same indicator, geography, year)")
                continue
            seen[key] = f"{name}:{i}"
            moe = num(r.get("moe"))
            obs.append({"indicator_id": iid, "geo_level": lvl, "geo_id": gid, "year": int(r["year"]),
                        "raw": raw, "moe": moe if isinstance(moe, float) else None})
    return obs, files


def to_published_geo(log, obs, by_id, xw):
    """Move every observation to its indicator's published geo_level, using a
    crosswalk when the research geography differs (e.g. district -> ZIP).
    Allocated value = weight-normalised average of contributing geographies."""
    out = defaultdict(dict)   # (iid, year) -> {geo_id: {"raw":..,"moe":..}}
    pending = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))  # (iid,year)->{to:[sum w*v, sum w]}
    missing_xw = set()
    for o in obs:
        target = by_id[o["indicator_id"]]["geo_level"]
        k = (o["indicator_id"], o["year"])
        if o["geo_level"] == target:
            out[k][o["geo_id"]] = {"raw": o["raw"], "moe": o["moe"]}
            continue
        table = xw.get((o["geo_level"], target))
        if not table:
            missing_xw.add((o["geo_level"], target, o["indicator_id"]))
            continue
        links = table.get(o["geo_id"])
        if not links:
            log.warn(f"{o['indicator_id']} {o['year']}: {o['geo_level']} {o['geo_id']} has no rows in the crosswalk")
            continue
        for to_id, w in links:
            acc = pending[k][to_id]
            acc[0] += w * o["raw"]
            acc[1] += w
    for k, d in pending.items():
        for to_id, (s, w) in d.items():
            if w > 0 and to_id not in out[k]:
                out[k][to_id] = {"raw": s / w, "moe": None, "allocated": True}
    for fl, tl, iid in sorted(missing_xw):
        log.warn(f"{iid}: research data is at '{fl}' but published level is '{tl}' and "
                 f"data/indicators/crosswalks has no {fl}->{tl} rows; those values are NOT published")
    return out


def derive(by_id, series):
    for iid, m in by_id.items():
        if m.get("derivation") != "mean_of_measures":
            continue
        kids = [k for k, v in by_id.items() if v.get("parent_indicator_id") == iid]
        years = {y for (k, y) in series if k in kids}
        for y in years:
            per_kid = [series.get((k, y), {}) for k in kids]
            common = set(per_kid[0]).intersection(*per_kid[1:]) if per_kid else set()
            for g in common:
                series[(iid, y)][g] = {"raw": sum(p[g]["raw"] for p in per_kid) / len(per_kid),
                                       "moe": None, "derived": True}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="validate only, write nothing")
    ap.add_argument("--src", help="source tables folder (default: data/indicators)")
    ap.add_argument("--out", help="output folder (default: files/indicators)")
    args = ap.parse_args()
    global SRC_DIR, OUT_DIR
    SRC_DIR = os.path.abspath(args.src) if args.src else SRC_DIR
    OUT_DIR = os.path.abspath(args.out) if args.out else OUT_DIR

    log = Log()
    components, sources, master, by_id = load_master(log)
    xw = load_crosswalks(log)
    obs, files = load_research(log, by_id)

    with open(COMMUNITY_DATA_PATH, encoding="utf-8") as f:
        known_zips = set(json.load(f).keys())
    with open(SERVICE_CENTERS_PATH, encoding="utf-8") as f:
        known_scids = set(json.load(f).keys())

    series = to_published_geo(log, obs, by_id, xw)
    derive(by_id, series)

    # Score + drop geographies the Lens does not know about (reported, not fatal)
    unknown = defaultdict(set)
    for (iid, year), geos in series.items():
        m = by_id[iid]
        lvl = m["geo_level"]
        known = known_zips if lvl == "zip" else known_scids
        for g in list(geos):
            if g not in known:
                unknown[iid].add(g)
                del geos[g]
                continue
            if m.get("scoring_method") == "linear_bands":
                geos[g]["score"] = linear_band_score(geos[g]["raw"], float(m["score_worst"]),
                                                     float(m["score_best"]))
    for iid, gs in unknown.items():
        log.warn(f"{iid}: {len(gs)} geographies not in community_data.json / service_centers.json "
                 f"were skipped (e.g. {sorted(gs)[:5]})")

    # ---- report ----
    print(f"Indicator master: {len(master)} rows "
          f"({sum(1 for r in master if r['level'] == 'indicator')} indicators, "
          f"{sum(1 for r in master if r['level'] == 'measure')} measures), {len(components)} components")
    print(f"Research files: {len(files)}, observations: {len(obs)}")
    for (iid, y), geos in sorted(series.items()):
        if geos:
            print(f"  {iid} {y}: {len(geos)} geographies published")
    for w in log.warnings:
        print("WARNING:", w)
    for e in log.errors:
        print("ERROR:", e)
    if log.errors:
        print(f"\n{len(log.errors)} error(s): nothing written. Fix the rows above and re-run.")
        sys.exit(1)
    if args.check:
        print("\nCheck passed (--check: nothing written).")
        return

    # ---- write ----
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    os.makedirs(os.path.join(OUT_DIR, "values"), exist_ok=True)

    values_by_component = defaultdict(dict)
    data_summary = {}
    for iid, m in by_id.items():
        if m["binding"] != "values_file":
            continue
        yrs = sorted(y for (k, y), g in series.items() if k == iid and g)
        values = {}
        for y in yrs:
            values[str(y)] = {
                g: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in rec.items() if v is not None}
                for g, rec in sorted(series[(iid, y)].items())
            }
        data_summary[iid] = {"years_available": yrs, "latest_year": yrs[-1] if yrs else None,
                             "geo_count_latest": len(series[(iid, yrs[-1])]) if yrs else 0}
        if m["status"] in ("defined", "validated", "published") or yrs:
            values_by_component[m["component_id"]][iid] = {
                "geo_level": m["geo_level"], "years": yrs,
                "latest_year": yrs[-1] if yrs else None, "values": values}

    def legend(m):
        if not m.get("legend_1"):
            return None
        return [m.get("legend_1", ""), m.get("legend_2", ""), "", m.get("legend_4", ""), m.get("legend_5", "")]

    def binding(m):
        b = {"type": m["binding"]}
        if m["binding"] == "values_file":
            b["values_file"] = f"values/{m['component_id']}.json"
        else:
            b.update({"selector_key": m.get("legacy_selector_key") or None,
                      "score_field": m.get("legacy_score_field") or None,
                      "raw_field": m.get("legacy_raw_field") or None})
        return b

    indicators = []
    for m in master:
        w = num(m.get("weight"))
        indicators.append({
            "id": m["indicator_id"], "level": m["level"],
            "parent_id": m.get("parent_indicator_id") or None,
            "component_id": m["component_id"],
            "priority_rank": int(m["priority_rank"]) if m.get("priority_rank", "").isdigit() else None,
            "name": m["indicator_name"], "short_label": m.get("short_label") or m["indicator_name"],
            "status": m["status"], "definition": m.get("definition") or None,
            "unit": m.get("unit") or None, "value_type": m.get("value_type") or None,
            "direction": m.get("direction") or None,
            "geo_level": m["geo_level"], "native_geo_level": m.get("native_geo_level") or m["geo_level"],
            "source_id": m.get("source_id") or None, "source_variables": m.get("source_variables") or None,
            "derivation": m.get("derivation") or None, "methodology": m.get("methodology") or None,
            "release_cycle": m.get("release_cycle") or None,
            "years_planned": years_list(m.get("years_planned")) + (["latest"] if "latest" in m.get("years_planned", "") else []),
            "scoring": {"method": m.get("scoring_method") or None,
                        "worst": num(m.get("score_worst")) if m.get("score_worst") else None,
                        "best": num(m.get("score_best")) if m.get("score_best") else None,
                        "status": m.get("scoring_status") or None},
            "legend": legend(m),
            "weight": w if isinstance(w, float) else None,
            "binding": binding(m),
            "research": {"indicator": m.get("research_indicator") or None,
                         "match_type": m.get("match_type") or None,
                         "rationale": m.get("match_rationale") or None},
            "data": data_summary.get(m["indicator_id"]),
            "notes": m.get("notes") or None,
        })

    master_out = {
        "schema_version": SCHEMA_VERSION, "generated_at": now,
        "generated_by": "scripts/build_indicators.py from data/indicators/*.csv - do not edit by hand",
        "components": [{"id": c["component_id"], "name": c["component_name"],
                        "display_order": int(c["display_order"]),
                        "in_top10_structure": c.get("in_top10_structure") == "yes",
                        "weight": num(c["weight"]) if c.get("weight") else None} for c in components],
        "sources": {s["source_id"]: {k: (v or None) for k, v in s.items() if k != "source_id"} for s in sources},
        "indicators": indicators,
    }
    with open(os.path.join(OUT_DIR, "indicator_master.json"), "w", encoding="utf-8") as f:
        json.dump(master_out, f, ensure_ascii=False, indent=1)

    expected = set(values_by_component)
    for cid, inds in values_by_component.items():
        with open(os.path.join(OUT_DIR, "values", f"{cid}.json"), "w", encoding="utf-8") as f:
            json.dump({"schema_version": SCHEMA_VERSION, "component_id": cid, "generated_at": now,
                       "indicators": inds}, f, ensure_ascii=False, separators=(",", ":"))
    for stale in glob.glob(os.path.join(OUT_DIR, "values", "*.json")):
        if os.path.basename(stale)[:-5] not in expected:
            os.remove(stale)

    print(f"\nWrote {os.path.relpath(os.path.join(OUT_DIR, 'indicator_master.json'), REPO_ROOT)}")
    for cid in sorted(values_by_component):
        p = os.path.join(OUT_DIR, "values", f"{cid}.json")
        print(f"Wrote {os.path.relpath(p, REPO_ROOT)} ({os.path.getsize(p) / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
