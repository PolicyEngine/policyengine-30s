"""Per-congressional-district impact of a $3,000 per-child CTC for 2026.

Reform (single parameter): gov.irs.credits.ctc.amount.base[0].amount = 3000
for the period 2026-01-01.2026-12-31. Nothing else changes.

Method, the same one PolicyEngine's production simulation API uses:
  policyengine-api-v2
    projects/policyengine-simulation-executor/src/policyengine_simulation_executor/
      simulation_output_geographic.py::build_congressional_district_impact
  calls
    policyengine.outputs.congressional_district_impact.
      compute_us_congressional_district_impacts(baseline, reform)
  on national baseline/reform `policyengine.core.Simulation`s built on the
  bundle's certified default dataset (`ensure_datasets(years=[year])`), with
  no scoping for the national region. That function groups the output
  household table by `congressional_district_geoid` (SSDD; at-large = SS00)
  and weights by `household_weight`.

This script runs that function unchanged, keeps its outputs verbatim
(`pe_*` fields), and adds the household-weighted share of households
gaining, which PolicyEngine's output does not report (its
`winner_percentage` is person-weighted).

Run with the interpreter of the venv whose policyengine version you want:
  .venv-pe520/bin/python compute_districts.py --label pe520 ...
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata as md
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

YEAR = 2026
PARAM = "gov.irs.credits.ctc.amount.base[0].amount"
REFORM_VALUE = 3000
PERIOD_START = dt.datetime(2026, 1, 1)
PERIOD_END = dt.datetime(2026, 12, 31)
# PolicyEngine's winner threshold, copied from
# policyengine/outputs/congressional_district_impact.py: a household is a
# winner when (reform - baseline) / max(baseline, 1) > 1e-3.
PE_REL_THRESHOLD = 1e-3

PACKAGES = [
    "policyengine",
    "policyengine-core",
    "policyengine-us",
    "spm-calculator",
    "microdf-python",
    "numpy",
    "pandas",
    "h5py",
    "tables",
    "pydantic",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pkg_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for p in PACKAGES:
        try:
            out[p] = md.version(p)
        except md.PackageNotFoundError:
            out[p] = None
    return out


def seed_source_dataset(manifest, data_folder: Path, hf_cache_blob: Path | None) -> dict:
    """Place the certified source .h5 in data_folder so ensure_datasets reuses it.

    policyengine's materializer reuses data_folder/<path> when its sha256
    matches the bundle manifest; otherwise it downloads from Hugging Face.
    We clone the byte-identical Hugging Face cache blob (APFS copy-on-write)
    and verify the sha256 against the manifest before use.
    """
    ref = manifest.datasets[manifest.default_dataset]
    dest = data_folder / Path(ref.path).name
    info = {
        "logical_name": manifest.default_dataset,
        "repo_id": ref.repo_id or manifest.data_package.repo_id,
        "repo_type": ref.repo_type or manifest.data_package.repo_type,
        "path_in_repo": ref.path,
        "revision": ref.revision,
        "uri": manifest.default_dataset_uri,
        "expected_sha256": ref.sha256,
        "local_path": str(dest),
    }
    data_folder.mkdir(parents=True, exist_ok=True)
    if not dest.exists() and hf_cache_blob is not None and hf_cache_blob.exists():
        r = subprocess.run(["cp", "-c", str(hf_cache_blob), str(dest)])
        if r.returncode != 0:
            shutil.copyfile(hf_cache_blob, dest)
        info["seeded_from_hf_cache_blob"] = str(hf_cache_blob)
    if dest.exists():
        actual = sha256_file(dest)
        info["sha256"] = actual
        if actual != ref.sha256:
            raise SystemExit(
                f"sha256 mismatch for {dest}: {actual} != manifest {ref.sha256}"
            )
    return info


def verify_reform_parameter(reform_dict: dict) -> dict:
    """Read the CTC base amount for 2026 with and without the reform."""
    from policyengine_core.reforms import Reform
    from policyengine_us import CountryTaxBenefitSystem

    base_tbs = CountryTaxBenefitSystem()
    reform_cls = Reform.from_dict(reform_dict, country_id="us")
    reform_tbs = reform_cls(CountryTaxBenefitSystem())

    def read(tbs, instant):
        return float(
            tbs.parameters.gov.irs.credits.ctc.amount.base.brackets[0].amount(instant)
        )

    return {
        "baseline_2026_01_01": read(base_tbs, "2026-01-01"),
        "baseline_2026_12_31": read(base_tbs, "2026-12-31"),
        "reform_2026_01_01": read(reform_tbs, "2026-01-01"),
        "reform_2026_12_31": read(reform_tbs, "2026-12-31"),
        "baseline_2027_01_01": read(base_tbs, "2027-01-01"),
        "reform_2027_01_01": read(reform_tbs, "2027-01-01"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--data-folder", required=True, type=Path)
    ap.add_argument("--hf-cache-blob", type=Path, default=None)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--configuration-note", default="")
    args = ap.parse_args()

    t0 = time.time()
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    timings: dict[str, float] = {}

    from policyengine.core import Parameter, ParameterValue, Policy, Simulation
    from policyengine.outputs.congressional_district_impact import (
        compute_us_congressional_district_impacts,
    )
    from policyengine.provenance.manifest import get_release_manifest
    import policyengine.tax_benefit_models.us as us

    manifest = get_release_manifest("us")
    src_info = seed_source_dataset(manifest, args.data_folder, args.hf_cache_blob)
    timings["seed_source_s"] = time.time() - t0

    t = time.time()
    datasets = us.ensure_datasets(years=[YEAR], data_folder=str(args.data_folder))
    dataset = next(iter(datasets.values()))
    timings["ensure_datasets_s"] = time.time() - t
    year_file = Path(getattr(dataset, "filepath", "") or "")
    year_info = {
        "name": getattr(dataset, "name", None),
        "year": getattr(dataset, "year", None),
        "local_path": str(year_file) if year_file else None,
        "sha256": sha256_file(year_file) if year_file and year_file.exists() else None,
        "note": (
            "Year-2026 file written by policyengine ensure_datasets from the "
            "certified source .h5 (input variables calculated for 2026)."
        ),
    }

    model = us.us_latest if hasattr(us, "us_latest") else us.model
    policy = Policy(
        name="CTC base amount $3,000 for 2026",
        parameter_values=[
            ParameterValue(
                parameter=Parameter(
                    name=PARAM, tax_benefit_model_version=model, data_type=float
                ),
                start_date=PERIOD_START,
                end_date=PERIOD_END,
                value=REFORM_VALUE,
            )
        ],
    )
    from policyengine.utils.parametric_reforms import build_reform_dict

    reform_dict = build_reform_dict(policy)
    param_check = verify_reform_parameter(reform_dict)

    baseline = Simulation(dataset=dataset, tax_benefit_model_version=model)
    reform = Simulation(dataset=dataset, tax_benefit_model_version=model, policy=policy)
    t = time.time()
    baseline.run()
    timings["baseline_run_s"] = time.time() - t
    t = time.time()
    reform.run()
    timings["reform_run_s"] = time.time() - t

    # PolicyEngine's own district computation, unchanged.
    t = time.time()
    impact = compute_us_congressional_district_impacts(baseline, reform)
    pe_rows = {int(r["district_geoid"]): r for r in impact.district_results}
    timings["district_impact_s"] = time.time() - t

    bh = baseline.output_dataset.data.household
    rh = reform.output_dataset.data.household
    assert np.array_equal(bh["household_id"].values, rh["household_id"].values)
    geoid = bh["congressional_district_geoid"].values.astype(int)
    w = bh["household_weight"].values.astype(float)
    b = bh["household_net_income"].values.astype(float)
    r = rh["household_net_income"].values.astype(float)
    npeople = bh["household_count_people"].values.astype(float)
    chg = r - b
    rel = chg / np.maximum(b, 1.0)
    gain_pe = rel > PE_REL_THRESHOLD
    lose_pe = rel <= -PE_REL_THRESHOLD
    gain_any = chg > 0.0
    gain_1usd = chg > 1.0

    # Persist household-level results so other thresholds need no re-run.
    hh_out = args.out.with_name(f"household_changes_{args.label}.npz")
    np.savez_compressed(
        hh_out,
        household_id=bh["household_id"].values,
        congressional_district_geoid=geoid,
        household_weight=w,
        household_count_people=npeople,
        baseline_household_net_income=b,
        reform_household_net_income=r,
    )

    # Tax-unit CTC change, for a national sanity check.
    btu = baseline.output_dataset.data.tax_unit
    rtu = reform.output_dataset.data.tax_unit
    ctc_change_total = float(
        ((rtu["ctc"].values - btu["ctc"].values) * btu["tax_unit_weight"].values).sum()
    )

    from policyengine.countries.us.data import AT_LARGE_STATES, US_STATE_FIPS

    fips_to_abbr = {int(v): k for k, v in US_STATE_FIPS.items()}

    districts = []
    for g in sorted(np.unique(geoid[geoid > 0])):
        m = geoid == g
        wm = w[m]
        W = float(wm.sum())
        state_fips = int(g) // 100
        dnum = int(g) % 100
        st = fips_to_abbr[state_fips]
        public_num = 1 if st in AT_LARGE_STATES else dnum
        pe = pe_rows[int(g)]
        own_avg = float((chg[m] * wm).sum() / W)
        districts.append(
            {
                "geoid": f"{int(g):04d}",
                "district_id": f"{st}-{public_num:02d}",
                "state_code": st,
                "state_fips": state_fips,
                "district_number": dnum,
                "at_large": st in AT_LARGE_STATES,
                "avg_change": pe["average_household_income_change"],
                "share_gaining": float(wm[gain_pe[m]].sum() / W),
                "households": W,
                "sample_households": int(m.sum()),
                "share_gaining_any_increase": float(wm[gain_any[m]].sum() / W),
                "share_gaining_over_1usd": float(wm[gain_1usd[m]].sum() / W),
                "share_losing": float(wm[lose_pe[m]].sum() / W),
                "total_change": float((chg[m] * wm).sum()),
                "avg_change_check": own_avg,
                "pe_average_household_income_change": pe[
                    "average_household_income_change"
                ],
                "pe_relative_household_income_change": pe[
                    "relative_household_income_change"
                ],
                "pe_winner_percentage_people": pe["winner_percentage"],
                "pe_loser_percentage_people": pe["loser_percentage"],
                "pe_no_change_percentage_people": pe["no_change_percentage"],
                "pe_population_field": pe["population"],
            }
        )

    max_avg_diff = max(abs(d["avg_change"] - d["avg_change_check"]) for d in districts)
    W_all = float(w.sum())
    national = {
        "households_weighted": W_all,
        "people_weighted": float((npeople * w).sum()),
        "total_household_net_income_change": float((chg * w).sum()),
        "avg_change_per_household": float((chg * w).sum() / W_all),
        "share_households_gaining_pe_threshold": float(w[gain_pe].sum() / W_all),
        "share_households_gaining_any_increase": float(w[gain_any].sum() / W_all),
        "share_households_gaining_over_1usd": float(w[gain_1usd].sum() / W_all),
        "share_households_losing_pe_threshold": float(w[lose_pe].sum() / W_all),
        "share_people_gaining_pe_threshold": float(
            (npeople * w)[gain_pe].sum() / (npeople * w).sum()
        ),
        "total_ctc_change_tax_units": ctc_change_total,
        "sample_households": int(len(w)),
    }

    timings["total_wall_clock_s"] = time.time() - t0
    meta = {
        "title": "Per-congressional-district impact of a $3,000 per-child CTC, 2026",
        "label": args.label,
        "configuration_note": args.configuration_note,
        "generated_at_utc": started,
        "finished_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "runtime_seconds": timings,
        "script": str(Path(__file__).resolve()),
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "python": sys.version,
        "platform": platform.platform(),
        "packages": pkg_versions(),
        "bundle": {
            "policyengine_version": manifest.policyengine_version,
            "bundle_id": manifest.bundle_id,
            "model_package": manifest.model_package.model_dump(),
            "data_package": manifest.data_package.model_dump(),
            "default_dataset": manifest.default_dataset,
            "default_dataset_uri": manifest.default_dataset_uri,
        },
        "dataset_source": src_info,
        "dataset_year_file": year_info,
        "household_level_output": {"path": str(hh_out.resolve()), "sha256": sha256_file(hh_out), "note": "Per-household 2026 baseline and reform household_net_income with weights and district, from this run."},
        "analysis_year": YEAR,
        "reform": {
            "parameter": PARAM,
            "value": REFORM_VALUE,
            "period": "2026-01-01.2026-12-31",
            "reform_dict_applied": reform_dict,
            "parameter_check": param_check,
            "note": "Single parameter changed; everything else is current law in the installed policyengine-us.",
        },
        "method": {
            "district_function": "policyengine.outputs.congressional_district_impact.compute_us_congressional_district_impacts",
            "production_caller": "PolicyEngine/policyengine-api-v2 projects/policyengine-simulation-executor/src/policyengine_simulation_executor/simulation_output_geographic.py::build_congressional_district_impact",
            "grouping_variable": "congressional_district_geoid (household; SSDD integer, at-large states and DC use district 00)",
            "weights": "household_weight from the certified national dataset after ensure_datasets for 2026",
            "scope": "national simulation, no scoping strategy (region 'us')",
            "fields": {
                "geoid": "4-character zero-padded congressional_district_geoid (state FIPS x 100 + district number; at-large and DC = SS00). Join key shared with district_layout.json.",
                "district_id": "PolicyEngine API public district code (at-large and DC are '-01'), matching the app's DISTRICT_ID.",
                "avg_change": "PolicyEngine's average_household_income_change: household-weighted mean of (reform - baseline) household_net_income, USD per household per year, 2026.",
                "share_gaining": "Household-weighted share of households whose household_net_income rises by more than 0.1% of baseline (PolicyEngine's winner threshold: (reform-baseline)/max(baseline,1) > 0.001). PolicyEngine itself reports this share person-weighted (pe_winner_percentage_people); this household-weighted version was computed here from the same simulation output.",
                "households": "Sum of household_weight in the district (weighted household count, 2026). Equals PolicyEngine's 'population' field, which is a household-weight sum.",
                "sample_households": "Unweighted number of microdata household records assigned to the district.",
                "share_gaining_any_increase": "Household-weighted share with any positive change in household_net_income (> $0).",
                "share_gaining_over_1usd": "Household-weighted share whose household_net_income rises by more than $1 (the definition used in data/national.json winners.share_households_gaining_over_1usd).",
                "share_losing": "Household-weighted share losing more than 0.1% of baseline household_net_income.",
                "total_change": "Weighted sum of the household_net_income change in the district, USD, 2026.",
                "avg_change_check": "Independent recomputation of avg_change from the same output tables; max abs difference is in checks.",
                "pe_*": "Fields copied verbatim from PolicyEngine's district_results.",
            },
        },
        "checks": {
            "n_districts": len(districts),
            "max_abs_diff_avg_change_vs_recomputation": max_avg_diff,
            "national": national,
        },
        "caveats": [
            "District estimates come from filtering one national microdata sample; the number of household records per district ranges from "
            f"{min(d['sample_households'] for d in districts)} to {max(d['sample_households'] for d in districts)} (median "
            f"{int(np.median([d['sample_households'] for d in districts]))}), so individual district values carry sampling noise.",
            "Static microsimulation: no behavioural responses.",
        ],
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"meta": meta, "districts": districts}, indent=1))
    print(json.dumps({"out": str(args.out), "timings": timings, "national": national, "param_check": param_check, "max_avg_diff": max_avg_diff}, indent=1))


if __name__ == "__main__":
    main()
