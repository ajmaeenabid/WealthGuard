"""Deterministic compliance rule engine (R1-R8) plus an LLM second-opinion reviewer.

The engine is independent of the agent: it re-derives everything from the stored profile and product data. The LLM
reviewer can only add a failing check, never turn a failed rule into a pass.
"""
import re
from typing import Optional

from app import allocation as al
from app import config
from app.config import BUCKETS, EQUITY_LIKE
from app.schemas import Allocation, ClientProfile, ComplianceCheck, ComplianceResult, Product

TOL = 1e-6

BANNED = [
    r"\bguarantee[sd]?\b", r"\brisk[- ]?free\b", r"\bcan(?:'|’)?t lose\b", r"\bcannot lose\b", r"\bcan not lose\b",
    r"\bno risk\b", r"\bzero risk\b", r"\bwithout risk\b", r"\b100% safe\b", r"\bsure (profit|thing|win)\b",
    r"\bnever lose\b", r"\bcertain (return|profit)s?\b", r"\bassured returns?\b",
]
NEGATION = re.compile(r"\b(not|no|never|without|isn't|is not|cannot|can't)\s+(a\s+|an\s+|any\s+|the\s+)?"
                      r"guarantee[sd]?\b", re.IGNORECASE)


def _chk(rule_id: str, passed: bool, detail: str) -> ComplianceCheck:
    return ComplianceCheck(rule_id=rule_id, passed=passed, detail=detail)


def banned_phrases(text: str) -> list[str]:
    cleaned = NEGATION.sub(" ", text)
    hits = []
    for pat in BANNED:
        m = re.search(pat, cleaned, re.IGNORECASE)
        if m:
            hits.append(m.group(0))
    return hits


def _lines(a: Allocation, products: dict[str, Product]):
    return [(l, products[l.product_id]) for l in a.lines if l.product_id in products]


def r1_suitability(a, prof, products):
    lim = BUCKETS[prof.bucket]
    unknown = [l.product_id for l in a.lines if l.product_id not in products]
    bad = [f"{p.name} (risk {p.risk_level})" for _, p in _lines(a, products) if p.risk_level > lim["max_risk"]]
    eq = sum(l.weight for l, p in _lines(a, products) if p.asset_class in EQUITY_LIKE) * 100
    if unknown:
        return _chk("R1", False, f"Unknown product ids: {unknown}")
    if bad:
        return _chk("R1", False, f"Above {prof.bucket} max risk {lim['max_risk']}: {', '.join(bad)}")
    if eq > lim["max_equity_pct"] + TOL:
        return _chk("R1", False, f"Equity-like share {eq:.1f}% exceeds {prof.bucket} limit {lim['max_equity_pct']}%")
    return _chk("R1", True, f"All products within {prof.bucket} max risk {lim['max_risk']}; equity-like {eq:.1f}% "
                            f"(limit {lim['max_equity_pct']}%)")


def r2_concentration(a, prof, products):
    cap = BUCKETS[prof.bucket]["max_single_pct"]
    total = sum(l.weight for l in a.lines)
    if abs(total - 1) > 0.001:
        return _chk("R2", False, f"Weights sum to {total:.4f}, not 1")
    over = [f"{l.product_id} {l.weight:.1%}" for l in a.lines if l.weight * 100 > cap + TOL]
    if over:
        return _chk("R2", False, f"Above single-product cap {cap}%: {', '.join(over)}")
    top = max((l.weight for l in a.lines), default=0) * 100
    return _chk("R2", True, f"Largest position {top:.1f}% (cap {cap}%)")


def r3_complexity(a, prof, products):
    cx = [p.name for _, p in _lines(a, products) if p.complex]
    if cx and prof.experience != "advanced":
        return _chk("R3", False, f"Complex product(s) {', '.join(cx)} require advanced experience; "
                                 f"client is '{prof.experience}'")
    return _chk("R3", True, "No complex products" if not cx else "Complex products allowed: client is advanced")


def r4_liquidity(a, prof, products):
    locked_beyond = [f"{p.name} ({p.lockup_days}d)" for _, p in _lines(a, products)
                     if p.lockup_days > prof.horizon_years * 365]
    liquid = sum(l.weight for l, p in _lines(a, products) if p.lockup_days == 0) * 100
    if locked_beyond:
        return _chk("R4", False, f"Lock-up beyond {prof.horizon_years:g}-year horizon: {', '.join(locked_beyond)}")
    if liquid + TOL < prof.liquidity_need_pct:
        return _chk("R4", False, f"Liquid assets {liquid:.1f}% below liquidity need {prof.liquidity_need_pct:g}%")
    return _chk("R4", True, f"Liquid assets {liquid:.1f}% (need {prof.liquidity_need_pct:g}%); no lock-up past horizon")


def vulnerable(prof: ClientProfile) -> bool:
    return prof.age >= config.VULNERABLE_AGE or prof.horizon_years < config.VULNERABLE_HORIZON_YEARS


def r5_vulnerable(a, prof, products):
    if not vulnerable(prof):
        return _chk("R5", True, "Not a vulnerable client")
    lim = BUCKETS[config.VULNERABLE_CAP_BUCKET]
    ls = _lines(a, products)
    eq = sum(l.weight for l, p in ls if p.asset_class in EQUITY_LIKE) * 100
    problems = []
    if any(p.risk_level > lim["max_risk"] for _, p in ls):
        problems.append(f"product risk above {lim['max_risk']}")
    if eq > lim["max_equity_pct"] + TOL:
        problems.append(f"equity-like {eq:.1f}% above {lim['max_equity_pct']}%")
    if any(l.weight * 100 > lim["max_single_pct"] + TOL for l, _ in ls):
        problems.append(f"position above {lim['max_single_pct']}%")
    if problems:
        return _chk("R5", False, f"Vulnerable client (age {prof.age}, horizon {prof.horizon_years:g}y) must stay "
                                 f"within Moderate limits: {'; '.join(problems)}")
    return _chk("R5", True, f"Vulnerable client held within {config.VULNERABLE_CAP_BUCKET} limits")


def required_disclosures(a: Allocation, products: dict[str, Product]) -> list[str]:
    return al.disclosures([l for l in a.lines if l.product_id in products], products)


def r6_disclosures(a, prof, products):
    t = a.client_text.lower()
    missing = []
    if "risk" not in t or "lose" not in t:
        missing.append("risk warning")
    if config.FEE_MARKER not in t or "%" not in t:
        missing.append("fee summary")
    if "past performance" not in t:
        missing.append("past-performance disclaimer")
    if missing:
        return _chk("R6", False, f"Missing disclosure(s): {', '.join(missing)}")
    return _chk("R6", True, "Risk warning, fee summary and past-performance disclaimer present")


def r7_language(a, prof, products):
    texts = [a.summary, a.client_text] + [l.rationale for l in a.lines]
    hits = sorted({h.lower() for t in texts for h in banned_phrases(t)})
    if hits:
        return _chk("R7", False, f"Prohibited wording: {', '.join(hits)}")
    return _chk("R7", True, "No guaranteed / risk-free / can't-lose wording")


def r8_minimums(a, prof, products):
    bad = [f"{p.name} needs CNY {p.min_invest_cny:,.0f}, gets CNY {l.weight * prof.investable_amount_cny:,.0f}"
           for l, p in _lines(a, products) if l.weight * prof.investable_amount_cny + TOL < p.min_invest_cny]
    if bad:
        return _chk("R8", False, "Below minimum investment: " + "; ".join(bad))
    return _chk("R8", True, f"All lines meet minimums on CNY {prof.investable_amount_cny:,.0f}")


RULES = [r1_suitability, r2_concentration, r3_complexity, r4_liquidity, r5_vulnerable, r6_disclosures,
         r7_language, r8_minimums]


def llm_review(a: Allocation) -> Optional[ComplianceCheck]:
    """Second opinion on explanation quality. Returns a check only; failure can only make the result stricter."""
    try:
        from app.agent import llm
        verdict = llm.review(a.client_text)
    except Exception:  # reviewer unavailable: deterministic rules alone decide
        return None
    if verdict.get("approve", True):
        return _chk("LLM", True, "Reviewer found no explanation-quality concerns")
    return _chk("LLM", False, "Reviewer concern: " + "; ".join(verdict.get("concerns", ["unspecified"])))


def check(a: Allocation, prof: ClientProfile, products: dict[str, Product], use_llm: bool = True) -> ComplianceResult:
    checks = [rule(a, prof, products) for rule in RULES]
    if use_llm:
        r = llm_review(a)
        if r:
            checks.append(r)
    return ComplianceResult(allocation_id=a.id, passed=all(c.passed for c in checks), checks=checks,
                            required_disclosures=required_disclosures(a, products))


def violating_products(a: Allocation, prof: ClientProfile, products: dict[str, Product]) -> list[str]:
    """Product ids that individually break R1/R3/R4/R5/R8 - the agent drops these when revising."""
    lim = BUCKETS[prof.bucket]
    vcap = BUCKETS[config.VULNERABLE_CAP_BUCKET] if vulnerable(prof) else None
    out = []
    for l, p in _lines(a, products):
        if (p.risk_level > lim["max_risk"] or (p.complex and prof.experience != "advanced")
                or p.lockup_days > prof.horizon_years * 365
                or l.weight * prof.investable_amount_cny + TOL < p.min_invest_cny
                or (vcap and p.risk_level > vcap["max_risk"])):
            out.append(p.id)
    out += [l.product_id for l in a.lines if l.product_id not in products]
    return out
