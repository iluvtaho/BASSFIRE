"""Eligibility tiers, parameter comparison, subscores, provisional ranking, explanations."""
from __future__ import annotations

import re
from collections import Counter

TIER_ORDER = {"direct": 0, "exploratory": 1, "needs_review": 2, "ineligible": 3}
SUBSCORE_PARAMS = {
    "material": ["sample_thickness"],
    "environment": ["airflow", "oxygen_mole_fraction", "oxygen_partial_pressure",
                    "pressure", "temperature"],
    "geometry": ["sample_width", "sample_length", "duct_height", "duct_width",
                 "duct_length", "sample_duct_width_ratio"],
}
NUMERIC_PARAMS = [p for ps in SUBSCORE_PARAMS.values() for p in ps]
UNIT_LABEL = {"airflow": "m/s", "oxygen_mole_fraction": "", "oxygen_partial_pressure": "Pa",
              "pressure": "Pa", "temperature": "K", "sample_duct_width_ratio": ""}
DECISIVE = {
    "flow_direction": {"concurrent", "opposed"},
    "gravity_environment": {"microgravity", "ground"},
    "airflow_measurement_type": {"inlet", "local", "duct_average"},
}


def fuel_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def fuel_relation(ref, tgt, cfg) -> str:
    a, b = ref.get("fuel_name"), tgt.get("fuel_name")
    if not a or not b:
        return "unknown"
    ka, kb = fuel_key(a), fuel_key(b)
    if ka == kb:
        return "exact"
    for group in cfg["fuel"]["alias_groups"]:
        keys = {fuel_key(x) for x in group}
        if ka in keys and kb in keys:
            return "exact"
    ca, cb = fuel_key(ref.get("fuel_category")), fuel_key(tgt.get("fuel_category"))
    if ca and cb and ca == cb:
        return "related"
    return "different"


def _cat_match(field: str, ref, tgt) -> str:
    a, b = ref.get(field), tgt.get(field)
    ok = DECISIVE[field]
    if a in ok and b in ok:
        return "match" if a == b else "mismatch"
    return "unknown"


def compare_numeric(name: str, a, b, cfg) -> dict:
    out = {"label": "unknown", "ref": a.si_value, "tgt": b.si_value, "abs_diff": None,
           "rel_diff": None, "score": None}
    if not (a.known and b.known):
        return out
    d = abs(a.si_value - b.si_value)
    out["abs_diff"] = d
    if abs(b.si_value) > 1e-12:
        out["rel_diff"] = d / abs(b.si_value)
    tol = cfg["tolerances"][name]
    if tol["mode"] == "absolute":
        x = d / tol["tol"]
    elif out["rel_diff"] is None:
        x = 0.0 if d <= 1e-12 else 1.0
    else:
        x = out["rel_diff"] / tol["tol"]
    score = max(0.0, 1.0 - x)
    out["score"] = score
    lab = cfg["labels"]
    out["label"] = ("close" if score >= lab["close_min_score"]
                    else "moderate" if score >= lab["moderate_min_score"] else "different")
    return out


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def compare_pair(ref, tgt, cfg) -> dict:
    el = cfg["eligibility"]
    fuel_rel = fuel_relation(ref, tgt, cfg)
    flow = _cat_match("flow_direction", ref, tgt)
    grav = _cat_match("gravity_environment", ref, tgt)
    meas = _cat_match("airflow_measurement_type", ref, tgt)
    warnings = []

    params = {n: compare_numeric(n, ref.q[n], tgt.q[n], cfg) for n in NUMERIC_PARAMS}
    if meas == "mismatch":
        params["airflow"].update(label="not_comparable_definition", score=None)
        warnings.append("airflow_measurement_definition_mismatch")
    elif meas == "unknown" and ref.q["airflow"].known and tgt.q["airflow"].known:
        warnings.append("airflow_measurement_type_unknown")
    rd, td = ref.get("ratio_denominator"), tgt.get("ratio_denominator")
    if ref.q["sample_duct_width_ratio"].known and tgt.q["sample_duct_width_ratio"].known and rd != td:
        params["sample_duct_width_ratio"].update(label="not_comparable_definition", score=None)
        warnings.append("ratio_definition_mismatch")
    if fuel_rel == "different" and not (ref.get("fuel_category") and tgt.get("fuel_category")):
        warnings.append("fuel_category_missing_cannot_judge_relatedness")
    for side, rec in (("ref", ref), ("tgt", tgt)):
        warnings += [f"{side}:{f}" for f in rec.flags]

    # ---- tier ----
    excl, review, down = [], [], []
    if flow == "mismatch":
        excl.append("flow_direction_mismatch")
    if grav == "mismatch":
        excl.append("gravity_mismatch")
    if fuel_rel == "different" and el["unrelated_fuel_tier"] == "ineligible":
        excl.append("fuel_unrelated")
    if excl:
        tier, reasons = "ineligible", excl
    else:
        known = {"flow_direction": flow != "unknown", "gravity_environment": grav != "unknown",
                 "fuel_name": fuel_rel != "unknown", "airflow_measurement_type": meas != "unknown"}
        for key in el["direct_required_known"]:
            if not known.get(key, True):
                review.append(f"{key}_unknown_or_undecided")
        if review:
            tier, reasons = "needs_review", review
        else:
            if fuel_rel == "related":
                down.append("fuel_related_not_identical")
            if fuel_rel == "different":
                down.append("fuel_unrelated")
            if meas == "mismatch":
                down.append("airflow_measurement_definition_mismatch")
            if down and el["exploratory_tier_enabled"]:
                tier, reasons = "exploratory", down
            elif down:
                tier, reasons = "ineligible", down + ["exploratory_tier_disabled"]
            else:
                tier, reasons = "direct", []

    # ---- subscores ----
    fscore = {"exact": cfg["fuel"]["exact_score"], "related": cfg["fuel"]["related_score"],
              "different": cfg["fuel"]["different_score"], "unknown": None}[fuel_rel]
    comps = {
        "material": [fscore, params["sample_thickness"]["score"]],
        "environment": [params[p]["score"] for p in SUBSCORE_PARAMS["environment"]],
        "geometry": [params[p]["score"] for p in SUBSCORE_PARAMS["geometry"]],
        "flow_configuration": [{"match": 1.0, "mismatch": 0.0, "unknown": None}[flow],
                               {"match": 1.0, "mismatch": 0.0, "unknown": None}[meas]],
    }
    subscores = {k: _mean(v) for k, v in comps.items()}
    known_sub = {k: v for k, v in subscores.items() if v is not None}
    prov = None
    if cfg["ranking"]["aggregate_enabled"] and known_sub:
        w = cfg["ranking"]["weights"]
        tot = sum(w[k] for k in known_sub)
        prov = sum(w[k] * v for k, v in known_sub.items()) / tot if tot else None

    # ---- completeness ----
    cat_known = {"fuel_name": fuel_rel != "unknown", "flow_direction": flow != "unknown",
                 "gravity_environment": grav != "unknown",
                 "airflow_measurement_type": meas != "unknown"}
    missing, n_known = [], 0
    plist = cfg["completeness_parameters"]
    for p in plist:
        if p in cat_known:
            ok_ref = ref.get(p) not in ("", "unknown", "other") if p != "fuel_name" else bool(ref.get(p))
            ok_tgt = tgt.get(p) not in ("", "unknown", "other") if p != "fuel_name" else bool(tgt.get(p))
        else:
            ok_ref, ok_tgt = ref.q[p].known, tgt.q[p].known
        if ok_ref and ok_tgt:
            n_known += 1
        else:
            side = "both" if not ok_ref and not ok_tgt else "reference" if not ok_ref else "target"
            missing.append(f"{p}[{side}]")
    completeness = n_known / len(plist) if plist else None

    return {"tier": tier, "tier_reasons": reasons, "warnings": warnings,
            "fuel_relation": fuel_rel, "flow_direction_match": flow, "gravity_match": grav,
            "airflow_measurement_match": meas, "params": params, "subscores": subscores,
            "subscores_known": len(known_sub), "completeness": completeness,
            "missing": missing, "provisional_score": prov}


def explain(ref, tgt, r) -> str:
    tier = r["tier"]
    lead = {"direct": "Direct-tier candidate: same fuel, flow direction, gravity and airflow definition.",
            "exploratory": "Exploratory candidate (not a direct match): " + "; ".join(r["tier_reasons"]) + ".",
            "needs_review": "Cannot be classified yet: " + "; ".join(r["tier_reasons"]) + ".",
            "ineligible": "Excluded from matching: " + "; ".join(r["tier_reasons"]) + "."}[tier]
    close, diff = [], []
    for n, p in r["params"].items():
        if p["label"] in ("close", "moderate", "different") and p["ref"] is not None:
            u = UNIT_LABEL.get(n, "m" if n.startswith(("sample_", "duct_")) else "")
            txt = f"{n} ({p['ref']:.4g} vs {p['tgt']:.4g}{(' ' + u) if u else ''})"
            (close if p["label"] == "close" else diff).append(
                txt if p["label"] == "close" else f"{txt} [{p['label']}]")
    parts = [lead]
    if close:
        parts.append("Close: " + ", ".join(close) + ".")
    if diff:
        parts.append("Differ: " + ", ".join(diff) + ".")
    defs = [n for n, p in r["params"].items() if p["label"] == "not_comparable_definition"]
    if defs:
        parts.append("Not comparable (different definitions): " + ", ".join(defs) + ".")
    if r["missing"]:
        parts.append("Not comparable (missing): " + ", ".join(r["missing"]) + ".")
    if tier in ("direct", "exploratory"):
        parts.append("Screening heuristic only; not a statement of physical equivalence.")
    return " ".join(parts)


def rank_pairs(pairs: list, cfg: dict) -> None:
    """Adds rank / qualifying / non_qualifying_reason into each pair['r'] in place."""
    rk = cfg["ranking"]
    by_target: dict = {}
    for p in pairs:
        by_target.setdefault(p["tgt"].record_id, []).append(p)
    for group in by_target.values():
        for p in group:
            r, why = p["r"], []
            if r["tier"] not in rk["include_tiers"]:
                why.append(f"tier={r['tier']}")
            if r["completeness"] is None or r["completeness"] < rk["min_data_completeness"]:
                why.append("data_completeness_below_threshold")
            if rk["aggregate_enabled"] and (r["provisional_score"] is None
                                            or r["provisional_score"] < rk["min_provisional_score"]):
                why.append("provisional_score_below_threshold")
            r["qualifying"] = not why
            r["non_qualifying_reason"] = "; ".join(why)
            r["rank"] = None
        qual = sorted((p for p in group if p["r"]["qualifying"]),
                      key=lambda p: (TIER_ORDER[p["r"]["tier"]],
                                     -(p["r"]["provisional_score"] or -1.0),
                                     -(p["r"]["completeness"] or 0.0), p["ref"].record_id))
        for i, p in enumerate(qual, start=1):
            p["r"]["rank"] = i


def no_match_summary(group: list) -> str:
    tiers = Counter(p["r"]["tier"] for p in group)
    reasons = Counter()
    for p in group:
        for t in p["r"]["tier_reasons"]:
            reasons[t] += 1
        if p["r"]["tier"] in ("direct", "exploratory") and p["r"]["non_qualifying_reason"]:
            reasons[p["r"]["non_qualifying_reason"]] += 1
    top = ", ".join(f"{k} (x{v})" for k, v in reasons.most_common(3))
    return (f"{len(group)} reference run(s) considered: " +
            ", ".join(f"{k}={tiers.get(k, 0)}" for k in TIER_ORDER) +
            (f". Most common blockers: {top}" if top else ""))
