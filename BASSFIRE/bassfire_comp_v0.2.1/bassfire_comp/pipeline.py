"""ingest -> normalize -> pair -> rank -> export, with no interactive input."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .compare import compare_pair, explain, no_match_summary, rank_pairs
from .config import config_hash
from .export import (PAIR_COLUMNS, RECORD_COLUMNS, TOP_COLUMNS, pair_row, record_row,
                     write_csv, _source)
from .ingest import ingest, split_pools
import re


def run(data_dir: Path, out_dir: Path, cfg: dict, label: str = "") -> dict:
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    res = ingest(data_dir, cfg)
    refs, tgts = split_pools(res.executed)

    pairs = []
    for t in tgts:
        for r in refs:
            pairs.append({"ref": r, "tgt": t, "r": compare_pair(r, t, cfg)})
    rank_pairs(pairs, cfg)

    pair_rows = [pair_row(p, explain(p["ref"], p["tgt"], p["r"])) for p in pairs]
    pair_rows.sort(key=lambda x: (x["target_record_id"], x["rank"] is None, x["rank"] or 0,
                                  x["reference_record_id"]))
    top_rows = []
    top_n = cfg["ranking"]["top_n"]
    for t in tgts:
        group = [p for p in pairs if p["tgt"] is t]
        best = sorted((p for p in group if p["r"]["rank"]), key=lambda p: p["r"]["rank"])[:top_n]
        base = {"target_record_id": t.record_id, "target_programme": t.text["programme"],
                "target_experiment_id": t.text["experiment_id"], "target_fuel": t.text["fuel_identity"],
                "target_source": _source(t)}
        if not best:
            top_rows.append({**base, "outcome": "no_qualifying_match",
                             "no_match_reason": (no_match_summary(group) if group
                                                 else "no reference runs available")})
            continue
        for p in best:
            r, ref = p["r"], p["ref"]
            top_rows.append({**base, "outcome": "match", "rank": r["rank"],
                             "reference_record_id": ref.record_id,
                             "reference_programme": ref.text["programme"],
                             "reference_experiment_id": ref.text["experiment_id"],
                             "reference_fuel": ref.text["fuel_identity"], "eligibility_tier": r["tier"],
                             "provisional_score_UNVALIDATED": (round(r["provisional_score"], 4)
                                                               if r["provisional_score"] is not None else None),
                             "data_completeness": round(r["completeness"], 4),
                             "missing_parameters": r["missing"],
                             "match_explanation": explain(ref, t, r),
                             "reference_source": _source(ref)})

    write_csv(out_dir / "executed_experiments.csv", RECORD_COLUMNS, [record_row(r) for r in res.executed])
    write_csv(out_dir / "planned_experiments.csv", RECORD_COLUMNS, [record_row(r) for r in res.supplementary])
    write_csv(out_dir / "excluded_records.csv", ["exclusion_reason"] + RECORD_COLUMNS,
              [{**record_row(r), "exclusion_reason": why} for r, why in res.excluded])
    write_csv(out_dir / "pairwise_comparability.csv", PAIR_COLUMNS, pair_rows)
    write_csv(out_dir / "top_matches_by_saffire.csv", TOP_COLUMNS, top_rows)
    write_csv(out_dir / "source_inventory.csv", ["path", "bytes", "sha256", "role", "detected_as"],
              res.inventory)

    n_todo = _write_todo(out_dir, res.executed, refs, tgts)
    tiers = Counter(p["r"]["tier"] for p in pairs)
    summary = {"references": len(refs), "targets": len(tgts), "pairs": len(pairs),
               "tiers": dict(tiers), "targets_with_match": len({r["target_record_id"] for r in top_rows if r["outcome"] == "match"}),
               "targets_without_match": sum(1 for r in top_rows if r["outcome"] == "no_qualifying_match"),
               "planned_or_supplementary": len(res.supplementary), "excluded": len(res.excluded),
               "todo_rows": n_todo,
               "notes": res.notes}
    flag_counts = Counter(f for r in res.executed + res.supplementary for f in r.flags)
    _write_log(out_dir, cfg, res, summary, label)
    _write_report(out_dir, cfg, res, summary, flag_counts)
    return summary


TODO_COLUMNS = ["priority", "programme", "experiment_id", "ref_fuel_in_table", "ref_table_location",
                "ref_missing", "ref_current_raw_values", "fuel_name", "flow_direction",
                "airflow_value", "airflow_unit", "oxygen_value", "oxygen_unit_or_basis",
                "sample_thickness", "sample_length", "duct_height", "duct_width", "dimension_unit",
                "source_file", "source_location", "notes"]


def _natural(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _write_todo(out_dir, executed, refs, tgts) -> int:
    """todo_fill_in.csv: one row per executed run that lacks a field needed for matching.
    Fill the blank columns, save into data/runs/, and the values are merged over the raw table."""
    shared = ({r.text["fuel_identity"] for r in refs} & {r.text["fuel_identity"] for r in tgts}) - {""}
    rows = []
    for r in executed:
        miss, raws = [], []
        if r.text["flow_direction"] not in ("concurrent", "opposed"):
            miss.append("flow_direction")
        if not r.q["airflow"].known:
            miss.append("airflow_value+airflow_unit")
            if r.q["airflow"].raw_text:
                raws.append(f"airflow='{r.q['airflow'].raw_text}'")
        if not r.text["fuel_identity"]:
            miss.append("fuel_name")
        if not r.q["oxygen_mole_fraction"].known:
            miss.append("oxygen_value+oxygen_unit_or_basis")
            if r.q["oxygen"].raw_text:
                raws.append(f"oxygen='{r.q['oxygen'].raw_text}'")
        if not r.q["sample_thickness"].known:
            miss.append("sample_thickness")
            if r.q["sample_thickness"].raw_text:
                raws.append(f"thickness='{r.q['sample_thickness'].raw_text}'")
        if "duplicate_experiment_id_disambiguated_by_row" in r.flags:
            miss.append("(duplicate id: tell me which row)")
        if not miss:
            continue
        ident = r.text["fuel_identity"]
        rows.append({"priority": 1 if (not ident or ident in shared) else 2,
                     "programme": r.text["programme"], "experiment_id": r.text["experiment_id"],
                     "ref_fuel_in_table": r.text["fuel_name"],
                     "ref_table_location": f"{r.text['curation_file']} row {r.text['curation_row']}",
                     "ref_missing": miss, "ref_current_raw_values": "; ".join(raws)})
    rows.sort(key=lambda x: (x["priority"], x["programme"], _natural(x["experiment_id"])))
    write_csv(out_dir / "todo_fill_in.csv", TODO_COLUMNS, rows)
    return len(rows)


def _write_log(out_dir, cfg, res, summary, label):
    log = {"tool": "bassfire_comp", "version": __version__, "label": label,
           "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "config_hash": config_hash(cfg), "config": cfg, "summary": summary,
           "inputs": res.inventory}
    (out_dir / "run_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")


def _write_report(out_dir, cfg, res, s, flag_counts):
    L = ["# BASSFIRE comparability run", "",
         f"- Reference runs (BASS / BASS-II, executed): **{s['references']}**",
         f"- Target runs (SAFFIRE I-III, executed): **{s['targets']}**",
         f"- Pairs compared: **{s['pairs']}**  (tiers: {s['tiers'] or 'none'})",
         f"- Targets with a qualifying match: **{s['targets_with_match']}**; "
         f"with no qualifying match: **{s['targets_without_match']}**",
         f"- Planned / SAFFIRE IV-VI records kept separately: {s['planned_or_supplementary']}",
         f"- Records excluded (see excluded_records.csv): {s['excluded']}",
         f"- Runs missing something needed for matching (todo_fill_in.csv): {s['todo_rows']}", ""]
    if s["references"] == 0 or s["targets"] == 0:
        L += ["**No pairs could be formed.** Put curated run tables in `data/runs/` or raw "
              "downloads in `data/raw/PSI-nn/...`; see README. Check excluded_records.csv "
              "for rows that were read but rejected, and source_inventory.csv for files "
              "that were not recognized as run tables.", ""]
    L += ["## Read this before using the ranking", "",
          "- Tolerances, thresholds and the provisional score are **placeholders, not validated** "
          "against manually reviewed pairs. Ranking is a screening aid, not equivalence.",
          "- Unknown values are never filled in. They show as missing and reduce data_completeness.",
          "- Dimension definitions are flagged `dimension_definitions_unreviewed` until you set "
          "`dimension_definition_status = verified`.", ""]
    if flag_counts:
        L += ["## Record flags", ""] + [f"- `{k}`: {v}" for k, v in sorted(flag_counts.items())] + [""]
    if res.notes:
        L += ["## Ingest notes", ""] + [f"- {n}" for n in res.notes] + [""]
    (out_dir / "run_report.md").write_text("\n".join(L), encoding="utf-8")
