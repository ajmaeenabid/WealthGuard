"""Deterministic financial analysis. Every number the dashboard, the reports and the AI explanations use is computed here
from the user's own ledger entries; the language model only ever sees these results, never raw rows to add up.

Definitions (shown to the user wherever they matter):
  spending       expenses minus refunds, actual (dated now or earlier) and in the user's base currency
  income         income transactions only; refunds, transfers and adjustments are never income
  net cash flow  income - spending
  savings        money moved into savings or investment accounts (transfers) minus money moved out
  savings rate   savings / income (actual), and net cash flow / income (implied), reported separately
"""
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from app.finance import books, money, taxonomy
from app.finance.books import FinanceError

SAVINGS_TYPES = {"savings", "investment"}


# ---------------------------------------------------------------------------------------------- periods
def period(kind: str = "month", ref: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None) -> tuple[date, date]:
    d = date.fromisoformat(ref) if ref else money.today()
    if kind == "day":
        return d, d
    if kind == "week":
        s = d - timedelta(days=d.weekday())
        return s, s + timedelta(days=6)
    if kind == "month":
        return money.month_bounds(d)
    if kind == "year":
        return date(d.year, 1, 1), date(d.year, 12, 31)
    if kind == "custom":
        try:
            s, e = date.fromisoformat(start), date.fromisoformat(end)
        except (TypeError, ValueError):
            raise FinanceError("A custom period needs a start and an end date (YYYY-MM-DD).")
        if e < s:
            raise FinanceError("The end date is before the start date.")
        if (e - s).days > 3660:
            raise FinanceError("The period is too long.")
        return s, e
    raise FinanceError("Period must be day, week, month, year or custom.")


def previous(start: date, end: date, kind: str = "custom") -> tuple[date, date]:
    if kind == "month":
        return money.month_bounds(start - timedelta(days=1))
    if kind == "year":
        return date(start.year - 1, 1, 1), date(start.year - 1, 12, 31)
    n = (end - start).days + 1
    return start - timedelta(days=n), start - timedelta(days=1)


def _rows(user: str, start: date, end: date) -> list:
    """Actual, non-deleted transactions in the base currency within the window (future-dated ones are scheduled, not actual)."""
    base = books.base_currency(user)
    upper = min(money.iso(datetime.combine(end, datetime.max.time())), money.iso(money.now()))
    c = books.db.connect()
    try:
        return c.execute("SELECT * FROM fin_transactions WHERE username=? AND deleted_at IS NULL AND currency=? AND ts>=? AND ts<=? ORDER BY ts",
                         (user, base, start.isoformat() + "T00:00:00", upper)).fetchall()
    finally:
        c.close()


def _account_types(user: str) -> dict:
    return {a["id"]: a["type"] for a in books.list_accounts(user, include_archived=True)}


def _share(part: int, whole: int) -> Optional[float]:
    return round(part / whole, 4) if whole else None


def summary(user: str, start: date, end: date) -> dict:
    base = books.base_currency(user)
    rows = _rows(user, start, end)
    types = _account_types(user)
    income = expense = refunds = 0
    savings_in = savings_out = 0
    cats, merchants, methods = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0]), defaultdict(int)
    essential = {"essential": 0, "discretionary": 0, "unclassified": 0}
    recurring = {"recurring": 0, "one_time": 0}
    daily = defaultdict(int)
    weekday = defaultdict(int)
    income_by_cat = defaultdict(int)
    amounts = []
    for r in rows:
        f = r["final_minor"]
        if r["type"] == "income":
            income += f
            income_by_cat[r["category"] or "other income"] += f
        elif r["type"] == "expense":
            expense += f
            cat = r["category"] or "other"
            cats[cat][0] += f
            cats[cat][1] += 1
            m = (r["merchant"] or "").strip()
            if m:
                merchants[m][0] += f
                merchants[m][1] += 1
            methods[r["payment_method"] or "unspecified"] += f
            essential["essential" if r["essential"] == 1 else "discretionary" if r["essential"] == 0 else "unclassified"] += f
            recurring["recurring" if r["recurring"] else "one_time"] += f
            daily[r["ts"][:10]] += f
            weekday[datetime.fromisoformat(r["ts"]).strftime("%a")] += f
            amounts.append(f)
        elif r["type"] == "refund":
            refunds += f
            cat = r["category"] or "other"
            cats[cat][0] -= f
        elif r["type"] == "transfer":
            src, dst = types.get(r["account_id"]), types.get(r["to_account_id"])
            if dst in SAVINGS_TYPES and src not in SAVINGS_TYPES:
                savings_in += f
            elif src in SAVINGS_TYPES and dst not in SAVINGS_TYPES:
                savings_out += f
    spending = max(0, expense - refunds)
    net_flow = income - spending
    savings = savings_in - savings_out
    days = (end - start).days + 1
    elapsed = max(1, (min(end, money.today()) - start).days + 1)
    series = []
    d = start
    while d <= min(end, money.today()):
        series.append({"date": d.isoformat(), "amount": money.s(daily.get(d.isoformat(), 0)), "minor": daily.get(d.isoformat(), 0)})
        d += timedelta(days=1)
    cat_rows = sorted(({"category": k, "amount": money.s(max(0, v[0])), "minor": max(0, v[0]), "count": v[1], "share": _share(max(0, v[0]), spending)}
                       for k, v in cats.items() if v[0] > 0), key=lambda x: -x["minor"])
    merch_rows = sorted(({"merchant": k, "amount": money.s(v[0]), "minor": v[0], "count": v[1], "share": _share(v[0], expense)}
                         for k, v in merchants.items()), key=lambda x: -x["minor"])[:10]
    big = sorted((r for r in rows if r["type"] == "expense"), key=lambda r: -r["final_minor"])[:5]
    return {
        "currency": base, "start": start.isoformat(), "end": end.isoformat(), "days": days, "days_elapsed": elapsed, "transactions": len(rows),
        "income": money.s(income), "income_minor": income, "spending": money.s(spending), "spending_minor": spending,
        "expense_gross": money.s(expense), "refunds": money.s(refunds), "net_cash_flow": money.s(net_flow), "net_cash_flow_minor": net_flow,
        "savings_contributions": money.s(savings_in), "savings_withdrawals": money.s(savings_out), "savings_net": money.s(savings), "savings_net_minor": savings,
        "savings_rate_actual": _share(savings, income), "savings_rate_implied": _share(net_flow, income),
        "average_daily_spending": money.s(spending // elapsed), "average_daily_minor": spending // elapsed,
        "by_category": cat_rows, "by_merchant": merch_rows,
        "by_payment_method": [{"method": k, "amount": money.s(v), "minor": v} for k, v in sorted(methods.items(), key=lambda x: -x[1])],
        "essential_split": {k: {"amount": money.s(v), "minor": v, "share": _share(v, expense)} for k, v in essential.items()},
        "recurring_split": {k: {"amount": money.s(v), "minor": v, "share": _share(v, expense)} for k, v in recurring.items()},
        "income_by_category": [{"category": k, "amount": money.s(v), "minor": v} for k, v in sorted(income_by_cat.items(), key=lambda x: -x[1])],
        "daily": series, "by_weekday": {k: money.s(v) for k, v in weekday.items()},
        "largest": [{"id": r["id"], "merchant": r["merchant"], "category": r["category"], "amount": money.s(r["final_minor"]), "ts": r["ts"][:10]} for r in big],
        "median_expense_minor": int(statistics.median(amounts)) if amounts else 0,
        "definitions": {"spending": "expenses minus refunds", "income": "income transactions only (refunds, transfers and adjustments excluded)",
                        "savings": "transfers into savings/investment accounts minus transfers out",
                        "basis": "actual transactions dated up to now, in " + base},
        "excluded": {"other_currency_accounts": [a["name"] for a in books.list_accounts(user) if a["currency"] != base],
                     "future_dated": _future_count(user)},
    }


def _future_count(user: str) -> int:
    c = books.db.connect()
    try:
        return c.execute("SELECT COUNT(*) FROM fin_transactions WHERE username=? AND deleted_at IS NULL AND ts>?", (user, money.iso(money.now()))).fetchone()[0]
    finally:
        c.close()


def compare(cur: dict, prev: dict) -> dict:
    def delta(k):
        a, b = cur[k + "_minor"], prev[k + "_minor"]
        return {"current": money.s(a), "previous": money.s(b), "change": money.s(a - b), "change_pct": round((a - b) / b, 4) if b else None}
    prev_cats = {c["category"]: c["minor"] for c in prev["by_category"]}
    cats = []
    for c in cur["by_category"]:
        p = prev_cats.get(c["category"], 0)
        cats.append({"category": c["category"], "current": c["amount"], "previous": money.s(p), "change": money.s(c["minor"] - p),
                     "change_pct": round((c["minor"] - p) / p, 4) if p else None})
    return {"income": delta("income"), "spending": delta("spending"), "net_cash_flow": delta("net_cash_flow"), "categories": cats,
            "previous_period": {"start": prev["start"], "end": prev["end"]}}


# ---------------------------------------------------------------------------------------------- insights
def _insight(kind: str, title: str, pattern: str, evidence: dict, why: str, action: str, impact_minor: Optional[int] = None,
             assumptions: Optional[list] = None, severity: str = "info") -> dict:
    return {"kind": kind, "severity": severity, "title": title, "pattern": pattern, "evidence": evidence, "why": why, "action": action,
            "impact": None if impact_minor is None else money.s(impact_minor), "impact_minor": impact_minor, "assumptions": assumptions or []}


def insights(user: str, start: date, end: date, cur: Optional[dict] = None, prev: Optional[dict] = None) -> list[dict]:
    cur = cur or summary(user, start, end)
    base = cur["currency"]
    out = []
    spending = cur["spending_minor"]
    period_txt = f"{cur['start']} to {cur['end']}"
    if spending <= 0:
        return out
    top = cur["by_category"][0] if cur["by_category"] else None
    if top and (top["share"] or 0) >= 0.30 and len(cur["by_category"]) > 1:
        out.append(_insight("top_category", f"{top['category'].title()} is your biggest category",
                            f"{top['category']} was {round(top['share'] * 100)}% of spending ({money.fmt(top['minor'], base)}) in {period_txt}.",
                            {"category": top["category"], "amount": top["amount"], "share": top["share"], "count": top["count"]},
                            "A single category above 30% of spending is where a small change moves the total most.",
                            f"Look at the {top['count']} {top['category']} transactions and decide which are fixed and which are choices.",
                            int(top["minor"] * 0.10), ["Assumes a 10% reduction is realistic for this category."]))
    if prev:
        pc = {c["category"]: c["minor"] for c in prev["by_category"]}
        for c in cur["by_category"]:
            p = pc.get(c["category"], 0)
            inc = c["minor"] - p
            if p and inc / p >= 0.30 and inc >= prev["spending_minor"] * 0.05:
                out.append(_insight("category_increase", f"{c['category'].title()} spending went up",
                                    f"{c['category']} rose from {money.fmt(p, base)} to {money.fmt(c['minor'], base)} (+{round(inc / p * 100)}%) compared with the previous period.",
                                    {"category": c["category"], "current": c["amount"], "previous": money.s(p), "increase": money.s(inc)},
                                    "A sharp rise is worth checking in case it is a one-off rather than a new habit.",
                                    f"Review this period's {c['category']} purchases and mark the one-offs as such.", inc // 2,
                                    ["Assumes about half of the increase could be avoided."], "attention"))
    amounts = sorted(cur["daily"], key=lambda d: d["minor"])
    # small purchases that add up
    c = books.db.connect()
    try:
        rows = c.execute("SELECT final_minor, merchant, category FROM fin_transactions WHERE username=? AND type='expense' AND deleted_at IS NULL AND currency=? AND ts>=? AND ts<=?",
                         (user, base, start.isoformat() + "T00:00:00", end.isoformat() + "T23:59:59")).fetchall()
    finally:
        c.close()
    small_limit = int(spending * 0.02)                       # "small" = each purchase is at most 2% of the period's spending
    small = [r for r in rows if r["final_minor"] <= small_limit]
    small_total = sum(r["final_minor"] for r in small)
    if len(small) >= 8 and small_total >= spending * 0.10:
        out.append(_insight("small_purchases", "Small purchases are adding up",
                            f"{len(small)} purchases of {money.fmt(small_limit, base)} or less added up to {money.fmt(small_total, base)} ({round(small_total / spending * 100)}% of spending) in {period_txt}.",
                            {"count": len(small), "total": money.s(small_total), "share": round(small_total / spending, 4)},
                            "Frequent small amounts are easy to overlook but can be a meaningful share of the month.",
                            "Pick the one or two small habits you value least and set a weekly limit for them.", int(small_total * 0.2),
                            ["Assumes a 20% cut in small purchases."]))
    # frequent merchant
    for m in cur["by_merchant"][:3]:
        if m["count"] >= 5 and (m["share"] or 0) >= 0.08:
            out.append(_insight("frequent_merchant", f"Frequent spending at {m['merchant']}",
                                f"{m['count']} purchases at {m['merchant']} totalled {money.fmt(m['minor'], base)} in {period_txt}.",
                                {"merchant": m["merchant"], "count": m["count"], "total": m["amount"]},
                                "Repeated visits to one place are a pattern you can plan around.",
                                f"Check whether a weekly plan or a bulk purchase at {m['merchant']} would cost less.", int(m["minor"] * 0.1),
                                ["Assumes a 10% saving from planning."]))
            break
    # unusual days
    vals = [d["minor"] for d in cur["daily"] if d["minor"] > 0]
    if len(vals) >= 10:
        mean, sd = statistics.mean(vals), statistics.pstdev(vals)
        if sd:
            hi = max(cur["daily"], key=lambda d: d["minor"])
            z = (hi["minor"] - mean) / sd
            if z >= 2:
                out.append(_insight("unusual_day", "One day stands out", f"On {hi['date']} you spent {money.fmt(hi['minor'], base)}, about {z:.1f} standard deviations above your usual day ({money.fmt(int(mean), base)}).",
                                    {"date": hi["date"], "amount": hi["amount"], "typical_day": money.s(int(mean)), "z_score": round(z, 2)},
                                    "Unusually large days can be one-off events or an unplanned purchase.",
                                    "Check what happened that day and tag it as a one-off if it will not repeat.", None, [], "attention"))
    # discretionary share
    es = cur["essential_split"]
    classified = es["essential"]["minor"] + es["discretionary"]["minor"]
    if classified and es["discretionary"]["minor"] / classified >= 0.40:
        d = es["discretionary"]["minor"]
        out.append(_insight("discretionary_share", "A large share of spending is discretionary",
                            f"{round(d / classified * 100)}% of classified spending ({money.fmt(d, base)}) was discretionary in {period_txt}.",
                            {"discretionary": money.s(d), "essential": es["essential"]["amount"], "unclassified": es["unclassified"]["amount"]},
                            "Discretionary spending is the part you can adjust without touching bills or food.",
                            "Choose one discretionary category to cap next month.", int(d * 0.10), ["Assumes a 10% reduction in discretionary spending."]))
    # savings rate
    inc = cur["income_minor"]
    if inc > 0 and cur["savings_rate_implied"] is not None and cur["savings_rate_implied"] < 0.10:
        out.append(_insight("low_savings", "Little is left to save" if cur["net_cash_flow_minor"] >= 0 else "Spending exceeded income",
                            f"Income was {money.fmt(inc, base)} and spending {money.fmt(spending, base)}, leaving {money.fmt(cur['net_cash_flow_minor'], base)} ({round(cur['savings_rate_implied'] * 100)}% of income).",
                            {"income": cur["income"], "spending": cur["spending"], "net_cash_flow": cur["net_cash_flow"]},
                            "Saving less than about 10% of income leaves little buffer for surprises.",
                            "Set a fixed monthly transfer to savings on payday, even a small one.", None, [], "attention"))
    # subscriptions (same merchant, same amount, about a month apart)
    subs = detect_subscriptions(user)
    if subs:
        total = sum(s["monthly_minor"] for s in subs)
        out.append(_insight("subscriptions", "Recurring payments detected",
                            f"{len(subs)} recurring payments cost about {money.fmt(total, base)} a month: " + ", ".join(s["merchant"] for s in subs[:5]) + ".",
                            {"count": len(subs), "monthly_total": money.s(total), "items": [{"merchant": s["merchant"], "monthly": money.s(s["monthly_minor"])} for s in subs[:8]]},
                            "Subscriptions renew without a decision each time.", "Review each one and cancel what you no longer use.", None,
                            ["Detected from repeated payments of the same amount to the same merchant."]))
    return out


def detect_subscriptions(user: str, lookback_days: int = 120) -> list[dict]:
    base = books.base_currency(user)
    since = (money.today() - timedelta(days=lookback_days)).isoformat()
    c = books.db.connect()
    try:
        rows = c.execute("SELECT merchant, final_minor, ts, recurring FROM fin_transactions WHERE username=? AND type='expense' AND deleted_at IS NULL "
                         "AND currency=? AND ts>=? AND merchant IS NOT NULL ORDER BY ts", (user, base, since + "T00:00:00")).fetchall()
    finally:
        c.close()
    groups = defaultdict(list)
    for r in rows:
        groups[(r["merchant"].strip().lower(), r["final_minor"])].append(r)
    out = []
    for (merchant, amount), rs in groups.items():
        if len(rs) < 2:
            continue
        dates = [datetime.fromisoformat(r["ts"]).date() for r in rs]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        monthly = all(25 <= g <= 35 for g in gaps)
        if monthly or all(r["recurring"] for r in rs):
            out.append({"merchant": rs[0]["merchant"], "amount": money.s(amount), "monthly_minor": amount, "occurrences": len(rs), "last": dates[-1].isoformat()})
    return sorted(out, key=lambda x: -x["monthly_minor"])
