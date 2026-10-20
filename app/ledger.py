"""Purchase ledger: planned / bought / cancelled items, edited by typing or voice."""
import json
import re
from datetime import date, datetime, timezone
from typing import Optional

from app import db, store
from app.schemas import LedgerEntry
from app.security import audit

CATEGORIES = ["food", "transport", "shopping", "entertainment", "health", "housing", "education", "other"]
MAX_ENTRIES = 500

KEYWORDS = {
    "food": ["food", "grocer", "lunch", "dinner", "breakfast", "restaurant", "coffee", "meal", "snack", "吃", "餐",
             "饭", "咖啡", "外卖", "超市", "菜"],
    "transport": ["taxi", "uber", "bus", "metro", "subway", "train", "fuel", "petrol", "parking", "打车", "地铁",
                  "公交", "油费", "高铁", "停车"],
    "shopping": ["clothes", "shoes", "shirt", "laptop", "phone", "bag", "gadget", "shopping", "headphone", "衣服",
                 "鞋", "手机", "电脑", "包", "购物", "耳机"],
    "entertainment": ["movie", "game", "concert", "netflix", "trip", "travel", "hotel", "电影", "游戏", "旅行", "旅游",
                      "演唱会", "酒店"],
    "health": ["doctor", "medicine", "pharmacy", "gym", "hospital", "dental", "医院", "药", "健身", "体检"],
    "housing": ["rent", "electricity", "utilities", "mortgage", "furniture", "房租", "水电", "房贷", "家具", "物业"],
    "education": ["tuition", "course", "book", "school", "class", "textbook", "学费", "课程", "书", "培训", "补习"],
}
IMPULSE_WORDS = ["impulse", "on a whim", "spur of the moment", "冲动", "一时兴起"]

_NUM = r"[¥￥]?\s*(\d[\d,]*(?:\.\d+)?)\s*(?:yuan|rmb|cny|元|块|¥)?"
_ART = r"(?:a\s+|an\s+|the\s+|my\s+|some\s+)?"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def guess_category(text: str) -> str:
    t = text.lower()
    for cat, words in KEYWORDS.items():
        if any(w in t for w in words):
            return cat
    return "other"


def _row(r) -> LedgerEntry:
    d = dict(r)
    d["impulse"] = bool(d["impulse"])
    return LedgerEntry(**d)


def list_entries(client_id: str) -> list[LedgerEntry]:
    c = db.connect()
    rows = c.execute("SELECT * FROM ledger WHERE client_id=? ORDER BY ts DESC, rowid DESC", (client_id,)).fetchall()
    c.close()
    return [_row(r) for r in rows]


def get_entry(entry_id: str) -> Optional[LedgerEntry]:
    c = db.connect()
    r = c.execute("SELECT * FROM ledger WHERE id=?", (entry_id,)).fetchone()
    c.close()
    return _row(r) if r else None


def _save(e: LedgerEntry) -> None:
    with db.LOCK:
        c = db.connect()
        c.execute("INSERT OR REPLACE INTO ledger (id,client_id,ts,item,category,amount_cny,status,impulse,source,updated)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (e.id, e.client_id, e.ts, e.item, e.category, e.amount_cny, e.status, int(e.impulse), e.source,
                   e.updated))
        c.commit()
        c.close()


def add_entry(client_id: str, item: str, amount_cny: float, category: str = "other", status: str = "bought",
              impulse: bool = False, ts: Optional[str] = None, source: str = "typed", actor: str = "client") -> LedgerEntry:
    if len(list_entries(client_id)) >= MAX_ENTRIES:
        raise ValueError("ledger is full")
    e = LedgerEntry(id=store.new_id("buy"), client_id=client_id, ts=ts or date.today().isoformat(), item=item.strip(),
                    category=category, amount_cny=amount_cny, status=status, impulse=impulse, source=source,
                    updated=_now())
    _save(e)
    audit.append(actor, "ledger_add", "T1", {"entry_id": e.id, "status": e.status, "amount_cny": e.amount_cny,
                                             "category": e.category, "source": source}, client_id)
    return e


def update_entry(entry_id: str, client_id: str, actor: str = "client", **fields) -> LedgerEntry:
    e = get_entry(entry_id)
    if not e or e.client_id != client_id:
        raise PermissionError("entry not found for this client")
    data = e.model_dump()
    data.update({k: v for k, v in fields.items() if v is not None})
    data["updated"] = _now()
    new = LedgerEntry(**data)
    _save(new)
    audit.append(actor, "ledger_update", "T1", {"entry_id": entry_id, "changes": {k: v for k, v in fields.items()
                                                                                    if v is not None}}, client_id)
    return new


def delete_entry(entry_id: str, client_id: str, actor: str = "client") -> None:
    e = get_entry(entry_id)
    if not e or e.client_id != client_id:
        raise PermissionError("entry not found for this client")
    with db.LOCK:
        c = db.connect()
        c.execute("DELETE FROM ledger WHERE id=?", (entry_id,))
        c.commit()
        c.close()
    audit.append(actor, "ledger_delete", "T1", {"entry_id": entry_id, "item": e.item, "status": e.status}, client_id)


def _amount(text: str, last: bool = False) -> Optional[float]:
    nums = re.findall(_NUM, text, re.I)
    if not nums:
        return None
    try:
        v = float(nums[-1 if last else 0].replace(",", ""))
    except ValueError:
        return None
    return v if v > 0 else None


def _clean_item(s: str) -> str:
    s = re.sub(r"\b(on\s+(?:an\s+)?impulse|impulse|on\s+a\s+whim|spur\s+of\s+the\s+moment)\b|冲动|一时兴起", " ", s, flags=re.I)
    s = re.sub(_NUM, " ", s, flags=re.I)
    s = re.sub(r"\b(for|on|at|costing|cost|about|around|yuan|rmb|cny|please|today|yesterday|it|i|was|were)\b", " ", s,
               flags=re.I)
    s = re.sub(r"(花了|花费|大约|约|共|一共|预算|元|块|了|的|，|,|。|\.|！|!)", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .,;:-")
    s = re.sub(r"^(a|an|the|my|some)\s+", "", s, flags=re.I)
    return s[:80]


def find_entry(client_id: str, phrase: str, statuses: tuple = ("planned", "bought")) -> Optional[LedgerEntry]:
    p = phrase.lower().strip()
    if not p:
        return None
    for e in list_entries(client_id):
        name = e.item.lower()
        if e.status in statuses and (p in name or name in p):
            return e
    return None


def parse_command(client_id: str, text: str) -> dict:
    raw = text.strip()
    t = raw.lower()
    impulse = any(w in t for w in IMPULSE_WORDS)

    def fail(msg):
        return {"ok": False, "message": msg}

    m = re.search(r"\b(?:delete|remove|erase)\s+" + _ART + r"(.+)", t) or re.search(r"(?:删除|删掉|移除)(.+)", raw)
    if m:
        phrase = _clean_item(m.group(m.lastindex))
        e = find_entry(client_id, phrase, ("planned", "bought", "cancelled"))
        if not e:
            return fail(f"I could not find an entry matching '{phrase}'.")
        return _proposal(client_id, "delete", e, {}, f"Delete '{e.item}' ({e.status}, CNY {e.amount_cny:,.0f}) from your history.")

    m = (re.search(r"\b(?:cancel|didn'?t buy|did not buy|never bought|not buying|won'?t buy|skip)\s+" + _ART + r"(.+)", t)
         or re.search(r"(?:取消|没买|没有买|不买了|没有购买)(.+)", raw))
    if m:
        phrase = _clean_item(m.group(m.lastindex))
        e = find_entry(client_id, phrase)
        if not e:
            return fail(f"I could not find an entry matching '{phrase}'.")
        return _proposal(client_id, "update", e, {"status": "cancelled"},
                         f"Mark '{e.item}' as not bought (cancelled), so it no longer counts as spending.")

    m = (re.search(r"\b(?:change|set|update|make)\s+" + _ART + r"(.+?)\s+(?:to|as)\s+" + _NUM, t)
         or re.search(r"把(.+?)(?:改成|改为|调整为|修改为)\s*" + _NUM, raw))
    if m:
        phrase = _clean_item(m.group(1))
        amount = _amount(raw, last=True)
        e = find_entry(client_id, phrase, ("planned", "bought", "cancelled"))
        if not e or not amount:
            return fail("I could not tell which entry or which amount you mean.")
        return _proposal(client_id, "update", e, {"amount_cny": amount},
                         f"Change '{e.item}' from CNY {e.amount_cny:,.0f} to CNY {amount:,.0f}.")

    m = (re.search(r"\b(?:plan(?:ning)? to buy|want to buy|going to buy|will buy|thinking of buying|planned)\s+" + _ART + r"(.+)", t)
         or re.search(r"(?:计划买|计划购买|打算买|想买|准备买)(.+)", raw))
    if m:
        return _add(client_id, m.group(m.lastindex), raw, "planned", impulse)

    m = (re.search(r"\b(?:bought|purchased|paid for|got)\s+" + _ART + r"(.+)", t)
         or re.search(r"\bspent\s+" + _NUM + r"\s+(?:on|for)\s+" + _ART + r"(.+)", t)
         or re.search(r"(?:买了|购买了|购买|买)(.+)", raw) or re.search(r"花了.+?(?:买了|买|用于)(.+)", raw))
    if m:
        item_part = m.group(m.lastindex)
        return _add(client_id, item_part, raw, "bought", impulse)

    return fail("I did not understand. Try: 'I bought headphones for 300', 'plan to buy a laptop 6000', "
                "'cancel the laptop', 'change headphones to 250' or 'delete lunch'.")


def _add(client_id: str, item_part: str, raw: str, status: str, impulse: bool) -> dict:
    amount = _amount(raw)
    item = _clean_item(item_part)
    if not item or not amount:
        return {"ok": False, "message": "I need both an item and an amount, for example 'bought headphones for 300'."}
    if amount > 10_000_000:
        return {"ok": False, "message": "That amount is too large."}
    existing = find_entry(client_id, item, ("planned",)) if status == "bought" else None
    if existing:
        return _proposal(client_id, "update", existing, {"status": "bought", "amount_cny": amount},
                         f"Mark your planned '{existing.item}' as bought for CNY {amount:,.0f}.")
    cat = guess_category(raw)
    fields = {"item": item, "category": cat, "amount_cny": amount, "status": status, "impulse": impulse}
    return _proposal(client_id, "add", None, fields,
                     f"Add '{item}' ({cat}) for CNY {amount:,.0f} as {status}" + (", marked impulse" if impulse else "") + ".")


def _proposal(client_id: str, action: str, entry: Optional[LedgerEntry], fields: dict, summary: str) -> dict:
    p = {"id": store.new_id("chg"), "client_id": client_id, "action": action,
         "entry_id": entry.id if entry else None, "fields": fields, "summary": summary}
    with db.LOCK:
        c = db.connect()
        c.execute("INSERT INTO ledger_changes VALUES (?,?,?,?)", (p["id"], client_id, json.dumps(p), "pending"))
        c.commit()
        c.close()
    return {"ok": True, "proposal": p}


def pending_changes(client_id: str) -> list[dict]:
    c = db.connect()
    rows = c.execute("SELECT data FROM ledger_changes WHERE client_id=? AND status='pending'", (client_id,)).fetchall()
    c.close()
    return [json.loads(r["data"]) for r in rows]


def _set_change_status(change_id: str, status: str) -> None:
    with db.LOCK:
        c = db.connect()
        c.execute("UPDATE ledger_changes SET status=? WHERE id=?", (status, change_id))
        c.commit()
        c.close()


def _load_change(change_id: str, client_id: str) -> dict:
    c = db.connect()
    r = c.execute("SELECT data, status FROM ledger_changes WHERE id=?", (change_id,)).fetchone()
    c.close()
    if not r or json.loads(r["data"])["client_id"] != client_id or r["status"] != "pending":
        audit.append("client", "ledger_confirm_refused", "T2", {"change_id": change_id}, client_id)
        raise PermissionError("change not found, not yours, or already handled")
    return json.loads(r["data"])


def confirm(change_id: str, client_id: str, source: str = "typed") -> dict:
    p = _load_change(change_id, client_id)
    f = p["fields"]
    if p["action"] == "add":
        e = add_entry(client_id, f["item"], f["amount_cny"], f["category"], f["status"], f["impulse"], source=source)
        result = e.model_dump()
    elif p["action"] == "update":
        result = update_entry(p["entry_id"], client_id, **f).model_dump()
    else:
        delete_entry(p["entry_id"], client_id)
        result = {"deleted": p["entry_id"]}
    _set_change_status(change_id, "applied")
    audit.append("client", "ledger_confirm", "T2", {"change_id": change_id, "action": p["action"]}, client_id)
    return result


def reject(change_id: str, client_id: str) -> None:
    _load_change(change_id, client_id)
    _set_change_status(change_id, "rejected")
    audit.append("client", "ledger_reject", "T2", {"change_id": change_id}, client_id)


def load_sample(client_id: str, kind: str = "balanced") -> int:
    today = date.today()

    def month_day(back: int, day: int) -> str:
        y, m = today.year, today.month - back
        while m <= 0:
            m += 12
            y -= 1
        return date(y, m, min(day, 28)).isoformat()

    rows = []
    if kind == "heavy":
        for b in range(3):
            rows += [("Rent and utilities", "housing", 9000, "bought", False, month_day(b, 1)),
                     ("Dining out", "food", 5200, "bought", False, month_day(b, 6)),
                     ("Designer clothes", "shopping", 6800, "bought", True, month_day(b, 12)),
                     ("Gadgets", "shopping", 4500, "bought", True, month_day(b, 18)),
                     ("Weekend trip", "entertainment", 3800, "bought", True, month_day(b, 24))]
        rows += [("New phone", "shopping", 7500, "planned", False, month_day(0, 27))]
    else:
        for b in range(3):
            rows += [("Groceries", "food", 2400, "bought", False, month_day(b, 5)),
                     ("Transport card", "transport", 600, "bought", False, month_day(b, 8)),
                     ("Child tutoring", "education", 1800, "bought", False, month_day(b, 15)),
                     ("Streaming and games", "entertainment", 300, "bought", False, month_day(b, 20))]
        rows += [("Headphones", "shopping", 450, "bought", True, month_day(1, 22)),
                 ("Laptop", "shopping", 6000, "planned", False, month_day(0, 26)),
                 ("Tablet", "shopping", 3000, "cancelled", False, month_day(1, 10))]
    n = 0
    for item, cat, amt, status, imp, ts in rows:
        if len(list_entries(client_id)) >= MAX_ENTRIES:
            break
        e = LedgerEntry(id=store.new_id("buy"), client_id=client_id, ts=ts, item=item, category=cat, amount_cny=amt,
                        status=status, impulse=imp, source="sample", updated=_now())
        _save(e)
        n += 1
    audit.append("client", "ledger_sample_loaded", "T1", {"kind": kind, "entries": n}, client_id)
    return n
