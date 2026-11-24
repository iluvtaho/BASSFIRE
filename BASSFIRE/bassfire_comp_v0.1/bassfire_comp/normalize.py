"""Turn one curated/auto-detected row into a normalized Record (nothing is guessed)."""
from __future__ import annotations

from . import units as U
from .schema import (CATEGORICAL, INPUT_QUANTITIES, MISSING_REASONS, Quantity, Record,
                     canon_categorical)

_NA_TOKENS = {"n/a", "na", "nan", "none", "null", "-", "--", "unknown"}
_BLANK_TOKENS = {"tbd", "?", ""}


def parse_cell(text: str):
    """Return (float|None, missing_reason|None)."""
    t = (text or "").strip()
    low = t.lower()
    if low in _BLANK_TOKENS:
        return None, "not_extracted"
    if low in MISSING_REASONS:
        return None, low
    if low in _NA_TOKENS:
        return None, "not_reported"
    try:
        return float(t), None
    except ValueError:
        return None, "ambiguous_definition"


def _quantity(name: str, kind: str, value_text: str, unit_text: str, rec: Record,
              cfg: dict, pressure_basis: str) -> Quantity:
    q = Quantity(name, raw_text=(value_text or "").strip(), raw_unit=(unit_text or "").strip())
    val, reason = parse_cell(value_text)
    if val is None:
        q.missing_reason = reason
        if reason == "ambiguous_definition":
            rec.flag(f"{name}_unparseable_value")
        return q
    q.raw_value = val

    def fail(why: str, flag: str):
        q.missing_reason = "ambiguous_definition"
        q.method = why
        rec.flag(flag)
        return q

    try:
        if kind == "oxygen":
            return _oxygen(q, val, unit_text, rec, cfg)
        if not q.raw_unit:
            return fail("unit missing", f"{name}_unit_missing")
        if kind == "length":
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
    return q


def _oxygen(q: Quantity, val: float, unit_text: str, rec: Record, cfg: dict) -> Quantity:
    kind, factor, note = U.classify_oxygen_basis(unit_text)
    if kind == "mole":
        q.si_value, q.si_unit = val * factor, "mole_fraction"
        q.method = ("; ".join(x for x in (f"{q.raw_unit} -> mole fraction", note) if x))
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
        rec.flag("oxygen_basis_unspecified" if kind == "unspecified"
                 else "oxygen_basis_missing")
    return q


def build_record(fields: dict, header_units: dict, cfg: dict) -> Record:
    """fields: canonical column -> raw cell text. header_units: column -> unit from header."""
    rec = Record(record_id=fields.get("record_id", ""))
    for f in ("programme", "investigation_id", "experiment_id", "fuel_name",
              "fuel_composition", "fuel_category", "sample_position", "source_url",
              "source_doi", "source_file", "source_location", "retrieved_at", "notes",
              "curation_file", "curation_row"):
        rec.text[f] = (fields.get(f) or "").strip()
    for f in CATEGORICAL:
        raw = (fields.get(f) or "").strip()
        value, ok = canon_categorical(f, raw)
        rec.text[f], rec.raw_text[f] = value, raw
        if not ok:
            rec.flag(f"{f}_unrecognized_value")
    if rec.text["fuel_name"] == "":
        rec.flag("fuel_name_missing")

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
