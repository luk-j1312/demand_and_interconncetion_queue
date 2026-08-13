"""
Plot one balancing authority's hourly demand across a single week.

A sanity/eyeball figure for the EIA-930 pull: does the series show the diurnal and
weekday/weekend structure real electricity load has? If it doesn't, the pull is
wrong regardless of what the row counts say.

Usage
-----
    python plot_demand_week.py                      # PJM, most recent complete week
    python plot_demand_week.py ERCO
    python plot_demand_week.py ERCO 2026-07-06      # week starting that Monday

Output: figures/demand_week_<BA>_<start>.png
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # write files, don't try to open a GUI window

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

OUT_DIR = Path("figures")

# Prefer the cleaned series (implausible hours excluded — see DECISIONS.md) and
# fall back to raw so the plot still works before clean_eia930.py has been run.
_CLEAN = Path("data/processed/eia930_hourly_demand.csv")
_RAW = Path("data/raw/eia930_hourly_demand.csv")
CSV_PATH = _CLEAN if _CLEAN.exists() else _RAW

# Demand is reported in UTC, but the shape only makes sense in local time -- the
# evening peak has to land in the evening. Each BA is mapped to the timezone the
# bulk of its load actually sits in. (MISO and SWPP both span more than one zone;
# Central is where most of their load is, and this is a diagnostic plot, not an
# analysis input, so a single representative zone is fine.)
BA_TIMEZONE = {
    "PJM": "America/New_York",
    "ERCO": "America/Chicago",
    "MISO": "America/Chicago",
    "SWPP": "America/Chicago",
}

BA_LABEL = {
    "PJM": "PJM Interconnection",
    "ERCO": "ERCOT",
    "MISO": "MISO",
    "SWPP": "Southwest Power Pool",
}

# From the dataviz reference palette (light mode). One series, so categorical
# slot 1 and no legend box -- the title names what's plotted.
SERIES = "#2a78d6"
SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"


def load_ba_week(ba: str, week_start: str | None) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Return one BA's demand for one Mon-Sun week, indexed in local time."""
    df = pd.read_csv(CSV_PATH, parse_dates=["timestamp_utc"])
    df = df[df["balancing_authority"] == ba]
    if df.empty:
        raise SystemExit(f"No rows for '{ba}'. Available: {', '.join(BA_LABEL)}")

    # Convert to local time BEFORE slicing, so the week boundaries are local
    # midnights rather than 8pm the previous evening.
    local = df["timestamp_utc"].dt.tz_convert(BA_TIMEZONE[ba])
    series = pd.Series(df["demand_mwh"].values, index=local).sort_index()

    if week_start is None:
        # Most recent complete Mon-Sun week: step back from the last full local
        # day to the Monday of the preceding week.
        last_full_day = series.index.max().normalize() - pd.Timedelta(days=1)
        monday = last_full_day - pd.Timedelta(days=last_full_day.weekday() + 7)
    else:
        monday = pd.Timestamp(week_start, tz=BA_TIMEZONE[ba]).normalize()
        if monday.weekday() != 0:
            monday -= pd.Timedelta(days=monday.weekday())

    end = monday + pd.Timedelta(days=7)
    week = series.loc[(series.index >= monday) & (series.index < end)]
    if week.empty:
        raise SystemExit(f"No data for {ba} in week of {monday:%Y-%m-%d}")

    out = week.rename("demand_mwh").to_frame()
    out["demand_gw"] = out["demand_mwh"] / 1_000  # MWh per hour == average GW
    return out, monday


def plot(ba: str, week_start: str | None = None) -> Path:
    week, monday = load_ba_week(ba, week_start)
    tz_label = week.index[0].strftime("%Z")

    fig, ax = plt.subplots(figsize=(11, 4.6), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    # Weekends shaded before the data is drawn, so the wash sits behind the line.
    # Weekend load drop is a real structural feature and worth making visible.
    for day_offset in (5, 6):
        start = monday + pd.Timedelta(days=day_offset)
        ax.axvspan(start, start + pd.Timedelta(days=1),
                   color=GRIDLINE, alpha=0.45, linewidth=0, zorder=0)

    # Recessive horizontal hairline grid only; vertical structure is carried by
    # the day ticks and the weekend shading.
    ax.grid(axis="y", color=GRIDLINE, linewidth=1, linestyle="-", zorder=1)
    ax.set_axisbelow(True)

    ax.plot(week.index, week["demand_gw"], color=SERIES, linewidth=2,
            solid_capstyle="round", solid_joinstyle="round", zorder=3)

    # Label the weekly peak only -- one direct label, not a number per point.
    peak_ts = week["demand_gw"].idxmax()
    peak_val = week["demand_gw"].max()
    ax.plot([peak_ts], [peak_val], marker="o", markersize=8, color=SERIES,
            markeredgecolor=SURFACE, markeredgewidth=2, zorder=4)  # 2px surface ring
    # Built without %-d / %-I: those are glibc extensions and raise on Windows.
    hour12 = peak_ts.hour % 12 or 12
    ampm = "am" if peak_ts.hour < 12 else "pm"
    peak_when = f"{peak_ts.strftime('%a')} {peak_ts.day} {peak_ts.strftime('%b')}, {hour12}{ampm}"
    ax.annotate(
        f"Week peak {peak_val:,.1f} GW\n{peak_when}",
        xy=(peak_ts, peak_val), xytext=(8, -4), textcoords="offset points",
        ha="left", va="top", fontsize=9, color=INK_SECONDARY, linespacing=1.4,
        # The peak can fall anywhere in the week, so the label can land on the
        # line. A surface-colored backing keeps it readable without a border.
        bbox=dict(facecolor=SURFACE, edgecolor="none", alpha=0.85,
                  boxstyle="round,pad=0.3"),
        zorder=5,
    )

    trough_val = week["demand_gw"].min()
    ax.set_ylim(trough_val * 0.88, peak_val * 1.12)

    ax.xaxis.set_major_locator(mdates.DayLocator(tz=week.index.tz))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a\n%d %b", tz=week.index.tz))
    ax.xaxis.set_minor_locator(mdates.HourLocator(byhour=12, tz=week.index.tz))
    ax.set_xlim(monday, monday + pd.Timedelta(days=7))

    ax.set_ylabel("Demand (GW)", fontsize=9, color=INK_SECONDARY, labelpad=8)
    ax.tick_params(axis="both", colors=INK_MUTED, labelsize=9, length=0)
    ax.tick_params(axis="x", which="minor", length=0)
    for tick in ax.get_yticklabels():
        tick.set_fontfamily("monospace")  # tabular-ish alignment on axis ticks

    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.spines["bottom"].set_linewidth(1)

    # Title and subtitle are both placed as axes text at explicit heights rather
    # than via set_title -- set_title's pad is measured in points and collides
    # with a subtitle positioned in axes fraction, which silently overprints.
    mean_gw = week["demand_gw"].mean()
    ax.text(
        0, 1.155, f"{BA_LABEL[ba]} hourly electricity demand",
        transform=ax.transAxes, fontsize=13, color=INK_PRIMARY,
        fontweight="bold", va="bottom",
    )
    ax.text(
        0, 1.045,
        f"Week of {monday.day} {monday:%B %Y} · local time ({tz_label}) · "
        f"mean {mean_gw:,.1f} GW · shaded = weekend",
        transform=ax.transAxes, fontsize=9, color=INK_SECONDARY, va="bottom",
    )
    fig.text(
        0.005, -0.02, "Source: EIA-930 via EIA API v2 (electricity/rto/region-data, type=D)",
        fontsize=8, color=INK_MUTED,
    )

    OUT_DIR.mkdir(exist_ok=True)
    out_path = OUT_DIR / f"demand_week_{ba}_{monday:%Y%m%d}.png"
    fig.savefig(out_path, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)

    print(f"{ba} · week of {monday:%Y-%m-%d} ({tz_label})")
    print(f"  hours plotted : {len(week)} (expected 168)")
    print(f"  peak          : {peak_val:,.1f} GW at {peak_ts:%a %Y-%m-%d %H:%M}")
    print(f"  trough        : {trough_val:,.1f} GW")
    print(f"  peak/trough   : {peak_val / trough_val:.2f}x")
    print(f"  wrote         : {out_path}")
    return out_path


if __name__ == "__main__":
    ba_arg = sys.argv[1].upper() if len(sys.argv) > 1 else "PJM"
    week_arg = sys.argv[2] if len(sys.argv) > 2 else None
    plot(ba_arg, week_arg)
