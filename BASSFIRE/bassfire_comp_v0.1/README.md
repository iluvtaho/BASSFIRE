# bassfire_comp v0.1

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

1. Drop your downloads into `data\raw\PSI-26`, `PSI-25`, `PSI-98`, `PSI-99`, `PSI-100`.
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

## Auto-detected raw tables

A CSV/XLSX under `raw\PSI-nn\` is read as a run table when its headers include a fuel/material
column plus at least 3 recognized run columns. Those records are flagged
`autodetected_from_raw_table`, `status_assumed_from_psi_repository` and `verification_needs_review`.
Anything with a column the tool does not recognize is listed in the report notes.

## Known limits (v0.1)

- Built without sight of the real PSI file layouts; the raw-table reader is a best-effort
  header matcher. Send sample files and its aliases can be tightened.
- Volumetric flow (L/min, CFM) is not converted to velocity.
- No PDF parsing, no web fetching (by design for now), no learned weights.
