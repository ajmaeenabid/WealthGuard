"""Accounts, sign-in gate, saved chats and password change."""
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


def test_api_needs_sign_in_but_health_login_and_the_page_do_not():
    assert c.get("/").status_code == 200 and c.get("/api/health").status_code == 200
    for path in ["/api/products", "/api/personas", "/api/conversations", "/api/audit"]:
        assert c.get(path).status_code == 401, path
    assert c.post("/api/chat", json={"client_id": "x", "message": "hi"}).status_code == 401
    assert c.get("/api/products", headers={"Authorization": "Bearer nonsense"}).status_code == 401


@pytest.mark.parametrize("user,role,persona", [("admin", "admin", None), ("li", "client", "persona_li"),
                                               ("chen", "client", "persona_chen"), ("wang", "client", "persona_wang")])
def test_demo_accounts_exist_with_password_123(user, role, persona):
    r, h = login(user)
    assert r.status_code == 200 and r.json()["user"]["role"] == role and r.json()["user"]["persona_id"] == persona
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
    assert r.status_code == 200 and r.json()["user"]["username"] == "newbie" and r.json()["user"]["can_pick_persona"]
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
    assert c.get("/api/auth/me", headers=h1).status_code == 200      # this device stays signed in
    assert c.get("/api/auth/me", headers=h2).status_code == 401      # the other one does not
    assert login("chen", "123")[0].status_code == 401 and login("chen", "fresh-pass")[0].status_code == 200


def test_logout_ends_the_token():
    _, h = login()
    assert c.post("/api/auth/logout", headers=h).status_code == 200
    assert c.get("/api/auth/me", headers=h).status_code == 401


def test_new_chat_uses_the_accounts_own_client_and_cannot_be_redirected():
    _, h = login("wang")
    s = c.post("/api/conversations", headers=h, json={"persona_id": "persona_chen"}).json()
    assert s["persona_id"] == "persona_wang" and "Hello, Mr. Wang" in s["greeting"]


def test_a_blank_account_can_pick_a_persona_or_none():
    r = c.post("/api/auth/signup", json={"username": "freeuser", "password": "secret1"})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    assert c.post("/api/conversations", headers=h, json={"persona_id": "persona_chen"}).json()["persona_id"] == "persona_chen"
    assert c.post("/api/conversations", headers=h, json={}).json()["persona_id"] is None


def test_chat_history_is_saved_listed_reopened_and_resumes_the_questionnaire():
    _, h = login("li")
    a = c.post("/api/conversations", headers=h, json={}).json()["client_id"]
    c.post("/api/chat", headers=h, json={"client_id": a, "message": "hello"})
    c.post("/api/chat", headers=h, json={"client_id": a, "message": "Stable"})
    b = c.post("/api/conversations", headers=h, json={}).json()["client_id"]     # a second, separate chat
    listing = c.get("/api/conversations", headers=h).json()
    assert [x["id"] for x in listing] == [b, a] and {x["title"] for x in listing} == {"New chat"}
    from app import state
    state.HISTORY.clear(); state.PENDING_QUESTION.clear()                       # as after a server restart
    out = c.get(f"/api/conversations/{a}", headers=h).json()
    assert [m["role"] for m in out["messages"]] == ["agent", "user", "agent", "user", "agent"]
    assert out["messages"][1]["text"] == "hello" and out["next_question"]["id"] == "liquidity_need_pct"
    r = c.post("/api/chat", headers=h, json={"client_id": a, "message": "About 10%"}).json()   # answer lands on the right question
    assert r["question"]["id"] == "loss_reaction"


def test_chats_are_private_but_admin_can_see_everything():
    _, hl = login("li")
    _, hc = login("chen")
    _, ha = login("admin")
    cid = c.post("/api/conversations", headers=hl, json={}).json()["client_id"]
    assert c.get(f"/api/conversations/{cid}", headers=hc).status_code == 403
    assert c.post("/api/chat", headers=hc, json={"client_id": cid, "message": "hi"}).status_code == 403
    assert c.get(f"/api/state?client_id={cid}", headers=hc).status_code == 403
    assert c.post(f"/api/conversations/{cid}/delete", headers=hc).status_code == 403
    assert cid not in [x["id"] for x in c.get("/api/conversations", headers=hc).json()]
    assert cid in [x["id"] for x in c.get("/api/conversations", headers=ha).json()]
    assert c.get(f"/api/conversations/{cid}", headers=ha).status_code == 200


def test_delete_removes_the_chat_from_the_list():
    _, h = login("li")
    cid = c.post("/api/conversations", headers=h, json={}).json()["client_id"]
    assert c.post(f"/api/conversations/{cid}/delete", headers=h).status_code == 200
    assert c.get("/api/conversations", headers=h).json() == []
    assert c.get(f"/api/conversations/{cid}", headers=h).status_code == 404


def test_sign_in_and_password_changes_are_in_the_audit_log_without_secrets():
    _, h = login("li")
    c.post("/api/auth/password", headers=h, json={"old_password": "123", "new_password": "brand-new-pw"})
    log = c.get("/api/audit", headers=h).text
    assert '"login"' in log and "password_changed" in log and "brand-new-pw" not in log
    assert c.get("/api/audit/verify", headers=h).json()["valid"] is True


def test_titles_skip_greetings_and_questionnaire_answers_then_name_the_advice():
    _, h = login("li")
    cid = c.post("/api/conversations", headers=h, json={}).json()["client_id"]
    for m in ["hello", "Stable", "About 10%"]:
        c.post("/api/chat", headers=h, json={"client_id": cid, "message": m})
    assert c.get("/api/conversations", headers=h).json()[0]["title"] == "New chat"
    c.post("/api/chat", headers=h, json={"client_id": cid, "message": "Sell some"})
    assert c.get("/api/conversations", headers=h).json()[0]["title"] == "Advice for Ms. Li"
    other = c.post("/api/conversations", headers=h, json={}).json()["client_id"]
    c.post("/api/chat", headers=h, json={"client_id": other, "message": "What does the CSRC say about complex products?"})
    assert c.get("/api/conversations", headers=h).json()[0]["title"].startswith("What does the CSRC say")
