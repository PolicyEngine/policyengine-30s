"""Turn the raw PolicyEngine outputs in data/ into the small per-scene files
that tools/build_video_data.py assembles into data/video.json.

Every displayed number is derived here from a named variable in the model
output, and the rounded figures are re-summed to prove the waterfall closes.

usage: uv run --with pyyaml tools/adapt_outputs.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def load(name):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else None


def household():
    h = load("household.json")
    if not h:
        return None
    k = {r["variable"]: r for r in h["key_numbers"]}
    b = lambda v: k[v]["baseline"]
    r = lambda v: k[v]["reform"]
    taxes_b = b("income_tax_before_credits") + b("employee_payroll_tax") + b("state_income_tax")
    taxes_r = r("income_tax_before_credits") + r("employee_payroll_tax") + r("state_income_tax")
    rows = [
        ("Earnings", b("employment_income"), r("employment_income"), "start"),
        ("Taxes before federal credits", -taxes_b, -taxes_r, "minus"),
        ("Child Tax Credit", b("ctc_value"), r("ctc_value"), "plus"),
        ("Earned Income Tax Credit", b("eitc"), r("eitc"), "plus"),
        ("WIC and school meals", b("household_benefits"), r("household_benefits"), "plus"),
    ]
    rows = [dict(label=l, base=round(x), reform=round(y), kind=kd) for l, x, y, kd in rows]
    net_b, net_r = b("household_net_income"), r("household_net_income")
    # the rounded rows must close to the rounded net income
    for key, net in (("base", net_b), ("reform", net_r)):
        s = sum(row[key] for row in rows)
        assert abs(s - round(net)) <= 1, (key, s, net)
    rows.append(dict(label="Net income", base=round(net_b), reform=round(net_r), kind="total"))
    # benefits row: name exactly what the model counted
    bens = {x["variable"] for x in h["benefits_counted_in_net_income_nonzero"]}
    assert bens == {"wic", "reduced_price_school_meals"}, bens
    assert abs(b("household_benefits") - sum(x["baseline"] for x in h["benefits_counted_in_net_income_nonzero"])) < 1
    gain = round(net_r - net_b)
    assert gain == 1600, gain
    hd = h["meta"]["household_definition"]
    kids = sorted(p["age"] for p in hd["people"] if p.get("is_tax_unit_dependent"))
    # the same family across earnings (earnings_sweep.json): the answer is not (3000-2200) x 2
    sw = load("earnings_sweep.json")
    assert sw, "run data/compute/earnings_sweep.py first"
    E, G = sw["earnings"], sw["gain"]
    x_max = 120_000
    pts = [[e, g] for e, g in zip(E, G) if e <= x_max]
    starts, full = sw["gain_starts_at_earnings"], sw["full_gain_from_earnings"]
    below = int(starts // 100 * 100)              # $42,206 -> "below $42,200"
    from_ = int(-(-full // 100) * 100)            # $57,996 -> "from $58,000"
    # the on-screen statements must hold at every computed grid point
    assert all(g == 0 for e, g in pts if e < below), "gain not $0 below the stated threshold"
    assert all(abs(g - gain) < 0.01 for e, g in pts if e >= from_), "gain not full above the stated point"
    assert abs(dict(pts)[60_000] - gain) < 0.01  # the $60,000 household from household.json
    # the on-screen reason, checked at every point: the gain is exactly the income tax the
    # current credit leaves unpaid (liability beyond its $1,000 nonrefundable share), up to $1,600
    p26 = sw["meta"]["parameters_2026"]
    n_kids = len(kids)
    nr0 = n_kids * (p26["ctc_amount"] - p26["refundable_individual_max"])
    TL = sw["tax_liability"][: len(pts)]
    assert all(abs(g - min(max(tl - nr0, 0), gain)) < 0.01 for (e, g), tl in zip(pts, TL)), \
        "gain is not the income tax the current credit leaves unpaid"
    pin = [50_000, dict(pts)[50_000]]
    out = {
        "who": f"<b>Take a married couple in Ohio</b><br>two kids, ages {kids[0]} and {kids[1]}<br>one earner",
        "curve": {
            "points": pts,
            "xMax": x_max,
            "pin": pin,
            "lines": [f"$0 below ${below:,} in earnings.", f"+${gain:,} from ${from_:,}."],
            "note": (
                f"The refundable part stays at ${p26['refundable_individual_max']:,.0f} per child, so the extra "
                f"${gain:,} only offsets income tax the current credit leaves unpaid."
            ),
        },
        "gain": gain,
        # an example household, not a located one: its dot sits at Ohio's geographic centre
        "lonlat": [-82.79, 40.29],
        "source": "data/earnings_sweep.json (policyengine_us axes, cross-checked with policyengine.py) and data/household.json",
    }
    (DATA / "household_video.json").write_text(json.dumps(out, indent=1))
    return out


def geoid4(g):
    """District key as the app's 4-digit SSDD string."""
    if g is None:
        return None
    return f"{int(g):04d}"


def sample():
    smp = load("households_sample.json")
    if not smp:
        return None
    cols = smp["columns"] if "columns" in smp else None
    rows = smp["rows"] if "rows" in smp else smp["households"]
    out = []
    for r in rows:
        d = dict(zip(cols, r)) if cols else r
        out.append([int(d["state_fips"]), round(float(d["household_net_income_change"]), 2), geoid4(d["congressional_district_geoid"]), int(d["decile"])])
    (DATA / "sample_video.json").write_text(json.dumps(out, separators=(",", ":")))
    return smp.get("meta", {})


def nation(sample_meta):
    n = load("national.json")
    if not n:
        return None
    b = n["budget"]
    cost = -b["federal_income_tax_revenue_change"]
    hh = n["households_total_weighted"]
    share = n["winners"]["share_households_gaining_over_1usd"]
    child = n["poverty"]["spm"]["children_under_18"]
    per_dot = hh / 12000
    dec = sorted(n["deciles"]["by_decile"], key=lambda r: r["decile"])
    assert [r["decile"] for r in dec] == list(range(1, 11))
    children_out = child["children_lifted_out"]
    # both computation paths agree on child poverty to ~1e-9; cost differs 0.24%
    # between them ($31.19B vs $31.27B), so the cost shows at whole-billion precision
    out = {
        # the dataset covers the 50 states and DC; its weighted household total
        # (124.6M) is not checked against Census, so no count or per-dot figure is shown
        "caption": ["Now all ", "50 states and DC."],
        "stats": [
            {"kind": "billion", "value": round(cost / 1e9), "digits": 0, "what": "federal cost in 2026"},
            {"kind": "pct", "value": round(100 * share, 1), "digits": 1, "what": "of households gain"},
            {"kind": "count", "value": round(children_out, -2), "what": "fewer children in poverty"},
        ],
        # 12,000 draws with replacement cover 6,976 distinct households (README, "The story")
        "dotNote": "Each dot: a household drawn by weight, placed at random in its assigned congressional district",
        "draws": {"n": sample_meta.get("n_draws", 12000) if sample_meta else 12000,
                  "unique": sample_meta.get("unique_households_drawn") if sample_meta else None},
        "dotMax": 3200,
        "households": hh,
        "deciles": {
            "avg": [round(r["average_change_household_net_income"]) for r in dec],
            "caption": ["Average change per household", "\nby income decile"],
        },
        "raw": {"cost": cost, "share": share, "children_lifted_out": children_out},
    }
    (DATA / "nation_video.json").write_text(json.dumps(out, indent=1))
    return out


def districts():
    d = load("districts.json")
    lay = load("district_layout.json")
    if not d or not lay:
        return None
    vals = []
    for r in d["districts"]:
        vals.append({"geoid": geoid4(r["geoid"]), "avg": r["avg_change"], "share": r.get("share_gaining"), "label": r.get("district_id") or r.get("label")})
    byid = {v["geoid"]: v for v in vals}
    layout = []
    for x in lay["districts"]:
        polys = [ring for poly in x["polygons"] for ring in poly[:1]]
        layout.append({"geoid": geoid4(x["geoid"]), "id": x["district_id"], "cx": x["centroid"]["x"], "cy": x["centroid"]["y"],
                       "polys": [[[round(a, 3), round(b, 3)] for a, b in ring] for ring in polys]})
    missing = [l["id"] for l in layout if l["geoid"] not in byid]
    assert not missing, missing
    for l in layout:
        byid[l["geoid"]]["label"] = l["id"]
    top = max(vals, key=lambda v: v["avg"])
    mx = max(v["avg"] for v in vals)
    out = {
        "caption": ["Down to every ", "congressional district."],
        "legend": "Average gain per household",
        "max": round(mx, -1) if mx > 100 else mx,
        "values": vals,
        "layout": layout,
        "highlight": top["geoid"],
        "highlightText": f"{top['label']} · +${top['avg']:,.0f}",
    }
    (DATA / "districts_video.json").write_text(json.dumps(out, separators=(",", ":")))
    return {k: v for k, v in out.items() if k not in ("values", "layout")}


if __name__ == "__main__":
    print(json.dumps(household(), indent=1))
    sm = sample()
    print("sample meta", json.dumps(sm, indent=1)[:800] if sm else None)
    nat = nation(sm)
    print(json.dumps(nat, indent=1) if nat else "national: not yet")
    # districts.json stays in data/ for the record but is not shown: median
    # effective sample size is 20 per district, so within-state spread
    # ($105 sd) exceeds between-state spread ($58 sd) -- mostly sampling noise.
