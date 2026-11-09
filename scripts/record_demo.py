"""Launch the server over stdio as a real MCP client and record the assignment calls.

    uv run python scripts/record_demo.py

Writes demo/transcript.md and demo/transcript.json.
"""
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]

CALLS = [
    ("Original tool: RC slab, A1–A3 per m²", "compute_assembly_carbon", {
        "label": "RC slab", "area_m2": 100.0, "layers": [
            {"name": "concrete 200 mm", "thickness_mm": 200, "density_kg_m3": 2400,
             "gwp_kgco2e_per_kg": 0.149},
            {"name": "rebar", "mass_kg_per_m2": 20, "gwp_kgco2e_per_kg": 1.99}]}),
    ("Modified tool: CLT factor from ÖKOBAUDAT", "lookup_material_factor",
     {"material": "cross laminated timber", "max_results": 3}),
    ("New tool 1: CLT density across ÖKOBAUDAT datasets", "lookup_density",
     {"material": "cross laminated timber", "max_datasets": 10}),
    ("New tool 2: EPD per-m³ factor to per-kg", "convert_units",
     {"value": 119.14, "from_unit": "kgCO2e/m3", "to_unit": "kgCO2e/kg", "density_kg_m3": 489.41}),
    ("New tool 2: slab self-weight, kN per m²", "convert_units",
     {"value": 1, "from_unit": "m2", "to_unit": "kN", "thickness_mm": 200, "density_kg_m3": 2400}),
    ("Invalid input: storage-netted (negative) factor", "compute_layer_carbon",
     {"label": "glulam", "thickness_mm": 200, "area_m2": 1, "density_kg_m3": 470,
      "gwp_kgco2e_per_kg": -0.896}),
    ("Invalid input: per-m³ factor with no density", "convert_units",
     {"value": 119.14, "from_unit": "kgCO2e/m3", "to_unit": "kgCO2e/kg"}),
]


async def main():
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(
        p for p in (str(ROOT / "src"), os.environ.get("PYTHONPATH")) if p)}
    params = StdioServerParameters(command=sys.executable, args=["-m", "carbon_mcp.server"],
                                   cwd=str(ROOT), env=env)
    records = []
    async with Client(params) as client:
        tools = (await client.list_tools()).tools
        for title, name, args in CALLS:
            res = await client.call_tool(name, args)
            records.append({
                "title": title, "tool": name, "arguments": args, "is_error": res.is_error,
                "structured": res.structured_content,
                "text": [c.text for c in res.content if getattr(c, "type", "") == "text"],
            })
            print(("ERROR " if res.is_error else "ok    ") + title)
    out = ROOT / "demo"
    out.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    (out / "transcript.json").write_text(json.dumps(
        {"recorded": stamp, "tools": [t.name for t in tools], "calls": records},
        indent=2, ensure_ascii=False))
    md = [f"# MCP demo transcript\n\nRecorded {stamp} over stdio. "
          f"Server tools: {', '.join(t.name for t in tools)}.\n"]
    for r in records:
        body = r["structured"] if r["structured"] is not None else r["text"]
        md.append(f"## {r['title']}\n\n`{r['tool']}` — isError: **{str(r['is_error']).lower()}**\n\n"
                  f"Arguments:\n```json\n{json.dumps(r['arguments'], indent=2, ensure_ascii=False)}\n```\n"
                  f"Result:\n```json\n{json.dumps(body, indent=2, ensure_ascii=False)}\n```\n")
    (out / "transcript.md").write_text("\n".join(md))
    print(f"Wrote {out / 'transcript.md'}")


if __name__ == "__main__":
    asyncio.run(main())
