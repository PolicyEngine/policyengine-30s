"""The family curve through policyengine.py, at every plotted point.

earnings_sweep.py computes the curve with policyengine_us.Simulation axes and
spot-checks policyengine.py's household calculator at 7 earnings levels. The
video's tag on that chart names policyengine.py, so this runs the whole $250
grid (601 points, $0 to $150,000) through pe.us.calculate_household with an
earnings axis, baseline and reform, and asserts the change in net income
matches the sweep at every point.

Run: ../.venv/bin/python curve_policyengine_py.py   (from this directory)
Writes: checks/curve_policyengine_py.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, YEAR, Timer, package_versions, write_json  # noqa: E402

timer = Timer()
import policyengine as pe  # noqa: E402

TOL = 0.01  # dollars

sweep = json.loads((DATA_DIR / "earnings_sweep.json").read_text())
meta = json.loads((DATA_DIR / "household.json").read_text())["meta"]
hd = meta["household_definition"]
E = sweep["earnings"]
assert E[0] == 0 and E[-1] == 150_000 and len(E) == 601

people = [dict(p) for p in hd["people"]]
assert people[0].get("is_tax_unit_head"), "the axis runs over person 0, which must be the earner"
people[0]["employment_income"] = 0
axes = [[{"name": "employment_income", "min": E[0], "max": E[-1], "count": len(E)}]]
kw = dict(people=people, tax_unit={"filing_status": hd["filing_status"]}, household={"state_code": hd["state_code"]},
          year=meta["year"], spm={"geography_kind": "national"}, axes=axes)
assert meta["year"] == YEAR

net = {}
for label, reform in (("baseline", None), ("reform", meta["reform_dict_passed"])):
    r = pe.us.calculate_household(**kw, reform=reform)
    net[label] = [float(x) for x in r.household["household_net_income"]]
    assert len(net[label]) == len(E), (label, len(net[label]))
timer.lap("calculate_household")

gain = [b - a for a, b in zip(net["baseline"], net["reform"])]
diff = [abs(g - s) for g, s in zip(gain, sweep["gain"])]
worst = max(diff)
assert worst < TOL, f"policyengine.py differs from the sweep by ${worst:.4f}"

out = {
    "description": "policyengine.py pe.us.calculate_household with an earnings axis, at every point of earnings_sweep.json",
    "points": len(E),
    "tolerance_dollars": TOL,
    "max_abs_diff_dollars": worst,
    "versions": package_versions(),
    "sweep_versions": sweep["meta"]["versions"],
    "runtime": timer.summary(),
}
write_json(Path(__file__).resolve().parent / "checks" / "curve_policyengine_py.json", out)
print(json.dumps({k: v for k, v in out.items() if k != "versions"}, indent=1))
