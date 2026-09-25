# PolicyEngine in 30 seconds

A 30-second video that follows one real rule from statute to code to one family to all 50 states and DC. Every statistic on screen is a PolicyEngine output computed for this video, and every quotation is verbatim from a primary source; map dots are placed at random within each household's assigned congressional district.

The rendered files are attached to the [latest release](../../releases/latest); `bun run render` rebuilds them into `out/`.

| File | Format |
|---|---|
| `out/policyengine-30s-4k60.mp4` | 3840×2160, 60 fps, H.264 + AAC (master) |
| `out/policyengine-30s-1080p60.mp4` | 1920×1080, 60 fps |
| `out/policyengine-30s-vertical-1080x1920.mp4` | 1080×1920, 60 fps (Reels, Shorts, TikTok) |
| `out/posters-16x9/`, `out/posters-9x16/` | 2× stills at 12.9, 18.9, 23.6 and 28.8 s for thumbnails |

## The story

| Time | Scene | Source of what's on screen |
|---|---|---|
| 0–4 s | All of 26 U.S.C. § 24 (2,686 words) pours in under "…if the laws be so voluminous that they cannot be read…" (Federalist No. 62, 1788); the camera dives to "$2,200" in § 24(h)(2) | `data/statute.json` — uscode.house.gov (current through 2026-09-18), cross-checked word for word against Cornell LII; Avalon Project for Federalist No. 62; 1788 from Founders Online |
| 4–8.5 s | "$2,200" flies into lines 7–26 of `policyengine_us/parameters/gov/irs/credits/ctc/amount/base.yaml`; the § 24(h)(2) chip docks on the line that cites it; "What if Congress raised the credit to $3,000?" with the reform dict exactly as passed to policyengine.py | `data/base.yaml` at the policyengine-us commit in `data/base.yaml.commit`; `data/household.json → meta.reform_dict_passed` |
| 8.5–14 s | "Take a married couple in Ohio," kids 4 and 8, one earner: the change in net income drawn across earnings from $0 to $120,000. "$0 below $42,200 in earnings. +$1,600 from $58,000." "The refundable part stays at $1,700 per child, so the extra $1,600 only offsets income tax the current credit leaves unpaid." | `data/earnings_sweep.json` (policyengine_us axes, one point per $250; cross-checked with policyengine.py at 7 earnings levels) |
| 14–20 s | Zoom out to all 50 states and DC: 12,000 weighted draws of households, each placed at random in its assigned congressional district; gainers light up grouped by gain (about $800, $1,600, then $2,400 and more); federal cost, share gaining, children out of poverty | `data/national.json`, `data/households_sample.json`, district shapes from `data/district_geography.json` |
| 20–25 s | The same dots settle on the baseline of each income decile; bars show average change per household | `data/national.json` → `deciles.by_decile` (full sample, not the 12,000 draws) |
| 25–30 s | The dots form the wordmark; tagline; provenance lines | — |

## The reform

One parameter: `gov.irs.credits.ctc.amount.base[0].amount` = 3,000 for 2026-01-01 to 2026-12-31 (current law: $2,200). Static microsimulation, no behavioral responses.

Computed with policyengine.py 6.1.1 (policyengine-us 2.2.1, policyengine-core 3.32.5) on the bundle's default US dataset, `hf://policyengine/populace-us/populace_us_2024.h5@populace-us-2024-spm-20260915` (sha256 `6496cc43…`). Exact pins: `data/compute/requirements.lock.txt`.

| On screen | Value | Field |
|---|---|---|
| Family, $0 region | $0 below $42,200 | `earnings_sweep.json` → `gain_starts_at_earnings` = $42,206 ($1 search); gain is exactly 0 at every grid point below $42,200 |
| Family, pinned point | $50,000 → +$780 | `earnings_sweep.json` → `spots["50000"].gain` |
| Family, the reason | gain = income tax beyond the current credit's $1,000 nonrefundable share, capped at $1,600 | `earnings_sweep.json` → `tax_liability`; asserted at all 481 grid points in `tools/adapt_outputs.py` |
| Family, full gain | +$1,600 from $58,000 | `full_gain_from_earnings` = $57,996; exactly 1,600 at every grid point from $58,000 to $120,000 (and up to $488,000, `gain_first_below_full_above_100k` = $489,000) |
| Federal cost in 2026 | $31 billion | `national.json` → `budget.federal_income_tax_revenue_change` = −$31.193B (raw policyengine-us path: $31.269B; shown at whole-billion precision because the two paths differ by 0.24%) |
| Households that gain | 19.2% | `winners.share_households_gaining_over_1usd` = 0.1923 |
| Fewer children in poverty | 189,300 | `poverty.spm.children_under_18.children_lifted_out` = 189,306 (Supplemental Poverty Measure); both paths agree to ~1e-9 |
| Average change per household, by decile | $6 … $448 … $257 | `deciles.by_decile[*].average_change_household_net_income` |
| Map dots | 12,000 weighted draws of 6,976 distinct households | `households_sample.json` meta (`numpy default_rng(20260924)`, p ∝ household_weight, with replacement) |

Independent verification notes: `data/verify_national.md`, `data/verify_statute.md`.

## Why the family is a curve

A single family at $60,000 gains exactly (3,000 − 2,200) × 2 = $1,600, which needs no model. Swept across earnings, the same family shows where the reform does not change the result: below $42,200 the credit it receives is limited by the 15% earnings phase-in or the $1,700-per-child refundable cap, and its tax liability is too small to absorb any more nonrefundable credit, so raising the maximum adds $0. The gain rises one-for-one with tax liability between $42,200 and $58,000. The national results show the same pattern: the bottom income decile gains $6 on average.

## What was left out, and why

- **Congressional districts.** `data/districts.json` holds PolicyEngine's district breakdown (`compute_us_congressional_district_impacts` in policyengine.py) and `data/district_layout.json` a hex cartogram, but the national sample gives a median effective sample size of about 20 households per district; the spread within states ($105 sd) exceeds the spread between states ($58 sd), so a district map would mostly show sampling noise. The district-calibrated `populace_us_2024_acs_local` dataset (1.6M households) is the right source for that scene; it was not run for this cut (several hours of compute for a 1.6M-household file).
- **Household count.** The model's weighted count (124.6M) was not checked against Census, so the caption states scope ("Now all 50 states and DC.") and no per-dot household count appears.
- **The 2021 comment.** Line 17 of the parameter file ("Rose to $3,000/$3,600 in 2021. See arpa.yaml.") stays visible and unemphasized: the 2021 credit was also fully refundable, so highlighting it would imply an equivalence the two policies do not share.

## Invariants

These hold for every input, and `bun run test` plus CI check them (`tests/`, `.github/workflows/ci.yml`):

| Property | Kind | Test |
|---|---|---|
| The family's gain is income tax beyond today's $1,000 nonrefundable share, capped at $1,600, at all 601 computed earnings points | accounting identity | `test_family_curve.py` |
| 0 ≤ gain ≤ 2 × ($3,000 − $2,200); gain never falls as earnings rise below $150,000; the refundable part never exceeds 2 × $1,700 | bounds, monotonicity | `test_family_curve.py` |
| The change in net income equals the change in the CTC; the sweep at $60,000 equals the separate household run; `policyengine.py` agrees with the sweep at random earnings (slow, local) | differential | `test_family_curve.py` |
| The plotted points are exactly the computed points; "$0 below $42,200" and "+$1,600 from $58,000" hold at every point | differential, exhaustive | `test_family_curve.py` |
| Every stat and decile bar equals the national run at its stated precision; the reform card equals the dict PolicyEngine received; the code panel, statute and quote are verbatim; every dollar figure in the family text traces to the data | differential | `test_published_numbers.py` |
| Rebuilding `video.json` from `data/` is a no-op | round-trip | CI |
| Easings map 0→0 and 1→1 and (except the intended `outBack` overshoot) stay in [0, 1] and never decrease; progress and envelopes stay in [0, 1]; the seeded PRNG is deterministic and in [0, 1); number formatting round-trips | property-based (fast-check) | `util.test.js` |
| A fresh page and a page that played the film up to *t* draw identical pixels, in both layouts | determinism | `tools/determinism.mjs`, CI |
| Panning keeps power; synthesis is bit-identical across runs; the master is −14 ± 0.5 LUFS with true peak ≤ −1 dBTP and clean edges | property-based (Hypothesis), mastering | `test_soundtrack.py` |

## How it's made

- `site/` — a deterministic HTML/canvas timeline. `window.renderAt(t)` draws the frame at time `t`; nothing depends on wall-clock time or `Math.random`.
- `tools/render.mjs` — Playwright drives headless Chromium frame by frame. `--stream out.mp4` pipes PNG screenshots straight into parallel ffmpeg encoders and joins the segments, so no frames touch the disk.
- `tools/soundtrack.py` — the score is synthesized with numpy/scipy at 120 BPM (D minor; Bb → C → F under the wordmark), mastered to −14 LUFS integrated with a 4× oversampled true-peak limiter at −2 dBTP. Sound effects come from `events.json`, which the page exports from the same timeline, so each click and soft mallet note lands on the frame that causes it; gainer notes rise in pitch with the $800 step, and the family curve brightens a held chord as the gain rises.
- `tools/determinism.mjs` — proves a fresh page and a page that played the film up to *t* render identical pixels at 11 timestamps, in both layouts. Streaming workers start mid-film, so this is what makes parallel rendering safe.
- `tools/adapt_outputs.py` → `tools/build_video_data.py` — turn the raw PolicyEngine outputs into `data/video.json`, the only data the page reads. If any input is missing the page paints a striped MOCK DATA banner on every frame.

### Rebuild

```bash
bun install
bun run data          # PolicyEngine outputs in data/ -> data/video.json (asserts every on-screen claim)
bun run build         # site/main.js -> site/bundle.js
bun run score         # timeline cues -> audio/events.json -> audio/score.wav
bun run determinism   # fresh-page frames == played-through frames, both layouts
bun run render        # 4K/60 master, 1080p/60, 9:16 (supersampled from 2x), posters
bun run check         # specs, loudness, true peak, single-frame glitch scan
bun run test          # invariants (Vitest + fast-check, pytest + Hypothesis)
```

Recomputing the PolicyEngine outputs themselves (`data/compute/*.py`) needs the pinned environment in `data/compute/requirements.lock.txt` and the dataset from Hugging Face; each script's docstring gives its run command.

Preview any moment in a browser: `node tools/serve.mjs 4317`, then open `http://127.0.0.1:4317/site/index.html?t=17.5` (or `?play=1`, or `?w=1080&h=1920` for portrait).

## Credits

- PolicyEngine wordmark (`site/logo-*.svg`): from `PolicyEngine/policyengine-app-v2`. The PolicyEngine name and logo are PolicyEngine trademarks and are not covered by this repository's licenses.
- `data/base.yaml`: verbatim from `PolicyEngine/policyengine-us` (`policyengine_us/parameters/gov/irs/credits/ctc/amount/base.yaml`) at commit 2fbd777, AGPL-3.0.
- Statute text (`data/statute.json`): 26 U.S.C. § 24 from the Office of the Law Revision Counsel (uscode.house.gov), a US government work, cross-checked against the Legal Information Institute, Cornell Law School (law.cornell.edu). Fetched pages are not redistributed; `statute.json` records their URLs and sha256.
- Federalist No. 62 (1788, public domain) as published by the Avalon Project, Lillian Goldman Law Library, Yale Law School; the 1788 date is from Founders Online (National Archives).
- Microdata: PolicyEngine `populace-us` (`populace_us_2024.h5@populace-us-2024-spm-20260915`, MIT, huggingface.co/datasets/policyengine/populace-us). `data/households_sample.json` holds derived fields for 6,976 of its household records.
- Congressional district boundaries (`data/district_geography.json`, used to place dots): US Census Bureau cartographic boundary file `cb_2024_us_cd119_20m` (public domain), via `PolicyEngine/policyengine-app-v2`.
- Congressional district hex layout (`data/district_layout.json`; kept for the record, not shown in the video): House hexmap v3.1 by Daniel Donner, Daily Kos Elections / The Downballot (the-downballot.com; original release dkel.ec/map), via `PolicyEngine/snap-district-map` and `PolicyEngine/policyengine-app-v2`, licensed CC BY 4.0. Changes: district IDs re-keyed to PolicyEngine GEOIDs, centroids and bounding boxes added; polygons unmodified.
- Fonts: Inter, JetBrains Mono and Newsreader (SIL Open Font License, via Fontsource). US state shapes: `us-atlas` (Census cartographic boundaries). The score is synthesized by `tools/soundtrack.py`.

## License

Code in this repository is released under the [MIT License](LICENSE). Original text and figures are released under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) with attribution to PolicyEngine. Third-party material keeps its own terms (see Credits): `data/base.yaml` (AGPL-3.0), `data/district_layout.json` (CC BY 4.0, Daily Kos Elections / The Downballot), and the PolicyEngine name and logo.
