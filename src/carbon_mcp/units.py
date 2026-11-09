"""Unit conversion for quantities and per-unit carbon factors.

Quantities sit on one chain of dimensions:

    area --(thickness)--> volume --(density)--> mass --(g)--> weight (force)

Moving along the chain needs the link's parameter (thickness_mm, density_kg_m3);
mass <-> weight uses standard gravity. Ratio units ("kgCO2e/m3", "kg/m3") convert
numerator and denominator separately, so "kgCO2e/m3 -> kgCO2e/kg" uses density.
"""
import math

G_STANDARD = 9.80665  # m/s², ISO 80000-3

# unit -> (dimension, factor to SI base: kg, N, m3, m2, kgCO2e)
UNITS = {
    # mass
    "kg": ("mass", 1.0), "g": ("mass", 1e-3), "t": ("mass", 1000.0),
    "tonne": ("mass", 1000.0), "lb": ("mass", 0.45359237),
    "short_ton": ("mass", 907.18474),
    # weight (force)
    "N": ("force", 1.0), "kN": ("force", 1000.0), "lbf": ("force", 4.4482216152605),
    "kip": ("force", 4448.2216152605),
    # volume
    "m3": ("volume", 1.0), "L": ("volume", 1e-3), "ft3": ("volume", 0.028316846592),
    "yd3": ("volume", 0.764554857984),
    # area (of a layer with a thickness)
    "m2": ("area", 1.0), "ft2": ("area", 0.09290304),
    # carbon (numerator only)
    "kgCO2e": ("carbon", 1.0), "gCO2e": ("carbon", 1e-3), "tCO2e": ("carbon", 1000.0),
}
CHAIN = ["area", "volume", "mass", "force"]
VALUE_LIMIT = 1e12


def _parse(unit):
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError("unit must be a nonempty string")
    parts = unit.replace(" ", "").split("/")
    if len(parts) > 2:
        raise ValueError(f"unit {unit!r}: at most one '/'")
    for p in parts:
        if p not in UNITS:
            raise ValueError(f"unknown unit {p!r}; valid units: {sorted(UNITS)}")
    if len(parts) == 2 and UNITS[parts[1]][0] == "carbon":
        raise ValueError(f"unit {unit!r}: carbon cannot be a denominator")
    return parts


def _convert_simple(value, src, dst, thickness_mm, density_kg_m3, used):
    """Convert value from simple unit src to simple unit dst."""
    d_src, f_src = UNITS[src]
    d_dst, f_dst = UNITS[dst]
    base = value * f_src
    if d_src != d_dst:
        if "carbon" in (d_src, d_dst):
            raise ValueError(f"cannot convert {src} to {dst}: carbon only converts to carbon")
        i, j = CHAIN.index(d_src), CHAIN.index(d_dst)
        step = 1 if j > i else -1
        for k in range(i, j, step):
            a, b = (CHAIN[k], CHAIN[k + 1]) if step == 1 else (CHAIN[k - 1], CHAIN[k])
            if (a, b) == ("area", "volume"):
                if thickness_mm is None:
                    raise ValueError(f"converting {src} to {dst} needs thickness_mm")
                m = thickness_mm / 1000
                used.add(f"thickness {thickness_mm} mm")
            elif (a, b) == ("volume", "mass"):
                if density_kg_m3 is None:
                    raise ValueError(f"converting {src} to {dst} needs density_kg_m3")
                m = density_kg_m3
                used.add(f"density {density_kg_m3} kg/m3")
            else:  # mass -> force
                m = G_STANDARD
                used.add(f"standard gravity {G_STANDARD} m/s²")
            base = base * m if step == 1 else base / m
    return base / f_dst


def convert(value, from_unit, to_unit, density_kg_m3=None, thickness_mm=None):
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value) or abs(value) > VALUE_LIMIT):
        raise ValueError(f"value={value!r} must be a finite number with |value| ≤ {VALUE_LIMIT:g}")
    if density_kg_m3 is not None and not (
            isinstance(density_kg_m3, (int, float)) and 10 <= density_kg_m3 <= 20000):
        raise ValueError(f"density_kg_m3={density_kg_m3!r} is outside the valid range 10–20000")
    if thickness_mm is not None and not (
            isinstance(thickness_mm, (int, float)) and 1 <= thickness_mm <= 2000):
        raise ValueError(f"thickness_mm={thickness_mm!r} is outside the valid range 1–2000")
    src, dst = _parse(from_unit), _parse(to_unit)
    if len(src) != len(dst):
        raise ValueError(f"cannot convert {from_unit} to {to_unit}: one is a ratio and the other is not")

    numer_dims = (UNITS[src[0]][0], UNITS[dst[0]][0])
    if len(src) == 1 and value < 0:
        raise ValueError("a physical quantity cannot be negative")
    if len(src) == 2 and value < 0 and numer_dims != ("carbon", "carbon"):
        raise ValueError("only carbon factors may be negative")

    used = set()
    try:
        out = _convert_simple(value, src[0], dst[0], thickness_mm, density_kg_m3, used)
        if len(src) == 2:
            # value per 1 src-denominator -> per 1 dst-denominator:
            # multiply by how many src-denominator units are in one dst-denominator unit.
            out *= _convert_simple(1.0, dst[1], src[1], thickness_mm, density_kg_m3, used)
    except ValueError as exc:
        raise ValueError(f"{from_unit} → {to_unit}: {exc}") from exc

    warnings = []
    if len(src) == 2 and numer_dims == ("carbon", "carbon") and out < 0:
        warnings.append("Negative carbon factor: likely nets biogenic storage (GWP-total). "
                        "The calculation tools reject it; use GWP-fossil instead.")
    if "standard gravity" in " ".join(used):
        warnings.append("Weight is a force; mass ↔ weight uses standard gravity, not density.")
    return {"inputs": {"value": value, "from_unit": from_unit, "to_unit": to_unit,
                       "density_kg_m3": density_kg_m3, "thickness_mm": thickness_mm},
            "result": out, "unit": to_unit,
            "parameters_used": sorted(used),
            "warnings": warnings}
