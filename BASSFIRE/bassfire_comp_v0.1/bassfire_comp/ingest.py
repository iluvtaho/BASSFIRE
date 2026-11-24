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
    "fuel_name": "fuelname fuel material materialname specimen samplematerial",
    "fuel_composition": "fuelcomposition composition",
    "fuel_category": "fuelcategory materialfamily materialcategory",
    "flow_direction": "flowdirection flowmode flowconfiguration flamespreaddirection spreaddirection",
    "gravity_environment": "gravityenvironment gravity",
    "airflow_value": "airflowvalue airflow flowspeed flowvelocity airspeed velocity windspeed airflowspeed",
    "airflow_unit": "airflowunit flowspeedunit velocityunit",
    "airflow_measurement_type": "airflowmeasurementtype flowmeasurementtype velocitymeasurement",
    "oxygen_value": "oxygenvalue oxygen o2 o2concentration oxygenconcentration o2percent oxygenpercent o2fraction ambiento2",
    "oxygen_unit_or_basis": "oxygenunitorbasis oxygenunit oxygenbasis o2unit o2basis",
    "pressure_value": "pressurevalue pressure totalpressure ambientpressure testpressure",
    "pressure_unit": "pressureunit",
    "pressure_basis": "pressurebasis",
    "temperature_value": "temperaturevalue temperature ambienttemperature initialtemperature temp",
    "temperature_unit": "temperatureunit tempunit",
    "sample_width": "samplewidth specimenwidth fuelwidth",
    "sample_length": "samplelength specimenlength fuellength",
    "sample_thickness": "samplethickness thickness fuelthickness specimenthickness",
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
}
ALIAS_MAP = {}
for _field, _names in _ALIAS_SOURCE.items():
    ALIAS_MAP[re.sub(r"[^a-z0-9]", "", _field)] = _field
    for _n in _names.split():
        ALIAS_MAP[_n] = _field

DETECTION_FIELDS = {"fuel_name", "flow_direction", "airflow_value", "oxygen_value",
                    "pressure_value", "temperature_value", "sample_width", "sample_length",
                    "sample_thickness", "duct_height", "gravity_environment"}
_UNIT_RE = re.compile(r"^(.*?)\s*[\(\[]([^)\]]*)[\)\]]\s*$")


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (h or "").lower())


def map_header(header: str):
    """Return (field|None, unit_from_header)."""
    if _norm(header) in ALIAS_MAP:
        return ALIAS_MAP[_norm(header)], ""
    m = _UNIT_RE.match(header or "")
    if m and _norm(m.group(1)) in ALIAS_MAP:
        return ALIAS_MAP[_norm(m.group(1))], m.group(2).strip()
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
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(fh, dialect)
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


def _rows_to_records(path, sheet, header, rows, cfg, rel_name, autodetected, ctx_inv, notes):
    mapped = [map_header(h) for h in header]
    unmapped = [h for h, (f, _) in zip(header, mapped) if f is None and h]
    if unmapped:
        notes.append(f"{rel_name}{(' [' + sheet + ']') if sheet else ''}: "
                     f"{len(unmapped)} column(s) not mapped and ignored")
    records = []
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
        fields["curation_file"] = rel_name + (f"#{sheet}" if sheet else "")
        fields["curation_row"] = str(rownum)
        extra_flags = []
        prog = canon_programme(fields.get("programme", ""))
        inv = canon_investigation(fields.get("investigation_id", "")) or ctx_inv
        if not (fields.get("programme") or "").strip() and inv in PSI_MANIFEST:
            fields["programme"] = PSI_MANIFEST[inv]["programme"]
            extra_flags.append("programme_from_investigation_id")
        if prog and not canon_investigation(fields.get("investigation_id", "")):
            inv = PROGRAMME_TO_PSI.get(prog, inv)
            if inv:
                extra_flags.append("investigation_id_from_programme")
        fields["investigation_id"] = inv or fields.get("investigation_id", "")
        if autodetected:
            fields.setdefault("source_file", rel_name)
            if not (fields.get("source_location") or "").strip():
                fields["source_location"] = (f"sheet '{sheet}' " if sheet else "") + f"row {rownum}"
            if not (fields.get("record_status") or "").strip():
                fields["record_status"] = cfg["ingest"]["autodetect_record_status"]
                extra_flags.append("status_assumed_from_psi_repository")
            if not (fields.get("verification_status") or "").strip():
                fields["verification_status"] = "needs_review"
            extra_flags.append("autodetected_from_raw_table")
        rec = build_record(fields, hunits, cfg)
        for fl in extra_flags:
            rec.flag(fl)
        records.append(rec)
    return records


def _assign_id(rec):
    t = rec.text
    stem = Path(t["curation_file"].split("#")[0]).stem
    rec.record_id = (f"{t['programme']}:{t['experiment_id']}" if t["experiment_id"]
                     else f"{t['programme']}:{stem}#r{t['curation_row']}")
    rec.text["record_id"] = rec.record_id


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
    raw_records = []
    runs_dir, planned_dir, raw_dir = (data_dir / "runs", data_dir / "planned", data_dir / "raw")

    for folder in (runs_dir, planned_dir):
        for path in sorted(p for p in folder.rglob("*") if p.is_file()) if folder.exists() else []:
            if path.suffix.lower() not in (".csv", ".tsv", ".xlsx", ".xlsm"):
                continue
            rel = path.relative_to(data_dir).as_posix()
            res.inventory.append({"path": rel, "bytes": path.stat().st_size,
                                  "sha256": _sha256(path), "role": "curated_table",
                                  "detected_as": "run table (curated)"})
            for sheet, header, rows in read_tables(path, False, res.notes):
                raw_records += _rows_to_records(path, sheet, header, rows, cfg, rel, False,
                                                _context_investigation(path), res.notes)

    if raw_dir.exists():
        min_cols = cfg["ingest"]["autodetect_min_columns"]
        for path in sorted(p for p in raw_dir.rglob("*") if p.is_file()):
            rel = path.relative_to(data_dir).as_posix()
            entry = {"path": rel, "bytes": path.stat().st_size, "sha256": _sha256(path),
                     "role": "raw_download", "detected_as": "not parsed"}
            res.inventory.append(entry)
            tables = read_tables(path, True, res.notes)
            ctx_inv = _context_investigation(path)
            for sheet, header, _ in tables:
                fields = {map_header(h)[0] for h in header} - {None}
                if "fuel_name" not in fields or len(fields & DETECTION_FIELDS) < min_cols:
                    continue
                if not ctx_inv and not ({"programme", "investigation_id"} & fields):
                    res.notes.append(f"{rel}: looks like a run table but no PSI-nn folder in its "
                                     "path and no programme column; not ingested")
                    continue
                full = [t for t in read_tables(path, False, res.notes) if t[0] == sheet]
                for sh, hd, rows in full:
                    new = _rows_to_records(path, sh, hd, rows, cfg, rel, True, ctx_inv, res.notes)
                    raw_records += new
                    entry["detected_as"] = f"auto-detected run table ({len(new)} rows)"

    seen = set()
    for rec in sorted(raw_records, key=lambda r: (r.text["curation_file"],
                                                  int(r.text["curation_row"] or 0))):
        reason = _validate(rec)
        if not reason:
            _assign_id(rec)
        else:
            rec.record_id = rec.text["record_id"] = f"EXCLUDED:{rec.text['curation_file']}#r{rec.text['curation_row']}"
            res.excluded.append((rec, reason))
            continue
        prog, status = rec.text["programme"], rec.text["record_status"]
        if status == "planned" or prog in SUPPLEMENTARY_PROGRAMMES:
            res.supplementary.append(rec)
            continue
        if status not in EXECUTED_STATUSES:
            res.excluded.append((rec, f"record_status_not_executed:{status}"))
            continue
        if rec.record_id in seen:
            res.excluded.append((rec, "duplicate_experiment_id (resolve before pairing)"))
            continue
        seen.add(rec.record_id)
        res.executed.append(rec)
    res.executed.sort(key=lambda r: r.record_id)
    res.supplementary.sort(key=lambda r: r.record_id)
    return res


def split_pools(executed):
    refs = [r for r in executed if r.text["programme"] in REFERENCE_PROGRAMMES]
    tgts = [r for r in executed if r.text["programme"] in TARGET_PROGRAMMES]
    return refs, tgts
