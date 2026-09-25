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
  - MOCK: national parts are flagged, labelled MOCK, and use real July 2024 constituency codes
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
    """The curve's small print is the version the sweep recorded; the MOCK deciles carry none."""
    assert v["sources"]["curve"] == [f"policyengine.py {sw['meta']['versions']['policyengine']} · static"]
    assert v["sources"]["deciles"] == []


# ------------------------------------------------------------------ MOCK national parts
def test_mock_parts_are_flagged_and_placeable(v):
    assert v["mock"] is True and set(v["mock_parts"]) == {"nation", "sample", "deciles"}
    assert all(s["what"].startswith("MOCK") for s in v["nation"]["stats"])
    assert v["nation"]["dotNote"].startswith("MOCK") and v["deciles"]["caption"][0].startswith("MOCK")
    codes = {c["geoid"] for c in v["cdGeo"]}
    geo = json.loads((UK / "geography.json").read_text())
    # the boundary licence's two statements appear verbatim on the map they license
    assert v["sources"]["nation"] == [
        "Source: Office for National Statistics licensed under the Open Government Licence v.3.0",
        "Contains OS data © Crown copyright and database right 2024",
    ]
    assert geo["meta"]["attribution_notes"]["template_verbatim"][0] == v["sources"]["nation"][0]
    assert "provenance" not in v
    assert codes == {c["code"] for c in geo["constituencies"]} and len(codes) == 650
    assert len(v["sample"]) == 12_000
    for c1, g, c2, d in v["sample"]:
        assert c1 == c2 and c1 in codes and 1 <= d <= 10 and g >= 0


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
