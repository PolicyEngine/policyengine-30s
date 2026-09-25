"""The same Ohio family across earnings: how much does the $3,000 CTC reform add?

Sweeps the head's employment income for the household in household.py
(Ohio, married filing jointly, adults 35 and 34, children 4 and 8, 2026),
baseline vs reform, with policyengine_us.Simulation axes. Records the net
income change and the CTC pieces that explain it (credit allowed, the part
that offsets tax, the refundable part and its caps).

Cross-check: policyengine.py pe.us.calculate_household at spot earnings must
match the sweep to the cent-level tolerance below.

Run: ../.venv/bin/python earnings_sweep.py   (from this directory)
Writes: ../earnings_sweep.json
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DATA_DIR,
    REFORM_PARAMETER,
    REFORM_START,
    REFORM_STOP,
    REFORM_VALUE,
    YEAR,
    Timer,
    package_versions,
    reform_description,
    write_json,
)

timer = Timer()
import policyengine as pe  # noqa: E402
from policyengine.tax_benefit_models.us.spm import resolve_spm_selection  # noqa: E402
from policyengine_us import Simulation  # noqa: E402
from policyengine_us.system import system  # noqa: E402

timer.lap("imports")

REFORM = {REFORM_PARAMETER: {f"{REFORM_START}.{REFORM_STOP}": REFORM_VALUE}}
SPM = {"geography_kind": "national"}  # same choice as household.py
y = str(YEAR)

VARS = [
    "household_net_income",
    "ctc",
    "ctc_value",
    "non_refundable_ctc",
    "refundable_ctc",
    "ctc_refundable_maximum",
    "ctc_phase_in",
    "ctc_limiting_tax_liability",
    "income_tax_before_credits",
    "income_tax",
    "eitc",
    "state_income_tax",
    "household_benefits",
    "employee_payroll_tax",
]


def situation(axes=None, earnings=0.0):
    s = {
        "people": {
            "head": {"age": {y: 35}, "employment_income": {y: earnings}, "is_tax_unit_head": {y: True}},
            "spouse": {"age": {y: 34}, "employment_income": {y: 0}, "is_tax_unit_spouse": {y: True}},
            "child_4": {"age": {y: 4}, "is_tax_unit_dependent": {y: True}},
            "child_8": {"age": {y: 8}, "is_tax_unit_dependent": {y: True}},
        },
        "tax_units": {"tu": {"members": ["head", "spouse", "child_4", "child_8"], "filing_status": {y: "JOINT"}}},
        "marital_units": {"mu": {"members": ["head", "spouse"]}},
        "families": {"fam": {"members": ["head", "spouse", "child_4", "child_8"]}},
        "spm_units": {"spm": {"members": ["head", "spouse", "child_4", "child_8"]}},
        "households": {"hh": {"members": ["head", "spouse", "child_4", "child_8"], "state_code": {y: "OH"}}},
    }
    if axes:
        s["axes"] = [[{"name": "employment_income", "index": 0, "period": YEAR, **axes}]]
    return s


def sweep(lo, hi, count):
    out = {}
    for label, reform in (("baseline", None), ("reform", REFORM)):
        sim = Simulation(situation=situation({"min": lo, "max": hi, "count": count}), reform=reform,
                         spm=resolve_spm_selection(SPM))
        earn = sim.calculate("employment_income", YEAR, map_to="household")
        out["earnings"] = np.asarray(earn, dtype=float)
        out[label] = {v: np.asarray(sim.calculate(v, YEAR, map_to="household"), dtype=float) for v in VARS}
    return out


# main grid: $0 to $150,000 every $250
main = sweep(0, 150_000, 601)
timer.lap("sweep_main")
earn = main["earnings"]
gain = main["reform"]["household_net_income"] - main["baseline"]["household_net_income"]
assert np.allclose(np.diff(earn), 250), "grid is not $250 steps"

# where gains start: refine between the last $0 point and the first gaining point
first = int(np.argmax(gain > 0.5))
fine = sweep(earn[first - 1], earn[first], 251)  # $1 steps
fgain = fine["reform"]["household_net_income"] - fine["baseline"]["household_net_income"]
threshold = float(fine["earnings"][int(np.argmax(fgain > 0.5))])
# where the full $1,600 is first reached
full_i = int(np.argmax(gain >= 1600 - 0.5))
fine2 = sweep(earn[full_i - 1], earn[full_i], 251)
f2gain = fine2["reform"]["household_net_income"] - fine2["baseline"]["household_net_income"]
full_at = float(fine2["earnings"][int(np.argmax(f2gain >= 1600 - 0.5))])
timer.lap("thresholds")

# wide grid: to $600,000 every $1,000, to document the top end (phase-out)
wide = sweep(0, 600_000, 601)
wgain = wide["reform"]["household_net_income"] - wide["baseline"]["household_net_income"]
timer.lap("sweep_wide")

# cross-check against the policyengine.py household calculator
checks = []
for e in (20_000, 30_000, 40_000, 45_000, 50_000, 60_000, 100_000):
    res = []
    for reform in (None, REFORM):
        r = pe.us.calculate_household(
            people=[
                {"age": 35, "employment_income": e, "is_tax_unit_head": True},
                {"age": 34, "employment_income": 0, "is_tax_unit_spouse": True},
                {"age": 4, "is_tax_unit_dependent": True},
                {"age": 8, "is_tax_unit_dependent": True},
            ],
            tax_unit={"filing_status": "JOINT"},
            household={"state_code": "OH"},
            year=YEAR,
            reform=reform,
            spm=SPM,
        )
        res.append(float(r.household["household_net_income"]))
    i = int(np.argmin(np.abs(earn - e)))
    sweep_gain = float(gain[i])
    checks.append({"earnings": e, "pe_py_gain": res[1] - res[0], "sweep_gain": sweep_gain,
                   "match": abs((res[1] - res[0]) - sweep_gain) < 1.0})
assert all(c["match"] for c in checks), checks
timer.lap("cross_check")


def pick(i, src=main):
    b, r = src["baseline"], src["reform"]
    return {
        "earnings": float(src["earnings"][i]),
        "gain": float(r["household_net_income"][i] - b["household_net_income"][i]),
        **{f"{v}_baseline": round(float(b[v][i]), 2) for v in VARS},
        **{f"{v}_reform": round(float(r[v][i]), 2) for v in VARS},
    }


spots = {e: pick(int(np.argmin(np.abs(earn - e)))) for e in (0, 20_000, 30_000, 40_000, 50_000, 60_000, 100_000)}
params = system.parameters(f"{YEAR}-01-01").gov.irs.credits.ctc
top_end = [float(x) for x in wide["earnings"][(wgain < 1600 - 0.5) & (wide["earnings"] > 100_000)][:1]]

write_json(
    DATA_DIR / "earnings_sweep.json",
    {
        "meta": {
            "description": "Ohio MFJ, children 4 and 8, 2026: household_net_income change from the $3,000 CTC reform, by the head's employment income.",
            "reform": reform_description(),
            "method": "policyengine_us.Simulation with axes over person 0 employment_income; cross-checked against policyengine.py pe.us.calculate_household",
            "spm": SPM,
            "versions": package_versions(),
            "parameters_2026": {
                "ctc_amount": float(system.parameters.get_child(REFORM_PARAMETER)(f"{YEAR}-01-01")),
                "refundable_individual_max": float(params.refundable.individual_max),
                "phase_in_rate": float(params.refundable.phase_in.rate),
                "phase_in_threshold": float(params.refundable.phase_in.threshold),
            },
            "runtime": timer.laps,
            "script": "compute/earnings_sweep.py",
        },
        "grid": {"min": 0, "max": 150_000, "step": 250},
        "earnings": [float(x) for x in earn],
        "gain": [round(float(x), 2) for x in gain],
        "ctc_value_baseline": [round(float(x), 2) for x in main["baseline"]["ctc_value"]],
        "ctc_value_reform": [round(float(x), 2) for x in main["reform"]["ctc_value"]],
        "refundable_ctc_baseline": [round(float(x), 2) for x in main["baseline"]["refundable_ctc"]],
        "refundable_ctc_reform": [round(float(x), 2) for x in main["reform"]["refundable_ctc"]],
        "tax_liability": [round(float(x), 2) for x in main["baseline"]["ctc_limiting_tax_liability"]],
        "gain_starts_at_earnings": threshold,
        "full_gain_from_earnings": full_at,
        "gain_first_below_full_above_100k": top_end[0] if top_end else None,
        "max_gain": float(gain.max()),
        "spots": spots,
        "cross_check_policyengine_py": checks,
    },
)
print(f"gain starts at ${threshold:,.0f}; full $1,600 from ${full_at:,.0f}; drops below $1,600 at {top_end}")
for e, s in spots.items():
    print(f"  ${e:>7,}: gain {s['gain']:>8.2f}  ctc {s['ctc_value_baseline']:>7.0f}->{s['ctc_value_reform']:<7.0f} "
          f"refundable {s['refundable_ctc_baseline']:>6.0f}->{s['refundable_ctc_reform']:<6.0f} "
          f"liability {s['ctc_limiting_tax_liability_baseline']:>6.0f} phase-in {s['ctc_phase_in_baseline']:>6.0f}")
