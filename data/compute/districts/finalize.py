"""Assemble data/districts.json from the compute runs.

Primary: out/districts_pe611.json (policyengine 6.1.1 bundle, the latest
policyengine.py release and the version the sibling household/national tasks
in this project used). Cross-check: out/districts_pe520.json (policyengine
5.2.0 bundle, which the live app/API served on 2026-09-24). The two bundles'
datasets have identical household weights and congressional_district_geoid
assignments (verified column by column; see meta.selection.dataset_equivalence).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1]
PRIMARY = HERE / "out" / "districts_pe611.json"
LIVE = HERE / "out" / "districts_pe520.json"
RUN1 = HERE / "out" / "districts_pe611_run1.json"
LAYOUT = DATA / "district_layout.json"
OUT = DATA / "districts.json"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    import sys
    import time

    t0 = time.time()
    prim = json.loads(PRIMARY.read_text())
    live = json.loads(LIVE.read_text())
    layout = json.loads(LAYOUT.read_text())

    pd_ = {d["geoid"]: d for d in prim["districts"]}
    ld_ = {d["geoid"]: d for d in live["districts"]}
    lay = {d["geoid"]: d for d in layout["districts"]}
    assert set(pd_) == set(ld_) == set(lay), "geoid sets differ"
    for g, d in pd_.items():
        assert lay[g]["district_id"] == d["district_id"], (g, lay[g]["district_id"], d["district_id"])

    def diffs(field: str) -> dict:
        a = np.array([pd_[g][field] for g in sorted(pd_)])
        b = np.array([ld_[g][field] for g in sorted(pd_)])
        i = int(np.argmax(np.abs(a - b)))
        return {
            "max_abs_diff": float(np.max(np.abs(a - b))),
            "mean_abs_diff": float(np.mean(np.abs(a - b))),
            "at_geoid": sorted(pd_)[i],
            "primary_value": float(a[i]),
            "live_app_value": float(b[i]),
            "n_identical": int(np.sum(a == b)),
        }

    comparison = {
        "live_app_file": str(LIVE),
        "live_app_file_sha256": sha(LIVE),
        "live_app_packages": live["meta"]["packages"],
        "live_app_dataset": live["meta"]["dataset_source"],
        "avg_change": diffs("avg_change"),
        "share_gaining": diffs("share_gaining"),
        "households": diffs("households"),
        "national_primary": prim["meta"]["checks"]["national"],
        "national_live_app": live["meta"]["checks"]["national"],
    }

    meta = dict(prim["meta"])
    meta["assembled_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    meta["assembled_by"] = str(Path(__file__).resolve())
    meta["primary_run_file"] = str(PRIMARY)
    meta["primary_run_file_sha256"] = sha(PRIMARY)
    meta["selection"] = {
        "primary": "policyengine 6.1.1 bundle (latest policyengine.py release, 2026-09-22; policyengine-us 2.2.1; populace_us_2024 @ populace-us-2024-spm-20260915). Chosen so district figures are consistent with the other data files in this project, which use the same versions.",
        "live_app": "On 2026-09-24 https://api.policyengine.org/us/metadata reported policyengine-us 1.764.6 and default dataset hf://policyengine/populace-us/populace_us_2024.h5@populace-us-2024-buildp-sparse-rmloss100-cae8640-20260728T011454Z, and policyengine-api-v2 origin/main (aeae617) pins policyengine==5.2.0 in the simulation executor. That configuration was also run; see live_app_comparison.",
        "dataset_equivalence": "populace_us_2024.h5 at populace-us-2024-spm-20260915 (sha256 6496cc43...) and at populace-us-2024-buildp-sparse-rmloss100-cae8640-20260728T011454Z (sha256 48b9d479...) have identical household, tax_unit, spm_unit, family and marital_unit tables and identical person columns; the only difference is one extra person column, is_spm_independent_minor_role, in the spm-20260915 build. household_weight and congressional_district_geoid are identical, so the primary run uses the same weights and district assignment as the live app.",
        "difference_source": "Differences between primary and live-app numbers come from the policyengine-us model version (2.2.1 vs 1.764.6) and the policyengine.py version (6.1.1 vs 5.2.0), not from weights.",
    }
    meta["live_app_comparison"] = comparison

    # Determinism: the same configuration was run twice; shared fields must match exactly.
    if RUN1.exists():
        r1 = {d["geoid"]: d for d in json.loads(RUN1.read_text())["districts"]}
        shared = [k for k in r1[next(iter(r1))] if k in pd_[next(iter(pd_))]]
        mismatches = [
            (g, k) for g in pd_ for k in shared if r1[g][k] != pd_[g][k]
        ]
        meta["checks"]["rerun_determinism"] = {
            "first_run_file": str(RUN1),
            "first_run_file_sha256": sha(RUN1),
            "fields_compared": shared,
            "n_mismatches": len(mismatches),
            "examples": mismatches[:5],
        }
    meta["layout_join"] = {
        "layout_file": str(LAYOUT),
        "layout_file_sha256": sha(LAYOUT),
        "all_436_geoids_match": True,
        "all_district_ids_match": True,
    }

    # ---- Sample-quality diagnostics from the exact 2026 weights used ----
    import pandas as pd

    year_file = HERE / prim["meta"]["dataset_year_file"]["local_path"]
    assert sha(year_file) == prim["meta"]["dataset_year_file"]["sha256"]
    hh = pd.read_hdf(year_file, "household")[
        ["congressional_district_geoid", "state_fips", "household_weight"]
    ]
    hh["w2"] = hh["household_weight"].astype(float) ** 2
    hh["w"] = hh["household_weight"].astype(float)
    hh["lt1"] = hh["w"] < 1.0
    by_d = hh.groupby("congressional_district_geoid").agg(
        w=("w", "sum"), w2=("w2", "sum"), n=("w", "size"), lt1=("lt1", "sum")
    )
    by_s = hh.groupby("state_fips").agg(
        w=("w", "sum"), w2=("w2", "sum"), n=("w", "size"), lt1=("lt1", "sum")
    )
    NEAR_ZERO = 0.001
    districts = []
    for d in prim["districts"]:
        row = by_d.loc[int(d["geoid"])]
        assert int(row["n"]) == d["sample_households"]
        assert abs(float(row["w"]) - d["households"]) < 1e-6 * d["households"]
        d = dict(d)
        d["effective_sample_size"] = float(row["w"] ** 2 / row["w2"])
        d["sample_households_weight_below_1"] = int(row["lt1"])
        d["near_zero_gainers"] = bool(d["share_gaining"] < NEAR_ZERO)
        districts.append(d)

    ess = np.array([d["effective_sample_size"] for d in districts])
    flagged = [d for d in districts if d["near_zero_gainers"]]
    national = dict(meta["checks"]["national"])
    national["total_ctc_change_tax_units_note"] = (
        "Change in the weighted sum of the policyengine-us tax-unit variable 'ctc', whose formula "
        "(policyengine_us/variables/gov/irs/credits/ctc/ctc.py) is max(0, ctc_maximum_with_arpa_addition - "
        "ctc_phase_out) and does not reference tax liability. It is a diagnostic, not the reform's cost; "
        "the change in household net income is total_household_net_income_change."
    )
    meta["checks"]["national"] = national
    meta["share_definitions_note"] = (
        "Three household-weighted gainer shares are provided. share_gaining uses PolicyEngine's own winner "
        "threshold (gain > 0.1% of baseline household_net_income, from congressional_district_impact.py). "
        "share_gaining_over_1usd uses gain > $1, the definition in data/national.json "
        "(winners.share_households_gaining_over_1usd). share_gaining_any_increase uses gain > $0. National values: "
        f"{national['share_households_gaining_pe_threshold']} (PE threshold), "
        f"{national.get('share_households_gaining_over_1usd')} (> $1), "
        f"{national['share_households_gaining_any_increase']} (> $0). Use one definition consistently on screen."
    )
    meta["checks"]["sum_of_district_total_change"] = float(sum(d["total_change"] for d in districts))
    meta["checks"]["sum_of_district_households"] = float(sum(d["households"] for d in districts))
    meta["sample_quality"] = {
        "source": f"household_weight in {year_file} (sha256 {prim['meta']['dataset_year_file']['sha256']}), the exact 2026 weights used",
        "records_total": int(len(hh)),
        "records_with_weight_below_1": int(hh["lt1"].sum()),
        "effective_sample_size_definition": "Kish: (sum w)^2 / sum(w^2) over the district's household records",
        "district_effective_sample_size": {
            "min": float(ess.min()),
            "p25": float(np.percentile(ess, 25)),
            "median": float(np.median(ess)),
            "p75": float(np.percentile(ess, 75)),
            "max": float(ess.max()),
        },
        "near_zero_gainers_threshold": NEAR_ZERO,
        "near_zero_gainers_districts": [
            {
                "geoid": d["geoid"],
                "district_id": d["district_id"],
                "avg_change": d["avg_change"],
                "share_gaining": d["share_gaining"],
                "sample_households": d["sample_households"],
                "sample_households_weight_below_1": d["sample_households_weight_below_1"],
                "effective_sample_size": d["effective_sample_size"],
            }
            for d in flagged
        ],
        "interpretation": (
            "Each district value is a weighted mean over that district's records in one national sample. "
            "With effective sample sizes this small, district values are noisy and should not be presented "
            "as precise district facts. A near-zero district means no heavily weighted record in that district "
            "gains; it is not a measurement that no families there would gain."
        ),
        "better_source_not_run": (
            "policyengine.py docs (docs/microsim.md, origin/main 4dc5959) say congressional-district breakdowns "
            "should filter populace_us_2024_acs_local (release manifest: 1,588,854 households, 3,589,209 person "
            "rows; calibrated to state and congressional-district population) rather than the national default. "
            "It was not run here: the national file (166,321 person rows) took "
            f"{prim['meta']['runtime_seconds']['baseline_run_s']:.0f} s (baseline) and "
            f"{prim['meta']['runtime_seconds']['reform_run_s']:.0f} s (reform) with observed peak RSS of about "
            "9 GB per process; scaling linearly by person rows (21.6x) implies several hours of compute."
        ),
    }
    meta["fields_added_in_finalize"] = {
        "effective_sample_size": "Kish effective sample size of the district's household records under the 2026 weights",
        "sample_households_weight_below_1": "Number of the district's records with household_weight < 1",
        "near_zero_gainers": f"True when share_gaining < {NEAR_ZERO}",
    }

    meta["finalize_runtime_seconds"] = time.time() - t0
    meta["runtime_note"] = "runtime_seconds is the wall clock of the compute run that produced these numbers (out/districts_pe611.json); finalize_runtime_seconds is this assembly step."
    OUT.write_text(json.dumps({"meta": meta, "districts": districts}, indent=1))

    # ---- Exact state rollup of the same district results ----
    states: dict[str, dict] = {}
    for d in districts:
        s = states.setdefault(
            d["state_code"],
            {"state_code": d["state_code"], "state_fips": d["state_fips"], "n_districts": 0,
             "households": 0.0, "total_change": 0.0, "_gain_w": 0.0, "_gain1_w": 0.0, "sample_households": 0},
        )
        s["n_districts"] += 1
        s["households"] += d["households"]
        s["total_change"] += d["total_change"]
        s["_gain_w"] += d["share_gaining"] * d["households"]
        s["_gain1_w"] += d["share_gaining_over_1usd"] * d["households"]
        s["sample_households"] += d["sample_households"]
    rows = []
    for st, s in sorted(states.items(), key=lambda kv: kv[1]["state_fips"]):
        srow = by_s.loc[s["state_fips"]]
        rows.append(
            {
                "state_code": st,
                "state_fips": s["state_fips"],
                "n_districts": s["n_districts"],
                "avg_change": s["total_change"] / s["households"],
                "share_gaining": s["_gain_w"] / s["households"],
                "share_gaining_over_1usd": s["_gain1_w"] / s["households"],
                "households": s["households"],
                "total_change": s["total_change"],
                "sample_households": s["sample_households"],
                "effective_sample_size": float(srow["w"] ** 2 / srow["w2"]),
            }
        )
    assert len(rows) == 51
    rollup = {
        "meta": {
            "title": "State rollup of the district results (51 incl. DC), $3,000 per-child CTC, 2026",
            "derived_from": str(OUT),
            "derived_from_sha256": sha(OUT),
            "assembled_by": str(Path(__file__).resolve()),
            "method": "Exact aggregation of the district rows: avg_change = sum(total_change)/sum(households); share_gaining (and share_gaining_over_1usd) = sum(share*households)/sum(households). District household sets partition each state, so this equals a direct state-level computation on the same simulation.",
            "definitions": "As in districts.json meta.method.fields",
            "packages": meta["packages"],
            "dataset_source": meta["dataset_source"],
            "python": sys.version,
            "compute_runtime_seconds": meta["runtime_seconds"],
            "rollup_runtime_seconds": time.time() - t0,
            "note": "Not the fallback states.json (district computation was feasible). Offered because state values rest on larger effective samples than district values.",
        },
        "states": rows,
    }
    (DATA / "district_state_rollup.json").write_text(json.dumps(rollup, indent=1))

    print(json.dumps({"out": str(OUT), "comparison": {k: v for k, v in comparison.items() if k in ("avg_change", "share_gaining", "households")}, "sample_quality": {k: v for k, v in meta["sample_quality"].items() if k in ("district_effective_sample_size", "records_with_weight_below_1")}, "flagged": [d["district_id"] for d in flagged]}, indent=1))


if __name__ == "__main__":
    main()
