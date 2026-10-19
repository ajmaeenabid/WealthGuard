"""HTTP API for the personal-finance module (/api/fin/*). Every route is scoped to the signed-in account.

Amounts travel as strings ("850.00"), never floats. The model never touches the database: the assistant route calls the
same validated services the manual forms use.
"""
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from app import accounts as auth
import logging
import sqlite3

from app.finance import ai, analytics, assistant, books, exchange, fx, jurisdictions, money, planning, privacy, receipts, reports, settings, taxonomy
from app.finance.books import FinanceError

router = APIRouter(prefix="/api/fin")
log = logging.getLogger("wealthguard.finance")
ASSISTANT_PER_MINUTE = 30
# (max requests, window in seconds) per user. Writes and imports are generous but bounded; AI reports cost money, so they are scarcer.
LIMITS = {"assistant": (ASSISTANT_PER_MINUTE, 60), "write": (120, 60), "import": (6, 60), "report": (12, 3600), "erase": (3, 3600)}
_HITS: dict = defaultdict(deque)


def _user(request: Request) -> str:
    u = request.state.user
    if u is None:
        if auth.auth_required():
            raise HTTPException(401, "Sign in required.")
        return "local"
    if u["role"] == "admin":
        raise HTTPException(403, "Administrators manage accounts; they do not have personal finance data.")
    return u["username"]


def _call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except FinanceError as e:
        raise HTTPException(e.status, e.message)
    except money.MoneyError as e:
        raise HTTPException(400, str(e))
    except sqlite3.Error:
        log.exception("finance database error")           # the details stay in the server log, never in the response
        raise HTTPException(500, "Something went wrong while saving. Nothing was changed; please try again.")


def _limit(user: str, bucket: str) -> None:
    mx, window = LIMITS[bucket]
    now = time.monotonic()
    q = _HITS[(user, bucket)]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= mx:
        raise HTTPException(429, "Too many requests. Please wait a moment and try again.")
    q.append(now)


# ---------------------------------------------------------------------------------------------- request models
Amount = Optional[str]


class AccountIn(BaseModel):
    name: str = Field(max_length=60)
    type: str = Field(max_length=20)
    opening_balance: Optional[str] = Field("0", max_length=30)
    opening_date: Optional[str] = Field(None, max_length=10)
    currency: Optional[str] = Field(None, max_length=3)


class AccountPatch(BaseModel):
    name: Optional[str] = Field(None, max_length=60)
    opening_balance: Optional[str] = Field(None, max_length=30)
    opening_date: Optional[str] = Field(None, max_length=10)
    archived: Optional[bool] = None
    currency: Optional[str] = Field(None, max_length=3)


class RelabelIn(BaseModel):
    currency: str = Field(max_length=3)
    also_total_currency: bool = True


class ReconcileIn(BaseModel):
    actual: str = Field(max_length=30)
    apply: bool = False


class ItemIn(BaseModel):
    name: str = Field(max_length=80)
    quantity: Optional[str] = Field(None, max_length=20)
    unit_price: Amount = Field(None, max_length=30)
    amount: Amount = Field(None, max_length=30)


class TxnIn(BaseModel):
    type: str = Field(max_length=12)
    account_id: str = Field(max_length=40)
    to_account_id: Optional[str] = Field(None, max_length=40)
    ts: Optional[str] = Field(None, max_length=30)
    amount: Amount = Field(None, max_length=30)
    gross_amount: Amount = Field(None, max_length=30)
    final_amount: Amount = Field(None, max_length=30)
    discount: Amount = Field(None, max_length=30)
    tax: Amount = Field(None, max_length=30)
    service_charge: Amount = Field(None, max_length=30)
    direction: Optional[str] = Field(None, max_length=3)
    merchant: Optional[str] = Field(None, max_length=80)
    item_name: Optional[str] = Field(None, max_length=120)
    quantity: Optional[str] = Field(None, max_length=20)
    unit_price: Amount = Field(None, max_length=30)
    category: Optional[str] = Field(None, max_length=30)
    subcategory: Optional[str] = Field(None, max_length=40)
    payment_method: Optional[str] = Field(None, max_length=30)
    purpose: Optional[str] = Field(None, max_length=120)
    essential: Optional[bool] = None
    recurring: Optional[bool] = None
    refund_of: Optional[str] = Field(None, max_length=40)
    goal_id: Optional[str] = Field(None, max_length=40)
    tags: Optional[list[str]] = None
    note: Optional[str] = Field(None, max_length=600)
    items: Optional[list[ItemIn]] = None
    idempotency_key: Optional[str] = Field(None, max_length=80)
    currency: Optional[str] = Field(None, max_length=3)
    convert: Optional[bool] = None            # the amounts are in `currency`: convert them to the account's currency at today's exchange rate


class TxnPatch(TxnIn):
    type: Optional[str] = Field(None, max_length=12)
    account_id: Optional[str] = Field(None, max_length=40)


class BudgetIn(BaseModel):
    name: Optional[str] = Field(None, max_length=60)
    category: Optional[str] = Field(None, max_length=30)
    period: str = Field("monthly", max_length=10)
    limit: str = Field(max_length=30)
    start_date: Optional[str] = Field(None, max_length=10)
    end_date: Optional[str] = Field(None, max_length=10)
    alert_pct: int = 80


class BudgetPatch(BaseModel):
    name: Optional[str] = Field(None, max_length=60)
    limit: Optional[str] = Field(None, max_length=30)
    alert_pct: Optional[int] = None
    active: Optional[bool] = None


class GoalIn(BaseModel):
    name: str = Field(max_length=80)
    description: Optional[str] = Field(None, max_length=300)
    target: str = Field(max_length=30)
    saved: Optional[str] = Field("0", max_length=30)
    target_date: Optional[str] = Field(None, max_length=10)
    priority: int = 2
    monthly_target: Optional[str] = Field(None, max_length=30)
    account_id: Optional[str] = Field(None, max_length=40)


class GoalPatch(BaseModel):
    name: Optional[str] = Field(None, max_length=80)
    description: Optional[str] = Field(None, max_length=300)
    target: Optional[str] = Field(None, max_length=30)
    saved: Optional[str] = Field(None, max_length=30)
    target_date: Optional[str] = Field(None, max_length=10)
    priority: Optional[int] = None
    monthly_target: Optional[str] = Field(None, max_length=30)
    status: Optional[str] = Field(None, max_length=10)


class ObligationIn(BaseModel):
    name: str = Field(max_length=80)
    kind: Optional[str] = Field("bill", max_length=20)
    category: Optional[str] = Field(None, max_length=30)
    amount: str = Field(max_length=30)
    recurrence: str = Field("monthly", max_length=10)
    next_due: str = Field(max_length=10)
    reminder_days: int = 3
    account_id: Optional[str] = Field(None, max_length=40)


class ObligationPatch(BaseModel):
    name: Optional[str] = Field(None, max_length=80)
    amount: Optional[str] = Field(None, max_length=30)
    recurrence: Optional[str] = Field(None, max_length=10)
    next_due: Optional[str] = Field(None, max_length=10)
    reminder_days: Optional[int] = None
    active: Optional[bool] = None


class PayIn(BaseModel):
    account_id: Optional[str] = Field(None, max_length=40)
    amount: Amount = Field(None, max_length=30)
    ts: Optional[str] = Field(None, max_length=30)


class SettingsIn(BaseModel):
    base_currency: Optional[str] = Field(None, max_length=3)
    ai_reports: Optional[bool] = None
    assistant_lang: Optional[str] = Field(None, max_length=4)
    ask_adjustments: Optional[str] = Field(None, max_length=8)
    voice_replies: Optional[bool] = None
    history_days: Optional[int] = None
    ui_lang: Optional[str] = Field(None, max_length=2)
    jurisdiction: Optional[str] = Field(None, max_length=2)
    voice_enabled: Optional[bool] = None
    speech_lang: Optional[str] = Field(None, max_length=4)
    large_text: Optional[bool] = None
    primary_account_id: Optional[str] = Field(None, max_length=40)


class EraseIn(BaseModel):
    confirm: str = Field(max_length=60)


class ReportIn(BaseModel):
    kind: str = Field("month", max_length=10)
    ref: Optional[str] = Field(None, max_length=10)
    start: Optional[str] = Field(None, max_length=10)
    end: Optional[str] = Field(None, max_length=10)
    ai: Optional[bool] = None            # None: use the account's AI preference
    lang: Optional[str] = Field(None, pattern="^(en|bn)$")       # None: the account's assistant language (English when "auto")


class ChatIn(BaseModel):
    text: str = Field(max_length=assistant.MAX_TEXT)
    request_id: str = Field(max_length=80)
    source: str = Field("text", max_length=10)
    lang: Optional[str] = Field(None, max_length=2)


class ImportIn(BaseModel):
    csv: str
    account_id: Optional[str] = Field(None, max_length=40)


def _dump(model: BaseModel) -> dict:
    return model.model_dump(exclude_none=True)


# ---------------------------------------------------------------------------------------------- meta
@router.get("/meta")
def meta(request: Request):
    u = _user(request)
    pref = settings.get(u)
    return {"currencies": pref["currencies"], "currency_chosen": pref["currency_chosen"], "jurisdiction": pref["jurisdiction_config"], "jurisdictions": {c: jurisdictions.summary(c) for c in jurisdictions.codes()},
            "currency": books.base_currency(u), "expense_categories": {c: taxonomy.subcategories(c) for c in taxonomy.categories("expense")},
            "income_categories": taxonomy.categories("income"), "account_types": taxonomy.ACCOUNT_TYPES, "payment_methods": taxonomy.PAYMENT_METHODS,
            "transaction_types": list(books.TYPES), "ai": {"enabled": ai.enabled(), "model": ai.model_name() if ai.enabled() else None},
            "assistant_languages": ["en", "bn"], "ui_languages": list(settings.UI_LANGS)}


@router.get("/ai-usage")
def ai_usage(request: Request, days: int = Query(30, ge=1, le=365)):
    return ai.usage_summary(_user(request), days)


# ---------------------------------------------------------------------------------------------- accounts
@router.get("/accounts")
def get_accounts(request: Request, include_archived: bool = False):
    return _call(books.list_accounts, _user(request), include_archived)


@router.post("/accounts")
def post_account(body: AccountIn, request: Request):
    return _call(books.create_account, _user(request), body.name, body.type, body.opening_balance, body.opening_date, body.currency)


@router.post("/accounts/{account_id}")
def patch_account(account_id: str, body: AccountPatch, request: Request):
    return _call(books.update_account, _user(request), account_id, _dump(body))


@router.post("/accounts/{account_id}/reconcile")
def reconcile(account_id: str, body: ReconcileIn, request: Request):
    return _call(books.reconcile, _user(request), account_id, body.actual, None, body.apply)


@router.get("/position")
def position(request: Request):
    return _call(books.position, _user(request))


# ---------------------------------------------------------------------------------------------- transactions
@router.get("/transactions")
def list_txns(request: Request, start: Optional[str] = None, end: Optional[str] = None, type: Optional[str] = None, category: Optional[str] = None,
              merchant: Optional[str] = None, account_id: Optional[str] = None, payment_method: Optional[str] = None, q: Optional[str] = Query(None, max_length=100),
              min_amount: Optional[str] = None, max_amount: Optional[str] = None, recurring: Optional[bool] = None,
              sort: str = Query("ts", pattern="^(ts|amount|merchant|category)$"), direction: str = Query("desc", pattern="^(asc|desc)$"),
              page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=books.MAX_PAGE)):
    return _call(books.list_transactions, _user(request), start=start, end=end, type=type, category=category, merchant=merchant, account_id=account_id,
                 payment_method=payment_method, q=q, min_amount=min_amount, max_amount=max_amount, sort=sort, direction=direction, page=page, size=size, recurring=recurring)


@router.post("/transactions")
def create_txn(body: TxnIn, request: Request):
    _limit(_user(request), "write")
    data = _dump(body)
    key = data.pop("idempotency_key", None)
    if "items" in data:
        data["items"] = [i for i in data["items"]]
    return _call(books.create_transaction, _user(request), data, source="manual", idempotency_key=key)


@router.get("/transactions/{txn_id}")
def get_txn(txn_id: str, request: Request):
    return _call(books.get_transaction, _user(request), txn_id)


@router.post("/transactions/{txn_id}")
def update_txn(txn_id: str, body: TxnPatch, request: Request):
    return _call(books.update_transaction, _user(request), txn_id, _dump(body))


@router.post("/transactions/{txn_id}/delete")
def delete_txn(txn_id: str, request: Request):
    return _call(books.void_transaction, _user(request), txn_id)


# ---------------------------------------------------------------------------------------------- receipt photos
@router.post("/transactions/{txn_id}/receipt")
async def upload_receipt(txn_id: str, request: Request):
    """Raw image bytes in the body (JPEG, PNG or WebP). The type is decided by the bytes, not by the header or file name."""
    u = _user(request)
    _limit(u, "write")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > receipts.MAX_BYTES + 1024:
        raise HTTPException(413, "The photo is too large.")
    data = await request.body()
    return await run_in_threadpool(_call, receipts.attach, u, txn_id, data, request.headers.get("content-type"))


@router.get("/transactions/{txn_id}/receipt")
def view_receipt(txn_id: str, request: Request):
    mime, data = _call(receipts.get, _user(request), txn_id)
    return Response(data, media_type=mime, headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox",
                                                    "Cache-Control": "private, no-store", "Content-Disposition": f'inline; filename="receipt.{receipts.TYPES[mime]}"'})


@router.post("/transactions/{txn_id}/receipt/delete")
def delete_receipt(txn_id: str, request: Request):
    return _call(receipts.remove, _user(request), txn_id)


# ---------------------------------------------------------------------------------------------- planning
@router.get("/budgets")
def get_budgets(request: Request):
    return _call(planning.list_budgets, _user(request))


@router.post("/budgets")
def post_budget(body: BudgetIn, request: Request):
    return _call(planning.create_budget, _user(request), _dump(body))


@router.post("/budgets/{bid}")
def patch_budget(bid: str, body: BudgetPatch, request: Request):
    return _call(planning.update_budget, _user(request), bid, _dump(body))


@router.post("/budgets/{bid}/delete")
def delete_budget(bid: str, request: Request):
    return _call(planning.delete_budget, _user(request), bid)


@router.get("/goals")
def get_goals(request: Request):
    return _call(planning.list_goals, _user(request))


@router.post("/goals")
def post_goal(body: GoalIn, request: Request):
    return _call(planning.create_goal, _user(request), _dump(body))


@router.post("/goals/{gid}")
def patch_goal(gid: str, body: GoalPatch, request: Request):
    return _call(planning.update_goal, _user(request), gid, _dump(body))


@router.post("/goals/{gid}/delete")
def delete_goal(gid: str, request: Request):
    return _call(planning.delete_goal, _user(request), gid)


@router.get("/obligations")
def get_obligations(request: Request):
    return _call(planning.list_obligations, _user(request))


@router.post("/obligations")
def post_obligation(body: ObligationIn, request: Request):
    return _call(planning.create_obligation, _user(request), _dump(body))


@router.post("/obligations/{oid}")
def patch_obligation(oid: str, body: ObligationPatch, request: Request):
    return _call(planning.update_obligation, _user(request), oid, _dump(body))


@router.post("/obligations/{oid}/delete")
def delete_obligation(oid: str, request: Request):
    return _call(planning.delete_obligation, _user(request), oid)


@router.post("/obligations/{oid}/pay")
def pay_obligation(oid: str, body: PayIn, request: Request):
    return _call(planning.pay_obligation, _user(request), oid, account_id=body.account_id, amount=body.amount, ts=body.ts)


@router.post("/obligations/{oid}/skip")
def skip_obligation(oid: str, request: Request):
    return _call(planning.skip_obligation, _user(request), oid)


@router.get("/upcoming")
def upcoming(request: Request, days: int = Query(30, ge=1, le=365)):
    return _call(planning.upcoming, _user(request), days)


@router.get("/alerts")
def get_alerts(request: Request):
    return _call(planning.alerts, _user(request))


@router.get("/activity")
def activity(request: Request, limit: int = Query(50, ge=1, le=200)):
    """This account's own finance actions from the tamper-evident audit log (ids and amounts, never names or notes)."""
    from app.security import audit
    u = _user(request)
    rows = [e for e in audit.list_entries(None) if isinstance(e.get("payload"), dict) and e["payload"].get("user") == u]
    return {"entries": [{"ts": e["ts"], "action": e["action"], "detail": {k: v for k, v in e["payload"].items() if k != "user"}} for e in rows[-limit:][::-1]],
            "chain": audit.verify()}


@router.get("/forecast")
def get_forecast(request: Request, reduce: Optional[str] = Query(None, max_length=200, description="category:percent,category:percent")):
    reductions = {}
    for part in (reduce or "").split(","):
        if ":" in part:
            k, _, v = part.partition(":")
            try:
                reductions[k.strip()] = float(v)
            except ValueError:
                raise HTTPException(400, "Use reduce=food:10,shopping:20")
    return _call(planning.forecast, _user(request), reductions)


# ---------------------------------------------------------------------------------------------- dashboard
@router.get("/dashboard")
def dashboard(request: Request, kind: str = Query("month", pattern="^(day|week|month|year|custom)$"), ref: Optional[str] = None,
              start: Optional[str] = None, end: Optional[str] = None):
    u = _user(request)

    def build():
        s, e = analytics.period(kind, ref, start, end)
        cur = analytics.summary(u, s, e)
        ps, pe = analytics.previous(s, e, kind)
        prev = analytics.summary(u, ps, pe)
        recent = books.list_transactions(u, size=8)["items"]
        goals = planning.list_goals(u)
        return {"period": {"kind": kind, "start": s.isoformat(), "end": e.isoformat()}, "summary": cur, "comparison": analytics.compare(cur, prev),
                "position": books.position(u), "budgets": [b for b in planning.list_budgets(u) if b["active"]], "goals": [g for g in goals if g["status"] != "completed"],
                "upcoming": planning.upcoming(u, 30)[:8], "alerts": planning.alerts(u), "insights": analytics.insights(u, s, e, cur=cur, prev=prev),
                "forecast": planning.forecast(u), "recent": recent, "subscriptions": analytics.detect_subscriptions(u)}
    return _call(build)


# ---------------------------------------------------------------------------------------------- reports and files
@router.post("/reports")
def make_report(body: ReportIn, request: Request):
    u = _user(request)
    pref = settings.get(u)
    use_ai = pref["ai_reports"] if body.ai is None else body.ai
    lang = body.lang or (pref["assistant_lang"] if pref["assistant_lang"] in ("en", "bn") else "en")
    if use_ai:
        _limit(u, "report")
    return _call(reports.generate, u, body.kind, body.ref, body.start, body.end, use_ai, lang)


@router.get("/reports")
def get_reports(request: Request):
    return reports.list_reports(_user(request))


@router.get("/reports/{rid}")
def get_report(rid: str, request: Request):
    return _call(reports.get, _user(request), rid)


@router.get("/reports/{rid}/export")
def export_report(rid: str, request: Request, format: str = Query("md", pattern="^(md|json)$")):
    rep = _call(reports.get, _user(request), rid)
    if format == "json":
        import json
        return Response(json.dumps(rep, ensure_ascii=False, indent=2), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{rid}.json"'})
    return PlainTextResponse(reports.to_markdown(rep), headers={"Content-Disposition": f'attachment; filename="{rid}.md"'})


@router.get("/export/transactions.csv")
def export_csv(request: Request, start: Optional[str] = None, end: Optional[str] = None):
    text = _call(exchange.export_csv, _user(request), start, end)
    return PlainTextResponse(text, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="transactions.csv"'})


@router.post("/import/transactions")
def import_csv(body: ImportIn, request: Request):
    u = _user(request)
    _limit(u, "import")
    return _call(exchange.import_csv, u, body.csv, body.account_id)


# ---------------------------------------------------------------------------------------------- preferences and privacy
@router.post("/currency/apply-to-all")
def relabel_all(body: RelabelIn, request: Request):
    u = _user(request)
    def run():
        out = books.relabel_currency(u, body.currency)
        if body.also_total_currency:
            books.set_base_currency(u, body.currency)
        return out
    return _call(run)


@router.post("/accounts/{account_id}/primary")
def make_primary(account_id: str, request: Request):
    return _call(books.set_primary_account, _user(request), account_id)


@router.get("/fx")
def fx_summary(request: Request):
    _user(request)
    return fx.summary()


@router.post("/fx/refresh")
def fx_refresh(request: Request):
    u = _user(request)
    _limit(u, "report")
    try:
        fx.refresh()
    except fx.FxError:
        pass
    return fx.summary()


@router.get("/fx/convert")
def fx_convert(amount: str, request: Request, frm: str = Query(..., alias="from", max_length=3), to: str = Query(..., max_length=3)):
    _user(request)
    try:
        return fx.convert_amount(amount, frm, to)
    except fx.FxError as e:
        raise HTTPException(503, e.message)
    except money.MoneyError as e:
        raise HTTPException(400, str(e))


@router.get("/version")
def data_version(request: Request):
    return _call(settings.data_version, _user(request))


@router.get("/settings")
def get_settings(request: Request):
    return _call(settings.get, _user(request))


@router.post("/settings")
def post_settings(body: SettingsIn, request: Request):
    return _call(settings.update, _user(request), _dump(body))


@router.post("/privacy/clear-history")
def clear_history(request: Request):
    return _call(privacy.clear_assistant_history, _user(request))


@router.post("/privacy/erase")
def erase(body: EraseIn, request: Request):
    u = _user(request)
    _limit(u, "erase")
    return _call(privacy.erase_all, u, body.confirm)


# ---------------------------------------------------------------------------------------------- the assistant
@router.post("/assistant/chat")
def assistant_chat(body: ChatIn, request: Request):
    u = _user(request)
    if body.source not in ("text", "voice"):
        raise HTTPException(400, "source must be text or voice")
    _limit(u, "assistant")
    return _call(assistant.turn, u, body.text, body.request_id, source=body.source, lang=body.lang)


@router.get("/assistant/session")
def assistant_session(request: Request):
    return _call(assistant.current, _user(request))


@router.get("/conversations")
def conversations(request: Request):
    return _call(assistant.list_sessions, _user(request))


@router.get("/conversations/{sid}")
def conversation_messages(sid: str, request: Request):
    return _call(lambda: {"id": sid, "messages": assistant.messages(_user(request), sid)})


@router.post("/conversations/{sid}/resume")
def conversation_resume(sid: str, request: Request):
    return _call(assistant.resume, _user(request), sid)


@router.post("/assistant/cancel")
def assistant_cancel(request: Request):
    return _call(assistant.cancel_session, _user(request))
