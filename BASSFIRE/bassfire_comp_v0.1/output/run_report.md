# BASSFIRE comparability run

- Reference runs (BASS / BASS-II, executed): **0**
- Target runs (SAFFIRE I-III, executed): **21**
- Pairs compared: **0**  (tiers: none)
- Targets with a qualifying match: **0**; with no qualifying match: **21**
- Planned / SAFFIRE IV-VI records kept separately: 0
- Records excluded (see excluded_records.csv): 0

**No pairs could be formed.** Put curated run tables in `data/runs/` or raw downloads in `data/raw/PSI-nn/...`; see README. Check excluded_records.csv for rows that were read but rejected, and source_inventory.csv for files that were not recognized as run tables.

## Read this before using the ranking

- Tolerances, thresholds and the provisional score are **placeholders, not validated** against manually reviewed pairs. Ranking is a screening aid, not equivalence.
- Unknown values are never filled in. They show as missing and reduce data_completeness.
- Dimension definitions are flagged `dimension_definitions_unreviewed` until you set `dimension_definition_status = verified`.

## Record flags

- `airflow_unparseable_value`: 11
- `autodetected_from_raw_table`: 21
- `dimension_definitions_unreviewed`: 21
- `fuel_name_missing`: 6
- `programme_from_investigation_id`: 21
- `sample_length_unparseable_value`: 11
- `sample_thickness_unparseable_value`: 2
- `sample_width_unparseable_value`: 11
- `source_url_defaulted_to_investigation_page`: 21
- `status_assumed_from_psi_repository`: 21
- `verification_needs_review`: 21

## Ingest notes

- raw/PSI-100/PSI-100_Experimental table_SAFFIRE-3.csv: 3 column(s) not mapped and ignored
- raw/PSI-98/PSI-98_Experimental table_SAFFIRE-1.csv: 6 column(s) not mapped and ignored
- raw/PSI-99/PSI-99_Experimental table_SAFFIRE-2.csv: 11 column(s) not mapped and ignored
