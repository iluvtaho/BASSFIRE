"""Turn one row into a normalized Record (nothing is guessed; every transform is flagged)."""
from __future__ import annotations

import re

from . import units as U
from .schema import (CATEGORICAL, INPUT_QUANTITIES, MISSING_REASONS, Quantity, Record,
                     canon_categorical)

_NA_TOKENS = {"n/a", "na", "nan", "none", "null", "-", "--", "unknown"}
_BLANK_TOKENS = {"tbd", "?", ""}
_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)"
_UNIT = r"[A-Za-z\u00b5\u03bc\u00b0%][A-Za-z\u00b5\u03bc\u00b0%/\^\-0-9]*"
_RANGE_RE = re.compile(rf"^\s*[~\u2248]?\s*({_NUM})\s*(?:-|\u2013|to)\s*({_NUM})\s*({_UNIT})?\s*$", re.I)
_SINGLE_RE = re.compile(rf"^\s*[~\u2248]?\s*({_NUM})\s*({_UNIT})?\s*$")
_LEADING_ZERO = re.compile(r"^[-+]?0\d")


def parse_value(text: str) -> dict:
    """-> {value, unit, reason, notes}. Handles '~ 21.5', '0.33 cm', '21.5 - 21.7'.
    Leading-zero integers such as '037' are ambiguous (likely typos), never read as 37."""
    t = (text or "").strip()
    low = t.lower()
    out = {"value": None, "unit": "", "reason": None, "notes": [], "approx": False, "range": False}
    if low in _BLANK_TOKENS:
        out["reason"] = "not_extracted"
    elif low in MISSING_REASONS:
        out["reason"] = low
    elif low in _NA_TOKENS:
        out["reason"] = "not_reported"
    else:
        m = _SINGLE_RE.match(t)
        r = None if m else _RANGE_RE.match(t)
        if m:
            if _LEADING_ZERO.match(m.group(1)):
                out["reason"] = "ambiguous_definition"
                out["notes"].append("leading-zero number (possible typo) not interpreted")
            else:
                out["value"], out["unit"] = float(m.group(1)), (m.group(2) or "")
                out["approx"] = t.lstrip().startswith(("~", "\u2248"))
        elif r:
            if _LEADING_ZERO.match(r.group(1)) or _LEADING_ZERO.match(r.group(2)):
                out["reason"] = "ambiguous_definition"
            else:
                a, b = float(r.group(1)), float(r.group(2))
                out["value"], out["unit"], out["range"] = (a + b) / 2.0, (r.group(3) or ""), True
                out["notes"].append(f"midpoint of range {r.group(1)} to {r.group(2)}")
        else:
            out["reason"] = "ambiguous_definition"
    return out


def parse_cell(text: str):
    """Back-compat helper: (value|None, missing_reason|None)."""
    p = parse_value(text)
    return p["value"], p["reason"]


def _quantity(name, kind, value_text, unit_text, rec, cfg, pressure_basis) -> Quantity:
    q = Quantity(name, raw_text=(value_text or "").strip(), raw_unit=(unit_text or "").strip())
    p = parse_value(value_text)
    if p["value"] is None:
        q.missing_reason = p["reason"]
        if p["reason"] == "ambiguous_definition":
            rec.flag(f"{name}_unparseable_or_ambiguous_value")
        return q
    val = p["value"]
    q.raw_value = val
    if p["approx"]:
        rec.flag(f"{name}_approximate_value")
    if p["range"]:
        rec.flag(f"{name}_range_midpoint_used")
    emb = p["unit"]
    if emb:
        if kind == "oxygen":
            if U.classify_oxygen_basis(unit_text)[0] == "unknown":
                unit_text = emb
        else:
            if unit_text and U.unit_key(unit_text) != U.unit_key(emb):
                rec.flag(f"{name}_unit_conflict_header_vs_cell")
            unit_text = emb
    q.raw_unit = (unit_text or "").strip()

    def fail(why: str, flag: str):
        q.missing_reason = "ambiguous_definition"
        q.method = why
        rec.flag(flag)
        return q

    try:
        if kind == "oxygen":
            _oxygen(q, val, unit_text, rec, cfg)
        elif not q.raw_unit:
            return fail("unit missing", f"{name}_unit_missing")
        elif kind == "length":
            q.si_value, q.si_unit, q.method = U.to_length_m(val, unit_text)
        elif kind == "velocity":
            q.si_value, q.si_unit, q.method = U.to_velocity_ms(val, unit_text)
        elif kind == "temperature":
            q.si_value, q.si_unit, q.method = U.to_temperature_k(val, unit_text)
        elif kind == "pressure":
            si, q.si_unit, q.method, hint = U.to_pressure_pa(val, unit_text)
            basis = hint or pressure_basis
            if basis == "gauge":
                q.si_unit = ""
                return fail("gauge pressure not converted (atmospheric reference unknown)",
                            "pressure_gauge_not_absolute")
            q.si_value = si
            if basis == "unknown":
                rec.flag("pressure_basis_unknown")
    except U.UnitError as exc:
        return fail(str(exc), f"{name}_unit_unrecognized")
    if p["notes"] and q.known:
        q.method = "; ".join(p["notes"] + [q.method])
    return q


def _oxygen(q: Quantity, val: float, unit_text: str, rec: Record, cfg: dict) -> None:
    kind, factor, note = U.classify_oxygen_basis(unit_text)
    if kind in ("unknown", "unspecified"):
        default = cfg["ingest"]["oxygen_basis_by_investigation"].get(
            rec.text.get("investigation_id", ""), "")
        if default:
            k2, f2, n2 = U.classify_oxygen_basis(default)
            if k2 == "mole":
                kind, factor, note = k2, f2, (n2 or "") + ("; " if n2 else "") + \
                    f"basis '{default}' supplied by config"
                rec.flag("oxygen_basis_from_config")
    if kind == "mole":
        q.si_value, q.si_unit = val * factor, "mole_fraction"
        q.method = "; ".join(x for x in (f"{q.raw_unit or 'config basis'} -> mole fraction", note) if x)
    elif kind == "partial":
        si, _, method, _ = U.to_pressure_pa(val, factor)
        q.si_value, q.si_unit, q.method = si, "Pa", "partial pressure; " + method
    elif kind == "unspecified" and cfg["ingest"]["assume_percent_oxygen_is_mole_fraction"]:
        q.si_value, q.si_unit = val * factor, "mole_fraction"
        q.method = "basis unspecified; ASSUMED mole fraction (config)"
        rec.flag("oxygen_basis_assumed_mole_fraction")
    else:
        q.missing_reason = "ambiguous_definition"
        q.method = ("oxygen basis unspecified" if kind == "unspecified"
                    else "oxygen unit/basis missing or unrecognized")
        rec.flag("oxygen_basis_unspecified" if kind == "unspecified" else "oxygen_basis_missing")


# ---------------- material-string interpretation ----------------
_LEN_TOKEN = re.compile(r"(?<![\w/\"])(\d+(?:\.\d+)?|\.\d+)\s*(microns?|um|\u00b5m|\u03bcm|mm|cm)\b(\s*(wide|thick))?",
                        re.I)


def _fuel_and_shape(rec: Record, fields: dict, cfg: dict) -> dict:
    """Sets fuel_identity / category / shape on rec; returns dimension fields parsed from the
    material string (only for blank columns, only when enabled)."""
    fc = cfg["fuel"]
    name = rec.text["fuel_name"]
    ident = ""
    if name:
        hits = sorted({r["name"] for r in fc["identity_rules"] if re.search(r["pattern"], name)})
        if len(hits) == 1:
            ident = hits[0]
        elif len(hits) > 1:
            ident = "+".join(hits)
            rec.flag("fuel_composite_sample")
        else:
            ident = re.sub(r"\s+", " ", name).strip()
    rec.text["fuel_identity"] = ident
    if ident and not rec.text["fuel_category"] and ident in fc["category_by_identity"]:
        rec.text["fuel_category"] = fc["category_by_identity"][ident]
        rec.flag("fuel_category_from_config")
    if not rec.text["sample_shape"] and name:
        low = name.lower()
        for kw, shape in fc["shape_keywords"].items():
            if re.search(rf"\b{re.escape(kw)}\b", low):
                rec.text["sample_shape"] = shape
                rec.flag("sample_shape_parsed_from_material")
                break
        else:
            if ident in fc["default_shape_by_identity"]:
                rec.text["sample_shape"] = fc["default_shape_by_identity"][ident]
                rec.flag("sample_shape_from_config")
    rec.text["sample_shape"] = rec.text["sample_shape"].strip().lower()

    parsed = {}
    if not (cfg["ingest"]["parse_material_strings"] and name):
        return parsed
    if rec.get("flow_direction") == "unknown" and re.search(r"\bopp\w*sed\b", name, re.I):
        rec.text["flow_direction"] = "opposed"
        rec.flag("flow_direction_parsed_from_material_string")
    toks = [(m.group(1), m.group(2).lower(), (m.group(4) or "").lower())
            for m in _LEN_TOKEN.finditer(name)]
    thick = [t for t in toks if t[1] != "cm"]
    cms = [t for t in toks if t[1] == "cm"]
    if len(thick) == 1 and not (fields.get("sample_thickness") or "").strip():
        parsed["sample_thickness"] = f"{thick[0][0]} {thick[0][1]}"
    if (len(cms) == 1 and rec.text["sample_shape"] not in ("sphere", "rod", "candle")
            and not (fields.get("sample_width") or "").strip()
            and (cms[0][2] == "wide" or len(thick) == 1
                 or ident in fc["width_from_cm_identities"])):
        parsed["sample_width"] = f"{cms[0][0]} cm"
    return parsed


def build_record(fields: dict, header_units: dict, cfg: dict) -> Record:
    """fields: canonical column -> raw cell text. header_units: column -> unit from header."""
    rec = Record(record_id=fields.get("record_id", ""))
    for f in ("programme", "investigation_id", "experiment_id", "fuel_name", "fuel_composition",
              "fuel_category", "sample_shape", "sample_position", "source_url", "source_doi",
              "source_file", "source_location", "retrieved_at", "notes", "curation_file",
              "curation_row"):
        rec.text[f] = (fields.get(f) or "").strip()
    for f in CATEGORICAL:
        raw = (fields.get(f) or "").strip()
        value, ok = canon_categorical(f, raw)
        rec.text[f], rec.raw_text[f] = value, raw
        if not ok:
            rec.flag(f"{f}_unrecognized_value")
    if rec.text["fuel_name"] == "":
        rec.flag("fuel_name_missing")

    fields = dict(fields)
    for k, v in _fuel_and_shape(rec, fields, cfg).items():
        fields[k] = v
        rec.flag(f"{k}_parsed_from_material_string")

    pbasis = rec.text["pressure_basis"]
    shared_dim_unit = (fields.get("dimension_unit") or "").strip()
    for name, kind in INPUT_QUANTITIES.items():
        col = {"airflow": "airflow_value", "oxygen": "oxygen_value",
               "pressure": "pressure_value", "temperature": "temperature_value"}.get(name, name)
        unit_col = {"airflow": "airflow_unit", "oxygen": "oxygen_unit_or_basis",
                    "pressure": "pressure_unit", "temperature": "temperature_unit"}.get(
                        name, f"{name}_unit")
        unit = ((fields.get(unit_col) or "").strip() or header_units.get(col, "")
                or (shared_dim_unit if kind == "length" else ""))
        rec.q[name] = _quantity(name, kind, fields.get(col, ""), unit, rec, cfg, pbasis)

    _derive(rec)
    if rec.text["dimension_definition_status"] != "verified":
        rec.flag("dimension_definitions_unreviewed")
    if rec.text["verification_status"] in ("digitized", "conflicting", "needs_review"):
        rec.flag(f"verification_{rec.text['verification_status']}")
    return rec


def _derive(rec: Record) -> None:
    ox, p = rec.q["oxygen"], rec.q["pressure"]
    frac = Quantity("oxygen_mole_fraction", missing_reason="not_extracted")
    ppo2 = Quantity("oxygen_partial_pressure", missing_reason="not_extracted")
    if ox.known and ox.si_unit == "mole_fraction":
        frac.si_value, frac.si_unit, frac.method = ox.si_value, "mole_fraction", "from oxygen input"
        frac.missing_reason = None
        if p.known:
            ppo2.si_value, ppo2.si_unit = ox.si_value * p.si_value, "Pa"
            ppo2.method, ppo2.missing_reason = "derived: mole fraction x total pressure", None
    elif ox.known and ox.si_unit == "Pa":
        ppo2.si_value, ppo2.si_unit, ppo2.method = ox.si_value, "Pa", "from oxygen input"
        ppo2.missing_reason = None
        if p.known and p.si_value > 0:
            frac.si_value, frac.si_unit = ox.si_value / p.si_value, "mole_fraction"
            frac.method, frac.missing_reason = "derived: partial pressure / total pressure", None
    else:
        frac.missing_reason = ppo2.missing_reason = ox.missing_reason or "not_extracted"
    rec.q["oxygen_mole_fraction"], rec.q["oxygen_partial_pressure"] = frac, ppo2

    ratio = Quantity("sample_duct_width_ratio", missing_reason="ambiguous_definition")
    denom = rec.text["ratio_denominator"]
    w = rec.q["sample_width"]
    if not denom:
        if w.known and (rec.q["duct_height"].known or rec.q["duct_width"].known):
            rec.flag("ratio_denominator_missing")
        ratio.method = "ratio denominator not named"
    else:
        d = rec.q[denom]
        if w.known and d.known and d.si_value > 0:
            ratio.si_value, ratio.si_unit = w.si_value / d.si_value, "dimensionless"
            ratio.method, ratio.missing_reason = f"sample_width / {denom}", None
        else:
            ratio.missing_reason, ratio.method = "not_extracted", f"needs sample_width and {denom}"
    rec.q["sample_duct_width_ratio"] = ratio
