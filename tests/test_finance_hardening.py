"""Preferences, privacy and retention, redaction, migrations, rollback, rate limits, safe errors, performance."""
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import accounts, db, store
from app.finance import ai, assistant, books, money, planning, privacy, routes, settings
from app.finance.ai import AIError, AIResult
from app.main import app

U = "alice"
TODAY = money.today().isoformat()


def day(n):
    return (money.today() - timedelta(days=n)).isoformat()


def say(text, user=U, rid=None):
    return assistant.turn(user, text, rid or uuid.uuid4().hex)


@pytest.fixture
def cash():
    return books.create_account(U, "Cash", "cash", "5000", opening_date=day(30))


# ============================================================================================== preferences
def test_settings_defaults_validation_and_audit():
    s = settings.get(U)
    assert (s["ai_reports"], s["assistant_lang"], s["ask_adjustments"], s["voice_replies"], s["history_days"]) == (True, "auto", "auto", False, 90)
    out = settings.update(U, {"ai_reports": False, "assistant_lang": "bn", "ask_adjustments": "always", "history_days": 30, "voice_replies": True})
    assert (out["ai_reports"], out["assistant_lang"], out["ask_adjustments"], out["history_days"], out["voice_replies"]) == (False, "bn", "always", 30, True)
    for bad in [{"assistant_lang": "fr"}, {"ask_adjustments": "sometimes"}, {"history_days": 3}, {"history_days": 9999}, {"ai_reports": "yes"}, {"history_days": True}]:
        with pytest.raises(books.FinanceError):
            settings.update(U, bad)
    assert settings.get("bob")["assistant_lang"] == "auto"                      # preferences are per account


def test_the_main_currency_is_locked_once_accounts_exist(cash):
    with pytest.raises(books.FinanceError, match="before you add accounts"):
        settings.update(U, {"base_currency": "USD"})
    assert settings.update("fresh", {"base_currency": "usd"})["base_currency"] == "USD"


def test_ask_always_reproduces_the_full_discount_conversation_from_the_specification(cash):
    settings.update(U, {"ask_adjustments": "always"})
    r = say("I spent 850 taka at the grocery store today on rice, oil and vegetables.")
    assert r["awaiting"] == "adjustments" and "final amount you paid, or was there a discount, VAT or service charge" in r["reply"]
    r = say("There was a 50 taka discount.")
    assert r["awaiting"] == "amount_basis" and "before the discount" in r["reply"]
    r = say("Before the discount.")
    assert r["awaiting"] == "tax" and "VAT or service charge" in r["reply"]
    r = say("No.")
    assert r["awaiting"] == "confirm" and "original ৳850.00" in r["reply"]
    r = say("Save it.")
    assert r["reply"] == "Saved. The original amount was ৳850.00, the discount was ৳50.00, and the final amount was ৳800.00."
    assert books.list_transactions(U)["total"] == 1


def test_ask_always_asks_only_once_and_accepts_final_amount_as_the_answer(cash):
    settings.update(U, {"ask_adjustments": "always"})
    assert say("spent 300 on a taxi today")["awaiting"] == "adjustments"
    r = say("that was the final amount")
    assert r["awaiting"] == "confirm" and "Expense of ৳300.00" in r["reply"] and "discount" not in r["reply"].lower().split("shall")[0]


def test_ask_never_assumes_the_amount_was_what_was_paid(cash):
    settings.update(U, {"ask_adjustments": "never"})
    r = say("spent 850 at Shwapno today with a 50 taka discount")
    assert r["awaiting"] == "confirm" and "Expense of ৳850.00" in r["reply"] and "original ৳900.00" in r["reply"]


def test_the_default_policy_asks_only_when_something_is_unclear(cash):
    assert say("spent 300 on a taxi today")["awaiting"] == "confirm"


def test_a_language_preference_is_respected_even_for_english_input(cash):
    settings.update(U, {"assistant_lang": "bn"})
    r = say("spent 300 on a taxi")
    assert r["language"] == "bn" and "কবে" in r["reply"]


# ============================================================================================== privacy, redaction, minimal prompts
@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(ai, "enabled", lambda: True)
    seen = []

    def install(obj=None, error=None):
        def fake(messages, **kw):
            seen.append(messages)
            if error:
                raise error
            return AIResult(content="{}", parsed=assistant.validate_turn(obj), correlation_id="c1")
        monkeypatch.setattr(ai, "call", fake)
        return seen
    return install


def blank_turn(**tx):
    base = {k: None for k in assistant.TRANSACTION_FIELDS}
    base.update(tx)
    return {"intent": "create_transaction", "transaction": base, "query": {k: None for k in assistant.QUERY_FIELDS}, "missing_fields": [],
            "next_question": None, "proposed_action": "ask"}


def test_long_identifiers_are_hidden_before_the_model_and_the_history_see_them(cash, live):
    seen = live(blank_turn(type="expense", amount="500", date=TODAY, category="shopping"))
    say("paid 500 taka by card 4111 1111 1111 1111 and phone 01712345678 to Daraz today")
    prompt = " ".join(m["content"] for m in seen[0])
    assert "4111" not in prompt and "01712345678" not in prompt and "[number hidden]" in prompt
    sid = assistant.open_session(U)["id"]
    stored = " ".join(m["text"] for m in assistant.messages(U, sid))
    assert "4111" not in stored and "01712345678" not in stored
    assert privacy.redact("spent 850 on 12 oct, 1,250.50 total") == "spent 850 on 12 oct, 1,250.50 total"      # amounts and dates are untouched


def test_prompts_carry_only_what_extraction_needs(cash, live):
    books.create_account("bob", "Bob Secret Savings", "savings", "999999")
    books.create_transaction(U, {"type": "expense", "account_id": cash["id"], "amount": "77", "category": "food", "merchant": "Hidden Merchant"})
    seen = live(blank_turn(type="expense", amount="100", date=TODAY, category="food"))
    say("spent 100 on lunch today")
    system = seen[0][0]["content"]
    assert "Cash" in system and "Bob Secret" not in system and "999999" not in system and "Hidden Merchant" not in system
    assert "balance" not in system.lower() and "5000" not in system and "alice" not in system.lower()


def test_ai_logs_contain_ids_and_counts_never_message_text(cash, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="wealthguard.ai")
    from app.finance.ai import GroqClient, _Resp
    import os
    os.environ["USE_MOCK_LLM"] = "0"
    os.environ["GROQ_API_KEY"] = "gsk_dummy_value"
    os.environ["FIN_AI_RPM"] = "0"
    try:
        c = GroqClient(post=lambda *a, **k: _Resp(200, {}, {"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}), sleep=lambda s: None)
        c.chat([{"role": "user", "content": "my secret salary is 987654 taka"}], purpose="t", user=U)
    finally:
        os.environ["USE_MOCK_LLM"] = "1"
        os.environ.pop("GROQ_API_KEY", None)
    assert "987654" not in caplog.text and "salary" not in caplog.text and "gsk_" not in caplog.text and "purpose=t" in caplog.text


# ============================================================================================== retention and deletion
def test_old_finished_conversations_and_retry_records_expire_but_open_ones_stay(cash):
    say("spent 10 on tea today")
    say("yes")                                                                  # completed conversation
    say("spent 20 on tea today")                                               # still open
    old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat(timespec="seconds")
    store._write("UPDATE fin_sessions SET updated=? WHERE state='completed'", (old,))
    store._write("UPDATE fin_requests SET created=?", (old,))
    out = privacy.purge(U)
    assert out["conversations_removed"] == 1 and out["requests_removed"] >= 2
    left = books._q("SELECT state FROM fin_sessions WHERE username=?", (U,))
    assert [r["state"] for r in left] == ["awaiting_confirmation"]
    assert books._one("SELECT COUNT(*) AS n FROM fin_messages WHERE session_id NOT IN (SELECT id FROM fin_sessions)")["n"] == 0
    assert books.list_transactions(U)["total"] == 1                              # the ledger itself is never purged by retention


def test_a_shorter_retention_setting_is_applied(cash):
    settings.update(U, {"history_days": 7})
    say("spent 10 on tea today")
    say("yes")
    store._write("UPDATE fin_sessions SET updated=? WHERE state='completed'", ((datetime.now(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds"),))
    assert privacy.purge(U)["conversations_removed"] == 1


def test_clearing_history_keeps_the_ledger(cash):
    say("spent 10 on tea today")
    say("yes")
    assert privacy.clear_assistant_history(U)["conversations_removed"] == 1
    assert assistant.current(U)["state"] == "idle" and books.list_transactions(U)["total"] == 1


def test_erasing_everything_needs_the_exact_phrase_removes_only_this_users_finance_data(cash):
    other = books.create_account("bob", "Cash", "cash", "100")
    books.create_transaction("bob", {"type": "expense", "account_id": other["id"], "amount": "5", "category": "food"})
    books.create_transaction(U, {"type": "expense", "account_id": cash["id"], "amount": "50", "category": "food", "items": [{"name": "rice", "amount": "50"}]})
    planning.create_budget(U, {"limit": "100"}); planning.create_goal(U, {"name": "G", "target": "10"})
    planning.create_obligation(U, {"name": "Rent", "amount": "10", "next_due": day(-3)})
    store._write("INSERT INTO memories (username, kind, key, text, created, updated) VALUES ('alice','note','n1','keep me','x','x')", ())
    with pytest.raises(books.FinanceError, match="exactly"):
        privacy.erase_all(U, "yes please")
    assert books.list_transactions(U)["total"] == 1
    res = privacy.erase_all(U, privacy.CONFIRM_PHRASE)["erased"]
    assert res["transactions"] == 1 and res["accounts"] == 1 and res["budgets"] == 1 and res["goals"] == 1 and res["obligations"] == 1
    assert books.list_accounts(U, include_archived=True) == [] and planning.list_budgets(U) == [] and books._one("SELECT COUNT(*) AS n FROM fin_items")["n"] == 0
    assert books.list_transactions("bob")["total"] == 1 and len(books.list_accounts("bob")) == 1          # nobody else is touched
    assert books._one("SELECT COUNT(*) AS n FROM memories WHERE username='alice'")["n"] == 1             # the advisor's memory is a separate feature
    audit = [e["action"] for e in __import__("app.security.audit", fromlist=["x"]).list_entries(None)]
    assert "fin_data_erased" in audit


# ============================================================================================== migrations
def build_old_database(path):
    con = sqlite3.connect(path)
    con.executescript("""
    CREATE TABLE clients (id TEXT PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE users (username TEXT PRIMARY KEY, display_name TEXT NOT NULL, role TEXT NOT NULL, persona_id TEXT, salt TEXT NOT NULL, pw_hash TEXT NOT NULL, created TEXT NOT NULL);
    CREATE TABLE memories (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL, text TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL, UNIQUE (username, kind, key));
    INSERT INTO clients VALUES ('c1', '{"name": "Ms. Li"}');
    INSERT INTO users VALUES ('li', 'Ms. Li', 'client', NULL, 'aa', 'bb', 'then');
    INSERT INTO memories (username, kind, key, text, created, updated) VALUES ('li', 'note', 'k', 'likes bonds', 'then', 'then');
    """)
    con.commit()
    con.close()


def test_an_older_database_keeps_its_data_and_gains_the_finance_tables_and_columns(tmp_path, monkeypatch):
    path = str(tmp_path / "old.db")
    build_old_database(path)
    monkeypatch.setenv("WEALTHGUARD_DB", path)
    db._MIGRATED.discard(path)
    c = db.connect()
    assert c.execute("SELECT data FROM clients WHERE id='c1'").fetchone()["data"] == '{"name": "Ms. Li"}'
    assert c.execute("SELECT text FROM memories").fetchone()["text"] == "likes bonds"
    u = c.execute("SELECT username, banned, permissions FROM users").fetchone()
    assert (u["username"], u["banned"], u["permissions"]) == ("li", 0, "{}")                        # defaults for the new columns
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"fin_accounts", "fin_transactions", "fin_budgets", "fin_goals", "fin_obligations", "fin_sessions", "fin_requests", "fin_ai_usage", "fin_reports"} <= tables
    c.close()
    assert books.create_account("li", "Cash", "cash", "10")["balance"] == "10.00"                    # and the new module works on it
    assert settings.get("li")["history_days"] == 90


def test_a_finance_settings_table_from_before_the_preferences_existed_is_upgraded_in_place(tmp_path, monkeypatch):
    path = str(tmp_path / "mid.db")
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE fin_settings (username TEXT PRIMARY KEY, base_currency TEXT NOT NULL DEFAULT 'BDT', created TEXT NOT NULL);"
                      "INSERT INTO fin_settings VALUES ('li', 'BDT', 'then');")
    con.commit(); con.close()
    monkeypatch.setenv("WEALTHGUARD_DB", path)
    db._MIGRATED.discard(path)
    s = settings.get("li")
    assert s["base_currency"] == "BDT" and s["ask_adjustments"] == "auto" and s["voice_replies"] is False


def test_the_migration_can_run_twice_without_changing_anything(tmp_path, monkeypatch):
    path = str(tmp_path / "twice.db")
    build_old_database(path)
    monkeypatch.setenv("WEALTHGUARD_DB", path)
    db._MIGRATED.discard(path)
    db.connect().close()
    db._MIGRATED.discard(path)
    c = db.connect()
    cols = [r[1] for r in c.execute("PRAGMA table_info(users)")]
    assert cols.count("banned") == 1 and c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


# ============================================================================================== integrity: rollback and failures
def test_a_failure_while_saving_leaves_no_partial_record_and_no_balance_change(cash, monkeypatch):
    real_save = books._save_items

    def boom(c, txn_id, items):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(books, "_save_items", boom)
    with pytest.raises(sqlite3.OperationalError):
        books.create_transaction(U, {"type": "expense", "account_id": cash["id"], "amount": "100", "category": "food", "items": [{"name": "x", "amount": "100"}]})
    assert books.list_transactions(U)["total"] == 0 and books.list_accounts(U)[0]["balance"] == "5000.00"
    assert books._one("SELECT COUNT(*) AS n FROM fin_transactions")["n"] == 0                       # the insert itself was rolled back
    monkeypatch.setattr(books, "_save_items", real_save)
    assert books.create_transaction(U, {"type": "expense", "account_id": cash["id"], "amount": "100", "category": "food"})["final_amount"] == "100.00"


def test_the_assistant_never_reports_success_when_saving_failed(cash, monkeypatch):
    say("spent 100 on lunch today")
    real = books.create_transaction

    def failing(*a, **k):
        raise books.FinanceError("The database is busy.", 500)
    monkeypatch.setattr(books, "create_transaction", failing)
    with pytest.raises(books.FinanceError):
        say("yes")
    sess = assistant.open_session(U)
    assert sess["state"] == "awaiting_confirmation"                                                  # still waiting: nothing was claimed as saved
    monkeypatch.setattr(books, "create_transaction", real)
    assert say("yes")["state"] == "completed" and books.list_transactions(U)["total"] == 1


def test_invalid_model_output_and_service_failures_degrade_to_rules(cash, live):
    for err in (AIError("format", "bad json"), AIError("timeout", "slow"), AIError("unavailable", "down"), AIError("auth", "key rejected")):
        live(error=err)
        r = say("I spent 850 taka at the grocery store today", rid=uuid.uuid4().hex)
        assert r["ai"] == "fallback" and r["awaiting"] == "confirm"
        say("cancel")


# ============================================================================================== HTTP: safe errors, limits, admin usage
c = TestClient(app)


@pytest.fixture
def web(monkeypatch):
    monkeypatch.setenv("WEALTHGUARD_AUTH", "1")
    accounts._FAILS.clear()
    routes._HITS.clear()

    def login(user):
        r = c.post("/api/auth/login", json={"username": user, "password": "123"})
        return {"Authorization": "Bearer " + r.json()["token"]}
    return login


def test_database_errors_become_a_generic_message_without_paths_or_sql(web, monkeypatch):
    h = web("li")
    def boom(*a, **k):
        raise sqlite3.OperationalError("unable to open database file C:/secret/path/wealthguard.db SELECT * FROM fin_accounts")
    monkeypatch.setattr(books, "list_accounts", boom)
    r = c.get("/api/fin/accounts", headers=h)
    assert r.status_code == 500 and "secret" not in r.text and "SELECT" not in r.text and "try again" in r.json()["detail"]


def test_write_report_and_erase_requests_are_rate_limited(web, monkeypatch):
    h = web("li")
    acc = c.post("/api/fin/accounts", headers=h, json={"name": "Cash", "type": "cash", "opening_balance": "100"}).json()
    monkeypatch.setitem(routes.LIMITS, "write", (5, 60))
    codes = [c.post("/api/fin/transactions", headers=h, json={"type": "expense", "account_id": acc["id"], "amount": "1", "category": "food"}).status_code for _ in range(8)]
    assert codes.count(200) == 5 and codes.count(429) == 3
    monkeypatch.setitem(routes.LIMITS, "report", (2, 3600))
    rc = [c.post("/api/fin/reports", headers=h, json={"kind": "month"}).status_code for _ in range(4)]
    assert rc == [200, 200, 429, 429]
    assert c.post("/api/fin/reports", headers=h, json={"kind": "month", "ai": False}).status_code == 200       # the non-AI report is not metered
    monkeypatch.setitem(routes.LIMITS, "erase", (1, 3600))
    assert c.post("/api/fin/privacy/erase", headers=h, json={"confirm": "nope"}).status_code == 400
    assert c.post("/api/fin/privacy/erase", headers=h, json={"confirm": "nope"}).status_code == 429


def test_settings_and_privacy_endpoints(web):
    h = web("chen")
    s = c.get("/api/fin/settings", headers=h).json()
    assert s["ask_adjustments"] == "auto" and "options" in s
    r = c.post("/api/fin/settings", headers=h, json={"ask_adjustments": "always", "ai_reports": False})
    assert r.json()["ask_adjustments"] == "always" and r.json()["ai_reports"] is False
    assert c.post("/api/fin/settings", headers=h, json={"assistant_lang": "xx"}).status_code == 400
    rep = c.post("/api/fin/reports", headers=h, json={"kind": "month"}).json()
    assert rep["narrative"]["mode"] == "rules"                                                            # the account turned AI explanations off
    assert c.get("/api/fin/settings", headers=web("li")).json()["ask_adjustments"] == "auto"
    assert c.post("/api/fin/privacy/clear-history", headers=h).json()["conversations_removed"] == 0
    assert c.post("/api/fin/privacy/erase", headers=h, json={"confirm": privacy.CONFIRM_PHRASE}).json()["erased"]["settings"] == 1


def test_only_the_admin_sees_ai_usage_totals_and_never_message_text(web):
    h = web("li")
    store._write("INSERT INTO fin_ai_usage (ts, username, purpose, model, prompt_version, correlation_id, prompt_tokens, completion_tokens, est_cost_usd, latency_ms, retries, status) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (store.now(), "li", "assistant_extract", "openai/gpt-oss-20b", "v1", "c", 1000, 200, 0.00013, 900, 0, "ok"))
    assert c.get("/api/admin/ai-usage", headers=h).status_code == 403
    u = c.get("/api/admin/ai-usage", headers=web("admin")).json()
    assert u["calls"] == 1 and u["prompt_tokens"] == 1000 and "est_cost_usd" in u
    assert c.get("/api/fin/ai-usage", headers=h).json()["calls"] == 1 and c.get("/api/fin/ai-usage", headers=web("chen")).json()["calls"] == 0


# ============================================================================================== time, scheduling, scale
def test_future_dated_transactions_are_flagged_scheduled_and_not_counted(cash):
    t = books.create_transaction(U, {"type": "expense", "account_id": cash["id"], "amount": "100", "category": "food", "ts": day(-3)})
    now = books.create_transaction(U, {"type": "expense", "account_id": cash["id"], "amount": "10", "category": "food", "ts": day(0)})
    assert t["scheduled"] is True and now["scheduled"] is False
    assert books.list_accounts(U)[0]["balance"] == "4990.00"


def test_stored_timestamps_are_utc_with_an_offset_and_user_dates_are_dhaka_local(cash):
    row = books._one("SELECT created FROM fin_accounts WHERE id=?", (cash["id"],))
    assert row["created"].endswith("+00:00")
    local = money.now()
    utc = datetime.now(timezone.utc).replace(tzinfo=None)
    assert 5 * 3600 <= (local - utc).total_seconds() + 60 <= 7 * 3600                                    # Asia/Dhaka is UTC+6, no daylight saving


def test_a_large_ledger_still_loads_the_dashboard_quickly_and_lists_are_paginated(cash):
    c2 = db.connect()
    rows = [(f"txn_bulk{i}", U, "expense", f"{day(i % 120)}T00:00:01", cash["id"], 5000, 0, 0, 0, 5000, "BDT", "manual", "food", f"Shop{i % 15}", "2026-01-01", "2026-01-01") for i in range(2500)]
    c2.executemany("INSERT INTO fin_transactions (id, username, type, ts, account_id, gross_minor, discount_minor, tax_minor, service_minor, final_minor, currency, source, category, merchant, created, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    c2.commit(); c2.close()
    t = time.time()
    from app.finance import analytics, reports
    s = analytics.summary(U, money.today() - timedelta(days=119), money.today())
    f = planning.forecast(U)
    rep = reports.build(U, "year")
    assert time.time() - t < 6 and s["transactions"] == 2500 and rep["spending"]["by_category"][0]["category"] == "food" and f["is_estimate"]
    page = books.list_transactions(U, size=25)
    assert len(page["items"]) == 25 and page["total"] == 2500 and page["pages"] == 100
