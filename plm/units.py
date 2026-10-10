"""Unit dictionary: every known unit -> (dimension, factor to the canonical unit of that dimension)."""
from __future__ import annotations

_BASE = {  # dimension -> canonical unit (must agree with quantity_def.canonical_unit)
    "length": "mm", "pressure": "MPa", "dimensionless": "1", "mass": "g", "density": "g/cm^3",
    "force": "N", "area": "mm^2", "volume": "mm^3", "energy": "mJ", "energy_per_area": "kJ/m^2", "count": "1",
}
UNITS = {  # unit: (dimension, multiply by this to reach the canonical unit)
    "mm": ("length", 1.0), "m": ("length", 1e3),
    "Pa": ("pressure", 1e-6), "kPa": ("pressure", 1e-3), "MPa": ("pressure", 1.0), "GPa": ("pressure", 1e3),
    "1": ("dimensionless", 1.0),
    "g": ("mass", 1.0), "kg": ("mass", 1e3), "tonne": ("mass", 1e6),
    "g/cm^3": ("density", 1.0), "kg/m^3": ("density", 1e-3), "tonne/mm^3": ("density", 1e9),
    "N": ("force", 1.0), "mm^2": ("area", 1.0), "mm^3": ("volume", 1.0),
    "mJ": ("energy", 1.0), "J": ("energy", 1e3), "kJ/m^2": ("energy_per_area", 1.0),
}
_ALIASES = {"dimensionless": "1", "-": "1", "": "1", "g/cm³": "g/cm^3", "kJ/m²": "kJ/m^2", "mm²": "mm^2", "mm³": "mm^3",
            "tonne mm^-3": "tonne/mm^3", "tonne s^-2 mm^-1": "MPa"}


def normalise(unit: str) -> str:
    """Map the spelling found in a source file to the dictionary spelling (unknown units are returned unchanged)."""
    unit = (unit or "").strip()
    return _ALIASES.get(unit, unit)


def dimension(unit: str):
    entry = UNITS.get(normalise(unit))
    return entry[0] if entry else None


def canonical_unit(dim: str) -> str:
    return _BASE[dim]


def convert(value: float, unit: str, to_unit: str) -> float:
    """Convert between two units of the same dimension; raises ValueError otherwise (never guesses)."""
    src, dst = UNITS.get(normalise(unit)), UNITS.get(normalise(to_unit))
    if src is None or dst is None:
        raise ValueError(f"unknown unit: {unit!r} -> {to_unit!r}")
    if src[0] != dst[0]:
        raise ValueError(f"cannot convert {src[0]} ({unit!r}) to {dst[0]} ({to_unit!r})")
    return float(f"{value * src[1] / dst[1]:.12g}")  # drop binary-float noise such as 41.041000000000004
