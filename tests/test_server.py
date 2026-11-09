"""End-to-end through an in-process MCP client."""
import json
import math

import pytest

from mcp import Client

from carbon_mcp import oekobaudat as ok
from carbon_mcp.server import mcp
from test_oekobaudat import fake_api  # noqa: F401  (fixture)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def call(name, args):
    async with Client(mcp) as client:
        return await client.call_tool(name, args)


async def test_lists_seven_tools():
    async with Client(mcp) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert names == {"compute_layer_carbon", "compute_assembly_carbon", "compute_transport_carbon",
                     "compute_biogenic_carbon", "lookup_material_factor", "lookup_density",
                     "convert_units"}


async def test_assembly_structured_result():
    res = await call("compute_assembly_carbon", {"label": "RC slab", "area_m2": 1.0, "layers": [
        {"name": "concrete", "thickness_mm": 200, "density_kg_m3": 2400, "gwp_kgco2e_per_kg": 0.149},
        {"name": "rebar", "mass_kg_per_m2": 20, "gwp_kgco2e_per_kg": 1.99}]})
    assert not res.is_error
    assert math.isclose(res.structured_content["a1a3_kgco2e_per_m2"], 111.32)


async def test_convert_units_tool():
    res = await call("convert_units", {"value": 119.14, "from_unit": "kgCO2e/m3",
                                       "to_unit": "kgCO2e/kg", "density_kg_m3": 489.41})
    assert not res.is_error
    assert math.isclose(res.structured_content["result"], 119.14 / 489.41)


async def test_lookup_tools(fake_api):  # noqa: F811
    res = await call("lookup_material_factor", {"material": "CLT"})
    assert not res.is_error and res.structured_content["usable_count"] == 1
    res = await call("lookup_density", {"material": "CLT"})
    assert res.structured_content["summary"]["n"] == 2


async def test_schema_rejects_negative_factor():
    res = await call("compute_layer_carbon", {"label": "glulam", "thickness_mm": 200, "area_m2": 1,
                                              "density_kg_m3": 470, "gwp_kgco2e_per_kg": -0.896})
    assert res.is_error
    assert "gwp_kgco2e_per_kg" in res.content[0].text


async def test_domain_error_is_tool_error():
    res = await call("convert_units", {"value": 119.14, "from_unit": "kgCO2e/m3",
                                       "to_unit": "kgCO2e/kg"})
    assert res.is_error
    assert res.content[0].text.endswith(
        "Invalid input: kgCO2e/m3 → kgCO2e/kg: converting kg to m3 needs density_kg_m3")


async def test_assembly_both_mass_modes_rejected():
    res = await call("compute_assembly_carbon", {"label": "x", "area_m2": 1.0, "layers": [
        {"name": "a", "thickness_mm": 10, "density_kg_m3": 100, "mass_kg_per_m2": 5,
         "gwp_kgco2e_per_kg": 1}]})
    assert res.is_error and "not both" in res.content[0].text


async def test_network_failure_is_tool_error(monkeypatch):
    def down(path, params):
        raise ok.LookupUnavailable("ÖKOBAUDAT unavailable (URLError: test)")
    monkeypatch.setattr(ok, "fetch_json", down)
    res = await call("lookup_density", {"material": "Beton"})
    assert res.is_error and "unavailable" in res.content[0].text
