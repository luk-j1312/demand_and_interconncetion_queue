"""
Produce the analysis-ready EIA-930 demand series from the raw pull.

Reads   data/raw/eia930_hourly_demand.csv        (as-reported, never modified)
Writes  data/processed/eia930_hourly_demand.csv  (5 implausible hours dropped)
        data/processed/excluded_hours.csv        (the audit trail of what went)

Why this is a separate script and not part of the pull: re-downloading 266k rows
takes ~10 minutes and hits intermittent 503s. Cleaning rules get revisited; the
download shouldn't be coupled to them. Raw stays immutable so any exclusion can
always be undone or re-examined.

    python clean_eia930.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from eia930_quality import flag_implausible

RAW_PATH = Path("data/raw/eia930_hourly_demand.csv")
CLEAN_PATH = Path("data/processed/eia930_hourly_demand.csv")
EXCLUDED_PATH = Path("data/processed/excluded_hours.csv")


def main() -> int:
    if not RAW_PATH.exists():
        print(f"ERROR: {RAW_PATH} not found. Run pull_eia930_demand.py first.")
        return 1

    raw = pd.read_csv(RAW_PATH, parse_dates=["timestamp_utc"])
    print(f"Read {len(raw):,} raw rows from {RAW_PATH}")

    excluded = flag_implausible(raw)

    if excluded.empty:
        print("No implausible hours detected — clean series is identical to raw.")
        clean = raw.copy()
    else:
        print(f"\nExcluding {len(excluded)} implausible hour(s):")
        print("-" * 78)
        for _, r in excluded.iterrows():
            print(
                f"  {r.balancing_authority:<5} {r.timestamp_utc:%Y-%m-%d %H:%M} UTC  "
                f"reported={r.demand_mwh:>14,.0f}  baseline={r.baseline:>9,.0f}  "
                f"({r.ratio:>9,.2f}x, {r.test}, pass {r['pass']})"
            )
        print("-" * 78)

        # Anti-join on the (timestamp, BA) key rather than a positional drop, so
        # this is correct regardless of row order in the raw file.
        key = ["timestamp_utc", "balancing_authority"]
        clean = raw.merge(excluded[key], on=key, how="left", indicator=True)
        clean = clean[clean["_merge"] == "left_only"].drop(columns="_merge")

        assert len(clean) == len(raw) - len(excluded), "drop removed unexpected row count"

    CLEAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(CLEAN_PATH, index=False)
    excluded.to_csv(EXCLUDED_PATH, index=False)

    print(f"\nWrote {len(clean):,} rows to {CLEAN_PATH}")
    print(f"Wrote {len(excluded):,} excluded rows to {EXCLUDED_PATH}")

    # Show the effect on the aggregate that actually feeds the analysis. This is
    # the number the exclusion exists to protect.
    print("\nEffect on mean demand (MWh) — the growth-rate input")
    print("-" * 78)
    print(f"{'BA':<6} {'raw mean':>14} {'clean mean':>14} {'change':>10}")
    print("-" * 78)
    for ba in sorted(raw["balancing_authority"].unique()):
        r_mean = raw.loc[raw.balancing_authority == ba, "demand_mwh"].mean()
        c_mean = clean.loc[clean.balancing_authority == ba, "demand_mwh"].mean()
        delta = (c_mean / r_mean - 1) * 100
        print(f"{ba:<6} {r_mean:>14,.0f} {c_mean:>14,.0f} {delta:>9.2f}%")
    print("-" * 78)

    # Null demand values are left in place: they are missing, not wrong. pandas
    # skips NaN in both sum() and mean() by default, so neither zeroes them --
    # the real risk downstream is dividing a total by an assumed hour count.
    # Flagged here so the count is visible rather than assumed. (See DECISIONS.md.)
    nulls = clean.groupby("balancing_authority", observed=True)["demand_mwh"].apply(
        lambda s: int(s.isna().sum())
    )
    if nulls.sum():
        print(f"\nNull demand values retained (missing, not wrong): {nulls.sum()} total")
        print(nulls[nulls > 0].to_string())
        print("Use .mean() directly downstream; never divide a total by 8760/8784 --")
        print("hours per BA-year are not uniform (leap years, exclusions, DST gaps).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
