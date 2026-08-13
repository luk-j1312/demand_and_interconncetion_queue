"""
Phase 3 diagnostics. Three views of the analysis panel. Nothing is fitted.

Reads   data/processed/analysis_panel.csv
Writes  figures/diag_clearance_by_year.png       clearance vs year, one panel per region
        figures/diag_scatter_by_year.png         the main scatter, coloured by YEAR not region
        figures/diag_scatter_no_ercot2022.png    the main scatter minus the leverage point

These exist to test three specific readings of the first look:
  1. is the within-region decline in clearance real and monotone, or an artifact of
     describing it in prose?
  2. does the cloud's shape track early-vs-late years rather than the growth value?
  3. does anything change when ERCOT 2022 (+9.70%, alone in the right tail) is removed?

    python plot_analysis_diagnostics.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

PANEL_PATH = Path("data/processed/analysis_panel.csv")
FIG_DIR = Path("figures")

REGIONS = ["PJM", "ERCOT", "MISO", "SPP"]
SHORT = {"PJM": "PJM", "ERCOT": "ERC", "MISO": "MSO", "SPP": "SPP"}

# Categorical slots 1-3 + 7, validated all-pairs. Same hue per region as every
# other figure in the project -- colour follows the entity, not the chart.
COLORS = {"PJM": "#2a78d6", "MISO": "#eb6834", "SPP": "#1baf7a", "ERCOT": "#4a3aa7"}

# Ordinal ramp for year: six steps sampled evenly in OKLab between the documented
# blue ramp's 250 and 700 steps. Six *documented* steps cannot be used directly --
# the ramp's own spacing is ~0.047 in L, so any six of them force one adjacent gap
# below the 0.06 floor. These realized steps clear every ordinal gate: monotone L,
# min adjacent dL 0.084, light end 2.06:1, hue spread 4 deg.
YEAR_RAMP = {
    2020: "#86b6ef", 2021: "#6d9bd3", 2022: "#5480b8",
    2023: "#3c679e", 2024: "#254e84", 2025: "#0d366b",
}

SURFACE = "#fcfcfb"
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"

LEVERAGE_POINT = ("ERCOT", 2022)


def decollide(ax, fig, points, labels, sizes=(0.903, 0.730)):
    """Greedy label placement: try above, below, then diagonals; take the first
    slot clearing every label already placed. Tested in axes fractions, i.e. in
    screen space, so it is independent of the data's units."""
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    candidates = [(0, 10), (0, -17), (13, 3), (-13, 3), (14, -11), (-14, -11)]
    placed: list[tuple[float, float]] = []
    out = []
    for (px_data, py_data), text in zip(points, labels):
        px = (px_data - x0) / (x1 - x0)
        py = (py_data - y0) / (y1 - y0)
        for dx, dy in candidates:
            fx = px + dx / 72 / fig.get_size_inches()[0] / sizes[0]
            fy = py + dy / 72 / fig.get_size_inches()[1] / sizes[1]
            if all(abs(fx - qx) > 0.033 or abs(fy - qy) > 0.033 for qx, qy in placed):
                break
        placed.append((fx, fy))
        out.append(((px_data, py_data), text, (dx, dy)))
    return out


def style(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(color=GRID, lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)


# ─────────────────────────────────────────────── 1. clearance vs year, per region
def plot_clearance_by_year(panel: pd.DataFrame) -> None:
    fig, axes = plt.subplots(
        1, 4, figsize=(15, 4.6), facecolor=SURFACE, sharey=True,
        gridspec_kw={"wspace": 0.12},
    )

    for ax, region in zip(axes, REGIONS):
        s = panel[panel.region == region].sort_values("year")
        style(ax)
        ax.plot(s.year, s.clearance_rate, color=COLORS[region], lw=2, zorder=3)
        ordinary = s[~s.likely_reform_driven]
        reform = s[s.likely_reform_driven]
        ax.scatter(ordinary.year, ordinary.clearance_rate, s=70, color=COLORS[region],
                   edgecolors=SURFACE, linewidths=1.2, zorder=4)
        ax.scatter(reform.year, reform.clearance_rate, s=85, marker="D",
                   facecolors=SURFACE, edgecolors=COLORS[region], linewidths=2, zorder=5)

        for _, r in s.iterrows():
            # First and last points sit on the panel edge; nudge their labels
            # inward so they are not clipped by the spine.
            off = (9, 7) if r.year == 2020 else (-9, 7) if r.year == 2025 else (0, 11)
            ax.annotate(f"{r.clearance_rate:.0f}", (r.year, r.clearance_rate),
                        xytext=off, textcoords="offset points", ha="center",
                        color=MUTED, fontsize=7.5, zorder=6, clip_on=False)

        ax.set_title(region, color=COLORS[region], fontsize=12, fontweight="bold",
                     pad=8, loc="left")
        ax.set_xticks(range(2020, 2026))
        ax.set_xticklabels([str(y)[2:] for y in range(2020, 2026)])
        ax.set_xlim(2019.45, 2025.55)
        ax.set_ylim(0, 78)

        missing = [y for y in range(2020, 2026) if y not in set(s.year)]
        if missing:
            # Top-right: the only corner guaranteed clear in the panel that has
            # a missing year, since its series has fallen to the floor by then.
            ax.text(0.98, 0.97, f"{', '.join(str(m) for m in missing)} excluded",
                    transform=ax.transAxes, ha="right", va="top", color=MUTED,
                    fontsize=8, style="italic")

    axes[0].set_ylabel("Clearance rate — MW per GW of backlog", color=INK_2, fontsize=10)

    fig.suptitle("Clearance collapses in MISO and SPP — and holds flat in PJM and ERCOT",
                 x=0.048, y=0.965, ha="left", color=INK, fontsize=15, fontweight="bold")
    fig.text(0.048, 0.885,
             "Same vertical scale across panels. MISO −92% and SPP −80% first year to last; "
             "PJM −4% and ERCOT +12%. Hollow diamonds are likely_reform_driven years.",
             ha="left", color=INK_2, fontsize=9.5)
    fig.text(0.048, 0.03,
             "MISO 2025 excluded — no on_date records that year (operational_series_usable=False). "
             "Source: data/processed/analysis_panel.csv.",
             ha="left", color=MUTED, fontsize=8)

    fig.subplots_adjust(top=0.775, bottom=0.135, left=0.048, right=0.985)
    out = FIG_DIR / "diag_clearance_by_year.png"
    fig.savefig(out, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    print(f"Wrote {out}")


# ──────────────────────────────────────────────────── 2. scatter coloured by year
def plot_scatter_by_year(panel: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(11, 7.2), facecolor=SURFACE)
    style(ax)
    ax.axvline(0, color=AXIS, lw=1, ls=(0, (4, 3)), zorder=1)

    for year, sub in panel.groupby("year"):
        ax.scatter(sub.demand_growth_yoy * 100, sub.clearance_rate, s=110,
                   color=YEAR_RAMP[year], edgecolors=SURFACE, linewidths=1.2, zorder=4)

    ax.set_xlim(*ax.get_xlim())
    ax.set_ylim(*ax.get_ylim())
    pts = list(zip(panel.demand_growth_yoy * 100, panel.clearance_rate))
    # Region carries the label here, since colour has been reassigned to year --
    # identity is never colour-alone in either encoding.
    for (x, y), text, (dx, dy) in decollide(
        ax, fig, pts, [SHORT[r] for r in panel.region]
    ):
        ax.annotate(text, (x, y), xytext=(dx, dy), textcoords="offset points",
                    ha="center", va="bottom" if dy >= 0 else "top",
                    color=MUTED, fontsize=7.5, zorder=5)

    handles = [plt.Line2D([], [], marker="o", ls="", markersize=9,
                          color=YEAR_RAMP[y], label=str(y)) for y in sorted(YEAR_RAMP)]
    ax.legend(handles=handles, frameon=False, ncol=6, loc="upper left",
              bbox_to_anchor=(0, 1.055), fontsize=10, labelcolor=INK_2,
              handletextpad=0.35, columnspacing=1.4)

    ax.set_xlabel("Year-over-year growth in annual mean demand (%)", color=INK_2, fontsize=10.5)
    ax.set_ylabel("Clearance rate — MW per GW of active backlog", color=INK_2, fontsize=10.5)
    fig.suptitle("The same scatter, coloured by year instead of region",
                 x=0.072, y=0.972, ha="left", color=INK, fontsize=15.5, fontweight="bold")
    fig.text(0.072, 0.923,
             "Points labelled by region. Light = 2020, dark = 2025. Colour drifts downward "
             "but does not sort the cloud: 2024 holds both the lowest point (MSO 5.4) and "
             "the second-highest (ERC 45.7).",
             ha="left", color=INK_2, fontsize=9.5)
    fig.text(0.072, 0.028,
             "23 region-years. No fitted line, no correlation. Source: data/processed/analysis_panel.csv.",
             ha="left", color=MUTED, fontsize=8)

    fig.subplots_adjust(top=0.855, bottom=0.115, left=0.072, right=0.975)
    out = FIG_DIR / "diag_scatter_by_year.png"
    fig.savefig(out, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    print(f"Wrote {out}")


# ────────────────────────────────────────── 3. main scatter minus leverage point
def plot_scatter_without_leverage(panel: pd.DataFrame) -> None:
    region, year = LEVERAGE_POINT
    kept = panel[~((panel.region == region) & (panel.year == year))]

    fig, ax = plt.subplots(figsize=(11, 7.2), facecolor=SURFACE)
    style(ax)
    ax.axvline(0, color=AXIS, lw=1, ls=(0, (4, 3)), zorder=1)

    for rg in REGIONS:
        s = kept[kept.region == rg]
        for is_reform, sub in s.groupby("likely_reform_driven"):
            if sub.empty:
                continue
            ax.scatter(sub.demand_growth_yoy * 100, sub.clearance_rate,
                       s=115 if is_reform else 95, marker="D" if is_reform else "o",
                       facecolors=SURFACE if is_reform else COLORS[rg],
                       edgecolors=COLORS[rg], linewidths=2.0 if is_reform else 1.2,
                       zorder=4)

    ax.set_xlim(*ax.get_xlim())
    ax.set_ylim(*ax.get_ylim())
    pts = list(zip(kept.demand_growth_yoy * 100, kept.clearance_rate))
    for (x, y), text, (dx, dy) in decollide(
        ax, fig, pts, [f"{int(yr) % 100:02d}" for yr in kept.year]
    ):
        ax.annotate(text, (x, y), xytext=(dx, dy), textcoords="offset points",
                    ha="center", va="bottom" if dy >= 0 else "top",
                    color=MUTED, fontsize=7.5, zorder=5)

    region_handles = [plt.Line2D([], [], marker="o", ls="", markersize=9,
                                 color=COLORS[r], label=r) for r in REGIONS]
    shape_handles = [
        plt.Line2D([], [], marker="o", ls="", markersize=9, color=MUTED, label="ordinary year"),
        plt.Line2D([], [], marker="D", ls="", markersize=9, markerfacecolor=SURFACE,
                   markeredgecolor=MUTED, markeredgewidth=2, color=MUTED,
                   label="likely reform-driven"),
    ]
    first = ax.legend(handles=region_handles, frameon=False, ncol=4, loc="upper left",
                      bbox_to_anchor=(0, 1.055), fontsize=10, labelcolor=INK_2,
                      handletextpad=0.35, columnspacing=1.5)
    ax.add_artist(first)
    ax.legend(handles=shape_handles, frameon=False, ncol=2, loc="upper right",
              bbox_to_anchor=(1, 1.055), fontsize=9.5, labelcolor=INK_2,
              handletextpad=0.35, columnspacing=1.4)

    ax.set_xlabel("Year-over-year growth in annual mean demand (%)", color=INK_2, fontsize=10.5)
    ax.set_ylabel("Clearance rate — MW per GW of active backlog", color=INK_2, fontsize=10.5)
    fig.suptitle(f"The main scatter with {region} {year} removed",
                 x=0.072, y=0.972, ha="left", color=INK, fontsize=15.5, fontweight="bold")
    full_range = (panel.demand_growth_yoy.max() - panel.demand_growth_yoy.min()) * 100
    kept_range = (kept.demand_growth_yoy.max() - kept.demand_growth_yoy.min()) * 100
    fig.text(0.072, 0.923,
             f"{len(kept)} region-years. Dropping the one high-leverage point compresses the "
             f"x-range from {full_range:.1f} to {kept_range:.1f} points and leaves the "
             "vertical spread untouched.",
             ha="left", color=INK_2, fontsize=9.5)
    fig.text(0.072, 0.028,
             "Points labelled by year. No fitted line, no correlation. Source: data/processed/analysis_panel.csv.",
             ha="left", color=MUTED, fontsize=8)

    fig.subplots_adjust(top=0.855, bottom=0.115, left=0.072, right=0.975)
    out = FIG_DIR / "diag_scatter_no_ercot2022.png"
    fig.savefig(out, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    print(f"Wrote {out}")


def describe(panel: pd.DataFrame) -> None:
    region, year = LEVERAGE_POINT
    kept = panel[~((panel.region == region) & (panel.year == year))]

    print("\nClearance rate by region-year (MW per GW)")
    print("-" * 78)
    print(panel.pivot(index="region", columns="year", values="clearance_rate")
          .reindex(REGIONS).round(1).to_string(na_rep="  --"))
    print("-" * 78)

    print("\nWithin-region change, first to last observed year")
    for r in REGIONS:
        s = panel[panel.region == r].sort_values("year")
        print(f"  {r:<7}{s.clearance_rate.iloc[0]:>6.1f} ({int(s.year.iloc[0])})"
              f"  ->{s.clearance_rate.iloc[-1]:>6.1f} ({int(s.year.iloc[-1])})"
              f"   {s.clearance_rate.iloc[-1] / s.clearance_rate.iloc[0] - 1:>+7.0%}")

    print("\nClearance rate by year, pooled across regions")
    print("-" * 78)
    g = panel.groupby("year").clearance_rate.agg(["count", "min", "median", "max"])
    print(g.round(1).to_string())
    print("-" * 78)

    print("\nEffect of dropping the leverage point on the x-range only")
    for label, d in [("with ERCOT 2022", panel), ("without", kept)]:
        lo, hi = d.demand_growth_yoy.min() * 100, d.demand_growth_yoy.max() * 100
        print(f"  {label:<18}n={len(d):>3}   growth {lo:+.2f}% to {hi:+.2f}%"
              f"   range {hi - lo:.1f} pp   clearance {d.clearance_rate.min():.1f}"
              f"-{d.clearance_rate.max():.1f}")


def main() -> int:
    if not PANEL_PATH.exists():
        print(f"ERROR: {PANEL_PATH} not found. Run build_analysis_panel.py first.")
        return 1

    panel = pd.read_csv(PANEL_PATH)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    describe(panel)
    print()
    plot_clearance_by_year(panel)
    plot_scatter_by_year(panel)
    plot_scatter_without_leverage(panel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
