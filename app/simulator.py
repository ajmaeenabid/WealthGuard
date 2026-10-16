"""Stress tests (per-asset-class shocks) and Monte Carlo goal projection (lognormal)."""
import numpy as np

from app.config import MC_PATHS, MC_SEED
from app.schemas import Allocation, ClientProfile, Product

# percent price shock per asset class
SCENARIOS = {
    "equity_-20": {
        "label": "Equities fall 20%",
        "shocks": {"equity_fund": -20, "balanced_fund": -10, "structured_note": -15, "gold": 2, "bond": 0, "cash": 0},
    },
    "rate_+2": {
        "label": "Interest rates rise 2 points",
        "shocks": {"bond": -6, "balanced_fund": -3, "equity_fund": -4, "gold": -3, "structured_note": -4, "cash": 0},
    },
    "crash_2008": {
        "label": "2008-style crash",
        "shocks": {"equity_fund": -45, "balanced_fund": -25, "structured_note": -35, "gold": 5, "bond": 3,
                   "cash": 0},
    },
    "inflation_spike": {
        "label": "Inflation spike",
        "shocks": {"bond": -5, "equity_fund": -8, "balanced_fund": -6, "gold": 10, "structured_note": -5,
                   "cash": -2},
    },
}


def stress(allocation: Allocation, products: dict[str, Product], scenario: str) -> dict:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario '{scenario}'; choose from {sorted(SCENARIOS)}")
    sc = SCENARIOS[scenario]
    by_line = []
    total = 0.0
    for l in allocation.lines:
        p = products[l.product_id]
        shock = sc["shocks"].get(p.asset_class, 0)
        contrib = l.weight * shock
        total += contrib
        by_line.append({"product_id": p.id, "name": p.name, "weight": l.weight, "shock_pct": shock,
                        "contribution_pct": round(contrib, 3)})
    return {"scenario": scenario, "label": sc["label"], "loss_pct": round(total, 2), "by_line": by_line}


def goal_projection(allocation: Allocation, profile: ClientProfile, shock_pct: float = 0.0) -> dict:
    """P(final value >= target) after horizon; optional immediate shock applied to the starting value."""
    amount = profile.investable_amount_cny * (1 + shock_pct / 100)
    target = profile.goal_target_cny or profile.investable_amount_cny * 1.3
    years = max(1, int(round(profile.horizon_years)))
    mu, sigma = allocation.expected_return, allocation.volatility
    rng = np.random.default_rng(MC_SEED)
    # lognormal annual growth factors with mean (1+mu) and std sigma*(1+mu)
    s2 = np.log(1 + (sigma / (1 + mu)) ** 2)
    m = np.log(1 + mu) - s2 / 2
    growth = rng.lognormal(m, np.sqrt(s2), size=(MC_PATHS, years))
    final = amount * growth.prod(axis=1)
    return {
        "paths": MC_PATHS, "years": years, "target_cny": round(float(target), 2),
        "start_cny": round(float(amount), 2),
        "probability": round(float((final >= target).mean()), 4),
        "median_cny": round(float(np.median(final)), 2),
        "p10_cny": round(float(np.percentile(final, 10)), 2),
        "p90_cny": round(float(np.percentile(final, 90)), 2),
    }
