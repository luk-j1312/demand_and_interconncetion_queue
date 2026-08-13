"""
Presentation-grade figures for the memo, per TECHNICAL_APPENDIX.md's own
"Figures: current status and what the memo needs" table.

Builds the three "Not built" figures (#1, #2, #5 in that table) and rebuilds
presentation ("promoted") versions of the two exploratory diagnostics (#3, #4),
per the specific stripping instructions the appendix already gives for each:
  - clearance-by-year: drop per-point value labels and the diamond/circle
    reform-year distinction
  - withdrawal parallel-trends: single panel, 2018-2025 only, pre/post shading

Does not touch TECHNICAL_APPENDIX.md or any existing figure. Writes only new
files under figures/memo_*.png so the exploratory versions are untouched.

    python build_memo_figures.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

FIG_DIR = Path("figures")
REGIONS = ["PJM", "ERCOT", "MISO", "SPP"]

# Same fixed region -> hue mapping used in every prior figure in this project.
# Categorical slots 1, 7, 2, 3 (dataviz palette), validated all-pairs on the
# light surface: worst CVD dE 9.2 (deutan), worst normal-vision dE 16.3.
COLORS = {"PJM": "#2a78d6", "ERCOT": "#4a3aa7", "MISO": "#eb6834", "SPP": "#1baf7a"}

SURFACE = "#fcfcfb"
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"

BA_TO_REGION = {"PJM": "PJM", "ERCO": "ERCOT", "MISO": "MISO", "SWPP": "SPP"}


def style_axes(ax):
    ax.set_facecolor(SURFACE)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)


def savefig(fig, name):
    out = FIG_DIR / name
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    print(f"Wrote {out}")


# ───────────────────────────────────────── 1. demand growth, indexed 2019=100
def fig_demand_index():
    d = pd.read_csv("data/processed/eia930_hourly_demand.csv", parse_dates=["timestamp_utc"])
    d["region"] = d.balancing_authority.map(BA_TO_REGION)
    d["year"] = d.timestamp_utc.dt.year
    means = d.groupby(["region", "year"])["demand_mwh"].mean().div(1000).reset_index(name="gw")
    means = means[means.year.between(2019, 2025)]
    wide = means.pivot(index="year", columns="region", values="gw")[REGIONS]
    idx = wide.div(wide.loc[2019]) * 100

    fig, ax = plt.subplots(figsize=(10, 6.6), facecolor=SURFACE)
    style_axes(ax)
    ax.axhline(100, color=AXIS, lw=1, ls=(0, (4, 3)), zorder=1)

    for region in REGIONS:
        s = idx[region]
        ax.plot(s.index, s.values, color=COLORS[region], lw=2.2, zorder=4,
                marker="o", markersize=5, markeredgecolor=SURFACE, markeredgewidth=1.2)
        ax.annotate(f"{region}  {s.iloc[-1]:.0f}", (s.index[-1], s.iloc[-1]),
                    xytext=(8, 0), textcoords="offset points", va="center",
                    color=COLORS[region], fontsize=10, fontweight="bold", zorder=6)

    ax.grid(axis="y", color=GRID, lw=0.8, zorder=0)
    ax.set_xlim(2018.7, 2026.6)
    ax.set_xticks(range(2019, 2026))
    ax.set_ylabel("Annual mean demand, indexed to 2019 = 100", color=INK_2, fontsize=10.5)

    fig.suptitle("ERCOT's demand growth outpaces the other three regions",
                 x=0.075, y=0.965, ha="left", color=INK, fontsize=15, fontweight="bold")
    fig.text(0.075, 0.905,
             "Total growth 2019→2025: ERCOT +27.2%, SPP +11.2%, PJM +5.4%, MISO +2.2%.",
             ha="left", color=INK_2, fontsize=10)
    fig.text(0.075, 0.03,
             "Annual mean of cleaned EIA-930 hourly demand per balancing authority. "
             "Source: data/processed/eia930_hourly_demand.csv.",
             ha="left", color=MUTED, fontsize=8)

    fig.subplots_adjust(top=0.85, bottom=0.12, left=0.09, right=0.86)
    savefig(fig, "memo_demand_growth_indexed.png")


# ───────────────────────────────────────────────── 2. coefficient plot, L23
def fig_coefficient_plot():
    m = pd.read_csv("data/processed/diagnostic_model_results.csv")
    l23 = m[m.model == "L23 full set"].set_index("term")

    order = ["growth", "C(region)[T.ERCOT]", "C(region)[T.MISO]", "C(region)[T.SPP]"]
    labels = ["Demand growth\n(per pp)", "ERCOT\n(vs. PJM)", "MISO\n(vs. PJM)", "SPP\n(vs. PJM)"]
    colors = [MUTED, COLORS["ERCOT"], COLORS["MISO"], COLORS["SPP"]]

    fig, ax = plt.subplots(figsize=(10, 5.8), facecolor=SURFACE)
    style_axes(ax)
    ax.axvline(0, color=AXIS, lw=1.2, zorder=1)

    ys = list(range(len(order)))[::-1]
    lo = l23.loc[order].ci_low.min()
    hi = l23.loc[order].ci_high.max()
    span = hi - lo
    x0, x1 = lo - 0.06 * span, hi + 0.34 * span  # extra right margin for the labels

    for y, term, label, color in zip(ys, order, labels, colors):
        row = l23.loc[term]
        sig = row.p < 0.05
        ax.plot([row.ci_low, row.ci_high], [y, y], color=color, lw=2.2, zorder=3,
                solid_capstyle="round")
        ax.scatter([row.coef], [y], s=90, color=color, zorder=4,
                   edgecolors=SURFACE, linewidths=1.3)
        tag = f"  p = {row.p:.3f}" + ("  *" if sig else "")
        ax.annotate(f"{row.coef:+.2f}{tag}", (row.ci_high, y), xytext=(10, 0),
                     textcoords="offset points", va="center", color=INK_2,
                     fontsize=9.5, fontweight="600" if sig else "normal", zorder=5)

    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=10, color=INK_2)
    ax.set_ylim(-0.7, len(order) - 0.3)
    ax.set_xlim(x0, x1)
    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    ax.set_xlabel("Effect on clearance rate, percentage points of backlog (95% CI)",
                  color=INK_2, fontsize=10.5)

    fig.suptitle("Only one region-level difference is distinguishable from zero",
                 x=0.06, y=0.965, ha="left", color=INK, fontsize=14.5, fontweight="bold")
    fig.text(0.055, 0.895,
             "clearance_rate_pct ~ growth + region, n = 23. ERCOT clears faster than PJM (p = .031);\n"
             "demand growth and the MISO/SPP differences do not (p > .05).",
             ha="left", va="top", color=INK_2, fontsize=9.5)
    fig.text(0.055, 0.025,
             "Point = coefficient, line = 95% CI, PJM is the reference level. "
             "Source: data/processed/diagnostic_model_results.csv (model L23).",
             ha="left", color=MUTED, fontsize=8)

    fig.subplots_adjust(top=0.79, bottom=0.14, left=0.18, right=0.93)
    savefig(fig, "memo_coefficient_plot.png")


# ──────────────────────────────────────── 3. outcome-date coverage by region
def fig_coverage():
    c = pd.read_csv("data/processed/queue_date_coverage.csv")

    fig, axes = plt.subplots(1, 2, figsize=(11, 5.4), facecolor=SURFACE, sharey=True)
    for ax, outcome, title in zip(axes, ["operational", "withdrawn"],
                                   ["on_date (operational projects)", "wd_date (withdrawn projects)"]):
        style_axes(ax)
        sub = c[c.outcome == outcome].set_index("region").loc[REGIONS[::-1]]
        ys = range(len(REGIONS))
        vals = sub.pct_mw_dated.values
        colors = [COLORS[r] for r in REGIONS[::-1]]
        ax.barh(ys, vals, color=colors, height=0.6, zorder=3)
        ax.axvline(100, color=AXIS, lw=1, ls=(0, (4, 3)), zorder=1)
        for y, v in zip(ys, vals):
            ax.annotate(f"{v:.1f}%", (v, y), xytext=(6, 0), textcoords="offset points",
                        va="center", color=INK_2, fontsize=9.5, fontweight="600", zorder=4)
        ax.set_yticks(list(ys))
        ax.set_yticklabels(REGIONS[::-1], fontsize=10.5, color=INK_2, fontweight="600")
        ax.set_xlim(0, 118)
        ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
        ax.set_title(title, color=INK_2, fontsize=10.5, pad=10, loc="left")
        ax.set_xlabel("% of MW carrying a usable date", color=INK_2, fontsize=9.5)

    fig.suptitle("ERCOT's withdrawal dates are the weak point in the panel",
                 x=0.055, y=0.97, ha="left", color=INK, fontsize=15, fontweight="bold")
    fig.text(0.055, 0.885,
             "Completion dates (left) are even across regions. Withdrawal dates (right) are "
             "not — ERCOT carries a date for only 40% of withdrawn capacity.",
             ha="left", color=INK_2, fontsize=9.5)
    fig.text(0.055, 0.02,
             "Source: data/processed/queue_date_coverage.csv.",
             ha="left", color=MUTED, fontsize=8)

    fig.subplots_adjust(top=0.8, bottom=0.14, left=0.1, right=0.97, wspace=0.15)
    savefig(fig, "memo_outcome_date_coverage.png")


# ──────────────────────────── 4. clearance by year, per region (presentation)
def fig_clearance_by_year():
    a = pd.read_csv("data/processed/analysis_panel.csv")

    fig, axes = plt.subplots(1, 4, figsize=(14, 4.2), facecolor=SURFACE, sharey=True,
                             gridspec_kw={"wspace": 0.1})
    for ax, region in zip(axes, REGIONS):
        style_axes(ax)
        s = a[a.region == region].sort_values("year")
        ax.plot(s.year, s.clearance_rate_pct, color=COLORS[region], lw=2.2, zorder=3,
                marker="o", markersize=6.5, markeredgecolor=SURFACE, markeredgewidth=1.3)
        ax.set_title(region, color=COLORS[region], fontsize=12, fontweight="bold",
                    pad=8, loc="left")
        ax.set_xticks(range(2020, 2026))
        ax.set_xticklabels([str(y)[2:] for y in range(2020, 2026)])
        ax.set_xlim(2019.5, 2025.5)
        ax.set_ylim(0, 7.4)
        ax.grid(axis="y", color=GRID, lw=0.8, zorder=0)

    axes[0].set_ylabel("Clearance rate\n(% of active backlog)", color=INK_2, fontsize=9.5)

    fig.suptitle("Clearance rate by region, 2020–2025",
                 x=0.045, y=0.96, ha="left", color=INK, fontsize=14.5, fontweight="bold")
    fig.text(0.045, 0.03,
             "MISO 2025 omitted (no completion dates recorded that year). "
             "Source: data/processed/analysis_panel.csv.",
             ha="left", color=MUTED, fontsize=8)

    fig.subplots_adjust(top=0.78, bottom=0.16, left=0.075, right=0.98)
    savefig(fig, "memo_clearance_by_year.png")


# ───────────────────────── 5. withdrawal parallel-trends (presentation)
def fig_withdrawal_trends():
    w = pd.read_csv("data/processed/withdrawal_rates.csv")
    w = w[w.year.between(2018, 2025)]
    wide = w.pivot(index="year", columns="region", values="rate_pct")[REGIONS]

    fig, ax = plt.subplots(figsize=(10, 6.4), facecolor=SURFACE)
    style_axes(ax)

    ax.axvspan(2022.5, 2025.4, color="#0b0b0b", alpha=0.045, lw=0, zorder=0)
    ax.axvline(2022.5, color=AXIS, lw=1, ls=(0, (4, 3)), zorder=1)
    ax.text(2022.65, 37.5, "FERC Order 2023 →", color=MUTED, fontsize=9, va="top")

    ends = []
    for region in REGIONS:
        s = wide[region]
        ax.plot(s.index, s.values, color=COLORS[region], lw=2.2, zorder=4,
                marker="o", markersize=5.5, markeredgecolor=SURFACE, markeredgewidth=1.2)
        ends.append([region, s.values[-1]])

    # PJM and SPP finish within ~1pp of each other in 2025; nudge apart so the
    # end labels do not print on top of each other.
    min_gap = 2.2
    ends.sort(key=lambda e: e[1])
    for i in range(1, len(ends)):
        if ends[i][1] - ends[i - 1][1] < min_gap:
            ends[i][1] = ends[i - 1][1] + min_gap
    for region, y in ends:
        ax.annotate(region, (wide.index[-1], y), xytext=(8, 0),
                    textcoords="offset points", va="center", color=COLORS[region],
                    fontsize=10.5, fontweight="bold", zorder=6)

    ax.grid(axis="y", color=GRID, lw=0.8, zorder=0)
    ax.set_xlim(2017.7, 2026.3)
    ax.set_xticks(range(2018, 2026))
    ax.set_ylim(0, 40)
    ax.set_ylabel("Withdrawal rate — % of at-risk projects", color=INK_2, fontsize=10.5)

    fig.suptitle("PJM, MISO and SPP withdrawal rates rise sharply after 2023 — ERCOT does not",
                 x=0.07, y=0.965, ha="left", color=INK, fontsize=14, fontweight="bold")
    fig.text(0.07, 0.9,
             "ERCOT is the one region of the four not bound by FERC Order 2023.",
             ha="left", color=INK_2, fontsize=9.5)
    fig.text(0.07, 0.03,
             "Hazard rate: projects withdrawn in year t / projects at risk in t. "
             "Source: data/processed/withdrawal_rates.csv.",
             ha="left", color=MUTED, fontsize=8)

    fig.subplots_adjust(top=0.84, bottom=0.12, left=0.09, right=0.93)
    savefig(fig, "memo_withdrawal_parallel_trends.png")


def main() -> int:
    fig_demand_index()
    fig_coefficient_plot()
    fig_coverage()
    fig_clearance_by_year()
    fig_withdrawal_trends()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
