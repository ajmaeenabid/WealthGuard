"""CSV export and import of transactions. Import uses the same validation as manual entry and skips rows that were already imported."""
import csv
import hashlib
import io
from typing import Optional

from app.finance import books, money
from app.finance.books import FinanceError

COLUMNS = ["date", "type", "amount", "gross_amount", "discount", "tax", "service_charge", "category", "subcategory", "merchant", "item", "account",
           "to_account", "payment_method", "essential", "recurring", "tags", "note", "currency", "id"]
MAX_BYTES = 1_000_000
MAX_ROWS = 2000
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s.startswith(FORMULA_PREFIXES) and not _is_number(s) else s


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def export_csv(user: str, start: Optional[str] = None, end: Optional[str] = None) -> str:
    names = {a["id"]: a["name"] for a in books.list_accounts(user, include_archived=True)}
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(COLUMNS)
    page = 1
    while True:
        res = books.list_transactions(user, start=start, end=end, sort="ts", direction="asc", page=page, size=books.MAX_PAGE)
        for t in res["items"]:
            w.writerow([_safe_cell(x) for x in [t["ts"][:10], t["type"], t["final_amount"], t["gross_amount"], t["discount"], t["tax"], t["service_charge"], t["category"],
                                                  t["subcategory"], t["merchant"], t["item_name"], names.get(t["account_id"]), names.get(t["to_account_id"]),
                                                  t["payment_method"], "" if t["essential"] is None else ("yes" if t["essential"] else "no"),
                                                  "yes" if t["recurring"] else "", ";".join(t["tags"]), t["note"], t["currency"], t["id"]]])
        if page >= res["pages"]:
            break
        page += 1
    return out.getvalue()


def _yes(v: str) -> Optional[bool]:
    v = (v or "").strip().lower()
    return True if v in ("yes", "true", "1", "y") else False if v in ("no", "false", "0", "n") else None


def import_csv(user: str, text: str, default_account: Optional[str] = None) -> dict:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise FinanceError("The file is too large (limit 1 MB).")
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    if not rows:
        raise FinanceError("The file has no rows.")
    if len(rows) > MAX_ROWS:
        raise FinanceError(f"Too many rows (limit {MAX_ROWS}).")
    need = {"date", "type", "amount"}
    if not need <= set(rows[0].keys()):
        raise FinanceError("The first row must contain the columns: date, type, amount (see the export for the full list).")
    accounts = {a["name"].lower(): a for a in books.list_accounts(user, include_archived=True)}
    default = books.get_account(user, default_account) if default_account else None
    created, skipped, errors = 0, 0, []
    for n, row in enumerate(rows, start=2):
        try:
            acc = accounts.get((row.get("account") or "").strip().lower()) if row.get("account") else None
            acc = acc or (dict(default) if default else None)
            if not acc:
                raise FinanceError("account not found; add it first or choose a default account")
            data = {"type": (row.get("type") or "").strip().lower(), "ts": row["date"].strip(), "account_id": acc["id"],
                    "amount": (row.get("amount") or "").strip()}
            for k_csv, k in (("gross_amount", "gross_amount"), ("discount", "discount"), ("tax", "tax"), ("service_charge", "service_charge"), ("category", "category"),
                             ("subcategory", "subcategory"), ("merchant", "merchant"), ("item", "item_name"), ("payment_method", "payment_method"), ("note", "note")):
                v = (row.get(k_csv) or "").strip()
                if v:
                    data[k] = v
            if data["type"] == "transfer":
                dst = accounts.get((row.get("to_account") or "").strip().lower())
                if not dst:
                    raise FinanceError("to_account not found")
                data["to_account_id"] = dst["id"]
            ess = _yes(row.get("essential", ""))
            if ess is not None:
                data["essential"] = ess
            if _yes(row.get("recurring", "")):
                data["recurring"] = True
            if row.get("tags"):
                data["tags"] = [t for t in row["tags"].split(";") if t.strip()]
            if "category" in data and data["type"] == "expense":
                data["category"] = data["category"].lower()
            key = "import:" + hashlib.sha1("|".join(str(data.get(k, "")) for k in sorted(data)).encode()).hexdigest()[:32]
            if books._one("SELECT 1 FROM fin_transactions WHERE username=? AND idempotency_key=?", (user, key)):
                skipped += 1
                continue
            books.create_transaction(user, data, source="import", idempotency_key=key)
            created += 1
        except (FinanceError, money.MoneyError) as e:
            errors.append({"row": n, "error": getattr(e, "message", str(e))})
    books._audit(user, "fin_import", {"created": created, "skipped": skipped, "errors": len(errors)})
    return {"created": created, "skipped_duplicates": skipped, "errors": errors[:50], "error_count": len(errors)}
