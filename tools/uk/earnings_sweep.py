"""The UK family's change in net income across earnings, baseline vs the personal allowance reform.

One policyengine_uk.Simulation per run, with an axis on the parent's
employment_income, computes every earnings point at once. Two grids:
  * £250 steps from £0 to £80,000 (321 points): the plotted curve, written in full;
  * £1 steps from £0 to £80,000 (80,001 points): where each flat stretch starts and
    ends and where Universal Credit runs out, to the pound. Every on-screen sentence
    about the curve is asserted at all 80,001 points (tools/uk/curve_claims.py).

The change in hbai_household_net_income is decomposed exactly into the variables
policyengine-uk itself adds and subtracts for it, and the decomposition is asserted.

Household runs only: no dataset is loaded (see uk_family.no_microdata).

Run from the repo root, once per environment (the second is the previous pin, a differential):
  uv run --no-project --python 3.13 --with-requirements tools/uk/requirements.pe-6.2.0.lock.txt \
      python tools/uk/earnings_sweep.py --out data/uk/earnings_sweep.json
  uv run --no-project --python 3.13 --with-requirements tools/uk/requirements.pe-6.1.1.lock.txt \
      python tools/uk/earnings_sweep.py --out data/uk/compute/earnings_sweep_pe-6.1.1.json
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import platform
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

import curve_claims  # noqa: E402
from uk_family import (  # noqa: E402
    BENUNIT, CHILDREN, ADULT, FAMILY_LABEL, FISCAL_YEAR, HOUSEHOLD, PA_PATH, RECORD, REFORM,
    RENT_PER_MONTH, YEAR, assert_no_microdata, no_microdata, situation, versions,
)

X_MAX = 80_000
STEP = 250
PIN = 30_000


def run(sit_kwargs):
    import numpy as np
    from policyengine_uk import Simulation
    from policyengine_uk.variables.household.income.hbai_household_net_income import (
        HBAI_HOUSEHOLD_NET_INCOME_ADDS as ADDS,
        HBAI_HOUSEHOLD_NET_INCOME_SUBTRACTS as SUBS,
    )

    sit = situation(**sit_kwargs)
    base = Simulation(situation=copy.deepcopy(sit))
    ref = Simulation(situation=copy.deepcopy(sit), reform=copy.deepcopy(REFORM))
    known = base.tax_benefit_system.variables
    names = [v for v in dict.fromkeys(RECORD + list(ADDS) + list(SUBS)) if v in known]

    def calc(sim):
        out = {}
        for v in names:
            a = np.asarray(sim.calculate(v, YEAR, map_to="household"))
            out[v] = (a.astype(float) if a.dtype != bool else a.astype(float))
        return out

    b, r = calc(base), calc(ref)
    d = {v: r[v] - b[v] for v in names}
    adds = [a for a in ADDS if a in known]
    subs = [s for s in SUBS if s in known]
    recomposed = sum(d[a] for a in adds) - sum(d[s] for s in subs)
    gap = float(np.max(np.abs(recomposed - d["hbai_household_net_income"])))
    assert gap < 0.05, f"net income change does not decompose: gap {gap}"
    moved = sorted(v for v in adds + subs if np.max(np.abs(d[v])) > 0.005)
    # the parameter the model read for 2026 (= 2026-27): the reform must actually have moved it
    p0 = base.tax_benefit_system.parameters(YEAR)
    p1 = ref.tax_benefit_system.parameters(YEAR)
    pa0 = float(p0.gov.hmrc.income_tax.allowances.personal_allowance.amount)
    pa1 = float(p1.gov.hmrc.income_tax.allowances.personal_allowance.amount)
    ((_, periods),) = REFORM.items()
    ((_, new_value),) = periods.items()
    assert pa1 == new_value and pa0 != pa1, f"reform did not reach the 2026 parameter: {pa0} -> {pa1}"
    uk = p0.gov.hmrc.income_tax.rates.uk
    params = {
        "personal_allowance_baseline": pa0,
        "personal_allowance_reform": pa1,
        "uc_reduction_rate": float(p0.gov.dwp.universal_credit.means_test.reduction_rate),
        "uc_reduction_rate_reform_run": float(p1.gov.dwp.universal_credit.means_test.reduction_rate),
        "income_tax_rates_uk": [float(x) for x in uk.rates],
        "income_tax_thresholds_uk_above_allowance": [float(x) for x in uk.thresholds],
    }
    return b["employment_income"], b, r, d, moved, gap, params


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    t0 = time.time()
    home = no_microdata()
    import numpy as np

    # ---- £1 grid: exact thresholds, and every on-screen sentence checked at every pound
    E1, b1, r1, d1, moved1, gap1, params = run(dict(earnings_min=0, earnings_max=X_MAX, count=X_MAX + 1))
    assert np.array_equal(E1, np.arange(X_MAX + 1, dtype=float)), "£1 grid is not every pound"
    L = lambda a: [float(x) for x in a]
    E1l = L(E1)
    G1 = L(d1["hbai_household_net_income"])
    UC0, UC1 = L(b1["universal_credit"]), L(r1["universal_credit"])
    CUT = L(-d1["income_tax"])
    DUC, DNI, DUCE = L(d1["universal_credit"]), L(d1["national_insurance"]), L(d1["uc_earned_income"])
    fine = curve_claims.facts(E1l, G1, UC0, UC1, CUT, PIN)
    stm = curve_claims.statements(fine, params["uc_reduction_rate"])
    checked_fine = curve_claims.check(E1l, G1, UC0, UC1, CUT, DUC, DNI, DUCE, stm, fine["pin"])
    # the plateau levels follow from the parameters the model read, not only from the data
    band_cut = params["income_tax_rates_uk"][0] * (params["personal_allowance_reform"] - params["personal_allowance_baseline"])
    assert abs(fine["plateau_off_uc"]["gain"] - band_cut) < 0.02, (fine["plateau_off_uc"], band_cut)
    assert abs(fine["plateau_on_uc"]["gain"] - (1 - params["uc_reduction_rate"]) * band_cut) < 0.02
    assert abs(fine["plateau_top"]["gain"] - params["income_tax_rates_uk"][1] * (params["personal_allowance_reform"] - params["personal_allowance_baseline"])) < 0.02
    fine_summary = {
        "grid": f"every £1 from £0 to £{X_MAX:,} ({X_MAX + 1:,} points)",
        **fine,
        "net_income_components_that_moved": moved1,
        "decomposition_max_abs_gap": gap1,
        "on_screen": {"lines": stm["lines"], "note": stm["note"], "claims": stm["claims"]},
        "points_checked": checked_fine,
        "tax_cut_on_the_basic_rate_band": round(band_cut, 2),
    }
    del E1, b1, r1, d1

    # ---- £250 grid: the plotted curve
    n = X_MAX // STEP + 1
    E, b, r, d, moved, gap, params250 = run(dict(earnings_min=0, earnings_max=X_MAX, count=n))
    assert params250 == params
    El = L(E)
    assert El == [float(STEP * i) for i in range(n)]
    G = L(d["hbai_household_net_income"])
    # the £250 grid is a subset of the £1 grid: identical values there (two runs, same model)
    for e, g in zip(El, G):
        assert abs(g - G1[int(e)]) < 0.01, (e, g, G1[int(e)])
    checked = curve_claims.check(El, G, L(b["universal_credit"]), L(r["universal_credit"]), L(-d["income_tax"]),
                                 L(d["universal_credit"]), L(d["national_insurance"]), L(d["uc_earned_income"]),
                                 stm, fine["pin"])
    assert_no_microdata(home)
    import hashlib
    import policyengine_uk
    pfile = Path(policyengine_uk.__file__).parent / "parameters/gov/hmrc/income_tax/allowances/personal_allowance/amount.yaml"
    param_file_sha256 = hashlib.sha256(pfile.read_bytes()).hexdigest()
    R = lambda a: [round(float(x), 2) for x in a]
    keep = ["hbai_household_net_income", "income_tax", "national_insurance", "universal_credit", "uc_earned_income",
            "uc_income_reduction", "uc_maximum_amount", "child_benefit", "CB_HITC", "benefit_cap_reduction",
            "marriage_allowance"]
    out = {
        "meta": {
            "what": FAMILY_LABEL,
            "family_inputs": {"people": [ADULT] + CHILDREN, "benunit": BENUNIT, "household": HOUSEHOLD,
                              "rent_per_month": RENT_PER_MONTH},
            "reform_dict_passed": REFORM,
            "reform_parameter": PA_PATH,
            "period": YEAR,
            "fiscal_year": FISCAL_YEAR,
            "year_convention": "policyengine-uk reads a bare year as the fiscal year starting in April of it (2026 = 2026-27)",
            "net_income_variable": "hbai_household_net_income",
            "engine": "policyengine_uk.Simulation(situation=..., reform=...) with one axis on the parent's employment_income",
            "versions": versions(),
            "python": platform.python_version(),
            "parameters_2026": params,
            "personal_allowance_yaml_sha256_in_installed_package": param_file_sha256,
            "grid": {"min": 0, "max": X_MAX, "step": STEP, "points": n},
            "microdata": "none: household situations only; HF cache pointed at an empty temp dir, hub offline, tokens unset, cache still empty after the run",
            "computed_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "seconds": round(time.time() - t0, 1),
            "script": "tools/uk/earnings_sweep.py",
        },
        "earnings": El,
        "gain": R(d["hbai_household_net_income"]),
        "baseline": {k: R(b[k]) for k in keep},
        "reform": {k: R(r[k]) for k in keep},
        "change": {k: R(d[k]) for k in keep},
        "net_income_components_that_moved": moved,
        "decomposition_max_abs_gap": gap,
        "points_checked_on_this_grid": checked,
        "fine": fine_summary,
    }
    p = ROOT / args.out
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"wrote {p.relative_to(ROOT)}  versions={out['meta']['versions']}  {out['meta']['seconds']}s")
    print(json.dumps(fine_summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
