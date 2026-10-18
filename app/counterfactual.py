"""Counterfactual compliance: "what would have to be true for this product to be allowed for this client?"

For one product and the client's stored answers it reports, per rule, whether the product passes today, and searches the
questionnaire (5 changeable answers, 720 combinations) for the smallest set of different answers under which the product
would be eligible. Facts that cannot change (age, horizon, income) are respected, so an impossible case is said to be impossible
and why.

This is an explanation, never advice to change an answer: suitability depends on truthful answers, and nothing here changes
the profile. The search uses the same scoring and eligibility code as the real engine (profiling + allocation.eligible).
"""
import itertools

from app import config, knowledge, profiling, store
from app.config import BUCKET_ORDER, BUCKETS, lower_bucket
from app.products import load_products

MUTABLE = ["loss_reaction", "income_stability", "liquidity_need_pct", "goal", "experience"]
NOTE = ("This shows what would have to be true for the product to be allowed. It is not a suggestion to change your answers: "
        "advice is only suitable if your answers are truthful, and nothing here changes your profile.")


def _scores(facts: dict, penalty: float) -> tuple[float, float]:
    tol, cap = profiling.compute_scores(facts)
    return tol, round(max(0.0, cap - penalty), 1)


def _bucket(tol: float, cap: float) -> str:
    return lower_bucket(profiling.score_to_bucket(tol), profiling.score_to_bucket(cap))


def _eligible(product, facts: dict, bucket: str) -> bool:
    eff = config.effective_bucket(bucket, int(float(facts["age"])), float(facts["horizon_years"]))
    return (product.risk_level <= BUCKETS[eff]["max_risk"]
            and (not product.complex or facts.get("experience") == "advanced")
            and product.lockup_days <= float(facts["horizon_years"]) * 365)


def _options(qid: str) -> list:
    return list(profiling.QBY[qid]["options"].keys())


def _label(qid: str, value) -> str:
    return profiling.QBY[qid]["options"][value][0]


def _article(rule: str):
    b = knowledge.basis_for_rule(rule)
    return {"ref": b["article"], "snippet": b["snippet"], "url": b["url"]} if b else None


def _rule_status(product, facts: dict, bucket: str) -> list[dict]:
    eff = config.effective_bucket(bucket, int(float(facts["age"])), float(facts["horizon_years"]))
    lim = BUCKETS[eff]
    out = []
    ok = product.risk_level <= lim["max_risk"]
    out.append({"rule": "R1", "passed": ok, "detail": f"risk level {product.risk_level} vs your {eff} limit {lim['max_risk']}",
                "needs": None if ok else f"a bucket with maximum risk level {product.risk_level} or more"})
    ok = not product.complex or facts.get("experience") == "advanced"
    out.append({"rule": "R3", "passed": ok, "detail": "complex product" if product.complex else "not a complex product",
                "needs": None if ok else "advanced investing experience"})
    ok = product.lockup_days <= float(facts["horizon_years"]) * 365
    out.append({"rule": "R4", "passed": ok, "detail": f"lock-up {product.lockup_days} days vs horizon {float(facts['horizon_years']):g} years",
                "needs": None if ok else f"a horizon of at least {product.lockup_days / 365:.1f} years"})
    vul = config.effective_bucket("Aggressive", int(float(facts["age"])), float(facts["horizon_years"])) != "Aggressive"
    out.append({"rule": "R5", "passed": not (vul and product.risk_level > BUCKETS[config.VULNERABLE_CAP_BUCKET]["max_risk"]),
                "detail": "vulnerable client (age 65 or older, or horizon under 2 years): capped at Moderate" if vul else "not a vulnerable client",
                "needs": None})
    for r in out:
        r["article"] = _article(r["rule"])
    return out


def explain(client_id: str, product_id: str) -> dict:
    d = store.load_client(client_id)
    products = load_products()
    if not d:
        return {"ok": False, "error": "unknown client"}
    if product_id not in products:
        return {"ok": False, "error": f"unknown product {product_id}"}
    facts = {k: v for k, v in d["facts"].items()}
    missing = profiling.missing(facts)
    if missing:
        return {"ok": False, "error": f"profile incomplete; still needed: {missing}"}
    p = products[product_id]
    penalty = float((d.get("extra") or {}).get("behaviour_penalty_applied", 0) or 0)
    tol, cap = _scores(facts, penalty)
    bucket = _bucket(tol, cap)
    rules = _rule_status(p, facts, bucket)
    allowed = _eligible(p, facts, bucket)

    # search over the changeable answers
    base = {q: facts.get(q) for q in MUTABLE if q in facts}
    names = [q for q in MUTABLE if q in base]
    candidates = []
    best_tol = best_cap = 0.0
    for combo in itertools.product(*[_options(q) for q in names]):
        cand = {**facts, **dict(zip(names, combo))}
        t, c = _scores(cand, penalty)
        best_tol, best_cap = max(best_tol, t), max(best_cap, c)
        b = _bucket(t, c)
        if _eligible(p, cand, b):
            changes = [{"fact": q, "from": base[q], "to": v, "from_label": _label(q, base[q]), "to_label": _label(q, v)}
                       for q, v in zip(names, combo) if v != base[q]]
            candidates.append({"changes": changes, "tolerance": t, "capacity": c, "bucket": b,
                               "_key": (len(changes), abs(t - tol) + abs(c - cap))})
    candidates.sort(key=lambda x: (x["_key"], str(x["changes"])))
    paths = [{k: v for k, v in c.items() if k != "_key"} for c in candidates[:3]]
    max_bucket = _bucket(best_tol, best_cap)
    why_not = None
    if not allowed and not paths:
        need = BUCKET_ORDER[min(i for i, b in enumerate(BUCKET_ORDER) if BUCKETS[b]["max_risk"] >= p.risk_level)] \
            if any(BUCKETS[b]["max_risk"] >= p.risk_level for b in BUCKET_ORDER) else None
        reasons = []
        age, horizon = int(float(facts["age"])), float(facts["horizon_years"])
        if config.effective_bucket("Aggressive", age, horizon) != "Aggressive" and p.risk_level > BUCKETS[config.VULNERABLE_CAP_BUCKET]["max_risk"]:
            reasons.append(f"you are a vulnerable client (age {age}, horizon {horizon:g} years), which caps you at "
                           f"{config.VULNERABLE_CAP_BUCKET} (maximum risk level {BUCKETS[config.VULNERABLE_CAP_BUCKET]['max_risk']})")
        if p.lockup_days > horizon * 365:
            reasons.append(f"the lock-up of {p.lockup_days} days is longer than your {horizon:g}-year horizon, and a horizon is a fact, not an answer")
        if need and BUCKET_ORDER.index(max_bucket) < BUCKET_ORDER.index(need):
            reasons.append(f"even with the most favourable truthful answers your best bucket would be {max_bucket} "
                           f"(tolerance up to {best_tol:g}, capacity up to {best_cap:g}), below the {need} this product needs; "
                           f"age {age}, horizon {horizon:g} years and income limit capacity")
        why_not = "; ".join(reasons) or "no combination of your answers makes it eligible"
    return {
        "ok": True, "product": {"id": p.id, "name": p.name, "risk_level": p.risk_level, "complex": p.complex,
                                "lockup_days": p.lockup_days},
        "allowed_now": allowed, "current": {"tolerance": tol, "capacity": cap, "bucket": bucket,
                                           "experience": facts.get("experience")},
        "rules": rules, "reachable_by_answers": bool(paths) or allowed, "paths": paths,
        "max_reachable": {"tolerance": best_tol, "capacity": best_cap, "bucket": max_bucket},
        "impossible_because": why_not, "combinations_checked": len(list(itertools.product(*[_options(q) for q in names]))),
        "note": NOTE,
    }
