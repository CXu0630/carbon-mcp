# carbon-mcp

MCP server for early-design embodied-carbon comparisons of building assemblies. It exposes the
four Homework 4 calculators, a factor lookup now backed by ÖKOBAUDAT, and two new tools: a
density lookup and a unit converter.

## Run

```bash
uv sync --extra dev
uv run pytest                          # offline tests (fixtures)
uv run pytest -m live                  # hits the real ÖKOBAUDAT API
uv run carbon-mcp                      # stdio server
npx @modelcontextprotocol/inspector uv run carbon-mcp   # MCP Inspector
uv run python scripts/record_demo.py   # records demo/transcript.md over stdio
```

### Local model client (Ollama)

`scripts/local_agent.py` is a minimal MCP client. It launches the server over stdio, gives the
tool schemas to a local Ollama model, runs the model's tool calls through MCP, and returns the
results to the model.

```bash
brew install ollama && ollama serve        # or the Ollama app
ollama pull qwen3:4b-instruct-2507-q4_K_M  # 2.5 GB; same model as the HW4 notebook
uv run python scripts/local_agent.py       # interactive chat
uv run python scripts/local_agent.py --log demo/agent.md \
  "Which is lower A1-A3 per m2: 200 mm RC slab with 20 kg/m2 rebar, or 200 mm CLT with a 50 mm concrete topping? Look up factors."
```

`OLLAMA_MODEL` swaps the model (e.g. `qwen3:8b` if 4B misfires). Tool calls print to stderr;
`--log` appends the calls, arguments, results and answer as markdown.

### Claude Desktop

`claude_desktop_config.json`:

```json
{"mcpServers": {"embodied-carbon": {
  "command": "uv", "args": ["--directory", "/Users/cxu/Documents/repos/carbon-mcp", "run", "carbon-mcp"]}}}
```

## Tools

All results are structured JSON (`structuredContent`) that echo the inputs and state units and
scope. Ranges are enforced twice: in the JSON schema the client sees, and again in the function.
Invalid input returns a tool result with `isError: true` and a message naming the field and the
valid range. It never returns a plausible-looking number.

| Tool | Status | Purpose | Inputs (units, valid range) | Result |
| --- | --- | --- | --- | --- |
| `compute_layer_carbon` | HW4 | A1–A3 of one uniform layer | label; thickness_mm 1–2000; area_m2 0.01–1e6; density_kg_m3 10–20,000; gwp_kgco2e_per_kg 0–50 | volume m³, mass kg, A1–A3 kgCO2e, kgCO2e/m², scope |
| `compute_assembly_carbon` | HW4 | A1–A3 of a 1–12 layer assembly | label; area_m2; layers[]: name, gwp 0–50, and **either** thickness_mm + density_kg_m3 **or** mass_kg_per_m2 0.01–5000 | per-layer mass, kgCO2e, share %; total; kgCO2e/m² |
| `compute_transport_carbon` | HW4 | A4, one delivery leg | label; mass_kg 0.1–1e8; distance_km 0–20,000; factor_kgco2e_per_tkm 0.001–2 | tonne·km, A4 kgCO2e |
| `compute_biogenic_carbon` | HW4 | EN 16449 stored CO2 | label; volume_m3 0.001–1e5; density_kg_m3 250–1200 at ω; moisture_content_pct 0–30 | dry mass kg, stored kgCO2; reported separately |
| `lookup_material_factor` | modified | A1–A3 factor from ÖKOBAUDAT EPDs | material, 2–100 chars, English or German; max_results 1–8 | per dataset: name, link, compliance, validity, declared unit and its mass, density, GWP A1–A3 by indicator, `gwp_kgco2e_per_kg`, notes |
| `lookup_density` | **new** | Sourced density with spread | material, 2–100 chars; max_datasets 1–25 | per-dataset gross density with link; n, median, min, max, spread % |
| `convert_units` | **new** | Quantity and carbon-factor conversion | value, abs ≤ 1e12; from_unit, to_unit; density_kg_m3 10–20,000 when crossing volume↔mass; thickness_mm 1–2000 when crossing area↔volume | result, unit, parameters used, warnings |

### Lookup details

- **Source.** ÖKOBAUDAT (BBSR) public soda4LCA API; no key. English queries that find nothing
  are retried in German (e.g. "cross laminated timber" → "Brettsperrholz").
- **Ranking.** EN 15804+A2 first, then unexpired datasets, then the most recent reference year.
- **Factor.** GWP-fossil + GWP-luluc for module A1–A3, divided by the declared unit's mass. This
  excludes biogenic storage, consistent with `compute_biogenic_carbon`. Older EN 15804+A1
  datasets report one GWP that nets biogenic uptake for timber, so no factor is derived from them
  (`gwp_kgco2e_per_kg: null`, with a note). The same happens when the declared unit has no mass
  or the result would be negative.
- **Density.** The dataset's declared "gross density", or its mass per declared m³.
- **Errors.** A network failure gives `isError: true` ("ÖKOBAUDAT unavailable …"). No match gives
  an empty result with a note; that is not an error.

### Unit converter

The dimensions form one chain: area –(thickness)→ volume –(density)→ mass –(g = 9.80665)→
weight.

- **Units.** Mass: kg, g, t, tonne, lb, short_ton. Weight: N, kN, lbf, kip. Volume: m3, L, ft3,
  yd3. Area: m2, ft2. Carbon: kgCO2e, gCO2e, tCO2e.
- **Ratios.** Numerator and denominator convert separately. For example, `kgCO2e/m3 → kgCO2e/kg`
  needs a density, and `kg/m3 → lb/ft3` needs nothing.
- **Errors.** The tool errors on an unknown unit, a missing density or thickness, a ratio
  converted to a non-ratio, carbon converted to mass, or a negative physical quantity. Negative
  carbon factors convert, but come with a warning that the calculators will reject them.

## Client vs. server

The server owns everything that must be correct regardless of which model calls it. It defines
the typed input schemas, units and valid ranges, and validates every argument against them. It
applies the formulas and labels every result with its life-cycle scope. It queries ÖKOBAUDAT,
ranks the datasets, derives the per-kg factor, and attaches provenance links. It keeps biogenic
storage out of A1–A3. On invalid input it returns `isError` with a message that names the field,
instead of a plausible-looking number. It is stateless, holding no memory between calls. The client, here `local_agent.py` with a local
model, or Claude Desktop or MCP Inspector, owns judgment and conversation. It decides which tool
fits the question and extracts the numbers from the user's text into typed arguments. It chains
calls (lookup → convert → assembly) and chooses among the datasets a lookup returns, saying why.
It recovers from errors by correcting the arguments or asking the user. It writes the answer
with A1–A3, A4 and biogenic storage on separate lines. Because validation lives on the server, a
weak or mistaken client can fail to get an answer, but it cannot get a wrong number past the
server.

## What a human should verify before acting

1. **Dataset fit.** The ÖKOBAUDAT dataset is the product you will specify: region (mostly DE or
   AT), strength class, product type. It is unexpired and EN 15804+A2.
2. **Declared unit.** The declared unit and its mass are what you think they are. Open the
   dataset link and check.
3. **Density.** The density matches the factor's dataset. If `lookup_density` shows a wide
   spread, the median may not suit your product.
4. **Structural equivalence.** The assemblies compared share span, load, fire rating and
   acoustics. No tool checks this.
5. **Scope.** A1–A3 (+A4) is not whole-life carbon. A5, B and C stages are excluded, and biogenic
   storage is temporary.
6. **Final figures.** Generic or average EPD data should be replaced with the product's own EPD.
