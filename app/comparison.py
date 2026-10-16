"""Product comparison and specific "why not product X" explanations."""
from typing import Optional

from app.allocation import _score, limits_for
from app.config import BUCKETS
from app.schemas import Allocation, ClientProfile, Product


def row(p: Product) -> dict:
    return {
        "id": p.id, "name": p.name, "asset_class": p.asset_class, "risk_level": p.risk_level,
        "expected_return_pct": round(p.expected_return * 100, 2), "volatility_pct": round(p.volatility * 100, 2),
        "annual_fee_pct": p.annual_fee_pct, "min_invest_cny": p.min_invest_cny, "lockup_days": p.lockup_days,
        "complex": p.complex, "return_per_risk": round((p.expected_return - p.annual_fee_pct / 100) / p.volatility, 2)
        if p.volatility > 0.005 else None,
    }


def blocking_reasons(p: Product, profile: ClientProfile) -> list[str]:
    bucket, lim = limits_for(profile)
    reasons = []
    if p.risk_level > lim["max_risk"]:
        extra = ""
        if bucket != profile.bucket:
            extra = f" (your {profile.bucket} score is capped at {bucket} by the vulnerable-client rule R5)"
        reasons.append(f"its risk level {p.risk_level} is above the maximum {lim['max_risk']} for your "
                       f"{bucket} bucket{extra} (R1)")
    if p.complex and profile.experience != "advanced":
        reasons.append(f"it is a complex product and your experience is '{profile.experience}', not 'advanced' (R3)")
    if p.lockup_days > profile.horizon_years * 365:
        reasons.append(f"it locks money up for {p.lockup_days} days, longer than your "
                       f"{profile.horizon_years:g}-year horizon (R4)")
    if p.min_invest_cny > profile.investable_amount_cny:
        reasons.append(f"its minimum of CNY {p.min_invest_cny:,.0f} exceeds your investable amount (R8)")
    return reasons


def why_not(p: Product, profile: ClientProfile, products: dict[str, Product],
            allocation: Optional[Allocation] = None) -> str:
    reasons = blocking_reasons(p, profile)
    head = f"{p.name} is not recommended"
    if reasons:
        tail = ""
        if p.expected_return >= 0.10:
            tail = (f" Its {p.expected_return:.0%} headline return comes with {p.volatility:.0%} volatility and a "
                    f"{p.annual_fee_pct:g}% fee.")
        return f"{head}: " + "; and ".join(reasons) + "." + tail
    held = {l.product_id for l in allocation.lines} if allocation else set()
    if p.id in held:
        return f"{p.name} is already part of your allocation."
    peers = [q for q in products.values() if q.asset_class == p.asset_class and q.id in held and q.id != p.id]
    better = [q for q in peers if _score(q) > _score(p)]
    if better:
        b = max(better, key=_score)
        return (f"{head}: it is allowed for you, but {b.name} has a better risk/fee profile in the same class "
                f"(net return per unit of risk {_score(b):.3f} vs {_score(p):.3f}; fee {b.annual_fee_pct:g}% vs "
                f"{p.annual_fee_pct:g}%).")
    return (f"{head}: it is allowed for you but adds no diversification beyond the products already chosen, and "
            f"the {p.asset_class.replace('_', ' ')} share is already at its target weight.")


def compare(product_ids: list[str], products: dict[str, Product], profile: Optional[ClientProfile] = None,
            allocation: Optional[Allocation] = None) -> dict:
    ps = [products[i] for i in product_ids if i in products]
    out = {"rows": [row(p) for p in ps], "unknown_ids": [i for i in product_ids if i not in products]}
    if profile:
        bucket, lim = limits_for(profile)
        out["bucket"] = bucket
        out["suitability"] = {p.id: ("blocked" if blocking_reasons(p, profile) else "allowed") for p in ps}
        out["why_not"] = {p.id: why_not(p, profile, products, allocation)
                          for p in ps if blocking_reasons(p, profile) or not allocation
                          or p.id not in {l.product_id for l in allocation.lines}}
    if ps:
        best = max(ps, key=_score)
        out["note"] = f"Best net return per unit of risk among these: {best.name}."
    return out
