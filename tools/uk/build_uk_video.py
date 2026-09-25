"""Assemble data/uk/video.json: every string and number the UK cut of the video displays.

Same schema as data/video.json (tools/build_video_data.py), plus the UK fields the
page reads: country, currency, locale, captions, reform.chip, household.figures,
household.axis_title, code.repo, statute.wall_label.

Inputs, each written by a script in tools/uk/ (see data/uk/README.md):
  data/uk/earnings_sweep.json                      family curve (policyengine.py 6.1.1 bundle: policyengine-uk 2.90.2)
  data/uk/compute/earnings_sweep_pe-uk-2.102.0.json  the same sweep on the latest policyengine-uk (differential)
  data/uk/compute/crosscheck.json                  the same family through pe.uk.calculate_household (differential)
  data/uk/statute.json, data/uk/quote.json         legislation.gov.uk and Nichols (1857), via fetch_sources.py
  data/uk/amount.yaml (+ .commit, code_source.json) policyengine-uk parameter file, via fetch_sources.py
  data/uk/geography.json                           ONS July 2024 constituencies, via build_uk_geography.py

National results are MOCK: UK survey microdata may not be processed until
permission is settled (decision d404), so the nation, sample and deciles parts
come from mock_national() below, are labelled MOCK on screen, and set
"mock": true, which makes the page paint its MOCK DATA banner on every frame.

Every on-screen statement is asserted here; the build fails rather than ship a
string the data does not support.

usage (repo root):  uv run --no-project --with pyyaml python tools/uk/build_uk_video.py
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
UK = ROOT / "data" / "uk"
sys.path.insert(0, str(HERE))

import curve_claims  # noqa: E402

X_MAX = 80_000
CODE_FIRST, CODE_LAST = 2, 22  # "values:" through the s. 35 legislation.gov.uk href: the whole file but its description
HOME_CONSTITUENCY = "Manchester Central"  # where the example family's dot sits (an example, not a located household)


def load(name):
    return json.loads((UK / name).read_text())


def pounds(x):
    return f"£{x:,.0f}"


def fiscal_label(year):
    return f"{year}-{(year + 1) % 100:02d}"


# ------------------------------------------------------------------ MOCK national data
MOCK_SEED = 20260925
MOCK_N = 12_000
MOCK_GAIN_LEVELS = [0, 250, 500, 1000]        # round placeholders, not estimates
MOCK_GAIN_WEIGHTS = [0.4, 0.2, 0.3, 0.1]
MOCK_DECILE_AVG = [100 * (i + 1) for i in range(10)]  # a straight ramp: obviously not a result


def mock_national(codes):
    """MOCK: placeholder national figures until the UK microdata question (d404) is settled.

    Every value here is invented; nothing comes from a PolicyEngine national run or
    from survey data. The dots use real July 2024 constituency codes (so the page can
    place them) with pseudo-random gains and deciles from a fixed seed.
    """
    rnd = random.Random(MOCK_SEED)
    sample = []
    for _ in range(MOCK_N):
        c = rnd.choice(codes)
        gain = rnd.choices(MOCK_GAIN_LEVELS, MOCK_GAIN_WEIGHTS)[0]
        sample.append([c, float(gain), c, rnd.randint(1, 10)])
    deciles = {"avg": list(MOCK_DECILE_AVG), "caption": ["MOCK: average change", "\nper household by income decile"]}
    nation = {
        "mock": True,
        "caption": ["Now all of ", "the UK."],
        "stats": [
            {"kind": "billion", "value": 0, "digits": 0, "what": "MOCK cost in 2026-27"},
            {"kind": "pct", "value": 0.0, "digits": 1, "what": "MOCK of households gain"},
            {"kind": "count", "value": 0, "what": "MOCK fewer children in poverty"},
        ],
        "dotNote": "MOCK dots: placeholder households, not survey records, each placed at random in a July 2024 Westminster constituency",
        "draws": {"n": MOCK_N, "unique": None},
        "dotMax": max(MOCK_GAIN_LEVELS),
        "households": None,
        "deciles": deciles,
        "raw": {"cost": None, "share": None, "children_lifted_out": None},
        "generator": "tools/uk/build_uk_video.py mock_national() (random.Random(20260925)); MOCK, pending data permission",
    }
    return nation, sample, deciles


# ------------------------------------------------------------------ pieces
def code_block(from_value):
    text = (UK / "amount.yaml").read_text()
    lines = text.splitlines()
    meta = yaml.safe_load(text)
    src = load("code_source.json")
    assert hashlib.sha256((UK / "amount.yaml").read_bytes()).hexdigest() == src["sha256"]
    commit = (UK / "amount.yaml.commit").read_text().split()[0]
    assert commit == src["commit"]
    # the value in force for 2026-27: the latest dated entry on or before 6 April 2026
    dated = {str(k): v for k, v in meta["values"].items()}
    in_force = max(d for d in dated if d <= "2026-04-06")
    value_line = next(i for i, l in enumerate(lines, 1) if l.strip().startswith(f"{in_force}:"))
    token = lines[value_line - 1].split(":", 1)[1].strip()
    assert token.replace("_", "") == str(from_value) and token == f"{from_value:_}", (token, from_value)
    assert dated[in_force] == from_value
    ref_line = next(i for i, l in enumerate(lines, 1) if "Income Tax Act 2007 s. 35" in l)
    assert "legislation.gov.uk/ukpga/2007/3/section/35" in lines[ref_line]  # the href follows the title
    assert CODE_FIRST <= value_line <= CODE_LAST and CODE_FIRST <= ref_line + 1 <= CODE_LAST == len(lines)
    block = lines[CODE_FIRST - 1:CODE_LAST]
    return {
        "file": src["path"],
        "dedent": min(len(l) - len(l.lstrip()) for l in block if l.strip()),
        "first": CODE_FIRST,
        "lines": block,
        "valueLine": value_line,
        "arpaLine": None,
        "refLine": ref_line,
        "label": meta["metadata"]["label"],
        "commit": commit,
        "repo": "policyengine-uk",
    }, src


def family_curve(sw):
    E = sw["earnings"]
    pts = [[e, g] for e, g in zip(E, sw["gain"]) if e <= X_MAX]
    assert len(pts) == len(E) and E[-1] == X_MAX
    fine = sw["fine"]
    rate = sw["meta"]["parameters_2026"]["uc_reduction_rate"]
    stm = curve_claims.statements(fine, rate)
    assert stm["lines"] == fine["on_screen"]["lines"] and stm["note"] == fine["on_screen"]["note"]
    assert stm["claims"] == fine["on_screen"]["claims"]
    b, r, d = sw["baseline"], sw["reform"], sw["change"]
    cut = [-x for x in d["income_tax"]]
    checked = curve_claims.check(E, sw["gain"], b["universal_credit"], r["universal_credit"], cut,
                                 d["universal_credit"], d["national_insurance"], d["uc_earned_income"], stm, fine["pin"])
    # the £1 run checked the same sentences at all 80,001 pounds
    assert fine["points_checked"][stm["lines"][0]] > 30_000 and fine["points_checked"][stm["note"]] > 30_000
    # the displayed pin sits on the top plateau (+£972 from £52,700), a level the two text lines
    # do not state; the internal plateau detection above still uses fine["pin"]
    at = dict(map(tuple, pts))
    pin = [60_000, at[60_000]]
    top = [g for e, g in pts if e >= 52_700]
    assert all(abs(g - pin[1]) < 0.01 for g in top), "pin is not on the top plateau"
    return {
        "points": pts,
        "xMax": X_MAX,
        "pin": pin,
        "lines": stm["lines"],
        "note": stm["note"],
        # the UK gain tops out at £972, so the US axis (0-1,800, ticks at 800 and 1,600) leaves it flat;
        # the page may read these (site/ is not edited from here)
        "yMax": 1100,
        "yTicks": [0, 500, 1000],
    }, checked


def differential(sw):
    other = load("compute/earnings_sweep_pe-uk-2.102.0.json")
    assert other["earnings"] == sw["earnings"]
    worst = 0.0
    for sec in ("baseline", "reform", "change"):
        for k, v in sw[sec].items():
            worst = max(worst, max(abs(x - y) for x, y in zip(v, other[sec][k])))
    assert worst < 0.01, worst
    strip = lambda f: {k: v for k, v in f.items() if k != "decomposition_max_abs_gap"}
    assert strip(sw["fine"]) == strip(other["fine"]), "the £1 facts differ between policyengine-uk versions"
    cc = load("compute/crosscheck.json")
    assert cc["meta"]["reform_dict_passed"] == sw["meta"]["reform_dict_passed"]
    assert cc["axes_path"]["points"] == len(sw["earnings"])
    assert all(v < 0.01 for v in cc["axes_path"]["max_abs_difference"].values()), cc["axes_path"]
    assert cc["single_household_path"]["points"] >= 5
    return {
        "policyengine_uk_2_102_0_max_abs_difference": worst,
        "policyengine_py_axes_max_abs_difference": cc["axes_path"]["max_abs_difference"],
        "policyengine_py_single_households": cc["single_household_path"]["points"],
        "versions": {"sweep": sw["meta"]["versions"], "latest": other["meta"]["versions"], "crosscheck": cc["meta"]["versions"]},
    }


def centroid(polys):
    """Area-weighted centroid of a MultiPolygon's outer rings in lon/lat (planar; fine at city scale)."""
    A = cx = cy = 0.0
    for poly in polys:
        ring = poly[0]
        for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
            c = x0 * y1 - x1 * y0
            A += c
            cx += (x0 + x1) * c
            cy += (y0 + y1) * c
    return [round(cx / (3 * A), 3), round(cy / (3 * A), 3)]


def boundary_statements(geo):
    """ONS's two required statements for its boundaries, with the year of the boundaries."""
    ons, os_ = geo["meta"]["attribution_notes"]["template_verbatim"]
    year = geo["meta"]["attribution_notes"]["year"][:4]
    assert os_.endswith("[year]") and year == "2024", (os_, year)
    return [ons, os_.replace("[year]", year)]


def main():
    sw = load("earnings_sweep.json")
    m = sw["meta"]
    params = m["parameters_2026"]
    rdict = m["reform_dict_passed"]
    ((rpath, periods),) = rdict.items()
    ((rperiod, rvalue),) = periods.items()
    year = int(rperiod[:4])
    assert year == m["period"] and m["fiscal_year"] == fiscal_label(year)
    assert rvalue == int(rvalue) and params["personal_allowance_reform"] == rvalue
    to_value = int(rvalue)
    from_value = int(params["personal_allowance_baseline"])
    assert from_value == params["personal_allowance_baseline"] and from_value != to_value
    fy = fiscal_label(year)

    code, code_src = code_block(from_value)
    # the code panel is the file the model ran: same bytes in both installed packages
    assert m["personal_allowance_yaml_sha256_in_installed_package"] == code_src["sha256"]
    assert load("compute/earnings_sweep_pe-uk-2.102.0.json")["meta"]["personal_allowance_yaml_sha256_in_installed_package"] == code_src["sha256"]

    st = load("statute.json")
    amount = pounds(from_value)
    assert st["amount"] == amount and amount in st["h2_text"]
    off = st["wall_h2_offset"]
    assert st["wall_text"][off:off + len(st["h2_text"])] == st["h2_text"]
    assert st["html_crosscheck"]["lines_found_exactly"] == st["html_crosscheck"]["lines_checked"]
    assert "2026-27" in st["figure_for_2026_27"]["text"] and amount in st["figure_for_2026_27"]["text"]

    q = load("quote.json")
    assert all(q["checks"]["found_in_ocr"].values())
    assert q["text"] == f"…{q['fragment']}…" and 10 <= len(q["fragment"].split()) <= 15
    # the page breaks the quote before " that ": the two lines it will show
    qb = q["text"].index(" that ")
    quote_lines = [q["text"][:qb], q["text"][qb + 1:]]

    curve, checked = family_curve(sw)
    # line 2 ends where the higher rate starts: allowance + basic rate limit, both from legislation
    brl = st["basic_rate_limit_2026_27"]["amount"]
    assert params["income_tax_thresholds_uk_above_allowance"][1] == brl, "model's basic rate limit differs from FA 2021 s. 5(1)"
    assert sw["fine"]["plateau_off_uc"]["to"] == from_value + brl == sw["fine"]["on_screen"]["claims"][1]["hi"]
    diff = differential(sw)

    fam = m["family_inputs"]
    adults = [p for p in fam["people"] if p["age"] >= 18]
    kids = sorted(p["age"] for p in fam["people"] if p["age"] < 18)
    assert len(adults) == 1 and len(kids) == 2 and fam["household"]["local_authority"] == "MANCHESTER"
    assert fam["household"]["tenure_type"] == "RENT_FROM_HA" and fam["household"]["rent"] == 12 * fam["rent_per_month"]
    # short lines: the page sets this in a 600 px column
    who = (f"<b>Take a single parent<br>in Manchester</b><br>two kids, ages {kids[0]} and {kids[1]}<br>"
           f"housing association rent<br>of {pounds(fam['rent_per_month'])} a month")

    geo = load("geography.json")
    cons = geo["constituencies"]
    assert len(cons) == 650 and len({c["code"] for c in cons}) == 650
    cd_geo = [{"geoid": c["code"], "polys": c["polys"]} for c in cons]
    home = next(c for c in cons if c["name"] == HOME_CONSTITUENCY)
    lonlat = centroid(home["polys"])

    codes = sorted(c["code"] for c in cons)
    nation, sample, deciles = mock_national(codes)
    assert {r[0] for r in sample} <= set(codes) and all(r[0] == r[2] for r in sample)

    captions = {
        "code": "PolicyEngine turns the law into ",
        "code_hl": "code.",
        "whatif": [f"What if Parliament raised the {code['label'].lower()} to ", f"{pounds(to_value)}?"],
        "nation": list(nation["caption"]),
    }
    v = m["versions"]
    video = {
        "country": "uk",
        "currency": "£",
        "locale": "en-GB",
        "mock": True,
        "mock_parts": ["nation", "sample", "deciles"],
        "mock_note": ("MOCK: every national figure (nation stats, the 12,000 map dots, decile bars) is a placeholder "
                      "from mock_national() in tools/uk/build_uk_video.py; no UK survey microdata was processed "
                      "(pending data permission, decision d404). The statute, quote, code and family curve are real."),
        "captions": captions,
        "reform": {
            "label": code["label"],
            "path": rpath,
            "from": from_value,
            "to": to_value,
            "year": year,
            "dict": rdict,
            # no year here: the chart's axis title carries 2026-27, and the shorter chip clears the captions
            "chip": f"{code['label']} {pounds(from_value)} → {pounds(to_value)}",
        },
        "cdGeo": cd_geo,
        "code": code,
        "signoff": "Free and open source · <b>policyengine.org</b>",
        # each chart's small print, in its bottom-right corner; nothing below the URL on the close
        "sources": {
            "curve": [f"policyengine.py {v['policyengine']} · static"],
            # the map draws ONS boundaries, whose licence requires both statements wherever they
            # are used; the video travels without the README. Its figures are MOCK, labelled as such
            "nation": boundary_statements(geo),
            "deciles": [],
        },
        "statute": {
            "wall": st["wall_text"],
            "wall_h2_offset": off,
            "h2": st["h2_text"],
            "amount": amount,
            "cite": st["cite"],
            "source": st["h2_source_url"],
            "wall_source": st["wall_source_url"],
            "wall_label": st["wall_label"],
            "words": st["wall_words_excluding_dot_padding"],
        },
        "quote": {
            "text": q["text"],
            "attr": q["attr"],
            "break": " that ",
            "source": q["source_url"],
            "date_source": q["source_url"],
        },
        "household": {
            "who": who,
            "figures": {"adults": len(adults), "kid_ages": kids},
            "axis_title": f"Change in net income, {fy}",
            "curve": curve,
            "gain": max(g for _, g in curve["points"]),
            # an example household, not a located one: its dot sits at the centroid of Manchester Central
            "lonlat": lonlat,
            "source": ("data/uk/earnings_sweep.json (policyengine_uk axes; identical on policyengine-uk 2.102.0; "
                       "cross-checked with policyengine.py pe.uk.calculate_household)"),
        },
        "nation": nation,
        "sample": sample,
        "districts": None,
        "deciles": deciles,
    }

    # every £ figure in the family and reform text traces to a computed or sourced number
    # the pin is the top plateau, asserted flat from £52,700 in build_curve
    allowed = {from_value, to_value, fam["rent_per_month"], curve["pin"][0], round(curve["pin"][1])}
    for c in sw["fine"]["on_screen"]["claims"]:
        allowed |= {c["lo"], c["hi"], round(c["gain"])}
    shown = [video["reform"]["chip"], *captions["whatif"], *curve["lines"], curve["note"], who,
             f"{pounds(curve['pin'][0])} +{pounds(curve['pin'][1])}", amount]
    for s in shown:
        for num in re.findall(r"£([\d,]+)", s):
            assert int(num.replace(",", "")) in allowed | {1}, (s, num)  # "each £1" in the note

    out = UK / "video.json"
    out.write_text(json.dumps(video, ensure_ascii=False))
    json.loads(out.read_text())  # valid JSON
    report = {
        "written": str(out.relative_to(ROOT)),
        "mock_parts": video["mock_parts"],
        "on_screen": {
            "captions": captions, "chip": video["reform"]["chip"], "who": who, "lines": curve["lines"],
            "note": curve["note"], "pin": curve["pin"], "quote_lines": quote_lines, "quote_attr": q["attr"],
            "statute_cite": st["cite"], "statute_amount": amount, "wall_label": st["wall_label"],
            "sources": video["sources"], "nation_stats": [s["what"] for s in nation["stats"]],
            "dotNote": nation["dotNote"],
        },
        "points_checked_on_the_plotted_grid": checked,
        "points_checked_at_every_pound": sw["fine"]["points_checked"],
        "differential": diff,
        "code_panel": {k: code[k] for k in ("first", "valueLine", "refLine", "dedent", "label", "commit")},
        "lonlat": lonlat,
    }
    (UK / "compute" / "build_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
