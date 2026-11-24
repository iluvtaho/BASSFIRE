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
                "target_experiment_id": t.text["experiment_id"], "target_fuel": t.text["fuel_name"],
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
                             "reference_fuel": ref.text["fuel_name"], "eligibility_tier": r["tier"],
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

    tiers = Counter(p["r"]["tier"] for p in pairs)
    summary = {"references": len(refs), "targets": len(tgts), "pairs": len(pairs),
               "tiers": dict(tiers), "targets_with_match": len({r["target_record_id"] for r in top_rows if r["outcome"] == "match"}),
               "targets_without_match": sum(1 for r in top_rows if r["outcome"] == "no_qualifying_match"),
               "planned_or_supplementary": len(res.supplementary), "excluded": len(res.excluded),
               "notes": res.notes}
    flag_counts = Counter(f for r in res.executed + res.supplementary for f in r.flags)
    _write_log(out_dir, cfg, res, summary, label)
    _write_report(out_dir, cfg, res, summary, flag_counts)
    return summary


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
         f"- Records excluded (see excluded_records.csv): {s['excluded']}", ""]
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
