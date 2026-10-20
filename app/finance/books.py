"""The ledger: accounts and transactions. One validation path for manual entry, the assistant, imports and obligations."""
import json
import sqlite3
import uuid
from typing import Optional

from app import db, store
from app.finance import fx, money, taxonomy
from app.finance.money import MoneyError
from app.security import audit

TYPES = ("expense", "income", "refund", "transfer", "adjustment")
SOURCES = ("voice", "text", "manual", "import", "assistant")
MAX_NOTE = 500
MAX_PAGE = 200


class FinanceError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _q(sql: str, params: tuple = ()) -> list:
    c = db.connect()
    try:
        return c.execute(sql, params).fetchall()
    finally:
        c.close()


def _one(sql: str, params: tuple = ()):
    r = _q(sql, params)
    return r[0] if r else None


def _audit(user: str, action: str, payload: dict) -> None:
    audit.append("client", action, "T1", dict(payload, user=user))


def currency_chosen(user: str) -> bool:
    r = _one("SELECT currency_set FROM fin_settings WHERE username=?", (user,))
    if r and r["currency_set"]:
        return True
    if _one("SELECT 1 FROM fin_accounts WHERE username=?", (user,)):
        store._write("UPDATE fin_settings SET currency_set=1 WHERE username=?", (user,))
        return True
    return False


def base_currency(user: str) -> str:
    r = _one("SELECT base_currency, jurisdiction FROM fin_settings WHERE username=?", (user,))
    if not r:
        store._write("INSERT OR IGNORE INTO fin_settings (username, base_currency, created) VALUES (?,?,?)", (user, money.DEFAULT_CURRENCY, store.now()))
        r = _one("SELECT base_currency, jurisdiction FROM fin_settings WHERE username=?", (user,))
    if currency_chosen(user):
        return r["base_currency"]
    from app.finance import jurisdictions
    return jurisdictions.currency(r["jurisdiction"])


def primary_account(user: str) -> Optional[dict]:
    base_currency(user)
    r = _one("SELECT primary_account_id FROM fin_settings WHERE username=?", (user,))
    if not r or not r["primary_account_id"]:
        return None
    a = _one("SELECT * FROM fin_accounts WHERE id=? AND username=? AND archived=0", (r["primary_account_id"], user))
    return None if a is None else _account_out(a)


def set_primary_account(user: str, account_id: Optional[str]) -> Optional[dict]:
    base_currency(user)
    if account_id:
        a = get_account(user, account_id)
        if a["archived"]:
            raise FinanceError("An archived account cannot be the primary account.")
    store._write("UPDATE fin_settings SET primary_account_id=? WHERE username=?", (account_id or None, user))
    _audit(user, "fin_primary_account_set", {"account": account_id})
    return primary_account(user)


def valid_currency(currency: Optional[str]) -> str:
    c = (currency or "").strip().upper()
    if c not in money.CURRENCIES:
        raise FinanceError("Choose one of: " + ", ".join(money.CURRENCIES) + ".")
    return c


def set_base_currency(user: str, currency: str) -> str:
    currency = valid_currency(currency)
    base_currency(user)
    store._write("UPDATE fin_settings SET base_currency=?, currency_set=1 WHERE username=?", (currency, user))
    _audit(user, "fin_currency_set", {"currency": currency})
    return currency


def _account_out(r, balance: Optional[int] = None) -> dict:
    d = {"id": r["id"], "name": r["name"], "type": r["type"], "currency": r["currency"], "opening_balance": money.s(r["opening_minor"]),
         "opening_date": r["opening_date"], "archived": bool(r["archived"]), "liability": r["type"] in taxonomy.LIABILITY_TYPES,
         "created": r["created"], "updated": r["updated"]}
    if balance is not None:
        d["balance"] = money.s(balance)
        d["balance_minor"] = balance
    return d


def get_account(user: str, account_id: str):
    r = _one("SELECT * FROM fin_accounts WHERE id=? AND username=?", (account_id, user)) if account_id else None
    if r is None:
        raise FinanceError("No such account.", 404)
    return r


def create_account(user: str, name: str, type: str, opening="0", opening_date=None, currency: Optional[str] = None) -> dict:
    name = (name or "").strip()[:60]
    if not name:
        raise FinanceError("The account needs a name.")
    if type not in taxonomy.ACCOUNT_TYPES:
        raise FinanceError("Account type must be one of: " + ", ".join(taxonomy.ACCOUNT_TYPES) + ".")
    cur = valid_currency(currency) if currency else base_currency(user)
    if not currency_chosen(user):
        set_base_currency(user, cur)
    try:
        opening_minor = money.to_minor(opening or "0", allow_negative=True)
        odate = (money.parse_ts(opening_date)[:10] if opening_date else money.today().isoformat())
    except MoneyError as e:
        raise FinanceError(str(e))
    if type not in taxonomy.LIABILITY_TYPES and opening_minor < 0:
        raise FinanceError("Only a credit card or loan can start with a negative balance.")
    if type in taxonomy.LIABILITY_TYPES and opening_minor > 0:
        opening_minor = -opening_minor
    aid, now = new_id("acc"), store.now()
    try:
        store._write("INSERT INTO fin_accounts (id, username, name, type, currency, opening_minor, opening_date, archived, created, updated) "
                     "VALUES (?,?,?,?,?,?,?,0,?,?)", (aid, user, name, type, cur, opening_minor, odate, now, now))
    except sqlite3.IntegrityError:
        raise FinanceError("You already have an account with that name.", 409)
    _audit(user, "fin_account_created", {"account": aid, "type": type})
    return _account_out(get_account(user, aid), opening_minor)


def relabel_currency(user: str, currency: str, account_id: Optional[str] = None) -> dict:
    currency = valid_currency(currency)
    accts = _q("SELECT id, name, currency FROM fin_accounts WHERE username=?", (user,))
    if account_id:
        target = next((a for a in accts if a["id"] == account_id), None)
        if not target:
            raise FinanceError("No such account.", 404)
        ids = {account_id}
        others = {a["id"]: a["currency"] for a in accts if a["id"] != account_id}
        linked = _q("SELECT account_id, to_account_id FROM fin_transactions WHERE username=? AND type='transfer' AND deleted_at IS NULL AND (account_id=? OR to_account_id=?)", (user, account_id, account_id))
        for t in linked:
            partner = t["to_account_id"] if t["account_id"] == account_id else t["account_id"]
            if partner and others.get(partner) not in (None, currency):
                raise FinanceError(f"'{target['name']}' has transfers with an account in {others[partner]}. Change both accounts together (Settings > Currency > apply to all accounts).", 409)
    else:
        ids = {a["id"] for a in accts}
    n_acc = n_txn = 0
    with db.LOCK:
        c = db.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            marks = ",".join("?" * len(ids)) or "''"
            n_acc = c.execute(f"UPDATE fin_accounts SET currency=?, updated=? WHERE username=? AND id IN ({marks})", (currency, store.now(), user, *ids)).rowcount
            n_txn = c.execute(f"UPDATE fin_transactions SET currency=? WHERE username=? AND (account_id IN ({marks}) OR to_account_id IN ({marks}))", (currency, user, *ids, *ids)).rowcount
            if not account_id:
                for table in ("fin_budgets", "fin_goals", "fin_obligations"):
                    c.execute(f"UPDATE {table} SET currency=? WHERE username=?", (currency, user))
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()
    _audit(user, "fin_currency_relabelled", {"currency": currency, "accounts": n_acc, "transactions": n_txn, "scope": "account" if account_id else "all"})
    return {"currency": currency, "accounts": n_acc, "transactions": n_txn}


def update_account(user: str, account_id: str, patch: dict) -> dict:
    r = get_account(user, account_id)
    name = (patch.get("name", r["name"]) or "").strip()[:60]
    if not name:
        raise FinanceError("The account needs a name.")
    if patch.get("currency") and valid_currency(patch["currency"]) != r["currency"]:
        relabel_currency(user, patch["currency"], account_id)
    try:
        opening = money.to_minor(patch["opening_balance"], allow_negative=True) if "opening_balance" in patch else r["opening_minor"]
        odate = money.parse_ts(patch["opening_date"])[:10] if patch.get("opening_date") else r["opening_date"]
    except MoneyError as e:
        raise FinanceError(str(e))
    archived = 1 if patch.get("archived", bool(r["archived"])) else 0
    try:
        store._write("UPDATE fin_accounts SET name=?, opening_minor=?, opening_date=?, archived=?, updated=? WHERE id=? AND username=?",
                     (name, opening, odate, archived, store.now(), account_id, user))
    except sqlite3.IntegrityError:
        raise FinanceError("You already have an account with that name.", 409)
    _audit(user, "fin_account_updated", {"account": account_id, "fields": sorted(patch)})
    return list_accounts(user, include_archived=True, only=account_id)[0]


def balances(user: str, as_of: Optional[str] = None) -> dict[str, int]:
    as_of = as_of or money.iso(money.now())
    accounts = _q("SELECT id, opening_minor, opening_date FROM fin_accounts WHERE username=?", (user,))
    out = {a["id"]: (a["opening_minor"] if a["opening_date"] <= as_of[:10] else 0) for a in accounts}
    moves = _q("""SELECT account_id AS acc, SUM(CASE type WHEN 'income' THEN final_minor WHEN 'refund' THEN final_minor
                  WHEN 'expense' THEN -final_minor WHEN 'transfer' THEN -final_minor
                  WHEN 'adjustment' THEN CASE direction WHEN 'in' THEN final_minor ELSE -final_minor END END) AS d
                  FROM fin_transactions WHERE username=? AND deleted_at IS NULL AND ts<=? GROUP BY account_id
                  UNION ALL
                  SELECT to_account_id, SUM(COALESCE(to_final_minor, final_minor)) FROM fin_transactions
                  WHERE username=? AND deleted_at IS NULL AND ts<=? AND type='transfer' AND to_account_id IS NOT NULL
                  GROUP BY to_account_id""", (user, as_of, user, as_of))
    for m in moves:
        if m["acc"] in out:
            out[m["acc"]] += m["d"] or 0
    return out


def list_accounts(user: str, include_archived: bool = False, as_of: Optional[str] = None, only: Optional[str] = None) -> list[dict]:
    rows = _q("SELECT * FROM fin_accounts WHERE username=? ORDER BY archived, type, name", (user,))
    bal = balances(user, as_of)
    return [_account_out(r, bal.get(r["id"], 0)) for r in rows
            if (include_archived or not r["archived"]) and (only is None or r["id"] == only)]


def position(user: str, as_of: Optional[str] = None) -> dict:
    base = base_currency(user)
    accts = list_accounts(user, as_of=as_of)
    ins = [a for a in accts if a["currency"] == base]
    liquid = sum(a["balance_minor"] for a in ins if a["type"] in taxonomy.LIQUID_TYPES)
    by_type: dict = {}
    for a in ins:
        by_type[a["type"]] = by_type.get(a["type"], 0) + a["balance_minor"]
    liabilities = -sum(a["balance_minor"] for a in ins if a["liability"])
    net = sum(a["balance_minor"] for a in ins)
    converted = _converted_estimate(accts, base, liquid, net)
    return {"currency": base, "converted_estimate": converted, "as_of": as_of or money.iso(money.now()), "liquid": money.s(liquid), "liquid_minor": liquid,
            "cash": money.s(by_type.get("cash", 0)), "bank": money.s(by_type.get("bank", 0)), "wallet": money.s(by_type.get("wallet", 0)),
            "savings": money.s(by_type.get("savings", 0)), "investments": money.s(by_type.get("investment", 0)),
            "liabilities": money.s(liabilities), "net_worth": money.s(net), "net_worth_minor": net,
            "accounts": accts, "excluded_other_currency": [a["name"] for a in accts if a["currency"] != base],
            "basis": "actual: opening balances you entered plus recorded transactions up to now",
            "has_accounts": bool(accts)}


def _converted_estimate(accts: list, base: str, liquid: int, net: int) -> Optional[dict]:
    others = [a for a in accts if a["currency"] != base]
    if not others:
        return None
    fx.ensure_fresh_async()
    try:
        table = fx.current(allow_fetch=False)
    except fx.FxError:
        return {"available": False, "reason": "No exchange rate is available yet; it will appear here once one has been fetched."}
    rows, add_liquid, add_net = [], 0, 0
    for a in others:
        c, _ = fx.convert_minor(a["balance_minor"], a["currency"], base, table)
        rows.append({"id": a["id"], "name": a["name"], "currency": a["currency"], "balance": a["balance"], "converted": money.s(c)})
        add_net += c
        if a["type"] in taxonomy.LIQUID_TYPES:
            add_liquid += c
    r = fx.rate(others[0]["currency"], base, table)
    return {"available": True, "currency": base, "liquid": money.s(liquid + add_liquid), "net_worth": money.s(net + add_net), "accounts": rows,
            "source": r["source_name"], "provider_date": r["provider_date"], "stale": r["stale"], "age_hours": r["age_hours"],
            "note": "Estimate at an indicative mid-market rate; your own accounts and exact totals above are unchanged."}


def reconcile(user: str, account_id: str, actual, as_of: Optional[str] = None, apply: bool = False) -> dict:
    acct = get_account(user, account_id)
    try:
        actual_minor = money.to_minor(actual, allow_negative=True)
    except MoneyError as e:
        raise FinanceError(str(e))
    ledger = balances(user, as_of)[account_id]
    diff = actual_minor - ledger
    out = {"account": acct["name"], "ledger": money.s(ledger), "actual": money.s(actual_minor), "difference": money.s(diff), "applied": False}
    if apply and diff != 0:
        txn = create_transaction(user, {"type": "adjustment", "account_id": account_id, "direction": "in" if diff > 0 else "out",
                                        "amount": money.s(abs(diff)), "note": "Reconciliation adjustment", "ts": as_of or None}, source="manual")
        out.update(applied=True, adjustment_id=txn["id"])
    return out


def _tx_out(r, items: Optional[list] = None) -> dict:
    d = {"id": r["id"], "type": r["type"], "ts": r["ts"], "account_id": r["account_id"], "to_account_id": r["to_account_id"],
         "direction": r["direction"], "merchant": r["merchant"], "item_name": r["item_name"], "quantity": r["quantity"],
         "unit_price": money.s(r["unit_price_minor"]), "category": r["category"], "subcategory": r["subcategory"],
         "gross_amount": money.s(r["gross_minor"]), "discount": money.s(r["discount_minor"]), "tax": money.s(r["tax_minor"]),
         "service_charge": money.s(r["service_minor"]), "final_amount": money.s(r["final_minor"]), "final_minor": r["final_minor"],
         "currency": r["currency"], "payment_method": r["payment_method"], "purpose": r["purpose"],
         "essential": None if r["essential"] is None else bool(r["essential"]), "recurring": bool(r["recurring"]),
         "obligation_id": r["obligation_id"], "goal_id": r["goal_id"], "refund_of": r["refund_of"],
         "tags": json.loads(r["tags"] or "[]"), "note": r["note"], "receipt_ref": r["receipt_ref"], "source": r["source"],
         "confidence": r["confidence"], "confirmed": bool(r["confirmed"]), "created": r["created"], "updated": r["updated"],
         "original": _original(r), "to_amount": None if r["to_final_minor"] is None else money.s(r["to_final_minor"]),
         "has_receipt": bool(r["receipt_ref"]), "scheduled": r["ts"] > money.iso(money.now())}
    if items is not None:
        d["items"] = items
    return d


def _original(r) -> Optional[dict]:
    if not r["orig_currency"]:
        return None
    return {"currency": r["orig_currency"], "amount": money.s(r["orig_final_minor"]), "rate": r["fx_rate"], "source": r["fx_source"], "fetched": r["fx_ts"],
            "converted_to": r["currency"]}


def _items(txn_id: str) -> list[dict]:
    return [{"name": i["name"], "quantity": i["quantity"], "unit_price": money.s(i["unit_price_minor"]), "amount": money.s(i["amount_minor"])}
            for i in _q("SELECT * FROM fin_items WHERE txn_id=? ORDER BY id", (txn_id,))]


def get_transaction(user: str, txn_id: str, include_void: bool = False) -> dict:
    r = _one("SELECT * FROM fin_transactions WHERE id=? AND username=?", (txn_id, user))
    if r is None or (r["deleted_at"] and not include_void):
        raise FinanceError("No such transaction.", 404)
    return _tx_out(r, _items(txn_id))


def _amount(v, label: str, allow_none: bool = True) -> Optional[int]:
    if v is None or v == "":
        if allow_none:
            return None
        raise FinanceError(f"{label} is required.")
    try:
        return money.to_minor(v)
    except MoneyError as e:
        raise FinanceError(f"{label}: {e}")


def _quote(frm: str, to: str, pinned: Optional[dict] = None) -> dict:
    if pinned and pinned.get("from") == frm and pinned.get("to") == to and pinned.get("rate"):
        return pinned
    try:
        return fx.rate(frm, to)
    except fx.FxError as e:
        raise FinanceError(f"I cannot convert {frm} to {to} right now: {e.message} Enter the amount in {to} instead.", 503)


def _normalise(user: str, data: dict, source: str, existing=None) -> dict:
    g = lambda k, default=None: data.get(k, existing[k] if (existing is not None and k in existing.keys()) else default)
    typ = data.get("type", existing["type"] if existing is not None else None)
    if typ not in TYPES:
        raise FinanceError("Type must be one of: " + ", ".join(TYPES) + ".")
    ts = money.parse_ts(data["ts"]) if data.get("ts") else (existing["ts"] if existing is not None else money.iso(money.now()))
    acct = get_account(user, data.get("account_id", existing["account_id"] if existing is not None else None))
    if acct["archived"] and (existing is None or existing["account_id"] != acct["id"]):
        raise FinanceError(f"The account '{acct['name']}' is archived.")
    to_acct = None
    if typ == "transfer":
        to_id = data.get("to_account_id", existing["to_account_id"] if existing is not None else None)
        to_acct = get_account(user, to_id)
        if to_acct["id"] == acct["id"]:
            raise FinanceError("A transfer needs two different accounts.")
        if to_acct["currency"] != acct["currency"] and not data.get("convert"):
            raise FinanceError(f"'{acct['name']}' is in {acct['currency']} and '{to_acct['name']}' is in {to_acct['currency']}. "
                               "Record the transfer with currency conversion so each account receives its own currency at today's exchange rate.")
        if to_acct["archived"]:
            raise FinanceError(f"The account '{to_acct['name']}' is archived.")
    elif data.get("to_account_id"):
        raise FinanceError("Only a transfer has a destination account.")
    cur = acct["currency"]
    spoken = (data.get("currency") or "").upper() or None
    quote = None
    if spoken and spoken != cur:
        if not data.get("convert"):
            raise FinanceError(f"The account '{acct['name']}' uses {cur}; the transaction cannot be in {spoken} unless it is converted at today's exchange rate.")
        quote = _quote(spoken, cur, data.get("fx_quote"))

    if "amount" in data and "final_amount" not in data:
        data = dict(data, final_amount=data["amount"])
    conv = (lambda v: v) if quote is None else (lambda v: None if v is None else fx.convert_minor(v, spoken, cur, quote=quote)[0])
    discount = conv(_amount(data.get("discount", None if existing is None else money.s(existing["discount_minor"])), "Discount")) or 0
    tax = conv(_amount(data.get("tax", None if existing is None else money.s(existing["tax_minor"])), "Tax")) or 0
    service = conv(_amount(data.get("service_charge", None if existing is None else money.s(existing["service_minor"])), "Service charge")) or 0
    amount_keys = ("final_amount", "gross_amount", "amount")
    touched = any(k in data for k in amount_keys)
    final = _amount(data.get("final_amount"), "Final amount")
    gross = _amount(data.get("gross_amount"), "Gross amount")
    orig_final = None
    if quote is not None:
        if final is not None:
            orig_final = final
        elif gross is not None:
            orig_final = gross - (_amount(data.get("discount"), "Discount") or 0) + (_amount(data.get("tax"), "Tax") or 0) + (_amount(data.get("service_charge"), "Service charge") or 0)
        final, gross = conv(final), None if final is not None else conv(gross)
    if not touched and existing is not None:
        gross, final = existing["gross_minor"], existing["final_minor"]
        if any(k in data for k in ("discount", "tax", "service_charge")):
            final = gross - discount + tax + service
    if final is None and gross is None:
        raise FinanceError("An amount is required.")
    if typ not in ("expense", "refund") and (discount or tax or service):
        raise FinanceError("Discount, tax and service charge apply to expenses and refunds only.")
    if final is not None and gross is not None:
        if gross - discount + tax + service != final:
            raise FinanceError(f"The amounts do not add up: gross {money.s(gross)} - discount {money.s(discount)} + tax {money.s(tax)} "
                               f"+ service {money.s(service)} = {money.s(gross - discount + tax + service)}, not {money.s(final)}.")
    elif final is not None:
        gross = final + discount - tax - service
    else:
        final = gross - discount + tax + service
    if gross < 0 or discount > gross:
        raise FinanceError("The discount cannot be larger than the amount before discount.")
    if final <= 0:
        raise FinanceError("The final amount must be greater than zero.")

    direction = data.get("direction", existing["direction"] if existing is not None else None)
    if typ == "adjustment" and direction not in ("in", "out"):
        raise FinanceError("An adjustment needs a direction: in or out.")
    if typ != "adjustment":
        direction = None

    category, sub = g("category"), g("subcategory")
    if typ == "expense" and not category:
        category = "other"
    if typ == "income" and not category:
        category = "other income"
    if typ in ("transfer", "adjustment"):
        category, sub = None, None
    if typ == "expense" and category not in taxonomy.EXPENSE:
        raise FinanceError("Unknown category '%s'. Use one of: %s." % (category, ", ".join(taxonomy.EXPENSE)))
    if typ == "income" and category not in taxonomy.INCOME:
        raise FinanceError("Unknown income category '%s'. Use one of: %s." % (category, ", ".join(taxonomy.INCOME)))

    refund_of = data.get("refund_of", existing["refund_of"] if existing is not None else None)
    if typ == "refund" and refund_of:
        orig = _one("SELECT * FROM fin_transactions WHERE id=? AND username=? AND deleted_at IS NULL", (refund_of, user))
        if orig is None or orig["type"] != "expense":
            raise FinanceError("A refund must point to one of your recorded expenses.")
        done = _one("SELECT COALESCE(SUM(final_minor),0) AS n FROM fin_transactions WHERE refund_of=? AND username=? AND deleted_at IS NULL AND id<>?",
                    (refund_of, user, existing["id"] if existing is not None else ""))["n"]
        if done + final > orig["final_minor"]:
            raise FinanceError(f"Refunds would exceed the original payment of {money.s(orig['final_minor'])}.")
        category = category or orig["category"]
        sub = sub or orig["subcategory"]
        if orig["currency"] != cur:
            raise FinanceError("The refund must be in the same currency as the original expense.")
    elif typ != "refund":
        refund_of = None
    if typ == "refund" and not category:
        category = "other"

    goal_id = data.get("goal_id", existing["goal_id"] if existing is not None else None)
    if goal_id and not _one("SELECT 1 FROM fin_goals WHERE id=? AND username=?", (goal_id, user)):
        raise FinanceError("No such goal.", 404)

    essential = data.get("essential", existing["essential"] if existing is not None else None)
    if essential is None and typ == "expense":
        essential = taxonomy.default_essential(category, sub)
    tags = data.get("tags", json.loads(existing["tags"]) if existing is not None else [])
    if not isinstance(tags, list) or len(tags) > 20:
        raise FinanceError("Tags must be a list of at most 20 words.")
    tags = [str(t).strip()[:30] for t in tags if str(t).strip()]
    note = (g("note") or "")[:MAX_NOTE] or None
    if len(g("note") or "") > MAX_NOTE:
        raise FinanceError(f"The note is limited to {MAX_NOTE} characters.")
    conf = data.get("confidence", existing["confidence"] if existing is not None else None)
    if conf is not None and not (0 <= float(conf) <= 1):
        raise FinanceError("Confidence must be between 0 and 1.")
    unit_price = _amount(data.get("unit_price"), "Unit price") if "unit_price" in data else (existing["unit_price_minor"] if existing is not None else None)
    if quote is not None and unit_price is not None:
        unit_price = fx.convert_minor(unit_price, spoken, cur, quote=quote)[0]
    to_final = None
    if to_acct is not None and to_acct["currency"] != cur:
        to_quote = _quote(cur, to_acct["currency"], data.get("fx_transfer_quote"))
        to_final = fx.convert_minor(final, cur, to_acct["currency"], quote=to_quote)[0]
        if to_final <= 0:
            raise FinanceError("That amount is too small to convert.")
    elif existing is not None and not touched and existing["to_final_minor"] is not None and to_acct is not None:
        to_final = existing["to_final_minor"]
    if quote is not None:
        fxcols = {"orig_currency": spoken, "orig_final_minor": orig_final, "fx_rate": quote["rate"], "fx_source": f"{quote['source']}@{quote['provider_date']}", "fx_ts": quote["fetched"]}
    elif existing is not None and not touched:
        fxcols = {k: existing[k] for k in ("orig_currency", "orig_final_minor", "fx_rate", "fx_source", "fx_ts")}
    else:
        fxcols = {"orig_currency": None, "orig_final_minor": None, "fx_rate": None, "fx_source": None, "fx_ts": None}
    return {**fxcols, "to_final_minor": to_final, "type": typ, "ts": ts, "account_id": acct["id"], "to_account_id": to_acct["id"] if to_acct else None, "direction": direction,
            "merchant": (g("merchant") or None) and str(g("merchant")).strip()[:80], "item_name": (g("item_name") or None) and str(g("item_name")).strip()[:120],
            "quantity": None if g("quantity") in (None, "") else str(g("quantity"))[:20], "unit_price_minor": unit_price,
            "category": category, "subcategory": sub, "gross_minor": gross, "discount_minor": discount, "tax_minor": tax, "service_minor": service,
            "final_minor": final, "currency": cur, "payment_method": g("payment_method"), "purpose": (g("purpose") or None) and str(g("purpose"))[:120],
            "essential": None if essential is None else (1 if essential else 0), "recurring": 1 if g("recurring", False) else 0,
            "obligation_id": g("obligation_id"), "goal_id": goal_id, "refund_of": refund_of, "tags": json.dumps(tags, ensure_ascii=False),
            "note": note, "receipt_ref": g("receipt_ref"), "source": source if existing is None else existing["source"],
            "confidence": conf, "confirmed": 1 if g("confirmed", True) else 0}


COLS = ["orig_currency", "orig_final_minor", "fx_rate", "fx_source", "fx_ts", "to_final_minor", "type", "ts", "account_id", "to_account_id", "direction", "merchant", "item_name", "quantity", "unit_price_minor", "category",
        "subcategory", "gross_minor", "discount_minor", "tax_minor", "service_minor", "final_minor", "currency", "payment_method",
        "purpose", "essential", "recurring", "obligation_id", "goal_id", "refund_of", "tags", "note", "receipt_ref", "source",
        "confidence", "confirmed"]


def _save_items(c, txn_id: str, items) -> None:
    c.execute("DELETE FROM fin_items WHERE txn_id=?", (txn_id,))
    for it in (items or [])[:50]:
        name = str(it.get("name", "")).strip()[:80]
        if not name:
            continue
        c.execute("INSERT INTO fin_items (txn_id, name, quantity, unit_price_minor, amount_minor) VALUES (?,?,?,?,?)",
                  (txn_id, name, None if it.get("quantity") in (None, "") else str(it["quantity"])[:20],
                   _amount(it.get("unit_price"), "Item price"), _amount(it.get("amount"), "Item amount")))


def create_transaction(user: str, data: dict, *, source: str = "manual", idempotency_key: Optional[str] = None) -> dict:
    if source not in SOURCES:
        raise FinanceError("Unknown source.")
    key = idempotency_key or data.get("idempotency_key")
    if key:
        key = str(key)[:80]
        prior = _one("SELECT id FROM fin_transactions WHERE username=? AND idempotency_key=?", (user, key))
        if prior:
            return dict(get_transaction(user, prior["id"], include_void=True), duplicate=True)
    cols = _normalise(user, data, source)
    tid, now = new_id("txn"), store.now()
    with db.LOCK:
        c = db.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            c.execute(f"INSERT INTO fin_transactions (id, username, idempotency_key, created, updated, {', '.join(COLS)}) VALUES (?,?,?,?,?,{','.join('?' * len(COLS))})",
                      (tid, user, key, now, now, *[cols[k] for k in COLS]))
            _save_items(c, tid, data.get("items"))
            c.commit()
        except sqlite3.IntegrityError:
            c.rollback()
            prior = _one("SELECT id FROM fin_transactions WHERE username=? AND idempotency_key=?", (user, key)) if key else None
            if prior:
                return dict(get_transaction(user, prior["id"], include_void=True), duplicate=True)
            raise FinanceError("That transaction could not be saved because it breaks a data rule.")
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()
    _audit(user, "fin_txn_created", {"id": tid, "type": cols["type"], "final_minor": cols["final_minor"], "source": source})
    return get_transaction(user, tid)


def update_transaction(user: str, txn_id: str, patch: dict) -> dict:
    r = _one("SELECT * FROM fin_transactions WHERE id=? AND username=?", (txn_id, user))
    if r is None or r["deleted_at"]:
        raise FinanceError("No such transaction.", 404)
    if r["type"] != patch.get("type", r["type"]):
        raise FinanceError("The type of a recorded transaction cannot be changed. Delete it and add a new one.")
    cols = _normalise(user, dict(patch, type=r["type"]), r["source"], existing=r)
    with db.LOCK:
        c = db.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            c.execute(f"UPDATE fin_transactions SET {', '.join(k + '=?' for k in COLS)}, updated=? WHERE id=? AND username=?",
                      (*[cols[k] for k in COLS], store.now(), txn_id, user))
            if "items" in patch:
                _save_items(c, txn_id, patch["items"])
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()
    _audit(user, "fin_txn_updated", {"id": txn_id, "fields": sorted(k for k in patch if k != "type")})
    return get_transaction(user, txn_id)


def void_transaction(user: str, txn_id: str) -> dict:
    r = _one("SELECT * FROM fin_transactions WHERE id=? AND username=?", (txn_id, user))
    if r is None or r["deleted_at"]:
        raise FinanceError("No such transaction.", 404)
    if _one("SELECT 1 FROM fin_transactions WHERE refund_of=? AND username=? AND deleted_at IS NULL", (txn_id, user)):
        raise FinanceError("Delete the refunds of this expense first.", 409)
    now = store.now()
    with db.LOCK:
        c = db.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            c.execute("UPDATE fin_transactions SET deleted_at=?, updated=? WHERE id=? AND username=?", (now, now, txn_id, user))
            pay = c.execute("SELECT obligation_id, due_date FROM fin_obligation_payments WHERE txn_id=?", (txn_id,)).fetchone()
            if pay:
                c.execute("DELETE FROM fin_obligation_payments WHERE txn_id=?", (txn_id,))
                c.execute("UPDATE fin_obligations SET next_due=?, active=1 WHERE id=? AND username=?", (pay["due_date"], pay["obligation_id"], user))
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()
    _audit(user, "fin_txn_deleted", {"id": txn_id, "type": r["type"], "final_minor": r["final_minor"]})
    return {"deleted": txn_id}


def list_transactions(user: str, *, start: Optional[str] = None, end: Optional[str] = None, type: Optional[str] = None,
                      category: Optional[str] = None, merchant: Optional[str] = None, account_id: Optional[str] = None,
                      payment_method: Optional[str] = None, q: Optional[str] = None, min_amount=None, max_amount=None,
                      sort: str = "ts", direction: str = "desc", page: int = 1, size: int = 25, recurring: Optional[bool] = None) -> dict:
    where, args = ["username=?", "deleted_at IS NULL"], [user]
    def add(cond, *vals):
        where.append(cond); args.extend(vals)
    if start:
        add("ts>=?", money.parse_ts(start)[:10] + "T00:00:00")
    if end:
        add("ts<=?", money.parse_ts(end)[:10] + "T23:59:59")
    if type:
        add("type=?", type)
    if category:
        add("category=?", category)
    if merchant:
        add("merchant LIKE ?", f"%{merchant}%")
    if account_id:
        add("(account_id=? OR to_account_id=?)", account_id, account_id)
    if payment_method:
        add("payment_method=?", payment_method)
    if recurring is not None:
        add("recurring=?", 1 if recurring else 0)
    if q:
        like = f"%{q}%"
        add("(merchant LIKE ? OR item_name LIKE ? OR note LIKE ? OR tags LIKE ? OR category LIKE ? OR purpose LIKE ?)", *([like] * 6))
    if min_amount not in (None, ""):
        add("final_minor>=?", _amount(min_amount, "Minimum amount"))
    if max_amount not in (None, ""):
        add("final_minor<=?", _amount(max_amount, "Maximum amount"))
    col = {"ts": "ts", "amount": "final_minor", "merchant": "merchant", "category": "category"}.get(sort, "ts")
    order = "ASC" if str(direction).lower() == "asc" else "DESC"
    size = max(1, min(int(size), MAX_PAGE))
    page = max(1, int(page))
    sql = " AND ".join(where)
    total = _one(f"SELECT COUNT(*) AS n FROM fin_transactions WHERE {sql}", tuple(args))["n"]
    rows = _q(f"SELECT * FROM fin_transactions WHERE {sql} ORDER BY {col} {order}, created DESC LIMIT ? OFFSET ?", (*args, size, (page - 1) * size))
    return {"items": [_tx_out(r) for r in rows], "total": total, "page": page, "size": size, "pages": max(1, -(-total // size))}
