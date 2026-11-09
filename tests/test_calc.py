"""Homework 4 hand checks, carried over unchanged."""
import math

import pytest

from carbon_mcp.calc import assembly_carbon, biogenic_carbon, layer_carbon, transport_carbon

RC = [{"name": "concrete 200 mm", "thickness_mm": 200.0, "density_kg_m3": 2400.0,
       "gwp_kgco2e_per_kg": 0.149},
      {"name": "rebar", "mass_kg_per_m2": 20.0, "gwp_kgco2e_per_kg": 1.99}]
CLT = [{"name": "CLT 200 mm", "thickness_mm": 200.0, "density_kg_m3": 470.0,
        "gwp_kgco2e_per_kg": 0.437},
       {"name": "concrete topping 50 mm", "thickness_mm": 50.0, "density_kg_m3": 2400.0,
        "gwp_kgco2e_per_kg": 0.149}]


def test_assemblies_match_hand_calc():
    assert math.isclose(assembly_carbon("RC", 1.0, RC)["a1a3_kgco2e_per_m2"], 111.32)
    assert math.isclose(assembly_carbon("CLT", 1.0, CLT)["a1a3_kgco2e_per_m2"], 58.958)


def test_layer_transport_biogenic():
    assert math.isclose(layer_carbon("c", 200, 1.0, 2400, 0.149)["a1a3_kgco2e"], 71.52)
    assert math.isclose(transport_carbon("t", 9400, 1200, 0.07547)["a4_kgco2e"],
                        9.4 * 1200 * 0.07547)
    bio = biogenic_carbon("b", 1.0, 470, 12)
    assert math.isclose(bio["stored_co2_kg"], 44 / 12 * 0.5 * 470 / 1.12)
    assert abs(bio["stored_co2_kg"] - 754) / 754 < 0.03


@pytest.mark.parametrize("bad", [
    lambda: layer_carbon("x", 200, 1.0, 2400, -0.896),
    lambda: biogenic_carbon("x", 1.0, 470, 45),
    lambda: transport_carbon("x", 1000, 30000, 0.075),
    lambda: assembly_carbon("x", 1.0, [{"name": "a", "thickness_mm": 10, "density_kg_m3": 100,
                                        "mass_kg_per_m2": 5, "gwp_kgco2e_per_kg": 1}]),
])
def test_invalid_rejected(bad):
    with pytest.raises(ValueError):
        bad()
