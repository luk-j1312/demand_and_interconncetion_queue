# EIA-930 Data Quality: Decisions & Method (AI-GENERATED SUMMARIES INCLUDED)

*Project: Data-Center Demand Growth & Generation-Interconnection Queue Congestion — Luke W. Jones*
*Written 2026-08-05. Covers the data-quality work on the EIA-930 hourly demand pull (Phase 1).*

This is the backing record for the technical appendix. It documents what was excluded
from the demand series, the method that identified it, the calibration evidence, and the
approaches that were tried and rejected. Everything here should survive a reviewer
grilling it.

---

## Bottom line

**14 hours of 266,181 (0.0053%) were excluded as corrupt. 13 are PJM, 1 is SWPP. ERCO
and MISO required no exclusions at all.**

The exclusions are identified by three rules, all expressed as ratios against each
balancing authority's **own rolling history** — there are no absolute MW ceilings
anywhere in the method. Raw data is never modified; cleaning is a separate derived step
with a full audit trail.

The correction matters more than 0.0053% suggests, because the damage was concentrated
rather than diffuse. PJM's mean hourly demand reads **154,050 MWh as-reported vs.
92,219 MWh clean** — the as-reported figure is inflated 67%, and essentially all of that
(99.97%) comes from just the three 32-bit-overflow hours on 2021-10-19, out of 13 PJM
rows excluded in total. This is in the largest region in the study, while ERCO and MISO
are unaffected to the megawatt. Left in, these hours would have manufactured a spurious
cross-regional difference in precisely the variable the analysis turns on.

---

## Pipeline

| Stage | Script | Output |
|---|---|---|
| Pull | `pull_eia930_demand.py` | `data/raw/eia930_hourly_demand.csv` — as-reported, 266,181 rows, never modified |
| Detect | `eia930_quality.py` | the rules; imported by both other scripts |
| Clean | `clean_eia930.py` | `data/processed/eia930_hourly_demand.csv` (266,167 rows) + `excluded_hours.csv` (14 rows) |
| Inspect | `plot_demand_week.py` | `figures/` — reads processed, falls back to raw |
| Panel | `build_queue_panel.py` | `data/processed/queue_outcomes_panel.csv` (108 region-years) + `queue_date_coverage.csv` (8 rows) |
| Pre-test | `plot_withdrawal_parallel_trends.py` | `data/processed/withdrawal_rates.csv` + `figures/withdrawal_rate_parallel_trends.png` |
| Analysis set | `build_analysis_panel.py` | `data/processed/analysis_panel.csv` (23 rows) + `figures/demand_growth_vs_clearance.png` |
| Diagnostics | `plot_analysis_diagnostics.py` | `figures/diag_clearance_by_year.png`, `diag_scatter_by_year.png`, `diag_scatter_no_ercot2022.png` |
| Diag. models | `fit_diagnostic_models.py` | `data/processed/diagnostic_model_results.csv` |

**Two structural choices worth stating explicitly.**

*Raw stays immutable and cleaning is separate.* Re-downloading 266k rows takes ~10
minutes and hits intermittent 503s from EIA's API. The cleaning rule was revised twice
on the day it was written, and decoupling meant no re-pull was needed for either
revision. It also means any exclusion can be re-examined or reversed against an
untouched original — which is what makes the exclusions auditable rather than merely
asserted.

*The detection rule lives in exactly one module.* Both the pull script (which reports)
and the clean script (which drops) import from `eia930_quality.py`. If the thresholds
lived in two places, the hours we *report* and the hours we *exclude* could silently
diverge — a discrepancy a reviewer would catch and we couldn't explain.

---

## The decision: drop, don't interpolate or substitute

**Decision.** Drop the hours the rules identify. Do not interpolate them, and do not
switch to EIA's adjusted/imputed series to repair them.

**Reasoning.**
- 14 hours out of 266,181 is 0.0053% of the data. What this project needs from EIA-930
  is multi-year *regional growth rates*, not hour-by-hour dynamics, so losing a handful
  of specific identified hours has no meaningful effect on an annual or multi-year
  aggregate.
- Dropping is the easiest choice to defend. "We excluded these 14 timestamps, here is
  the detection method and the exact values" is a fast check for anyone reviewing the
  work. Every exclusion is written to `data/processed/excluded_hours.csv` with the test
  that fired, the baseline compared against, and the ratio.
- Interpolating would mean inventing values the analysis does not need.
- EIA's own adjusted series is worth knowing exists as a fallback, but pulling in a
  second, less-transparent data pipeline to fix a handful of rows solves a bigger
  problem than the one we have.

**Why no absolute ceilings.** Every threshold is a ratio against a rolling baseline, so
the rule scales with each region as it grows. This is the central design constraint: a
fixed MW ceiling in a project *about demand growth* would eventually be crossed by real
load and start silently deleting good data — the exact failure mode the project is
trying to measure.

---

## The three tests

Each catches a different failure mode; none subsumes the others. Two of the corrupt
hours are invisible to the spike test but caught by peak-level; one is the reverse.

### 1. Peak-level — is this hour above anything this BA has plausibly ever hit?

Compare each hour to the **99.9th percentile of its own BA over a centred two-year
window** — the region's demonstrated peak *level* around that time. Flag above **1.15×**.

Real load grows gradually, so a genuine record beats the recent peak level by a few
percent; corruption beats it by tens of percent. Calibration across all four BAs:

| | ratio to own 2-yr p99.9 |
|---|---|
| Highest **legitimate** annual peak — ERCO 2026 record 1.02×, MISO 2024 1.04×, SWPP 2026 1.04×, PJM 2025 1.05× | **1.05×** |
| Lowest **corrupt** hour | **1.21×** |

1.15 sits in that gap with ~10pp of headroom on the legitimate side. All four BAs
independently agree on where real peaks sit relative to their own history, which is what
makes the threshold defensible rather than tuned to one region.

The window is **centred, not trailing**. A sustained step up in load therefore raises the
baseline from both directions and is not flagged — only an isolated spike above the
surrounding two years trips it. This is retrospective analysis, so using later data in
the baseline is legitimate, and it removes the cold-start problem a trailing window would
have in 2019.

### 2. Isolated-spike — is this hour discontinuous with the hours either side?

Compare each hour to the **mean of the immediately adjacent hours**. Flag above **1.35×**.

This test exists because the peak-level test has a blind spot found during validation: a
spike landing just *under* the annual peak is indistinguishable from a genuine new record.
Electricity demand is physically continuous — aggregate load cannot rise 50% in one hour
and fall back the next.

| | ratio to mean of adjacent hours |
|---|---|
| Typical legitimate hours (ERCO and MISO never exceed 1.06× even on the steepest morning ramps) | 1.00–1.06× |
| Highest legitimate value anywhere in the series | **1.22×** |
| Corrupt spikes | **1.42–113×** |

Only applied where both neighbours are exactly one hour away, so the DST reporting gaps
don't read as false discontinuities.

### 3. Level-collapse — has this hour dropped out?

Below **0.33×** a centred 7-day median. Catches zeros, negatives, and dropouts, which
neither high-side test can see. Currently fires on nothing.

### Iteration

Applied iteratively. A corrupt hour is part of the percentile used to judge it, so the
first pass computes a baseline inflated by the very values it is trying to catch;
removing flagged hours and recomputing can expose borderline cases. Iteration can only
tighten the baseline, never un-flag an hour. Converges in one pass on this series.

---

## The 14 excluded hours

**PJM 13 · SWPP 1 · ERCO 0 · MISO 0**

| BA | Timestamp (UTC) | Reported (MWh) | Baseline | Ratio | Test |
|---|---|---|---|---|---|
| PJM | 2021-10-19 04:00 | 2,147,480,000 | 146,695 | 14,639.04× | peak-level |
| PJM | 2021-10-19 03:00 | 1,527,760,000 | 146,695 | 10,414.51× | peak-level |
| PJM | 2021-10-19 05:00 | 431,044,000 | 146,695 | 2,938.36× | peak-level |
| SWPP | 2023-06-13 02:00 | 3,621,097 | 54,120 | 66.91× | peak-level |
| PJM | 2019-12-11 20:00 | 417,669 | 148,147 | 2.82× | peak-level |
| PJM | 2020-07-24 16:00 | 262,651 | 145,243 | 1.81× | peak-level |
| PJM | 2020-09-03 21:00 | 250,825 | 147,144 | 1.70× | peak-level |
| PJM | 2020-07-27 22:00 | 245,799 | 145,243 | 1.69× | peak-level |
| PJM | 2020-07-13 23:00 | 224,345 | 147,961 | 1.52× | peak-level |
| PJM | 2019-12-12 22:00 | 155,276 | 103,637 | 1.50× | isolated-spike |
| PJM | 2020-04-10 04:00 | 215,682 | 147,419 | 1.46× | peak-level |
| PJM | 2020-08-13 13:00 | 138,575 | 99,324 | 1.40× | isolated-spike |
| PJM | 2020-07-28 17:00 | 192,229 | 145,243 | 1.32× | peak-level |
| PJM | 2020-07-29 21:00 | 176,085 | 145,243 | 1.21× | peak-level |

Each was inspected in its surrounding hours before acceptance. None is a borderline
judgment call:

- **The three consecutive 2021-10-19 PJM hours** are almost certainly an upstream
  integer overflow — the largest, 2,147,480,000, sits just under the signed 32-bit
  ceiling of 2,147,483,647.
- **2019-12-11 20:00** reads 417,669 between neighbours of 99,567 and 99,613.
- **2019-12-12 22:00** reads 155,276 between 98,466 and 108,808 — the same December 2019
  fault one day later. This was PJM's *reported 2019 annual maximum*, and a December one
  in a summer-peaking RTO. Excluding it moves PJM's 2019 peak to a July afternoon
  (152.3 GW), which is the correct seasonal shape.
- **2020-08-13 13:00** reads 138,575 in the middle of a smooth monotonic morning ramp
  (85.7 → 87.8 → 91.1 → 95.3 → **138.6** → 103.4 → 108.9 → 114.1 GW), which resumes
  cleanly afterwards.

---

## Validation

The strongest evidence the rule is correctly calibrated is that it fixes exactly the
years that were wrong and touches nothing else. **ERCO and MISO are unchanged in every
single year.**

### Annual peak demand, GW (before → after)

| Year | PJM | ERCO | MISO | SWPP |
|---|---|---|---|---|
| 2019 | 417.7 → **152.3** | 74.5 | 116.6 | 50.5 |
| 2020 | 262.7 → **145.4** | 74.2 | 112.9 | 48.7 |
| 2021 | 2,147,480 → **149.6** | 73.5 | 114.2 | 50.8 |
| 2022 | 148.5 | 79.8 | 116.4 | 53.0 |
| 2023 | 147.6 | 85.4 | 120.8 | 3,621.1 → **56.0** |
| 2024 | 153.1 | 85.5 | 121.6 | 54.2 |
| 2025 | 160.6 | 83.6 | 118.7 | 54.7 |
| 2026 | 162.6 | 91.1 | 121.5 | 58.0 |

**Two independent confirmations:**
1. PJM's corrected peaks now sit in a coherent 145–163 GW band, below its ~165 GW
   all-time record, trending upward. Its corrected 2020 peak of 145.4 GW matches PJM's
   actual reported 2020 summer peak of ~144–145 GW.
2. Correcting 2019 moves PJM's annual peak from a December hour to a July afternoon —
   the right seasonal shape for a summer-peaking system.

### Effect on annual mean demand

| BA | raw mean (MWh) | clean mean (MWh) | change |
|---|---|---|---|
| ERCO | 49,318 | 49,318 | 0.00% |
| MISO | 73,945 | 73,945 | 0.00% |
| PJM | 154,050 | 92,219 | −40.14% |
| SWPP | 32,124 | 32,070 | −0.17% |

### Resulting growth-rate series — annual mean demand, GW

| Year | Hours | ERCO | MISO | PJM | SWPP |
|---|---|---|---|---|---|
| 2019 | 8,760 | 43.80 | 74.15 | 91.35 | 30.76 |
| 2020 | 8,784 | 43.37 | 71.05 | 87.64 | 29.83 |
| 2021 | 8,760 | 44.81 | 73.32 | 90.90 | 30.54 |
| 2022 | 8,760 | 49.16 | 74.56 | 92.48 | 32.25 |
| 2023 | 8,760 | 51.00 | 73.17 | 89.63 | 32.03 |
| 2024 | 8,784 | 52.80 | 73.59 | 92.81 | 33.02 |
| 2025 | 8,760 | 55.71 | 75.77 | 96.24 | 34.23 |
| **2026 — PARTIAL** | **5,178** | *57.07* | *77.34* | *99.73* | *35.17* |

#### Headline growth: 2019 → 2025, both full years

This is the comparison to cite. Both endpoints are complete calendar years, so no
seasonal bias enters.

| BA | 2019 (GW) | 2025 (GW) | Total growth | CAGR |
|---|---|---|---|---|
| **ERCO** | 43.80 | 55.71 | **+27.2%** | **4.09%** |
| **SWPP** | 30.76 | 34.23 | **+11.2%** | **1.79%** |
| **PJM** | 91.35 | 96.24 | **+5.4%** | **0.87%** |
| **MISO** | 74.15 | 75.77 | **+2.2%** | **0.36%** |

ERCOT is growing more than an order of magnitude faster than MISO — the cross-regional
variation the research question needs, and exactly the spread the corrupt PJM data would
have distorted.

#### 2026 is partial-year and directional only

2026 covers 2019-01-01 through **2026-08-04 only — 5,178 hours vs. ~8,760** for a full
year. It omits August–December, so its mean is seasonally biased and **must not be used
as a growth endpoint against full years.** It is retained in the table above (italicised)
because it is real data and useful as a directional signal, not because it is comparable.

To use 2026 directionally, restrict *every* year to the same calendar window. On a
like-for-like **Jan 1 – Aug 4** basis:

| Year | ERCO | MISO | PJM | SWPP |
|---|---|---|---|---|
| 2019 | 42.82 | 74.35 | 92.52 | 30.54 |
| 2020 | 42.92 | 71.23 | 88.05 | 29.87 |
| 2021 | 44.14 | 73.50 | 91.25 | 30.62 |
| 2022 | 49.90 | 75.79 | 93.77 | 32.52 |
| 2023 | 49.98 | 73.37 | 89.52 | 31.86 |
| 2024 | 52.01 | 73.68 | 94.30 | 33.05 |
| 2025 | 55.30 | 76.12 | 97.60 | 34.23 |
| 2026 | 57.07 | 77.34 | 99.73 | 35.17 |
| **2019 → 2026 (directional)** | **+33.3%** | **+4.0%** | **+7.8%** | **+15.2%** |

**The regional ranking is stable across both windows** — ERCO ≫ SWPP > PJM > MISO on the
full-year 2019→2025 basis and on the like-for-like 2019→2026 basis alike. That robustness
is worth noting: the headline finding does not depend on which window is chosen, only its
magnitude does.

---

## How the rule got here

Recorded because the dead ends are part of the audit trail. Final exclusion count went
**5 → 12 → 14** as each test was added and validated.

### Version 1 (5 hours) — ratio to a 7-day median, 3× / 0.33×

Caught the five grossest values. Left PJM's maximum at 262,651 MWh (262.7 GW) against a
~165 GW all-time record. **The failure:** a median is a measure of *central tendency*, so
PJM's high summer median (~110 GW) meant a 2.4× error didn't trip a threshold tuned to
catch 26,000× overflows. Seven implausible PJM hours, all in 2020, survived.

### Rejected fix A — an absolute per-BA MW ceiling (e.g. PJM ≈ 170,000 MWh)

Would have isolated exactly the 7 surviving hours, and there was a clean 13 GW gap in the
data to place it in. **Rejected** because a fixed ceiling in a project about demand growth
would eventually be crossed by real load and start deleting good data.

### Rejected fix B — lowering the median threshold to 1.5×

**Rejected** because it flags 24 hours, most of them apparently genuine weather:
- ERCO 2019-10-10, 62.2 GW at 1.61× — a hot October evening against a mild-month median
  of 38.7 GW, well inside ERCOT's ~75 GW 2019 range.
- PJM 2022-05-31, 138.8 GW at 1.53× — a late-May heat wave, below PJM's 148.5 GW 2022 peak.

A mild-month median makes legitimate extremes look extreme, so a median-ratio test cannot
separate "corrupt" from "hot spell in a mild month" at *any* threshold. MISO and SWPP have
zero hours above 1.5×; the problem was specific to PJM.

### Version 2 (12 hours) — peak-level test replaces the median upper bound

Comparing to a rolling *peak* level rather than a rolling *median* was the fix. Candidate
baselines were evaluated empirically against the known-corrupt set; all separated cleanly,
and p99.9 over a centred 731-day window separated widest:

| baseline | lowest corrupt ratio | highest legitimate ratio | gap |
|---|---|---|---|
| **p99.9 / 731d** | **1.212×** | **1.052×** | **0.160** |
| p99.5 / 731d | 1.263× | 1.111× | 0.151 |
| p99.0 / 731d | 1.296× | 1.144× | 0.153 |

### Version 3 (14 hours) — isolated-spike test added

Validating version 2 surfaced its blind spot. PJM's surviving 2019 maximum of 155,276 MWh
scored only 1.05× the two-year peak level — identical to legitimate annual peaks in the
other three BAs — because it sat just under PJM's real summer peak of ~152 GW. Checking its
neighbours showed 98,466 → **155,276** → 108,808: an isolated spike, not a cold snap, which
would have produced a sustained elevated evening. Adding the physical-continuity test caught
it and one further hour (2020-08-13 13:00).

---

## Other decisions carried forward

### Series begins 2019-01-01; the 2015–2018 tail is not pursued
The API v2 route `electricity/rto/region-data` reports `startPeriod = 2019-01-01T00`, and a
test request for January 2018 returns `total: 0` — there is no pre-2019 data on this
endpoint. EIA-930 history back to July 2015 exists only in the Hourly Grid Monitor **bulk
CSV** downloads, a separate pipeline. 2019 onward is ample for measuring recent regional
growth against queue outcomes, and it gives a clean pre-COVID baseline year. The original
plan referenced "since 2015"; this is a deliberate narrowing, not an oversight.

### Null demand values retained
176 rows have a timestamp but no value (PJM 116, MISO 35, SWPP 25). These are *missing*, not
*wrong* — a different problem from the exclusions above — and the detection rules
deliberately do not flag them. Retaining them costs nothing and preserves the honest record
of which hours a BA failed to report.

**Where missing hours could actually bias a result.** pandas defaults to `skipna=True`, so
both `.sum()` and `.mean()` *skip* NaNs rather than treating them as zero — a straight
`.sum()` is not the risk:

```python
s = pd.Series([1.0, 2.0, None, 4.0])
s.sum()        # 7.0   — skips the NaN, does not zero it
s.mean()       # 2.33  — 7/3, divides by the NON-NULL count
s.sum() / len(s)  # 1.75 — the actual failure mode
```

The real exposure is **dividing a total by an assumed hour count** — `annual_total / 8760`,
or `sum() / len(group)` — instead of calling `.mean()` directly. That silently treats every
missing hour as a zero-demand hour and biases the result downward. This is not hypothetical
here: hours per BA-year are not uniform. Leap years have 8,784; the 14 exclusions and the
3 DST gaps (below) leave some BA-years a few hours short (PJM 2020 has 8,776 rows, not
8,784); and the 176 nulls are rows that exist but contribute nothing to a mean.

**Rule for Phase 2: use `.mean()` directly, and never hard-code 8,760 or 8,784.** If a
total is genuinely needed, divide by the non-null count explicitly.

### Three missing DST hours left as-is
ERCO and SWPP are each missing 2021-11-07 06:00 UTC; PJM is missing 2023-11-06 05:00 UTC.
MISO has fully continuous coverage. All three fall on daylight-saving fall-back dates —
artifacts of BAs submitting in local time to a UTC-indexed series. One hour each out of
~66,545 is immaterial, and there is nothing to correct. The isolated-spike test explicitly
skips hours adjacent to these gaps.

### UTC canonical; local time only for display
Stored as `timestamp_utc` (the API's `frequency=hourly` UTC series). UTC has no DST
discontinuities, so the hourly index is unambiguous and gap detection is meaningful. But
load shape is only interpretable in local time — an evening peak has to appear in the
evening — so `plot_demand_week.py` converts per BA before plotting. MISO and SWPP span
multiple time zones; a single representative zone (Central) is used for **display only**,
never for analysis.

---

## Queue outcome panel (Phase 2)

*Added 2026-08-06. Covers `build_queue_panel.py` and the region-year outcome panel.*

### Why the microdata and not LBNL's trend tabs

Four candidate tabs were inspected for a region-year join against the demand series.
**Three of them have no region dimension at all:**

| Tab | Layout | Breakout | Usable for region-year? |
|---|---|---|---|
| 21. Operational Volume Trend | 26 rows, 2000–2025 | year × *data source* (queue vs. EIA) | **No** — national |
| 22. Withdrawn Volume Trend | 26 rows, 2000–2025 | year only (+ project count) | **No** — national |
| 07. Active Capacity by Year | 24 rows, 2014–2025 | year × *vintage* (new vs. carryover) | **No** — national |
| 09. Active Cap. Region+Type | 840 rows | region × year × type, 10 × 12 × 7, balanced | **Yes** |

Only tab 09 is broken out by both. But tab 09 reports a **stock** — capacity sitting
active at year end — not the **flows** this project treats as the outcome. Year-over-year
deltas in a stock mix new entries, withdrawals and completions into one number, so it
cannot answer "did congestion worsen" on its own. Tab 03's project-level microdata
(38,201 rows with `region`, `on_date`, `wd_date`, `q_status`, `mw_1`) is the only source
that yields regional *flows*, so the panel is aggregated from it. Tab 09 is retained as
a **backlog-size control**, not an outcome.

### The decision: aggregate flows from tab 03, keep tab 09 as a control

**Outputs.** `data/processed/queue_outcomes_panel.csv` (108 region-year rows, 4 regions ×
2000–2026) and `data/processed/queue_date_coverage.csv` (the completeness audit).

**Capacity field.** `mw_1`. `mw_2`/`mw_3` hold co-located hybrid components and are
**entirely unpopulated for all four regions** — LBNL excludes its imputed hybrid storage
from the published microdata (codebook, `mw_2`). The script sums all three anyway so the
measure stays correct if a region is added later; today the sum equals `mw_1`.

**A consequence worth stating: the panel will not reconcile to tab 09.** Tab 09's totals
*include* imputed hybrid storage that tab 03 omits. The two are measuring different things
from different inputs; do not treat a discrepancy as a bug.

### Reporting quality is *not* comparable across the four regions

This was checked before anything was built on top of it, and it is the single most
important finding of this phase.

| Region | operational rows w/ `on_date` | by MW | withdrawn rows w/ `wd_date` | by MW |
|---|---|---|---|---|
| PJM | 99.4% | 99.1% | 98.4% | 96.2% |
| MISO | 96.5% | 97.1% | 93.8% | 91.7% |
| SPP | 96.3% | 98.4% | **72.8%** | **68.1%** |
| ERCOT | **84.7%** | **82.1%** | **48.7%** | **39.8%** |

**`on_date` is reasonably even (82–99% by MW) and supports cross-regional comparison.
`wd_date` does not.** ERCOT is a severe outlier: **60% of its withdrawn capacity carries
no withdrawal date at all.**

And the gap is not random — it is concentrated in early vintages. Coverage by queue-entry
year runs 0–20% for ERCOT projects entering before 2016, then 80–97% for 2017–2022.
Because the panel is indexed on withdrawal year, an undated project cannot be placed in
any year and drops out entirely. The result:

**ERCOT records zero placeable withdrawals in every year before 2018.** Not a low number —
zero, against 1,158 withdrawn ERCOT projects in the file. SPP has the same problem more
mildly (near-zero before 2010, ~95%+ from 2012).

A second, opposite gap: **MISO records no `on_date` after 2024**, so MISO 2025 reads as
zero completions while PJM and ERCOT report 47 and 76. Reporting lag, not a standstill.

**Decision.** Build the panel, but flag the structural zeros rather than emitting them
as data. `operational_series_usable` and `withdrawn_series_usable` mark every region-year
outside that region's observed reporting window. The window is **derived from the data**
(first and last year with any dated outcome, per region and outcome) rather than
hard-coded, so a re-pull that shifts coverage updates the flags instead of silently
invalidating them. The inferred windows are printed on every run.

Inferred windows: operational — ERCOT 2012–2025, MISO 2000–**2024**, PJM 2000–2025,
SPP 2002–2025. Withdrawn — ERCOT **2018**–2025, MISO 2002–2026, PJM 2000–2026, SPP 2004–2026.

**Filter on these flags before modelling.** A region and year fixed-effects specification
run on the unfiltered panel would read ERCOT's missing pre-2018 withdrawals as a genuine
regional difference in withdrawal behaviour — in the region whose demand growth is the
headline result (+27.2%, an order of magnitude above MISO). That is the same failure mode
as the corrupt PJM demand hours: a data artifact masquerading as cross-regional variation
in exactly the variable the analysis turns on.

### The `project_type` trap

Filtering to `project_type == "Generation"` looks obviously right and is wrong. **876
in-scope rows have a blank `project_type`, and 854 of them are ERCOT** (the rest SPP).
They are plainly generation — `type_clean` reads Wind, Solar, Gas, Battery, Coal,
Nuclear — and they carry **209 GW**, including 42 GW operational and 166 GW withdrawn.

An `!= "Generation"` filter drops all of them, deleting roughly a third of ERCOT's
outcome capacity and none of PJM's. The first build did exactly this; it understated
ERCOT 2025 completions as 60 projects / 7.4 GW against a corrected 76 / 9.2 GW.

**Decision.** Exclude only rows *explicitly labelled* `Upgrade`, `Surplus` or
`Replacement` (174 rows across the four regions — network upgrades and surplus service
are not new capacity). Treat blanks as generation and report the count on every run.
The general rule, and it recurs throughout this workbook: **a null-valued exclusion filter
is only safe when the nulls are spread evenly across regions. Here they never are.**

### Tab 09 control: the 2020 hybrid break

Tab 09 note (1): hybrid-storage capacity is *estimated* from storage:generator ratios and
**only included from 2020**. The workbook carries a literal `"NA"` for hybrid in 2014–2019
(60 cells, all 10 regions). Offshore wind is likewise only broken out from 2020.

`active_gw_total` therefore has a level break at 2020 — PJM 2020 reads 152.8 GW with
hybrid, 144.7 GW without. The panel ships both `active_gw_total` and
`active_gw_excl_hybrid` plus a `hybrid_in_active_total` flag. **Use
`active_gw_excl_hybrid` for anything spanning 2019–2020**; the totals are not
like-for-like across that boundary. `"All Regions"` is dropped — it is LBNL's national
total, not a region, and would double-count.

### Validation

The four regions sum to a stable and plausible share of LBNL's own national totals:
**61–86% of tab 21 operational capacity** and **37–77% of tab 22 withdrawn capacity**
across 2015–2025. These are the four largest queue regions, and the shortfall sits where
expected — West and Southeast have 18% and 59% `on_date` coverage nationally, so the
national denominators are themselves understated.

### Reform-driven withdrawal spikes: `likely_reform_driven`

FERC Order 2023 forced cluster restructuring and mass resubmission across the
FERC-jurisdictional RTOs, purging speculative projects wholesale. Those withdrawals are
administrative, not demand-driven attrition, and they land squarely in the analysis
window. Every region-year is screened for the pattern.

**Test.** Withdrawal count *or* MW above **3× the region's own median**, where the median
is taken over that region's usable, complete years only. Both ratios ship as columns
(`n_withdrawn_vs_median`, `mw_withdrawn_vs_median`) so the threshold stays a parameter —
re-threshold straight from the CSV, the same way `excluded_hours.csv` carries the ratio
and the test that fired rather than just a verdict. **Flags, never excludes.**

Restricting the median to usable years is load-bearing, not incidental: ERCOT's
structural pre-2018 zeros would otherwise drag its median toward zero and flag its whole
series. The reporting-window flags must be computed first.

**Eight region-years flagged:**

| Region | Year | n withdrawn | vs. median | MW withdrawn | vs. median |
|---|---|---|---|---|---|
| MISO | 2023 | 268 | 4.1× | 41,892 | 2.9× |
| MISO | 2025 | 938 | **14.2×** | 171,737 | **11.8×** |
| PJM | 2024 | 821 | 5.4× | 67,653 | 3.5× |
| PJM | 2025 | 655 | 4.3× | 78,517 | 4.0× |
| SPP | 2022 | 134 | 3.2× | 23,550 | 3.6× |
| SPP | 2023 | 257 | 6.1× | 50,688 | 7.8× |
| SPP | 2024 | 137 | 3.3× | 27,614 | 4.2× |
| SPP | 2025 | 280 | 6.7× | 65,049 | **10.0×** |

**ERCOT is the only region with no flagged year** — its largest deviation is 1.32×, not
close to the threshold. This is strong corroboration that the screen is picking up the
reform rather than noise: **ERCOT is the one non-FERC-jurisdictional region of the four,
so Order 2023 does not apply to it.** The flag independently recovers the jurisdictional
boundary without being told about it. Seven of the eight flagged years fall in 2023–2025;
the eighth (SPP 2022) is the one to inspect manually.

#### Why a plain own-median baseline, after testing the alternatives

The baseline choice changes the answer more than the threshold does, so three were tried.

*Centred rolling median* — the idiom used for the EIA-930 peak-level test — **is the
wrong tool here, for an interesting reason.** A centred window deliberately lets a
sustained step-up raise its own baseline, which is exactly right for demand (a real
load increase should not be flagged as corruption) and exactly wrong for this: the
reform *is* a sustained multi-year regime, so it suppresses its own detection. At a
7-year centred window PJM 2025, SPP 2023 and SPP 2025 all fall below 2×, with 2024's
spike sitting in the baseline of 2025.

*Trailing median* (5- and 10-year) picks up secular growth as readily as reform, flagging
PJM 2008–2012 and SPP 2010–2016 — eras when those queues were simply growing.

*Own-median over the full usable window* is the simplest, is what a reviewer will expect,
and empirically separates cleanest: 7 of 8 hits in the reform era, zero hits in the one
exempt region. Restricting the median to 2019+ instead was rejected because the reform
years are inside that window and inflate the very median they are being tested against —
MISO's 2019+ median is 179 against a full-window 66, which suppresses MISO 2023 entirely.

#### The filter is nearly collinear with region — do not blindly drop flagged rows

**Excluding flagged rows would do more damage than leaving them in.** Because ERCOT is
exempt, the flag is not evenly distributed — it removes the late period from the
FERC-jurisdictional regions and nothing from ERCOT:

| Region | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | kept |
|---|---|---|---|---|---|---|---|---|
| PJM | ✓ | ✓ | ✓ | ✓ | ✓ | — | — | 5 |
| ERCOT | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **7** |
| MISO | ✓ | ✓ | ✓ | ✓ | — | ✓ | — | 5 |
| SPP | ✓ | ✓ | ✓ | — | — | — | — | **3** |
| **kept** | 4 | 4 | 4 | 3 | 2 | 2 | **1** | |

2025 retains ERCOT alone. A regression on the filtered panel would compare ERCOT's
2023–2025 against everyone else's 2019–2022 — a region-period confound worse than the
one the filter was meant to remove, and pointed at the region carrying the headline
demand result. **Prefer a period control or a reform-year interaction to a hard drop.**
This is why the column is a flag and the guard accounting is reported rather than
pre-applied.

### Analysis-ready row count

Applying every guard as a hard exclusion, from 108 region-years (4 regions × 2000–2026):

| Guard applied cumulatively | Rows | PJM | ERCOT | MISO | SPP |
|---|---|---|---|---|---|
| all region-years | 108 | 27 | 27 | 27 | 27 |
| + `year_complete` (drops the 2026 stub) | 104 | 26 | 26 | 26 | 26 |
| + `demand_years_available` (2019+) | 28 | 7 | 7 | 7 | 7 |
| + `operational_series_usable` | 27 | 7 | 7 | 6 | 7 |
| + `withdrawn_series_usable` | 27 | 7 | 7 | 6 | 7 |
| + `not likely_reform_driven` | **20** | 5 | 7 | 5 | 3 |

**20 region-year observations.** The binding constraint by far is the demand window —
2019+ costs 76 rows on its own, because EIA-930 has no pre-2019 history on the API route
(see below). The quality guards cost 8 more, 7 of them from the reform flag.

Twenty observations across four cross-sectional units is a small panel. It supports
descriptive comparison and simple fixed-effects work; it will not support a heavily
parameterised specification, and region-and-year fixed effects alone would consume a
large share of the degrees of freedom. Worth settling the specification against this
number rather than discovering it later.

### Parallel-trends pre-test: FAILED — do not run the DiD

*Added 2026-08-06. `plot_withdrawal_parallel_trends.py` → `figures/withdrawal_rate_parallel_trends.png`,
`data/processed/withdrawal_rates.csv`.*

FERC Order 2023 binds PJM, MISO and SPP but not ERCOT, which suggests a
difference-in-differences read with ERCOT as control. **The pre-test rejects it.**
The comparison was not estimated.

**Rate definition.** A hazard rate, not a share of the queue:

> withdrawal rate(region, *t*) = projects withdrawn in *t* ÷ projects at risk in *t*

A project is at risk in year *t* if it entered on or before *t* and had not already
exited (withdrawn or operational) before *t*; active and suspended projects stay at
risk to the end of the sample. Projects that exited with no usable date are dropped
from **numerator and denominator alike** — 1,505 of them (ERCOT 688, SPP 508, MISO 219,
PJM 90). Leaving them in the denominator would count them as perpetually at risk and
deflate every later year, worst in the region that can least afford it.

#### Three independent reasons the test fails

**1. The treated regions do not move together with each other.** Pre-reform slopes over
the common 2018–2022 window disagree in sign:

| Region | slope, pp/yr | |
|---|---|---|
| PJM | **−4.17** | treated |
| MISO | **−2.10** | treated |
| SPP | **+1.95** | treated |
| ERCOT | −0.78 | control |

SPP rises through the pre-period while PJM and MISO fall. A DiD needs the treated group
to share a trend before it can share a treatment effect; this one does not.

**2. Co-movement is negative where it most needs to be positive.** Correlation of
year-over-year changes, 2018–2022:

| | PJM | MISO | SPP | ERCOT |
|---|---|---|---|---|
| **PJM** | 1.00 | 0.51 | **−0.73** | 0.28 |
| **MISO** | 0.51 | 1.00 | **−0.67** | 0.76 |
| **SPP** | −0.73 | −0.67 | 1.00 | −0.09 |
| **ERCOT** | 0.28 | 0.76 | −0.09 | 1.00 |

SPP is *negatively* correlated with both of its own treatment-group partners. Worse for
the design: **the strongest pair in the matrix is MISO↔ERCOT at 0.76** — the control
tracks one treated region better than the treated regions track each other, so the
treated/control split does not match the data's own correlation structure. Extending the
window to 2014–2022 does not rescue it (PJM↔MISO −0.16, PJM↔SPP −0.62, MISO↔SPP −0.32).

**3. ERCOT's post-2023 flatness is partly a reporting artifact.** ERCOT's rate sits at
3.9–4.3% across 2022–2025 while the other three swing between 4% and 36%. Some of that
gap is not real: ERCOT's `wd_date` coverage *degrades in recent cohorts* — 97% of its
2018 entrants have a withdrawal date, against 56% (2023), 56% (2024) and 24% (2025).
Allocating ERCOT's 594 undated withdrawals at its own median 2-year queue-to-withdrawal
duration implies roughly **+18 / +16 / +37** additional withdrawals in 2023 / 2024 / 2025
against 72 / 88 / 96 observed — a 20–38% understatement concentrated in the post period.
A DiD would book that reporting lag as the treatment effect. It does not explain ERCOT's
whole level gap, but it contaminates the post-period difference in the direction that
would flatter the hypothesis.

#### What is still true, and what to do instead

The FERC three do all show a sharp post-2023 rise (PJM 5.5%→31.7%, MISO 2.4%→35.9%,
SPP 19.8%→31.0% by 2025) while ERCOT stays flat. That contrast is real and probably
does reflect Order 2023 — it is just **not cleanly identified** by this design, because
the pre-period gives no stable baseline to difference against and the control's post-period
is measured with a known, one-sided error.

Treat the reform as a **descriptive regime break to control for**, not a treatment effect
to estimate. This is consistent with `likely_reform_driven` being a flag rather than a
filter, and with the collinearity finding above: ERCOT's exemption makes "reform-affected"
and "is a FERC region" nearly the same variable in the late sample.

If a causal read is wanted later, the design needs within-region variation Order 2023
actually created — cluster-cycle timing differences across RTOs, or project-level
exposure by queue-entry cohort — not a four-region region-level DiD.

## Analysis panel (Phase 3, construction)

*Added 2026-08-07. `build_analysis_panel.py` → `data/processed/analysis_panel.csv`,
`figures/demand_growth_vs_clearance.png`. Construction only — nothing fitted.*

**23 region-years, 2020–2025.** PJM 6, ERCOT 6, SPP 6, MISO 5.

| Step | Rows |
|---|---|
| demand × queue, 2019–2025 | 28 |
| − 2019 base year (no prior year for YoY) | 24 |
| − MISO 2025 (`operational_series_usable=False`) | **23** |

The 7 `likely_reform_driven` rows are **retained and flagged**, per the collinearity
finding above — dropping them would strip the late period from the FERC three and
nothing from ERCOT.

### Reusing the Phase 1 demand means

Phase 1 never persisted an annual-mean artifact; the numbers exist only in the table
in this document. The means are therefore recomputed from the **cleaned** hourly series
(never the raw one) using Phase 1's documented method — `.mean()` directly, never a
division by 8,760 — and then **checked value-by-value against the published table**.
Worst deviation 0.0050 GW, inside the table's 2dp quoting precision. The check is a hard
assertion, not a warning: if a future re-pull moves the series, this script fails rather
than silently publishing a different demand history than the one already written up.

### Two definitional notes

**`clearance_rate` is MW per GW, not a fraction.** Built as specified —
`mw_operational / active_gw_excl_hybrid` — with the numerator in MW and the denominator
in GW, so the values (5–69) are 1000× the dimensionless share. A pure scale factor: it
changes no ordering, no ranking and no scatter shape. Flagged only so the units are
never mistaken for percent.

**It also crosses two sources.** The numerator is aggregated from tab 03 microdata; the
denominator is LBNL's own tab 09 series, which includes imputed hybrid storage that tab
03 omits. `active_gw_excl_hybrid` is used precisely to keep the denominator on a
consistent basis across the 2020 hybrid break — but numerator and denominator still come
from different aggregations and should not be expected to reconcile.

### First look, before anything is fitted

Read off the raw table and scatter, stated as observations rather than results:

- **No relationship is visible to the eye.** At comparable demand growth (≈+3.5%),
  clearance ranges from 5.4 (MISO 2024) to 69.1 (ERCOT 2021) — an order of magnitude.
- **Region separates the data far more cleanly than growth does.** ERCOT occupies the
  high-clearance band (25–69) in every year; SPP and MISO fall into the single digits by
  2023–2025. The vertical spread is regional, not growth-driven.
- **Clearance declines steeply in MISO and SPP — but not in PJM or ERCOT.** MISO runs
  69.1 → 25.2 → 11.7 → 6.8 → 5.4; SPP 46.3 → 32.0 → 30.5 → 10.0 → 11.9 → 9.4. PJM is
  flat and ERCOT drifts up. *(An earlier draft of this section said clearance declines
  within every region. The per-region diagnostic below shows that is wrong: first year
  to last, MISO −92% and SPP −80%, against PJM −4% and ERCOT +12%.)*
- **The denominator drives much of that decline.** MISO's active backlog grows 90 → 397
  GW while its completions fall 6,250 → 2,136 MW; both movements push the ratio down, so
  a falling clearance rate is not evidence of slowing completions on its own.
- **One high-leverage point.** ERCOT 2022 (+9.70%) sits alone in the right tail; the
  other 22 observations fall between −4.2% and +5.6%. Any slope through this cloud would
  be substantially a function of that single region-year.

None of this is a finding. It is the shape of the data, recorded before any model is
fitted so that the model can be judged against it.

### Diagnostics

*`plot_analysis_diagnostics.py` → `figures/diag_clearance_by_year.png`,
`diag_scatter_by_year.png`, `diag_scatter_no_ercot2022.png`. Still nothing fitted.*

**1. The decline is two regions, not four.** First observed year to last:

| Region | first | last | change |
|---|---|---|---|
| MISO | 69.1 (2020) | 5.4 (2024) | **−92%** |
| SPP | 46.3 (2020) | 9.4 (2025) | **−80%** |
| PJM | 20.9 (2020) | 20.1 (2025) | −4% |
| ERCOT | 22.7 (2020) | 25.4 (2025) | **+12%** |

This corrects the first-look claim above. It also rules out the obvious reading: PJM is
FERC-jurisdictional and flat, so the split is **not** FERC vs. non-FERC.

**And the collapse largely predates the reform flags.** MISO falls 69.1 → 25.2 → 11.7
across 2020–2022, all three unflagged; its flagged 2023 (6.8) continues a trend already
almost complete. SPP falls 46.3 → 32.0 → 30.5 before its first flagged year. Whatever is
driving MISO and SPP down, `likely_reform_driven` is not a sufficient explanation.

**2. Year drifts the cloud downward but does not sort it.** Pooled across regions, the
median clearance runs 34.5 → 28.6 → 21.1 → 14.8 → 18.7 → 20.1 (2020→2025) — down, then
partially back up. **2024 contains both the lowest observation in the panel (MISO 5.4)
and the second-highest (ERCOT 45.7).** So "early vs. late" explains a great deal *within*
MISO and SPP and essentially nothing within PJM and ERCOT. Year is not a cleaner
organising variable than region; the two are entangled, and neither is growth.

**3. Removing ERCOT 2022 changes no apparent pattern, because there is none to change.**
The x-range compresses from 13.9 to 9.8 pp; the vertical spread is untouched at 5.4–69.1.
What remains at the high-growth end is mixed rather than high: at +3.1% to +5.6% growth
sit ERCOT 2023–24 (41.9, 45.7) *and* SPP 2024–25 (11.9, 9.4) — a four-fold difference in
clearance at effectively the same demand growth. If anything the removal weakens the
impression of a positive relationship, since ERCOT 2022 was the single point most
consistent with one.

The honest summary of all three: **the vertical spread in this panel is organised by
region and by within-region trajectory, not by demand growth.** Any specification should
be judged against that before its coefficient on growth is believed.

### Diagnostic regressions

*`fit_diagnostic_models.py` → `data/processed/diagnostic_model_results.csv`. n = 22
(ERCOT 2022 excluded). Growth in percentage points; clearance in MW per GW. **Variance
accounting, not estimates** — nothing below clears p < 0.05.*

| | M1 pooled | M2 + region | M0 region only |
|---|---|---|---|
| intercept | 17.73 (6.28) | 10.91 (8.43) | 19.48 (7.13) |
| growth | −1.37 (1.35) | −2.13 (1.32) | — |
| growth² | **0.962 (0.500)** p=.070 | **0.915 (0.475)** p=.072 | — |
| ERCOT | — | 23.88 (10.18) p=.032 | 21.49 (10.57) p=.057 |
| MISO | — | 6.20 (10.08) | 4.15 (10.57) |
| SPP | — | 5.75 (9.46) | 3.87 (10.08) |
| R² | 0.166 | 0.390 | 0.208 |
| adj R² | 0.078 | 0.200 | 0.076 |

**The growth² term does not behave as hypothesised. It does not shrink and it does not
lose significance — because it never had any.** Adding region moves it 0.962 → 0.915, a
5% change, with p essentially static (0.070 → 0.072). It is marginal in both models.
Dropping the three observations above the Cook's D screen (MISO 2020, ERCOT 2025, ERCOT
2021) moves it only to 0.795 with p = 0.073, while R² rises to 0.516. The coefficient is
stable; what it lacks is power, not robustness.

**Region and growth are close to orthogonal in this sample.** Region alone buys R² 0.208;
growth terms alone buy 0.166; together 0.390 — slightly *more* than the sum of the parts,
so the two blocks are not competing for the same variance. Incrementally, growth adds
0.182 on top of region and region adds 0.225 on top of growth. This is a genuine
correction to the read from the scatter diagnostics: region organises the vertical spread,
but it is not absorbing the growth terms.

**Neither block earns its degrees of freedom.** F(growth | region) = 2.39, p = 0.124;
F(region | growth) = 1.96, p = 0.160. With 22 observations and 6 parameters, nothing here
is separable from noise, and adjusted R² for M0 (0.076) and M1 (0.078) is essentially nil.

**The fitted curvature is a U, with its vertex inside the data.** Minimum at +0.71 pp
growth (M1) and +1.16 pp (M2), so the fit says clearance is *lowest* at about 1% demand
growth and rises at both ends. That shape has no obvious mechanism behind it and is better
read as the parabola accommodating high-clearance early years at both extremes of the
growth axis (MISO 2020 at −4.17%, ERCOT 2021 at +3.33%, both at 69.1) than as a
demand response.

#### Linear-only: `clearance ~ growth + region`

Dropping growth² is not a neutral simplification, because the quadratic's vertex sat
inside the data — the linear term in M2 was the slope of a parabola at zero, not an
average slope. These fits give the average slope, with and without the leverage point.

| | L22 (excl. ERCOT 2022) | L23 (full set) |
|---|---|---|
| intercept (PJM) | 20.67 (7.25) p=.011 | 20.54 (7.04) p=.009 |
| **growth** | **−1.290 (1.340)** p=.349 | **−1.144 (1.183)** p=.346 |
| ERCOT | 24.20 (10.96) p=.041 | 24.64 (10.55) p=.031 |
| MISO | 2.81 (10.69) p=.796 | 2.96 (10.39) p=.779 |
| SPP | 5.04 (10.18) p=.627 | 4.91 (9.90) p=.626 |
| R² | 0.2491 | 0.2595 |
| adj R² | 0.0724 | 0.0950 |
| region-only R² | 0.2082 | 0.2211 |
| growth adds | +0.0409 | +0.0385 |
| F(growth \| region) | 0.926, p = 0.349 | 0.935, p = 0.346 |

**Growth does not earn its place in either.** It adds about 4 points of R² for one degree
of freedom, F ≈ 0.93, p ≈ 0.35. Adjusted R² barely moves off region-only (0.072 vs 0.076
at n=22), so on the penalised measure the linear growth term is worth slightly *less*
than nothing.

**Almost all of the growth block's explanatory power in M2 was the quadratic term.**
Growth terms added 0.182 to R² over region in the quadratic model; the linear term alone
adds 0.041. Whatever growth is contributing, it is not contributing a slope.

**The leverage point barely moves the linear slope: −1.290 → −1.144, an 11% shift, sign
unchanged, and each estimate sits comfortably inside the other's 95% CI.** This is worth
stating plainly because it contradicts the expectation set by the scatter. ERCOT 2022 was
the single point most consistent with a positive relationship *visually*, but that
impression came from comparing it to the pooled cloud. Once the ERCOT dummy is in the
model, the point is judged against ERCOT's own mean clearance (40.4) rather than the
pooled mean — and at 37.8 it is an entirely ordinary ERCOT year. Its extreme growth gives
it leverage on the x-axis; its unremarkable within-region clearance gives it almost
nothing to pull with.

The practical consequence: **the earlier note that ERCOT 2022 would dominate any slope
through the cloud holds only for a pooled fit.** With region in the model it is not
influential, and the n=22 / n=23 choice is immaterial to the linear specification.

### Carried forward

- **2026 is a stub.** `wd_date` runs to 2026-01-16 only; `year_complete` marks it.
- **MISO 2025 is excluded twice over** — no `on_date` records after 2024, *and* a
  14.2× withdrawal spike. It is the single worst region-year in the panel.
- **13 in-scope rows report `mw <= 0`**, retained as reported.

---

## Limitations & open questions

**The thresholds are calibrated to the corruption present in this series.** 1.15× and
1.35× separate cleanly here with good margins, but they are empirical. If a future re-pull
introduces a new failure mode, or a BA genuinely spikes >15% above its own two-year peak
level, the exclusion log surfaces it rather than hiding it — **glance at
`excluded_hours.csv` after any re-pull rather than assuming the count stays at 14.**

**2026 is a partial year and not comparable to full years.** The headline growth figures use
2019 → 2025 (both complete). Use 2026 only against a like-for-like calendar window, as
tabulated above, and label it directional.

**Never divide a demand total by an assumed hour count.** Use `.mean()` directly; hours per
BA-year are not uniform (leap years, exclusions, DST gaps, nulls). See the nulls section for
the specific failure mode — note that pandas `.sum()` and `.mean()` both skip NaNs by
default, so plain summation is *not* the risk.

**Sub-BA parent mapping — not yet addressed.** Some sub-balancing-authorities (Duke Energy
Progress, PacifiCorp West) don't publish standalone EIA-930 demand and need explicit
mapping to a parent BA. The four BAs pulled so far are all parents, so this hasn't bitten
yet.

**ERCOT needs separate treatment.** ERCO is non-FERC-jurisdictional with its own large-load
process and cannot be pooled naively with the FERC-jurisdictional RTOs.

**The 2023 regime-change confound.** Queue dynamics shifted in 2023–2025 partly because of
FERC Order 2023 (forced resubmissions, purged speculative projects), not purely from demand
pressure. This is a Phase 2/3 concern, noted here because the demand series spans the break.
