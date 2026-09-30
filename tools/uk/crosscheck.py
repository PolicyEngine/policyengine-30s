"""Differential check of the UK family curve through policyengine.py's household calculator.

The sweep (tools/uk/earnings_sweep.py) calls policyengine_uk.Simulation directly.
This script computes the same family through policyengine.py's
pe.uk.calculate_household, passing the identical reform dict, two ways:
  * with an earnings axis over the whole £250 grid (every plotted point), and
  * one household at a time, at the breakpoints the on-screen text relies on plus
    eight seeded random grid points.
It then compares the change in net income, Universal Credit and income tax with
data/uk/earnings_sweep.json, and the breakpoints with the sweep's £1 facts.

Household runs only: no dataset is loaded (see uk_family.no_microdata).

  uv run --no-project --python 3.13 --with-requirements tools/uk/requirements.pe-6.2.0.lock.txt \
      python tools/uk/crosscheck.py
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

from uk_family import BENUNIT, HOUSEHOLD, REFORM, YEAR, assert_no_microdata, no_microdata, pe_py_people, versions  # noqa: E402

TOL = 0.01
VARS = ["hbai_household_net_income", "universal_credit", "income_tax", "national_insurance"]


def main():
    home = no_microdata()
    import policyengine as pe

    sw = json.loads((ROOT / "data/uk/earnings_sweep.json").read_text())
    fine = sw["fine"]
    E = sw["earnings"]
    n = len(E)

    def calc(reform, earnings=None, axes=None):
        r = pe.uk.calculate_household(
            people=pe_py_people(earnings), benunit=dict(BENUNIT), household=dict(HOUSEHOLD), year=YEAR,
            reform=copy.deepcopy(reform) if reform else None, extra_variables=VARS, axes=axes,
        )
        return {
            "hbai_household_net_income": r.household.hbai_household_net_income,
            "universal_credit": r.benunit.universal_credit,
            "income_tax": r.person[0].income_tax,
            "national_insurance": r.person[0].national_insurance,
        }

    # 1) the whole £250 grid through policyengine.py's axes
    axes = [[{"name": "employment_income", "min": E[0], "max": E[-1], "count": n}]]
    b, r = calc(None, axes=axes), calc(REFORM, axes=axes)
    gain = [y - x for x, y in zip(b["hbai_household_net_income"], r["hbai_household_net_income"])]
    worst_axes = {
        "gain": max(abs(g - s) for g, s in zip(gain, sw["gain"])),
        "universal_credit_baseline": max(abs(x - s) for x, s in zip(b["universal_credit"], sw["baseline"]["universal_credit"])),
        "universal_credit_reform": max(abs(x - s) for x, s in zip(r["universal_credit"], sw["reform"]["universal_credit"])),
        "income_tax_baseline": max(abs(x - s) for x, s in zip(b["income_tax"], sw["baseline"]["income_tax"])),
        "income_tax_reform": max(abs(x - s) for x, s in zip(r["income_tax"], sw["reform"]["income_tax"])),
    }
    assert all(v < TOL for v in worst_axes.values()), worst_axes

    # 2) single households at the breakpoints and at seeded random grid points
    breaks = sorted({0, 12_570, 12_571, 15_000, 30_000, 48_000, 48_001, 48_002, 48_676, 48_677, 48_700,
                     50_270, 50_271, 52_699, 52_700, 80_000})
    rnd = random.Random(20260925)
    randoms = sorted(rnd.sample([e for e in E if e not in breaks], 8))
    rows = []
    for e in breaks + randoms:
        x, y = calc(None, earnings=e), calc(REFORM, earnings=e)
        row = {"earnings": e, "gain": round(y["hbai_household_net_income"] - x["hbai_household_net_income"], 4),
               "uc_baseline": round(x["universal_credit"], 2), "uc_reform": round(y["universal_credit"], 2),
               "income_tax_cut": round(x["income_tax"] - y["income_tax"], 2),
               "ni_change": round(y["national_insurance"] - x["national_insurance"], 4)}
        if e in E:  # on the plotted grid: equal to the sweep
            i = E.index(e)
            row["sweep_gain"] = sw["gain"][i]
            assert abs(row["gain"] - sw["gain"][i]) < TOL, row
        for c in fine["on_screen"]["claims"]:  # inside a stated range: equal to the stated amount
            if c["lo"] <= e <= c["hi"]:
                assert abs(row["gain"] - c["gain"]) < 0.02, (row, c)
                row["inside_claim"] = c["text"]
        rows.append(row)
    by = {r_["earnings"]: r_ for r_ in rows}
    # the £1 facts, recomputed one household at a time
    assert by[fine["baseline_uc_last_positive_at"]]["uc_baseline"] > 0 and by[fine["baseline_uc_last_positive_at"] + 1]["uc_baseline"] == 0
    assert by[fine["reform_uc_last_positive_at"]]["uc_reform"] > 0 and by[fine["reform_uc_last_positive_at"] + 1]["uc_reform"] == 0
    assert by[12_570]["gain"] == 0 < by[12_571]["gain"]
    assert abs(by[fine["plateau_on_uc"]["to"]]["gain"] - fine["plateau_on_uc"]["gain"]) < 0.02 < by[fine["plateau_on_uc"]["to"] + 1]["gain"] - fine["plateau_on_uc"]["gain"]
    assert abs(by[fine["plateau_off_uc"]["to"]]["gain"] - fine["plateau_off_uc"]["gain"]) < 0.02 < by[fine["plateau_off_uc"]["to"] + 1]["gain"] - fine["plateau_off_uc"]["gain"]
    assert all(abs(r_["ni_change"]) < 0.01 for r_ in rows)
    assert_no_microdata(home)
    out = {
        "meta": {
            "what": "policyengine.py pe.uk.calculate_household vs the policyengine_uk axes sweep in data/uk/earnings_sweep.json",
            "versions": versions(),
            "reform_dict_passed": REFORM,
            "computed_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "tolerance": TOL,
            "script": "tools/uk/crosscheck.py",
        },
        "axes_path": {"points": n, "max_abs_difference": {k: round(v, 6) for k, v in worst_axes.items()}},
        "single_household_path": {"points": len(rows), "breakpoints": breaks, "seeded_random_grid_points": randoms,
                                  "rows": rows},
    }
    p = ROOT / "data/uk/compute/crosscheck.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"wrote {p.relative_to(ROOT)}")
    print(json.dumps({k: out[k] for k in ("meta", "axes_path")}, indent=1))
    for r_ in rows:
        print(r_)


if __name__ == "__main__":
    main()
