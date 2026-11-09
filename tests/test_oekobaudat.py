"""Parser and ranking tests on fixtures shaped like ÖKOBAUDAT responses.

Live API test: `uv run pytest -m live` (needs network).
"""
import json
import math
from pathlib import Path

import pytest

from carbon_mcp import oekobaudat as ok

FIX = Path(__file__).parent / "fixtures"
A2 = json.loads((FIX / "process_clt_a2.json").read_text())
A1 = json.loads((FIX / "process_clt_a1.json").read_text())
SEARCH = json.loads((FIX / "search_brettsperrholz.json").read_text())


@pytest.fixture
def fake_api(monkeypatch):
    calls = []

    def fake(path, params):
        calls.append((path, params))
        if path == "processes":
            return SEARCH if params["name"] == "Brettsperrholz" else {"data": []}
        uuid = path.split("/")[1]
        return {"8c4eb262-9ae6-4ace-8f3d-0b06f2007f3e": A2,
                "e0a9e1c6-4dec-41b0-b9c1-c9e05010bc68": A1}[uuid]

    monkeypatch.setattr(ok, "fetch_json", fake)
    ok._dataset_cached.cache_clear()
    return calls


def test_parse_a2_uses_fossil_per_kg():
    rec = ok.parse_dataset(A2, SEARCH["data"][1])
    assert rec["declared_unit"] == {"amount": 1.0, "unit": "m3", "mass_kg": 489.41}
    assert math.isclose(rec["a1a3_kgco2e_per_declared_unit"], 119.13949426364547)
    assert math.isclose(rec["gwp_kgco2e_per_kg"], 119.13949426364547 / 489.41)
    assert 0.24 < rec["gwp_kgco2e_per_kg"] < 0.25          # close to Arup's 0.25
    assert rec["gwp_a1a3_per_declared_unit"]["gwp_total"] < 0  # biogenic netted in total
    assert rec["gross_density_kg_m3"] == 489.41


def test_parse_a1_gives_no_factor():
    rec = ok.parse_dataset(A1, SEARCH["data"][0])
    assert rec["gwp_kgco2e_per_kg"] is None
    assert any("15804+A1" in n for n in rec["notes"])
    assert rec["expired"]
    assert rec["gross_density_kg_m3"] == 470.88


def test_scenario_modules_ignored():
    mods = ok._gwp_modules(A2)["gwp_total"]
    assert "D" not in mods


def test_lookup_factor_falls_back_to_german_and_ranks_a2_first(fake_api):
    out = ok.lookup_factor("cross laminated timber", 3)
    assert out["search_terms_tried"] == ["cross laminated timber", "Brettsperrholz"]
    assert out["search_term_used"] == "Brettsperrholz"
    assert out["results"][0]["uuid"].startswith("8c4eb262")
    assert out["usable_count"] == 1


def test_lookup_density_summary(fake_api):
    out = ok.lookup_density("CLT", 10)
    assert out["summary"]["n"] == 2
    assert out["summary"]["median_kg_m3"] == pytest.approx((489.41 + 470.88) / 2)


def test_no_match(fake_api):
    out = ok.lookup_factor("unobtainium", 3)
    assert out["results"] == [] and "No ÖKOBAUDAT match" in out["note"]


@pytest.mark.live
def test_live_clt():
    ok._dataset_cached.cache_clear()
    out = ok.lookup_factor("Brettsperrholz", 3)
    assert out["results"], out
    usable = [r for r in out["results"] if r["gwp_kgco2e_per_kg"]]
    assert usable and all(0.05 < r["gwp_kgco2e_per_kg"] < 1.5 for r in usable)
    dens = ok.lookup_density("Brettsperrholz", 10)
    assert 350 < dens["summary"]["median_kg_m3"] < 600
