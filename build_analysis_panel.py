"""
Phase 3, step 1: assemble the final analysis dataset. Construction only.

Reads   data/processed/eia930_hourly_demand.csv    the CLEANED demand series (Phase 1)
        data/processed/queue_outcomes_panel.csv    the queue outcome panel (Phase 2)
Writes  data/processed/analysis_panel.csv          the merged analysis table
        figures/demand_growth_vs_clearance.png     the raw scatter

No regression, no fitted line, no correlation coefficient. This step builds the table
and looks at it honestly.

On "reuse the Phase 1 annual means": Phase 1 never persisted an annual-mean artifact --
the figures live only in the DECISIONS.md table. So the means are recomputed here from
the *cleaned* hourly series (never the raw one) using Phase 1's documented method, and
then checked against the published table value by value. A mismatch is a hard failure,
not a warning; that check is what makes this a reuse rather than a second opinion.

Phase 1's standing rule applies: call .mean() directly. Never divide an annual total by
8,760 or 8,784 -- hours per BA-year are not uniform (leap years, the 14 excluded hours,
3 DST gaps, 176 nulls), and dividing by an assumed count silently treats missing hours
as zero-demand hours.

    python build_analysis_panel.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

DEMAND_PATH = Path("data/processed/eia930_hourly_demand.csv")
QUEUE_PATH = Path("data/processed/queue_outcomes_panel.csv")
OUT_PATH = Path("data/processed/analysis_panel.csv")
FIG_PATH = Path("figures/demand_growth_vs_clearance.png")

# EIA-930 balancing-authority codes -> the queue data's region names.
BA_TO_REGION = {"PJM": "PJM", "ERCO": "ERCOT", "MISO": "MISO", "SWPP": "SPP"}
REGIONS = ["PJM", "ERCOT", "MISO", "SPP"]
FERC_JURISDICTIONAL = {"PJM", "MISO", "SPP"}  # ERCOT is not FERC-jurisdictional

FIRST_YEAR, LAST_YEAR = 2019, 2025  # 2026 is a partial year; excluded by Phase 1 rule

# Annual mean demand, GW, as published in DECISIONS.md after the Phase 1 cleaning.
# Reproducing these exactly is the check that this script reuses Phase 1's series
# rather than quietly deriving a different one.
PHASE1_MEAN_GW = {
    2019: {"ERCOT": 43.80, "MISO": 74.15, "PJM": 91.35, "SPP": 30.76},
    2020: {"ERCOT": 43.37, "MISO": 71.05, "PJM": 87.64, "SPP": 29.83},
    2021: {"ERCOT": 44.81, "MISO": 73.32, "PJM": 90.90, "SPP": 30.54},
    2022: {"ERCOT": 49.16, "MISO": 74.56, "PJM": 92.48, "SPP": 32.25},
    2023: {"ERCOT": 51.00, "MISO": 73.17, "PJM": 89.63, "SPP": 32.03},
    2024: {"ERCOT": 52.80, "MISO": 73.59, "PJM": 92.81, "SPP": 33.02},
    2025: {"ERCOT": 55.71, "MISO": 75.77, "PJM": 96.24, "SPP": 34.23},
}
TOLERANCE_GW = 0.01  # the published table is quoted to 2dp

# dataviz palette, categorical slots 1-3 + 7. Validated all-pairs on the light
# surface (worst CVD dE 9.2 deutan, worst normal-vision dE 16.3). Same hue per
# region as the parallel-trends chart -- color follows the entity, so a region
# keeps its color across every figure in the project.
COLORS = {"PJM": "#2a78d6", "MISO": "#eb6834", "SPP": "#1baf7a", "ERCOT": "#4a3aa7"}

SURFACE = "#fcfcfb"
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"


def annual_mean_demand() -> pd.DataFrame:
    """Annual mean demand in GW per region-year, from the cleaned hourly series."""
    df = pd.read_csv(DEMAND_PATH, parse_dates=["timestamp_utc"])
    df["region"] = df.balancing_authority.map(BA_TO_REGION)
    if df.region.isna().any():
        unmapped = sorted(df[df.region.isna()].balancing_authority.unique())
        raise ValueError(f"unmapped balancing authorities: {unmapped}")
    df["year"] = df.timestamp_utc.dt.year

    # .mean() skips nulls and divides by the non-null count. Never len(group).
    means = (
        df.groupby(["region", "year"])["demand_mwh"].mean().div(1000).reset_index(
            name="mean_demand_gw"
        )
    )
    return means[means.year.between(FIRST_YEAR, LAST_YEAR)].copy()


def check_against_phase1(means: pd.DataFrame) -> None:
    """Hard-fail if the recomputed means drift from the published Phase 1 table."""
    worst, mismatches = 0.0, []
    for _, r in means.iterrows():
        published = PHASE1_MEAN_GW[r.year][r.region]
        delta = abs(r.mean_demand_gw - published)
        worst = max(worst, delta)
        if delta > TOLERANCE_GW:
            mismatches.append(f"{r.region} {r.year}: {r.mean_demand_gw:.2f} vs {published:.2f}")
    if mismatches:
        raise AssertionError(
            "recomputed annual means do not match the published Phase 1 table:\n  "
            + "\n  ".join(mismatches)
        )
    print(
        f"Annual means reproduce the published Phase 1 table exactly "
        f"({len(means)} region-years, worst delta {worst:.4f} GW)."
    )


def add_growth(means: pd.DataFrame) -> pd.DataFrame:
    """Year-over-year demand growth. 2019 has no prior year and is dropped."""
    means = means.sort_values(["region", "year"]).copy()
    prior = means.set_index(["region", "year"]).mean_demand_gw
    means["prior_gw"] = [
        prior.get((r, y - 1)) for r, y in zip(means.region, means.year)
    ]
    means["demand_growth_yoy"] = (means.mean_demand_gw - means.prior_gw) / means.prior_gw

    # Drop rather than carry a blank. 2019 is the base year, not a missing
    # observation, and leaving it in invites a later fillna(0) that would read
    # the base year as a year of zero growth.
    dropped = means.demand_growth_yoy.isna().sum()
    means = means[means.demand_growth_yoy.notna()].copy()
    print(f"Dropped {dropped} base-year rows with no prior year ({FIRST_YEAR}).")
    return means.drop(columns="prior_gw")


def build() -> pd.DataFrame:
    means = annual_mean_demand()
    check_against_phase1(means)
    growth = add_growth(means)

    queue = pd.read_csv(QUEUE_PATH)

    # MW completed as a PERCENTAGE of active backlog (GW converted to MW via
    # *1000 before dividing). This is a true dimensionless share -- "% of the
    # active backlog that reached operation this year" -- unlike the earlier
    # MW-per-GW construction, which was 1000x a fraction. A pure rescaling of
    # that earlier version (divide by 10): changes no ranking, ordering, or
    # scatter shape, and changes no p-value, R^2, adjusted R^2, or F-statistic
    # in anything fitted on it -- only the coefficient and SE magnitudes.
    queue["clearance_rate_pct"] = (
        100 * queue.mw_operational / (queue.active_gw_excl_hybrid * 1000)
    )
    queue["ferc_jurisdictional"] = queue.region.isin(FERC_JURISDICTIONAL)

    panel = growth.merge(
        queue[
            [
                "region", "year", "mw_operational", "active_gw_excl_hybrid",
                "clearance_rate_pct", "ferc_jurisdictional", "likely_reform_driven",
                "operational_series_usable",
            ]
        ],
        on=["region", "year"],
        how="inner",
    )

    before = len(panel)
    panel = panel[panel.demand_growth_yoy.notna() & panel.clearance_rate_pct.notna()]
    print(f"Dropped {before - len(panel)} rows where growth or clearance was undefined.")

    unusable = panel[~panel.operational_series_usable]
    if len(unusable):
        cells = ", ".join(f"{r.region} {r.year}" for _, r in unusable.iterrows())
        print(
            f"Dropped {len(unusable)} row(s) flagged operational_series_usable=False "
            f"in Phase 2: {cells}\n"
            "  (no on_date records that year -- mw_operational reads 0 because the\n"
            "   dates are missing, not because nothing was completed.)"
        )
    panel = panel[panel.operational_series_usable].drop(columns="operational_series_usable")

    order = {r: i for i, r in enumerate(REGIONS)}
    return panel.sort_values(
        ["region", "year"], key=lambda s: s.map(order) if s.name == "region" else s
    ).reset_index(drop=True)


def plot(panel: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(11, 7.2), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)

    # Demand contracted in 2020, so zero is inside the data range, not at an edge.
    ax.axvline(0, color=AXIS, lw=1, ls=(0, (4, 3)), zorder=1)

    for region in REGIONS:
        s = panel[panel.region == region]
        for is_reform, sub in s.groupby("likely_reform_driven"):
            if sub.empty:
                continue
            # Reform years get a hollow diamond: a SHAPE difference, so the
            # distinction survives grayscale, CVD and print, not a second hue
            # that would compete with the region encoding.
            ax.scatter(
                sub.demand_growth_yoy * 100, sub.clearance_rate_pct,
                s=115 if is_reform else 95,
                marker="D" if is_reform else "o",
                facecolors=SURFACE if is_reform else COLORS[region],
                edgecolors=COLORS[region],
                linewidths=2.0 if is_reform else 1.2,
                zorder=4, label=None,
            )

    # Year labels on every point -- these are the "visible labels" relief the
    # palette's sub-3:1 aqua requires, and with 23 points they also make the
    # per-region trajectory legible without a connecting line.
    #
    # Several region-years sit almost on top of each other (PJM and MISO both
    # land near +1.7% / 11), so labels are placed greedily: try above, then
    # below, then the diagonals, and take the first slot that clears every
    # label already placed. Measured in axes fractions so the test is in
    # screen space, not data units.
    ax.set_xlim(*ax.get_xlim())
    ax.set_ylim(*ax.get_ylim())
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    candidates = [(0, 10), (0, -17), (13, 3), (-13, 3), (14, -11), (-14, -11)]
    min_sep = 0.033  # axes fractions
    placed: list[tuple[float, float]] = []

    for _, r in panel.iterrows():
        px = (r.demand_growth_yoy * 100 - x0) / (x1 - x0)
        py = (r.clearance_rate_pct - y0) / (y1 - y0)
        for dx, dy in candidates:
            # points -> axes fractions, via the axes box in inches
            fx = px + dx / 72 / fig.get_size_inches()[0] / 0.903
            fy = py + dy / 72 / fig.get_size_inches()[1] / 0.730
            if all(abs(fx - qx) > min_sep or abs(fy - qy) > min_sep for qx, qy in placed):
                break
        placed.append((fx, fy))
        ax.annotate(
            f"{int(r.year) % 100:02d}",
            (r.demand_growth_yoy * 100, r.clearance_rate_pct),
            xytext=(dx, dy), textcoords="offset points",
            ha="center", va="bottom" if dy >= 0 else "top",
            color=MUTED, fontsize=7.5, zorder=5,
        )

    region_handles = [
        plt.Line2D([], [], marker="o", ls="", markersize=9, color=COLORS[r], label=r)
        for r in REGIONS
    ]
    shape_handles = [
        plt.Line2D([], [], marker="o", ls="", markersize=9, color=MUTED, label="ordinary year"),
        plt.Line2D(
            [], [], marker="D", ls="", markersize=9, markerfacecolor=SURFACE,
            markeredgecolor=MUTED, markeredgewidth=2, color=MUTED,
            label="likely reform-driven",
        ),
    ]
    first = ax.legend(
        handles=region_handles, frameon=False, ncol=4, loc="upper left",
        bbox_to_anchor=(0, 1.055), fontsize=10, labelcolor=INK_2, handletextpad=0.35,
        columnspacing=1.5,
    )
    ax.add_artist(first)
    ax.legend(
        handles=shape_handles, frameon=False, ncol=2, loc="upper right",
        bbox_to_anchor=(1, 1.055), fontsize=9.5, labelcolor=INK_2, handletextpad=0.35,
        columnspacing=1.4,
    )

    ax.grid(color=GRID, lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9.5, length=0)
    ax.set_xlabel("Year-over-year growth in annual mean demand (%)", color=INK_2, fontsize=10.5)
    ax.set_ylabel("Clearance rate — % of active backlog reaching operation",
                  color=INK_2, fontsize=10.5)

    fig.suptitle(
        "Demand growth against queue clearance, by region-year",
        x=0.072, y=0.972, ha="left", color=INK, fontsize=15.5, fontweight="bold",
    )
    fig.text(
        0.072, 0.923,
        f"{len(panel)} region-years, 2020–2025. Points labelled by year. "
        "No fitted line and no correlation — raw points only.",
        ha="left", color=INK_2, fontsize=9.5,
    )
    fig.text(
        0.072, 0.028,
        "Demand: EIA-930 cleaned hourly series, annual mean (Phase 1). Clearance: MW reaching operational status in the year, as a % of active non-hybrid\n"
        "queue capacity (LBNL tab 09). MISO 2025 excluded — no on_date records that year. Full table: data/processed/analysis_panel.csv.",
        ha="left", color=MUTED, fontsize=8,
    )

    fig.subplots_adjust(top=0.855, bottom=0.125, left=0.072, right=0.975)
    FIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_PATH, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    print(f"\nWrote {FIG_PATH}")


def main() -> int:
    for p in (DEMAND_PATH, QUEUE_PATH):
        if not p.exists():
            print(f"ERROR: {p} not found.")
            return 1

    panel = build()

    cols = [
        "region", "year", "mean_demand_gw", "demand_growth_yoy", "mw_operational",
        "active_gw_excl_hybrid", "clearance_rate_pct", "ferc_jurisdictional",
        "likely_reform_driven",
    ]
    panel = panel[cols]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(OUT_PATH, index=False)

    print(f"\nANALYSIS PANEL — all {len(panel)} rows")
    print("=" * 118)
    print(
        f"{'region':<8}{'year':>6}{'mean_dem_GW':>13}{'growth_yoy':>12}"
        f"{'mw_oper':>10}{'active_GW':>11}{'clearance%':>11}  {'ferc':<6}{'reform':<7}"
    )
    print("-" * 118)
    for _, r in panel.iterrows():
        print(
            f"{r.region:<8}{r.year:>6}{r.mean_demand_gw:>13.2f}"
            f"{r.demand_growth_yoy * 100:>11.2f}%{r.mw_operational:>10,.1f}"
            f"{r.active_gw_excl_hybrid:>11.2f}{r.clearance_rate_pct:>10.2f}%  "
            f"{str(r.ferc_jurisdictional):<6}{str(r.likely_reform_driven):<7}"
        )
    print("=" * 118)
    print(f"Wrote {OUT_PATH}")

    print(f"\nRows per region: "
          + ", ".join(f"{r}={int((panel.region == r).sum())}" for r in REGIONS))
    print(f"Reform-flagged rows retained (flagged, not dropped): "
          f"{int(panel.likely_reform_driven.sum())}")

    plot(panel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
