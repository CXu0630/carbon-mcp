"""ÖKOBAUDAT (BBSR, Germany) client: material GWP factors and densities.

Uses the public soda4LCA REST API; no account or key. Parses ILCD+EPD process
datasets in the JSON "extended" view.

EN 15804 has two formats:
- +A2 datasets report GWP-total, GWP-fossil, GWP-biogenic, GWP-luluc. The A1–A3
  factor used here is GWP-fossil + GWP-luluc, which excludes biogenic storage.
- +A1 (older) datasets report one GWP that, for bio-based products, nets
  biogenic uptake into A1. No A1–A3 factor is derived from those.
"""
import datetime
import json
import statistics
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache

BASE_URL = "https://oekobaudat.de/OEKOBAU.DAT/resource"
USER_AGENT = "carbon-mcp/0.1 (course project; embodied carbon calculator)"
TIMEOUT_S = 20

GWP_TOTAL = "6a37f984-a4b3-458a-a20a-64418c145fa2"
GWP_FOSSIL = "5f635281-343e-44fb-83df-1971b155e6b6"
GWP_BIOGENIC = "2356e1ab-0185-4db5-86e5-16de51c7485c"
GWP_LULUC = "4331bbdb-978a-490d-8707-eeb047f01a55"
GWP_LEGACY = "77e416eb-a363-4258-a04e-171d843a6460"  # EN 15804+A1 single GWP
GWP_NAMES = {GWP_TOTAL: "gwp_total", GWP_FOSSIL: "gwp_fossil", GWP_BIOGENIC: "gwp_biogenic",
             GWP_LULUC: "gwp_luluc", GWP_LEGACY: "gwp_en15804_a1"}
MASS_PROPERTY = "93a60a56-a3c8-11da-a746-0800200b9a66"

# ÖKOBAUDAT names are mostly German; try these when the English query finds nothing.
GERMAN_TERMS = {
    "cross laminated timber": "Brettsperrholz", "cross-laminated timber": "Brettsperrholz",
    "clt": "Brettsperrholz", "glulam": "Brettschichtholz", "glued laminated": "Brettschichtholz",
    "rebar": "Betonstahl", "reinforcing steel": "Betonstahl", "reinforcement": "Betonstahl",
    "ready mix concrete": "Transportbeton", "concrete": "Beton", "cement": "Zement",
    "screed": "Estrich", "structural steel": "Baustahl", "steel": "Stahl",
    "brick": "Ziegel", "plasterboard": "Gipskarton", "gypsum": "Gips",
    "mineral wool": "Mineralwolle", "glass wool": "Glaswolle", "stone wool": "Steinwolle",
    "timber": "Schnittholz", "lumber": "Schnittholz", "sawn wood": "Schnittholz",
    "aluminium": "Aluminium", "aluminum": "Aluminium", "glass": "Glas",
    "particle board": "Spanplatte", "wood fibre": "Holzfaser", "wood fiber": "Holzfaser",
}


class LookupUnavailable(RuntimeError):
    """ÖKOBAUDAT could not be reached or returned something unreadable."""


def _get_json(path, params):
    url = f"{BASE_URL}/{path}?" + urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.load(resp)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise LookupUnavailable(f"ÖKOBAUDAT unavailable ({type(exc).__name__}: {exc})") from exc


# Swappable for tests.
fetch_json = _get_json


def search(term, page_size=25):
    data = fetch_json("processes", {"search": "true", "name": term, "pageSize": page_size})
    return data.get("data", []) if isinstance(data, dict) else []


@lru_cache(maxsize=256)
def _dataset_cached(uuid):
    return fetch_json(f"processes/{uuid}", {"view": "extended"})


def dataset(uuid):
    return _dataset_cached(uuid)


# ---------- parsing helpers ----------

def _text(items, lang="en"):
    """Pick a language string from [{"lang": .., "value": ..}], falling back to any."""
    if isinstance(items, str):
        return items
    if not isinstance(items, list):
        return None
    by_lang = {i.get("lang"): i.get("value") for i in items if isinstance(i, dict)}
    return by_lang.get(lang) or by_lang.get("de") or next(
        (v for v in by_lang.values() if v), None)


def _float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _compliance_names(item):
    comp = item.get("compliance") or []
    if isinstance(comp, dict):
        comp = [comp]
    return [c.get("name") if isinstance(c, dict) else str(c) for c in comp]


def _is_a2(names):
    return any("15804+A2" in (n or "").replace(" ", "") for n in names)


def _expired(valid_until):
    year = _float(valid_until)
    return year is not None and year < datetime.date.today().year


def rank_search_items(items):
    """+A2 first, then unexpired, then most recent reference year."""
    def key(item):
        return (not _is_a2(_compliance_names(item)), _expired(item.get("validUntil")),
                -(_float(item.get("refYear")) or 0))
    return sorted((i for i in items if i.get("uuid")), key=key)


def _reference_exchange(doc):
    exchanges = (doc.get("exchanges") or {}).get("exchange") or []
    ref_ids = (((doc.get("processInformation") or {}).get("quantitativeReference") or {})
               .get("referenceToReferenceFlow") or [])
    ref_ids = {str(r) for r in (ref_ids if isinstance(ref_ids, list) else [ref_ids])}
    for ex in exchanges:
        if str(ex.get("dataSetInternalID")) in ref_ids:
            return ex
    for ex in exchanges:
        if ex.get("referenceFlow") is True:
            return ex
    return exchanges[0] if exchanges else {}


def _declared_unit(ex):
    """(declared amount, unit, kg per declared unit or None)."""
    props = ex.get("flowProperties") or []
    amount = _float(ex.get("resultingflowAmount")) or _float(ex.get("meanAmount")) or 1.0
    ref = next((p for p in props if p.get("referenceFlowProperty")), props[0] if props else {})
    ref_mean = _float(ref.get("meanValue")) or 1.0
    is_mass_ref = ref.get("uuid") == MASS_PROPERTY or _text(ref.get("name")) == "Mass"
    unit = ref.get("referenceUnit") or ("kg" if is_mass_ref else None)
    mass = next((p for p in props
                 if p.get("uuid") == MASS_PROPERTY or _text(p.get("name")) == "Mass"), None)
    kg = None
    if mass is not None and _float(mass.get("meanValue")):
        kg = amount * _float(mass["meanValue"]) / ref_mean
    return amount, unit, kg


def _material_properties(ex):
    out = {}
    for p in ex.get("materialProperties") or []:
        name = (p.get("name") or "").strip().lower()
        val = _float(p.get("value"))
        if name and val is not None:
            out[name] = {"value": val, "unit": p.get("unit")}
    return out


def _gwp_modules(doc):
    """{indicator: {module: value}} for the GWP indicators present."""
    out = {}
    for res in (doc.get("LCIAResults") or {}).get("LCIAResult") or []:
        ref = res.get("referenceToLCIAMethodDataSet") or {}
        key = GWP_NAMES.get(ref.get("refObjectId"))
        if not key:
            continue
        modules = {}
        for a in (res.get("other") or {}).get("anies") or []:
            if not isinstance(a, dict) or "module" not in a or a.get("scenario"):
                continue
            v = _float(a.get("value"))
            if v is not None:
                modules[a["module"]] = v
        out[key] = modules
    return out


def _a1a3(modules):
    if "A1-A3" in modules:
        return modules["A1-A3"]
    if all(m in modules for m in ("A1", "A2", "A3")):
        return modules["A1"] + modules["A2"] + modules["A3"]
    return None


def parse_dataset(doc, search_item=None):
    search_item = search_item or {}
    info = (doc.get("processInformation") or {}).get("dataSetInformation") or {}
    uuid = info.get("UUID") or search_item.get("uuid")
    name = _text((info.get("name") or {}).get("baseName")) or search_item.get("name")
    compliance = _compliance_names(search_item)
    ex = _reference_exchange(doc)
    amount, unit, kg_per_unit = _declared_unit(ex)
    props = _material_properties(ex)
    density = props.get("gross density", {}).get("value")
    if kg_per_unit is None:
        conv = props.get("conversion factor to 1 kg", {}).get("value")
        if conv:
            kg_per_unit = conv * amount
        elif unit == "m3" and density:
            kg_per_unit = density * amount
    if density is None and unit == "m3" and kg_per_unit:
        density = kg_per_unit / amount

    gwp = _gwp_modules(doc)
    a1a3 = {k: _a1a3(v) for k, v in gwp.items()}
    notes = []
    factor_per_unit = None
    if a1a3.get("gwp_fossil") is not None:
        factor_per_unit = a1a3["gwp_fossil"] + (a1a3.get("gwp_luluc") or 0.0)
        basis = "GWP-fossil + GWP-luluc, A1–A3 (EN 15804+A2); excludes biogenic"
    elif "gwp_en15804_a1" in a1a3:
        basis = None
        notes.append("EN 15804+A1 dataset: single GWP may net biogenic uptake; "
                     "no A1–A3 factor derived. Prefer a +A2 dataset.")
    else:
        basis = None
        notes.append("No A1–A3 GWP values found in this dataset.")

    per_kg = None
    if factor_per_unit is not None:
        if kg_per_unit:
            per_kg = factor_per_unit / kg_per_unit
        else:
            notes.append("No mass for the declared unit; use lookup_density + convert_units.")
    if per_kg is not None and per_kg < 0:
        notes.append("Derived factor is negative; not usable as an A1–A3 input.")
        per_kg = None
    expired = _expired(search_item.get("validUntil"))
    if expired:
        notes.append(f"Dataset validity ended {search_item.get('validUntil')}.")
    return {
        "uuid": uuid, "name": name,
        "classification": search_item.get("classific"),
        "type": search_item.get("type"), "sub_type": search_item.get("subType"),
        "geo": search_item.get("geo"), "ref_year": search_item.get("refYear"),
        "valid_until": search_item.get("validUntil"), "expired": expired,
        "compliance": compliance,
        "declared_unit": {"amount": amount, "unit": unit, "mass_kg": kg_per_unit},
        "gross_density_kg_m3": density,
        "gwp_a1a3_per_declared_unit": a1a3,
        "factor_basis": basis,
        "a1a3_kgco2e_per_declared_unit": factor_per_unit,
        "gwp_kgco2e_per_kg": per_kg,
        "url": f"{BASE_URL}/processes/{uuid}?format=html" if uuid else None,
        "notes": notes,
    }


def _search_with_fallback(material):
    q = material.strip()
    terms = [q]
    low = q.lower()
    for en in sorted(GERMAN_TERMS, key=len, reverse=True):  # longest phrase first
        if en in low:
            terms.append(GERMAN_TERMS[en])
            break
    for term in terms:
        items = search(term)
        if items:
            return term, terms, items
    return None, terms, []


def lookup_factor(material, max_results=3):
    used, tried, items = _search_with_fallback(material)
    ranked = rank_search_items(items)[:max_results]
    results = [parse_dataset(dataset(i["uuid"]), i) for i in ranked]
    usable = [r for r in results if r["gwp_kgco2e_per_kg"] is not None and not r["expired"]]
    return {"query": material, "search_terms_tried": tried, "search_term_used": used,
            "matches_found": len(items), "results": results,
            "usable_count": len(usable),
            "source": "ÖKOBAUDAT (BBSR), soda4LCA API",
            "retrieved": datetime.date.today().isoformat(),
            "note": ("Factors are per kg, A1–A3, excluding biogenic storage. Check the "
                     "dataset matches the product, region, and declared unit before use."
                     if results else "No ÖKOBAUDAT match; try the German product name.")}


def lookup_density(material, max_datasets=10):
    used, tried, items = _search_with_fallback(material)
    ranked = rank_search_items(items)[:max_datasets]
    values, skipped = [], []
    for item in ranked:
        rec = parse_dataset(dataset(item["uuid"]), item)
        d = rec["gross_density_kg_m3"]
        if d is None:
            skipped.append({"name": rec["name"], "uuid": rec["uuid"], "reason": "no density"})
        elif not 10 <= d <= 20000:
            skipped.append({"name": rec["name"], "uuid": rec["uuid"],
                            "reason": f"density {d} outside 10–20000 kg/m3"})
        else:
            values.append({"name": rec["name"], "uuid": rec["uuid"],
                           "density_kg_m3": d, "ref_year": rec["ref_year"],
                           "geo": rec["geo"], "url": rec["url"]})
    ds = [v["density_kg_m3"] for v in values]
    stats = None
    if ds:
        med = statistics.median(ds)
        stats = {"n": len(ds), "median_kg_m3": med, "min_kg_m3": min(ds), "max_kg_m3": max(ds),
                 "spread_pct_of_median": 100 * (max(ds) - min(ds)) / med}
    return {"query": material, "search_terms_tried": tried, "search_term_used": used,
            "datasets_checked": len(ranked), "values": values, "skipped": skipped,
            "summary": stats,
            "source": "ÖKOBAUDAT (BBSR), soda4LCA API — gross density of each dataset",
            "retrieved": datetime.date.today().isoformat(),
            "note": ("Densities are as declared, including moisture for timber. "
                     "Use the value from the dataset whose factor you use when possible."
                     if ds else "No density found; try the German product name.")}
