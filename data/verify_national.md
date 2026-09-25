# Adversarial verification: CTC $3,000 (2026) outputs

Verified 2026-09-25 against `household.json`, `national.json`, `households_sample.json` and the scripts in `compute/`. No output file was modified. The sha256 values of all three files match before and after this check. Every rerun wrote to a temporary directory.

**Verdict: the outputs are correct and internally consistent.** None of the numbers is wrong. The caveats below are about presentation and data calibration.

## 1. Reform scope

- Both paths pass the same reform dict: `{"gov.irs.credits.ctc.amount.base[0].amount": {"2026-01-01.2026-12-31": 3000}}`.
  - `household.py` passes it directly.
  - `national.py` passes a `Policy`/`ParameterValue` with start 2026-01-01 and end 2026-12-31. `policyengine.utils.parametric_reforms.build_reform_dict` turns that into a dict, and I checked programmatically that it equals the one above.
  - `national_raw_check.py` also passes it directly.
- I diffed all 102,530 parameter leaves of the baseline and reformed `CountryTaxBenefitSystem` at 2025-12-31, 2026-01-01, 2026-06-30, 2026-12-31, 2027-01-01 and 2030-01-01.
  - The only difference is `gov.irs.credits.ctc.amount.base[0].amount`, which goes from 2200 to 3000 at the three 2026 instants.
  - Nothing changes in 2025 or 2027 onward.
- Other code that reads this parameter:
  - `ctc_child_individual_maximum` is the intended use.
  - `ctc_qualifying_child` reads only the age threshold.
  - Colorado's `co_federal_ctc_child_individual_maximum` is used only when `gov.states.co.tax.income.credits.ctc.ctc_matched_federal_credit` is true. That flag has been false since 2024-01-01, so it has no effect in 2026, which matches the absence of CO from the by-state list.
  - The remaining matches are in `reforms/` and only run when a contrib flag is set.
- `data/base.yaml` is byte-identical to the installed `policyengine_us` 2.2.1 `parameters/gov/irs/credits/ctc/amount/base.yaml`.

## 2. Household rerun

I reran `compute/household.py` with `common.DATA_DIR` redirected to a temporary directory. Apart from `meta.runtime`, the output matches `household.json` exactly, with 0 differences. It includes the second-method (`policyengine_us.Simulation`) match and the Franklin County SPM-geography sensitivity check.

## 3. Hand check against IRC §24 (2026 parameters read from the installed model)

Household: married filing jointly in Ohio, one earner with $60,000 of wages, children aged 4 and 8. Neither child is phased out, since AGI is well below $400,000. Model phase-out parameters: $50 per $1,000 above $400,000 for joint filers.

| Step | Hand calculation | Model |
|---|---|---|
| Taxable income | 60,000 - 32,200 (2026 joint standard deduction) = 27,800 | 27,800 |
| Tax before credits | 10% x 24,800 + 12% x 3,000 = 2,840 | 2,840 |
| CTC allowed, baseline / reform | 2 x 2,200 = 4,400 / 2 x 3,000 = 6,000 | 4,400 / 6,000 |
| Nonrefundable part (limited to liability) | min(credit, 2,840) = 2,840 in both | 2,840 / 2,840 |
| ACTC earned-income phase-in | 15% x (60,000 - 2,500) = 8,625 | 8,625 |
| ACTC cap | 2 x 1,700 = 3,400 | 3,400 |
| ACTC, baseline | min(4,400 - 2,840 = 1,560; 3,400; 8,625) = 1,560 | 1,560 |
| ACTC, reform | min(6,000 - 2,840 = 3,160; 3,400; 8,625) = 3,160 | 3,160 |
| Credit realized, baseline / reform | 2,840 + 1,560 = 4,400 / 2,840 + 3,160 = 6,000 | 4,400 / 6,000 |
| EITC (unchanged) | 7,316 - 21.06% x (60,000 - 31,160) = 1,242.30 | 1,242.30 |
| Federal income tax | 2,840 - 4,400 - 1,242.30 = -2,802.30; reform -4,402.30 | same |
| Net income change | +1,600 (the refundable cap does not bind: 3,160 < 3,400) | +1,599.996 (float32) |

The waterfall in `household_video.json` also adds up. Its "Taxes before credits" of -8,086 is federal income tax before credits (2,840) plus payroll tax (4,590) plus Ohio income tax (656.44). The rows sum to 59,293 in the baseline and 60,893 under the reform.

## 4. National outputs

### Recomputed from the saved baseline and reform output datasets

These are the two `pe_data/*-spm-*.h5` files. Their IDs and weights are identical, and I identified the baseline as the file with the lower weighted CTC total.

- Every budget line in `national.json` matches to $0.00. That covers the federal income tax change (-$31,193,255,594), net income, state tax, CTC allowed, CTC value, refundable and nonrefundable CTC, EITC, payroll tax and benefits.
- policyengine.py's `budgetary_impact.federal` agrees with the script's figure to within $0.31. The weighted sum of the net-income change equals minus the combined federal and state revenue change to within $776, which is float32 noise.
- Per tax unit:
  - All 24,227 units with positive baseline `ctc` have a change in `ctc` that is an exact multiple of $800.
  - No unit has a negative change in `ctc`.
  - No unit's `ctc_value` rises by more than its `ctc`.
  - No unit's income tax rises by more than $1.

### Is the cost plausible? (independent raw `policyengine_us` run, 2026)

1. `ctc_qualifying_children` gives 71.90M weighted qualifying children. Of these, 68.70M meet the ID requirements, computed as the sum of `ctc_child_individual_maximum` divided by $2,200.
2. Multiplying by $800 gives an upper bound of $54.96B.
3. Applying the phase-out formula per unit, `max(0, max + 800n - phase_out) - max(0, max - phase_out)`, gives $53.2848B. That reproduces the Δ`ctc` in `national.json` to the dollar.
4. Of that, 58.9% is realized: $31.36B of `ctc_value`, and a $31.19B federal cost.
   - The rest goes unused because the reform does not change the $1,700-per-child refundable cap or the phase-in. A family gains only when its liability plus refundable CTC exceeds $2,200 per child.
   - I confirmed from `refundable_ctc.py`, and from the parameter diff, that neither limit changes.
   - The 36.9M weighted tax units with a higher CTC fits with 40.0M tax units that have qualifying children.
5. Take-up: a grep of `variables/gov/irs/credits/ctc/` for take-up variables (`takes_up`, `take_up`, `takeup`) returned nothing.
6. The $168M (0.54%) gap between -Δincome_tax and Δctc_value comes from `ctc_limiting_tax_liability`. I read it in `ctc_limiting_tax_liability.py`: it evaluates `income_tax_before_credits` in a `no_salt` branch with `salt_deduction` set to 0. Its documentation says it "Excludes SALT ... to avoid circular dependencies."
7. The raw `policyengine_us` path gives $31.27B, 0.24% above policyengine.py's $31.19B.

### Winners

- 19.23% of households (23.95M) gain more than $1, and 0% lose more than $1. I recomputed both exactly.
- The smallest change in net income is -$0.0078. That is float32 noise on 8 records, 27k weighted households.
- 29.02% of people live in households that gain.
- The average change is $250.27 across all households and $1,301.72 among households that gain.

### Deciles

- In `national.json`, the better-off, worse-off and no-change counts plus the 296k excluded households with negative income sum exactly to the 124,557,998 total.
- The decile averages agree with the policyengine-us `household_income_decile` variable to about 1e-10.
- My own cumulative-weight ranking (household weight times people) differs slightly at decile boundaries: 98.98% of households land in the same decile, and every decile average is within $3.
- The shape does not depend on the method. The bottom decile gets about $6 to $8, the peak is decile 7 at about $448, and the top decile gets about $257.
- The Gini (0.47437) reproduces when I use household weights.

### Poverty

- I recomputed SPM and deep SPM rates for all people and for children under 18 from the `spm_unit` poverty flags. They match to about 1e-16. All ages are integers, so `age <= 17` and `age < 18` select the same people.
- Rates equal headcount divided by population exactly, and the number lifted out equals the difference in headcounts.
- 0 people are pushed into poverty.
- Everyone lifted out of poverty is in a household that gains.
- Children lifted out: 189,306, which cuts the rate from 17.42% to 17.18% (-0.24 pp, 1.4% relative). People lifted out overall: 368,758.

## 5. `households_sample.json`

- It has 12,000 rows and the 10 documented columns, in the same order as `columns_doc`. No cell is null or NaN.
- Re-drawing `default_rng(20260924).choice(..., p=household_weight/sum)` reproduces every row exactly, with 6,976 unique households. That covers IDs, state, net income, change, weight, weight share and number of children.
- The decile field equals `household_income_decile` for 100% of rows.
- Every congressional district code starts with its row's state FIPS. The sample covers 51 states and 436 districts, and 29 rows have decile -1.
- Checks against the population (`households_per_dot` = 10,379.83):

| Measure | Sample | Population | Gap |
|---|---|---|---|
| Mean change | $251.76 | $250.27 | z = 0.27 |
| Share gaining | 19.57% | 19.23% | z = 0.95 |
| Children x households per dot | 77.99M | 77.95M | |
| Total change x households per dot | $31.36B | $31.17B | |

## Problems and caveats (none change a headline number)

1. **Low: the two computation paths differ by 0.24%** ($31.19B vs $31.27B). Show the headline as "$31 billion".
2. **Low: the decile `households_worse_off_weighted` counts are not zero** (9.8k, 12.4k and 4.8k in deciles 1 to 3). These are float32 noise with changes of -$0.004 to -$0.008. Do not display them. Nobody actually loses.
3. **Low: the bottom-decile average depends on the ranking method**: $5.95 in the policyengine.py output vs $7.95 with my own ranking.
4. **Low: the sample's decile means differ from the population by up to 11%** (decile 5: $366 vs $330). That is sampling noise. Take the decile bars from `national.json`, not the sample.
5. **Low: a diagnostics field is mislabeled.** `pepy_share_limiting_liability_exceeds_income_tax_before_credits_baseline` (0.953) compares against a different quantity than its name says. The direct comparison, `flagged_units_share_pepy_limiting_gt_actual`, is 0.891. Both are in `national.json`.
6. **Low: Utah's +$0.34M is listed but not explained in the `gap_explanation` text.** I traced it: all of it comes from a single sample tax unit whose federal itemization choice flips under the reform, which lowers its Utah taxpayer credit by the same amount. Six units flip nationally, 4k weighted.
