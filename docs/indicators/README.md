# IAC Indicators — how data gets into the Lens

Background and design rationale: [`ARCHITECTURE_AUDIT.md`](ARCHITECTURE_AUDIT.md).

```
data/indicators/               ← humans edit these (CSV, opens in Excel)
  components.csv
  indicator_master.csv         ← one row per indicator / measure
  sources.csv                  ← one row per data source
  research/*.csv               ← observations: indicator × geography × year
  crosswalks/*.csv             ← optional: e.g. school district → ZIP
  templates/research_values_template.csv

scripts/build_indicators.py    ← validates, scores, writes ↓
scripts/fetch_acs_education.py ← optional: pulls ACS education data into research/

files/indicators/              ← generated, do not edit by hand
  indicator_master.json
  values/<component_id>.json
files/js/iac-indicators.js     ← browser loader used by the Lens map
```

## For researchers: adding data

1. Copy `templates/research_values_template.csv`, delete the example row.
2. One row per **indicator × geography × year**:

   | Column | Required | Rule |
   |---|---|---|
   | `indicator_id` | ✔ | Must exist in `indicator_master.csv` (e.g. `edu_school_absenteeism`) |
   | `geo_level` | ✔ | `zip`, `service_center`, `school_district` or `county` |
   | `geo_id` | ✔ | 5-digit ZIP (keep leading zeros), SC id, NCES district id, county FIPS |
   | `geo_name` | | Human-readable name, for checking |
   | `year` | ✔ | 4-digit data year. ACS: the end year (2020–2024 → `2024`). School year 2023-24 → `2024` |
   | `raw_value` | ✔ | The measured value. **Percent as 0–100** (21.3, not 0.213). **Never a 1–10 score** |
   | `moe` | | Margin of error if the source publishes one |
   | `numerator`, `denominator` | | Counts behind a rate, if available |
   | `source_id` | ✔ | Must exist in `sources.csv` |
   | `source_detail` | | File name / table / vintage you used |
   | `researcher`, `collected_date` | | Initials, YYYY-MM-DD |
   | `notes` | | Anything a reviewer should know |

3. Suppressed or missing cells: **leave the row out**. Do not enter 0.
4. Save as `data/indicators/research/<component>_<topic>.csv` (any name ending `.csv`).
5. Run `python3 scripts/build_indicators.py --check` and fix every `ERROR`.

Data at district/county level is allowed: the build allocates it to ZIPs if
a matching crosswalk exists (`crosswalks/<from>_to_zip.csv`). If not, the
build warns and those values are not published.

## For the data-integration owner: adding or changing an indicator

Edit its row in `indicator_master.csv`:

| Column | Meaning |
|---|---|
| `indicator_id` | Permanent id: component prefix + snake_case (`edu_…`, `eco_…`, `inf_…`, `hhs_…`, `saf_…`, `con_…`, `ccq_…`, `pop_…`). Never rename once published |
| `level` / `parent_indicator_id` | `indicator`, or `measure` feeding a parent (e.g. ELA → K–12 Proficiency) |
| `component_id`, `priority_rank` | From the workbook; rank orders the selector |
| `indicator_name`, `short_label` | Full name; dropdown label (fits ~22 characters) |
| `status` | `planned` → `researching` → `defined` (listed as "data pending") → `validated` (shown on map) → `published` |
| `definition`, `unit`, `value_type` | `value_type` ∈ percent, currency, count, ratio, category |
| `direction` | `higher_is_better`, `lower_is_better`, `neutral` |
| `geo_level` | Level the Lens shows: `zip` or `service_center` |
| `native_geo_level` | Level the source publishes |
| `source_id`, `source_variables`, `methodology`, `release_cycle`, `years_planned` | Provenance |
| `derivation` | blank, or `mean_of_measures` (composite of its `measure` rows) |
| `scoring_method`, `score_worst`, `score_best`, `scoring_status` | `linear_bands`: value at `score_worst` → 1, at `score_best` → 10, equal bands, clipped. Same rule the existing scores follow. `scoring_status`: provisional / confirmed / legacy_inferred |
| `legend_1`, `legend_2`, `legend_4`, `legend_5` | Legend text for scores 1, 2–4, 7–9, 10 (5–6 is "Average") |
| `weight` | Calculator weight within the component; blank until set by the weighting process |
| `binding` | `values_file` (new indicators), or `legacy_zip_field` / `legacy_sc_field` for indicators whose values still live in `community_data.json` / `service_centers.json` |
| `legacy_selector_key`, `legacy_score_field`, `legacy_raw_field` | For legacy bindings only |
| `research_indicator`, `match_type`, `match_rationale` | Link to the researcher's indicator: Exact / Strong / Partial / Related but Different / No Match |
| `existing_materials_match`, `revision_needed`, `notes` | Copied from / back to the workbook |

Then:

```bash
python3 scripts/build_indicators.py          # writes files/indicators/
```

Review the printed counts and warnings, set `status` to `validated`, rebuild,
and commit both the CSVs and the generated JSON.

### Education ACS data (Bachelor's+, Postsecondary)

Needs network access to `api.census.gov` (key optional: `CENSUS_API_KEY`):

```bash
python3 scripts/fetch_acs_education.py --years 2012 2020 2024
python3 scripts/build_indicators.py
```

The script checks each Census variable label before using it, filters to the
ZIPs in `community_data.json`, computes percent and MOE, and writes
`research/education_acs.csv`. For 2010–2011 it uses table B15002. For 2000
use Census 2000 SF3 (P037) from NHGIS, preferably the geographically
standardised time-series tables, and add it as a research CSV.

## For frontend developers

```html
<script src="js/iac-indicators.js"></script>
```

```js
const store = await IACIndicators.load('indicators/');          // relative to the page
store.selectorEntries();     // [{component, entries:[{id, label, enabled, reason, geoLevel, legend}]}]
store.score('edu_bachelors_degree_or_higher', '56401');          // 1–10 or null (latest year)
store.record('edu_bachelors_degree_or_higher', '56401', 2020);   // {raw, score, moe?} or null
store.formatRaw('edu_bachelors_degree_or_higher', 21.5);         // "21.5%"
store.provenance('edu_bachelors_degree_or_higher');              // "U.S. Census Bureau · 2024 · provisional scoring"
store.attachLegacy({ zip: communityData, service_center: scData });
store.score('eco_poverty_rate', '56401');                        // works for legacy indicators too
```

Rules: don't hard-code indicator ids, fields, legends or years in pages.
Treat `null` as "No data" (grey). Colour with the shared 1–10 scale.

`files/neighborhood-map.html` lists every `values_file` indicator with status
`defined` or higher under its component, disabled until it is validated and
has data. Deep link: `neighborhood-map.html?scid=9&zip=56401&indicator=edu_bachelors_degree_or_higher`.
