"""Constrained, deterministic allocation with a per-line rationale.

Steps: template weights per asset class -> drop products failing R1/R3/R4/R8 -> tilt by net return per risk
(lower fee wins) -> cap singles (R2) and equity-like total -> liquidity floor -> renormalise.
`preferred_ids` simulates an over-eager draft (e.g. from the LLM): those products are injected even if
ineligible. The compliance engine, not this module, is what blocks them.
"""
import math
from typing import Iterable, Optional

from app import config, store
from app.config import BUCKETS, EQUITY_LIKE, TEMPLATES, effective_bucket
from app.schemas import Allocation, AllocationLine, ClientProfile, Product

PREFERRED_WEIGHT = 0.15
RHO = 0.5  # flat correlation between distinct products


def limits_for(profile: ClientProfile) -> tuple[str, dict]:
    b = effective_bucket(profile.bucket, profile.age, profile.horizon_years)
    return b, BUCKETS[b]


def eligible(p: Product, profile: ClientProfile, bucket: str) -> bool:
    lim = BUCKETS[bucket]
    if p.risk_level > lim["max_risk"]:
        return False
    if p.complex and profile.experience != "advanced":
        return False
    if p.lockup_days > profile.horizon_years * 365:
        return False
    return True


def _score(p: Product) -> float:
    net = p.expected_return - p.annual_fee_pct / 100
    return max(net, 0.001) / (1 + p.risk_level)


def portfolio_stats(weights: dict[str, float], products: dict[str, Product]) -> tuple[float, float]:
    ids = list(weights)
    ret = sum(weights[i] * (products[i].expected_return - products[i].annual_fee_pct / 100) for i in ids)
    var = 0.0
    for i in ids:
        for j in ids:
            rho = 1.0 if i == j else RHO
            var += weights[i] * weights[j] * rho * products[i].volatility * products[j].volatility
    return round(ret, 4), round(math.sqrt(var), 4)


def _normalise(w: dict[str, float]) -> dict[str, float]:
    s = sum(w.values())
    return {k: v / s for k, v in w.items()} if s > 0 else w


def _base_weights(profile: ClientProfile, products: dict[str, Product], bucket: str,
                  exclude: set[str]) -> dict[str, float]:
    template = TEMPLATES[bucket]
    pool = [p for p in products.values() if p.id not in exclude and eligible(p, profile, bucket)]
    amount = profile.investable_amount_cny
    for _ in range(10):  # drop products that cannot meet their minimum (R8), then re-spread
        by_class: dict[str, list[Product]] = {}
        for p in pool:
            by_class.setdefault(p.asset_class, []).append(p)
        class_w = _normalise({c: w for c, w in template.items() if c in by_class}) if by_class else {}
        weights: dict[str, float] = {}
        for c, cw in class_w.items():
            scores = {p.id: _score(p) for p in by_class[c]}
            tot = sum(scores.values())
            for pid, s in scores.items():
                weights[pid] = cw * s / tot
        bad = [pid for pid, w in weights.items() if w * amount < products[pid].min_invest_cny]
        if not bad:
            return weights
        pool = [p for p in pool if p.id not in bad]
    return weights


def _cap_singles(w: dict[str, float], cap: float, products: dict[str, Product], pool_ids: list[str]) -> dict:
    w = dict(w)
    for _ in range(20):
        excess = sum(max(0.0, v - cap) for v in w.values())
        if excess < 1e-9:
            break
        w = {k: min(v, cap) for k, v in w.items()}
        free = {k: v for k, v in w.items() if v < cap - 1e-9}
        if not free:  # bring in additional eligible products, safest first
            extras = [i for i in pool_ids if i not in w]
            if not extras:
                break
            nxt = sorted(extras, key=lambda i: (products[i].risk_level, i))[0]
            w[nxt] = 0.0
            free = {nxt: 0.0}
        tot = sum(free.values())
        for k in free:
            share = (free[k] / tot) if tot > 0 else 1 / len(free)
            w[k] += excess * share
    return w


def _cap_equity(w: dict[str, float], max_eq: float, products: dict[str, Product]) -> dict:
    eq = sum(v for k, v in w.items() if products[k].asset_class in EQUITY_LIKE)
    if eq <= max_eq + 1e-9:
        return w
    scale = max_eq / eq
    safe = [k for k in w if products[k].asset_class not in EQUITY_LIKE]
    moved = eq - max_eq
    w = {k: (v * scale if products[k].asset_class in EQUITY_LIKE else v) for k, v in w.items()}
    if safe:
        tot = sum(w[k] for k in safe)
        for k in safe:
            w[k] += moved * (w[k] / tot if tot else 1 / len(safe))
    return w


def _liquidity_floor(w: dict[str, float], need: float, products: dict[str, Product]) -> dict:
    liquid = [k for k in w if products[k].lockup_days == 0]
    locked = [k for k in w if products[k].lockup_days > 0]
    cur = sum(w[k] for k in liquid)
    if cur >= need - 1e-9 or not locked or not liquid:
        return w
    short = need - cur
    lock_tot = sum(w[k] for k in locked)
    take = min(short, lock_tot)
    for k in locked:
        w[k] -= take * w[k] / lock_tot
    tot = sum(w[k] for k in liquid)
    for k in liquid:
        w[k] += take * w[k] / tot
    return w


def _round_weights(w: dict[str, float]) -> dict[str, float]:
    w = {k: round(v, 4) for k, v in w.items() if v > 5e-5}
    diff = round(1.0 - sum(w.values()), 4)
    if diff:
        top = sorted(w, key=lambda k: (-w[k], k))[0]
        w[top] = round(w[top] + diff, 4)
    return w


def rationale(p: Product, weight: float, profile: ClientProfile, bucket: str, capped: bool,
              injected: bool = False) -> str:
    facts = f"{profile.horizon_years:g}-year horizon, goal '{profile.goal}'"
    fee = ("a low" if p.annual_fee_pct <= 0.35 else "a moderate" if p.annual_fee_pct <= 0.9 else "a higher")
    base = {
        "cash": f"Covers your {profile.liquidity_need_pct:g}% short-notice liquidity need with no lock-up",
        "bond": f"Core stability for your {facts}",
        "gold": "Diversifier that tends to hold value when equities fall",
        "balanced_fund": f"Moderate growth with built-in bond cushion, suited to your {facts}",
        "equity_fund": f"Long-term growth for your {facts}, sized within your {bucket} equity limit",
        "structured_note": "Return enhancer; complex, so only suitable for advanced investors",
    }[p.asset_class]
    s = (f"{base}. Risk level {p.risk_level} fits your {bucket} bucket; fee {p.annual_fee_pct:g}% is {fee} fee "
         f"for its class; weight {weight:.0%}")
    if capped:
        s += " (held at the single-product cap)"
    if injected:
        s += ". Included at the request of the draft"
    return s + "."


def disclosures(lines: Iterable[AllocationLine], products: dict[str, Product]) -> list[str]:
    ls = list(lines)
    fee = sum(l.weight * products[l.product_id].annual_fee_pct for l in ls)
    return [
        config.RISK_WARNING,
        f"Estimated blended annual fees: {fee:.2f}% of invested assets (product annual fees; no other charges "
        f"are modelled in this synthetic demo).",
        config.PERF_DISCLAIMER,
    ]


def make_client_text(summary: str, lines: list[AllocationLine], products: dict[str, Product]) -> str:
    parts = [summary.strip()] if summary.strip() else []
    parts += [f"- {products[l.product_id].name}: {l.weight:.0%}. {l.rationale}" for l in lines]
    parts += disclosures(lines, products)
    parts.append(config.DISCLAIMER)
    return "\n".join(parts)


def build(profile: ClientProfile, products: dict[str, Product], preferred_ids: Iterable[str] = (),
          exclude_ids: Iterable[str] = (), summary: str = "", allocation_id: Optional[str] = None) -> Allocation:
    exclude = set(exclude_ids)
    bucket, lim = limits_for(profile)
    cap = lim["max_single_pct"] / 100
    base = _base_weights(profile, products, bucket, exclude)
    pool_ids = sorted(p.id for p in products.values() if p.id not in exclude and eligible(p, profile, bucket))
    w = _normalise(base) if base else {}
    for _ in range(5):
        w = _cap_singles(w, cap, products, pool_ids)
        w = _cap_equity(w, lim["max_equity_pct"] / 100, products)
        w = _liquidity_floor(w, profile.liquidity_need_pct / 100, products)
    w = _round_weights(_normalise(w)) if w else {}
    pref = [i for i in dict.fromkeys(preferred_ids) if i in products and i not in exclude]
    injected = set()
    if pref:
        scale = 1 - PREFERRED_WEIGHT * len(pref)
        w = {k: v * scale for k, v in w.items() if k not in pref}
        for i in pref:
            w[i] = PREFERRED_WEIGHT
            injected.add(i)
        w = _round_weights(w)
    lines = [
        AllocationLine(product_id=k, weight=v,
                       rationale=rationale(products[k], v, profile, bucket, v >= cap - 1e-4, k in injected))
        for k, v in sorted(w.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    ret, vol = portfolio_stats({l.product_id: l.weight for l in lines}, products)
    if not summary:
        note = ""
        if bucket != profile.bucket:
            note = f" Your profile was capped at {bucket} because you are classed as a vulnerable client (R5)."
        summary = (f"Proposed {bucket} allocation for {profile.name}: expected net return about {ret:.1%} a year "
                   f"with volatility about {vol:.1%}.{note}")
    a = Allocation(id=allocation_id or store.new_id("alloc"), client_id=profile.id, lines=lines,
                   expected_return=ret, volatility=vol, created_at=store.now(), summary=summary)
    a.client_text = make_client_text(summary, lines, products)
    return a
