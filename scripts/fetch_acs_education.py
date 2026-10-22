#!/usr/bin/env python3
"""Fetch ACS educational attainment for every IAC ZIP and write it as a
research table for scripts/build_indicators.py.

Produces data/indicators/research/education_acs.csv with two Education
indicators from the Indicator Master, at ZCTA (ZIP) level:

    edu_bachelors_degree_or_higher           % of adults 25+ with BA or higher
    edu_postsecondary_educational_attainment % of adults 25+ with associate's
                                             or higher (definition: see
                                             indicator_master.csv; NEEDS
                                             CONFIRMATION)

Source: Census API, ACS 5-year detailed tables
    year >= 2012 : B15003 (Educational Attainment, Population 25+)
    2010 - 2011  : B15002 (same, by sex - male + female are summed)
    2000         : not in ACS. Census 2000 SF3 P037 is a different product and
                   ZCTA boundaries changed in 2010 and 2020; use NHGIS
                   time-series tables (geographically standardised) instead.

The "year" written is the ACS end year (2024 = 2020-2024 5-year estimates).
Before using any column the script checks its label against the Census
variable metadata, so a renumbered table aborts instead of silently writing
wrong data. Percent MOE uses the Census derived-proportion formula.

Needs network access to api.census.gov (stdlib only). An API key is optional
but recommended: set CENSUS_API_KEY.

    python3 scripts/fetch_acs_education.py --years 2024
    python3 scripts/fetch_acs_education.py --years 2012 2020 2024
then:
    python3 scripts/build_indicators.py
"""
import argparse
import csv
import datetime
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
COMMUNITY_DATA_PATH = os.path.join(REPO_ROOT, "community_data.json")
OUTPUT_PATH = os.path.join(REPO_ROOT, "data", "indicators", "research", "education_acs.csv")
API = "https://api.census.gov/data/{year}/acs/acs5"

# FIPS for the states in community_data.json (MN, IA, ND, SD, WI). Only used
# for ACS years before 2020, when ZCTA queries had to be nested in a state.
STATE_FIPS = {"MN": "27", "IA": "19", "ND": "38", "SD": "46", "WI": "55"}

# variable -> words its label must contain (case-insensitive)
B15003 = {
    "total": {"B15003_001": ["total"]},
    "assoc": {"B15003_021": ["associate"]},
    "bach": {"B15003_022": ["bachelor"]},
    "grad": {"B15003_023": ["master"], "B15003_024": ["professional"], "B15003_025": ["doctorate"]},
}
B15002 = {
    "total": {"B15002_001": ["total"]},
    "assoc": {"B15002_014": ["male", "associate"], "B15002_031": ["female", "associate"]},
    "bach": {"B15002_015": ["male", "bachelor"], "B15002_032": ["female", "bachelor"]},
    "grad": {"B15002_016": ["male", "master"], "B15002_017": ["male", "professional"],
             "B15002_018": ["male", "doctorate"], "B15002_033": ["female", "master"],
             "B15002_034": ["female", "professional"], "B15002_035": ["female", "doctorate"]},
}

INDICATORS = {
    "edu_bachelors_degree_or_higher": ["bach", "grad"],
    "edu_postsecondary_educational_attainment": ["assoc", "bach", "grad"],
}

COLS = ["indicator_id", "geo_level", "geo_id", "geo_name", "year", "raw_value", "moe", "numerator",
        "denominator", "source_id", "source_detail", "researcher", "collected_date", "notes"]


def fetch_json(url, retries=3):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                raise
            err = e
        except (urllib.error.URLError, TimeoutError) as e:
            err = e
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed after {retries} attempts: {url} ({err})")


def with_key(params):
    key = os.environ.get("CENSUS_API_KEY")
    if key:
        params = dict(params, key=key)
    return urllib.parse.urlencode(params, safe=":*,")


def check_labels(year, table):
    for group in table.values():
        for var, words in group.items():
            meta = fetch_json(f"{API.format(year=year)}/variables/{var}E.json")
            label = meta.get("label", "").lower()
            if not all(w in label for w in words):
                sys.exit(f"ABORT: {year} {var} label is '{meta.get('label')}', expected words {words}. "
                         "Table layout differs from what this script assumes; update the mapping.")
            # 'male' is a substring of 'female'; make sure male vars are not female
            if "male" in words and "female" not in words and "female" in label:
                sys.exit(f"ABORT: {year} {var} is a female row but mapped as male.")


def fetch_rows(year, variables):
    get = "NAME," + ",".join(f"{v}E,{v}M" for v in variables)
    base = API.format(year=year)
    try:
        data = fetch_json(f"{base}?{with_key({'get': get, 'for': 'zip code tabulation area:*'})}")
        return data[0], data[1:]
    except urllib.error.HTTPError:
        pass   # pre-2020 vintages require ZCTA nested within state
    header, rows = None, []
    for st, fips in STATE_FIPS.items():
        data = fetch_json(f"{base}?{with_key({'get': get, 'for': 'zip code tabulation area:*', 'in': f'state:{fips}'})}")
        header = data[0]
        rows.extend(data[1:])
        time.sleep(0.2)
    return header, rows


def val(x):
    """Census uses large negative sentinels (e.g. -666666666) for N/A."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v < 0 else v


def build_records(year, table, header, rows, zips, today):
    idx = {h: i for i, h in enumerate(header)}
    total_var = next(iter(table["total"]))
    out, skipped = [], 0
    source_detail = (f"ACS {year - 4}-{year} 5-year, table {total_var.split('_')[0]}")
    for r in rows:
        zcta = r[idx["zip code tabulation area"]]
        if zcta not in zips:
            continue
        x, x_moe = val(r[idx[total_var + "E"]]), val(r[idx[total_var + "M"]])
        if not x:
            skipped += 1
            continue
        for iid, groups in INDICATORS.items():
            vars_ = [v for g in groups for v in table[g]]
            ests = [val(r[idx[v + "E"]]) for v in vars_]
            moes = [val(r[idx[v + "M"]]) for v in vars_]
            if any(e is None for e in ests):
                continue
            y = sum(ests)
            p = y / x
            y_moe = math.sqrt(sum((m or 0) ** 2 for m in moes))
            rad = y_moe ** 2 - (p ** 2) * ((x_moe or 0) ** 2)
            if rad < 0:   # Census guidance: fall back to the ratio formula
                rad = y_moe ** 2 + (p ** 2) * ((x_moe or 0) ** 2)
            p_moe = math.sqrt(rad) / x
            out.append({
                "indicator_id": iid, "geo_level": "zip", "geo_id": zcta, "geo_name": r[idx["NAME"]],
                "year": year, "raw_value": round(100 * p, 2), "moe": round(100 * p_moe, 2),
                "numerator": int(y), "denominator": int(x), "source_id": "acs5_b15003",
                "source_detail": source_detail + " (" + ",".join(vars_) + ")",
                "researcher": "scripts/fetch_acs_education.py", "collected_date": today,
                "notes": "High MOE: interpret with caution" if p_moe > 0.10 else "",
            })
    return out, skipped


def main():
    ap = argparse.ArgumentParser(description="Fetch ACS education indicators for IAC ZIPs")
    ap.add_argument("--years", nargs="+", type=int, default=[2024],
                    help="ACS 5-year end years, e.g. 2012 2020 2024 (minimum 2010)")
    ap.add_argument("--out", default=OUTPUT_PATH)
    args = ap.parse_args()

    with open(COMMUNITY_DATA_PATH, encoding="utf-8") as f:
        zips = set(json.load(f).keys())
    today = datetime.date.today().isoformat()

    records = []
    for year in sorted(set(args.years)):
        if year < 2010:
            sys.exit(f"{year}: ACS 5-year ZCTA data starts with 2010 (2006-2010). "
                     "For 2000 use Census SF3 via NHGIS; see docs/indicators/README.md.")
        table = B15003 if year >= 2012 else B15002
        print(f"{year}: checking variable labels...")
        check_labels(year, table)
        variables = [v for g in table.values() for v in g]
        header, rows = fetch_rows(year, variables)
        recs, skipped = build_records(year, table, header, rows, zips, today)
        n = len({r["geo_id"] for r in recs})
        print(f"{year}: {len(rows)} ZCTAs returned, {n} IAC ZIPs written, "
              f"{skipped} IAC ZCTAs with no adults 25+, {len(zips) - n - skipped} IAC ZIPs not a ZCTA in {year}")
        records.extend(recs)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(sorted(records, key=lambda r: (r["indicator_id"], r["year"], r["geo_id"])))
    print(f"Wrote {len(records)} rows to {os.path.relpath(args.out, REPO_ROOT)}")
    print("Next: review the file, set status=validated in indicator_master.csv, run build_indicators.py")


if __name__ == "__main__":
    main()
