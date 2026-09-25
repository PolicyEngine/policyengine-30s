"""The UK video's example family and reform, shared by every UK compute script.

Nothing here is on screen by itself: build_uk_video.py reads the reform dict and
the family inputs back out of the JSON files the compute scripts write, so the
video shows exactly what PolicyEngine received.

Microdata guard: these scripts build single households from a `situation` and
never touch a dataset. `no_microdata()` makes that a hard failure rather than a
convention: it points the Hugging Face cache at an empty temporary folder, turns
the hub offline and drops every token, so any code path that tried to load the
UK survey microdata (enhanced_frs_*, populace_uk_*) would raise instead of
downloading or reading a cached copy. Call it before importing policyengine.
"""

from __future__ import annotations

import importlib.metadata as md
import os
import tempfile
from pathlib import Path

YEAR = 2026  # policyengine-uk: a bare year names the fiscal year from April, so 2026 = 2026-27
FISCAL_YEAR = "2026-27"

PA_PATH = "gov.hmrc.income_tax.allowances.personal_allowance.amount"
PA_NEW = 15_000
# Keyed by the bare model year, which policyengine-uk reads as 2026-27. A key of
# "2026-04-06" (the statutory start of 2026-27) silently leaves 2026 on current law;
# every script asserts the reform actually moved the parameter the model reads.
REFORM = {PA_PATH: {str(YEAR): PA_NEW}}

RENT_PER_MONTH = 500  # illustrative input, not sourced (see data/uk/README.md)
ADULT = {"age": 30}
CHILDREN = [{"age": 4, "is_male": False}, {"age": 8, "is_male": True}]
HOUSEHOLD = {
    "region": "NORTH_WEST",
    "brma": "CENTRAL_GREATER_MANCHESTER",
    "local_authority": "MANCHESTER",
    "tenure_type": "RENT_FROM_HA",
    "rent": RENT_PER_MONTH * 12,
    # held at 0 in both runs: Council Tax Reduction for working-age households is not
    # simulated for Manchester, so a council tax bill would only shift both runs equally
    "council_tax": 0,
}
BENUNIT: dict = {}
FAMILY_LABEL = (
    "Lone parent (30), children aged 4 and 8, one earner, renting from a housing "
    f"association in Manchester at £{RENT_PER_MONTH} a month, tax year {FISCAL_YEAR}"
)

# Variables recorded at every earnings point (all mapped to the household).
RECORD = [
    "employment_income",
    "hbai_household_net_income",
    "income_tax",
    "national_insurance",
    "universal_credit",
    "uc_earned_income",
    "uc_income_reduction",
    "uc_maximum_amount",
    "uc_work_allowance",
    "benefit_cap_reduction",
    "child_benefit",
    "CB_HITC",
    "marriage_allowance",
    "council_tax",
]


def no_microdata() -> Path:
    home = Path(tempfile.mkdtemp(prefix="pe-uk-no-microdata-"))
    os.environ["HF_HOME"] = str(home)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(home / "hub")
    os.environ["HF_HUB_OFFLINE"] = "1"
    for k in list(os.environ):
        u = k.upper()
        if "TOKEN" in u and ("HUGGING" in u or u.startswith("HF_")):
            os.environ.pop(k, None)
    return home


def assert_no_microdata(home: Path) -> None:
    """After a run: nothing was written to the empty cache (no dataset was fetched or opened)."""
    leftovers = [p for p in home.rglob("*") if p.is_file()]
    assert not leftovers, f"a dataset cache appeared during a household run: {leftovers[:5]}"


def versions() -> dict[str, str]:
    out = {}
    for pkg in ["policyengine", "policyengine-uk", "policyengine-core", "numpy"]:
        try:
            out[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            pass
    return out


def situation(earnings_min: float | None = None, earnings_max: float | None = None, count: int | None = None,
              earnings: float | None = None, rent_per_month: float | None = None) -> dict:
    """policyengine_uk situation: one household, optionally with an axis on the parent's earnings.

    rent_per_month overrides the illustrative rent (used only by rent_sensitivity.py)."""
    people = {"parent": {k: {YEAR: v} for k, v in ADULT.items()}}
    for i, c in enumerate(CHILDREN, 1):
        people[f"child{i}"] = {k: {YEAR: v} for k, v in c.items()}
    if earnings is not None:
        people["parent"]["employment_income"] = {YEAR: earnings}
    names = list(people)
    sit = {
        "people": people,
        "benunits": {"benunit": {"members": names, **{k: {YEAR: v} for k, v in BENUNIT.items()}}},
        "households": {"household": {"members": names, **{k: {YEAR: v} for k, v in HOUSEHOLD.items()}}},
    }
    if rent_per_month is not None:
        sit["households"]["household"]["rent"] = {YEAR: rent_per_month * 12}
    if count is not None:
        sit["axes"] = [[{"name": "employment_income", "min": earnings_min, "max": earnings_max,
                         "count": count, "period": YEAR, "index": 0}]]
    return sit


def pe_py_people(earnings: float | None = None) -> list[dict]:
    """The same people in policyengine.py's calculate_household shape."""
    parent = dict(ADULT)
    if earnings is not None:
        parent["employment_income"] = earnings
    return [parent] + [dict(c) for c in CHILDREN]
