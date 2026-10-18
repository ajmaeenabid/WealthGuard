"""Loaders for the real public datasets in app/data/real (see MANIFEST.json for source and license).

Our products are synthetic; their asset classes are mapped onto real historical series so stress scenarios and
backtests use what markets actually did. Mapping assumptions are explicit and documented in docs/algorithm.md.
"""
import csv
import os
from functools import lru_cache

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "real")

# asset class -> blend of real series (weights sum to 1). Assumptions, not facts about any product:
#  bond = intermediate-duration proxy; balanced = 60/40; structured note = equity-linked with a cash cushion.
ASSET_MIX = {
    "cash": {"tbill_3m": 1.0},
    "bond": {"tbond_10y": 0.6, "tbill_3m": 0.4},
    "balanced_fund": {"sp500": 0.6, "tbond_10y": 0.4},
    "equity_fund": {"sp500": 1.0},
    "structured_note": {"sp500": 0.7, "tbill_3m": 0.3},
    "gold": {"gold": 1.0},
}
SOURCE = "Damodaran (NYU Stern) annual US returns 1928-2025; US data is a proxy for these synthetic CNY products"


@lru_cache(maxsize=1)
def annual_returns() -> dict:
    with open(os.path.join(DIR, "returns_annual.csv"), encoding="utf-8") as f:
        return {int(r["year"]): {k: float(v) for k, v in r.items() if k != "year"} for r in csv.DictReader(f)}


@lru_cache(maxsize=1)
def _shiller() -> dict:
    with open(os.path.join(DIR, "shiller_monthly.csv"), encoding="utf-8") as f:
        return {r["month"]: r for r in csv.DictReader(f)}


def years() -> list[int]:
    return sorted(annual_returns())


def class_return(asset_class: str, year: int) -> float:
    """Real annual return of an asset class (fraction) from its mapped blend."""
    r = annual_returns()[year]
    return sum(w * r[col] for col, w in ASSET_MIX[asset_class].items())


def cumulative_pct(asset_class: str, start: int, end: int) -> float:
    g = 1.0
    for y in range(start, end + 1):
        g *= 1 + class_return(asset_class, y)
    return (g - 1) * 100


def inflation_pct(year: int):
    """December-to-December CPI change from Shiller's series, or None if the months are missing."""
    s = _shiller()
    a, b = s.get(f"{year - 1}-12"), s.get(f"{year}-12")
    if not a or not b:
        return None
    return (float(b["cpi"]) / float(a["cpi"]) - 1) * 100


def long_rate_change(start_month: str, end_month: str):
    s = _shiller()
    if start_month not in s or end_month not in s:
        return None
    return float(s[end_month]["long_rate"]) - float(s[start_month]["long_rate"])
