"""Invariants of the family scene: the Ohio couple with two kids across earnings.

The on-screen claims are "$0 below $42,200", "+$780 at $50,000", "+$1,600 from
$58,000", and "the extra $1,600 only offsets income tax the current credit
leaves unpaid". Each is checked exhaustively over the 601 computed points.
"""

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

KIDS = 2


def arrays(sweep):
    e = np.array(sweep["earnings"])
    g = np.array(sweep["gain"])
    tl = np.array(sweep["tax_liability"])
    return e, g, tl


def test_gain_is_bounded_by_the_credit_increase(sweep):
    p = sweep["meta"]["parameters_2026"]
    _, g, _ = arrays(sweep)
    max_increase = KIDS * (3000 - p["ctc_amount"])
    assert g.min() >= 0 and g.max() <= max_increase + 0.01


def test_gain_is_income_tax_the_current_credit_leaves_unpaid(sweep):
    """Accounting identity: gain = min(max(liability - nonrefundable share of today's credit, 0), increase)."""
    p = sweep["meta"]["parameters_2026"]
    _, g, tl = arrays(sweep)
    nonrefundable_now = KIDS * (p["ctc_amount"] - p["refundable_individual_max"])  # $1,000
    increase = KIDS * (3000 - p["ctc_amount"])  # $1,600
    expected = np.minimum(np.maximum(tl - nonrefundable_now, 0), increase)
    assert np.abs(g - expected).max() < 0.01


def test_gain_never_falls_as_earnings_rise_below_150k(sweep):
    """Intended monotonicity on the plotted range; the phase-out starts at $400,000."""
    _, g, _ = arrays(sweep)
    assert (np.diff(g) >= -0.01).all()


def test_net_income_change_is_all_child_tax_credit(sweep):
    """Differential: nothing but the CTC moves for this family."""
    _, g, _ = arrays(sweep)
    d_ctc = np.array(sweep["ctc_value_reform"]) - np.array(sweep["ctc_value_baseline"])
    assert np.abs(g - d_ctc).max() < 0.01


def test_refundable_part_never_exceeds_the_cap(sweep):
    p = sweep["meta"]["parameters_2026"]
    cap = KIDS * p["refundable_individual_max"]
    for key in ("refundable_ctc_baseline", "refundable_ctc_reform"):
        assert max(sweep[key]) <= cap + 0.01


def test_on_screen_statements_hold_at_every_point(sweep, video):
    e, g, _ = arrays(sweep)
    curve = video["household"]["curve"]
    below = int(curve["lines"][0].split("$")[2].split(" ")[0].replace(",", ""))
    from_ = int(curve["lines"][1].rstrip(".").split("$")[2].replace(",", ""))
    assert (below, from_) == (42_200, 58_000)
    assert (g[e < below] == 0).all()
    assert (np.abs(g[(e >= from_) & (e <= curve["xMax"])] - 1600) < 0.01).all()
    assert sweep["gain_starts_at_earnings"] >= below  # nothing gained before the stated threshold
    assert sweep["full_gain_from_earnings"] <= from_


def test_plotted_points_are_the_computed_points(sweep, video):
    """Differential: the page draws exactly the sweep, nothing smoothed or invented."""
    curve = video["household"]["curve"]
    computed = {e: g for e, g in zip(sweep["earnings"], sweep["gain"]) if e <= curve["xMax"]}
    assert dict(map(tuple, curve["points"])) == computed
    assert computed[curve["pin"][0]] == curve["pin"][1] == 780


def test_matches_the_single_household_run(sweep):
    """Differential: the sweep at $60,000 equals the separate household.json computation."""
    from conftest import load

    hh = load("household.json")
    net = {k["variable"]: k for k in hh["key_numbers"]}["household_net_income"]
    i = sweep["earnings"].index(60_000.0)
    assert abs(sweep["gain"][i] - (net["reform"] - net["baseline"])) < 0.01


@pytest.mark.slow
@settings(max_examples=6, deadline=None)
@given(st.integers(min_value=0, max_value=600).map(lambda k: k * 250))
def test_policyengine_py_agrees_with_the_sweep(sweep, earnings):
    """Differential against the policyengine.py household calculator at random grid points."""
    pe = pytest.importorskip("policyengine")
    from conftest import load

    meta = load("household.json")["meta"]
    hd = meta["household_definition"]
    people = [{k: v for k, v in p.items()} for p in hd["people"]]
    head = next(p for p in people if p.get("is_tax_unit_head"))
    head["employment_income"] = earnings
    reform = meta["reform_dict_passed"]
    kw = dict(people=people, tax_unit={"filing_status": hd["filing_status"]}, household={"state_code": hd["state_code"]},
              year=meta["year"], spm={"geography_kind": "national"})
    base = pe.us.calculate_household(**kw).household["household_net_income"]
    ref = pe.us.calculate_household(**kw, reform=reform).household["household_net_income"]
    i = sweep["earnings"].index(float(earnings))
    assert abs((ref - base) - sweep["gain"][i]) < 1.0
