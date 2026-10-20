"""Behaviour insights from the purchase ledger. Pure arithmetic and fixed templates: no model is involved, so every number is reproducible and every sentence can be traced to a rule."""
from collections import defaultdict
from typing import Optional

from app import ledger, store

HIGH_SPEND_RATIO = 0.80
ELEVATED_SPEND_RATIO = 0.60
IMPULSE_SHARE = 0.30
CONCENTRATION_SHARE = 0.50
CANCEL_RATE = 0.30
PENALTY_PER_FLAG = 5.0
MAX_PENALTY = 10.0
NOTE = "Based only on the records you entered. This is general guidance, not a prediction or financial advice."


def _income(client_id: str) -> Optional[float]:
    d = store.load_client(client_id) or {}
    v = (d.get("facts") or {}).get("monthly_income_cny")
    try:
        return float(v) if v else None
    except (TypeError, ValueError):
        return None


def insights(client_id: str) -> dict:
    entries = ledger.list_entries(client_id)
    bought = [e for e in entries if e.status == "bought"]
    planned = [e for e in entries if e.status == "planned"]
    cancelled = [e for e in entries if e.status == "cancelled"]
    total = round(sum(e.amount_cny for e in bought), 2)
    by_cat, by_month = defaultdict(float), defaultdict(float)
    for e in bought:
        by_cat[e.category] += e.amount_cny
        by_month[e.ts[:7]] += e.amount_cny
    months = max(len(by_month), 1)
    avg_month = round(total / months, 2)
    income = _income(client_id)
    ratio = round(avg_month / income, 4) if income and bought else None
    impulse_total = sum(e.amount_cny for e in bought if e.impulse)
    impulse_share = round(impulse_total / total, 4) if total else 0.0
    n = len(entries)
    cancel_rate = round(len(cancelled) / n, 4) if n else 0.0
    top_cat, top_share = (None, 0.0)
    if by_cat:
        top_cat = max(by_cat, key=by_cat.get)
        top_share = round(by_cat[top_cat] / total, 4)
    planned_total = round(sum(e.amount_cny for e in planned), 2)

    flags, penalty = [], 0.0

    def flag(code, severity, text, pen=0.0):
        nonlocal penalty
        flags.append({"code": code, "severity": severity, "text": text})
        penalty += pen

    if ratio is not None and ratio >= HIGH_SPEND_RATIO:
        flag("HIGH_SPEND", "high", f"Your recorded purchases average CNY {avg_month:,.0f} a month, about {ratio:.0%} of "
             f"your income. That leaves little room to save or to absorb investment losses.", PENALTY_PER_FLAG)
    elif ratio is not None and ratio >= ELEVATED_SPEND_RATIO:
        flag("ELEVATED_SPEND", "info", f"Your recorded purchases average CNY {avg_month:,.0f} a month, about {ratio:.0%} "
             f"of your income. Check whether a savings target is realistic.")
    if total and impulse_share >= IMPULSE_SHARE:
        flag("IMPULSE_HEAVY", "high", f"About {impulse_share:.0%} of what you bought was tagged as impulse. A 24-hour "
             f"wait before non-essential purchases is a common way to reduce this.", PENALTY_PER_FLAG)
    if top_cat and top_share >= CONCENTRATION_SHARE and len(bought) >= 3:
        flag("CATEGORY_CONCENTRATION", "info", f"{top_share:.0%} of your spending is in one category ({top_cat}). "
             f"Review whether that matches your priorities.")
    if n >= 3 and cancel_rate >= CANCEL_RATE:
        flag("CANCEL_PATTERN", "info", f"You cancelled {len(cancelled)} of {n} entries. Planning and then skipping a "
             f"purchase is healthy, but make sure the planned list reflects real intentions.")
    if income and planned_total >= income * 0.5:
        flag("PLANNED_BACKLOG", "info", f"Your planned purchases total CNY {planned_total:,.0f}, about "
             f"{planned_total / income:.0%} of one month's income. Decide which ones you really want.")
    if not flags and bought:
        flag("STEADY", "ok", "Your recorded spending looks steady: no concerning pattern was found in these records.")

    return {
        "entries": n, "bought_count": len(bought), "planned_count": len(planned), "cancelled_count": len(cancelled),
        "bought_total": total, "planned_total": planned_total,
        "cancelled_total": round(sum(e.amount_cny for e in cancelled), 2),
        "by_category": {k: round(v, 2) for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])},
        "by_month": {k: round(v, 2) for k, v in sorted(by_month.items())},
        "avg_monthly_spend": avg_month, "monthly_income": income, "spend_ratio": ratio,
        "impulse_share": impulse_share, "cancel_rate": cancel_rate,
        "flags": flags, "capacity_penalty": min(MAX_PENALTY, penalty), "note": NOTE,
    }


def capacity_penalty(client_id: str) -> float:
    return insights(client_id)["capacity_penalty"]
