"""Homework 4 calculation functions, unchanged from the notebook.

Each function validates its inputs against a stated range and returns its
inputs, outputs, units, and life-cycle scope. Invalid inputs raise ValueError.
"""
import json
import math


def _check(name, value, low, high):
    # Reject non-numbers, non-finite values, and values outside the documented range.
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value) or not low <= value <= high):
        raise ValueError(f"{name}={value!r} is outside the valid range {low}–{high}")


def _check_label(label):
    if not isinstance(label, str) or not label.strip():
        raise ValueError("label must be a nonempty string")


def layer_carbon(label, thickness_mm, area_m2, density_kg_m3, gwp_kgco2e_per_kg):
    '''A1–A3 carbon of one uniform material layer.'''
    _check_label(label)
    _check("thickness_mm", thickness_mm, 1, 2000)
    _check("area_m2", area_m2, 0.01, 1e6)
    _check("density_kg_m3", density_kg_m3, 10, 20000)
    _check("gwp_kgco2e_per_kg", gwp_kgco2e_per_kg, 0, 50)
    volume_m3 = thickness_mm / 1000 * area_m2
    mass_kg = volume_m3 * density_kg_m3
    a1a3 = mass_kg * gwp_kgco2e_per_kg
    return {"label": label,
            "inputs": {"thickness_mm": thickness_mm, "area_m2": area_m2,
                       "density_kg_m3": density_kg_m3, "gwp_kgco2e_per_kg": gwp_kgco2e_per_kg},
            "volume_m3": volume_m3, "mass_kg": mass_kg,
            "a1a3_kgco2e": a1a3, "a1a3_kgco2e_per_m2": a1a3 / area_m2,
            "scope": "A1–A3 cradle-to-gate; excludes A4, A5, use, end of life, biogenic storage"}


def assembly_carbon(label, area_m2, layers):
    '''A1–A3 carbon of a multi-layer assembly over one area.'''
    _check_label(label)
    _check("area_m2", area_m2, 0.01, 1e6)
    if isinstance(layers, str):          # tolerate a JSON string from the model
        layers = json.loads(layers)
    if not isinstance(layers, list) or not 1 <= len(layers) <= 12:
        raise ValueError("layers must be a list of 1–12 layer objects")
    rows = []
    for i, layer in enumerate(layers):
        if not isinstance(layer, dict):
            raise ValueError(f"layer {i} must be an object")
        name = str(layer.get("name") or f"layer {i + 1}")
        gwp = layer.get("gwp_kgco2e_per_kg")
        _check(f"{name}.gwp_kgco2e_per_kg", gwp, 0, 50)
        has_thickness = "thickness_mm" in layer or "density_kg_m3" in layer
        has_areal = "mass_kg_per_m2" in layer
        if has_thickness == has_areal:
            raise ValueError(f"{name}: give thickness_mm + density_kg_m3, or mass_kg_per_m2, not both")
        if has_areal:
            _check(f"{name}.mass_kg_per_m2", layer["mass_kg_per_m2"], 0.01, 5000)
            mass_per_m2 = layer["mass_kg_per_m2"]
        else:
            _check(f"{name}.thickness_mm", layer.get("thickness_mm"), 1, 2000)
            _check(f"{name}.density_kg_m3", layer.get("density_kg_m3"), 10, 20000)
            mass_per_m2 = layer["thickness_mm"] / 1000 * layer["density_kg_m3"]
        mass_kg = mass_per_m2 * area_m2
        rows.append({"name": name, "mass_kg": mass_kg, "a1a3_kgco2e": mass_kg * gwp})
    total = sum(r["a1a3_kgco2e"] for r in rows)
    for r in rows:
        r["share_pct"] = 100 * r["a1a3_kgco2e"] / total if total else 0.0
    return {"label": label, "area_m2": area_m2, "layers": rows,
            "total_mass_kg": sum(r["mass_kg"] for r in rows),
            "a1a3_kgco2e": total, "a1a3_kgco2e_per_m2": total / area_m2,
            "scope": "A1–A3 cradle-to-gate; layers summed linearly; no A5 waste factor"}


def transport_carbon(label, mass_kg, distance_km, factor_kgco2e_per_tkm):
    '''A4 transport emissions for one delivery leg.'''
    _check_label(label)
    _check("mass_kg", mass_kg, 0.1, 1e8)
    _check("distance_km", distance_km, 0, 20000)
    _check("factor_kgco2e_per_tkm", factor_kgco2e_per_tkm, 0.001, 2)
    tonne_km = mass_kg / 1000 * distance_km
    return {"label": label,
            "inputs": {"mass_kg": mass_kg, "distance_km": distance_km,
                       "factor_kgco2e_per_tkm": factor_kgco2e_per_tkm},
            "tonne_km": tonne_km, "a4_kgco2e": tonne_km * factor_kgco2e_per_tkm,
            "scope": "A4 single leg; return trip only if included in the freight factor"}


def biogenic_carbon(label, volume_m3, density_kg_m3, moisture_content_pct):
    '''CO2 stored in wood per EN 16449 (carbon fraction 0.5 of oven-dry mass).'''
    _check_label(label)
    _check("volume_m3", volume_m3, 0.001, 1e5)
    _check("density_kg_m3", density_kg_m3, 250, 1200)
    _check("moisture_content_pct", moisture_content_pct, 0, 30)
    dry_mass_kg = density_kg_m3 * volume_m3 / (1 + moisture_content_pct / 100)
    stored = 44 / 12 * 0.5 * dry_mass_kg
    return {"label": label,
            "inputs": {"volume_m3": volume_m3, "density_kg_m3": density_kg_m3,
                       "moisture_content_pct": moisture_content_pct},
            "dry_mass_kg": dry_mass_kg, "stored_co2_kg": stored,
            "scope": ("EN 16449 biogenic carbon; temporary storage, released at end of life; "
                      "report separately from A1–A3, do not subtract")}
