"""Retention and deletion for personal finance data, and redaction of identifiers before text goes to a model or into history.

What is kept and for how long:
  * ledger, accounts, budgets, goals, bills: until the user deletes them (or erases everything)
  * assistant conversations: `history_days` (default 90), then removed automatically
  * idempotency records for retried requests: 7 days (long enough to survive any realistic retry)
  * the tamper-evident audit log keeps ids and amounts of changes (not names or notes) and cannot be edited by design
"""
import re
from datetime import datetime, timedelta, timezone

from app import db
from app.finance import books, settings
from app.finance.books import FinanceError

REQUEST_RETENTION_DAYS = 7
CONFIRM_PHRASE = "DELETE MY FINANCE DATA"
LONG_NUMBER = re.compile(r"(?<![\d.,])(?:\d[ -]?){10,}\d(?![\d])")


def redact(text: str) -> str:
    """Hide card, account and phone numbers (10+ digits) before text is stored or sent to a model. Amounts are far shorter."""
    return LONG_NUMBER.sub("[number hidden]", text or "")


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def purge(user: str) -> dict:
    """Remove expired idempotency records and old finished conversations for one user. Cheap; called while chatting."""
    days = settings.get(user)["history_days"]
    with db.LOCK:
        c = db.connect()
        try:
            r = c.execute("DELETE FROM fin_requests WHERE username=? AND created<?", (user, _cutoff(REQUEST_RETENTION_DAYS))).rowcount
            old = [x["id"] for x in c.execute("SELECT id FROM fin_sessions WHERE username=? AND state IN ('completed','cancelled') AND updated<?", (user, _cutoff(days)))]
            for sid in old:
                c.execute("DELETE FROM fin_messages WHERE session_id=?", (sid,))
                c.execute("DELETE FROM fin_sessions WHERE id=?", (sid,))
            c.commit()
        finally:
            c.close()
    return {"requests_removed": r, "conversations_removed": len(old)}


def clear_assistant_history(user: str) -> dict:
    with db.LOCK:
        c = db.connect()
        try:
            ids = [x["id"] for x in c.execute("SELECT id FROM fin_sessions WHERE username=?", (user,))]
            for sid in ids:
                c.execute("DELETE FROM fin_messages WHERE session_id=?", (sid,))
            c.execute("DELETE FROM fin_sessions WHERE username=?", (user,))
            c.execute("DELETE FROM fin_requests WHERE username=?", (user,))
            c.commit()
        finally:
            c.close()
    books._audit(user, "fin_history_cleared", {"conversations": len(ids)})
    return {"conversations_removed": len(ids)}


def erase_all(user: str, confirm: str) -> dict:
    """Delete everything this account holds in the finance module, in one database transaction (all or nothing)."""
    if confirm != CONFIRM_PHRASE:
        raise FinanceError(f'To erase everything, send confirm exactly as "{CONFIRM_PHRASE}".')
    counts = {}
    with db.LOCK:
        c = db.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            def run(label, sql, args):
                counts[label] = c.execute(sql, args).rowcount
            run("payments", "DELETE FROM fin_obligation_payments WHERE obligation_id IN (SELECT id FROM fin_obligations WHERE username=?)", (user,))
            run("items", "DELETE FROM fin_items WHERE txn_id IN (SELECT id FROM fin_transactions WHERE username=?)", (user,))
            run("transactions", "DELETE FROM fin_transactions WHERE username=?", (user,))
            run("obligations", "DELETE FROM fin_obligations WHERE username=?", (user,))
            run("goals", "DELETE FROM fin_goals WHERE username=?", (user,))
            run("budgets", "DELETE FROM fin_budgets WHERE username=?", (user,))
            run("accounts", "DELETE FROM fin_accounts WHERE username=?", (user,))
            run("messages", "DELETE FROM fin_messages WHERE session_id IN (SELECT id FROM fin_sessions WHERE username=?)", (user,))
            run("conversations", "DELETE FROM fin_sessions WHERE username=?", (user,))
            run("requests", "DELETE FROM fin_requests WHERE username=?", (user,))
            run("reports", "DELETE FROM fin_reports WHERE username=?", (user,))
            run("ai_usage", "DELETE FROM fin_ai_usage WHERE username=?", (user,))
            run("settings", "DELETE FROM fin_settings WHERE username=?", (user,))
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()
    books._audit(user, "fin_data_erased", {"counts": counts})
    return {"erased": counts}
