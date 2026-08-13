"""
Phase 3 diagnostic regressions. Variance accounting, not interpretation.

Reads   data/processed/analysis_panel.csv
Writes  data/processed/diagnostic_model_results.csv

Fits, on the 22-point set with ERCOT 2022 (the high-leverage point) excluded:

    M1  clearance ~ growth + growth^2                    pooled, no region term
    M2  clearance ~ growth + growth^2 + region           region fixed effects
    M0  clearance ~ region                               region alone, no growth terms

The question these answer is narrow: does the growth^2 coefficient survive the
addition of region, or was it absorbing cross-regional level differences? M0 exists
to separate "R^2 that region alone buys" from "R^2 that growth adds on top of it".

Growth enters in PERCENTAGE POINTS (+3.72, not 0.0372), so growth^2 is in points^2
and the coefficients are readable at the scale of the data. Clearance is a
percentage of active backlog (clearance_rate_pct), as constructed in
build_analysis_panel.py.

These are diagnostics on 22 observations. They are not the study's estimates, and
the identification problems documented in DECISIONS.md are not fixed by running them.

    python fit_diagnostic_models.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

PANEL_PATH = Path("data/processed/analysis_panel.csv")
OUT_PATH = Path("data/processed/diagnostic_model_results.csv")

LEVERAGE_POINT = ("ERCOT", 2022)
BASELINE_REGION = "PJM"  # reference level for the region dummies
REGIONS = ["PJM", "ERCOT", "MISO", "SPP"]


def load(drop_leverage: bool = True) -> pd.DataFrame:
    df = pd.read_csv(PANEL_PATH)
    if drop_leverage:
        region, year = LEVERAGE_POINT
        df = df[~((df.region == region) & (df.year == year))].copy()
    else:
        df = df.copy()

    df["growth"] = df.demand_growth_yoy * 100  # percentage points
    df["growth2"] = df.growth ** 2
    df["clearance"] = df.clearance_rate_pct
    # Reference level first so the intercept is PJM, the region that is flat over
    # the window -- it makes the dummies read as offsets from a stable baseline.
    df["region"] = pd.Categorical(
        df.region, categories=[BASELINE_REGION] + [r for r in REGIONS if r != BASELINE_REGION]
    )
    return df


def report(name: str, formula: str, fit) -> list[dict]:
    print(f"\n{name}:  {formula}")
    print("-" * 78)
    print(f"  n = {int(fit.nobs)},  df resid = {int(fit.df_resid)},  "
          f"R2 = {fit.rsquared:.4f},  adj R2 = {fit.rsquared_adj:.4f}")
    print(f"  {'term':<22}{'coef':>12}{'std err':>11}{'t':>9}{'p':>10}"
          f"{'[0.025':>11}{'0.975]':>11}")
    ci = fit.conf_int()
    rows = []
    for term in fit.params.index:
        print(f"  {term:<22}{fit.params[term]:>12.4f}{fit.bse[term]:>11.4f}"
              f"{fit.tvalues[term]:>9.2f}{fit.pvalues[term]:>10.4f}"
              f"{ci.loc[term, 0]:>11.4f}{ci.loc[term, 1]:>11.4f}")
        rows.append({
            "model": name, "term": term, "coef": fit.params[term],
            "std_err": fit.bse[term], "t": fit.tvalues[term], "p": fit.pvalues[term],
            "ci_low": ci.loc[term, 0], "ci_high": ci.loc[term, 1],
            "n": int(fit.nobs), "r2": fit.rsquared, "adj_r2": fit.rsquared_adj,
        })
    print("-" * 78)
    return rows


def main() -> int:
    if not PANEL_PATH.exists():
        print(f"ERROR: {PANEL_PATH} not found. Run build_analysis_panel.py first.")
        return 1

    df = load()
    region, year = LEVERAGE_POINT
    print(f"Excluded the leverage point {region} {year}. n = {len(df)}.")
    print("Growth in percentage points; clearance as a % of active backlog.")

    # Raw growth and its square are strongly collinear over an asymmetric range,
    # which inflates both standard errors. Reported so a large SE on growth^2 is
    # not misread as evidence about the curvature itself.
    r = np.corrcoef(df.growth, df.growth2)[0, 1]
    print(f"\ncorr(growth, growth^2) = {r:+.3f}  "
          f"(range {df.growth.min():+.2f} to {df.growth.max():+.2f} pp)")

    f1 = "clearance ~ growth + growth2"
    f2 = "clearance ~ growth + growth2 + C(region)"
    f0 = "clearance ~ C(region)"

    m1 = smf.ols(f1, data=df).fit()
    m2 = smf.ols(f2, data=df).fit()
    m0 = smf.ols(f0, data=df).fit()

    rows = []
    rows += report("M1  pooled", f1, m1)
    rows += report("M2  + region", f2, m2)
    rows += report("M0  region only", f0, m0)

    # ---------------------------------------------------------- what happened to growth^2
    print("\nGROWTH^2 ACROSS THE TWO MODELS")
    print("=" * 78)
    c1, s1, p1 = m1.params["growth2"], m1.bse["growth2"], m1.pvalues["growth2"]
    c2, s2, p2 = m2.params["growth2"], m2.bse["growth2"], m2.pvalues["growth2"]
    print(f"  {'':<14}{'coef':>12}{'std err':>11}{'t':>9}{'p':>10}")
    print(f"  {'M1 pooled':<14}{c1:>12.4f}{s1:>11.4f}{c1 / s1:>9.2f}{p1:>10.4f}")
    print(f"  {'M2 + region':<14}{c2:>12.4f}{s2:>11.4f}{c2 / s2:>9.2f}{p2:>10.4f}")
    shrink = (1 - abs(c2) / abs(c1)) * 100 if c1 else float("nan")
    print(f"\n  |coef| shrinks {shrink:.0f}% ({abs(c1):.4f} -> {abs(c2):.4f}) "
          "-- it is NOT absorbed by region")
    print(f"  significant at 0.05?   M1: {'yes' if p1 < 0.05 else 'NO'} (p={p1:.3f})"
          f"    M2: {'yes' if p2 < 0.05 else 'NO'} (p={p2:.3f})")

    # Where the fitted parabola turns. A vertex sitting inside the data range means
    # the curvature is being identified by high points at BOTH ends of the growth
    # axis, which is worth naming before anyone reads it as a demand-response shape.
    for label, m in [("M1", m1), ("M2", m2)]:
        b, a = m.params["growth"], m.params["growth2"]
        print(f"  {label} vertex at growth = {-b / (2 * a):+.2f} pp "
              f"({'minimum' if a > 0 else 'maximum'}), inside the observed range")
    print("=" * 78)

    # ------------------------------------------------------------- variance accounting
    print("\nR^2 ACCOUNTING")
    print("=" * 78)
    print(f"  {'model':<34}{'R2':>9}{'adj R2':>10}{'params':>9}")
    for label, m in [("M1  growth + growth^2 only", m1),
                     ("M0  region only", m0),
                     ("M2  region + growth + growth^2", m2)]:
        print(f"  {label:<34}{m.rsquared:>9.4f}{m.rsquared_adj:>10.4f}{len(m.params):>9}")
    print("-" * 78)
    print(f"  region alone buys                 {m0.rsquared:>9.4f}")
    print(f"  growth terms add on top of region {m2.rsquared - m0.rsquared:>9.4f}")
    print(f"  growth terms alone buy            {m1.rsquared:>9.4f}")
    print(f"  region adds on top of growth      {m2.rsquared - m1.rsquared:>9.4f}")
    print("-" * 78)

    # Nested F-tests: does each block earn its degrees of freedom?
    f_growth = m2.compare_f_test(m0)
    f_region = m2.compare_f_test(m1)
    print(f"  F-test, growth terms given region:  F = {f_growth[0]:.3f}, "
          f"p = {f_growth[1]:.4f}, df = {int(f_growth[2])}")
    print(f"  F-test, region given growth terms:  F = {f_region[0]:.3f}, "
          f"p = {f_region[1]:.4f}, df = {int(f_region[2])}")
    print("=" * 78)

    # ------------------------------------------------------------------- influence
    # 22 observations and 6 parameters: a single region-year can carry the
    # curvature. Cook's D flags which, using the conventional 4/n screen.
    infl = m2.get_influence()
    cooks = infl.cooks_distance[0]
    thresh = 4 / len(df)
    d = df.assign(cooks_d=cooks).sort_values("cooks_d", ascending=False)
    print(f"\nINFLUENCE ON M2  (Cook's D, screen at 4/n = {thresh:.3f})")
    print("=" * 78)
    print(f"  {'region':<8}{'year':>6}{'growth':>9}{'clearance':>11}{'Cook D':>9}")
    for _, r in d.head(5).iterrows():
        flag = "  <-- above screen" if r.cooks_d > thresh else ""
        print(f"  {r.region:<8}{int(r.year):>6}{r.growth:>9.2f}{r.clearance:>11.1f}"
              f"{r.cooks_d:>9.3f}{flag}")
    print(f"  ({int((cooks > thresh).sum())} of {len(df)} observations above the screen)")

    # Refit without whatever is above the screen: if growth^2 depends on a couple
    # of points, that is the finding, not the coefficient.
    keep = df[cooks <= thresh]
    m2b = smf.ols(f2, data=keep).fit()
    print(f"\n  M2 refit without them (n = {int(m2b.nobs)}):")
    print(f"    growth^2 coef {m2.params['growth2']:.4f} -> {m2b.params['growth2']:.4f}"
          f"   p {m2.pvalues['growth2']:.4f} -> {m2b.pvalues['growth2']:.4f}")
    print(f"    R2 {m2.rsquared:.4f} -> {m2b.rsquared:.4f}")
    print("=" * 78)

    rows += linear_only()

    summary = pd.DataFrame(rows)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUT_PATH, index=False)
    print(f"\nWrote {OUT_PATH}")
    return 0


def linear_only() -> list[dict]:
    """clearance ~ growth + region, with and without the leverage point.

    Dropping growth^2 is not a neutral simplification here: the quadratic's vertex
    sat inside the data, so the linear term in the quadratic model was the slope of
    a parabola at zero, not an average slope. These two fits give the average slope,
    and the n=23 pair shows how much of it one region-year is carrying.
    """
    region, year = LEVERAGE_POINT
    formula = "clearance ~ growth + C(region)"
    region_only = "clearance ~ C(region)"

    print("\n\nLINEAR-ONLY SPECIFICATION:  clearance ~ growth + region")
    print("=" * 78)

    rows, fits = [], {}
    for label, drop in [(f"L22 excl {region} {year}", True), ("L23 full set", False)]:
        d = load(drop_leverage=drop)
        fit = smf.ols(formula, data=d).fit()
        base = smf.ols(region_only, data=d).fit()
        f_stat, f_p, f_df = fit.compare_f_test(base)
        fits[label] = (fit, base, f_stat, f_p, f_df, d)
        rows += report(label, formula, fit)
        print(f"  region-only R2 = {base.rsquared:.4f}   "
              f"growth adds {fit.rsquared - base.rsquared:+.4f}")
        print(f"  F-test, growth given region: F = {f_stat:.3f}, p = {f_p:.4f}, "
              f"df = ({int(f_df)}, {int(fit.df_resid)})")
        print(f"  {'growth EARNS its place' if f_p < 0.05 else 'growth does NOT earn its place'}"
              " at the 0.05 level")

    # ------------------------------------------------- what the extra point does
    print("\nEFFECT OF THE LEVERAGE POINT ON THE LINEAR SLOPE")
    print("=" * 78)
    a_label, b_label = list(fits)
    (fa, ba, Fa, pa, _, _) = fits[a_label][:6]
    (fb, bb, Fb, pb, _, _) = fits[b_label][:6]
    print(f"  {'':<26}{'n':>4}{'growth coef':>13}{'std err':>10}{'p':>9}{'R2':>9}{'adj R2':>9}")
    for lbl, f in [(a_label, fa), (b_label, fb)]:
        print(f"  {lbl:<26}{int(f.nobs):>4}{f.params['growth']:>13.4f}"
              f"{f.bse['growth']:>10.4f}{f.pvalues['growth']:>9.4f}"
              f"{f.rsquared:>9.4f}{f.rsquared_adj:>9.4f}")

    ca, cb = fa.params["growth"], fb.params["growth"]
    print(f"\n  slope moves {ca:+.4f} -> {cb:+.4f}  "
          f"({(cb - ca) / abs(ca) * 100:+.0f}%), sign "
          f"{'FLIPS' if ca * cb < 0 else 'holds'}")
    print(f"  both slopes sit inside the other fit's 95% CI: "
          f"{'yes' if (fa.conf_int().loc['growth', 0] <= cb <= fa.conf_int().loc['growth', 1]) else 'no'}")
    print("=" * 78)
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
