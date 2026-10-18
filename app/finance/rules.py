"""Deterministic understanding of a spoken or typed money message (English, Bangla and Banglish).

This is the offline path (USE_MOCK_LLM=1, no API key, or the AI service down) and also the parser for short answers to a
clarifying question ("before the discount", "yes", "bkash"). It returns only what it can actually see in the text; anything
it cannot find is left out so the assistant asks for it instead of guessing.
"""
import re
from datetime import date, timedelta
from typing import Optional

from app.finance import taxonomy

BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
CUR = r"(?:taka|tk\.?|bdt|takas|৳|টাকা|টাকায়|rs\.?)"
NUM = r"(\d[\d,]*(?:\.\d+)?)"
UNITS = r"(?:kg|kgs|g|gm|gram|grams|l|ltr|litre|liter|liters|pcs?|pieces?|items?|dozen|packets?|packs?|bottles?|boxes|box|km|hours?|hrs?|days?|months?|weeks?|years?|people|persons?|টা|টি|কেজি|লিটার)"
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
WEEKDAYS = {"monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2, "thursday": 3, "thu": 3, "thurs": 3,
            "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6}

YES = re.compile(r"^\s*(yes|yep|yeah|y|ok|okay|sure|save( it)?|confirm(ed)?|correct|right|go ahead|do it|looks good|that'?s right|haan|ha|ji|হ্যাঁ|হ্যা|ঠিক আছে|ঠিক|সেভ( করো| কর)?|করো)\s*[.!]*\s*$", re.I)
NO = re.compile(r"^\s*(no|nope|nah|n|na|nothing|none|not really|না|নাহ|নেই|কিছু না)\s*[.!]*\s*$", re.I)
CANCEL = re.compile(r"^\s*(cancel( it| that| this)?|stop|never ?mind|forget it|discard|abort|বাদ( দাও)?|থাক|বাতিল)\s*[.!]*\s*$", re.I)
SKIP = re.compile(r"^\s*(skip|save it|no note|without( a)? note|just save|save without( a)? note|leave it|none|no|nothing|না|বাদ)\s*[.!]*\s*$", re.I)

EXPENSE_WORDS = r"spent|spend|bought|buy|paid|pay|purchased|purchase|cost me|costs me|ordered|got .{0,20} for|khoroch|খরচ|কিনলাম|কিনেছি|দিলাম|দিয়েছি|কিনেছিলাম|korlam|kinlam|dilam|disi"
INCOME_WORDS = r"received|earned|got paid|salary|got a salary|income|was paid|payment received|bonus|পেলাম|পেয়েছি|আয়|বেতন|paisi|peyechi|peyechhi"
REFUND_WORDS = r"refund(ed)?|money back|returned the|ফেরত"
TRANSFER_WORDS = r"transfer(red)?|moved .{0,30} to|sent .{0,30} to (my )?(savings|bank|bkash|cash)|put .{0,30} (in|into) (my )?savings|deposit(ed)?"


def ascii_digits(text: str) -> str:
    return (text or "").translate(BN_DIGITS)


def is_bangla(text: str) -> bool:
    return bool(re.search(r"[ঀ-৿]", text or ""))


def _num(s: str) -> str:
    return s.replace(",", "")


# ---------------------------------------------------------------------------------------------- dates
def parse_date(text: str, today: date) -> Optional[date]:
    t = ascii_digits(text).lower()
    if re.search(r"\b(today|just now|this morning|this afternoon|this evening|tonight|aj|ajke|ajk)\b|আজ|এইমাত্র", t):
        return today
    if re.search(r"day before yesterday|পরশু", t):
        return today - timedelta(days=2)
    if re.search(r"\b(yesterday|last night|gotokal|gotoikal|kal)\b|গতকাল|কাল", t):
        return today - timedelta(days=1)
    m = re.search(r"\b(\d{1,2}) days? ago\b", t)
    if m:
        return today - timedelta(days=int(m.group(1)))
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else today.year
        y += 2000 if y < 100 else 0
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", t) or \
        re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?\b", t)
    if m:
        a, b = m.group(1), m.group(2)
        day_, mon = (int(a), MONTHS[b[:3]]) if a.isdigit() else (int(b), MONTHS[a[:3]])
        try:
            d = date(today.year, mon, day_)
            return d if d <= today else date(today.year - 1, mon, day_)
        except ValueError:
            return None
    m = re.search(r"\b(?:on |last )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tues?|wed|thu(?:rs)?|fri|sat|sun)\b", t)
    if m:
        wd = WEEKDAYS[m.group(1)]
        back = (today.weekday() - wd) % 7 or 7
        return today - timedelta(days=back)
    return None


# ---------------------------------------------------------------------------------------------- amounts
def _spans(text: str):
    return [(m.start(), m.end(), _num(m.group(1))) for m in re.finditer(NUM, text)]


def amounts(text: str) -> dict:
    """Find the main amount and any discount / VAT / service charge in the text."""
    t = ascii_digits(text)
    low = t.lower()
    out: dict = {}
    claimed = set()
    for key, words in (("discount", r"discount|off|rebate|ছাড়|ডিসকাউন্ট"), ("tax", r"vat|tax|ভ্যাট|ট্যাক্স"),
                       ("service_charge", r"service charge|service fee|service|সার্ভিস")):
        for sp in _spans(low):
            s, e, v = sp
            before = low[max(0, s - 26):s]
            after = low[e:e + 24]
            if re.search(rf"(?:{words})\s*(?:of|was|is|:|=|-)?\s*(?:{CUR})?\s*$", before) or re.search(rf"^\s*(?:{CUR})?\s*(?:{words})", after):
                if sp not in claimed and key not in out:
                    out[key] = v
                    claimed.add(sp)
    if re.search(r"\b(no|without|zero)\s+(discount|offer)\b|ছাড় নেই|ডিসকাউন্ট নেই", low):
        out["no_discount"] = True
    if re.search(r"\b(no|without|zero)\s+(vat|tax|service( charge)?|extra( charges?)?)\b|ভ্যাট নেই|কোনো চার্জ নেই", low):
        out["no_tax"] = True
    main = None
    for sp in _spans(low):
        if sp in claimed:
            continue
        s, e, v = sp
        after = low[e:e + 14]
        before = low[max(0, s - 12):s]
        if re.match(rf"\s*{UNITS}\b", after) and not re.match(rf"\s*{CUR}", after):
            continue                                                       # a quantity, not money
        if re.match(r"\s*(?:st|nd|rd|th)?\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", after) or re.search(r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*$", before):
            continue                                                       # part of a date
        if re.match(r"\s*(?:days? ago|[/-]\d)", after) or re.search(r"\d[/-]$", before):
            continue
        cued = re.match(rf"\s*{CUR}", after) or re.search(rf"{CUR}\s*$", before) or re.search(r"(spent|paid|cost|for|received|got|earned|worth|total|of|bill|price|খরচ)\s*$", before)
        if cued:
            main = v
            break
        if main is None:
            main = v
    if main:
        out["amount"] = main
    return out


def amount_basis(text: str) -> Optional[str]:
    t = ascii_digits(text).lower()
    if re.search(r"before (the )?(discount|vat|tax|offer)|original (price|amount)|mrp|list price|ছাড়ের আগে|ডিসকাউন্টের আগে", t):
        return "before_discount"
    if re.search(r"after (the )?(discount|vat|tax|offer)|final( amount| price| total)?|net|amount paid|i paid|actually paid|total paid|ছাড়ের পর|ডিসকাউন্টের পর|পরিশোধ", t):
        return "final"
    return None


# ---------------------------------------------------------------------------------------------- the rest of the draft
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" ,.;:!?")


def merchant_of(text: str) -> Optional[str]:
    t = ascii_digits(text)
    m = re.search(r"\b(?:at|from|in|@)\s+(?:the\s+|a\s+|my\s+)?((?:[A-Z][\w&'.-]*)(?:\s+[A-Z][\w&'.-]*){0,3})(?=[\s,.!?]|$)", t)
    if m and m.group(1).lower() not in ("today", "yesterday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "cash", "bkash", "nagad"):
        return _clean(m.group(1))
    m = re.search(r"\b(?:at|from|in)\s+(?:the\s+|a\s+|my\s+)?([a-z]+(?:\s[a-z]+)?\s+(?:store|shop|market|mart|bazar|bazaar|restaurant|cafe|pharmacy|mall|supermarket|super shop|salon|clinic|hospital))\b", t, re.I)
    if m:
        return _clean(m.group(1))
    return None


def items_of(text: str) -> Optional[str]:
    t = ascii_digits(text)
    m = re.search(r"\b(?:on|for|buying|bought|buy|purchasing|ordered)\s+([a-zA-Z][a-zA-Z ,&'-]{2,80}?)(?=\s+(?:today|yesterday|at|from|with|using|by|via|in|on|for)\b|[.!?]|$)", t)
    if not m:
        return None
    val = _clean(re.sub(r"\b(some|the|a|an)\b", "", m.group(1)))
    return val or None


def note_of(text: str) -> Optional[str]:
    m = re.search(r"(?:note|memo|remark)\s*[:\-]\s*(.+)$", text, re.I) or re.search(r"(?:add|with)\s+(?:a\s+)?note\s+(?:saying\s+|that\s+)?['\"]?(.+?)['\"]?$", text, re.I)
    return _clean(m.group(1))[:300] if m else None


def classify_type(text: str) -> Optional[str]:
    t = ascii_digits(text).lower()
    if re.search(REFUND_WORDS, t):
        return "refund"
    if re.search(TRANSFER_WORDS, t):
        return "transfer"
    if re.search(INCOME_WORDS, t):
        return "income"
    if re.search(EXPENSE_WORDS, t):
        return "expense"
    return None


QUERY = re.compile(r"how much|total|spent on|spending|what('?s| is) my (balance|spending|budget|net worth)|my balance|balance|show (me )?(my )?|list (my )?|budget|goals?|report|summary|summari[sz]e|how am i doing|overview|net worth|কত খরচ|কত টাকা|ব্যালেন্স|কত আছে|হিসাব", re.I)
DELETE = re.compile(r"\b(delete|remove|undo|erase)\b.{0,30}\b(last|latest|previous|that|this|transactions?|expenses?|entry|entries|records?|payments?|purchases?)\b|মুছে|ডিলিট", re.I)
UPDATE = re.compile(r"\b(change|edit|update|correct|fix|make it|set it|actually|oops|that should be|should have been|it was)\b|ঠিক করো|বদলাও|পরিবর্তন", re.I)


def period_of(text: str, today: date) -> tuple[Optional[str], Optional[str], Optional[str]]:
    t = ascii_digits(text).lower()
    if re.search(r"today|আজ", t):
        return "day", today.isoformat(), today.isoformat()
    if re.search(r"yesterday|গতকাল", t):
        y = today - timedelta(days=1)
        return "day", y.isoformat(), y.isoformat()
    if re.search(r"last week|previous week|গত সপ্তাহ", t):
        s = today - timedelta(days=today.weekday() + 7)
        return "week", s.isoformat(), (s + timedelta(days=6)).isoformat()
    if re.search(r"this week|এই সপ্তাহ", t):
        s = today - timedelta(days=today.weekday())
        return "week", s.isoformat(), (s + timedelta(days=6)).isoformat()
    if re.search(r"last month|previous month|গত মাস", t):
        first = today.replace(day=1) - timedelta(days=1)
        return "month", first.replace(day=1).isoformat(), first.isoformat()
    if re.search(r"this year|এই বছর", t):
        return "year", date(today.year, 1, 1).isoformat(), date(today.year, 12, 31).isoformat()
    if re.search(r"this month|এই মাস|monthly", t):
        return "month", None, None
    return None, None, None


def extract(text: str, today: date) -> dict:
    """A partial understanding of one message: {"intent": ..., "transaction": {...}, "query": {...}}."""
    raw = text or ""
    t = ascii_digits(raw).strip()
    low = t.lower()
    if CANCEL.match(t):
        return {"intent": "cancel"}
    if YES.match(t):
        return {"intent": "confirm"}
    if NO.match(t):
        return {"intent": "deny"}
    if DELETE.search(low):
        return {"intent": "delete_transaction"}
    amt = amounts(t)
    typ = classify_type(t)
    # a question about the user's money, not a new entry
    if QUERY.search(low) and not (typ and amt.get("amount") and re.search(r"\b(i|just|today|yesterday)\b", low) and not re.search(r"how much|what", low)):
        kind = "balance" if re.search(r"balance|net worth|কত আছে|ব্যালেন্স", low) else "budget" if re.search(r"budget", low) else "goal" if re.search(r"goal", low) \
            else "summary" if re.search(r"summary|summari|how am i doing|overview|report|হিসাব", low) else "spend_total" if re.search(r"how much|total|spent|spending|কত", low) else "list"
        per, ps, pe = period_of(t, today)
        cat = taxonomy.guess(t)[0]
        return {"intent": "query", "query": {"kind": kind, "category": cat if cat != "other" else None, "period": per, "start": ps, "end": pe,
                                              "merchant": merchant_of(t)}}
    tx: dict = {}
    if typ:
        tx["type"] = typ
    tx.update({k: v for k, v in amt.items()})
    basis = amount_basis(t)
    if basis:
        tx["amount_basis"] = basis
    if re.search(r"discount|\boffer\b|ছাড়|ডিসকাউন্ট", low) and not amt.get("discount") and not amt.get("no_discount") and typ in (None, "expense", "refund"):
        tx["discount_mentioned"] = True                                    # said there was one, did not say how much
    if re.search(r"\bvat\b|\btax\b|service charge|ভ্যাট", low) and not (amt.get("tax") or amt.get("service_charge") or amt.get("no_tax")) and typ in (None, "expense", "refund"):
        tx["tax_mentioned"] = True
    d = parse_date(t, today)
    if d:
        tx["date"] = d.isoformat()
    mer = merchant_of(t)
    if mer:
        tx["merchant"] = mer
    it = items_of(t)
    if it:
        tx["item_name"] = it
    pm = taxonomy.payment_method_from(t)
    if pm:
        tx["payment_method"] = pm
    nt = note_of(t)
    if nt:
        tx["note"] = nt
    if typ in (None, "expense", "refund"):
        cat, sub, conf = taxonomy.guess(f"{mer or ''} {it or ''} {t}")
        if conf >= 0.5:
            tx["category"], tx["category_confidence"] = cat, conf
            if sub:
                tx["subcategory"] = sub
    if typ == "income":
        tx["category"] = taxonomy.guess_income(t)
    if typ is None and tx.get("amount") and tx.get("category") and not re.search(r"\b(how|what|when|why)\b", low):
        tx["type"] = "expense"                                              # an amount with a spending category reads as an expense
    frm = re.search(r"\b(?:from|using|via|through|paid by|paid with|by)\s+(?:my\s+)?([a-z][a-z0-9 ]{1,24}?)(?=\s+(?:to|for|on|at|today|yesterday)\b|[.,!?]|$)", low)
    to = re.search(r"\b(?:to|into)\s+(?:my\s+)?([a-z][a-z0-9 ]{1,24}?)(?:\s+account)?(?=\s+(?:from|today|yesterday|on)\b|[.,!?]|$)", low)
    if frm and not re.match(r"(a|the|it|me)\b", frm.group(1)):
        tx["account_hint"] = _clean(frm.group(1))
    if typ == "transfer" and to:
        tx["to_account_hint"] = _clean(to.group(1))
    if typ == "transfer":
        tx.pop("merchant", None)                                            # "from City Bank" is an account, not a shop
    if re.search(r"\b(every month|monthly|each month|recurring|subscription|প্রতি মাস)\b", low):
        tx["recurring"] = True
    if re.search(r"\b(essential|necessary|needed|must[- ]have)\b", low):
        tx["essential"] = True
    elif re.search(r"\b(luxury|treat|unnecessary|impulse|wasteful)\b", low):
        tx["essential"] = False
    if UPDATE.search(low) and not tx.get("type"):
        return {"intent": "update_transaction", "transaction": tx}
    if tx.get("amount") or tx.get("type"):
        return {"intent": "create_transaction", "transaction": tx}
    return {"intent": "provide_info" if tx else "other", "transaction": tx}


# ---------------------------------------------------------------------------------------------- answers to a specific question
def answer_slot(slot: str, text: str, today: date, options: Optional[list] = None) -> dict:
    """Interpret a short reply to the question the assistant just asked. Returns a patch for the draft (may be empty)."""
    t = ascii_digits(text or "").strip()
    low = t.lower()
    if slot == "amount_basis":
        b = amount_basis(t)
        if b:
            return {"amount_basis": b}
        if re.search(r"\b(before|gross|original)\b|আগে", low):
            return {"amount_basis": "before_discount"}
        if re.search(r"\b(after|final|paid|net|total)\b|পর", low):
            return {"amount_basis": "final"}
        return {}
    if slot == "adjustments":                                              # "any discount, VAT or service charge?"
        if NO.match(t) or re.search(r"\b(no|none|nothing)\b|না", low):
            return {"no_discount": True, "no_tax": True}
        a = amounts(t)
        out = {k: v for k, v in a.items() if k != "amount"}
        if a.get("amount") and not out.get("discount") and re.search(r"discount|ছাড়", low):
            out["discount"] = a["amount"]
        if a.get("amount") and not out.get("tax") and re.search(r"vat|tax|ভ্যাট", low):
            out["tax"] = a["amount"]
        if YES.match(t):
            return {"adjustments_yes": True}
        return out
    if slot == "tax":                                                       # "any additional VAT or service charge?"
        if NO.match(t) or re.search(r"\b(no|none|nothing)\b|না", low):
            return {"no_tax": True}
        a = amounts(t)
        out = {k: v for k, v in a.items() if k in ("tax", "service_charge")}
        if not out and a.get("amount"):
            out["tax"] = a["amount"]
        return out
    if slot == "discount":
        if NO.match(t):
            return {"no_discount": True}
        a = amounts(t)
        v = a.get("discount") or a.get("amount")
        return {"discount": v} if v else {}
    if slot == "date":
        d = parse_date(t, today)
        return {"date": d.isoformat()} if d else {}
    if slot == "amount":
        a = amounts(t)
        return {"amount": a["amount"]} if a.get("amount") else {}
    if slot in ("type", "category", "account", "to_account"):
        for opt in options or []:
            if opt.lower() in low or low in opt.lower() and len(low) >= 3:
                return {slot: opt}
        if slot == "category":
            cat, sub, conf = taxonomy.guess(t)
            if conf:
                return {"category": cat, **({"subcategory": sub} if sub else {})}
            for c in taxonomy.EXPENSE:
                if c in low:
                    return {"category": c}
        if slot == "type":
            typ = classify_type(t) or next((x for x in ("expense", "income", "transfer", "refund") if x in low), None)
            return {"type": typ} if typ else {}
        return {"account": _clean(t)} if t and len(t) <= 40 else {}
    if slot == "note":
        if SKIP.match(t):
            return {"note_done": True}
        nt = note_of(t)
        return {"note": nt or _clean(t)[:300], "note_done": True}
    if slot == "confirm":
        if YES.match(t):
            return {"confirm": True}
        if NO.match(t) or CANCEL.match(t):
            return {"confirm": False}
        return {}
    return {}
