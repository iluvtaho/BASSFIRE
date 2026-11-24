"""Default configuration (every number is an UNVALIDATED placeholder) + TOML override."""
from __future__ import annotations

import copy
import hashlib
import json
import tomllib
from pathlib import Path

DEFAULTS = {
    "ingest": {
        # Percent oxygen with no stated basis is held as ambiguous unless this is true.
        "assume_percent_oxygen_is_mole_fraction": False,
        # Rows auto-detected in data/raw get this status (flagged on every record).
        "autodetect_record_status": "executed",
        "autodetect_min_columns": 3,
    },
    "eligibility": {
        "exploratory_tier_enabled": True,
        "unrelated_fuel_tier": "ineligible",   # or "exploratory"
        "direct_required_known": ["flow_direction", "gravity_environment", "fuel_name",
                                  "airflow_measurement_type"],
    },
    "fuel": {
        "exact_score": 1.0, "related_score": 0.5, "different_score": 0.0,
        # Groups of fuel names to treat as the same material, e.g. [["SIBAL", "..."]].
        "alias_groups": [],
    },
    # mode: relative -> |ref-tgt|/|tgt| ; absolute -> |ref-tgt| (SI units / mole fraction)
    "tolerances": {
        "airflow": {"mode": "relative", "tol": 0.5},
        "oxygen_mole_fraction": {"mode": "absolute", "tol": 0.05},
        "oxygen_partial_pressure": {"mode": "relative", "tol": 0.25},
        "pressure": {"mode": "relative", "tol": 0.25},
        "temperature": {"mode": "absolute", "tol": 30.0},
        "sample_thickness": {"mode": "relative", "tol": 0.5},
        "sample_width": {"mode": "relative", "tol": 0.5},
        "sample_length": {"mode": "relative", "tol": 0.5},
        "duct_height": {"mode": "relative", "tol": 0.5},
        "duct_width": {"mode": "relative", "tol": 0.5},
        "duct_length": {"mode": "relative", "tol": 0.5},
        "sample_duct_width_ratio": {"mode": "relative", "tol": 0.5},
    },
    "labels": {"close_min_score": 0.8, "moderate_min_score": 0.4},
    "ranking": {
        # Provisional screening heuristic. NOT validated against reviewed pairs yet.
        "aggregate_enabled": True,
        "weights": {"material": 1.0, "environment": 1.0, "geometry": 1.0,
                    "flow_configuration": 1.0},
        "include_tiers": ["direct", "exploratory"],
        "min_data_completeness": 0.4,
        "min_provisional_score": 0.5,
        "top_n": 3,
    },
    "completeness_parameters": [
        "fuel_name", "flow_direction", "gravity_environment", "airflow",
        "airflow_measurement_type", "oxygen_mole_fraction", "pressure", "temperature",
        "sample_thickness", "sample_width", "sample_length", "duct_height", "duct_width",
        "sample_duct_width_ratio",
    ],
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path | None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    if path and Path(path).exists():
        with open(path, "rb") as fh:
            cfg = _merge(cfg, tomllib.load(fh))
    return cfg


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]
