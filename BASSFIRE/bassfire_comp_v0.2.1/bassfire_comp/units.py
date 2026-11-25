"""Unit conversion to SI. Unknown units raise UnitError (never guessed)."""
from __future__ import annotations

import re


class UnitError(ValueError):
    pass


def unit_key(unit: str) -> str:
    u = (unit or "").strip().lower()
    for a, b in (("\u00b5", "u"), ("\u03bc", "u"), ("\u00b0", ""), (" ", ""),
                 ("/sec", "/s"), ("seconds", "s"), ("second", "s"), ("^-1", "")):
        u = u.replace(a, b)
    return u


_LENGTH = {"m": 1.0, "cm": 0.01, "mm": 1e-3, "um": 1e-6, "micron": 1e-6, "microns": 1e-6, "in": 0.0254, "inch": 0.0254,
           "inches": 0.0254, "ft": 0.3048, "feet": 0.3048}
_VELOCITY = {"m/s": 1.0, "cm/s": 0.01, "mm/s": 1e-3, "in/s": 0.0254, "ft/s": 0.3048,
             "ft/min": 0.3048 / 60.0, "m/min": 1.0 / 60.0, "cm/min": 0.01 / 60.0}
_PRESSURE = {"pa": 1.0, "kpa": 1e3, "mpa": 1e6, "hpa": 100.0, "mbar": 100.0, "bar": 1e5,
             "atm": 101325.0, "psi": 6894.757293168, "psia": 6894.757293168,
             "psig": 6894.757293168, "torr": 101325.0 / 760.0, "mmhg": 133.322387415}


def to_length_m(value: float, unit: str):
    k = unit_key(unit)
    if k not in _LENGTH:
        raise UnitError(f"unknown length unit '{unit}'")
    return value * _LENGTH[k], "m", f"{unit.strip()} -> m (x{_LENGTH[k]:g})"


def to_velocity_ms(value: float, unit: str):
    k = unit_key(unit)
    if k not in _VELOCITY:
        raise UnitError(f"unknown velocity unit '{unit}' (volumetric flow is not converted)")
    return value * _VELOCITY[k], "m/s", f"{unit.strip()} -> m/s (x{_VELOCITY[k]:g})"


def to_pressure_pa(value: float, unit: str):
    """Returns (si, 'Pa', method, basis_hint) ; basis_hint in {'absolute','gauge',None}."""
    k = unit_key(unit)
    if k not in _PRESSURE:
        raise UnitError(f"unknown pressure unit '{unit}'")
    hint = "absolute" if k == "psia" else "gauge" if k == "psig" else None
    return value * _PRESSURE[k], "Pa", f"{unit.strip()} -> Pa (x{_PRESSURE[k]:g})", hint


def to_temperature_k(value: float, unit: str):
    k = unit_key(unit)
    if k in ("k", "kelvin"):
        return value, "K", "already K"
    if k in ("c", "degc", "celsius"):
        return value + 273.15, "K", "C -> K (+273.15)"
    if k in ("f", "degf", "fahrenheit"):
        return (value - 32.0) * 5.0 / 9.0 + 273.15, "K", "F -> K"
    raise UnitError(f"unknown temperature unit '{unit}'")


# Oxygen "basis" strings -> (kind, factor to mole fraction, note)
_O2_MOLE = {
    "molefraction": (1.0, ""), "molarfraction": (1.0, ""),
    "molepercent": (0.01, ""), "mol%": (0.01, ""), "mole%": (0.01, ""), "%mol": (0.01, ""),
    "%mole": (0.01, ""),
    "volumefraction": (1.0, "volume fraction treated as mole fraction (ideal gas)"),
    "volumepercent": (0.01, "volume percent treated as mole percent (ideal gas)"),
    "vol%": (0.01, "volume percent treated as mole percent (ideal gas)"),
    "%vol": (0.01, "volume percent treated as mole percent (ideal gas)"),
    "%v/v": (0.01, "volume percent treated as mole percent (ideal gas)"),
    "%o2byvolume": (0.01, "volume percent treated as mole percent (ideal gas)"),
}
_O2_UNSPECIFIED = {"%": 0.01, "percent": 0.01, "fraction": 1.0, "vol": 0.01}


def classify_oxygen_basis(unit: str):
    """Return ('mole', factor, note) | ('partial', pressure_unit, '') |
    ('unspecified', factor, '') | ('unknown', None, '')."""
    k = re.sub(r"[_\-]", "", unit_key(unit))
    if k in _O2_MOLE:
        f, note = _O2_MOLE[k]
        return "mole", f, note
    if k in _O2_UNSPECIFIED:
        return "unspecified", _O2_UNSPECIFIED[k], ""
    pk = re.sub(r"^(partialpressure|po2|pp)", "", k)
    pk = re.sub(r"(partialpressure|po2)$", "", pk)
    if pk in _PRESSURE:
        return "partial", pk, ""
    return "unknown", None, ""
