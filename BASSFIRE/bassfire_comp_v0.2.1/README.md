# bassfire_comp v0.2.1

Screens every BASS / BASS-II (reference) run against every SAFFIRE I-III (target) run and
reports which pairs are comparable, how close they are, and what is missing. It never
fills in a value it was not given. No internet access is used.

## Install (Windows, Python 3.14)

```
py -m venv .venv
.venv\Scripts\activate
pip install -e .[xlsx]        # [xlsx] adds openpyxl for .xlsx files; plain `pip install -e .` also works
bassfire_comp demo            # sanity check on SYNTHETIC fake data -> output_demo\
```
If `bassfire_comp` is not found, use `py -m bassfire_comp run`. Tests: `py -m unittest discover tests`.

## Use

1. Drop the five experimental tables into `data\raw\`. The `PSI-nn` in the file name (or in a parent folder name) tells the tool which programme a table belongs to, e.g. `PSI-25_Experimental_table_BASS-II.csv`.
2. For values that only exist in PDFs/reports (e.g. BASS-II flow speed, oxygen, fuel), fill a
   copy of `templates\runs_template.csv` and save it in `data\runs\`.
3. `bassfire_comp run` (options: `--data`, `--out`, `--config`). No prompts.

Open `output\run_report.md` first, then `top_matches_by_saffire.csv`.

## Outputs (`output\`, UTF-8 with BOM so Excel opens them correctly)

| File | Contents |
|---|---|
| top_matches_by_saffire.csv | Top N references per SAFFIRE run, or `no_qualifying_match` with the reason |
| pairwise_comparability.csv | Every pair: tier, parameter labels/differences, subscores, completeness, explanation |
| executed_experiments.csv | Normalized records (raw value, unit, SI value, conversion, missing reason per quantity) |
| planned_experiments.csv | Planned records and all SAFFIRE IV-VI records (never paired) |
| excluded_records.csv | Rows that were read but not used, with the reason |
| source_inventory.csv, run_log.json | Every input file with SHA-256, config hash, version |

## Tiers (decided before any score)

- **ineligible**: flow direction differs, gravity differs, or fuels are unrelated.
- **needs_review**: flow direction, gravity, fuel identity or airflow-measurement type unknown.
- **exploratory**: related fuel (same `fuel_category`), or airflow measured differently
  (inlet vs local vs duct-average). Switch off with `exploratory_tier_enabled = false`.
- **direct**: same fuel, flow direction, gravity and airflow definition.

Ranking sorts by tier first, then the provisional score. A score can never lift a pair
across tiers. The score and all tolerances/thresholds in `config.toml` are placeholders until
validated against pairs you have reviewed.

## Curated table columns

Required: `programme` (BASS, BASS-II, SAFFIRE-I..VI), `record_status`
(executed/modified/planned/cancelled/unknown), `fuel_name`.
Strongly recommended: `experiment_id` (leave blank rather than invent one), `flow_direction`
(concurrent/opposed), `gravity_environment`, `airflow_value` + `airflow_unit` (velocity
units only) + `airflow_measurement_type` (inlet/local/duct_average), `oxygen_value` +
`oxygen_unit_or_basis` (mole_percent, volume_percent, mole_fraction, or a partial-pressure
unit such as kPa; plain "percent" is held as ambiguous), `pressure_value` + `pressure_unit` +
`pressure_basis` (absolute/gauge; gauge is not converted), `temperature_value` +
`temperature_unit`, `fuel_category` (needed to call two fuels "related"), `fuel_composition`.
Dimensions: `sample_width/length/thickness`, `duct_height/width/length` with `dimension_unit`
(or `<name>_unit`), and `ratio_denominator` (duct_height or duct_width) to get
sample/duct ratio. `dimension_definition_status`: leave as needs_review (default) until you
have checked them; every pair then carries `dimension_definitions_unreviewed`.
Provenance: `source_url` (defaults to the investigation page, flagged), `source_file`,
`source_location`, `source_doi`, `retrieved_at`, `verification_status`
(verified/needs_review/conflicting/digitized), `notes`.
Missing values: `not_reported`, `not_applicable`, `not_extracted` (blank), `ambiguous_definition`,
`conflicting_sources`. Headers may carry units, e.g. `Flow speed (cm/s)`.

## The fill-in sheet (`output\todo_fill_in.csv`)

Every run writes this file: one row per executed run that lacks something needed for matching
(flow direction, airflow, fuel, oxygen, thickness), with `ref_missing` saying what and
`ref_current_raw_values` showing text it could not read (e.g. `thickness='037 mm'`).
Rows with `priority = 1` are runs whose fuel exists on both the BASS/BASS-II and SAFFIRE side.
Fill the blank columns (airflow can be written `20` + `cm/s`, or `20 cm/s`), save the sheet into
`data\runs\`, and run again; your values are merged over the raw table. The `ref_` columns are
ignored on read. The optional columns `sample_length`, `duct_height`, `duct_width` and
`dimension_unit` raise `data_completeness`; any column from the table below also works.
Runs that share a duplicate test id are marked, and need a distinguishing id before merging.

## What happens to the NASA experimental tables

The tables are read as they are: units inside cells (`0.33 cm`, `30 cm/s`), `~ 21.5`,
ranges (`21.5 - 21.7` becomes the midpoint, flagged), header units (`Flow speed (cm/s)`).
`037 mm` and `See Fig. 5` are never guessed; they become missing with `ambiguous_definition`.
Note lines, `F1C1/F1C2` flow-visualization lines and cleaning lines go to
`excluded_records.csv` with the reason. Duplicate test ids are all kept (ids get a
`#file:rN` suffix and a flag) because they are separate rows in NASA's table.

**Curated rows override raw rows.** If a row in `data\runs\` has the same `programme` +
`experiment_id` as a raw-table row, the two are merged field by field: your non-blank values
win (a different value is flagged `conflict_curated_overrides_raw:<field>`), blanks are
filled from the raw table. So for BASS / BASS-II you only need to supply what the tables lack
(flow direction, airflow + unit + measurement type, oxygen) under the same `Test #`.

**Material strings** (`1 cm wide 200 micron thick PMMA`, `2 cm SIBAL`, `PMMA sphere 2 cm`) give
`fuel_identity` (used for matching), `sample_shape`, and, when your columns are blank,
thickness and width. A lone "2 cm" is read as strip width only when the string says "wide",
also gives a thickness, or the fuel is in `width_from_cm_identities` (SIBAL). It is never read
as width for spheres, rods or candles. `opposed` in the string sets flow direction. All flagged.
Shape known on both sides and different (e.g. sphere vs film) makes a pair exploratory.

**Config defaults** (`config.toml`, flagged on every record): gravity = microgravity for all
five programmes; fuel categories for fabric / polymer / wax; optional oxygen basis per PSI id.

## Auto-detected raw tables

A CSV/XLSX under `raw\` is read as a run table when its headers include a fuel/material column
plus either a test/sample id column or at least 3 recognized run columns. Those records are flagged
`autodetected_from_raw_table`, `status_assumed_from_psi_repository` and `verification_needs_review`.
Anything with a column the tool does not recognize is listed in the report notes.

## Known limits (v0.1)

- Tested against the five real experimental tables, but only their column layout, not summary-report content.
- BASS / BASS-II tables have no flow direction, airflow or gravity columns; until you supply them,
  pairs against those runs stay `needs_review` (never `direct`).
- Volumetric flow (L/min, CFM) is not converted to velocity.
- No PDF parsing, no web fetching (by design for now), no learned weights.
