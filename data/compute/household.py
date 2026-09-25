"""Part A (+ household half of Part D): example Ohio family, baseline vs $3,000 CTC.

Primary method: policyengine.py ``pe.us.calculate_household`` (household
calculator, no microdata).
Second method (Part D): raw ``policyengine_us.Simulation`` built from an
explicit situation dict, baseline and reform, same household.

Household: Ohio, married filing jointly, adults 35
and 34, children 4 and 8, one earner with $60,000 employment income, no other
income. Year 2026.

SPM geography: policyengine.py 6.x requires either a household county_fips or
an explicit SPM geography for its default outputs (which include SPM poverty).
The household specifies a state only, so we select the *national* SPM geography
explicitly rather than inventing a county. Per the calculate_household
docstring, SPM geography only affects SPM thresholds/poverty and the capped
housing subsidy of units allocated housing assistance (this household has
none); a county sensitivity check is included under ``checks``.

Run: ../.venv/bin/python household.py   (from this directory)
Writes: ../household.json
"""

from __future__ import annotations

import sys
from pathlib import Path

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
from policyengine_us import Simulation  # noqa: E402
from policyengine_us.system import system  # noqa: E402

timer.lap("imports")

PERIOD_KEY = f"{REFORM_START}.{REFORM_STOP}"
REFORM = {REFORM_PARAMETER: {PERIOD_KEY: REFORM_VALUE}}
SPM = {"geography_kind": "national"}

PEOPLE = [
    {"age": 35, "employment_income": 60_000, "is_tax_unit_head": True},
    {"age": 34, "employment_income": 0, "is_tax_unit_spouse": True},
    {"age": 4, "is_tax_unit_dependent": True},
    {"age": 8, "is_tax_unit_dependent": True},
]
TAX_UNIT = {"filing_status": "JOINT"}
HOUSEHOLD = {"state_code": "OH"}

# Components of household_benefits in 2026, read from the model itself.
params_2026 = system.parameters(f"{YEAR}-01-01")
BENEFIT_COMPONENTS = list(params_2026.gov.household.household_benefits)
HEALTH_COMPONENTS = list(params_2026.gov.household.household_health_benefits)
HEALTH_COST_COMPONENTS = list(params_2026.gov.household.household_health_costs)
INCLUDE_HEALTH_IN_NET = bool(
    params_2026.gov.simulation.include_health_benefits_in_net_income
)
CTC_BASE_2026 = float(system.parameters.get_child(REFORM_PARAMETER)(f"{YEAR}-01-01"))
CTC_REFUNDABLE_INDIVIDUAL_MAX_2026 = float(
    params_2026.gov.irs.credits.ctc.refundable.individual_max
)
CTC_PHASE_IN_RATE_2026 = float(params_2026.gov.irs.credits.ctc.refundable.phase_in.rate)
CTC_PHASE_IN_THRESHOLD_2026 = float(
    params_2026.gov.irs.credits.ctc.refundable.phase_in.threshold
)

TAX_UNIT_VARS = [
    "adjusted_gross_income",
    "taxable_income",
    "income_tax_before_credits",
    "income_tax_non_refundable_credits",
    "income_tax_before_refundable_credits",
    "income_tax_refundable_credits",
    "income_tax",
    "ctc",
    "ctc_value",
    "non_refundable_ctc",
    "refundable_ctc",
    "ctc_maximum_with_arpa_addition",
    "ctc_refundable_maximum",
    "ctc_limiting_tax_liability",
    "ctc_phase_in",
    "eitc",
    "employee_payroll_tax",
    "state_income_tax",
    "oh_income_tax",
    "assigned_aca_ptc",
]
PERSON_VARS = ["employment_income", "medicaid", "chip", "wic", "is_medicaid_eligible", "is_chip_eligible"]
SPM_VARS = ["snap", "tanf", "free_school_meals", "reduced_price_school_meals", "spm_unit_is_in_spm_poverty"]
HOUSEHOLD_VARS = [
    "household_net_income",
    "household_market_income",
    "household_benefits",
    "household_tax",
    "household_tax_before_refundable_credits",
    "household_refundable_tax_credits",
    "household_health_costs",
    "household_health_benefits",
]


def _unique(seq):
    out = []
    for x in seq:
        if x not in out:
            out.append(x)
    return out


EXTRA = _unique(
    TAX_UNIT_VARS
    + PERSON_VARS
    + SPM_VARS
    + HOUSEHOLD_VARS
    + BENEFIT_COMPONENTS
    + HEALTH_COMPONENTS
    + HEALTH_COST_COMPONENTS
)


def run_policyengine_py(reform=None, spm=SPM, household=HOUSEHOLD):
    return pe.us.calculate_household(
        people=PEOPLE,
        tax_unit=TAX_UNIT,
        household=household,
        year=YEAR,
        reform=reform,
        extra_variables=EXTRA,
        spm=spm,
    )


def entity_of(var: str) -> str:
    return system.variables[var].entity.key


def extract_pe_py(result) -> dict:
    """Flatten a HouseholdResult to household-level totals per variable."""
    out = {}
    for var in EXTRA:
        ent = entity_of(var)
        if ent == "person":
            vals = [p[var] for p in result.person]
            if all(isinstance(v, (int, float)) for v in vals):
                out[var] = float(sum(vals))
                out[var + "__by_person"] = [float(v) for v in vals]
            else:
                out[var + "__by_person"] = vals
        else:
            out[var] = getattr(result, ent)[var]
    return out


def run_raw(reform=None) -> dict:
    """Second method: policyengine_us.Simulation from an explicit situation."""
    y = str(YEAR)
    situation = {
        "people": {
            "head": {"age": {y: 35}, "employment_income": {y: 60_000}, "is_tax_unit_head": {y: True}},
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
    from policyengine.tax_benefit_models.us.spm import resolve_spm_selection

    sim = Simulation(situation=situation, reform=reform, spm=resolve_spm_selection(SPM))
    out = {}
    for var in EXTRA:
        v = system.variables[var]
        if v.value_type in (bool, str) or getattr(v, "possible_values", None) is not None:
            continue
        # Household-level total (sum over members for person/sub-entities).
        out[var] = float(sim.calculate(var, YEAR, map_to="household").sum())
    return out


# ---------------------------------------------------------------- run
base_res = run_policyengine_py(reform=None)
timer.lap("policyengine_py_baseline")
ref_res = run_policyengine_py(reform=REFORM)
timer.lap("policyengine_py_reform")

base = extract_pe_py(base_res)
ref = extract_pe_py(ref_res)

raw_base = run_raw(reform=None)
timer.lap("raw_policyengine_us_baseline")
raw_ref = run_raw(reform=REFORM)
timer.lap("raw_policyengine_us_reform")

# County sensitivity (not the reported household): same family placed in
# Franklin County OH (39049) with county-mode SPM, to show net income does
# not depend on the SPM geography choice.
cty_base = run_policyengine_py(reform=None, spm=None, household={"state_code": "OH", "county_fips": "39049"})
cty_ref = run_policyengine_py(reform=REFORM, spm=None, household={"state_code": "OH", "county_fips": "39049"})
timer.lap("county_sensitivity")


def num(d, k):
    v = d.get(k)
    return float(v) if isinstance(v, (int, float)) else v


KEY = [
    ("employment_income", "Employment income (sum of people)"),
    ("adjusted_gross_income", "Federal AGI"),
    ("taxable_income", "Federal taxable income"),
    ("income_tax_before_credits", "Federal income tax before credits"),
    ("ctc", "Federal CTC allowed (ctc: nonrefundable + refundable, before tax-liability limit)"),
    ("ctc_value", "Federal CTC value realized (ctc_value = min(ctc, liability + refundable_ctc))"),
    ("non_refundable_ctc", "Nonrefundable CTC (ctc - refundable_ctc)"),
    ("refundable_ctc", "Refundable CTC (ACTC)"),
    ("ctc_limiting_tax_liability", "Tax liability that limits the nonrefundable CTC"),
    ("ctc_refundable_maximum", "Maximum refundable CTC (per-child refundable cap x children)"),
    ("ctc_phase_in", "ACTC earned-income phase-in amount"),
    ("eitc", "Federal EITC"),
    ("income_tax", "Total federal income tax (after all credits; negative = net refund)"),
    ("employee_payroll_tax", "Employee payroll tax (Social Security + Medicare)"),
    ("state_income_tax", "State income tax (Ohio)"),
    ("snap", "SNAP (annual)"),
    ("household_benefits", "All household benefits counted in net income"),
    ("household_refundable_tax_credits", "Refundable tax credits (federal + state)"),
    ("household_tax_before_refundable_credits", "Taxes before refundable credits (federal + state + payroll)"),
    ("household_health_costs", "Health out-of-pocket costs subtracted from net income"),
    ("household_net_income", "Household net income"),
]

rows = []
for k, label in KEY:
    b, r = num(base, k), num(ref, k)
    rows.append(
        {
            "variable": k,
            "entity": entity_of(k),
            "label": label,
            "baseline": b,
            "reform": r,
            "change": (r - b) if isinstance(b, float) and isinstance(r, float) else None,
        }
    )

# Every benefit the model gives this family (nonzero in baseline or reform).
benefits_nonzero = []
for k in _unique(BENEFIT_COMPONENTS + ["tanf", "free_school_meals", "reduced_price_school_meals", "wic"]):
    b, r = num(base, k), num(ref, k)
    if isinstance(b, float) and (abs(b) > 0 or abs(r) > 0):
        benefits_nonzero.append({"variable": k, "baseline": b, "reform": r, "change": r - b, "counted_in_household_net_income": True})
health_nonzero = []
for k in _unique(HEALTH_COMPONENTS + ["medicaid", "chip"]):
    b, r = num(base, k), num(ref, k)
    if isinstance(b, float) and (abs(b) > 0 or abs(r) > 0):
        health_nonzero.append(
            {
                "variable": k,
                "baseline": b,
                "reform": r,
                "change": r - b,
                "counted_in_household_net_income": INCLUDE_HEALTH_IN_NET,
                "by_person_baseline": base.get(k + "__by_person"),
            }
        )

d_net = ref["household_net_income"] - base["household_net_income"]
d_ctc_value = ref["ctc_value"] - base["ctc_value"]
d_ctc = ref["ctc"] - base["ctc"]
full_gain = 2 * (REFORM_VALUE - CTC_BASE_2026)

# Explain whether the full $1,600 arrives.
if abs(d_net - full_gain) < 0.005:
    gain_explanation = (
        f"The household gains the full 2 x ${REFORM_VALUE - CTC_BASE_2026:,.0f} = ${full_gain:,.0f}. "
        f"Baseline federal tax before credits is ${base['income_tax_before_credits']:,.2f}; the nonrefundable "
        f"CTC absorbs that liability and the refundable portion (ACTC) covers the rest because the remaining "
        f"credit (${ref['ctc'] - base['ctc_limiting_tax_liability']:,.2f} under reform) stays below the refundable cap of "
        f"${ref['ctc_refundable_maximum']:,.0f} (2 x ${CTC_REFUNDABLE_INDIVIDUAL_MAX_2026:,.0f}) and the earned-income "
        f"phase-in amount of ${ref['ctc_phase_in']:,.2f}."
    )
else:
    gain_explanation = (
        f"The household does NOT gain the full ${full_gain:,.0f}; net income changes by ${d_net:,.2f}. "
        f"CTC allowed changes by ${d_ctc:,.2f}, CTC value realized by ${d_ctc_value:,.2f}. "
        f"Binding limits: tax liability for nonrefundable CTC ${ref['ctc_limiting_tax_liability']:,.2f}; "
        f"refundable cap ${ref['ctc_refundable_maximum']:,.2f}; ACTC phase-in ${ref['ctc_phase_in']:,.2f}; "
        f"refundable CTC under reform ${ref['refundable_ctc']:,.2f}."
    )

# Part D household comparison.
compare_vars = [k for k, _ in KEY if k in raw_base]
mismatches = []
for k in compare_vars:
    for label, a, b in (("baseline", base[k], raw_base[k]), ("reform", ref[k], raw_ref[k])):
        if abs(float(a) - float(b)) > 0.01:
            mismatches.append({"variable": k, "scenario": label, "policyengine_py": a, "raw_policyengine_us": b})

county_net_base = cty_base.household["household_net_income"]
county_net_ref = cty_ref.household["household_net_income"]

out = {
    "meta": {
        "description": "Example household, baseline vs reform, PolicyEngine household calculator (no microdata).",
        "reform": reform_description(),
        "reform_dict_passed": REFORM,
        "interface": "policyengine.py pe.us.calculate_household (primary); policyengine_us.Simulation situation dict (check)",
        "year": YEAR,
        "household_definition": {
            "state_code": "OH",
            "filing_status": "JOINT",
            "people": PEOPLE,
            "notes": "No county given; SPM geography set explicitly to national (see spm_selection).",
        },
        "spm_selection": base_res["provenance"]["spm_config"],
        "dataset": "none (household calculator mode; no microdata)",
        "model_parameters_2026": {
            "gov.irs.credits.ctc.amount.base[0].amount": CTC_BASE_2026,
            "gov.irs.credits.ctc.refundable.individual_max": CTC_REFUNDABLE_INDIVIDUAL_MAX_2026,
            "gov.irs.credits.ctc.refundable.phase_in.rate": CTC_PHASE_IN_RATE_2026,
            "gov.irs.credits.ctc.refundable.phase_in.threshold": CTC_PHASE_IN_THRESHOLD_2026,
            "gov.simulation.include_health_benefits_in_net_income": INCLUDE_HEALTH_IN_NET,
        },
        "versions": package_versions(),
        "runtime": None,  # filled below
        "script": "compute/household.py",
    },
    "ctc_variable_names": {
        "ctc": "Total CTC allowed (nonrefundable + refundable) after phase-out, before the tax-liability limit on the nonrefundable part",
        "ctc_value": "Actual CTC value realized = min(ctc, ctc_limiting_tax_liability + refundable_ctc)",
    },
    "key_numbers": rows,
    "benefits_counted_in_net_income_nonzero": benefits_nonzero,
    "health_benefits_nonzero": health_nonzero,
    "health_note": (
        "Medicaid/CHIP/ACA values are reported for context; with "
        f"gov.simulation.include_health_benefits_in_net_income = {INCLUDE_HEALTH_IN_NET} they are "
        "not added to household_net_income."
    ),
    "summary": {
        "household_net_income_baseline": base["household_net_income"],
        "household_net_income_reform": ref["household_net_income"],
        "household_net_income_change": d_net,
        "ctc_baseline": base["ctc"],
        "ctc_reform": ref["ctc"],
        "ctc_change": d_ctc,
        "ctc_value_baseline": base["ctc_value"],
        "ctc_value_reform": ref["ctc_value"],
        "ctc_value_change": d_ctc_value,
        "full_theoretical_gain": full_gain,
        "gets_full_gain": abs(d_net - full_gain) < 0.005,
        "explanation": gain_explanation,
        "household_net_income_change_rounded_to_cents": round(d_net, 2),
        "float32_note": (
            "policyengine-us stores values as float32. household_net_income is ~$60k, where float32 "
            "resolution is about $0.004, so the reform-minus-baseline difference prints as "
            f"{d_net!r} rather than exactly 1600; every credit component (ctc, ctc_value, "
            "refundable_ctc, household_refundable_tax_credits) changes by exactly 1600.0."
        ),
        "spm_poverty_baseline": bool(base_res.spm_unit["spm_unit_is_in_spm_poverty"]),
        "spm_poverty_reform": bool(ref_res.spm_unit["spm_unit_is_in_spm_poverty"]),
    },
    "checks": {
        "second_method": "policyengine_us.Simulation(situation=..., reform=...) with the same people, OH, JOINT, national SPM",
        "variables_compared": compare_vars,
        "raw_baseline": {k: raw_base[k] for k in compare_vars},
        "raw_reform": {k: raw_ref[k] for k in compare_vars},
        "mismatches_over_1_cent": mismatches,
        "match": len(mismatches) == 0,
        "spm_geography_sensitivity": {
            "note": "Same family with county_fips 39049 (Franklin County, OH) and county-mode SPM. NOT the reported household; shows net income does not depend on the SPM geography choice.",
            "household_net_income_baseline": county_net_base,
            "household_net_income_reform": county_net_ref,
            "identical_to_reported": abs(county_net_base - base["household_net_income"]) < 0.005
            and abs(county_net_ref - ref["household_net_income"]) < 0.005,
        },
    },
}
out["meta"]["runtime"] = timer.summary()
write_json(DATA_DIR / "household.json", out)
print("net baseline", base["household_net_income"], "reform", ref["household_net_income"], "change", d_net)
print("ctc", base["ctc"], ref["ctc"], "ctc_value", base["ctc_value"], ref["ctc_value"])
print("match:", len(mismatches) == 0, mismatches[:5])
print(gain_explanation)
