"""Accounts, sign-in gate, saved chats, password change."""
import pytest
from fastapi.testclient import TestClient

from app import accounts
from app.main import app

c = TestClient(app)


@pytest.fixture(autouse=True)
def sign_in_required(monkeypatch):
    monkeypatch.setenv("WEALTHGUARD_AUTH", "1")
    accounts._FAILS.clear()


def login(user="li", pw="123"):
    r = c.post("/api/auth/login", json={"username": user, "password": pw})
    return r, ({"Authorization": "Bearer " + r.json()["token"]} if r.status_code == 200 else {})


def signup(name="newbie", pw="secret1"):
    r = c.post("/api/auth/signup", json={"username": name, "password": pw})
    return r, ({"Authorization": "Bearer " + r.json()["token"]} if r.status_code == 200 else {})


def chat(h, cid, message):
    return c.post("/api/chat", headers=h, json={"client_id": cid, "message": message}).json()


def new_chat(h):
    return c.post("/api/conversations", headers=h).json()["client_id"]


def test_api_needs_sign_in_but_health_login_and_the_page_do_not():
    assert c.get("/").status_code == 200 and c.get("/api/health").status_code == 200
    for path in ["/api/products", "/api/personas", "/api/conversations", "/api/audit", "/api/memory", "/api/admin/users"]:
        assert c.get(path).status_code == 401, path
    assert c.post("/api/chat", json={"client_id": "x", "message": "hi"}).status_code == 401
    assert c.get("/api/products", headers={"Authorization": "Bearer nonsense"}).status_code == 401


@pytest.mark.parametrize("user,role,demo", [("admin", "admin", None), ("li", "client", "persona_li"),
                                            ("chen", "client", "persona_chen"), ("wang", "client", "persona_wang")])
def test_demo_accounts_exist_with_password_123(user, role, demo):
    r, h = login(user)
    assert r.status_code == 200 and r.json()["user"]["role"] == role and r.json()["user"]["demo_persona_id"] == demo
    assert c.get("/api/auth/me", headers=h).json()["username"] == user
    assert c.get("/api/products", headers=h).status_code == 200


def test_wrong_password_is_refused_and_repeated_failures_lock_the_account_for_a_while():
    for _ in range(5):
        assert login("li", "nope")[0].status_code == 401
    assert login("li", "123")[0].status_code == 429


def test_sign_up_validates_and_rejects_taken_names_and_short_passwords():
    assert c.post("/api/auth/signup", json={"username": "chen", "password": "secret1"}).status_code == 409
    assert c.post("/api/auth/signup", json={"username": "a", "password": "secret1"}).status_code == 400
    assert c.post("/api/auth/signup", json={"username": "newbie", "password": "123"}).status_code == 400
    r = c.post("/api/auth/signup", json={"username": "Newbie", "password": "secret1"})
    assert r.status_code == 200 and r.json()["user"]["username"] == "newbie" and r.json()["user"]["role"] == "client"
    assert all(r.json()["user"]["permissions"].values())
    assert login("newbie", "secret1")[0].status_code == 200


def test_passwords_are_stored_hashed_not_in_clear():
    login()
    from app import store
    row = store._one("SELECT salt, pw_hash FROM users WHERE username='li'", ())
    assert "123" != row["pw_hash"] and len(row["pw_hash"]) == 64 and len(row["salt"]) == 32


def test_change_password_needs_the_old_one_and_signs_other_devices_out():
    _, h1 = login("chen")
    _, h2 = login("chen")
    assert c.post("/api/auth/password", headers=h1, json={"old_password": "wrong", "new_password": "fresh-pass"}).status_code == 403
    assert c.post("/api/auth/password", headers=h1, json={"old_password": "123", "new_password": "12"}).status_code == 400
    assert c.post("/api/auth/password", headers=h1, json={"old_password": "123", "new_password": "fresh-pass"}).status_code == 200
    assert c.get("/api/auth/me", headers=h1).status_code == 200
    assert c.get("/api/auth/me", headers=h2).status_code == 401
    assert login("chen", "123")[0].status_code == 401 and login("chen", "fresh-pass")[0].status_code == 200


def test_logout_ends_the_token():
    _, h = login()
    assert c.post("/api/auth/logout", headers=h).status_code == 200
    assert c.get("/api/auth/me", headers=h).status_code == 401


def test_every_account_starts_a_blank_chat_with_no_preset_client_and_no_stored_greeting():
    _, h = login("wang")
    s = c.post("/api/conversations", headers=h).json()
    assert s["persona_id"] is None and s["name"] == "Mr. Wang" and s["next_question"]["id"] == "age"
    assert c.get(f"/api/conversations/{s['client_id']}", headers=h).json()["messages"] == []
    assert c.get(f"/api/state?client_id={s['client_id']}", headers=h).json()["profile"] is None


def test_chat_history_is_saved_listed_reopened_and_resumes_the_questionnaire():
    _, h = signup("historian")
    a = new_chat(h)
    chat(h, a, "hello")
    chat(h, a, "I would like some investment advice")
    chat(h, a, "I am 50")
    b = new_chat(h)
    listing = c.get("/api/conversations", headers=h).json()
    assert [x["id"] for x in listing] == [b, a] and listing[1]["title"] == "I would like some investment advice"
    from app import state
    state.HISTORY.clear(); state.PENDING_QUESTION.clear()
    out = c.get(f"/api/conversations/{a}", headers=h).json()
    assert [m["role"] for m in out["messages"]] == ["user", "agent"] * 3
    assert out["messages"][0]["text"] == "hello" and out["next_question"]["id"] == "horizon_years"
    r = chat(h, a, "in 8 years")
    assert r["question"]["id"] == "monthly_income_cny"


def test_chats_are_private_and_even_the_admin_cannot_read_them():
    _, hl = login("li")
    _, hc = login("chen")
    _, ha = login("admin")
    cid = new_chat(hl)
    for h in (hc, ha):
        assert c.get(f"/api/conversations/{cid}", headers=h).status_code == 403
        assert c.post("/api/chat", headers=h, json={"client_id": cid, "message": "hi"}).status_code == 403
        assert c.get(f"/api/state?client_id={cid}", headers=h).status_code == 403
        assert c.post(f"/api/conversations/{cid}/delete", headers=h).status_code == 403
        assert cid not in [x["id"] for x in c.get("/api/conversations", headers=h).json()]
    assert c.get("/api/audit", headers=hc).json() == []
    assert c.get(f"/api/audit?client_id={cid}", headers=hc).status_code == 403
    assert len(c.get("/api/audit", headers=ha).json()) > 0
    assert c.post("/api/conversations", headers=ha).status_code == 403


def test_delete_removes_the_chat_from_the_list():
    _, h = login("li")
    cid = new_chat(h)
    assert c.post(f"/api/conversations/{cid}/delete", headers=h).status_code == 200
    assert c.get("/api/conversations", headers=h).json() == []
    assert c.get(f"/api/conversations/{cid}", headers=h).status_code == 404


def test_titles_skip_greetings_and_questionnaire_answers_then_name_the_advice():
    _, h = login("li")
    assert c.post("/api/memory/demo", headers=h, json={"persona_id": "persona_li"}).status_code == 200
    cid = new_chat(h)
    for m in ["hello", "start", "Stable", "About 10%"]:
        chat(h, cid, m)
    assert c.get("/api/conversations", headers=h).json()[0]["title"] == "New chat"
    chat(h, cid, "Sell some")
    assert c.get("/api/conversations", headers=h).json()[0]["title"] == "Advice for Ms. Li"
    other = new_chat(h)
    chat(h, other, "What does the CSRC say about complex products?")
    assert c.get("/api/conversations", headers=h).json()[0]["title"].startswith("What does the CSRC say")


def test_sign_in_and_password_changes_are_in_the_audit_log_without_secrets():
    _, h = login("li")
    c.post("/api/auth/password", headers=h, json={"old_password": "123", "new_password": "brand-new-pw"})
    _, ha = login("admin")
    log = c.get("/api/audit", headers=ha).text
    assert '"login"' in log and "password_changed" in log and "brand-new-pw" not in log
    assert c.get("/api/audit/verify", headers=h).json()["valid"] is True


def test_greetings_get_a_greeting_and_other_topics_get_a_polite_redirect_without_the_questionnaire():
    _, h = signup("talker")
    cid = new_chat(h)
    hello = chat(h, cid, "hello")
    assert hello["reply"].startswith("Hello") and hello["trace"] == [] and hello["question"] is None
    off = chat(h, cid, "what is the weather in Paris")
    assert "wealth topics" in off["reply"] and off["trace"] == [] and off["question"] is None
    on = chat(h, cid, "I want some investment advice")
    assert on["question"]["id"] == "age"
