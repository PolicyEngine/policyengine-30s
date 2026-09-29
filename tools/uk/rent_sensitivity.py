"""How the UK family's curve depends on the illustrative £500 a month rent.

The rent is an input, not a sourced figure (data/uk/README.md, "Not verified"). This
reruns the family at £400, £500 and £600 a month on a £10 grid from £0 to £80,000
and records where Universal Credit ends and which flat stretches exist. At £500
the £10 grid must reproduce the £1 facts in data/uk/earnings_sweep.json, which
makes this a differential check on the main sweep as well.

Household runs only: no dataset is loaded (see uk_family.no_microdata).

Run from the repo root:
  uv run --no-project --python 3.13 --with-requirements tools/uk/requirements.pe-6.2.0.lock.txt \
      python tools/uk/rent_sensitivity.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

from uk_family import REFORM, RENT_PER_MONTH, YEAR, assert_no_microdata, no_microdata, situation, versions  # noqa: E402

X_MAX, STEP = 80_000, 10
RENTS = (400, 500, 600)
TOL = 0.005


def stretches(e, g, level):
    """Maximal runs of grid points where the gain equals level (to the penny)."""
    out, start = [], None
    for x, y in zip(e, g):
        if abs(y - level) < TOL:
            start = x if start is None else start
            end = x
        elif start is not None:
            out.append([start, end]); start = None
    if start is not None:
        out.append([start, end])
    return out


def case(rent):
    import numpy as np
    from policyengine_uk import Simulation

    sit = situation(0, X_MAX, X_MAX // STEP + 1, rent_per_month=rent)
    base = Simulation(situation=copy.deepcopy(sit))
    ref = Simulation(situation=copy.deepcopy(sit), reform=copy.deepcopy(REFORM))
    calc = lambda sim, v: np.asarray(sim.calculate(v, YEAR, map_to="household"), dtype=float)
    e = calc(base, "employment_income")
    assert len(e) == X_MAX // STEP + 1 and abs(e[1] - e[0] - STEP) < 1e-6
    g = calc(ref, "hbai_household_net_income") - calc(base, "hbai_household_net_income")
    ub, ur = calc(base, "universal_credit"), calc(ref, "universal_credit")
    last = lambda a: float(e[np.flatnonzero(a > TOL)[-1]]) if (a > TOL).any() else None
    return {
        "rent_per_month": rent,
        "baseline_uc_last_positive_at": last(ub),
        "reform_uc_last_positive_at": last(ur),
        "gain_218_70_stretches": stretches(e, g, 218.70),
        "gain_486_stretches": stretches(e, g, 486.0),
        "gain_972_stretches": stretches(e, g, 972.0),
        "gain_at": {str(x): round(float(g[x // STEP]), 2) for x in (10_000, 30_000, 49_000, 60_000, 80_000)},
    }


def main():
    home = no_microdata()
    cases = {str(r): case(r) for r in RENTS}
    assert_no_microdata(home)

    # at the video's rent the £10 grid lands on the £1 facts of the main sweep
    fine = json.loads((ROOT / "data" / "uk" / "earnings_sweep.json").read_text())["fine"]
    c = cases[str(RENT_PER_MONTH)]
    down10 = lambda x: float(int(x) // STEP * STEP)
    assert c["baseline_uc_last_positive_at"] == down10(fine["baseline_uc_last_positive_at"]), c
    assert c["reform_uc_last_positive_at"] == down10(fine["reform_uc_last_positive_at"]), c
    assert any(lo <= fine["plateau_off_uc"]["from"] + STEP and hi == fine["plateau_off_uc"]["to"]
               for lo, hi in c["gain_486_stretches"]), c["gain_486_stretches"]

    out = {
        "meta": {
            "script": "tools/uk/rent_sensitivity.py",
            "grid": f"every £{STEP} from £0 to £{X_MAX:,}",
            "versions": versions(),
            "reform": REFORM,
            "note": "only the rent differs from data/uk/earnings_sweep.json's family",
        },
        "cases": cases,
    }
    path = ROOT / "data" / "uk" / "compute" / "rent_sensitivity.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
