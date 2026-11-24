"""Record schema, controlled vocabularies and the fixed PSI source manifest."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- Source manifest (handoff section 2). BASS = PSI-26, BASS-II = PSI-25. ---
PSI_BASE = "https://psi.nasa.gov/physci/repo/data/investigations/"
PSI_MANIFEST = {
    "PSI-26": {"programme": "BASS", "role": "reference"},
    "PSI-25": {"programme": "BASS-II", "role": "reference"},
    "PSI-98": {"programme": "SAFFIRE-I", "role": "target"},
    "PSI-99": {"programme": "SAFFIRE-II", "role": "target"},
    "PSI-100": {"programme": "SAFFIRE-III", "role": "target"},
}
PROGRAMME_TO_PSI = {v["programme"]: k for k, v in PSI_MANIFEST.items()}
REFERENCE_PROGRAMMES = ("BASS", "BASS-II")
TARGET_PROGRAMMES = ("SAFFIRE-I", "SAFFIRE-II", "SAFFIRE-III")
SUPPLEMENTARY_PROGRAMMES = ("SAFFIRE-IV", "SAFFIRE-V", "SAFFIRE-VI")
EXECUTED_STATUSES = ("executed", "modified")


def psi_url(investigation_id: str) -> str:
    return PSI_BASE + investigation_id


_PROGRAMME_KEYS = {
    "BASS": "BASS", "BASSI": "BASS", "BASS1": "BASS",
    "BASSII": "BASS-II", "BASS2": "BASS-II",
    "SAFFIREI": "SAFFIRE-I", "SAFFIRE1": "SAFFIRE-I",
    "SAFFIREII": "SAFFIRE-II", "SAFFIRE2": "SAFFIRE-II",
    "SAFFIREIII": "SAFFIRE-III", "SAFFIRE3": "SAFFIRE-III",
    "SAFFIREIV": "SAFFIRE-IV", "SAFFIRE4": "SAFFIRE-IV",
    "SAFFIREV": "SAFFIRE-V", "SAFFIRE5": "SAFFIRE-V",
    "SAFFIREVI": "SAFFIRE-VI", "SAFFIRE6": "SAFFIRE-VI",
}


def canon_programme(text: str) -> str:
    key = re.sub(r"[^A-Z0-9]", "", (text or "").upper())
    return _PROGRAMME_KEYS.get(key, "")


def canon_investigation(text: str) -> str:
    m = re.search(r"PSI[-_ ]?(\d+)", (text or "").upper())
    return f"PSI-{int(m.group(1))}" if m else ""


def _vocab(text: str, table: dict, default: str) -> tuple[str, bool]:
    """Return (canonical value, recognized?). Blank -> (default, True)."""
    key = re.sub(r"[^a-z0-9]", "", (text or "").lower())
    if key == "":
        return default, True
    if key in table:
        return table[key], True
    return default, False


_FLOW = {
    "concurrent": "concurrent", "coflow": "concurrent", "forward": "concurrent",
    "cocurrent": "concurrent", "downstream": "concurrent",
    "opposed": "opposed", "counterflow": "opposed", "counter": "opposed",
    "opposedflow": "opposed", "concurrentflow": "concurrent",
    "other": "other", "unknown": "unknown",
}
_GRAVITY = {
    "microgravity": "microgravity", "ug": "microgravity", "mug": "microgravity",
    "lowg": "microgravity", "lowgravity": "microgravity", "0g": "microgravity",
    "ground": "ground", "1g": "ground", "normalgravity": "ground", "earth": "ground",
    "other": "other", "unknown": "unknown",
}
_AIRFLOW_MEAS = {
    "inlet": "inlet", "inletvelocity": "inlet", "local": "local",
    "flamezone": "local", "ductaverage": "duct_average", "average": "duct_average",
    "mean": "duct_average", "other": "other", "unknown": "unknown",
}
_STATUS = {
    "planned": "planned", "executed": "executed", "modified": "modified",
    "cancelled": "cancelled", "canceled": "cancelled", "unknown": "unknown",
}
_EVIDENCE = {
    "metadataonly": "metadata_only", "measureddataavailable": "measured_data_available",
    "publishedresultavailable": "published_result_available",
}
_VERIF = {
    "verified": "verified", "needsreview": "needs_review", "conflicting": "conflicting",
    "digitized": "digitized", "unknown": "unknown",
}
_PBASIS = {"absolute": "absolute", "abs": "absolute", "gauge": "gauge", "gage": "gauge",
           "unknown": "unknown"}
_DIMSTATUS = {"verified": "verified", "needsreview": "needs_review", "unknown": "needs_review"}
_DENOM = {"ductheight": "duct_height", "ductwidth": "duct_width"}

CATEGORICAL = {
    "flow_direction": (_FLOW, "unknown"),
    "gravity_environment": (_GRAVITY, "unknown"),
    "airflow_measurement_type": (_AIRFLOW_MEAS, "unknown"),
    "record_status": (_STATUS, "unknown"),
    "evidence_status": (_EVIDENCE, ""),
    "verification_status": (_VERIF, "needs_review"),
    "pressure_basis": (_PBASIS, "unknown"),
    "dimension_definition_status": (_DIMSTATUS, "needs_review"),
    "ratio_denominator": (_DENOM, ""),
}


def canon_categorical(field_name: str, text: str) -> tuple[str, bool]:
    table, default = CATEGORICAL[field_name]
    return _vocab(text, table, default)


# Free-text / identifier fields carried through unchanged.
TEXT_FIELDS = [
    "record_id", "programme", "investigation_id", "experiment_id", "record_status",
    "evidence_status", "fuel_name", "fuel_composition", "fuel_category",
    "flow_direction", "gravity_environment", "airflow_measurement_type",
    "pressure_basis", "ratio_denominator", "dimension_definition_status",
    "sample_position", "source_url", "source_doi", "source_file", "source_location",
    "retrieved_at", "verification_status", "notes", "curation_file", "curation_row",
]

# Numeric quantities supplied by the curator: name -> (unit kind)
INPUT_QUANTITIES = {
    "airflow": "velocity", "oxygen": "oxygen", "pressure": "pressure",
    "temperature": "temperature",
    "sample_width": "length", "sample_length": "length", "sample_thickness": "length",
    "duct_height": "length", "duct_width": "length", "duct_length": "length",
}
DERIVED_QUANTITIES = ["oxygen_mole_fraction", "oxygen_partial_pressure",
                      "sample_duct_width_ratio"]
ALL_QUANTITIES = list(INPUT_QUANTITIES) + DERIVED_QUANTITIES

MISSING_REASONS = ("not_reported", "not_applicable", "not_extracted",
                   "ambiguous_definition", "conflicting_sources")


@dataclass
class Quantity:
    name: str
    raw_text: str = ""
    raw_value: float | None = None
    raw_unit: str = ""
    si_value: float | None = None
    si_unit: str = ""
    method: str = ""
    missing_reason: str | None = None

    @property
    def known(self) -> bool:
        return self.si_value is not None


@dataclass
class Record:
    record_id: str
    text: dict = field(default_factory=dict)      # normalized text/categorical values
    raw_text: dict = field(default_factory=dict)  # original categorical text (audit)
    q: dict = field(default_factory=dict)         # name -> Quantity
    flags: list = field(default_factory=list)

    def get(self, key: str) -> str:
        return self.text.get(key, "")

    def flag(self, text: str) -> None:
        if text not in self.flags:
            self.flags.append(text)
