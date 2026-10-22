# IAC Indicator Architecture — Audit & Education Pilot

Audit of `tcr-iac/iac-community-portal` at commit `1a8786d` (2026-09-06) and of
the research workbook `IAC_Indicator_Structure.xlsx`, followed by the design and
implementation of the Education pilot.

Labels used throughout:

| Label | Meaning |
|---|---|
| **EXISTING** | In the repository today, verified by reading the code/data |
| **REQUIRED** | Needed for the stated goals (selector → trends → calculator) |
| **RECOMMENDED** | Advisable but a judgement call |
| **FUTURE** | Planned for later phases, intentionally not built now |
| **UNKNOWN / NEEDS CONFIRMATION** | Information missing from the repo/workbook; a person must decide |

How-to for researchers and developers: [`README.md`](README.md).

---

## A. Repository architecture (EXISTING)

A static website with no build step, no framework and (before this pilot) no
shared JavaScript: every page carries its own inline `<script>`. `server.js` is
a local static file server only. `scripts/` held two offline Python
precompute scripts that write JSON into `files/`.

Files that participate in the indicator / geography data flow:

| File | Role | Reads | Fields actually used |
|---|---|---|---|
| `files/neighborhood-map.html` | **Indicator Selector + map visualisation** (Lens "View Our Neighborhood") | `service_centers.json`, `sc_locations.json`, `sc_classification.json`, `../community_data.json`, Census TIGERweb (live ZIP polygons) | see §B |
| `community_data.json` (2.5 MB) | ZIP master + indicator values, 2,285 ZIP records keyed by ZIP | — | — |
| `files/service_centers.json` | Service Center master: 71 SCs, each with its ZIP list and SC-level population scores | — | — |
| `files/sc_locations.json` | SC anchor point (lat/lng, anchor ZIP) | — | — |
| `files/sc_classification.json` | SC typology for the profile pie (100 entries, 29 SCs not in `service_centers.json`) | — | — |
| `portal.html` (980 KB) | Community (SC) portal; links to the map, profile, calculator. Embeds its own `SC_ZIPS`, `SC_DATA` (10 SCs) and NAICS directory | none of the JSON above | — |
| `profile.html` | ZIP ("Neighborhood") profile | `community_data.json`, `service_centers.json`, `sc_locations.json` | `town, state, county, population, density, landform, total_acres, sc_name, tagline, vision1/2` — **no indicator fields** |
| `community-profile.html` | SC ("Community") profile | `community_data.json` | `scid, population, landform, county` — **no indicator fields** |
| `viability-calculator.html` | **Placeholder** ("Coming Soon"); passes `scid`/`zip` back to the portal | nothing | — |
| `iac_map.html`, `lens.html`, `index.html` | National map / search → portal | `iac_town_lookup_index.json`, `city_lookup.json`, `service_centers.json`, `iac_boundaries.json`, `iac_full_service_area.json` | geography/search only |
| `iac_home.html` | "Viability Index" demo chooser → `neighborhood-map.html?...&pop=1` | — | — |
| `scripts/build_iac_boundaries.py`, `scripts/build_service_area.py` | Offline geometry precompute | geojson, `community_data.json` keys | — |

Concept documents in `files/` (`IAC-Viability-Index-Concept.docx`,
`IAC_Viability_Index_Implementation.pdf`, `IAC_Viability_Index_Outline.pdf`,
`IAC-Lens-Concept.docx`) describe the target architecture (ZIP-first
observations, fixed weighting, four applications: Wellness, Trending,
Calculator, Decision Support; hierarchy Category → Topic → Component →
Indicator → Measure → Data Element → ZIP Observation → Source). **None of that
hierarchy exists in code yet.**

## B. The Indicator Selector (EXISTING)

1. **File:** `files/neighborhood-map.html` (only implementation in the repo).
2. **UI elements:** `<select id="ctrl-indicator-select">` ("View Indicator") in
   the right-hand green control bar; legends `#ctrl-legend-default`,
   `#ctrl-legend-scale` (5 rows + "No data"), `#ctrl-legend-landform`;
   title `#ctrl-title`.
3. **Selection:** 8 hard-coded `<option>`s plus "Community View". The
   `change` handler `handleIndicatorChange()` stores `currentIndicator`.
   `?pop=1` preselects Population Change (Viability Index entry from home page).
4. **Effect on the map:** every ZIP polygon is restyled through `styleFor()`;
   legend labels and title come from the hard-coded `INDICATOR_CONFIG`.
5. **Colour coding:** the 1–10 score is looked up in `SCALE_COLORS`
   (1 dark red · 2–4 red · 5–6 yellow · 7–9 green · 10 dark green · grey = no
   data). Raw values are never displayed. Landform uses `LANDFORM_COLORS`.
6. **Geography:** ZIP polygons are fetched live from Census TIGERweb (ZCTA5)
   for the SC's ZIP list. `pop_balance` / `pop_size` are *community-level*:
   read from the SC record and applied uniformly to all its ZIPs. Adjoining
   SCs are dissolved, uncoloured dashed outlines (by design, per John).
7. **Data files loaded:** `service_centers.json`, `sc_locations.json`,
   `sc_classification.json`, `../community_data.json`.
8. **Fields used:** per ZIP `pop_change_score`, `labor_force_participation_score`,
   `median_household_income_score`, `unemployment_rate_score`,
   `poverty_rate_score`, `dominant_landform`; per SC `pop_balance_score`,
   `pop_size_score`; SC `name`, `zips[].zip/town/state/population/landform`.
9. **Hard-coded** (options, field names, legends, titles).
10. **Not scalable:** a new indicator requires editing three places in the HTML
    and adding columns to a 2.5 MB file that every map/profile page downloads;
    no year dimension; no metadata.

Current data flow:

```
community_data.json ──(zip → {…_score})──┐
service_centers.json ─(scid → {…_score})─┼─► INDICATOR_CONFIG (hard-coded) ─► <select> ─► styleFor() ─► SCALE_COLORS ─► Leaflet polygons
TIGERweb (live) ─────(ZCTA polygons)─────┘
```

## C. Existing data schema (EXISTING)

`community_data.json` — `{ "<zip>": record }`, 2,285 records (MN 870, IA 702,
ND 260, SD 254, WI 199). Indicator fields follow `<name>_<year>` +
`<name>_score` (+ optional `_legend`):

| Indicator | Raw field | Score field | Coverage |
|---|---|---|---|
| Population change 2010→2020 | `pop_2010`, `pop_2020`, `pct_change_2010_2020` | `pop_change_score`, `pop_change_legend` | 2,177 scored |
| Labor force participation | `labor_force_participation_pct` (no year) | `labor_force_participation_score` | 2,209 |
| Median household income | `median_household_income_2024` | `median_household_income_score` | 2,154 |
| Unemployment rate | `unemployment_rate_2024` | `unemployment_rate_score` | 2,214 |
| Poverty rate | `poverty_rate_2024` | `poverty_rate_score` | 2,212 |
| Dominant landform | `dominant_landform` (+ `landform` acreage map) | — | 2,209 |

`files/service_centers.json` — `{ "<scid>": {name, zips:[{zip,town,state,population,landform}], pop_*} }`,
71 SCs / 2,164 ZIPs. **121 ZIPs in `community_data.json` have `scid: null`**
and appear in no SC.

**How the 1–10 scores were produced — UNKNOWN / NEEDS CONFIRMATION.** No
script in the repo computes them. Refitting shows they follow fixed,
equal-width bands with clipped tails, i.e.
`score = round(1 + 9·(x − worst)/(best − worst))` clipped to 1–10:

| Score field | Fitted worst → best | Agreement |
|---|---|---|
| `poverty_rate_score` | 40.5% → 0% | 99.5% |
| `unemployment_rate_score` | 18.5% → 0% | 99.2% |
| `median_household_income_score` | $38,750 → $153,750 | 99.1% |
| `pop_change_score` | −15% → +15% | 98.9% |
| `labor_force_participation_score` | 35.3% → 79.9% | 98.7% |

The pilot uses this same rule (`linear_bands`) so new and existing scores are
comparable; the parameters above are recorded in the master as
`scoring_status = legacy_inferred`.

### Project components vs. repository (Part 3)

| Project component | Exists in code? | File(s) | Current structure | Missing / needed |
|---|---|---|---|---|
| Indicator Master | **No** → **created in pilot** | `data/indicators/indicator_master.csv` → `files/indicators/indicator_master.json` | Was implicit in `INDICATOR_CONFIG` + field names | Weights; remaining 6 components' definitions |
| Trends Master | **No** (structure created) | `files/indicators/values/*.json` (year dimension) | Only `pop_2010/pop_2020`; others single-year | Historical data; ZCTA vintage crosswalk (FUTURE) |
| Zip Code Master | Partial | `community_data.json` (descriptive fields), `city_lookup.json`, `iac_town_lookup_index.json` | ZIP record mixes identity + indicator values | Separate identity from values (RECOMMENDED, not done) |
| Jurisdiction Master | **No** | — | Only `county`, `state` strings on ZIP | County/city/school-district FIPS tables (FUTURE; district crosswalk REQUIRED for K-12) |
| Community Master | Partial | `files/service_centers.json`, `sc_classification.json`, `portal.html` `SC_DATA` | "Community" = Service Center | Unify the three SC sources (RECOMMENDED) |
| Service Center Master | Yes | `files/service_centers.json`, `sc_locations.json`, `sc_classification.json` | scid → name, ZIPs, scores; location; typology | 29 SCs in classification lack ZIP lists |
| IAC Master | Partial | `iac_boundaries.json`, `iac_town_lookup_index.json` (`iacid`, `service_status`) | 30 IAC outlines; status per town | No IAC-level indicator data |
| Lens | Yes | `portal.html`, `files/neighborhood-map.html`, profiles | Static pages | Selector now consumes the master |
| Calculator | **Placeholder** | `viability-calculator.html` | "Coming Soon" page | Reusable loader + `weight`/`direction` fields prepared |
| Weighting Table | **No** | — | Concept doc only | `weight` columns in master/components (blank, controlled process) |
| Analytic Criteria & Results | **No** | — | Concept doc only | FUTURE |

## D. Excel workbook structure

| Sheet | Columns | Content |
|---|---|---|
| `7 Components - Top 10` | Component, Priority Rank, Top 10 Indicator, Existing Materials – Match/Overlap, Revision Needed, Notes | 70 indicators = 7 components × ranks 1–10. The last three columns are **empty**. |
| `Education Comparison` | Current Top 10 Candidate, Researcher Education Indicator | The 10 Education targets beside 4 researcher indicators (4-Year Graduation Rate, Attendance / Chronic Absence, Reading / ELA, Math). Rows are side-by-side lists, **not** pairings. |

There are **no** values, sources, years, geographic levels, methodologies,
historical data, rankings beyond priority rank, or 1–10 scores in the
workbook. It is therefore the **skeleton of the Indicator Master** (the
registry / selection layer), not a research source table, validation table
or Trends Master. Overlap with the existing system: 4 Economy indicators
(Median Household Income, Poverty, Unemployment, LFPR) already have values
and scores in `community_data.json`; the existing Population and Landform
views are not in the 70.

## E. Excel → Indicator Master mapping (Part 5)

| Excel field | Example | Target field | Target table | Transformation | Notes |
|---|---|---|---|---|---|
| Component | Education | `component_id`, `component_name` | `components.csv`, `indicator_master.csv` | name → stable id (`education`) | 8th group `population_land` holds existing Lens views — NEEDS CONFIRMATION |
| Priority Rank | 3 | `priority_rank` | `indicator_master.csv` | int | Orders selector entries; **not** a weight |
| Top 10 Indicator | Bachelor's Degree or Higher | `indicator_name`; `indicator_id` | `indicator_master.csv` | id = component prefix + slug (`edu_bachelors_degree_or_higher`) | ids are permanent; names may change |
| Existing Materials – Match/Overlap | (empty) | `existing_materials_match` | `indicator_master.csv` | copied; filled for the 8 existing fields | |
| Revision Needed | (empty) | `revision_needed` | `indicator_master.csv` | copied | |
| Notes | (empty) | `notes` | `indicator_master.csv` | copied | |
| Researcher Education Indicator | Reading / ELA | `research_indicator`, `match_type`, `match_rationale`; measures as `level = measure` rows | `indicator_master.csv` | classified (§G) | |
| *Source* | — (missing) | `source_id` → `sources.csv` | **REQUIRED** | | |
| *Source year / historical year* | — (missing) | `year` per observation; `years_planned` per indicator | research CSV / master | ACS end year | |
| *Geography / ZIP code* | — (missing) | `geo_level`, `geo_id` (research); `geo_level`, `native_geo_level` (master) | **REQUIRED** | ZIP zero-padded to 5 digits | |
| *Raw value* | — (missing) | `raw_value` (+ `moe`, `numerator`, `denominator`) | research CSV | percent as 0–100 | |
| *1–10 value* | — (missing) | `score` — **computed**, never typed | `values/<component>.json` | `linear_bands(score_worst, score_best)` | Researchers do not supply scores |
| *Methodology* | — (missing) | `definition`, `methodology`, `source_variables`, `derivation` | master | | |
| *Release cycle* | — (missing) | `release_cycle` | master + `sources.csv` | | |
| *Direction* | — (missing) | `direction` | master | higher/lower_is_better | **REQUIRED** for scoring & calculator |
| *Weight* | — (missing) | `weight` | master, `components.csv` | blank until set by the controlled weighting process | FUTURE |

## F. Indicator Master schema (minimum viable)

Source of truth: four CSV tables in `data/indicators/` (Excel-friendly), built
by `scripts/build_indicators.py` into JSON for the browser — the same
"offline precompute → `files/*.json`" pattern the repo already uses.

* `components.csv` — `component_id, component_name, display_order, in_top10_structure, weight, notes`
* `indicator_master.csv` — one row per indicator **or measure**. Required:
  `indicator_id, level, component_id, indicator_name, status, geo_level,
  binding, scoring_method`. Plus definition/unit/value_type/direction,
  source & methodology, years, scoring parameters, legend labels, weight,
  legacy field binding, research match. Full dictionary in `README.md`.
* `sources.csv` — `source_id, source_name, publisher, dataset_or_table, url,
  native_geo_levels, release_cycle, years_available, reliability_1to5,
  zip_availability, notes` (reliability/ZIP scales from
  `IAC_Viability_Index_Implementation.pdf`).
* `research/*.csv` — long format, one observation per row:
  `indicator_id, geo_level, geo_id, geo_name, year, raw_value, moe,
  numerator, denominator, source_id, source_detail, researcher,
  collected_date, notes`.
* `crosswalks/*.csv` — `from_geo_level, from_geo_id, to_geo_level, to_geo_id, weight, weight_basis, source`.

How it meets each need: **selector** (component, rank, short_label, status,
legend) · **visualisation** (geo_level, score) · **trends** (year is a
dimension; `years_planned` vs `data.years_available`) · **calculator**
(`direction`, `weight`, comparable 1–10 scores, uniform `record()` API over
new and legacy indicators) · **research workflow** (one CSV row per
observation, template provided) · **validation** (source, methodology, MOE,
researcher, date, status gate, build-time checks) · **historical** (any year;
2000/2010 sources documented).

Design decisions:

* **Existing indicators are registered, not migrated.** Rows with
  `binding = legacy_zip_field / legacy_sc_field` point at the current fields
  in `community_data.json` / `service_centers.json`. No values are copied, so
  there is one data system and nothing existing breaks. Migrating them into
  `values/economy.json` later is a separate, optional step.
* **Scores are computed, never entered.** Researchers deliver raw values; the
  build applies the indicator's band rule. Changing bands re-scores everything
  consistently.
* **Values are split per component** (`values/education.json`) so pages load
  only what they need, unlike the single 2.5 MB file.
* **Status gate:** `planned → researching → defined → validated → published`.
  The map lists `defined+` indicators but only colours `validated/published`
  ones with data; others show "(data pending)" or "(in review)".

## G. Education pilot design (Part 7)

| Target (Top-10) | Researcher indicator | Classification | Reasoning | Pilot source / geography |
|---|---|---|---|---|
| 1 High School Graduation Rate | 4-Year Graduation Rate | **Exact Match** | The 4-year adjusted cohort graduation rate (ACGR) is the federal standard definition of "graduation rate". | State agencies / EDFacts, **school district** → ZIP via crosswalk |
| 1 High School Graduation Rate | (ACS "HS diploma or higher", adults 25+) | **Related but Different** | Adult attainment stock, not a cohort outcome; must not be substituted. | not used |
| 2 Postsecondary Educational Attainment | — | **No Match** (researcher) | No researcher indicator. Proposed definition: % adults 25+ with associate's or higher — NEEDS CONFIRMATION (vs "some college or higher"). | ACS B15003, ZCTA |
| 3 Bachelor's Degree or Higher | — | **No Match** (researcher) | ACS gives an exact, standard measure. | ACS B15003, ZCTA |
| 4 K–12 Academic Proficiency | Reading / ELA | **Partial Match** | One subject of the composite. | measure `edu_k12_ela_proficiency` |
| 4 K–12 Academic Proficiency | Math | **Partial Match** | One subject of the composite. | measure `edu_k12_math_proficiency` |
| 4 K–12 Academic Proficiency | Reading / ELA + Math | **Strong Match** | ELA + Math together is the standard proficiency composite (`derivation = mean_of_measures`). | State assessments, district → ZIP |
| 6 School Absenteeism | Attendance / Chronic Absence | **Strong Match** | Chronic absence (≥10% of days missed) is the standard measure; "attendance rate" is inverse and not interchangeable. MN publishes "consistent attendance". | State agencies, district → ZIP |
| 5 Early Childhood Ed. / Readiness | — | No Match | | planned |
| 7 Student–Teacher Ratio | — | No Match | Candidate: NCES CCD (district). | planned |
| 8 Educational Opportunity / School Access | — | No Match | | planned |
| 9 Workforce Skill Alignment | — | No Match | | planned |
| 10 Adult Education / Lifelong Learning | — | No Match | | planned |

Provisional score bands (`scoring_status = provisional`, NEEDS CONFIRMATION
once real data are reviewed): Bachelor's+ 5→50%, Postsecondary 15→65%,
HS graduation 60→100%, K–12 proficiency 20→80%, chronic absence 40→0%.

## Part 8 — Data pipeline and responsibilities

```
Researchers ──► data/indicators/research/*.csv   (raw observations, any geography, any year)
                  + sources.csv rows, + indicator definition in indicator_master.csv
      │
Validation ───► python3 scripts/build_indicators.py --check   (automatic)
                  + human review → set status = validated
      │
Indicator Master ► scripts/build_indicators.py
                  ├─ crosswalk district/county → ZIP, derive composites
                  ├─ score with linear_bands (1–10)
                  └─ files/indicators/indicator_master.json + values/<component>.json
      │
Trends / geography ► year-keyed values; ZIP and SC levels
      │
Lens / Indicator Selector ► files/js/iac-indicators.js → neighborhood-map.html (dynamic options)
      │
Visualisation ► SCALE_COLORS per ZIP / per SC
      │
Calculator (FUTURE) ► same loader: store.record()/score(), direction, weight
```

| Layer | Responsibility |
|---|---|
| **Researchers** | One row per indicator × geography × year with raw value (not a score), source_id, source detail, MOE if published, their initials and date. Use the template. Report suppressed cells by leaving them out, never as 0. Propose new indicators/sources as rows for review. |
| **Validation** | Automatic: ids exist, numeric values, 0–100 for percents, 4-digit years, 5-digit ZIPs, no duplicates, source declared, crosswalk present, ZIP known to the Lens. Human: definition matches the master, year/vintage right, outliers, small-sample/MOE warnings, cross-state comparability; then flip `status` to `validated`. |
| **Indicator Master (Sofiia / data integration)** | Owns ids, definitions, units, direction, geography levels, scoring bands, legend text, source registry, crosswalks, status; runs the build; keeps legacy bindings correct; coordinates the weighting process. |
| **Frontend (Nikhitha)** | Consumes only `files/indicators/*.json` through `iac-indicators.js`; never hard-codes indicator ids, field names, legends or years; renders `score` with the shared colour scale; shows `provenance()`; treats missing records as "No data". |

## Part 9 — Data contract

### What the frontend expects today (derived from the code)

| Need | Source | Type |
|---|---|---|
| Option value → field name | hard-coded `INDICATOR_CONFIG[key].field` | string |
| Score per ZIP | `community_data[zip][field]` | integer 1–10, missing ⇒ grey |
| Score per SC | `service_centers[scid][field]` | integer 1–10 |
| Category per ZIP | `community_data[zip].dominant_landform` | one of 7 strings |
| Legend labels, title, community-level flag | hard-coded | strings / bool |
| ZIP list + town names | `service_centers[scid].zips[]` | array |

No indicator id, year, raw value, unit, source or methodology is consumed.

### Proposed contract: Indicator Master → Frontend (implemented)

`files/indicators/indicator_master.json`

| Field | Type | Req. | Used by current frontend? |
|---|---|---|---|
| `schema_version` | string | ✔ | — |
| `components[]` `{id, name, display_order, in_top10_structure, weight}` | object | ✔ | yes (optgroup label, order) |
| `sources{source_id: {...}}` | object | ✔ | yes (provenance line) |
| `indicators[].id` | string | ✔ | yes (option value) |
| `.level` (`indicator`/`measure`) | string | ✔ | yes (only `indicator` listed) |
| `.component_id`, `.priority_rank` | string, int | ✔ | yes (grouping/order) |
| `.name`, `.short_label` | string | ✔ | yes (option text) |
| `.status` | enum | ✔ | yes (pending / in review / live) |
| `.geo_level` (`zip`/`service_center`) | enum | ✔ | yes (per-ZIP vs community colouring) |
| `.binding` `{type, values_file \| score_field, raw_field, selector_key}` | object | ✔ | yes |
| `.legend` `[5 strings, index 2 blank]` | array | ✔ for selectable | yes |
| `.scoring` `{method, worst, best, status}` | object | ✔ | yes ("provisional scoring") |
| `.data` `{years_available, latest_year, geo_count_latest}` | object | ✔ (values_file) | — (FUTURE trends) |
| `.unit`, `.value_type`, `.direction` | string | optional | `formatRaw()`; FUTURE calculator |
| `.definition`, `.methodology`, `.source_id`, `.source_variables`, `.derivation`, `.release_cycle`, `.years_planned`, `.native_geo_level` | | optional | — (FUTURE info panel, validation) |
| `.weight` | number \| null | optional | — (FUTURE calculator) |
| `.research` `{indicator, match_type, rationale}`, `.notes`, `.parent_id` | | optional | — (documentation) |

`files/indicators/values/<component_id>.json`

```json
{
  "schema_version": "1.0",
  "component_id": "education",
  "generated_at": "2026-10-07T11:02:16+00:00",
  "indicators": {
    "edu_bachelors_degree_or_higher": {
      "geo_level": "zip",
      "years": [2020, 2024],
      "latest_year": 2024,
      "values": {
        "2024": { "56401": { "raw": 21.5, "moe": 2.54, "score": 4 } },
        "2020": { "56401": { "raw": 20.1, "moe": 2.71, "score": 4 } }
      }
    }
  }
}
```
*(illustrative numbers)* — per record: `raw` (number, required), `score`
(int 1–10, required for scored indicators), `moe` (optional), `allocated:
true` (value came through a crosswalk), `derived: true` (composite).
`geo_id` keys are 5-digit ZIPs or SC ids, matching `community_data.json` and
`service_centers.json`.

## H. Files created

| File | Purpose |
|---|---|
| `data/indicators/components.csv` | 7 components + `population_land` group |
| `data/indicators/indicator_master.csv` | 70 workbook indicators + 4 existing Lens views + 2 K-12 measures (76 rows) |
| `data/indicators/sources.csv` | 6 sources (ACS B15003, state ACGR, state assessments, attendance, NCES CCD, legacy) |
| `data/indicators/research/education.csv` | Empty research table for researcher-supplied Education data |
| `data/indicators/crosswalks/school_district_to_zip.csv` | Empty crosswalk (header only) |
| `data/indicators/templates/research_values_template.csv` | Template with one clearly fake example row |
| `scripts/build_indicators.py` | Validate → crosswalk → derive → score → write JSON (stdlib) |
| `scripts/fetch_acs_education.py` | ACS B15003/B15002 → `research/education_acs.csv` (needs network) |
| `files/js/iac-indicators.js` | Shared loader/API for selector, profiles, calculator |
| `files/indicators/indicator_master.json`, `files/indicators/values/education.json` | Generated |
| `docs/indicators/ARCHITECTURE_AUDIT.md`, `docs/indicators/README.md` | This audit; how-to |

## I. Files modified

`files/neighborhood-map.html` only:

* loads `js/iac-indicators.js` and (non-fatally) the master in the existing
  `Promise.all`;
* `addMasterIndicatorOptions()` appends one `<optgroup>` per component after
  the 8 existing options and registers each entry in `INDICATOR_CONFIG` with
  a `masterId` (so legend/title code is reused unchanged);
* one new branch in `styleFor()` → `masterScoreColor()`;
* a small source/year line (`#ctrl-indicator-meta`) under the scale legend,
  shown only for master indicators;
* `?indicator=<id>` deep link.

## J. Files intentionally not touched

`community_data.json`, `files/service_centers.json`, `sc_*.json`,
`portal.html`, `profile.html`, `community-profile.html`,
`viability-calculator.html`, `iac_map.html`, `lens.html`, `index.html`,
`iac_home.html`, geometry scripts and geojson.

## K. Risks / ambiguities

1. **No Education values exist yet.** The workbook has none; the repo has
   none; the Census API is unreachable from the environment where this was
   built. Run `scripts/fetch_acs_education.py` where the network is open, or
   provide the ACS export. Until then the Education options read "(data pending)".
2. **K-12 data are school/district level.** A district → ZIP crosswalk is
   REQUIRED before graduation, proficiency or absenteeism can be mapped
   (NCES EDGE district boundaries × ZCTA, population-weighted). UNKNOWN who
   builds it.
3. **Cross-state comparability** of proficiency (5 different state tests) and
   absenteeism definitions. Decide: SEDA cross-state scale, or score within
   state. NEEDS CONFIRMATION.
4. **Score bands for Education are provisional.** Confirm after first data
   review. Legacy band parameters are inferred.
5. **Provenance of existing values/scores** (year of LFPR, scoring script) is
   UNKNOWN.
6. **Population & Landform** are not among the 7 components; placed in
   `population_land` pending a decision.
7. **ZCTA ≠ ZIP.** PO-box ZIPs have no ACS data; ZCTA definitions changed in
   2010 and 2020, so 2000/2010 values need a vintage crosswalk (NHGIS
   standardised tables RECOMMENDED).
8. **121 ZIPs without an SC** and **29 SCs without ZIP lists** in the existing
   masters.
9. **Workbook vs CSV as source of truth.** RECOMMENDED: the CSV in the repo
   is canonical; the workbook remains the research working document and
   changes are copied in by the data-integration owner.
10. **Time-series MOEs:** ACS 5-year periods that overlap (e.g. 2020 and 2024)
    should not be compared as independent samples.

## L. Implementation plan and status

| Phase | Scope | Status |
|---|---|---|
| 1 Understand / document | This audit | **Done** |
| 2 Standardised Education structure | Master tables, sources, template, build script, ACS fetch script | **Done** (definitions); values pending data |
| 3 Connect to Indicator Selector | Loader + dynamic options in `neighborhood-map.html` | **Done** |
| 4 Validate visualisation | Headless browser: legacy views identical (fill colours of all 21 Brainerd ZIPs × 9 views, before/after), Education colours equal expected scores with test-only data, master-missing fallback, `?pop=1` and `?indicator=` | **Done with test data**; repeat with real ACS data |
| 5 Trends / historical | Year dimension in values; `--years` in fetch script | Structure **done**; year picker UI FUTURE |
| 6 Calculator compatibility | `direction`, `weight`, `store.record()` over new + legacy indicators | Prepared; calculator UI FUTURE |
| 7 Generalise to 6 components | Fill master rows, add research CSVs; no frontend changes needed | FUTURE |
