"""Stress tests (per-asset-class shocks) and Monte Carlo goal projection (lognormal)."""
import numpy as np

from app import realdata
from app.config import MC_PATHS, MC_SEED
from app.schemas import Allocation, ClientProfile, Product

# Percent price shock per asset class. "equity_-20" is a hypothetical round-number scenario; every other scenario is
# computed from what markets really did in the named years (app/data/real, mapped via realdata.ASSET_MIX).
EPISODES = {
    "crash_2008": {"label": "2008 financial crisis", "years": (2008, 2008)},
    "rate_+2": {"label": "Rate shock (2022)", "years": (2022, 2022), "rate": ("2021-12", "2022-12")},
    "inflation_spike": {"label": "Inflation spike (1974)", "years": (1974, 1974)},
    "dotcom_bust": {"label": "Dot-com bust (2000-2002)", "years": (2000, 2002)},
    "great_depression": {"label": "Great Depression (1929-1932)", "years": (1929, 1932)},
}
SHOCK_CLASSES = ["equity_fund", "balanced_fund", "structured_note", "gold", "bond", "cash"]


def _episode(spec: dict) -> dict:
    a, b = spec["years"]
    shocks = {c: round(realdata.cumulative_pct(c, a, b), 1) for c in SHOCK_CLASSES}
    span = str(a) if a == b else f"{a}-{b}"
    parts = [f"stocks {shocks['equity_fund']:+.1f}%", f"bonds {shocks['bond']:+.1f}%", f"gold {shocks['gold']:+.1f}%",
             f"cash {shocks['cash']:+.1f}%"]
    extra = ""
    infl = realdata.inflation_pct(b) if a == b else None
    if infl is not None:
        extra += f" US inflation that year was {infl:.1f}%."
    if spec.get("rate"):
        d = realdata.long_rate_change(*spec["rate"])
        if d is not None:
            extra += f" The 10-year rate rose {d:.1f} points."
    if infl is not None and shocks["cash"] < infl:
        extra += " Cash earned less than inflation, so it lost purchasing power."
    note = f"Real {span} market returns: {', '.join(parts)}.{extra}"
    return {"label": spec["label"], "shocks": shocks,
            "basis": {"type": "historical", "years": span, "note": note, "source": realdata.SOURCE}}


SCENARIOS = {
    "equity_-20": {
        "label": "Equities fall 20%",
        "shocks": {"equity_fund": -20, "balanced_fund": -10, "structured_note": -15, "gold": 2, "bond": 0, "cash": 0},
        "basis": {"type": "hypothetical", "years": None, "source": None,
                  "note": "Hypothetical round-number shock, not a historical episode."},
    },
    **{k: _episode(v) for k, v in EPISODES.items()},
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
    return {"scenario": scenario, "label": sc["label"], "loss_pct": round(total, 2), "by_line": by_line,
            "basis": sc["basis"]}


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


def _class_weights(allocation: Allocation, products: dict[str, Product]) -> tuple[dict, float]:
    w: dict[str, float] = {}
    fee = 0.0
    for l in allocation.lines:
        p = products[l.product_id]
        w[p.asset_class] = w.get(p.asset_class, 0.0) + l.weight
        fee += l.weight * p.annual_fee_pct / 100
    return w, fee


def historical_backtest(allocation: Allocation, products: dict[str, Product], profile: ClientProfile) -> dict:
    """What this allocation would have done over every real rolling window of the client's horizon (1928-2025),
    annually rebalanced, after the products' fees, plus a bootstrap that resamples real years. US data is a proxy."""
    weights, fee = _class_weights(allocation, products)
    amount = profile.investable_amount_cny
    target = profile.goal_target_cny or amount * 1.3
    years = max(1, int(round(profile.horizon_years)))
    ys = realdata.years()
    rets = {y: sum(wt * realdata.class_return(c, y) for c, wt in weights.items()) - fee for y in ys}
    finals = []
    for i in range(len(ys) - years + 1):
        v = amount
        for y in ys[i:i + years]:
            v *= 1 + rets[y]
        finals.append((ys[i], v))
    vals = np.array([v for _, v in finals])
    worst = min(finals, key=lambda t: t[1])
    rng = np.random.default_rng(MC_SEED)
    draw = np.array([rets[y] for y in ys])
    boot = amount * np.prod(1 + rng.choice(draw, size=(MC_PATHS, years)), axis=1)
    return {
        "source": realdata.SOURCE, "years": years, "windows": len(finals), "first_year": ys[0], "last_year": ys[-1],
        "target_cny": round(float(target), 2), "start_cny": round(float(amount), 2),
        "windows_reaching_target": int((vals >= target).sum()),
        "share_reaching_target": round(float((vals >= target).mean()), 4),
        "worst_cny": round(float(worst[1]), 2), "worst_start_year": worst[0],
        "median_cny": round(float(np.median(vals)), 2), "best_cny": round(float(vals.max()), 2),
        "bootstrap_probability": round(float((boot >= target).mean()), 4),
        "note": ("Past performance is not a reliable indicator of future results. Rolling windows overlap and use US "
                 "market history as a proxy for these synthetic products."),
    }
