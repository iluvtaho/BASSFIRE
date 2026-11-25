"""Find, read, validate and route records from data/runs, data/planned and data/raw."""
from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from .normalize import build_record
from .schema import (EXECUTED_STATUSES, PSI_MANIFEST, PROGRAMME_TO_PSI, REFERENCE_PROGRAMMES,
                     SUPPLEMENTARY_PROGRAMMES, TARGET_PROGRAMMES, canon_investigation,
                     canon_programme, psi_url)

_ALIAS_SOURCE = {
    "programme": "programme program mission",
    "investigation_id": "investigationid psiid psi",
    "experiment_id": "experimentid runid run testid test runnumber runno testnumber samplenumber sampleno",
    "record_status": "recordstatus status",
    "evidence_status": "evidencestatus",
    "fuel_name": "fuelname fuel material materialname specimen samplematerial fuelsamplematerial",
    "fuel_composition": "fuelcomposition composition",
    "fuel_category": "fuelcategory materialfamily materialcategory",
    "flow_direction": "flowdirection direction flowmode flowconfiguration flamespreaddirection spreaddirection",
    "gravity_environment": "gravityenvironment gravity",
    "airflow_value": "airflowvalue airflow flowspeed flowvelocity airspeed velocity windspeed airflowspeed",
    "airflow_unit": "airflowunit flowspeedunit velocityunit",
    "airflow_measurement_type": "airflowmeasurementtype flowmeasurementtype velocitymeasurement",
    "oxygen_value": "oxygenvalue oxygen o2 o2concentration oxygenconcentration o2percent oxygenpercent percento2 o2fraction ambiento2 calibratedinitialo2byvol",
    "oxygen_unit_or_basis": "oxygenunitorbasis oxygenunit oxygenbasis o2unit o2basis",
    "pressure_value": "pressurevalue pressure totalpressure ambientpressure testpressure",
    "pressure_unit": "pressureunit",
    "pressure_basis": "pressurebasis",
    "temperature_value": "temperaturevalue temperature ambienttemperature initialtemperature temp",
    "temperature_unit": "temperatureunit tempunit",
    "sample_width": "samplewidth specimenwidth fuelwidth",
    "sample_length": "samplelength specimenlength fuellength",
    "sample_thickness": "samplethickness samlethickness thickness fuelthickness specimenthickness",
    "duct_height": "ductheight channelheight",
    "duct_width": "ductwidth channelwidth",
    "duct_length": "ductlength channellength",
    "dimension_unit": "dimensionunit lengthunit",
    "sample_width_unit": "samplewidthunit", "sample_length_unit": "samplelengthunit",
    "sample_thickness_unit": "samplethicknessunit", "duct_height_unit": "ductheightunit",
    "duct_width_unit": "ductwidthunit", "duct_length_unit": "ductlengthunit",
    "sample_position": "sampleposition",
    "ratio_denominator": "ratiodenominator",
    "dimension_definition_status": "dimensiondefinitionstatus",
    "source_url": "sourceurl url", "source_doi": "sourcedoi doi",
    "source_file": "sourcefile", "source_location": "sourcelocation",
    "retrieved_at": "retrievedat retrievaldate", "verification_status": "verificationstatus",
    "notes": "notes note comments",
    "sample_shape": "sampleshape shape",
}
ALIAS_MAP = {}
for _field, _names in _ALIAS_SOURCE.items():
    ALIAS_MAP[re.sub(r"[^a-z0-9]", "", _field)] = _field
    for _n in _names.split():
        ALIAS_MAP[_n] = _field

IMPLIED_UNIT = {"percento2": "percent", "calibratedinitialo2byvol": "volume_percent"}
DIMS = ["sample_width", "sample_length", "sample_thickness", "duct_height", "duct_width",
        "duct_length"]
GROUPS = [("airflow_value", "airflow_unit"),
          ("oxygen_value", "oxygen_unit_or_basis"),
          ("pressure_value", "pressure_unit", "pressure_basis"),
          ("temperature_value", "temperature_unit")] + [(d, d + "_unit") for d in DIMS]
GROUP_OF = {f: g for g in GROUPS for f in g}
_NON_RUN_ID = re.compile(r"^(note\b|F\d+C\d+)", re.I)

DETECTION_FIELDS = {"fuel_name", "flow_direction", "airflow_value", "oxygen_value",
                    "pressure_value", "temperature_value", "sample_width", "sample_length",
                    "sample_thickness", "duct_height", "gravity_environment"}
_UNIT_RE = re.compile(r"^(.*?)\s*[\(\[]([^)\]]*)[\)\]]\s*$")


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (h or "").lower())


def map_header(header: str):
    """Return (field|None, unit_from_header). 'Note n' parentheses are not units."""
    key = _norm(header)
    if key in ALIAS_MAP:
        return ALIAS_MAP[key], IMPLIED_UNIT.get(key, "")
    m = _UNIT_RE.match(header or "")
    if m and _norm(m.group(1)) in ALIAS_MAP:
        base, unit = _norm(m.group(1)), m.group(2).strip()
        if re.match(r"(?i)^note\b", unit):
            unit = ""
        return ALIAS_MAP[base], unit or IMPLIED_UNIT.get(base, "")
    return None, ""


@dataclass
class IngestResult:
    executed: list = field(default_factory=list)
    supplementary: list = field(default_factory=list)   # planned + SAFFIRE IV-VI
    excluded: list = field(default_factory=list)        # (Record, reason)
    inventory: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _open_text(path: Path):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            with open(path, encoding=enc) as fh:
                fh.read(1 << 16)
            return open(path, encoding=enc, newline="")
        except UnicodeDecodeError:
            continue
    return open(path, encoding="utf-8", errors="replace", newline="")


def _csv_tables(path: Path, header_only: bool):
    with _open_text(path) as fh:
        first = fh.readline()
        fh.seek(0)
        delim = max(",;\t", key=lambda d: first.count(d)) if any(d in first for d in ",;\t") else ","
        reader = csv.reader(fh, delimiter=delim)
        header = None
        rows = []
        for i, row in enumerate(reader, start=1):
            if not any(c.strip() for c in row):
                continue
            if header is None:
                header = [c.strip() for c in row]
                if header_only:
                    break
                continue
            rows.append((i, row))
    return [("", header, rows)] if header else []


def _xlsx_tables(path: Path, header_only: bool, notes: list):
    try:
        import openpyxl
    except ImportError:
        notes.append(f"SKIPPED {path.name}: install openpyxl to read .xlsx (pip install openpyxl)")
        return []
    out = []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        header, rows = None, []
        for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
            cells = ["" if c is None else (str(int(c)) if isinstance(c, float) and c.is_integer()
                                           else str(c)) for c in row]
            if not any(c.strip() for c in cells):
                continue
            if header is None:
                header = [c.strip() for c in cells]
                if header_only:
                    break
                continue
            rows.append((i, cells))
        if header:
            out.append((ws.title, header, rows))
    wb.close()
    return out


def read_tables(path: Path, header_only: bool, notes: list):
    ext = path.suffix.lower()
    if ext in (".csv", ".tsv", ".txt"):
        return _csv_tables(path, header_only)
    if ext in (".xlsx", ".xlsm"):
        return _xlsx_tables(path, header_only, notes)
    return []


def _context_investigation(path: Path) -> str:
    for part in reversed(path.parts):
        inv = canon_investigation(part)
        if inv in PSI_MANIFEST:
            return inv
    return ""


def _collect_rows(sheet, header, rows, rel_name, kind, ctx_inv, notes):
    """Header-mapped raw rows (not yet normalized). kind: 'curated' | 'auto'."""
    mapped = [map_header(h) for h in header]
    unmapped = [h for h, (f, _) in zip(header, mapped)
                if f is None and h and not h.strip().lower().startswith('ref_')]
    if unmapped:
        notes.append(f"{rel_name}{(' [' + sheet + ']') if sheet else ''}: "
                     f"{len(unmapped)} column(s) not mapped and ignored: "
                     + ", ".join(h.strip() for h in unmapped[:12]) + (" ..." if len(unmapped) > 12 else ""))
    out = []
    for rownum, row in rows:
        fields, hunits = {}, {}
        for (f, unit), cell in zip(mapped, row):
            if f is None or f in fields:
                continue
            fields[f] = cell
            if unit:
                hunits[f] = unit
        if not any((v or "").strip() for v in fields.values()):
            continue
        du = (fields.pop("dimension_unit", "") or "").strip()
        for d in DIMS:
            if du and (fields.get(d) or "").strip() and not (fields.get(d + "_unit") or "").strip() \
                    and d not in hunits:
                fields[d + "_unit"] = du
        extra = []
        prog = canon_programme(fields.get("programme", ""))
        inv = canon_investigation(fields.get("investigation_id", "")) or ctx_inv
        if not (fields.get("programme") or "").strip() and inv in PSI_MANIFEST:
            fields["programme"] = PSI_MANIFEST[inv]["programme"]
            extra.append("programme_from_investigation_id")
        if prog and not canon_investigation(fields.get("investigation_id", "")):
            inv = PROGRAMME_TO_PSI.get(prog, inv)
            if inv:
                extra.append("investigation_id_from_programme")
        fields["investigation_id"] = inv or fields.get("investigation_id", "")
        fields["curation_file"] = rel_name + (f"#{sheet}" if sheet else "")
        fields["curation_row"] = str(rownum)
        if kind == "auto":
            if not (fields.get("source_file") or "").strip():
                fields["source_file"] = rel_name
            if not (fields.get("source_location") or "").strip():
                fields["source_location"] = (f"sheet '{sheet}' " if sheet else "") + f"row {rownum}"
            if not (fields.get("verification_status") or "").strip():
                fields["verification_status"] = "needs_review"
            extra.append("autodetected_from_raw_table")
        out.append({"fields": fields, "hunits": hunits, "extra": extra, "kind": kind,
                    "has_auto": kind == "auto", "exclude": ""})
    return out


def _same(a: str, b: str) -> bool:
    return re.sub(r"\s+", " ", (a or "").strip().lower()) == re.sub(r"\s+", " ", (b or "").strip().lower())


def _merge_pair(cur: dict, auto: dict) -> dict:
    """Field-level merge: non-blank curated values override the raw table (flagged on conflict)."""
    fields, hunits = dict(auto["fields"]), dict(auto["hunits"])
    extra = list(auto["extra"]) + ["merged_curated_over_raw_table"]
    done = set()
    for key, cval in cur["fields"].items():
        if key in ("curation_file", "curation_row") or key in done:
            continue
        group = GROUP_OF.get(key, (key,))
        lead = group[0]
        if lead != key and key in group:
            continue                       # handled when its group lead is reached
        if not (cur["fields"].get(lead) or "").strip():
            continue
        av = (auto["fields"].get(lead) or "").strip()
        if av and not _same(av, cur["fields"][lead]):
            extra.append(f"conflict_curated_overrides_raw:{lead}")
        for f in group:
            fields[f] = cur["fields"].get(f, "")
            done.add(f)
        if lead in cur["hunits"]:
            hunits[lead] = cur["hunits"][lead]
        else:
            hunits.pop(lead, None)
    note = f"raw table: {auto['fields']['curation_file']} row {auto['fields']['curation_row']}"
    fields["notes"] = "; ".join(x for x in ((fields.get("notes") or "").strip(), note) if x)
    fields["curation_file"], fields["curation_row"] = cur["fields"]["curation_file"], cur["fields"]["curation_row"]
    return {"fields": fields, "hunits": hunits, "extra": extra + cur["extra"], "kind": "merged",
            "has_auto": True, "exclude": ""}


def _merge_rows(rows: list) -> list:
    groups, out = {}, []
    for r in rows:
        prog = canon_programme(r["fields"].get("programme", ""))
        eid = re.sub(r"\s+", " ", (r["fields"].get("experiment_id") or "").strip().lower())
        if not prog or not eid:
            out.append(r)
        else:
            groups.setdefault((prog, eid), []).append(r)
    for items in groups.values():
        cur = [i for i in items if i["kind"] == "curated"]
        auto = [i for i in items if i["kind"] == "auto"]
        if len(cur) == 1 and len(auto) == 1:
            out.append(_merge_pair(cur[0], auto[0]))
        elif cur and len(auto) > 1:
            for c in cur:
                c["exclude"] = ("id_matches_multiple_raw_rows (give the curated row an "
                                "unambiguous experiment_id)")
            out += items
        else:
            out += items
    return out


def _assign_ids(records: list) -> None:
    counts = {}
    for r in records:
        t = r.text
        if t["experiment_id"]:
            k = (t["programme"], re.sub(r"\s+", " ", t["experiment_id"].lower()))
            counts[k] = counts.get(k, 0) + 1
    for r in records:
        t = r.text
        stem = Path(t["curation_file"].split("#")[0]).stem
        if not t["experiment_id"]:
            r.record_id = f"{t['programme']}:{stem}#r{t['curation_row']}"
        else:
            k = (t["programme"], re.sub(r"\s+", " ", t["experiment_id"].lower()))
            if counts[k] > 1:
                r.record_id = f"{t['programme']}:{t['experiment_id']}#{stem}:r{t['curation_row']}"
                r.flag("duplicate_experiment_id_disambiguated_by_row")
            else:
                r.record_id = f"{t['programme']}:{t['experiment_id']}"
        t["record_id"] = r.record_id


def _validate(rec):
    """Return exclusion reason or ''. Also fills source_url default."""
    t = rec.text
    prog = canon_programme(t["programme"])
    if not prog:
        return "programme_unrecognized"
    t["programme"] = prog
    inv = canon_investigation(t["investigation_id"])
    expected = PROGRAMME_TO_PSI.get(prog)
    if expected and inv and inv != expected:
        return f"programme_investigation_mismatch ({prog} expects {expected}, got {inv})"
    if expected:
        t["investigation_id"] = expected
    if not t["source_url"]:
        if expected:
            t["source_url"] = psi_url(expected)
            rec.flag("source_url_defaulted_to_investigation_page")
        else:
            rec.flag("source_url_missing")
    if not t["source_file"]:
        rec.flag("source_file_missing")
    if not t["source_location"]:
        rec.flag("source_location_missing")
    if t["record_status"] == "modified":
        rec.flag("record_modified")
    return ""


def ingest(data_dir: Path, cfg: dict) -> IngestResult:
    res = IngestResult()
    rows = []
    runs_dir, planned_dir, raw_dir = (data_dir / "runs", data_dir / "planned", data_dir / "raw")

    for folder in (runs_dir, planned_dir):
        for path in sorted(p for p in folder.rglob("*") if p.is_file()) if folder.exists() else []:
            if path.suffix.lower() not in (".csv", ".tsv", ".xlsx", ".xlsm") or path.name.lower().startswith("readme"):
                continue
            rel = path.relative_to(data_dir).as_posix()
            n = 0
            for sheet, header, trows in read_tables(path, False, res.notes):
                new = _collect_rows(sheet, header, trows, rel, "curated", _context_investigation(path), res.notes)
                rows += new
                n += len(new)
            res.inventory.append({"path": rel, "bytes": path.stat().st_size, "sha256": _sha256(path),
                                  "role": "curated_table", "detected_as": f"curated run table ({n} rows)"})

    if raw_dir.exists():
        min_cols = cfg["ingest"]["autodetect_min_columns"]
        for path in sorted(p for p in raw_dir.rglob("*") if p.is_file()):
            rel = path.relative_to(data_dir).as_posix()
            entry = {"path": rel, "bytes": path.stat().st_size, "sha256": _sha256(path),
                     "role": "raw_download", "detected_as": "not parsed"}
            res.inventory.append(entry)
            ctx_inv = _context_investigation(path)
            for sheet, header, _ in read_tables(path, True, res.notes):
                fields = {map_header(h)[0] for h in header} - {None}
                roster = "fuel_name" in fields and "experiment_id" in fields
                if "fuel_name" not in fields or not (roster or len(fields & DETECTION_FIELDS) >= min_cols):
                    continue
                if not ctx_inv and not ({"programme", "investigation_id"} & fields):
                    res.notes.append(f"{rel}: looks like a run table but no PSI-nn in its file/folder "
                                     "name and no programme column; not ingested")
                    continue
                for sh, hd, trows in [t for t in read_tables(path, False, res.notes) if t[0] == sheet]:
                    new = _collect_rows(sh, hd, trows, rel, "auto", ctx_inv, res.notes)
                    rows += new
                    entry["detected_as"] = f"auto-detected run table ({len(new)} rows)"

    records = []
    for row in _merge_rows(rows):
        f = row["fields"]
        prog = canon_programme(f.get("programme", ""))
        defaults = []
        for key, val in cfg.get("programme_defaults", {}).get(prog, {}).items():
            if not (f.get(key) or "").strip():
                f[key] = val
                defaults.append(f"default_from_config:{key}")
        extra = list(row["extra"]) + defaults
        if row["has_auto"] and not (f.get("record_status") or "").strip():
            f["record_status"] = cfg["ingest"]["autodetect_record_status"]
            extra.append("status_assumed_from_psi_repository")
        rec = build_record(f, row["hunits"], cfg)
        for fl in extra:
            rec.flag(fl)
        rec.exclude = row["exclude"]
        records.append(rec)

    _assign_ids(records)
    for rec in sorted(records, key=lambda r: (r.text["curation_file"], int(r.text["curation_row"] or 0))):
        t = rec.text
        reason = getattr(rec, "exclude", "") or _validate(rec)
        if not reason and re.match(r"(?i)^(note\b|F\d+C\d+)", t["experiment_id"] or ""):
            reason = "non_run_row (note or pre-test flow-visualization line)"
        if not reason and "autodetected_from_raw_table" in rec.flags and not t["experiment_id"]:
            reason = "missing_experiment_id (cleaning/blank line in raw table)"
        if reason:
            res.excluded.append((rec, reason))
            continue
        prog, status = t["programme"], t["record_status"]
        if status == "planned" or prog in SUPPLEMENTARY_PROGRAMMES:
            res.supplementary.append(rec)
        elif status not in EXECUTED_STATUSES:
            res.excluded.append((rec, f"record_status_not_executed:{status}"))
        else:
            res.executed.append(rec)
    res.executed.sort(key=lambda r: r.record_id)
    res.supplementary.sort(key=lambda r: r.record_id)
    return res


def split_pools(executed):
    refs = [r for r in executed if r.text["programme"] in REFERENCE_PROGRAMMES]
    tgts = [r for r in executed if r.text["programme"] in TARGET_PROGRAMMES]
    return refs, tgts
