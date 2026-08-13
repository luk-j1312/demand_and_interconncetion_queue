"""
Single source of truth for EIA-930 data-quality rules.

Both the pull script (which reports) and the cleaning script (which drops) import
the detection rule from here. If the threshold lived in two places, the hours we
report and the hours we exclude could silently diverge -- which is exactly the
kind of discrepancy a technical reviewer would catch and we couldn't explain.

The rule is entirely relative to each balancing authority's own rolling history.
There are no absolute MW ceilings anywhere in this file, deliberately: this is a
project about demand *growth*, so any fixed ceiling would eventually be crossed by
real load and start deleting good data. See DECISIONS.md D-1 and D-7.
"""

from __future__ import annotations

import pandas as pd

# --- High-side test: is this hour above anything this BA has ever plausibly hit? --
#
# Each hour is compared to the 99.9th percentile of its own BA over a centred
# two-year window -- i.e. the BA's own demonstrated peak *level* around that time.
# Real load grows gradually, so a genuine record beats the recent peak level by a
# few percent. Corruption beats it by tens of percent.
#
# Calibration against the 12 known-corrupt hours in the 2019-2026 series:
#   highest ratio reached by any legitimate annual peak : 1.05x
#     (ERCO 2026 record 1.02x, MISO 2024 peak 1.04x, SWPP 2026 peak 1.04x,
#      PJM 2025 peak 1.05x -- all four BAs agree)
#   lowest ratio of any corrupt hour                    : 1.21x
# 1.15 sits in that gap with roughly 10pp of headroom on the legitimate side.
#
# Note the window is *centred*, not trailing, so a sustained step up in load
# raises the baseline from both directions and is not flagged. Only an isolated
# spike far above the surrounding two years trips this. (Retrospective analysis,
# so using later data in the baseline is legitimate -- and it removes the
# cold-start problem a trailing window would have in 2019.)
PEAK_WINDOW = "731D"
PEAK_QUANTILE = 0.999
PEAK_RATIO = 1.15

# --- Spike test: is this hour discontinuous with the hours either side of it? ---
#
# The peak-level test above has a blind spot: an isolated spike that lands just
# under the BA's annual peak looks like a legitimate new record. PJM's reported
# 2019 maximum was exactly this case -- 155,276 MWh sandwiched between 98,466 and
# 108,808, only 1.05x the two-year peak level but 1.50x its own neighbours.
#
# Electricity demand is physically continuous: aggregate load cannot rise 50% in
# one hour and fall back the next. So each hour is compared to the mean of the
# hours immediately before and after it. Measured across all four BAs, legitimate
# hours sit at 1.00-1.06x (ERCO and MISO never exceed 1.06x even on the steepest
# morning ramps); the highest legitimate value anywhere in the series is 1.22x,
# and corrupt spikes run 1.42x to 113x. 1.35 sits in that gap.
#
# This test and the peak-level test catch different failure modes and neither
# subsumes the other -- two of the corrupt hours are invisible to this test but
# caught by peak-level, and one is the reverse. Both are applied.
SPIKE_RATIO = 1.35

# --- Low-side test: has this hour collapsed relative to its neighbours? ---
#
# Catches zeros, negatives, and dropouts, which the high-side test cannot see. A
# centred 7-day median is the right comparison here because we're asking about a
# departure from normal *level*, not from a peak.
MEDIAN_WINDOW = "169h"
LOWER_RATIO = 0.33

MIN_PERIODS = 2000   # ~83 days; lets hours near the series edges still get a baseline
MAX_PASSES = 5       # iteration guard; converges in 2-3 in practice


def _single_pass(df: pd.DataFrame) -> pd.DataFrame:
    """Flag implausible rows in one pass, per balancing authority."""
    out = []
    for ba, grp in df.sort_values("timestamp_utc").groupby(
        "balancing_authority", observed=True
    ):
        series = grp.set_index("timestamp_utc")["demand_mwh"].sort_index()

        peak_base = series.rolling(
            PEAK_WINDOW, center=True, min_periods=MIN_PERIODS
        ).quantile(PEAK_QUANTILE)
        peak_ratio = series / peak_base

        med_base = series.rolling(MEDIAN_WINDOW, center=True, min_periods=24).median()
        med_ratio = series / med_base

        # Neighbour mean, only where both neighbours are exactly one hour away, so
        # the DST reporting gaps don't produce a spurious discontinuity.
        gaps = series.index.to_series()
        adjacent = (gaps.diff() == pd.Timedelta("1h")) & (gaps.diff(-1) == -pd.Timedelta("1h"))
        nbr_base = (series.shift(1) + series.shift(-1)) / 2
        nbr_base = nbr_base.where(adjacent)
        nbr_ratio = series / nbr_base

        high = (peak_ratio > PEAK_RATIO).fillna(False)
        spike = (nbr_ratio > SPIKE_RATIO).fillna(False)
        low = (med_ratio < LOWER_RATIO).fillna(False)
        mask = high | spike | low
        if not mask.any():
            continue

        # Precedence when more than one test fires: report the one that speaks to
        # magnitude first, since that's the more serious claim.
        def pick(h, s):
            return "peak-level" if h else ("isolated-spike" if s else "level-collapse")

        tests = [pick(h, s) for h, s in zip(high[mask].values, spike[mask].values)]
        base_by_test = {"peak-level": peak_base, "isolated-spike": nbr_base,
                        "level-collapse": med_base}
        ratio_by_test = {"peak-level": peak_ratio, "isolated-spike": nbr_ratio,
                         "level-collapse": med_ratio}
        idx = series.index[mask]

        flagged = pd.DataFrame(
            {
                "timestamp_utc": idx,
                "balancing_authority": ba,
                "demand_mwh": series[mask].values,
                "test": tests,
                "baseline": [base_by_test[t].loc[i] for t, i in zip(tests, idx)],
                "ratio": [ratio_by_test[t].loc[i] for t, i in zip(tests, idx)],
            }
        )
        out.append(flagged)

    if not out:
        return pd.DataFrame(
            columns=["timestamp_utc", "balancing_authority", "demand_mwh",
                     "test", "baseline", "ratio"]
        )
    return pd.concat(out, ignore_index=True)


def flag_implausible(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return the rows of `df` whose demand is implausible under the rules above.

    Applied iteratively: a corrupt hour is itself part of the percentile used to
    judge it, so the first pass computes a baseline inflated by the very values it
    is trying to catch. Removing the flagged hours and recomputing tightens the
    baseline and can expose borderline cases the first pass missed. Iteration only
    ever makes the separation cleaner -- it cannot un-flag an hour.

    Adds `test` (which rule fired), `baseline`, `ratio`, `reason`, and `pass`
    columns so every exclusion is self-documenting.

    Null demand values are NOT flagged: a missing value is a different problem
    from a wrong one, handled separately (see DECISIONS.md D-3).
    """
    key = ["timestamp_utc", "balancing_authority"]
    working = df.copy()
    collected = []

    for n in range(1, MAX_PASSES + 1):
        found = _single_pass(working)
        if found.empty:
            break
        found["pass"] = n
        collected.append(found)
        working = working.merge(found[key], on=key, how="left", indicator=True)
        working = working[working["_merge"] == "left_only"].drop(columns="_merge")

    if not collected:
        return pd.DataFrame(
            columns=["timestamp_utc", "balancing_authority", "demand_mwh",
                     "test", "baseline", "ratio", "reason", "pass"]
        )

    result = pd.concat(collected, ignore_index=True)
    _phrase = {
        "peak-level": "the 2-year p99.9 peak level",
        "isolated-spike": "the mean of the adjacent hours",
        "level-collapse": "the 7-day local median",
    }
    result["reason"] = [
        f"{r.ratio:,.2f}x {_phrase[r.test]} ({r.baseline:,.0f} MWh)"
        for r in result.itertuples()
    ]
    return result.sort_values("ratio", ascending=False).reset_index(drop=True)
