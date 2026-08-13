"""
Parallel-trends check: queue withdrawal rates, FERC-jurisdictional RTOs vs ERCOT.

Reads   data/raw/LBNL_Ix_Queue_Data_File_thru2025.xlsx  tab "03. Complete Queue Data"
Writes  data/processed/withdrawal_rates.csv             the rate series
        figures/withdrawal_rate_parallel_trends.png     the chart

This is the pre-test for a difference-in-differences read of FERC Order 2023, which
applies to PJM, MISO and SPP but NOT to ERCOT (non-jurisdictional). A DiD is only
licensed if the four regions' withdrawal rates move roughly together before 2023.
This script tests that and reports the verdict; it deliberately does NOT estimate a
treatment effect. See DECISIONS.md -- the test fails.

Rate definition: a hazard rate, not a share of the queue.

    withdrawal rate(region, t) = projects withdrawn in t / projects at risk in t

A project is at risk in year t if it entered on or before t and had not already
exited (withdrawn or reached operation) before t. Projects still active or suspended
stay at risk through the end of the sample. Projects that exited but carry no exit
date are dropped from numerator AND denominator alike -- leaving them in the
denominator would count them as perpetually at risk and deflate every later year.

    python plot_withdrawal_parallel_trends.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

RAW_PATH = Path("data/raw/LBNL_Ix_Queue_Data_File_thru2025.xlsx")
RATES_PATH = Path("data/processed/withdrawal_rates.csv")
FIG_PATH = Path("figures/withdrawal_rate_parallel_trends.png")

MICRODATA_TAB = "03. Complete Queue Data"
MICRODATA_HEADER_ROW = 1
NON_GENERATION_TYPES = ["Upgrade", "Surplus", "Replacement"]

FERC_JURISDICTIONAL = ["PJM", "MISO", "SPP"]
CONTROL = "ERCOT"
REGIONS = FERC_JURISDICTIONAL + [CONTROL]

REFORM_YEAR = 2023  # FERC Order 2023 cluster restructuring
FIRST_YEAR, LAST_YEAR = 2005, 2025  # 2026 is a 16-day stub

# dataviz palette, categorical slots 1-3 + 7. Validated all-pairs on the light
# surface: worst CVD dE 9.2 (deutan), worst normal-vision dE 16.3. Aqua sits at
# 2.74:1 contrast, below the 3:1 floor -- direct labels are the required relief,
# so every series is labelled at its right end as well as in the legend.
COLORS = {"PJM": "#2a78d6", "MISO": "#eb6834", "SPP": "#1baf7a", "ERCOT": "#4a3aa7"}

SURFACE = "#fcfcfb"
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"


def load_projects() -> pd.DataFrame:
    df = pd.read_excel(RAW_PATH, sheet_name=MICRODATA_TAB, skiprows=MICRODATA_HEADER_ROW)
    df = df[df.region.isin(REGIONS) & ~df.project_type.isin(NON_GENERATION_TYPES)].copy()
    df["mw"] = df.mw_1.fillna(0) + df.mw_2.fillna(0) + df.mw_3.fillna(0)
    df["entry"] = df.q_date.dt.year
    df["exit"] = np.where(
        df.q_status == "withdrawn", df.wd_date.dt.year,
        np.where(df.q_status == "operational", df.on_date.dt.year, np.nan),
    )

    exited = df.q_status.isin(["withdrawn", "operational"])
    undateable = exited & df["exit"].isna()
    print(f"Read {len(df):,} generation requests across {len(REGIONS)} regions")
    print(f"Dropped {undateable.sum():,} that exited without a usable date:")
    print("  " + df[undateable].region.value_counts().to_string().replace("\n", "\n  "))
    print(f"Dropped {df.entry.isna().sum():,} with no queue-entry date")

    return df[df.entry.notna() & ~undateable].copy()


def withdrawal_rates(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for region in REGIONS:
        s = df[df.region == region]
        for t in range(FIRST_YEAR, LAST_YEAR + 1):
            at_risk = s[(s.entry <= t) & (s["exit"].isna() | (s["exit"] >= t))]
            wd = s[(s.q_status == "withdrawn") & (s["exit"] == t)]
            rows.append(
                {
                    "region": region, "year": t,
                    "n_at_risk": len(at_risk), "n_withdrawn": len(wd),
                    "rate_pct": 100 * len(wd) / len(at_risk) if len(at_risk) else np.nan,
                    "mw_at_risk": round(at_risk.mw.sum(), 1),
                    "mw_withdrawn": round(wd.mw.sum(), 1),
                    "mw_rate_pct": (
                        100 * wd.mw.sum() / at_risk.mw.sum() if at_risk.mw.sum() else np.nan
                    ),
                }
            )
    rates = pd.DataFrame(rows)

    # Mask each region's pre-coverage years. ERCOT logs no withdrawal date before
    # 2018, so a raw rate reads 0.0% there -- indistinguishable from "nobody
    # withdrew" and exactly the artifact this whole exercise has to avoid plotting.
    for region in REGIONS:
        m = rates.region == region
        seen = rates[m & (rates.n_withdrawn > 0)].year
        rates.loc[m & (rates.year < seen.min()), ["rate_pct", "mw_rate_pct"]] = np.nan

    rates["rate_pct"] = rates.rate_pct.round(2)
    rates["mw_rate_pct"] = rates.mw_rate_pct.round(2)
    return rates


def assess_parallel_trends(rates: pd.DataFrame) -> dict:
    """Slopes and co-movement over the common pre-reform window."""
    wide = rates.pivot(index="year", columns="region", values="rate_pct")[REGIONS]
    common = wide.dropna()
    pre = common[common.index < REFORM_YEAR]

    slopes = {r: np.polyfit(pre.index, pre[r], 1)[0] for r in REGIONS}
    changes = pre.diff().dropna()
    return {
        "wide": wide,
        "pre": pre,
        "slopes": slopes,
        "corr_changes": changes.corr(),
        "pre_window": (int(pre.index.min()), int(pre.index.max())),
    }


def plot(rates: pd.DataFrame, verdict: dict) -> None:
    wide = verdict["wide"]
    pre_lo, pre_hi = verdict["pre_window"]

    fig, axes = plt.subplots(
        1, 2, figsize=(14, 6), facecolor=SURFACE,
        gridspec_kw={"width_ratios": [1.45, 1], "wspace": 0.22},
    )

    panels = [
        (axes[0], FIRST_YEAR, LAST_YEAR, "Full record — each region from its first usable year"),
        (axes[1], pre_lo, LAST_YEAR, f"Common window {pre_lo}–{LAST_YEAR} — where the test is actually run"),
    ]

    y_top = max(46, wide.max().max() * 1.1)

    for ax, x0, x1, subtitle in panels:
        ax.set_facecolor(SURFACE)
        ax.set_xlim(x0 - 0.5, x1 + 2.2)
        ax.set_ylim(0, y_top)

        # Post-reform span. A wash, not a block: it marks the period, it isn't data.
        ax.axvspan(REFORM_YEAR - 0.5, x1 + 0.4, color="#0b0b0b", alpha=0.045, lw=0, zorder=0)
        ax.axvline(REFORM_YEAR - 0.5, color=AXIS, lw=1, ls=(0, (4, 3)), zorder=1)
        ax.text(
            REFORM_YEAR - 0.3, y_top * 0.965, "FERC Order 2023 →",
            color=MUTED, fontsize=8.5, va="top", ha="left", zorder=5,
        )

        ends = []
        for region in REGIONS:
            s = wide[region].loc[x0:x1].dropna()
            if s.empty:
                continue
            ax.plot(
                s.index, s.values, color=COLORS[region], lw=2, zorder=4,
                marker="o", markersize=4.5, markeredgecolor=SURFACE, markeredgewidth=1.2,
                label=region if ax is axes[0] else None,
            )
            ends.append([region, s.index[-1], s.values[-1]])

        # Direct labels at the right end -- the required relief for the sub-3:1
        # aqua. PJM and SPP finish ~0.7pp apart, so nudge overlapping labels
        # apart vertically rather than letting them print on top of each other.
        min_gap = y_top * 0.045
        ends.sort(key=lambda e: e[2])
        for i in range(1, len(ends)):
            if ends[i][2] - ends[i - 1][2] < min_gap:
                ends[i][2] = ends[i - 1][2] + min_gap
        for region, x, y in ends:
            ax.annotate(
                region, (x, y), xytext=(8, 0), textcoords="offset points",
                color=COLORS[region], fontsize=9.5, fontweight="bold",
                va="center", zorder=6,
            )

        ax.grid(axis="y", color=GRID, lw=0.8, zorder=0)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(AXIS)
        ax.tick_params(colors=MUTED, labelsize=9, length=0)
        step = 5 if (x1 - x0) > 12 else 2
        ax.set_xticks([y for y in range(x0, x1 + 1) if y % step == 0])
        ax.set_xticklabels([str(y) for y in ax.get_xticks()])
        ax.set_title(subtitle, color=INK_2, fontsize=10, pad=10, loc="left")
        ax.set_xlabel("")

    axes[0].set_ylabel("Withdrawal rate — % of at-risk projects", color=INK_2, fontsize=10)
    axes[0].legend(
        frameon=False, ncol=4, loc="upper left", fontsize=9.5,
        labelcolor=INK_2, handlelength=1.6, columnspacing=1.4, bbox_to_anchor=(0, 1.0),
    )

    fig.suptitle(
        "Queue withdrawal rates do not move in parallel before 2023",
        x=0.077, y=0.975, ha="left", color=INK, fontsize=15, fontweight="bold",
    )
    fig.text(
        0.077, 0.918,
        f"Pre-reform slopes diverge in sign ({pre_lo}–{pre_hi}): "
        + ", ".join(f"{r} {verdict['slopes'][r]:+.1f}" for r in REGIONS)
        + " pp/yr.  A difference-in-differences read of Order 2023 is not licensed.",
        ha="left", color=INK_2, fontsize=9.5,
    )
    fig.text(
        0.077, 0.028,
        "Hazard rate: projects withdrawn in year t / projects at risk in t. Requests that exited without a usable date are dropped from both terms.\n"
        "ERCOT is shown only from 2018, its first year with any recorded withdrawal date. Source: LBNL interconnection queue data through 2025, tab 03.",
        ha="left", color=MUTED, fontsize=8,
    )

    fig.subplots_adjust(top=0.845, bottom=0.135, left=0.077, right=0.975)
    FIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_PATH, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    print(f"\nWrote {FIG_PATH}")


def main() -> int:
    if not RAW_PATH.exists():
        print(f"ERROR: {RAW_PATH} not found.")
        return 1

    df = load_projects()
    rates = withdrawal_rates(df)
    RATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    rates.to_csv(RATES_PATH, index=False)
    print(f"\nWrote {len(rates)} region-year rates to {RATES_PATH}")

    verdict = assess_parallel_trends(rates)
    pre_lo, pre_hi = verdict["pre_window"]

    print("\nWithdrawal rate, % of at-risk projects")
    print("-" * 78)
    print(verdict["wide"].round(1).to_string(na_rep="  --"))
    print("-" * 78)

    print(f"\nPARALLEL-TRENDS TEST, common pre-reform window {pre_lo}-{pre_hi}")
    print("-" * 78)
    print("  OLS slope, percentage points per year:")
    for r in REGIONS:
        tag = "control" if r == CONTROL else "treated"
        print(f"    {r:<7}{verdict['slopes'][r]:>7.2f}   ({tag})")
    print("\n  Correlation of year-over-year changes:")
    print("  " + verdict["corr_changes"].round(2).to_string().replace("\n", "\n  "))

    treated = [verdict["slopes"][r] for r in FERC_JURISDICTIONAL]
    signs_disagree = min(treated) < 0 < max(treated)
    worst_pair = verdict["corr_changes"].where(
        ~np.eye(len(REGIONS), dtype=bool)
    ).min().min()

    print("-" * 78)
    print(f"  Treated-group slopes disagree in sign: {signs_disagree}")
    print(f"  Worst pairwise co-movement: {worst_pair:+.2f}")
    print(
        "\n  VERDICT: parallel trends REJECTED. The treated regions do not move\n"
        "  together with each other, let alone with the control. Do not estimate\n"
        "  a difference-in-differences on this. See DECISIONS.md."
    )

    plot(rates, verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
