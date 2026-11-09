"""MCP server exposing the embodied-carbon tools.

Run:  uv run carbon-mcp            (stdio, for Claude Desktop / MCP Inspector)
"""
import functools
from typing import Annotated, Any

from pydantic import BaseModel, Field

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import calc, oekobaudat, units

mcp = MCPServer(
    name="embodied-carbon",
    instructions=(
        "Embodied-carbon calculators for early-design assembly comparisons. "
        "Calculation tools take numbers only. If a material has no factor or density, "
        "call lookup_material_factor / lookup_density first, then convert_units if the "
        "declared unit is not per kg. Report results with units and life-cycle module "
        "(A1–A3, A4). Report biogenic storage separately; never subtract it from A1–A3."
    ),
)

CALC = ToolAnnotations(readOnlyHint=True, openWorldHint=False, idempotentHint=True)
LOOKUP = ToolAnnotations(readOnlyHint=True, openWorldHint=True, idempotentHint=True)


def _tool_errors(fn):
    """Turn domain errors into MCP tool errors (isError: true) with a readable message."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:
            raise ToolError(f"Invalid input: {exc}") from exc
        except oekobaudat.LookupUnavailable as exc:
            raise ToolError(str(exc)) from exc
    return wrapper


Label = Annotated[str, Field(min_length=1, max_length=200,
                             description="Free-text name, echoed in the result.")]
Area = Annotated[float, Field(ge=0.01, le=1e6, description="Plan area, m², 0.01–1,000,000.")]
Gwp = Annotated[float, Field(ge=0, le=50, description=(
    "A1–A3 factor, kgCO2e/kg, 0–50. Must exclude biogenic storage (no negative factors)."))]


class Layer(BaseModel):
    """One assembly layer: thickness_mm + density_kg_m3, OR mass_kg_per_m2."""
    name: str = Field(description="Layer name.")
    gwp_kgco2e_per_kg: float = Field(ge=0, le=50, description="A1–A3 factor, kgCO2e/kg, 0–50.")
    thickness_mm: float | None = Field(None, ge=1, le=2000, description="mm, 1–2000.")
    density_kg_m3: float | None = Field(None, ge=10, le=20000, description="kg/m³, 10–20,000.")
    mass_kg_per_m2: float | None = Field(None, ge=0.01, le=5000,
                                         description="Areal mass, kg/m², 0.01–5,000 (e.g. rebar).")


# ---------------- original Homework 4 tools ----------------

@mcp.tool(annotations=CALC)
@_tool_errors
def compute_layer_carbon(
    label: Label,
    thickness_mm: Annotated[float, Field(ge=1, le=2000, description="Layer thickness, mm, 1–2000.")],
    area_m2: Area,
    density_kg_m3: Annotated[float, Field(ge=10, le=20000, description="Density, kg/m³, 10–20,000.")],
    gwp_kgco2e_per_kg: Gwp,
) -> dict[str, Any]:
    """Cradle-to-gate (A1–A3) embodied carbon of ONE uniform material layer.

    Returns volume (m³), mass (kg), A1–A3 (kgCO2e), intensity (kgCO2e/m²), and scope.
    """
    return calc.layer_carbon(label, thickness_mm, area_m2, density_kg_m3, gwp_kgco2e_per_kg)


@mcp.tool(annotations=CALC)
@_tool_errors
def compute_assembly_carbon(
    label: Label,
    area_m2: Area,
    layers: Annotated[list[Layer], Field(min_length=1, max_length=12,
                                         description="1–12 layers.")],
) -> dict[str, Any]:
    """Cradle-to-gate (A1–A3) embodied carbon of a MULTI-LAYER assembly.

    Returns per-layer mass, kgCO2e and share (%), total kgCO2e, and kgCO2e/m².
    No A5 site waste. Each layer gives thickness_mm + density_kg_m3, or mass_kg_per_m2.
    """
    rows = [layer.model_dump(exclude_none=True) for layer in layers]
    return calc.assembly_carbon(label, area_m2, rows)


@mcp.tool(annotations=CALC)
@_tool_errors
def compute_transport_carbon(
    label: Label,
    mass_kg: Annotated[float, Field(ge=0.1, le=1e8, description="Delivered mass, kg, 0.1–1e8.")],
    distance_km: Annotated[float, Field(ge=0, le=20000, description="One-way distance, km, 0–20,000.")],
    factor_kgco2e_per_tkm: Annotated[float, Field(ge=0.001, le=2, description=(
        "Freight factor, kgCO2e per tonne·km, 0.001–2. "
        "UK DESNZ 2024 articulated HGV, average laden: 0.07547."))],
) -> dict[str, Any]:
    """Transport-to-site (A4) emissions for one delivery leg: (mass/1000) × km × factor."""
    return calc.transport_carbon(label, mass_kg, distance_km, factor_kgco2e_per_tkm)


@mcp.tool(annotations=CALC)
@_tool_errors
def compute_biogenic_carbon(
    label: Label,
    volume_m3: Annotated[float, Field(ge=0.001, le=1e5, description="Timber volume, m³, 0.001–100,000.")],
    density_kg_m3: Annotated[float, Field(ge=250, le=1200, description=(
        "Wood density at the stated moisture content, kg/m³, 250–1,200."))],
    moisture_content_pct: Annotated[float, Field(ge=0, le=30, description=(
        "Moisture content, % of dry mass, 0–30."))],
) -> dict[str, Any]:
    """CO2 stored in wood per EN 16449. Report separately; never subtract from A1–A3."""
    return calc.biogenic_carbon(label, volume_m3, density_kg_m3, moisture_content_pct)


# ---------------- lookup (modified: now ÖKOBAUDAT) ----------------

Material = Annotated[str, Field(min_length=2, max_length=100, description=(
    "Material or product name, English or German, e.g. 'cross laminated timber', 'Beton C30/37'."))]


@mcp.tool(annotations=LOOKUP)
@_tool_errors
def lookup_material_factor(
    material: Material,
    max_results: Annotated[int, Field(ge=1, le=8, description="Datasets to return, 1–8.")] = 3,
) -> dict[str, Any]:
    """Find A1–A3 GWP factors (kgCO2e/kg) for a material in ÖKOBAUDAT.

    Ranks EN 15804+A2, unexpired, recent datasets first. The factor is GWP-fossil +
    GWP-luluc for A1–A3 divided by the declared unit's mass, so it excludes biogenic
    storage. Each result keeps the declared unit, density, validity, and a link.
    gwp_kgco2e_per_kg is null when it cannot be derived safely; notes say why.
    """
    return oekobaudat.lookup_factor(material, max_results)


# ---------------- new tools ----------------

@mcp.tool(annotations=LOOKUP)
@_tool_errors
def lookup_density(
    material: Material,
    max_datasets: Annotated[int, Field(ge=1, le=25, description="Datasets to check, 1–25.")] = 10,
) -> dict[str, Any]:
    """Look up material density (kg/m³) across ÖKOBAUDAT datasets.

    Returns each dataset's declared gross density plus median, min, max, and spread,
    so the density used in a calculation has a source and a visible range.
    """
    return oekobaudat.lookup_density(material, max_datasets)


@mcp.tool(annotations=CALC)
@_tool_errors
def convert_units(
    value: Annotated[float, Field(description="Value to convert, |value| ≤ 1e12.")],
    from_unit: Annotated[str, Field(description=(
        "Simple unit or ratio. Mass: kg g t tonne lb short_ton. Weight: N kN lbf kip. "
        "Volume: m3 L ft3 yd3. Area: m2 ft2. Carbon: kgCO2e gCO2e tCO2e. "
        "Ratios: e.g. kgCO2e/m3, kg/m3, lb/ft3, kgCO2e/m2."))],
    to_unit: Annotated[str, Field(description="Target unit, same syntax as from_unit.")],
    density_kg_m3: Annotated[float | None, Field(ge=10, le=20000, description=(
        "Needed to cross volume ↔ mass, kg/m³, 10–20,000."))] = None,
    thickness_mm: Annotated[float | None, Field(ge=1, le=2000, description=(
        "Needed to cross area ↔ volume, mm, 1–2000."))] = None,
) -> dict[str, Any]:
    """Convert quantities and per-unit carbon factors between units.

    Dimension chain: area –(thickness)→ volume –(density)→ mass –(standard gravity)→ weight.
    Use it to turn an EPD's kgCO2e/m3 or kgCO2e/m2 into the kgCO2e/kg the calculators need.
    Errors if a needed density/thickness is missing or the units are incompatible.
    """
    return units.convert(value, from_unit, to_unit, density_kg_m3, thickness_mm)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
