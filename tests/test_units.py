import math

import pytest

from carbon_mcp.units import G_STANDARD, convert


def r(*a, **k):
    return convert(*a, **k)["result"]


def test_simple_mass_and_volume():
    assert math.isclose(r(1, "t", "kg"), 1000)
    assert math.isclose(r(1, "lb", "kg"), 0.45359237)
    assert math.isclose(r(1, "yd3", "m3"), 0.764554857984)


def test_mass_volume_via_density():
    assert math.isclose(r(20, "m3", "kg", density_kg_m3=470), 9400)
    assert math.isclose(r(9400, "kg", "m3", density_kg_m3=470), 20)


def test_mass_weight_via_gravity():
    assert math.isclose(r(1000, "kg", "kN"), G_STANDARD)
    assert math.isclose(r(G_STANDARD, "kN", "kg"), 1000)
    # area -> weight goes the whole chain
    assert math.isclose(r(1, "m2", "kN", thickness_mm=200, density_kg_m3=2400),
                        480 * G_STANDARD / 1000)


def test_carbon_factor_per_m3_to_per_kg():
    # ÖKOBAUDAT CLT +A2: GWP-fossil A1–A3 119.14 kgCO2e/m3 at 489.41 kg/m3
    assert math.isclose(r(119.13949426364547, "kgCO2e/m3", "kgCO2e/kg", density_kg_m3=489.41),
                        119.13949426364547 / 489.41)
    assert math.isclose(r(0.149, "kgCO2e/kg", "kgCO2e/t"), 149)
    assert math.isclose(r(1, "kgCO2e/kg", "kgCO2e/m2", thickness_mm=200, density_kg_m3=2400), 480)


def test_density_units_without_density_param():
    assert math.isclose(r(1, "g/L", "kg/m3"), 1)
    assert math.isclose(r(470, "kg/m3", "lb/ft3"), 470 * 0.028316846592 / 0.45359237)


def test_negative_carbon_factor_warns():
    out = convert(-669.6, "kgCO2e/m3", "kgCO2e/kg", density_kg_m3=489.41)
    assert out["result"] < 0 and out["warnings"]


@pytest.mark.parametrize("args,kwargs,msg", [
    ((119.1, "kgCO2e/m3", "kgCO2e/kg"), {}, "needs density_kg_m3"),
    ((1, "m2", "kg"), {"density_kg_m3": 2400}, "needs thickness_mm"),
    ((1, "furlong", "kg"), {}, "unknown unit"),
    ((1, "kg", "kgCO2e"), {}, "carbon only converts to carbon"),
    ((1, "kg", "kg/m3"), {}, "ratio"),
    ((-5, "kg", "lb"), {}, "cannot be negative"),
    ((1, "m3", "kg"), {"density_kg_m3": 5}, "outside the valid range"),
    ((float("nan"), "kg", "lb"), {}, "finite"),
])
def test_invalid(args, kwargs, msg):
    with pytest.raises(ValueError, match=msg):
        convert(*args, **kwargs)
