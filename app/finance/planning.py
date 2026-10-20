"""Budgets, goals, recurring obligations, alerts and the forecast."""
import statistics
from datetime import date, datetime, timedelta
from typing import Optional

from app import store
from app.finance import analytics, books, money, taxonomy
from app.finance.books import FinanceError, new_id

RECURRENCES = ("once", "weekly", "monthly", "yearly")


def _one(sql, params=()):
    return books._one(sql, params)


def _days(n: int) -> str:
    return f"{n} day" + ("" if n == 1 else "s")


def _q(sql, params=()):
    return books._q(sql, params)


def _date(v, label: str) -> str:
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        raise FinanceError(f"{label} must be a date like 2026-10-31.")


def _amt(v, label: str) -> int:
    try:
        n = money.to_minor(v)
    except money.MoneyError as e:
        raise FinanceError(f"{label}: {e}")
    if n <= 0:
        raise FinanceError(f"{label} must be greater than zero.")
    return n


def _budget_out(r, as_of: Optional[date] = None) -> dict:
    as_of = as_of or money.today()
    s, e = _budget_window(r, as_of)
    base = {"id": r["id"], "name": r["name"], "category": r["category"], "period": r["period"], "limit": money.s(r["limit_minor"]),
            "currency": r["currency"], "alert_pct": r["alert_pct"], "active": bool(r["active"]), "start_date": r["start_date"], "end_date": r["end_date"],
            "window": {"start": s.isoformat(), "end": e.isoformat()}}
    spent = _spent(r["username"], s, e, r["category"], r["currency"])
    limit = r["limit_minor"]
    days_total = (e - s).days + 1
    days_elapsed = max(1, min(days_total, (min(as_of, e) - s).days + 1)) if as_of >= s else 0
    projected = int(spent / days_elapsed * days_total) if days_elapsed else 0
    pct = spent / limit
    status = "over" if spent > limit else ("warning" if pct * 100 >= r["alert_pct"] else "ok")
    base.update({"spent": money.s(spent), "spent_minor": spent, "remaining": money.s(max(0, limit - spent)), "over_by": money.s(max(0, spent - limit)),
                 "utilization": round(pct, 4), "status": status, "projected_total": money.s(projected),
                 "projected_over": projected > limit and status != "over" and as_of <= e, "days_left": max(0, (e - as_of).days),
                 "basis": "actual spending (expenses minus refunds) in the window; the projection is an estimate from the pace so far"})
    return base


def _budget_window(r, as_of: date) -> tuple[date, date]:
    if r["period"] == "monthly":
        return money.month_bounds(as_of)
    if r["period"] == "weekly":
        s = as_of - timedelta(days=as_of.weekday())
        return s, s + timedelta(days=6)
    return date.fromisoformat(r["start_date"]), date.fromisoformat(r["end_date"])


def _spent(user: str, s: date, e: date, category: Optional[str], currency: str) -> int:
    where = "username=? AND deleted_at IS NULL AND currency=? AND ts>=? AND ts<=?"
    args = [user, currency, s.isoformat() + "T00:00:00", min(money.iso(datetime.combine(e, datetime.max.time())), money.iso(money.now()))]
    if category:
        where += " AND category=?"
        args.append(category)
    r = _one(f"SELECT COALESCE(SUM(CASE type WHEN 'expense' THEN final_minor WHEN 'refund' THEN -final_minor ELSE 0 END),0) AS n FROM fin_transactions WHERE {where}", tuple(args))
    return max(0, r["n"])


def create_budget(user: str, data: dict) -> dict:
    period = data.get("period", "monthly")
    if period not in ("weekly", "monthly", "custom"):
        raise FinanceError("Period must be weekly, monthly or custom.")
    cat = data.get("category") or None
    if cat and cat not in taxonomy.EXPENSE:
        raise FinanceError("Unknown category.")
    limit = _amt(data.get("limit"), "Budget limit")
    sd = ed = None
    if period == "custom":
        sd, ed = _date(data.get("start_date"), "Start date"), _date(data.get("end_date"), "End date")
        if ed < sd:
            raise FinanceError("The end date is before the start date.")
    try:
        alert = int(data.get("alert_pct", 80))
    except (TypeError, ValueError):
        raise FinanceError("Alert percentage must be a whole number.")
    if not 1 <= alert <= 200:
        raise FinanceError("Alert percentage must be between 1 and 200.")
    name = (data.get("name") or (f"{cat.title()} budget" if cat else "Overall budget")).strip()[:60]
    bid, now = new_id("bud"), store.now()
    store._write("INSERT INTO fin_budgets (id, username, name, category, period, start_date, end_date, limit_minor, currency, alert_pct, active, created, updated) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)", (bid, user, name, cat, period, sd, ed, limit, books.base_currency(user), alert, now, now))
    books._audit(user, "fin_budget_created", {"id": bid, "category": cat, "limit_minor": limit})
    return get_budget(user, bid)


def get_budget(user: str, bid: str) -> dict:
    r = _one("SELECT * FROM fin_budgets WHERE id=? AND username=?", (bid, user))
    if not r:
        raise FinanceError("No such budget.", 404)
    return _budget_out(r)


def list_budgets(user: str, as_of: Optional[date] = None) -> list[dict]:
    return [_budget_out(r, as_of) for r in _q("SELECT * FROM fin_budgets WHERE username=? ORDER BY active DESC, created", (user,))]


def update_budget(user: str, bid: str, patch: dict) -> dict:
    r = _one("SELECT * FROM fin_budgets WHERE id=? AND username=?", (bid, user))
    if not r:
        raise FinanceError("No such budget.", 404)
    limit = _amt(patch["limit"], "Budget limit") if "limit" in patch else r["limit_minor"]
    alert = int(patch.get("alert_pct", r["alert_pct"]))
    if not 1 <= alert <= 200:
        raise FinanceError("Alert percentage must be between 1 and 200.")
    store._write("UPDATE fin_budgets SET name=?, limit_minor=?, alert_pct=?, active=?, updated=? WHERE id=? AND username=?",
                 ((patch.get("name") or r["name"])[:60], limit, alert, 1 if patch.get("active", bool(r["active"])) else 0, store.now(), bid, user))
    books._audit(user, "fin_budget_updated", {"id": bid, "fields": sorted(patch)})
    return get_budget(user, bid)


def delete_budget(user: str, bid: str) -> dict:
    get_budget(user, bid)
    store._write("DELETE FROM fin_budgets WHERE id=? AND username=?", (bid, user))
    books._audit(user, "fin_budget_deleted", {"id": bid})
    return {"deleted": bid}


def _goal_out(r) -> dict:
    user = r["username"]
    c = _one("SELECT COALESCE(SUM(final_minor),0) AS n FROM fin_transactions WHERE username=? AND deleted_at IS NULL AND type='transfer' AND goal_id=? AND ts<=?",
             (user, r["id"], money.iso(money.now())))["n"]
    saved = r["saved_minor"] + c
    target = r["target_minor"]
    remaining = max(0, target - saved)
    since = money.iso(datetime.combine(money.today() - timedelta(days=90), datetime.min.time()))
    recent = _one("SELECT COALESCE(SUM(final_minor),0) AS n FROM fin_transactions WHERE username=? AND deleted_at IS NULL AND type='transfer' AND goal_id=? AND ts>=? AND ts<=?",
                  (user, r["id"], since, money.iso(money.now())))["n"]
    actual_monthly = int(recent / 3)
    plan = r["monthly_minor"] or 0
    out = {"id": r["id"], "name": r["name"], "description": r["description"], "target": money.s(target), "saved": money.s(saved), "saved_minor": saved,
           "baseline_saved": money.s(r["saved_minor"]), "contributed": money.s(c), "remaining": money.s(remaining), "currency": r["currency"],
           "target_date": r["target_date"], "priority": r["priority"], "monthly_target": money.s(plan) if plan else None, "account_id": r["account_id"],
           "status": r["status"], "progress_pct": round(min(1.0, saved / target), 4), "reached": saved >= target, "actual_monthly_contribution": money.s(actual_monthly),
           "basis": "saved = the amount you entered when creating the goal + transfers you linked to it. The monthly target is a plan, not money moved."}
    if saved >= target:
        out.update(estimated_completion=None, on_track=True, note="The target has been reached. You can mark the goal completed.")
        return out
    rate, label = (actual_monthly, "actual average of the last 90 days") if actual_monthly > 0 else (plan, "planned monthly target (not yet contributed)")
    est = None
    if rate > 0:
        months = -(-remaining // rate)
        est = money.add_months(money.today(), months).isoformat()
    out.update(estimated_completion=est, estimate_basis=label if rate > 0 else "no contributions or monthly plan to estimate from")
    if r["target_date"]:
        left = max(1, (date.fromisoformat(r["target_date"]) - money.today()).days)
        need = int(remaining / (left / 30.4375)) + 1
        out["required_monthly"] = money.s(need)
        out["on_track"] = bool(est) and est <= r["target_date"]
        out["days_left"] = (date.fromisoformat(r["target_date"]) - money.today()).days
    else:
        out["on_track"] = None
    return out


def create_goal(user: str, data: dict) -> dict:
    name = (data.get("name") or "").strip()[:80]
    if not name:
        raise FinanceError("The goal needs a name.")
    target = _amt(data.get("target"), "Target amount")
    try:
        saved = money.to_minor(data.get("saved", "0") or "0")
        monthly = money.to_minor(data["monthly_target"]) if data.get("monthly_target") not in (None, "") else None
    except money.MoneyError as e:
        raise FinanceError(str(e))
    td = _date(data["target_date"], "Target date") if data.get("target_date") else None
    prio = int(data.get("priority", 2))
    if prio not in (1, 2, 3):
        raise FinanceError("Priority must be 1 (high), 2 or 3 (low).")
    if data.get("account_id"):
        books.get_account(user, data["account_id"])
    gid, now = new_id("goal"), store.now()
    store._write("INSERT INTO fin_goals (id, username, name, description, target_minor, saved_minor, currency, target_date, priority, monthly_minor, account_id, status, created, updated) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?,?,'active',?,?)",
                 (gid, user, name, (data.get("description") or None) and data["description"][:300], target, saved, books.base_currency(user), td, prio, monthly,
                  data.get("account_id") or None, now, now))
    books._audit(user, "fin_goal_created", {"id": gid, "target_minor": target})
    return get_goal(user, gid)


def get_goal(user: str, gid: str) -> dict:
    r = _one("SELECT * FROM fin_goals WHERE id=? AND username=?", (gid, user))
    if not r:
        raise FinanceError("No such goal.", 404)
    return _goal_out(r)


def list_goals(user: str) -> list[dict]:
    return [_goal_out(r) for r in _q("SELECT * FROM fin_goals WHERE username=? ORDER BY status='completed', priority, created", (user,))]


def update_goal(user: str, gid: str, patch: dict) -> dict:
    r = _one("SELECT * FROM fin_goals WHERE id=? AND username=?", (gid, user))
    if not r:
        raise FinanceError("No such goal.", 404)
    status = patch.get("status", r["status"])
    if status not in ("active", "paused", "completed"):
        raise FinanceError("Status must be active, paused or completed.")
    target = _amt(patch["target"], "Target amount") if "target" in patch else r["target_minor"]
    saved = money.to_minor(patch["saved"]) if "saved" in patch else r["saved_minor"]
    monthly = (money.to_minor(patch["monthly_target"]) if patch["monthly_target"] not in (None, "") else None) if "monthly_target" in patch else r["monthly_minor"]
    td = (_date(patch["target_date"], "Target date") if patch["target_date"] else None) if "target_date" in patch else r["target_date"]
    prio = int(patch.get("priority", r["priority"]))
    if prio not in (1, 2, 3):
        raise FinanceError("Priority must be 1, 2 or 3.")
    store._write("UPDATE fin_goals SET name=?, description=?, target_minor=?, saved_minor=?, target_date=?, priority=?, monthly_minor=?, status=?, updated=? WHERE id=? AND username=?",
                 ((patch.get("name") or r["name"])[:80], patch.get("description", r["description"]), target, saved, td, prio, monthly, status, store.now(), gid, user))
    books._audit(user, "fin_goal_updated", {"id": gid, "fields": sorted(patch)})
    return get_goal(user, gid)


def delete_goal(user: str, gid: str) -> dict:
    get_goal(user, gid)
    store._write("UPDATE fin_transactions SET goal_id=NULL WHERE goal_id=? AND username=?", (gid, user))
    store._write("DELETE FROM fin_goals WHERE id=? AND username=?", (gid, user))
    books._audit(user, "fin_goal_deleted", {"id": gid})
    return {"deleted": gid}


def _next(d: date, rec: str) -> Optional[date]:
    if rec == "weekly":
        return d + timedelta(days=7)
    if rec == "monthly":
        return money.add_months(d, 1)
    if rec == "yearly":
        return money.add_months(d, 12)
    return None


def _obl_out(r, today: Optional[date] = None) -> dict:
    today = today or money.today()
    due = date.fromisoformat(r["next_due"])
    paid = _one("SELECT * FROM fin_obligation_payments WHERE obligation_id=? AND due_date=?", (r["id"], r["next_due"]))
    if not r["active"]:
        status = "cancelled"
    elif paid:
        status = "paid" if paid["status"] == "paid" else "skipped"
    elif due < today:
        status = "overdue"
    elif (due - today).days <= r["reminder_days"]:
        status = "due"
    else:
        status = "planned"
    last = _one("SELECT * FROM fin_obligation_payments WHERE obligation_id=? ORDER BY due_date DESC LIMIT 1", (r["id"],))
    return {"id": r["id"], "name": r["name"], "kind": r["kind"], "category": r["category"], "amount": money.s(r["amount_minor"]), "currency": r["currency"],
            "recurrence": r["recurrence"], "next_due": r["next_due"], "days_until_due": (due - today).days, "reminder_days": r["reminder_days"],
            "account_id": r["account_id"], "active": bool(r["active"]), "status": status,
            "last_payment": None if not last else {"due_date": last["due_date"], "status": last["status"], "txn_id": last["txn_id"], "amount": money.s(last["amount_minor"])}}


def create_obligation(user: str, data: dict) -> dict:
    name = (data.get("name") or "").strip()[:80]
    if not name:
        raise FinanceError("The bill needs a name.")
    rec = data.get("recurrence", "monthly")
    if rec not in RECURRENCES:
        raise FinanceError("Recurrence must be one of: " + ", ".join(RECURRENCES) + ".")
    cat = data.get("category") or None
    if cat and cat not in taxonomy.EXPENSE:
        raise FinanceError("Unknown category.")
    if data.get("account_id"):
        books.get_account(user, data["account_id"])
    try:
        reminder = int(data.get("reminder_days", 3))
    except (TypeError, ValueError):
        raise FinanceError("Reminder days must be a whole number.")
    if not 0 <= reminder <= 60:
        raise FinanceError("Reminder days must be between 0 and 60.")
    oid, now = new_id("obl"), store.now()
    store._write("INSERT INTO fin_obligations (id, username, name, kind, category, amount_minor, currency, recurrence, next_due, reminder_days, account_id, active, created, updated) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
                 (oid, user, name, (data.get("kind") or "bill")[:20], cat, _amt(data.get("amount"), "Amount"), books.base_currency(user), rec,
                  _date(data.get("next_due"), "Due date"), reminder, data.get("account_id") or None, now, now))
    books._audit(user, "fin_obligation_created", {"id": oid})
    return get_obligation(user, oid)


def get_obligation(user: str, oid: str) -> dict:
    r = _one("SELECT * FROM fin_obligations WHERE id=? AND username=?", (oid, user))
    if not r:
        raise FinanceError("No such bill.", 404)
    return _obl_out(r)


def list_obligations(user: str, include_inactive: bool = True) -> list[dict]:
    rows = _q("SELECT * FROM fin_obligations WHERE username=? ORDER BY active DESC, next_due", (user,))
    return [_obl_out(r) for r in rows if include_inactive or r["active"]]


def update_obligation(user: str, oid: str, patch: dict) -> dict:
    r = _one("SELECT * FROM fin_obligations WHERE id=? AND username=?", (oid, user))
    if not r:
        raise FinanceError("No such bill.", 404)
    amount = _amt(patch["amount"], "Amount") if "amount" in patch else r["amount_minor"]
    nd = _date(patch["next_due"], "Due date") if "next_due" in patch else r["next_due"]
    rec = patch.get("recurrence", r["recurrence"])
    if rec not in RECURRENCES:
        raise FinanceError("Unknown recurrence.")
    store._write("UPDATE fin_obligations SET name=?, amount_minor=?, next_due=?, recurrence=?, reminder_days=?, active=?, updated=? WHERE id=? AND username=?",
                 ((patch.get("name") or r["name"])[:80], amount, nd, rec, int(patch.get("reminder_days", r["reminder_days"])),
                  1 if patch.get("active", bool(r["active"])) else 0, store.now(), oid, user))
    books._audit(user, "fin_obligation_updated", {"id": oid, "fields": sorted(patch)})
    return get_obligation(user, oid)


def delete_obligation(user: str, oid: str) -> dict:
    get_obligation(user, oid)
    store._write("DELETE FROM fin_obligation_payments WHERE obligation_id=?", (oid,))
    store._write("UPDATE fin_transactions SET obligation_id=NULL WHERE obligation_id=? AND username=?", (oid, user))
    store._write("DELETE FROM fin_obligations WHERE id=? AND username=?", (oid, user))
    books._audit(user, "fin_obligation_deleted", {"id": oid})
    return {"deleted": oid}


def _advance(user: str, r, paid_due: str) -> None:
    nxt = _next(date.fromisoformat(paid_due), r["recurrence"])
    if nxt is None:
        store._write("UPDATE fin_obligations SET active=0, updated=? WHERE id=?", (store.now(), r["id"]))
    else:
        store._write("UPDATE fin_obligations SET next_due=?, updated=? WHERE id=?", (nxt.isoformat(), store.now(), r["id"]))


def pay_obligation(user: str, oid: str, *, account_id: Optional[str] = None, amount=None, ts: Optional[str] = None, source: str = "manual") -> dict:
    r = _one("SELECT * FROM fin_obligations WHERE id=? AND username=?", (oid, user))
    if not r or not r["active"]:
        raise FinanceError("No such active bill.", 404)
    due = r["next_due"]
    prior = _one("SELECT * FROM fin_obligation_payments WHERE obligation_id=? AND due_date=?", (oid, due))
    if prior and prior["status"] == "paid":
        return {"obligation": get_obligation(user, oid), "transaction": books.get_transaction(user, prior["txn_id"], include_void=True), "duplicate": True}
    acc = account_id or r["account_id"]
    if not acc:
        raise FinanceError("Choose the account the payment was made from.")
    final = _amt(amount, "Amount") if amount not in (None, "") else r["amount_minor"]
    txn = books.create_transaction(user, {"type": "expense", "account_id": acc, "amount": money.s(final), "category": r["category"] or "utilities",
                                          "merchant": r["name"], "purpose": f"{r['name']} due {due}", "recurring": r["recurrence"] != "once",
                                          "obligation_id": oid, "ts": ts, "essential": True if (r["category"] in (None, "utilities", "housing", "education", "health", "debt")) else None},
                                   source=source, idempotency_key=f"obl:{oid}:{due}")
    store._write("INSERT OR IGNORE INTO fin_obligation_payments (id, obligation_id, due_date, txn_id, status, amount_minor, created) VALUES (?,?,?,?,?,?,?)",
                 (new_id("pay"), oid, due, txn["id"], "paid", final, store.now()))
    _advance(user, r, due)
    books._audit(user, "fin_obligation_paid", {"id": oid, "due": due, "txn": txn["id"]})
    return {"obligation": get_obligation(user, oid), "transaction": txn, "duplicate": bool(txn.get("duplicate"))}


def skip_obligation(user: str, oid: str) -> dict:
    r = _one("SELECT * FROM fin_obligations WHERE id=? AND username=?", (oid, user))
    if not r or not r["active"]:
        raise FinanceError("No such active bill.", 404)
    store._write("INSERT OR IGNORE INTO fin_obligation_payments (id, obligation_id, due_date, txn_id, status, amount_minor, created) VALUES (?,?,?,NULL,'skipped',NULL,?)",
                 (new_id("pay"), oid, r["next_due"], store.now()))
    _advance(user, r, r["next_due"])
    return get_obligation(user, oid)


def upcoming(user: str, days: int = 30) -> list[dict]:
    today = money.today()
    horizon = today + timedelta(days=days)
    out = []
    for r in _q("SELECT * FROM fin_obligations WHERE username=? AND active=1", (user,)):
        o = _obl_out(r, today)
        d = date.fromisoformat(r["next_due"])
        first = True
        while d <= horizon:
            out.append({"id": r["id"], "name": r["name"], "amount": o["amount"], "due": d.isoformat(), "days_until_due": (d - today).days,
                        "status": o["status"] if first else "planned", "recurrence": r["recurrence"], "currency": r["currency"]})
            first = False
            nxt = _next(d, r["recurrence"])
            if nxt is None:
                break
            d = nxt
    return sorted(out, key=lambda x: x["due"])


def alerts(user: str) -> list[dict]:
    out = []
    for b in list_budgets(user):
        if not b["active"]:
            continue
        if b["status"] == "over":
            out.append({"kind": "budget_over", "severity": "high", "title": f"{b['name']} is over budget",
                        "body": f"{money.fmt(b['spent_minor'], b['currency'])} spent of {money.fmt(money.to_minor(b['limit']), b['currency'])}.", "ref": b["id"],
                        "key": f"budget_over:{b['id']}:{b['window']['start']}"})
        elif b["status"] == "warning":
            out.append({"kind": "budget_warning", "severity": "medium", "title": f"{b['name']} is at {round(b['utilization'] * 100)}%",
                        "body": f"{b['remaining']} {b['currency']} left with {_days(b['days_left'])} to go.", "ref": b["id"],
                        "key": f"budget_warning:{b['id']}:{b['window']['start']}"})
        elif b["projected_over"]:
            out.append({"kind": "budget_projected", "severity": "low", "title": f"{b['name']} may run over",
                        "body": f"At the current pace you would spend about {b['projected_total']} {b['currency']} against a limit of {b['limit']}.", "ref": b["id"],
                        "key": f"budget_projected:{b['id']}:{b['window']['start']}"})
    for o in list_obligations(user, include_inactive=False):
        if o["status"] == "overdue":
            out.append({"kind": "bill_overdue", "severity": "high", "title": f"{o['name']} is overdue", "body": f"{o['amount']} {o['currency']} was due {o['next_due']}.", "ref": o["id"], "key": f"bill_overdue:{o['id']}:{o['next_due']}"})
        elif o["status"] == "due":
            out.append({"kind": "bill_due", "severity": "medium", "title": f"{o['name']} is due soon", "body": f"{o['amount']} {o['currency']} due {o['next_due']} (in {_days(o['days_until_due'])}).", "ref": o["id"], "key": f"bill_due:{o['id']}:{o['next_due']}"})
    for g in list_goals(user):
        if g["status"] == "active" and g.get("on_track") is False:
            out.append({"kind": "goal_off_track", "severity": "low", "title": f"{g['name']} is behind schedule",
                        "body": f"Needs about {g['required_monthly']} {g['currency']} a month to reach {g['target']} by {g['target_date']}.", "ref": g["id"], "key": f"goal_off_track:{g['id']}:{money.today().strftime('%Y-%m')}"})
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda a: order[a["severity"]])


def forecast(user: str, reductions: Optional[dict] = None) -> dict:
    today = money.today()
    m_start, m_end = money.month_bounds(today)
    days_left = (m_end - today).days
    base = books.base_currency(user)
    pos = books.position(user)
    liquid = pos["liquid_minor"]
    window_start = today - timedelta(days=30)
    cur = analytics.summary(user, window_start, today)
    r = _one("SELECT COALESCE(SUM(final_minor),0) AS n FROM fin_transactions WHERE username=? AND type='expense' AND deleted_at IS NULL AND currency=? AND obligation_id IS NULL AND ts>=? AND ts<=?",
             (user, base, window_start.isoformat() + "T00:00:00", money.iso(money.now())))
    variable_30 = r["n"]
    by_day = [d["minor"] for d in cur["daily"]]
    avg_daily = variable_30 // 30
    reductions = reductions or {}
    saved_by_scenario = 0
    if reductions:
        rows = _q("SELECT category, COALESCE(SUM(final_minor),0) AS n FROM fin_transactions WHERE username=? AND type='expense' AND deleted_at IS NULL AND currency=? AND obligation_id IS NULL AND ts>=? AND ts<=? GROUP BY category",
                  (user, base, window_start.isoformat() + "T00:00:00", money.iso(money.now())))
        for row in rows:
            pct = float(reductions.get(row["category"], 0) or 0)
            if 0 < pct <= 100:
                saved_by_scenario += int(row["n"] / 30 * days_left * pct / 100)
    expected_variable = avg_daily * days_left - saved_by_scenario
    bills = [b for b in upcoming(user, days_left) if b["status"] in ("overdue", "due", "planned") and b["due"] <= m_end.isoformat() and b["currency"] == base]
    bills_total = sum(money.to_minor(b["amount"]) for b in bills)
    projected = liquid - expected_variable - bills_total
    sd = statistics.pstdev(by_day) if len(by_day) > 2 else 0
    band = int(sd * (days_left ** 0.5))
    budgets = [b for b in list_budgets(user) if b["active"] and b["period"] == "monthly"]
    return {
        "currency": base, "as_of": today.isoformat(), "month_end": m_end.isoformat(), "days_left": days_left,
        "current_liquid": money.s(liquid), "expected_variable_spending": money.s(expected_variable), "upcoming_bills": money.s(bills_total),
        "bills": [{"name": b["name"], "due": b["due"], "amount": b["amount"], "status": b["status"]} for b in bills],
        "projected_end_balance": money.s(projected), "projected_end_balance_minor": projected,
        "range_low": money.s(projected - band), "range_high": money.s(projected + band),
        "scenario": {"reductions_pct": reductions, "estimated_saving": money.s(saved_by_scenario)} if reductions else None,
        "budget_projections": [{"name": b["name"], "limit": b["limit"], "projected_total": b["projected_total"], "projected_over": b["projected_over"] or b["status"] == "over"} for b in budgets],
        "kind": "forecast", "is_estimate": True,
        "assumptions": ["Daily spending continues at the average of the last 30 days, excluding bills you track separately.",
                        "Listed bills are paid on their due dates.", "No income is assumed: only income you have recorded is in the balance.",
                        "The range is one standard deviation of your daily spending over the remaining days, not a guarantee."],
        "data_quality": {"accounts": len(pos["accounts"]), "days_with_spending": sum(1 for d in by_day if d > 0)},
    }
