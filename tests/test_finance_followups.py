"""Receipts, activity log, bill-reminder keys, Bangla answers and Bangla reports."""
import struct
import uuid
import zlib
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import accounts
from app.finance import ai, analytics, assistant, bn, books, money, planning, privacy, receipts, reports, routes, settings
from app.finance.ai import AIResult
from app.main import app

U = "alice"


def day(n):
    return (money.today() - timedelta(days=n)).isoformat()


def say(text, user=U):
    return assistant.turn(user, text, uuid.uuid4().hex)


@pytest.fixture
def cash():
    return books.create_account(U, "Cash", "cash", "5000", opening_date=day(60))


# ---- tiny valid images, built by hand so the tests need no imaging library
def png(extra_chunks=b""):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + extra_chunks + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


def jpeg(with_exif=True):
    exif = b"\xff\xe1" + struct.pack(">H", 2 + 30) + b"Exif\x00\x00GPS-LATITUDE-23.81-LON-90.41"[:30]
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sos = b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00" + b"\x12\x34" + b"\xff\xd9"
    return b"\xff\xd8" + app0 + (exif if with_exif else b"") + sos


def webp():
    return b"RIFF" + struct.pack("<I", 12) + b"WEBPVP8 " + b"\x00" * 4


# ============================================================================================== receipts
def test_receipts_are_checked_by_content_stripped_of_metadata_and_owner_only(cash):
    t = books.create_transaction(U, {"type": "expense", "account_id": cash["id"], "amount": "100", "category": "food"})
    j = jpeg()
    assert b"GPS-LATITUDE" in j
    out = receipts.attach(U, t["id"], j, "image/jpeg")
    mime, stored = receipts.get(U, t["id"])
    assert mime == "image/jpeg" and b"GPS-LATITUDE" not in stored and b"JFIF" in stored and stored.endswith(b"\xff\xd9") and out["metadata_removed"] is True
    assert books.get_transaction(U, t["id"])["has_receipt"] is True
    with pytest.raises(books.FinanceError) as e:
        receipts.get("bob", t["id"])
    assert e.value.status == 404
    with pytest.raises(books.FinanceError):
        receipts.attach("bob", t["id"], png(), "image/png")                         # not their transaction


def test_png_text_chunks_are_removed_and_webp_is_accepted(cash):
    t = books.create_transaction(U, {"type": "expense", "account_id": cash["id"], "amount": "100", "category": "food"})
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    receipts.attach(U, t["id"], png(chunk(b"tEXt", b"GPS\x0023.81,90.41")), "image/png")
    mime, stored = receipts.get(U, t["id"])
    assert mime == "image/png" and b"23.81" not in stored and stored.startswith(b"\x89PNG") and b"IDAT" in stored
    receipts.attach(U, t["id"], webp(), "image/webp")                               # replaces the previous receipt
    assert receipts.get(U, t["id"])[0] == "image/webp"
    assert books._one("SELECT COUNT(*) AS n FROM fin_receipts")["n"] == 1


@pytest.mark.parametrize("data,claimed,status", [
    pytest.param(b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "image/svg+xml", 415, id="svg"),
    pytest.param(b"<html><script>alert(1)</script></html>", "image/png", 415, id="html-as-png"),
    pytest.param(b"%PDF-1.4 fake", "application/pdf", 415, id="pdf"),
    pytest.param(b"", "image/png", 400, id="empty"),
    pytest.param(b"x" * (receipts.MAX_BYTES + 1), "image/jpeg", 413, id="too-large"),
])
def test_anything_that_is_not_a_small_real_photo_is_refused(cash, data, claimed, status):
    t = books.create_transaction(U, {"type": "expense", "account_id": cash["id"], "amount": "100", "category": "food"})
    with pytest.raises(books.FinanceError) as e:
        receipts.attach(U, t["id"], data, claimed)
    assert e.value.status == status


def test_a_file_that_pretends_to_be_another_type_is_refused(cash):
    t = books.create_transaction(U, {"type": "expense", "account_id": cash["id"], "amount": "100", "category": "food"})
    with pytest.raises(books.FinanceError, match="does not match"):
        receipts.attach(U, t["id"], png(), "image/jpeg")
    receipts.attach(U, t["id"], png(), "application/octet-stream")                  # browsers sometimes send this; the bytes decide


def test_a_per_account_limit_protects_storage(cash, monkeypatch):
    monkeypatch.setattr(receipts, "MAX_PER_USER", 2)
    ids = [books.create_transaction(U, {"type": "expense", "account_id": cash["id"], "amount": "1", "category": "food"})["id"] for _ in range(3)]
    receipts.attach(U, ids[0], png()); receipts.attach(U, ids[1], png())
    with pytest.raises(books.FinanceError, match="limit"):
        receipts.attach(U, ids[2], png())
    receipts.attach(U, ids[1], png())                                                # replacing one is still allowed


def test_removing_and_erasing_clear_receipts(cash):
    t = books.create_transaction(U, {"type": "expense", "account_id": cash["id"], "amount": "100", "category": "food"})
    receipts.attach(U, t["id"], png())
    receipts.remove(U, t["id"])
    assert books.get_transaction(U, t["id"])["has_receipt"] is False and books._one("SELECT COUNT(*) AS n FROM fin_receipts")["n"] == 0
    receipts.attach(U, t["id"], png())
    privacy.erase_all(U, privacy.CONFIRM_PHRASE)
    assert books._one("SELECT COUNT(*) AS n FROM fin_receipts")["n"] == 0


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


def test_receipt_endpoints_upload_serve_safely_and_isolate_users(web):
    h, other = web("li"), web("chen")
    acc = c.post("/api/fin/accounts", headers=h, json={"name": "Cash", "type": "cash", "opening_balance": "100"}).json()
    t = c.post("/api/fin/transactions", headers=h, json={"type": "expense", "account_id": acc["id"], "amount": "5", "category": "food"}).json()
    up = c.post(f"/api/fin/transactions/{t['id']}/receipt", headers=dict(h, **{"Content-Type": "image/jpeg"}), content=jpeg())
    assert up.status_code == 200 and up.json()["mime"] == "image/jpeg" and up.json()["metadata_removed"] is True
    got = c.get(f"/api/fin/transactions/{t['id']}/receipt", headers=h)
    assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg" and got.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in got.headers["content-security-policy"] and "no-store" in got.headers["cache-control"] and b"GPS" not in got.content
    assert c.get(f"/api/fin/transactions/{t['id']}/receipt", headers=other).status_code == 404
    assert c.post(f"/api/fin/transactions/{t['id']}/receipt", headers=dict(other, **{"Content-Type": "image/png"}), content=png()).status_code == 404
    assert c.get(f"/api/fin/transactions/{t['id']}", headers=h).json()["has_receipt"] is True
    bad = c.post(f"/api/fin/transactions/{t['id']}/receipt", headers=dict(h, **{"Content-Type": "image/png"}), content=b"<script>x</script>")
    assert bad.status_code == 415 and "JPEG, PNG or WebP" in bad.json()["detail"]
    big = c.post(f"/api/fin/transactions/{t['id']}/receipt", headers=dict(h, **{"Content-Type": "image/jpeg"}), content=b"\xff\xd8\xff" + b"0" * 2_100_000)
    assert big.status_code == 413
    assert c.post(f"/api/fin/transactions/{t['id']}/receipt/delete", headers=h).status_code == 200
    assert c.get(f"/api/fin/transactions/{t['id']}/receipt", headers=h).status_code == 404


def test_activity_log_shows_only_my_actions_and_the_chain_status(web):
    h, other = web("li"), web("chen")
    acc = c.post("/api/fin/accounts", headers=h, json={"name": "Cash", "type": "cash", "opening_balance": "100"}).json()
    c.post("/api/fin/transactions", headers=h, json={"type": "expense", "account_id": acc["id"], "amount": "5", "category": "food", "note": "private note"})
    a = c.get("/api/fin/activity", headers=h).json()
    assert [e["action"] for e in a["entries"]][:2] == ["fin_txn_created", "fin_account_created"] and a["chain"]["valid"] is True
    assert "private note" not in c.get("/api/fin/activity", headers=h).text and all("user" not in e["detail"] for e in a["entries"])
    assert c.get("/api/fin/activity", headers=other).json()["entries"] == []


# ============================================================================================== reminders
def test_alerts_carry_a_stable_key_so_a_device_can_notify_once(cash):
    planning.create_obligation(U, {"name": "Wifi", "amount": "500", "next_due": day(-1), "reminder_days": 3})
    planning.create_budget(U, {"category": "food", "limit": "100", "alert_pct": 50})
    books.create_transaction(U, {"type": "expense", "account_id": cash["id"], "amount": "60", "category": "food", "ts": day(0)})
    a1 = planning.alerts(U)
    a2 = planning.alerts(U)
    assert all(x["key"] for x in a1) and [x["key"] for x in a1] == [x["key"] for x in a2]
    assert any(x["key"].startswith("bill_due:") for x in a1) and any(x["key"].startswith("budget_warning:") for x in a1)
    books.create_transaction(U, {"type": "expense", "account_id": cash["id"], "amount": "60", "category": "food", "ts": day(0)})
    assert any(x["key"].startswith("budget_over:") for x in planning.alerts(U))                  # a new level is a new notification


# ============================================================================================== Bangla answers
def test_questions_are_answered_in_bangla_with_the_same_figures(cash):
    books.create_transaction(U, {"type": "income", "account_id": cash["id"], "amount": "9000", "category": "salary", "ts": day(1)})
    books.create_transaction(U, {"type": "expense", "account_id": cash["id"], "amount": "700", "category": "food", "merchant": "Shwapno", "ts": day(1)})
    planning.create_budget(U, {"category": "food", "limit": "1000"})
    planning.create_goal(U, {"name": "Laptop", "target": "60000", "saved": "6000"})
    r = say("এই মাসে খাবারে কত খরচ হয়েছে? how much did I spend on food this month")
    assert r["language"] == "bn" and "৳700.00" in r["reply"] and "খাবার" in r["reply"]
    bal_bn = say("আমার ব্যালেন্স কত?")["reply"]
    assert "৳13,300.00" in bal_bn and "তরল তহবিল" in bal_bn
    settings.update(U, {"assistant_lang": "bn"})
    bal = say("what is my balance")["reply"]
    assert "৳13,300.00" in bal and "তরল তহবিল" in bal and "Your liquid" not in bal
    assert "১০০০" not in say("show my budget")["reply"] and "1000.00 BDT-এর মধ্যে 700.00" in say("show my budget")["reply"]
    assert "জমেছে" in say("how are my goals?")["reply"]
    summary = say("how am I doing this month?")["reply"]
    assert "আয় ৳9,000.00" in summary and "খরচ ৳700.00" in summary
    assert "Income" not in summary


def test_bangla_empty_states_are_honest(cash):
    settings.update("fresh", {"assistant_lang": "bn"})
    assert "কোনো অ্যাকাউন্ট যোগ করেননি" in say("what is my balance", "fresh")["reply"]
    assert "কোনো বাজেট নেই" in say("show my budgets", "fresh")["reply"]
    assert "কোনো লক্ষ্য নেই" in say("how are my goals", "fresh")["reply"]


# ============================================================================================== Bangla reports
def populate(cash):
    bank = books.create_account(U, "Bank", "bank", "40000", opening_date=day(200))
    for m in range(4):
        books.create_transaction(U, {"type": "income", "account_id": bank["id"], "amount": "30000", "category": "salary", "ts": day(m * 30 + 2)})
        books.create_transaction(U, {"type": "expense", "account_id": cash["id"], "amount": "1500", "category": "entertainment", "merchant": "Cineplex", "ts": day(m * 30 + 4)})
    for i in range(25):
        books.create_transaction(U, {"type": "expense", "account_id": cash["id"], "amount": "40", "category": "food", "merchant": "Tea Stall", "ts": day(i + 1)})


def test_a_bangla_report_has_bangla_findings_with_the_same_figures(cash):
    populate(cash)
    en = reports.build(U, "month", lang="en")
    b = reports.generate(U, "month", with_ai=False, lang="bn")
    assert b["lang"] == "bn" and b["overview"]["income"] == en["overview"]["income"] and b["overview"]["spending"] == en["overview"]["spending"]
    n = b["narrative"]
    assert any("ঀ" <= ch <= "৿" for ch in n["headline"]) and n["mode"] == "rules" and n["findings"]
    assert all(any("ঀ" <= ch <= "৿" for ch in f["what_we_saw"]) for f in n["findings"])
    assert "এআই সেবা ছাড়াই" in " ".join(n["caveats"])
    assert any(a["title"] != e["title"] for a, e in zip(b["recommendations"]["actions"], en["recommendations"]["actions"]))
    assert "প্রতিবেদন" in reports.to_markdown(b)
    sug = b["recommendations"]["suggested_budgets"]
    assert sug and "গড়" in sug[0]["basis"] and "পরামর্শ" in b["recommendations"]["note"]


def test_bangla_insights_keep_their_evidence(cash):
    populate(cash)
    i = next(x for x in analytics.insights(U, money.today() - timedelta(days=30), money.today()) if x["kind"] == "small_purchases")
    t = bn.insight(i, "BDT")
    assert t["evidence"] == i["evidence"] and t["title"] != i["title"] and f"{i['evidence']['count']}" in t["pattern"] and t["assumptions"][0] != i["assumptions"][0]


def test_data_quality_notes_are_translated_and_unknown_ones_stay_readable():
    r = reports.build("nobody", "month", lang="bn")
    assert any("অ্যাকাউন্ট" in q for q in r["data_quality"]) and any("আয়" in q for q in r["data_quality"])
    assert bn.quality("Something new we never translated.") == "Something new we never translated."


def test_the_ai_is_told_to_write_bangla_and_bangla_digits_do_not_defeat_the_figure_check(cash, monkeypatch):
    populate(cash)
    spent = int(float(reports.build(U, "month")["overview"]["spending"]))
    assert spent >= 100
    bd = str(spent).translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))                # the same real figure written with Bangla digits
    monkeypatch.setattr(ai, "enabled", lambda: True)
    seen = []

    def fake(messages, **kw):
        seen.append(messages[0]["content"])
        obj = {"headline": "এই মাসের সারসংক্ষেপ", "summary": f"আপনি ৳{bd} খরচ করেছেন।", "caveats": [],
               "findings": [{"title": "খাবার", "what_we_saw": f"মোট {bd} টাকা গেছে।", "why_it_matters": "x", "suggested_action": "y", "estimated_impact": None, "assumptions": []},
                            {"title": "বানানো", "what_we_saw": "৯৮৭৬৫৪ টাকা গেছে।", "why_it_matters": "x", "suggested_action": "y", "estimated_impact": None, "assumptions": []}]}
        return AIResult(content="{}", parsed=kw["validate"](obj), correlation_id="c")
    monkeypatch.setattr(ai, "call", fake)
    rep = reports.generate(U, "month", lang="bn")
    assert "Bangla" in seen[0] and rep["narrative"]["mode"] == "ai"
    assert [f["title"] for f in rep["narrative"]["findings"]] == ["খাবার"]                      # the invented 987654 was removed even in Bangla digits
    assert "কিছু এআই বক্তব্য বাদ" in " ".join(rep["narrative"]["caveats"])


def test_report_language_follows_the_account_setting_unless_overridden(web):
    h = web("li")
    c.post("/api/fin/settings", headers=h, json={"assistant_lang": "bn", "ai_reports": False})
    assert c.post("/api/fin/reports", headers=h, json={"kind": "month"}).json()["lang"] == "bn"
    assert c.post("/api/fin/reports", headers=h, json={"kind": "month", "lang": "en"}).json()["lang"] == "en"
    assert c.post("/api/fin/reports", headers=h, json={"kind": "month", "lang": "fr"}).status_code == 422


def test_plain_balance_budget_and_goal_questions_never_call_the_model(cash, monkeypatch):
    calls = []
    monkeypatch.setattr(ai, "enabled", lambda: True)
    monkeypatch.setattr(ai, "call", lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(AssertionError("model must not be called")))
    for q in ("what is my balance?", "আমার ব্যালেন্স কত?", "show my budget", "how are my goals?"):
        assert say(q)["ai"] == "rules"
    assert calls == []
