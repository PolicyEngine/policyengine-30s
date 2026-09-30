# UK cut: data

`data/uk/video.json` is the only file the page reads for the UK cut (`site/index.html?country=uk`). It has the same schema as `data/video.json`, plus the UK fields the page reads: `country`, `currency`, `locale`, `captions`, `reform.chip`, `household.figures`, `household.axis_title`, `code.repo` and `statute.wall_label`. It also carries two optional hints, `household.curve.yMax` and `household.curve.yTicks`. The UK gain tops out at £972, so the US axis (0 to 1,800, with ticks at 800 and 1,600) would squash the curve.

**National figures** come from a PolicyEngine run on UK survey microdata: the enhanced Family Resources Survey 2024-25 (`enhanced_frs_2024_25`, policyengine-uk-data 1.56.16, the dataset policyengine.py 6.2.0 certifies for policyengine-uk 2.102.3), uprated to 2026. See "The national run" below. The microdata and anything record-level derived from them stay in `data/uk/private/`, which is git-ignored: the UK Data Service End User Licence does not allow redistribution. Only aggregates are committed (`national.json`). The 12,000 draws behind the map's dots are written to `private/sample_video.json`, and `video.json` only names that file. A checkout without it (a fresh clone, CI) renders placeholder dots under the MOCK DATA banner.

## Rebuild

From the repo root, in order:

```bash
# 1. statute, quote, parameter file (legislation.gov.uk, archive.org, gh api) -> statute.json, quote.json, amount.yaml
uv run --no-project --with lxml==6.1.3 python tools/uk/fetch_sources.py            # --no-fetch rebuilds from raw/sources
# 2. the family curve on policyengine.py 6.2.0's pinned policyengine-uk, then on the previous pin (6.1.1)
uv run --no-project --python 3.13 --with-requirements tools/uk/requirements.pe-6.2.0.lock.txt \
    python tools/uk/earnings_sweep.py --out data/uk/earnings_sweep.json
uv run --no-project --python 3.13 --with-requirements tools/uk/requirements.pe-6.1.1.lock.txt \
    python tools/uk/earnings_sweep.py --out data/uk/compute/earnings_sweep_pe-6.1.1.json
# 3. the same family through policyengine.py's household calculator
uv run --no-project --python 3.13 --with-requirements tools/uk/requirements.pe-6.2.0.lock.txt python tools/uk/crosscheck.py
# 4. constituencies (written by the geography build; see its docstring)
uv run --with pyproj --with shapely --with pypdf tools/uk/build_uk_geography.py
# 4b. the same family at £400 and £600 rent (README caveat; asserts £500 matches step 2)
uv run --no-project --python 3.13 --with-requirements tools/uk/requirements.pe-6.2.0.lock.txt python tools/uk/rent_sensitivity.py
# 4c. the national run (needs HF_TOKEN with access to policyengine/policyengine-uk-data-private); writes
#     national.json and the git-ignored private/households_sample.json
uv run --no-project --python 3.13 --with-requirements tools/uk/requirements.pe-6.2.0.lock.txt python tools/uk/national.py
# 5. assemble and assert every on-screen statement
uv run --no-project --with pyyaml python tools/uk/build_uk_video.py
# invariants
uv run --no-project --with pytest --with hypothesis --with pyyaml --with pyproj --with shapely --with pypdf pytest tests/uk
```

The compute scripts build single households from a `situation` and never load a dataset. `uk_family.no_microdata()` enforces this. It points the Hugging Face cache at an empty temporary folder, turns the hub offline and unsets every token, then checks that the folder is still empty after the run. Any code path that tried to reach the UK microdata would fail instead of silently downloading it or reading a cached copy.

## Every on-screen string and its source

| Scene | On screen | Source | Check |
|---|---|---|---|
| Quote | "…made more plaine and short, to th’intent / that men might the better understaund them…" (the page breaks before " that ") | J. G. Nichols (ed.), *Literary Remains of King Edward the Sixth*, vol. 2 (Roxburghe Club, 1857), p. 486, "Discourse on the Reformation of Abuses, 1551", §2 "Devising of good lawes". Public domain. archive.org/details/literaryremainso0002john/page/486 | The fragment appears in the OCR of two separate scans: the Internet Archive copy and Cornell `cu31924091758312` (straight apostrophe). I read the page image `raw/sources/edward_vi_p486.jpg` this session, and wording, spelling and punctuation match. The fragment is 14 contiguous words of the sentence recorded in `quote.json`. |
| Quote | "Edward VI · 1551" | The page's running head reads "[A.D. 1551.". Nichols attributes the discourse to the king. | Page image |
| Wall | Income Tax Act 2007, Part 3, from its heading through the end of Chapter 3 (ss. 33–55): 264 lines, 4,204 words | legislation.gov.uk revised XML `ukpga/2007/3/part/3/data.xml` (s. 35 valid from 2026-09-16, modified 2026-09-18). OGL v3.0. | All 264 lines appear verbatim in the site's HTML view of Part 3 once change marks are removed (`statute.json → html_crosscheck`). Wording repealed but still shown for savings (s. 37) is included, because the site shows it. |
| Wall label | "Income Tax Act 2007, Part 3, Chapters 1–3" | Scope of the excerpt | — |
| Dive | "(1) An individual who makes a claim is entitled to a personal allowance of £12,570 for a tax year if the individual meets the requirements of section 56 (residence etc)." | s. 35(1), from the section's own XML (a second fetch) | It appears once in the wall, at `wall_h2_offset` 1771, and "£12,570" appears once in the wall. The s. 35 page says "There are currently no known outstanding effects". Finance Act 2021 s. 5(2), as amended, specifies £12,570 for 2026-27. |
| Chip | "Income Tax Act 2007, s. 35" | Citation | — |
| Code | lines 2–22 of `policyengine_uk/parameters/gov/hmrc/income_tax/allowances/personal_allowance/amount.yaml`. Value line 7 is `2021-04-06: 12_570`, the entry in force for 2026-27. Reference line 21 is `- title: Income Tax Act 2007 s. 35`. | `PolicyEngine/policyengine-uk` main at `412b25aa` (2026-09-25T16:14Z), fetched with `gh api`. AGPL-3.0. Saved as `amount.yaml` and `amount.yaml.commit`. | The file is byte-identical (sha256 `a99cd925…`) to the copy installed in policyengine-uk 2.102.3 and in 2.90.2, so the panel shows the file the model ran. The value token equals the model's baseline 12,570 written as `12_570`. |
| Captions | "PolicyEngine turns the law into code." / "What if Parliament raised the personal allowance to £15,000?" | "personal allowance" is the YAML label. £15,000 is the value in the reform dict. | — |
| Reform | `{"gov.hmrc.income_tax.allowances.personal_allowance.amount": {"2026": 15000}}` | Exactly the dict passed to `policyengine_uk.Simulation` and to `pe.uk.calculate_household` | Each run asserts that the parameter the model read for 2026 moved from 12,570 to 15,000. policyengine-uk reads a bare year as the fiscal year, so 2026 is 2026-27. A key of `2026-04-06` would silently leave 2026-27 on current law. |
| Chip | "Personal allowance £12,570 → £15,000" | YAML label; the model's baseline value; the reform value | — |
| Family | "Take a single parent in Manchester · two kids, ages 4 and 8 · housing association rent of £500 a month" | The inputs in `earnings_sweep.json → meta.family_inputs`: a parent aged 30; children aged 4 and 8; `local_authority` MANCHESTER; `tenure_type` RENT_FROM_HA; `rent` 6,000 a year | The £500 rent is illustrative and not sourced. See "Not verified". |
| Chart | "Change in net income, 2026-27": the curve from £0 to £80,000, one computed point per £250 (321 points) | `earnings_sweep.json`. The measure is `hbai_household_net_income`. | The plotted points equal the computed points. |
| Pin | "£60,000 +£972" | Gain at £60,000 = £972.00, the top plateau of the chart | `build_curve` asserts the gain is £972.00 at every plotted point from £52,700 to £80,000 |
| Line 1 | "+£219 from £15,000 to £48,000." | The gain is exactly £218.70 (0.45 × £486), shown to the pound. The family is on Universal Credit in both runs. | Holds at all 33,001 £1 points (and at 133 plotted points). The exact flat stretch is £15,000 to £48,001. |
| Line 2 | "+£486 from £48,700 to £50,270." | £486.00 = 20% × £2,430, with no UC in either run | Holds at all 1,571 £1 points (and 7 plotted points). The exact flat stretch is £48,677 to £50,270. £50,270 = £12,570 + the £37,700 basic rate limit. FA 2021 s. 5(1) sets that limit for 2026-27, and it equals the model's threshold. |
| Note | "Universal Credit counts pay after tax, so it takes back 55p of each £1 of the tax cut." | Code, read this session in both versions: `uc_earned_income` = max(0, earnings − work allowance − `benunit_tax` − pension contributions), where `benunit_tax` sums `income_tax` and `national_insurance`, and `uc_income_reduction` = `reduction_rate` (0.55) × earned income. Law: UC Regs 2013 reg. 22(1)(b)(ii) "55% of the amount by which that earned income exceeds the work allowance"; reg. 55(5)(b) deducts "income tax or primary Class 1 contributions". | Wherever the family is on UC in both runs and the tax cut is positive, ΔUC = −0.55 × tax cut and UC earned income rises by the whole tax cut. That holds at all 35,431 such £1 points. NI never changes. |
| Nation | "Now all of the UK." | Scope. The map draws all 650 July 2024 Westminster constituencies (`geography.json`, ONS, OGL v3.0). | — |
| Nation | "£22 billion net cost in 2026-27", "75.9% of households gain", "40,000 fewer children in poverty" | `national.json`: net Exchequer cost £22.14bn (income tax forgone £22.82bn, less £0.60bn Universal Credit and £0.08bn Pension Credit withdrawn); 75.92% of households gain over £1; children in absolute poverty before housing costs fall from 16.32% to 16.06%, 39,996 children | `test_national_figures_are_the_run`, `test_national_accounting_closes` |
| Map | "Each dot: a household drawn by weight, placed at random in its assigned constituency (in Northern Ireland, anywhere in Northern Ireland)" | 12,000 draws by household weight (`numpy default_rng(20260925)`, 5,429 distinct households). Great Britain households carry `constituency_code_oa` in the dataset; Northern Ireland households (2.5% of households, 282 draws) carry none, so their dots fall anywhere in NI. | `test_every_draw_has_a_place` (local), `test_the_survey_sample_stays_out_of_git` |
| Deciles | "Average change per household by income decile", £168 in the lowest decile to £1,638 in the highest | policyengine.py `economic_impact_analysis`: households ranked by baseline household net income (not equivalised), each weighted by household weight × household size, and cut into tenths of people. Households with negative baseline income (460 records, 217,800 weighted households, all in the bottom tenth) are then left out of every bar, so the lowest decile holds 9.5% of people rather than 10%. Each bar averages households' change in net income by household weight. `national.py` rebuilds the groups from that definition, independently of policyengine.py, and they match for all 52,846 households (`national.json → deciles.grouping_check`); the averages are then recomputed from the household rows to the penny | `test_national_figures_are_the_run` |
| Curve tag | "policyengine.py 6.2.0 · static", bottom right of the chart | The version the sweep recorded. "Static" is checked: only `income_tax` and `universal_credit` move in the exact decomposition of net income, so earnings do not respond. The same curve on the previous pin (policyengine.py 6.1.1, policyengine-uk 2.90.2) is in `compute/`. | `test_curve_tag_names_the_run_that_drew_it` |
| Map tag | "policyengine.py 6.2.0 · enhanced_frs_2024_25 · static" / "poverty: absolute, before housing costs" / "Source: Office for National Statistics licensed under the Open Government Licence v.3.0" / "Contains OS data © Crown copyright and database right 2024", bottom right of the map | ONS's two required statements for its boundaries, verbatim from `geography.json → meta.attribution_notes` | `test_mock_parts_are_flagged_and_placeable` |
| Close | Wordmark, tagline, "Free and open source · policyengine.org"; nothing below | — | — |
| Home dot | `lonlat` [−2.19, 53.492] | Area-weighted centroid of Manchester Central (E14001352) in `geography.json`. The dot marks an example household, not a located one. | — |

## How the curve was checked

- **Two grids.** The sweep computes every £1 from £0 to £80,000 (80,001 points). There it finds each flat stretch and where UC ends: today's UC last pays at £48,676 and the reform's at £48,001. It then words the lines from those facts (`tools/uk/curve_claims.py`). A lower bound rounds up to the next £100 and an upper bound down to the next £10, so each stated range sits inside the computed stretch. Each sentence is asserted at all 80,001 points, and again at the 321 plotted points when the video file is built.
- **Differential.**
  - policyengine-uk 2.90.2 (the previous pin, in policyengine.py 6.1.1) matches 2.102.3 (the pin in policyengine.py 6.2.0) to £0.00 on every recorded variable at every plotted point, with identical £1 facts. Both run on policyengine-core 3.32.5.
  - policyengine.py's `pe.uk.calculate_household` with an earnings axis matches the sweep at all 321 points, to within £0.0013 on the gain and £0.005 on income tax.
  - Single households at 16 breakpoints and 8 seeded random earnings reproduce the £1 facts: 12,570 / 12,571, 48,001 / 48,002, 48,676 / 48,677, 50,270 / 50,271 and 52,699 / 52,700. Results are in `compute/crosscheck.json`.
- **Invariants** (`tests/uk/test_uk_video.py`, `tests/uk/test_uk_geography.py`):
  - net income change = tax cut + ΔUC at every point, and 0 ≤ gain ≤ tax cut;
  - the gain never falls as earnings rise;
  - the reform card is the dict the model received;
  - the statute, code and quote are verbatim;
  - every £ figure on screen traces to a computed or sourced number;
  - every national number traces to `national.json`, whose accounting identity closes, and the survey sample stays out of git;
  - rebuilding `video.json` is a no-op;
  - property-based tests of the range rounding and plateau detection.

## Survey data: citation and licence

The national figures rest on the Family Resources Survey, cited as its UK Data Service catalogue entry specifies (read 2026-09-27, https://datacatalogue.ukdataservice.ac.uk/studies/study/9563):

> Department for Work and Pensions. (2026). Family Resources Survey, 2024-2025. [data collection]. UK Data Service. SN: 9563, DOI: http://doi.org/10.5255/UKDA-SN-9563-1. © Crown copyright.

The End User Licence (clause 11) requires that citation in any publication "whether printed, electronic or broadcast", so the film carries it in the small print under the decile chart. policyengine-uk-data's enhancement also imputes variables from the Wealth and Assets Survey, the Living Costs and Food Survey, the Effects of Taxes and Benefits data and HMRC's Survey of Personal Incomes (its `docs/imputations.md`; the code loads `spi_2022_23`). The package does not pin those collections' study numbers, so their citations are left to PolicyEngine's registered user. Clause 12 also asks for the bibliographic details of published work to be sent to the UK Data Service.

## The national run

`tools/uk/national.py` runs policyengine.py 6.2.0's UK flow on its certified dataset:
- **Dataset.** `enhanced_frs_2024_25.h5` from `policyengine/policyengine-uk-data-private` at 1.56.16. Its sha256 (`e433e532…`) matches the installed policyengine.py's release manifest, which certifies it for policyengine-uk 2.102.3. `ensure_datasets` uprates it to 2026 with the installed policyengine-uk: 52,846 households, 113,617 people, 31.46 million weighted households. `ensure_datasets` reuses any uprated file it finds, so the script stamps the file with the policyengine-uk version that built it and rebuilds it when the version differs.
- **Reform.** Personal allowance £15,000 from 2026-01-01. policyengine-uk labels fiscal year 2026-27 as 2026 and reads it at 1 January; a start of 6 April 2026 leaves the run on current law (checked). The run asserts the allowance the model applied rose to at most £15,000 (from at most £12,570) and fell for nobody. 1,580 records have no allowance in either run; the run asserts that every one has adjusted net income of at least £130,000, where the £100,000 taper removes even a £15,000 allowance (`national.json → allowance`). Of the 113,617 records, 111,917 gain the full £2,430 and 120, on the taper, gain part of it.
- **Static.** No labour-supply elasticities are set.
- **Checks.** Income tax and Universal Credit changes agree between policyengine.py's programme statistics and the script's own weighted sums. Decile groups rebuilt from their definition match policyengine.py's for every household, and decile averages agree with a recomputation from household rows to the penny. Households' total gain equals the net Exchequer cost within 0.5%.

## Not verified, and caveats

- **The £500 a month rent** is an illustrative input. It does not change the £219 and £486 levels, but it does move where UC runs out, and so the £48,000 and £48,700 in the lines. `tools/uk/rent_sensitivity.py` reruns the family at £400, £500 and £600 on a £10 grid (`compute/rent_sensitivity.json`). Today's UC ends at £45,640 on £400 rent and £52,050 on £600, and on £600 the £486 stretch disappears: under the reform the family still gets UC at £50,270, where today's basic rate band ends (its UC runs out at £50,970), so no earnings level passes them the whole £486. At £500 the £10 grid reproduces the £1 facts of the main sweep, which the script asserts.
- **Things the model does not include:**
  - Free school meals (no formula), so any cliff where UC ends is missing.
  - Council Tax Reduction, which is not simulated for Manchester. Council tax is set to £0 in both runs.
  - Monthly UC assessment: annual amounts stand for steady monthly pay.
- **The basic rate** (20%), and the 40% that gives the £972 step, are the model's values. They were not re-read from the legislation. The £972 step is on the chart but not in the text.
- **"1551"** rests on Nichols's running head and item title. The manuscript itself was not examined.
- **Rounding on screen.** "+£219" is £218.70 rounded to the pound. Line 1 ends at £48,000 because the exact stretch ends at £48,001, and upper bounds round down to £10. At £48,000 the reform still pays £0.48 a year of UC, so "on UC in both runs" holds there only just.
- **The poverty measure.** The child poverty stat uses PolicyEngine's default measure, absolute poverty before housing costs. Relative poverty tracks inequality rather than poverty: policyengine-uk draws its relative line at 60% of each run's own median, so a reform that raises the median raises the line with it. Measures after housing costs subtract housing spending, which is partly discretionary (a flat or a mansion), and international poverty measurement works on income before housing costs.
- **The absolute line.** policyengine-uk 2.102.3 draws the line as HBAI has since March 2026: 60% of the FYE 2025 median before housing costs, £431.69 a week for a couple with no children (HBAI table 2.4ts), held constant in real terms. For 2026-27 the model uprates it by the OBR's CPI forecast to £456.63 a week (`household.poverty.absolute_poverty_threshold_bhc`); HBAI would use its own CPI variant, which the OBR does not forecast. A household is in absolute poverty when its equivalised HBAI net income before housing costs falls below the line (`in_poverty_bhc`). policyengine.py 6.1.1 pinned policyengine-uk 2.90.2, which used the FYE 2011 line for every year: 60% of the 2010/11 median, £251.40 a week, held at that through 2019, set at £305.70 from 2020 and uprated by CPI from there, to £403.42 a week in 2026-27. HBAI now keeps the FYE 2011 reference only for years before FYE 2022. That lower line put 11.78% of children in absolute poverty before housing costs and gave 59,863 fewer children under the reform. The four measures, children under 18, on policyengine-uk 2.102.3:

  | Measure | Baseline | Reform | Change |
  |---|---|---|---|
  | Absolute, after housing costs | 23.73% | 23.16% | 88,179 fewer |
  | Absolute, before housing costs (on screen) | 16.32% | 16.06% | 39,996 fewer |
  | Relative, after housing costs | 30.14% | 30.97% | 127,143 more |
  | Relative, before housing costs | 22.04% | 22.77% | 113,014 more |
- **Households that lose.** 12 records (19,514 weighted households, 0.06%) lose over £1. In every one, benefits fall by more than taxes do (checked household by household): Pension Credit falls for 11 of them, Housing Benefit for 7, Winter Fuel Allowance for 4, Council Tax Benefit for 3, and Universal Credit and Scottish Child Payment for 1 each (`national.json → winners.losers`). Over those records, income tax falls by £5,532 and Pension Credit by £1,627 (unweighted). The other programmes' sums rest on fewer than 10 of the households, so, like minimums and maximums, they are not published (`tools/uk/disclosure.py`). Households' total gain (£22.128bn) sits £11.7m under the net cost (£22.139bn). Housing Benefit, which is outside policyengine.py's UK programme list, falls by £10.1m (weighted, `budget.housing_benefit_change`) and accounts for most of the gap; the remaining £1.6m is other programmes outside the list.
- **Net cost** counts income tax, National Insurance and the benefits in policyengine.py's UK programme list. National Insurance does not move.

## Layout notes for `site/` (not edited from here)

- **Word count.** The page counts `\S+` tokens, so its label will read 4,369 words. That includes 165 "." tokens from the published ". . . ." dot padding. The count excluding them is 4,204 (`statute.words`). The dots are kept exactly as legislation.gov.uk publishes them.
- **Code panel.**
  - Line 14 (the OBR href, 77 characters) and line 19 (`uprating: …consumer_price_index`, 69 characters) overflow the 960 px panel.
  - The file path overflows the title bar.
  - `arpaLine` is `null`.
- **Reform card and caption.**
  - The parameter path (56 characters) is clipped in the reform card.
  - The "What if Parliament raised the personal allowance to £15,000?" caption runs to 5 lines at 78 px and overlaps the reform card.
- **Chip.** "Personal allowance £12,570 → £15,000 in 2026-27" is longer than the US chip and collides with the decile caption.
- **Chart.** The US y-axis (ticks +800 and +1,600) needs `curve.yMax` / `curve.yTicks`.
- **Map dots.** The dot light-up steps use `round(gain / 800)`, which is US-specific.

## Files

| File | What |
|---|---|
| `video.json` | the page's data (≈1.1 MB, mostly `cdGeo`) |
| `earnings_sweep.json` | the family at every £250 from £0 to £80,000. It holds earnings, gain, income tax, NI, UC, UC earned income and more, in both runs and as changes, plus the £1 facts and on-screen claims under `fine`. |
| `compute/earnings_sweep_pe-6.1.1.json`, `compute/crosscheck.json`, `compute/build_report.json` | differential runs (the previous pin; policyengine.py's household calculator) and the last build's report |
| `statute.json`, `quote.json`, `amount.yaml`, `amount.yaml.commit`, `code_source.json` | primary sources as used, with URLs, sha256 and retrieval times |
| `geography.json`, `geography_check.json` | constituencies, from the geography build (`tools/uk/build_uk_geography.py`) |
| `raw/sources/` | fetched legislation XML and HTML, OCR texts and the page image, with `fetch_log.json` (3.3 MB). The rest of `raw/` belongs to the geography build. `data/uk/raw/` is git-ignored; `fetch_sources.py` and the geography build re-fetch it. The contents are OGL v3.0, public domain and ONS OGL. |

## Licences

- Statute: contains public sector information licensed under the Open Government Licence v3.0 (legislation.gov.uk). No Royal Arms or legislation.gov.uk branding is shown.
- Quote: public domain.
- `amount.yaml`: AGPL-3.0, from PolicyEngine/policyengine-uk.
- Constituency boundaries: Source: Office for National Statistics licensed under the Open Government Licence v.3.0; contains OS data © Crown copyright and database right 2024.
