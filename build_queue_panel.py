"""
Build the region-year interconnection-outcome panel from the LBNL queue workbook.

Reads   data/raw/LBNL_Ix_Queue_Data_File_thru2025.xlsx  (as-reported, never modified)
          tab "03. Complete Queue Data"      -- project-level microdata, 38,201 rows
          tab "09. Active Cap. Region+Type"  -- LBNL's own region x year x type series

Writes  data/processed/queue_outcomes_panel.csv   the panel (region x year)
        data/processed/queue_date_coverage.csv    the completeness audit behind it

Why tab 03 and not LBNL's pre-aggregated trend tabs: tabs 21 (operational volume) and
22 (withdrawn volume) are national totals with no region dimension at all, so they
cannot be joined to a region-year demand series. Only tab 09 is broken out by region
AND year, and it reports a *stock* (capacity sitting active at year end), not the
*flows* -- reaching operational, withdrawing -- that this project treats as the
outcome. Aggregating the microdata ourselves is the only way to get regional flows.

Tab 09 is still pulled, as a backlog-size control. It is NOT the outcome variable.

    python build_queue_panel.py

Read the coverage warnings this prints. ERCOT's withdrawal series is not usable
before 2018 and the panel marks those rows rather than reporting them as zero --
see DECISIONS.md, "Queue outcome panel".
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

RAW_PATH = Path("data/raw/LBNL_Ix_Queue_Data_File_thru2025.xlsx")
PANEL_PATH = Path("data/processed/queue_outcomes_panel.csv")
COVERAGE_PATH = Path("data/processed/queue_date_coverage.csv")

MICRODATA_TAB = "03. Complete Queue Data"
MICRODATA_HEADER_ROW = 1  # row 1 is a "RETURN TO CONTENTS" banner; header is row 2
ACTIVE_TAB = "09. Active Cap. Region+Type"
ACTIVE_HEADER_ROW = 24  # rows 1-24 are title, chart and notes; header is row 25

REGIONS = ["PJM", "ERCOT", "MISO", "SPP"]

# Full span of placeable outcome dates in the workbook. Deliberately wider than the
# EIA-930 demand series (2019+) so the panel isn't silently pre-truncated to one
# join's needs; `demand_years_available` marks the overlap.
YEAR_MIN, YEAR_MAX = 2000, 2026

# Tab 09 imputes hybrid-storage capacity and only includes it from 2020 (tab 09
# note 1). Totals before and after this break are not like-for-like.
HYBRID_FIRST_YEAR = 2020

# Non-generation requests -- network upgrades, surplus interconnection service,
# replacements -- are not new capacity reaching the grid, so they are excluded.
#
# Exclude by explicit label ONLY. 876 in-scope rows have a blank project_type, and
# 854 of them are ERCOT. They are plainly generation (type_clean reads Wind, Solar,
# Gas, Battery, Coal, Nuclear) and carry 42 GW of operational and 166 GW of withdrawn
# capacity. A `project_type != "Generation"` filter silently drops all of them, and
# because the blanks are almost entirely ERCOT it would delete a third of ERCOT's
# outcome capacity and none of PJM's -- manufacturing a cross-regional difference in
# the outcome variable. Same failure mode as the PJM demand corruption in DECISIONS.md.
NON_GENERATION_TYPES = ["Upgrade", "Surplus", "Replacement"]

# Multiple of a region's own median withdrawal volume above which a year is flagged
# as probable queue-reform restructuring rather than demand-driven attrition.
# A screening threshold, calibrated below -- see DECISIONS.md for the alternatives
# tested and why a plain own-median baseline beat the rolling ones.
REFORM_RATIO = 3.0


def load_microdata() -> pd.DataFrame:
    df = pd.read_excel(RAW_PATH, sheet_name=MICRODATA_TAB, skiprows=MICRODATA_HEADER_ROW)

    # mw_2/mw_3 hold the co-located components of hybrid projects. They are entirely
    # unpopulated for all four regions here (LBNL excludes its imputed hybrid storage
    # from the published microdata -- codebook, mw_2), so this sum equals mw_1 today.
    # Written as a sum anyway so the measure stays correct if a region is added later.
    df["mw"] = df["mw_1"].fillna(0) + df["mw_2"].fillna(0) + df["mw_3"].fillna(0)
    return df


def profile_coverage(df: pd.DataFrame) -> pd.DataFrame:
    """Share of each region's outcome pool that carries a usable outcome date.

    A project whose date is missing cannot be placed in any year, so it drops out of
    the panel entirely rather than landing in the wrong cell. Coverage is therefore
    the ceiling on what the flow series can ever capture, and it has to be comparable
    across regions before the panel is used for cross-regional comparison.
    """
    rows = []
    for status, date_col in [("operational", "on_date"), ("withdrawn", "wd_date")]:
        pool = df[(df.q_status == status) & (df.region.isin(REGIONS))]
        for region in REGIONS:
            r = pool[pool.region == region]
            dated = r[r[date_col].notna()]
            rows.append(
                {
                    "region": region,
                    "outcome": status,
                    "date_field": date_col,
                    "n_projects": len(r),
                    "n_dated": len(dated),
                    "pct_projects_dated": round(100 * len(dated) / len(r), 1),
                    "mw_total": round(r.mw.sum(), 1),
                    "mw_dated": round(dated.mw.sum(), 1),
                    "pct_mw_dated": round(100 * dated.mw.sum() / r.mw.sum(), 1),
                    "first_dated_year": (
                        int(dated[date_col].dt.year.min()) if len(dated) else pd.NA
                    ),
                }
            )
    return pd.DataFrame(rows)


def build_flows(df: pd.DataFrame) -> pd.DataFrame:
    """Count and MW reaching operational / withdrawing, by region and outcome year."""
    gen = df[(df.region.isin(REGIONS)) & (~df.project_type.isin(NON_GENERATION_TYPES))]

    frames = []
    for status, date_col, prefix in [
        ("operational", "on_date", "operational"),
        ("withdrawn", "wd_date", "withdrawn"),
    ]:
        pool = gen[(gen.q_status == status) & (gen[date_col].notna())].copy()
        pool["year"] = pool[date_col].dt.year
        agg = (
            pool.groupby(["region", "year"])
            .agg(**{f"n_{prefix}": ("q_id", "size"), f"mw_{prefix}": ("mw", "sum")})
            .reset_index()
        )
        frames.append(agg)

    grid = pd.MultiIndex.from_product(
        [REGIONS, range(YEAR_MIN, YEAR_MAX + 1)], names=["region", "year"]
    ).to_frame(index=False)

    panel = grid
    for f in frames:
        panel = panel.merge(f, on=["region", "year"], how="left")

    # A year with no qualifying project is a true zero, not missing data -- the
    # microdata is a complete census of requests, so absence here means absence.
    # (Rows where the *date field* is unreliable are flagged separately below and
    # must not be read as zeros.)
    for c in ["n_operational", "n_withdrawn"]:
        panel[c] = panel[c].fillna(0).astype(int)
    for c in ["mw_operational", "mw_withdrawn"]:
        panel[c] = panel[c].fillna(0.0).round(1)

    return panel


def add_reporting_window_flags(panel: pd.DataFrame) -> pd.DataFrame:
    """Mark region-years that fall outside a region's observed reporting window.

    This is the flag that protects the regression. Where a region records no usable
    outcome dates, the aggregation emits 0 -- structurally indistinguishable from
    "nothing happened". Two such gaps exist here and they pull in opposite directions:

      * ERCOT logs almost no withdrawal date for projects entering before ~2016, so
        its withdrawal series is empty until 2018 despite 1,158 withdrawn projects.
      * MISO records no operational date after 2024, so 2025 reads as zero completions
        while PJM and ERCOT report 47 and 60.

    Derived from the data rather than hard-coded, so a re-pull that extends or shifts
    a region's coverage updates the flags instead of silently invalidating them. The
    window is [first year with a record, last year with a record] per region-outcome;
    a flagged row means "outside the region's observed reporting window", not "proven
    to be zero". Both boundaries are printed so the inferred windows stay auditable.
    """
    for prefix, flag in [
        ("operational", "operational_series_usable"),
        ("withdrawn", "withdrawn_series_usable"),
    ]:
        observed = panel[panel[f"n_{prefix}"] > 0]
        bounds = observed.groupby("region").year.agg(["min", "max"])
        panel[flag] = [
            bounds.loc[rg, "min"] <= yr <= bounds.loc[rg, "max"]
            for rg, yr in zip(panel.region, panel.year)
        ]
    return panel


def add_reform_flags(panel: pd.DataFrame) -> pd.DataFrame:
    """Flag region-years whose withdrawals dwarf that region's own typical year.

    FERC Order 2023 forced cluster restructuring and mass resubmission, purging
    speculative projects en masse. Those withdrawals are administrative, not demand-
    driven attrition, and they land in exactly the years the analysis cares about.

    The test: withdrawal count OR MW above `REFORM_RATIO` x the region's own median.
    Both ratios ship as columns so the threshold stays a parameter -- re-threshold
    from the CSV without re-running, the same way `excluded_hours.csv` carries the
    ratio and the test that fired rather than just a verdict.

    The median is taken over each region's usable, complete years only. Including
    ERCOT's structural pre-2018 zeros would drag its median toward zero and flag its
    entire series; this is why the reporting-window flags have to be computed first.

    Flags, never excludes. A flagged row is "inspect this", not "this is wrong".
    """
    usable = panel[panel.withdrawn_series_usable & panel.year_complete]
    med = usable.groupby("region")[["n_withdrawn", "mw_withdrawn"]].median()

    for col in ["n_withdrawn", "mw_withdrawn"]:
        base = panel.region.map(med[col])
        panel[f"{col}_vs_median"] = (panel[col] / base).round(2)

    panel["likely_reform_driven"] = (
        (panel.n_withdrawn_vs_median > REFORM_RATIO)
        | (panel.mw_withdrawn_vs_median > REFORM_RATIO)
    ) & panel.withdrawn_series_usable & panel.year_complete

    return panel


def load_active_capacity() -> pd.DataFrame:
    """Tab 09 active capacity by region-year -- the backlog-size control.

    Returned both with and without hybrid storage, because LBNL only includes the
    (imputed) hybrid component from 2020. `active_gw_total` therefore has a level
    break at 2020 that `active_gw_excl_hybrid` does not.
    """
    df = pd.read_excel(RAW_PATH, sheet_name=ACTIVE_TAB, skiprows=ACTIVE_HEADER_ROW)

    # "All Regions" is LBNL's national total row, not a region. Dropping it is what
    # keeps the four regional series from being double-counted against the aggregate.
    df = df[df.Region.isin(REGIONS)].copy()

    # GW arrives as NaN where the workbook says "NA" (hybrid storage, 2014-2019).
    df["GW"] = pd.to_numeric(df["GW"], errors="coerce")

    is_hybrid = df["type"].str.startswith("Hybrid")
    total = df.groupby(["Region", "Year"])["GW"].sum(min_count=1)
    excl = df[~is_hybrid].groupby(["Region", "Year"])["GW"].sum(min_count=1)

    out = pd.concat(
        [total.rename("active_gw_total"), excl.rename("active_gw_excl_hybrid")], axis=1
    ).reset_index()
    out = out.rename(columns={"Region": "region", "Year": "year"})
    out["hybrid_in_active_total"] = out.year >= HYBRID_FIRST_YEAR
    out["active_gw_total"] = out.active_gw_total.round(2)
    out["active_gw_excl_hybrid"] = out.active_gw_excl_hybrid.round(2)
    return out


def main() -> int:
    if not RAW_PATH.exists():
        print(f"ERROR: {RAW_PATH} not found.")
        return 1

    df = load_microdata()
    print(f"Read {len(df):,} project rows from {MICRODATA_TAB}")

    # ---------------------------------------------------------------- coverage
    coverage = profile_coverage(df)
    print("\nOutcome-date completeness by region")
    print("-" * 78)
    for outcome in ["operational", "withdrawn"]:
        c = coverage[coverage.outcome == outcome]
        field = c.date_field.iloc[0]
        print(f"\n  {outcome.upper()} rows -- {field} present?")
        print(f"  {'region':<8}{'projects':>10}{'dated':>8}{'% proj':>9}{'% MW':>8}{'1st yr':>9}")
        for _, r in c.iterrows():
            print(
                f"  {r.region:<8}{r.n_projects:>10,}{r.n_dated:>8,}"
                f"{r.pct_projects_dated:>8.1f}%{r.pct_mw_dated:>7.1f}%{str(r.first_dated_year):>9}"
            )
    print("-" * 78)

    # --------------------------------------------------------------- exclusions
    in_scope = df[df.region.isin(REGIONS)]
    non_gen = in_scope[in_scope.project_type.isin(NON_GENERATION_TYPES)]
    print(
        f"\nExcluded {len(non_gen)} non-generation requests "
        f"({', '.join(f'{k}={v}' for k, v in non_gen.project_type.value_counts().items())})"
        " -- upgrades and surplus service are not new capacity."
    )
    blank_type = in_scope[in_scope.project_type.isna()]
    if len(blank_type):
        by_region = ", ".join(f"{k}={v}" for k, v in blank_type.region.value_counts().items())
        print(
            f"Retained {len(blank_type)} in-scope rows with blank project_type ({by_region}); "
            f"{blank_type.mw.sum() / 1000:.1f} GW.\n"
            "  They carry real resource types and capacity, and the blanks are almost all\n"
            "  one region -- dropping them would bias that region's outcomes specifically."
        )
    zero_mw = in_scope[in_scope.mw <= 0]
    if len(zero_mw):
        print(f"Note: {len(zero_mw)} in-scope rows report mw <= 0; retained as reported.")

    # ------------------------------------------------------------------- panel
    panel = build_flows(df)
    panel = panel.merge(load_active_capacity(), on=["region", "year"], how="left")

    # Carry the coverage ceiling into every row, so a downstream user reading only
    # the panel cannot miss that ERCOT's withdrawal counts rest on 49% of its pool.
    for outcome, col in [("operational", "pct_mw_dated_operational"),
                         ("withdrawn", "pct_mw_dated_withdrawn")]:
        m = coverage[coverage.outcome == outcome].set_index("region").pct_mw_dated
        panel[col] = panel.region.map(m)

    panel = add_reporting_window_flags(panel)

    # 2026 outcome dates run only to 2026-01-16; the year is a stub, not a low year.
    panel["year_complete"] = panel.year <= 2025
    panel["demand_years_available"] = panel.year >= 2019  # EIA-930 series starts 2019

    # Must run after the reporting-window flags: the median it compares against is
    # taken over usable years only.
    panel = add_reform_flags(panel)

    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False)
    coverage.to_csv(COVERAGE_PATH, index=False)
    print(f"\nWrote {len(panel):,} region-year rows to {PANEL_PATH}")
    print(f"Wrote {len(coverage):,} coverage rows to {COVERAGE_PATH}")

    print("\nInferred reporting windows (years with any dated outcome)")
    print("-" * 78)
    for prefix in ["operational", "withdrawn"]:
        obs = panel[panel[f"n_{prefix}"] > 0].groupby("region").year.agg(["min", "max"])
        spans = ", ".join(f"{r} {v['min']}-{v['max']}" for r, v in obs.iterrows())
        print(f"  {prefix:<12} {spans}")
    print("-" * 78)

    for prefix, flag in [("operational", "operational_series_usable"),
                         ("withdrawn", "withdrawn_series_usable")]:
        bad = panel[~panel[flag] & panel.year_complete & panel.demand_years_available]
        if len(bad):
            cells = ", ".join(f"{r.region} {r.year}" for _, r in bad.iterrows())
            print(
                f"\nWARNING: {len(bad)} region-year rows inside the 2019-2025 join window "
                f"have {flag}=False:\n         {cells}\n"
                f"         n_{prefix} reads 0 there because the dates are missing, not "
                "because nothing happened.\n         Filter on this flag before modelling."
            )

    # ------------------------------------------------------- reform-driven years
    flagged = panel[panel.likely_reform_driven]
    print(f"\nReform-driven withdrawal years (> {REFORM_RATIO}x region's own median)")
    print("-" * 78)
    print(f"  {'region':<8}{'year':>6}{'n_wd':>8}{'vs med':>9}{'MW_wd':>12}{'vs med':>9}")
    for _, r in flagged.sort_values(["region", "year"]).iterrows():
        print(
            f"  {r.region:<8}{r.year:>6}{r.n_withdrawn:>8,}{r.n_withdrawn_vs_median:>8.1f}x"
            f"{r.mw_withdrawn:>12,.0f}{r.mw_withdrawn_vs_median:>8.1f}x"
        )
    print("-" * 78)
    by_region = flagged.region.value_counts()
    unflagged = [r for r in REGIONS if r not in by_region.index]
    if unflagged:
        print(f"  No flagged years: {', '.join(unflagged)}")

    # --------------------------------------------------- analysis-ready accounting
    print("\nRows surviving each guard (4 regions x 27 years = 108 total)")
    print("-" * 78)
    steps = [
        ("all region-years", pd.Series(True, index=panel.index)),
        ("+ year_complete (drops 2026 stub)", panel.year_complete),
        ("+ demand_years_available (2019+)", panel.demand_years_available),
        ("+ operational_series_usable", panel.operational_series_usable),
        ("+ withdrawn_series_usable", panel.withdrawn_series_usable),
        ("+ not likely_reform_driven", ~panel.likely_reform_driven),
    ]
    mask = pd.Series(True, index=panel.index)
    for label, step in steps:
        mask = mask & step
        counts = panel[mask].region.value_counts().reindex(REGIONS).fillna(0).astype(int)
        detail = "  ".join(f"{r}={counts[r]}" for r in REGIONS)
        print(f"  {label:<38}{mask.sum():>5}   {detail}")
    print("-" * 78)
    print(f"  ANALYSIS-READY: {mask.sum()} region-year rows across {panel[mask].region.nunique()} regions")

    # Show the join-relevant window so the shape is visible without opening the CSV.
    print("\nPanel, 2019-2025 (the window the demand series covers)")
    print("-" * 78)
    view = panel[(panel.year >= 2019) & (panel.year <= 2025)]
    print(
        view[
            [
                "region", "year", "n_operational", "mw_operational",
                "n_withdrawn", "mw_withdrawn", "active_gw_total",
                "operational_series_usable", "withdrawn_series_usable",
                "likely_reform_driven",
            ]
        ].to_string(index=False)
    )
    print("-" * 78)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
