"""
Pull hourly electricity demand by balancing authority from EIA-930 via EIA API v2.

Project: Data-Center Demand Growth & Generation-Interconnection Queue Congestion
Phase 1 — Data Acquisition (EIA-930 side)

Endpoint verified live against the API on 2026-08-04:
    https://api.eia.gov/v2/electricity/rto/region-data/data
    route name: "Hourly Demand, Demand Forecast, Generation, and Interchange"
    source:     Form EIA-930
    coverage:   2019-01-01T00 through present (see START_PERIOD note below)

Output: data/raw/eia930_hourly_demand.csv
    timestamp_utc, balancing_authority, demand_mwh
"""

from __future__ import annotations

import os
import random
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from eia930_quality import PEAK_RATIO, flag_implausible

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://api.eia.gov/v2/electricity/rto/region-data/data"

# Facet codes confirmed against .../region-data/facet/respondent — these are the
# API's exact IDs, not guesses. Note ERCOT's code is ERCO.
BALANCING_AUTHORITIES = {
    "PJM": "PJM Interconnection, LLC",
    "ERCO": "Electric Reliability Council of Texas, Inc.",
    "MISO": "Midcontinent Independent System Operator, Inc.",
    "SWPP": "Southwest Power Pool",
}

# Metric facet: D = Demand. (Others on this route: DF day-ahead forecast,
# NG net generation, TI total interchange.) We only want actual demand.
METRIC = "D"

# The request asked for January 2018, but this route's startPeriod is
# 2019-01-01T00 and a test request for 2018 returns total=0 — there is no
# pre-2019 data to page through here. See the README note on the bulk-CSV
# route if the 2015-2018 tail is needed later.
START_PERIOD = "2019-01-01T00"
END_PERIOD = None  # None => through the latest hour EIA has published

# The API's hard ceiling is 5,000 rows per JSON response. Requesting more does
# not error, it just silently truncates (and returns a warning header), so we
# pin length to exactly the cap and paginate.
PAGE_SIZE = 5_000

# EIA's published limits: stay under ~9,000 requests/hour sustained and 5/sec
# burst and your key won't be throttled. This pull is ~54 requests total, so
# we're nowhere near either bound; the delay below is just good manners.
POLITE_DELAY_SEC = 0.30

MAX_RETRIES = 6
REQUEST_TIMEOUT_SEC = 60

OUT_PATH = Path("data/raw/eia930_hourly_demand.csv")


# ---------------------------------------------------------------------------
# HTTP layer: one request, with retries
# ---------------------------------------------------------------------------

def request_page(session: requests.Session, params: dict) -> dict:
    """
    Make a single API request and return the parsed JSON body.

    Retries with exponential backoff on the failures that are worth retrying:
      * 429 Too Many Requests  -> we hit the rate limit
      * 5xx Server Error       -> EIA's API is genuinely flaky; live testing of
                                  this endpoint returned intermittent 503s on
                                  roughly a third of calls, so this is not a
                                  theoretical safeguard
      * connection/timeout errors

    A 400/403 is NOT retried — those mean the request itself is malformed or the
    key is bad, and hammering the API won't fix either. Fail loudly instead.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(BASE_URL, params=params, timeout=REQUEST_TIMEOUT_SEC)
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"network failure after {MAX_RETRIES} attempts: {exc}")
            _backoff(attempt, f"network error ({exc.__class__.__name__})")
            continue

        if resp.status_code == 200:
            # The API warns rather than errors if a request exceeds the row cap.
            warning = resp.headers.get("X-Warning") or resp.headers.get("Warning")
            if warning:
                print(f"    ! API warning: {warning}", file=sys.stderr)
            return resp.json()

        if resp.status_code in (429, 500, 502, 503, 504):
            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"HTTP {resp.status_code} after {MAX_RETRIES} attempts: {resp.text[:300]}"
                )
            # Honour Retry-After when the server tells us how long to wait.
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                wait = int(retry_after)
                print(f"    retrying in {wait}s (HTTP {resp.status_code}, Retry-After)")
                time.sleep(wait)
            else:
                _backoff(attempt, f"HTTP {resp.status_code}")
            continue

        raise RuntimeError(f"HTTP {resp.status_code} (not retryable): {resp.text[:500]}")

    raise RuntimeError("unreachable")


def _backoff(attempt: int, reason: str) -> None:
    """
    Exponential backoff with jitter: 1s, 2s, 4s, 8s, 16s (+/- randomness).

    The jitter matters if you ever parallelise this — without it, concurrent
    workers that fail together retry in lockstep and re-collide immediately.
    """
    wait = (2 ** (attempt - 1)) + random.uniform(0, 1)
    print(f"    retrying in {wait:.1f}s ({reason}, attempt {attempt}/{MAX_RETRIES})")
    time.sleep(wait)


# ---------------------------------------------------------------------------
# Pagination layer: walk one BA's full history
# ---------------------------------------------------------------------------

def fetch_ba(session: requests.Session, api_key: str, ba: str) -> list[dict]:
    """
    Fetch every hourly demand row for one balancing authority.

    How the pagination works
    ------------------------
    The API caps each response at 5,000 rows, but every response also reports
    `response.total` — the size of the *full* result set your filters match. So
    we don't have to guess when to stop:

        1. Ask for rows [0 .. 5000)      -> read `total` from the first response
        2. Ask for rows [5000 .. 10000)
        3. ... until we've collected `total` rows.

    `offset` is "how many rows to skip", `length` is "how many to return".
    Crucially we advance `offset` by the number of rows we *actually received*,
    not by PAGE_SIZE — if the API ever returns a short page, a hardcoded += 5000
    would silently skip data.

    Why sorting ascending by period matters
    --------------------------------------
    Offset pagination assumes stable ordering. Two safeguards here:

      * We sort explicitly by (period, respondent). Without an explicit sort the
        API's default ordering isn't guaranteed stable across requests, and rows
        could be duplicated or missed between pages.
      * We sort *ascending*. This dataset is live — EIA appends new hours while
        we're paging. Ascending means new rows land at the end, after the window
        we've already walked, so they can't shift earlier rows onto different
        offsets. Descending sort would push every existing row one offset
        deeper the moment a new hour published, which is a real (and silent)
        way to lose rows mid-pull.

    Two independent stop conditions guard against an infinite loop: an empty
    page, and having collected at least `total` rows.
    """
    params = {
        "api_key": api_key,
        "frequency": "hourly",          # UTC hourly. ("local-hourly" is the other option.)
        "data[0]": "value",             # the only data column this route exposes
        "facets[respondent][]": ba,
        "facets[type][]": METRIC,
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "sort[1][column]": "respondent",
        "sort[1][direction]": "asc",
        "start": START_PERIOD,
        "length": PAGE_SIZE,
    }
    if END_PERIOD:
        params["end"] = END_PERIOD

    rows: list[dict] = []
    offset = 0
    total: int | None = None
    page = 0

    while True:
        page += 1
        payload = request_page(session, {**params, "offset": offset})
        body = payload.get("response", {})

        if total is None:
            total = int(body.get("total", 0))
            if total == 0:
                print(f"  {ba}: API reports 0 matching rows — check facets/date range")
                return []
            n_pages = -(-total // PAGE_SIZE)  # ceiling division
            print(f"  {ba}: {total:,} rows to fetch across ~{n_pages} pages")

        batch = body.get("data", [])
        if not batch:
            break  # defensive: nothing left even though offset < total

        rows.extend(batch)
        offset += len(batch)
        print(f"    page {page}: +{len(batch):,} rows ({offset:,}/{total:,})")

        if offset >= total:
            break

        # Space out requests so a long pull never looks like a burst.
        time.sleep(POLITE_DELAY_SEC)

    return rows


# ---------------------------------------------------------------------------
# Tidy up into the analysis-ready frame
# ---------------------------------------------------------------------------

def to_dataframe(raw_rows: list[dict]) -> pd.DataFrame:
    """Normalise the API's JSON records into three clean columns."""
    df = pd.DataFrame(raw_rows)

    # 'period' arrives as "2019-01-01T05" (UTC, hour precision).
    df["timestamp_utc"] = pd.to_datetime(df["period"], format="%Y-%m-%dT%H", utc=True)
    df["balancing_authority"] = df["respondent"].astype("string")
    # Demand can come back as a string, or null for hours a BA failed to report.
    df["demand_mwh"] = pd.to_numeric(df["value"], errors="coerce")

    df = df[["timestamp_utc", "balancing_authority", "demand_mwh"]]

    # Safety net: if a page boundary ever did overlap, drop the repeats rather
    # than double-counting an hour in the growth-rate denominator.
    before = len(df)
    df = df.drop_duplicates(subset=["timestamp_utc", "balancing_authority"], keep="first")
    if len(df) < before:
        print(f"\n  note: dropped {before - len(df):,} duplicate (timestamp, BA) rows")

    return df.sort_values(["balancing_authority", "timestamp_utc"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------

def sanity_check(df: pd.DataFrame) -> None:
    """Print row counts, coverage, and anything that looks like a hole."""
    print("\n" + "=" * 72)
    print("SANITY CHECK")
    print("=" * 72)

    print(f"\nTotal rows: {len(df):,}")
    print(f"Overall range: {df['timestamp_utc'].min()}  ->  {df['timestamp_utc'].max()}")

    print("\nPer balancing authority")
    print("-" * 72)
    header = f"{'BA':<6} {'rows':>9} {'first hour':<17} {'last hour':<17} {'missing':>8} {'null':>6}"
    print(header)
    print("-" * 72)

    gap_detail: dict[str, pd.DatetimeIndex] = {}

    for ba, grp in df.groupby("balancing_authority", observed=True):
        first, last = grp["timestamp_utc"].min(), grp["timestamp_utc"].max()

        # A complete series has one row per hour between first and last. Compare
        # against that ideal index to find hours the BA never reported.
        expected = pd.date_range(first, last, freq="h", tz="UTC")
        missing = expected.difference(grp["timestamp_utc"])
        gap_detail[ba] = missing

        n_null = int(grp["demand_mwh"].isna().sum())

        print(
            f"{ba:<6} {len(grp):>9,} "
            f"{first.strftime('%Y-%m-%d %H:%M'):<17} "
            f"{last.strftime('%Y-%m-%d %H:%M'):<17} "
            f"{len(missing):>8,} {n_null:>6,}"
        )

    print("-" * 72)
    print("'missing' = hours with no row at all; 'null' = row present but no value.")

    # Report gaps as contiguous runs — far more diagnostic than a list of
    # timestamps. A single missing hour is usually a reporting hiccup; a
    # multi-day run means a genuine coverage problem worth documenting.
    print("\nGaps")
    print("-" * 72)
    any_gaps = False
    for ba, missing in gap_detail.items():
        if len(missing) == 0:
            print(f"{ba:<6} none — continuous hourly coverage")
            continue
        any_gaps = True
        runs = _contiguous_runs(missing)
        print(f"{ba:<6} {len(missing):,} missing hours in {len(runs)} run(s):")
        for start, end, length in runs[:10]:
            if length == 1:
                print(f"         {start:%Y-%m-%d %H:%M}  (1 hour)")
            else:
                print(f"         {start:%Y-%m-%d %H:%M} -> {end:%Y-%m-%d %H:%M}  ({length} hours)")
        if len(runs) > 10:
            print(f"         ... and {len(runs) - 10} more run(s)")

    if not any_gaps:
        print("\nNo gaps found in any BA.")

    _report_outliers(df)

    print("\nDemand summary (MWh)")
    print("-" * 72)
    print(
        df.groupby("balancing_authority", observed=True)["demand_mwh"]
        .agg(["min", "mean", "max"])
        .round(0)
        .to_string()
    )


def _report_outliers(df: pd.DataFrame) -> None:
    """
    Report physically implausible demand values in the raw EIA-930 series.

    The detection rule lives in eia930_quality.py so that this report and the
    exclusion applied by clean_eia930.py can never disagree.

    Nothing is dropped here by design: this script's output is the as-reported
    archive. The exclusion decision (drop these hours — see DECISIONS.md) is
    applied downstream in clean_eia930.py, which keeps raw immutable.
    """
    print("\nImplausible values")
    print("-" * 72)

    flagged = flag_implausible(df)
    all_bas = sorted(df["balancing_authority"].unique())

    for ba in all_bas:
        rows = flagged[flagged["balancing_authority"] == ba]
        if rows.empty:
            print(f"{ba:<6} none")
            continue
        print(f"{ba:<6} {len(rows)} implausible hour(s) "
              f"(>{PEAK_RATIO}x the 2-year peak level, or a level collapse):")
        for _, r in rows.head(10).iterrows():
            print(
                f"         {r.timestamp_utc:%Y-%m-%d %H:%M}  value={r.demand_mwh:>14,.0f}"
                f"  baseline={r.baseline:>9,.0f}  ratio={r.ratio:>9,.2f}x  [{r.test}]"
            )
        if len(rows) > 10:
            print(f"         ... and {len(rows) - 10} more")

    if not flagged.empty:
        print(
            f"\n=> {len(flagged)} suspect hour(s) of {len(df):,} "
            f"({len(flagged) / len(df) * 100:.4f}%). Retained here as-reported; "
            "run clean_eia930.py to write the excluded-hours series."
        )


def _contiguous_runs(idx: pd.DatetimeIndex) -> list[tuple]:
    """Collapse a sorted DatetimeIndex of missing hours into (start, end, n) runs."""
    if len(idx) == 0:
        return []
    runs = []
    start = prev = idx[0]
    for ts in idx[1:]:
        if (ts - prev) == pd.Timedelta(hours=1):
            prev = ts
            continue
        runs.append((start, prev, int((prev - start) / pd.Timedelta(hours=1)) + 1))
        start = prev = ts
    runs.append((start, prev, int((prev - start) / pd.Timedelta(hours=1)) + 1))
    return runs


# ---------------------------------------------------------------------------

def main() -> int:
    # load_dotenv reads .env into the environment. The key never appears in
    # source, so the script is safe to commit; .env is gitignored.
    load_dotenv()
    api_key = os.getenv("EIA_API_KEY")
    if not api_key:
        print("ERROR: EIA_API_KEY not found. Copy .env.example to .env and add your key.")
        return 1

    print("EIA-930 hourly demand pull")
    print(f"  endpoint: {BASE_URL}")
    print(f"  BAs:      {', '.join(BALANCING_AUTHORITIES)}")
    print(f"  from:     {START_PERIOD}  to: {END_PERIOD or 'latest available'}")
    print()

    started = time.time()
    all_rows: list[dict] = []

    with requests.Session() as session:
        for ba in BALANCING_AUTHORITIES:
            all_rows.extend(fetch_ba(session, api_key, ba))

    if not all_rows:
        print("\nNo data returned — nothing written.")
        return 1

    print(f"\nFetched {len(all_rows):,} raw rows in {time.time() - started:.0f}s")

    df = to_dataframe(all_rows)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    size_mb = OUT_PATH.stat().st_size / 1e6
    print(f"Wrote {len(df):,} rows to {OUT_PATH}  ({size_mb:.1f} MB)")

    sanity_check(df)
    return 0


if __name__ == "__main__":
    sys.exit(main())
