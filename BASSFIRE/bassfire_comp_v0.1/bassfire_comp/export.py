"""CSV export. UTF-8 with BOM so Excel on Windows opens the files correctly."""
from __future__ import annotations

import csv
from pathlib import Path

from .compare import NUMERIC_PARAMS, SUBSCORE_PARAMS
from .schema import ALL_QUANTITIES, CATEGORICAL, TEXT_FIELDS


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return format(v, ".10g")
    if isinstance(v, (list, tuple)):
        return ";".join(str(x) for x in v)
    return str(v)


def write_csv(path: Path, columns: list, rows: list) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(columns)
        for row in rows:
            w.writerow([_fmt(row.get(c)) for c in columns])


RECORD_COLUMNS = (TEXT_FIELDS + [f"{c}_raw" for c in CATEGORICAL]
                  + [f"{n}_{s}" for n in ALL_QUANTITIES
                     for s in ("raw", "raw_unit", "si", "si_unit", "conversion", "missing_reason")]
                  + ["flags"])


def record_row(rec) -> dict:
    row = dict(rec.text)
    row["record_id"] = rec.record_id
    for c in CATEGORICAL:
        row[f"{c}_raw"] = rec.raw_text.get(c, "")
    for n in ALL_QUANTITIES:
        q = rec.q[n]
        row.update({f"{n}_raw": q.raw_text, f"{n}_raw_unit": q.raw_unit, f"{n}_si": q.si_value,
                    f"{n}_si_unit": q.si_unit, f"{n}_conversion": q.method,
                    f"{n}_missing_reason": q.missing_reason or ""})
    row["flags"] = rec.flags
    return row


def _source(rec) -> str:
    t = rec.text
    return " | ".join(x for x in (t["source_url"], t["source_file"], t["source_location"],
                                  f"curated in {t['curation_file']} row {t['curation_row']}") if x)


PAIR_COLUMNS = (
    ["pair_id", "reference_record_id", "target_record_id", "reference_programme",
     "reference_experiment_id", "target_programme", "target_experiment_id", "eligibility_tier",
     "tier_reasons", "fuel_relation", "flow_direction_match", "gravity_match",
     "airflow_measurement_match"]
    + [f"{p}_{s}" for p in NUMERIC_PARAMS
       for s in ("label", "ref", "tgt", "abs_diff", "rel_diff")]
    + [f"{k}_similarity" for k in list(SUBSCORE_PARAMS) + ["flow_configuration"]]
    + ["provisional_score_UNVALIDATED", "subscores_known", "data_completeness",
       "missing_parameters", "qualifying", "non_qualifying_reason", "rank", "match_explanation",
       "warnings", "reference_verification_status", "target_verification_status",
       "reference_source", "target_source"])


def pair_row(p: dict, explanation: str) -> dict:
    ref, tgt, r = p["ref"], p["tgt"], p["r"]
    row = {"pair_id": f"{ref.record_id}__{tgt.record_id}",
           "reference_record_id": ref.record_id, "target_record_id": tgt.record_id,
           "reference_programme": ref.text["programme"],
           "reference_experiment_id": ref.text["experiment_id"],
           "target_programme": tgt.text["programme"],
           "target_experiment_id": tgt.text["experiment_id"],
           "eligibility_tier": r["tier"], "tier_reasons": r["tier_reasons"],
           "fuel_relation": r["fuel_relation"], "flow_direction_match": r["flow_direction_match"],
           "gravity_match": r["gravity_match"],
           "airflow_measurement_match": r["airflow_measurement_match"]}
    for n in NUMERIC_PARAMS:
        pr = r["params"][n]
        for s in ("label", "ref", "tgt", "abs_diff", "rel_diff"):
            row[f"{n}_{s}"] = round(pr[s], 6) if isinstance(pr[s], float) else pr[s]
    for k, v in r["subscores"].items():
        row[f"{k}_similarity"] = round(v, 4) if v is not None else None
    row.update({
        "provisional_score_UNVALIDATED": (round(r["provisional_score"], 4)
                                          if r["provisional_score"] is not None else None),
        "subscores_known": r["subscores_known"],
        "data_completeness": round(r["completeness"], 4) if r["completeness"] is not None else None,
        "missing_parameters": r["missing"], "qualifying": "yes" if r["qualifying"] else "no",
        "non_qualifying_reason": r["non_qualifying_reason"], "rank": r["rank"],
        "match_explanation": explanation, "warnings": r["warnings"],
        "reference_verification_status": ref.text["verification_status"],
        "target_verification_status": tgt.text["verification_status"],
        "reference_source": _source(ref), "target_source": _source(tgt)})
    return row


TOP_COLUMNS = ["target_record_id", "target_programme", "target_experiment_id", "target_fuel",
               "outcome", "rank", "reference_record_id", "reference_programme",
               "reference_experiment_id", "reference_fuel", "eligibility_tier",
               "provisional_score_UNVALIDATED", "data_completeness", "missing_parameters",
               "match_explanation", "no_match_reason", "reference_source", "target_source"]
