# Data Center Demand Growth and Generation-Interconnection Queue Congestion (AI-GENERATED README)

Luke W. Jones · August 2026

## The Question

Do US regions absorbing faster AI- and data center-driven electricity demand growth also
experience slower clearing of generation-interconnection queues — evidence that the demand
surge itself is straining the approval pipeline for new power supply?

**No.** Across 23 region-years spanning four major US grid regions (PJM, ERCOT, MISO, and
SPP, 2020–2025), regional demand growth shows no detectable relationship with how quickly a
region's generation queue clears, once the region itself is accounted for. What does predict
queue performance is *which region* a project sits in. ERCOT, for instance, clears its backlog
at a substantially higher rate than the other three — the only effect in the analysis that is
statistically distinguishable from zero. Demand growth, by contrast, is not.

This is a **weak null**: with 23 observations, the analysis could not have detected anything
short of a very large effect. The correct reading is that this design cannot detect a
relationship, not that no relationship exists. See the memo and appendix (linked below) for the
full argument and its limits.

## Data Sources

Two public datasets, combined at the region-year level:

- **EIA-930 (Hourly Electric Grid Monitor)** — hourly electricity demand by balancing
  authority, pulled from the EIA API v2 route `electricity/rto/region-data`. 266,181
  as-reported rows, 2019-01-01 through 2026-08-04, for four balancing authorities: `PJM`,
  `MISO`, `SWPP` (SPP), `ERCO` (ERCOT).
- **LBNL "Queued Up"** — project-level interconnection-queue records,
  `data/raw/LBNL_Ix_Queue_Data_File_thru2025.xlsx`. Two tabs are used: tab 03 ("Complete Queue
  Data," 38,201 rows) for project-level dates and outcomes, and tab 09 ("Active Cap.
  Region+Type," 840 rows) as the backlog-size control.

Full sourcing rationale, including why these four regions and not others, is in appendix §1.

## Method

**Demand growth** is each region's year-over-year change in mean hourly demand.
**Clearance rate** is queue performance: MW reaching commercial operation in a year, divided by
the region's active queue backlog in MW, expressed as a percentage of that backlog cleared per
year.

The two are regressed as:

```
clearance_rate ~ demand_growth + region_fixed_effects
```

Demand growth is tested against clearance rate because FERC Order 2023 governs how new
generation and storage connect to the grid — the supply-side approval pipeline — and the
question is whether regions absorbing faster demand growth show that pipeline straining under
the load. Region fixed effects are included because, as the analysis found, region is the
dominant source of variation in clearance rate; without controlling for it, a raw
growth-vs-clearance correlation would be confounded by which region a given region-year happens
to be.

The resulting panel covers 23 region-years (PJM 6, ERCOT 6, SPP 6, MISO 5) from 2020 through
2025. Full variable definitions, the guard cascade that produced this panel from a 108-row
universe, and the diagnostics that led to this specification (including a U-shaped curvature
that was tested and rejected) are in appendix §6–8.

## Repository Structure

### `data/raw/` — as-pulled, never modified
| File | Contents |
|---|---|
| `eia930_hourly_demand.csv` | As-reported EIA-930 hourly demand, 266,181 rows |
| `LBNL_Ix_Queue_Data_File_thru2025.xlsx` | LBNL "Queued Up," 43 tabs |

### `data/processed/` — derived outputs
| File | Contents |
|---|---|
| `eia930_hourly_demand.csv` | Cleaned hourly demand (266,167 rows; 14 corrupt hours removed) |
| `excluded_hours.csv` | Audit trail of the 14 excluded hours — test, baseline, ratio |
| `queue_outcomes_panel.csv` | Region-year queue outcomes, 108 rows (4 regions × 2000–2026) |
| `queue_date_coverage.csv` | Outcome-date completeness by region and outcome type |
| `withdrawal_rates.csv` | Region-year withdrawal hazard rates, 84 rows (parallel-trends pre-test) |
| `analysis_panel.csv` | The final 23-row analysis panel |
| `diagnostic_model_results.csv` | Coefficients, SEs, R², and F-tests for all 5 fitted models |

### `figures/`
Memo figures (`memo_*.png`) are presentation-grade and appear in the memo and appendix.
Everything else is exploratory/diagnostic, referenced only in the appendix.

| File | Used in |
|---|---|
| `memo_demand_growth_indexed.png` | Memo Figure 1 — demand growth by region, indexed to 2019 |
| `memo_coefficient_plot.png` | Memo Figure 2 / appendix §8 — final specification, coefficients and 95% CIs |
| `memo_clearance_by_year.png` | Memo Figure 3 / appendix §6 — clearance rate by region, 2020–2025 |
| `memo_outcome_date_coverage.png` | Appendix §3 — outcome-date coverage by region |
| `memo_withdrawal_parallel_trends.png` | Memo Figure 4 / appendix §5 — withdrawal rate, parallel-trends check |
| `demand_growth_vs_clearance.png` | Appendix §6 — main scatter, growth vs. clearance, exploratory |
| `diag_clearance_by_year.png` | Appendix §6 — exploratory, per-region small multiples |
| `diag_scatter_by_year.png` | Appendix §6 — exploratory, scatter colored by year |
| `diag_scatter_no_ercot2022.png` | Appendix §6 — exploratory, leverage-point check |
| `withdrawal_rate_parallel_trends.png` | Appendix §5 — exploratory, full 2005–2025 parallel-trends record |
| `demand_week_*.png` | Appendix §2 — single-week inspection plots from the cleaning stage |

### Scripts (repository root)
| Script | Reads | Produces |
|---|---|---|
| `pull_eia930_demand.py` | EIA API | `data/raw/eia930_hourly_demand.csv` |
| `eia930_quality.py` | — | the three data-quality tests (imported, not run directly) |
| `clean_eia930.py` | `data/raw/eia930_hourly_demand.csv` | `data/processed/eia930_hourly_demand.csv`, `excluded_hours.csv` |
| `plot_demand_week.py` | cleaned demand | `figures/demand_week_*.png` |
| `build_queue_panel.py` | LBNL workbook | `data/processed/queue_outcomes_panel.csv`, `queue_date_coverage.csv` |
| `plot_withdrawal_parallel_trends.py` | queue panel | `data/processed/withdrawal_rates.csv`, `figures/withdrawal_rate_parallel_trends.png` |
| `build_analysis_panel.py` | cleaned demand + queue panel | `data/processed/analysis_panel.csv`, `figures/demand_growth_vs_clearance.png` |
| `plot_analysis_diagnostics.py` | analysis panel | `figures/diag_*.png` |
| `fit_diagnostic_models.py` | analysis panel | `data/processed/diagnostic_model_results.csv` |
| `build_memo_figures.py` | cleaned demand, queue panel, analysis panel, model results | `figures/memo_*.png` |

`DECISIONS.md` is the chronological working log behind the appendix — every data-quality
decision, dead end, and superseded draft, in the order it happened.

## Reproduction

Run from the repository root, in order. Each script prints its own diagnostics and writes its
own artifacts; none of them modifies `data/raw/`.

```
python pull_eia930_demand.py
python clean_eia930.py
python plot_demand_week.py
python build_queue_panel.py
python plot_withdrawal_parallel_trends.py
python build_analysis_panel.py
python plot_analysis_diagnostics.py
python fit_diagnostic_models.py
python build_memo_figures.py
```

Dependencies: `pandas`, `numpy`, `matplotlib`, `openpyxl`, `statsmodels`, `requests`.

`build_analysis_panel.py` contains a hard assertion that the recomputed annual demand means
match the published table to within 0.01 GW — if a re-pull changes the demand series, the
build fails rather than silently publishing a divergent history. After any re-pull, also check
`data/processed/excluded_hours.csv` rather than assuming the exclusion count stays at 14; the
detection thresholds are empirically calibrated to the corruption present in the current pull,
not derived from first principles.

## Full Write-Ups

- **[Data-Center_Demand_Queue_Memo.pdf](Data-Center_Demand_Queue_Memo.pdf)** — the memo. Start
  here: the question, the finding, why it matters, and what it doesn't tell you.
- **[Technical_Appendix_DataCenter_Demand_Queue.pdf](Technical_Appendix_DataCenter_Demand_Queue.pdf)**
  — the full methodology: every data-quality decision and its calibration evidence, why the
  panel is built the way it is, the abandoned difference-in-differences and why it failed its
  own pre-test, the U-shaped curvature that was found and rejected, and the final specification
  with its limitations. This is the reference document if the memo's claims need checking.

Both are also available as `.docx`.
