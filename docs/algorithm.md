# Algorithms

> Educational demo with synthetic products. Not real financial advice.

## Profiling (`profiling.py`)

Each answer maps to a 0-100 score. **Tolerance** = goal (0.2), loss reaction (0.5), experience (0.3).
**Capacity** = age (0.2), horizon (0.3), income (0.1), income stability (0.2), liquidity need (0.2).
Score to bucket: <20 Conservative, <40 Moderate, <60 Balanced, <80 Growth, else Aggressive.
**Final bucket = the lower of tolerance bucket and capacity bucket.**

Adaptive: questions already answered (e.g. persona facts) are skipped, and some are inferred: horizon < 2 years implies a
40% liquidity need; goal "preservation" implies a low loss reaction.

## Allocation (`allocation.py`)

1. Effective bucket = final bucket capped to Moderate for vulnerable clients (age >= 65 or horizon < 2 years, R5).
2. Start from the bucket's asset-class template weights.
3. Remove products failing risk (R1), complexity (R3), lock-up beyond horizon (R4); drop products whose minimum is not
   met by their weight (R8) and re-spread.
4. Within a class, tilt toward `(expected_return - fee) / (1 + risk_level)`: lower fee and better return per risk win.
5. Cap each product at the single-product limit (R2), bringing in extra eligible products if necessary; cap equity-like
   assets (equity funds, balanced funds, structured notes); enforce the liquidity floor; renormalise; round to 4 d.p.
6. Attach a one-sentence rationale per line citing the client's facts, plus fee-summary and risk disclosures.

Deterministic: same profile and products give identical weights.
Portfolio return = sum of weight x (return - fee); volatility uses a flat 0.5 correlation between distinct products.

## Compliance (`compliance.py`)

R1 suitability (risk and equity-like limit), R2 concentration (and weights sum to 1), R3 complexity, R4 liquidity,
R5 vulnerable client (must stay within Moderate limits), R6 disclosures (risk warning, fee summary, past-performance),
R7 language (guaranteed / risk-free / can't-lose, negated phrases like "not guaranteed" allowed), R8 minimums.
The LLM reviewer can only add a failing check.

## "Why not product X" (`comparison.py`)

If a rule blocks it: the specific rule(s), the client's fact, and the product's headline numbers. Otherwise: a better
risk/fee alternative in the same class already held, or no added diversification.

## Stress tests and goal probability (`simulator.py`)

Per-asset-class percentage shocks for equity -20%, rates +2, 2008-style crash, inflation spike. Portfolio change =
sum of weight x shock. Goal probability: 5,000 lognormal paths (fixed seed) with annual mean/vol of the allocation over
the horizon; probability that final value >= target, reported with and without the immediate shock.

### Real-data calibration (`realdata.py`, `simulator.py`)

Products stay synthetic. Their asset classes are mapped onto real annual US returns 1928-2025 (Damodaran, see
`app/data/real/MANIFEST.json`):

| Asset class | Real series blend (assumption) |
|---|---|
| cash | 3-month T-bill |
| bond | 60% 10-year T-bond + 40% T-bill (intermediate-duration proxy) |
| balanced_fund | 60% S&P 500 + 40% 10-year T-bond |
| equity_fund | S&P 500 with dividends |
| structured_note | 70% S&P 500 + 30% T-bill |
| gold | gold |

**Stress scenarios.** `equity_-20` is a hypothetical round number and is labelled so. The others are the compounded
real returns of named years: `crash_2008` (2008), `rate_+2` (2022, the 10-year rate rose about 2.2 points, from Shiller),
`inflation_spike` (1974, CPI +12.3% Dec-Dec, from Shiller), `dotcom_bust` (2000-2002), `great_depression` (1929-1932).
Each result carries a `basis` sentence with the real numbers. Because the blends are real, a bond-heavy portfolio can
*gain* in 2008 or 2000-02 (bonds rallied) and lose in 2022; that is the point of using history.

**Historical backtest** (`historical_backtest`). For every rolling window of the client's horizon in 1928-2025 the
allocation is annually rebalanced, after the weighted product fees, and the final value is compared with the goal:
windows reaching the goal, worst/median/best final value, and the worst start year. A bootstrap resamples real years
5,000 times (seeded) for a second probability. It is shown next to the lognormal Monte Carlo, which uses the products'
own (more conservative) return assumptions, so the two can differ widely. Windows overlap and US history is a proxy.
