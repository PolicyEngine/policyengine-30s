"""Every number and quoted string in data/video.json traces to its source."""

import re

import yaml
from hypothesis import given
from hypothesis import strategies as st

from adapt_outputs import geoid4
from conftest import ROOT, load


def test_no_mock_data(video):
    assert video["mock"] is False and "mock_parts" not in video


def test_stats_are_the_national_run_at_stated_precision(video, national):
    stats = {s["kind"]: s for s in video["nation"]["stats"]}
    cost = -national["budget"]["federal_income_tax_revenue_change"] / 1e9
    share = 100 * national["winners"]["share_households_gaining_over_1usd"]
    kids = national["poverty"]["spm"]["children_under_18"]["children_lifted_out"]
    assert stats["billion"]["value"] == round(cost) == 31
    assert stats["pct"]["value"] == round(share, 1) == 19.2
    assert stats["count"]["value"] == round(kids, -2) == 189_300


def test_decile_bars_are_the_national_deciles(video, national):
    dec = sorted(national["deciles"]["by_decile"], key=lambda r: r["decile"])
    assert video["deciles"]["avg"] == [round(r["average_change_household_net_income"]) for r in dec]


def test_nobody_loses_in_the_national_run(national):
    """Intended property of a pure credit increase (float32 noise below $0.01 is tolerated)."""
    assert national["winners"]["share_households_losing_over_1usd"] == 0


def test_quote_and_statute_are_verbatim(video):
    st_ = load("statute.json")
    assert video["quote"]["text"].strip("…") in st_["federalist_quote"]
    wall, off, h2 = st_["wall_text"], st_["wall_h2_offset"], st_["h2_text"]
    assert wall[off : off + len(h2)] == h2 and '"$2,200"' in h2
    assert len(wall.split()) == 2686
    # what the page shows is the source text
    s = video["statute"]
    assert s["wall"] == wall and s["h2"] == h2 and s["amount"] in s["h2"]


def test_code_panel_is_the_parameter_file(video):
    lines = (ROOT / "data" / "base.yaml").read_text().splitlines()
    code = video["code"]
    assert code["lines"] == lines[code["first"] - 1 : code["first"] - 1 + len(code["lines"])]
    assert lines[code["valueLine"] - 1].strip() == "2025-01-01: 2_200"
    assert "§ 24(h)(2)" in lines[code["refLine"] - 1]
    assert yaml.safe_load("\n".join(lines))["metadata"]["label"] == code["label"]


def test_reform_card_is_what_policyengine_received(video):
    meta = load("household.json")["meta"]
    r = video["reform"]
    assert r["dict"] == meta["reform_dict_passed"]
    ((path, periods),) = r["dict"].items()
    assert path == r["path"] == meta["reform"]["parameter"]
    assert periods == {f"{r['year']}-01-01.{r['year']}-12-31": r["to"]}
    # "$2,200 -> $3,000": the baseline is what the model read, in every run that fed the video
    sweep = load("earnings_sweep.json")["meta"]
    assert r["from"] == meta["reform"]["baseline_value_2026"] == sweep["parameters_2026"]["ctc_amount"] == 2200
    assert r["to"] == meta["reform"]["reform_value"] == 3000


def test_provenance_names_the_versions_that_ran(video, national):
    v = national["meta"]["versions"]
    assert f"policyengine.py {v['policyengine']}" in video["provenance"][0]
    assert f"policyengine-us {v['policyengine-us']}" in video["provenance"][0]
    smp = load("households_sample.json")["meta"]
    assert f"{smp['n_draws']:,} weighted draws of {smp['unique_households_drawn']:,}" in video["provenance"][2]


def test_sample_dots_have_valid_geography(video):
    shapes = {d["geoid"] for d in video["cdGeo"]}
    assert len(video["sample"]) == 12_000
    for fips, gain, cd, dec in video["sample"]:
        assert cd in shapes and int(cd) // 100 == fips
        assert -1 <= dec <= 10 and gain > -0.01


@given(st.integers(min_value=100, max_value=5699))
def test_geoid_keys_round_trip(g):
    s = geoid4(g)
    assert len(s) == 4 and int(s) == g


def test_family_text_states_exactly_the_computed_figures(video):
    """Every dollar figure in the family scene's text, in order, derived from the model outputs."""
    sweep = load("earnings_sweep.json")
    p = sweep["meta"]["parameters_2026"]
    below = int(sweep["gain_starts_at_earnings"] // 100 * 100)        # $42,206 computed -> "$42,200"
    from_ = int(-(-sweep["full_gain_from_earnings"] // 100) * 100)    # $57,996 computed -> "$58,000"
    full = round(max(sweep["gain"]))                                  # 1,600
    text = " ".join(video["household"]["curve"]["lines"]) + " " + video["household"]["curve"]["note"]
    shown = [int(m.replace(",", "")) for m in re.findall(r"\$([\d,]+)", text)]
    assert shown == [0, below, full, from_, round(p["refundable_individual_max"]), full]
