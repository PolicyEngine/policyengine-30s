"""Invariants of data/uk/video.json and the scripts that build it.

Runs with the rest of the suite (`bun run test`).

Invariants:
  - schema: every key of the US data/video.json is present, plus the UK fields the page reads
  - accounting: at every plotted earnings point the change in net income is the income tax
    cut plus the change in Universal Credit (nothing else moves), 0 <= gain <= tax cut, and
    National Insurance is unchanged
  - monotonicity (intended): the family's gain never falls as earnings rise
  - exhaustive: each on-screen sentence about the curve holds at every plotted point, and the
    compute step recorded it holding at every £1 from £0 to £80,000
  - differential: the plotted points equal data/uk/earnings_sweep.json; policyengine-uk
    2.102.0 and policyengine.py's household calculator agree with it
  - verbatim: the statute wall contains the s. 35(1) paragraph once, at the stated offset;
    the code panel is the parameter file's lines; the quote is in the source sentence
  - traceability: every £ figure on screen is a computed or sourced number
  - national: every stat, decile bar and tag traces to data/uk/national.json, whose accounting
    identity closes; the record-level sample stays out of git and places every dot
  - round trip: rebuilding video.json from data/uk is a no-op
  - property-based: the range rounding in curve_claims always lands inside the computed
    flat stretch, and a stretch found by facts() is maximal
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "tools" / "uk"
UK = ROOT / "data" / "uk"
sys.path.insert(0, str(HERE))

import curve_claims  # noqa: E402

TOL = curve_claims.TOL


@pytest.fixture(scope="module")
def v():
    return json.loads((UK / "video.json").read_text())


@pytest.fixture(scope="module")
def sw():
    return json.loads((UK / "earnings_sweep.json").read_text())


# ------------------------------------------------------------------ schema
def test_schema_superset_of_us(v):
    us = json.loads((ROOT / "data" / "video.json").read_text())
    assert set(us) <= set(v), set(us) - set(v)
    for k in ("reform", "code", "statute", "quote", "household", "nation"):
        assert set(us[k]) <= set(v[k]), (k, set(us[k]) - set(v[k]))
    assert set(us["household"]["curve"]) <= set(v["household"]["curve"])
    assert v["country"] == "uk" and v["currency"] == "£" and v["locale"] == "en-GB"
    assert set(v["captions"]) == {"code", "code_hl", "whatif", "nation"}
    assert v["code"]["repo"] == "policyengine-uk" and v["code"]["arpaLine"] is None
    assert v["household"]["figures"] == {"adults": 1, "kid_ages": [4, 8]}
    assert v["household"]["axis_title"] == "Change in net income, 2026-27"


# ------------------------------------------------------------------ the family curve
def test_points_are_the_computed_points(v, sw):
    assert v["household"]["curve"]["points"] == [[e, g] for e, g in zip(sw["earnings"], sw["gain"])]
    assert sw["earnings"] == [250.0 * i for i in range(321)]


def test_accounting_identity(sw):
    d = sw["change"]
    for i, g in enumerate(sw["gain"]):
        cut = -d["income_tax"][i]
        assert abs(g - (cut + d["universal_credit"][i])) < 0.05, (sw["earnings"][i], g)
        assert -TOL < g <= cut + TOL
        assert abs(d["national_insurance"][i]) < TOL
    assert sw["net_income_components_that_moved"] == ["income_tax", "universal_credit"]


def test_gain_never_falls_with_earnings(sw):
    g = sw["gain"]
    assert all(b >= a - TOL for a, b in zip(g, g[1:]))


def test_on_screen_sentences_hold_at_every_point(v, sw):
    stm = curve_claims.statements(sw["fine"], sw["meta"]["parameters_2026"]["uc_reduction_rate"])
    assert stm["lines"] == v["household"]["curve"]["lines"] and stm["note"] == v["household"]["curve"]["note"]
    b, r, d = sw["baseline"], sw["reform"], sw["change"]
    curve_claims.check(sw["earnings"], sw["gain"], b["universal_credit"], r["universal_credit"],
                       [-x for x in d["income_tax"]], d["universal_credit"], d["national_insurance"],
                       d["uc_earned_income"], stm, sw["fine"]["pin"])
    pc = sw["fine"]["points_checked"]
    assert pc[stm["lines"][0]] == 48_000 - 15_000 + 1 and pc[stm["lines"][1]] == 50_270 - 48_700 + 1
    assert pc["0 <= gain <= tax cut (not on screen)"] == 80_001


def test_note_rate_is_the_model_parameter(v, sw):
    rate = sw["meta"]["parameters_2026"]["uc_reduction_rate"]
    assert f"{round(rate * 100)}p of each £1" in v["household"]["curve"]["note"]


def test_differential_paths_agree(sw):
    other = json.loads((UK / "compute" / "earnings_sweep_pe-uk-2.102.0.json").read_text())
    assert other["meta"]["versions"]["policyengine-uk"] != sw["meta"]["versions"]["policyengine-uk"]
    assert max(abs(a - b) for a, b in zip(sw["gain"], other["gain"])) < 0.01
    cc = json.loads((UK / "compute" / "crosscheck.json").read_text())
    assert cc["meta"]["reform_dict_passed"] == sw["meta"]["reform_dict_passed"]
    assert all(x < 0.01 for x in cc["axes_path"]["max_abs_difference"].values())
    rows = cc["single_household_path"]["rows"]
    assert len(rows) >= 5 and all("sweep_gain" not in r or abs(r["gain"] - r["sweep_gain"]) < 0.01 for r in rows)


# ------------------------------------------------------------------ reform, statute, code, quote
def test_reform_card_is_the_dict_passed(v, sw):
    assert v["reform"]["dict"] == sw["meta"]["reform_dict_passed"]
    ((path, periods),) = v["reform"]["dict"].items()
    ((period, value),) = periods.items()
    assert path == v["reform"]["path"] and value == v["reform"]["to"] == 15_000
    # the year-convention trap: a key of 2026-04-06 silently leaves 2026-27 on current law
    assert period == "2026" and sw["meta"]["parameters_2026"]["personal_allowance_reform"] == value
    assert v["reform"]["from"] == sw["meta"]["parameters_2026"]["personal_allowance_baseline"] == 12_570
    assert v["reform"]["chip"] == "Personal allowance £12,570 → £15,000"
    assert v["captions"]["whatif"][1] == "£15,000?"


def test_statute_is_verbatim(v):
    s = v["statute"]
    st_ = json.loads((UK / "statute.json").read_text())
    assert s["wall"] == st_["wall_text"] and s["h2"] == st_["h2_text"]
    o = s["wall_h2_offset"]
    assert s["wall"][o:o + len(s["h2"])] == s["h2"] and s["wall"].count(s["h2"]) == 1
    assert s["h2"].count(s["amount"]) == 1 and s["wall"].count(s["amount"]) == 1
    assert st_["html_crosscheck"]["lines_found_exactly"] == st_["html_crosscheck"]["lines_checked"] == len(s["wall"].split("\n"))
    words = len([t for t in s["wall"].split() if not re.fullmatch(r"\.+", t)])
    assert words == s["words"] and 2_000 <= words <= 4_500


def test_code_panel_is_the_file(v):
    c = v["code"]
    lines = (UK / "amount.yaml").read_text().splitlines()
    assert c["lines"] == lines[c["first"] - 1:c["first"] - 1 + len(c["lines"])]
    val = lines[c["valueLine"] - 1]
    assert val.strip() == "2021-04-06: 12_570" and val.split(":")[1].strip() == f"{v['reform']['from']:_}"
    assert "Income Tax Act 2007 s. 35" in lines[c["refLine"] - 1]
    assert c["label"] == yaml.safe_load("\n".join(lines))["metadata"]["label"]
    src = json.loads((UK / "code_source.json").read_text())
    assert hashlib.sha256((UK / "amount.yaml").read_bytes()).hexdigest() == src["sha256"] and c["commit"] == src["commit"]


def test_quote_is_in_the_source_sentence(v):
    q = json.loads((UK / "quote.json").read_text())
    frag = v["quote"]["text"].strip("…")
    assert frag in q["sentence"] and 10 <= len(frag.split()) <= 15
    assert " that " in v["quote"]["text"] and v["quote"]["attr"] == "Edward VI · 1551"


def test_pin_is_on_the_top_plateau(v, sw):
    """The pinned point shows a level the text lines do not state: the flat top from £52,700."""
    e, g = v["household"]["curve"]["pin"]
    assert e == 60_000 and round(g) == 972
    assert all(abs(gg - g) < 0.01 for ee, gg in zip(sw["earnings"], sw["gain"]) if 52_700 <= ee <= 80_000)


def test_every_pound_figure_traces(v, sw):
    fine = sw["fine"]
    allowed = {12_570, 15_000, 500, fine["pin"][0], 1}
    for c in fine["on_screen"]["claims"]:
        allowed |= {c["lo"], c["hi"], round(c["gain"])}
    h = v["household"]
    text = " ".join([v["reform"]["chip"], *v["captions"]["whatif"], *h["curve"]["lines"], h["curve"]["note"], h["who"]])
    for num in re.findall(r"£([\d,]+)", text):
        assert int(num.replace(",", "")) in allowed, num


# ------------------------------------------------------------------ source tags
def test_curve_tag_names_the_run_that_drew_it(v, sw):
    """The curve's small print is the version the sweep recorded."""
    assert v["sources"]["curve"] == [f"policyengine.py {sw['meta']['versions']['policyengine']} · static"]


# ------------------------------------------------------------------ national results
@pytest.fixture(scope="module")
def nat():
    return json.loads((UK / "national.json").read_text())


def test_national_figures_are_the_run(v, nat):
    """Each stat, bar and label is read from national.json, at the precision shown."""
    assert v["mock"] is False and v["mock_parts"] == []
    b, w = nat["budget"], nat["winners"]
    pov = nat["poverty"]["absolute_bhc"]["children_under_18"]
    # the count and its direction come from the two headcounts themselves, not the stored difference
    child = pov["headcount_baseline"] - pov["headcount_reform"]
    assert abs(child - pov["children_lifted_out"]) < 1e-6
    assert (child > 0) == (pov["rate_reform"] < pov["rate_baseline"])
    cost, share, kids = v["nation"]["stats"]
    assert cost == {"kind": "billion", "value": round(b["net_cost_2026_27_gbp"] / 1e9), "digits": 0, "what": "net cost in 2026-27"}
    assert share["value"] == round(100 * w["share_households_gaining_over_1gbp"], 1) and share["what"] == "of households gain"
    assert kids["value"] == round(abs(child), -2)
    assert kids["what"] == ("fewer children in poverty" if child > 0 else "more children in poverty")
    dec = sorted(nat["deciles"]["by_decile"], key=lambda r: r["decile"])
    assert v["deciles"]["avg"] == [round(r["average_change_household_net_income"]) for r in dec]
    assert v["deciles"]["caption"] == ["Average change per household", "\nby income decile"]


def test_national_accounting_closes(nat):
    """Households gain what the Exchequer loses (taxes forgone less benefits withdrawn), within 0.5%,
    and the two aggregation paths (policyengine.py's programme totals, the script's own sums) agree."""
    b = nat["budget"]
    prog = b["policyengine_py_program_statistics"]
    net = sum(x["change"] for k, x in prog.items() if not x["is_tax"] and k != "tax_credits") - sum(
        x["change"] for x in prog.values() if x["is_tax"])
    assert abs(net - b["net_cost_2026_27_gbp"]) < 1.0
    assert abs(b["household_net_income_total_change"] - net) <= 0.005 * net
    assert abs(prog["income_tax"]["change"] - b["income_tax_revenue_change"]) < 1.0
    assert nat["meta"]["behavioral_responses"].startswith("none")
    assert nat["meta"]["reform"]["value"] == 15_000 and nat["meta"]["reform"]["start_date"] == "2026-01-01"


def test_national_tags_name_the_run_and_the_licence(v, nat):
    run = f"policyengine.py {nat['meta']['versions']['policyengine']} · enhanced_frs_2024_25 · static"
    assert nat["meta"]["dataset"]["key"] == "enhanced_frs_2024_25_2026"
    geo = json.loads((UK / "geography.json").read_text())
    # the boundary licence's two statements appear verbatim on the map they license
    assert v["sources"]["nation"] == [
        run,
        "poverty: absolute, before housing costs",
        "Source: Office for National Statistics licensed under the Open Government Licence v.3.0",
        "Contains OS data © Crown copyright and database right 2024",
    ]
    assert geo["meta"]["attribution_notes"]["template_verbatim"][0] == v["sources"]["nation"][2]
    # the survey's own citation (UK Data Service EUL clause 11), verbatim from its catalogue entry
    assert v["sources"]["deciles"] == [
        run,
        "Department for Work and Pensions. (2026). Family Resources Survey, 2024-2025.",
        "[data collection]. UK Data Service. SN: 9563, DOI: http://doi.org/10.5255/UKDA-SN-9563-1",
        "© Crown copyright",
    ]
    assert "provenance" not in v


# Every tracked file under data/uk/ and audio/uk/, each reviewed for survey-derived records. A new
# tracked file fails here until someone checks it and adds it.
PUBLIC_UK_FILES = {
    "audio/uk/events.json",
    "data/uk/README.md", "data/uk/amount.yaml", "data/uk/amount.yaml.commit", "data/uk/code_source.json",
    "data/uk/compute/build_report.json", "data/uk/compute/crosscheck.json",
    "data/uk/compute/earnings_sweep_pe-uk-2.102.0.json", "data/uk/compute/rent_sensitivity.json",
    "data/uk/earnings_sweep.json", "data/uk/geography.json", "data/uk/geography_check.json",
    "data/uk/national.json", "data/uk/quote.json", "data/uk/statute.json", "data/uk/video.json",
}
CODE = re.compile(r"^(?:[EWSN]\d{8}|NI)$")


def _record_like(x, path=""):
    """Paths of lists that look like survey rows: at least 100 short lists or dicts that each carry
    an area code (a constituency code or "NI") next to numbers. Map geometry carries codes in dicts
    with polygons, which is allowed."""
    found = []
    if isinstance(x, dict):
        for k, y in x.items():
            found += _record_like(y, f"{path}.{k}")
    elif isinstance(x, list):
        def row(r):
            vals = list(r.values()) if isinstance(r, dict) else r if isinstance(r, list) else None
            if vals is None or (isinstance(r, dict) and "polys" in r) or len(vals) > 8:
                return False
            return any(isinstance(e, str) and CODE.match(e) for e in vals) and any(isinstance(e, (int, float)) and not isinstance(e, bool) for e in vals)
        if len(x) >= 100 and sum(map(row, x[:200])) >= 50:
            found.append(path or "<root>")
        for i, y in enumerate(x[:5]):
            found += _record_like(y, f"{path}[{i}]")
    return found


def test_the_survey_sample_stays_out_of_git(v, nat):
    """The dots are record-level survey derivatives: video.json only names their file, the file sits
    under data/uk/private/ (git-ignored), nothing there is tracked, every tracked UK file is on the
    reviewed list, and no tracked JSON carries rows that look like the sample."""
    assert v["sample"] is None and v["sampleFile"].startswith("private/")
    ignored = subprocess.run(["git", "check-ignore", "-q", str(UK / v["sampleFile"])], cwd=ROOT)
    assert ignored.returncode == 0
    tracked = subprocess.run(["git", "ls-files", "data/uk", "audio/uk"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert not [f for f in tracked if f.startswith("data/uk/private/")]
    assert set(tracked) <= PUBLIC_UK_FILES, set(tracked) - PUBLIC_UK_FILES
    for f in tracked:
        if f.endswith(".json"):
            assert _record_like(json.loads((ROOT / f).read_text())) == [], f


def test_the_privacy_scan_catches_a_smuggled_sample(v):
    """The scan above is not vacuous: the real sample's row shape, hidden under any key, is caught."""
    rows = [["E14001063", 486.0, "E14001063", 5]] * 150 + [["NI", 0.0, None, 2]] * 50
    assert _record_like({"deep": {"stuff": rows}}) == [".deep.stuff"]
    assert _record_like({"x": [{"code": "S14000001", "gain": 972.0, "decile": 9}] * 120}) == [".x"]
    assert _record_like({"cdGeo": v["cdGeo"]}) == []


def test_every_draw_has_a_place(v, nat):
    """Where the private sample exists: 12,000 draws, each in one of the 650 constituencies or, for
    Northern Ireland (which the data does not split by constituency), in NI as a whole."""
    path = UK / v["sampleFile"]
    if not path.exists():
        pytest.skip("data/uk/private/ is not in this checkout")
    rows = json.loads(path.read_text())
    codes = {c["geoid"] for c in v["cdGeo"]}
    ni = set(v["sampleRegions"]["NI"])
    assert len(rows) == nat["sample"]["n_draws"] == 12_000 and len(ni) == 18 and ni <= codes
    for c1, g, c2, d in rows:
        assert (c1 == "NI" and c2 is None) or (c1 == c2 and c1 in codes - ni), (c1, c2)
        assert -1 <= d <= 10
    assert sum(r[0] == "NI" for r in rows) == nat["sample"]["draws_in_northern_ireland"]
    # the draws are weighted: their share gaining is the population's, within sampling error
    share = sum(r[1] > 1 for r in rows) / len(rows)
    assert abs(share - nat["winners"]["share_households_gaining_over_1gbp"]) < 0.02


# ------------------------------------------------------------------ round trip
def test_rebuild_is_a_noop():
    before = hashlib.sha256((UK / "video.json").read_bytes()).hexdigest()
    subprocess.run([sys.executable, str(HERE / "build_uk_video.py")], check=True, capture_output=True, cwd=ROOT)
    assert hashlib.sha256((UK / "video.json").read_bytes()).hexdigest() == before


# ------------------------------------------------------------------ property-based
@given(st.integers(0, 10**6))  # earnings on the £1 grid are whole pounds
def test_rounding_brackets(x):
    assert x <= curve_claims.up100(x) < x + 100 and curve_claims.up100(x) % 100 == 0
    assert x - 10 < curve_claims.down10(x) <= x and curve_claims.down10(x) % 10 == 0


@settings(max_examples=200, deadline=None)
@given(st.integers(0, 60), st.integers(1, 60), st.integers(1, 60), st.integers(1, 40), st.integers(1, 40))
def test_facts_find_maximal_flat_stretches_and_ranges_sit_inside(z, r1, p1, r2, p2):
    """A synthetic staircase: 0, ramp, flat v1 on UC, ramp while UC ends, flat v2 off UC, ramp, flat v3."""
    step = 97.0
    v1, v2, v3 = 218.7, 486.0, 972.0
    segs = [(0.0, z + 1, True)] + [(None, r1, True)] + [(v1, p1 + 2, True)] + [(None, r2, None)] + \
           [(v2, p2 + 1, False)] + [(None, 3, False)] + [(v3, 4, False)]
    G, on0, on1 = [], [], []
    prev = 0.0
    for val, n, uc in segs:
        for k in range(n):
            if val is None:  # strictly rising ramp towards the next level
                g = prev + (k + 1) * 7.3
            else:
                g = val
            G.append(g)
            on0.append(uc is not False)
            on1.append(uc is True)
        prev = G[-1]
    E = [step * i for i in range(len(G))]
    start1 = z + 1 + r1
    pin = E[start1]
    UC0 = [100.0 if o else 0.0 for o in on0]
    UC1 = [100.0 if o else 0.0 for o in on1]
    f = curve_claims.facts(E, G, UC0, UC1, [0.0] * len(G), pin)
    p = f["plateau_on_uc"]
    assert p["from"] == E[start1] and p["to"] == E[start1 + p1 + 1] and p["gain"] == v1
    q = f["plateau_off_uc"]
    assert q["gain"] == v2 and q["from"] == E[start1 + p1 + 2 + r2]
    stm = curve_claims.statements(f, 0.55) if curve_claims.up100(p["from"]) < curve_claims.down10(p["to"]) and \
        curve_claims.up100(q["from"]) < curve_claims.down10(q["to"]) else None
    if stm:
        for c, pl in zip(stm["claims"], (p, q)):
            assert pl["from"] <= c["lo"] < c["hi"] <= pl["to"]
