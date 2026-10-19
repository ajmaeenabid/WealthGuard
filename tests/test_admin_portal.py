"""Admin portal: live account data, create / sign out / delete, activity feed, and the page wiring."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import accounts, store
from app.main import app

c = TestClient(app)


@pytest.fixture(autouse=True)
def sign_in_required(monkeypatch):
    monkeypatch.setenv("WEALTHGUARD_AUTH", "1")
    accounts._FAILS.clear()


def login(user, pw="123"):
    r = c.post("/api/auth/login", json={"username": user, "password": pw})
    return r, ({"Authorization": "Bearer " + r.json()["token"]} if r.status_code == 200 else {})


def admin():
    return login("admin")[1]


def new_chat(h):
    return c.post("/api/conversations", headers=h).json()["client_id"]


def chat(h, cid, message):
    return c.post("/api/chat", headers=h, json={"client_id": cid, "message": message}).json()


def test_account_list_carries_live_figures_and_a_summary():
    ha = admin()
    login("li"); login("li")
    out = c.get("/api/admin/users", headers=ha).json()
    li = next(u for u in out["users"] if u["username"] == "li")
    assert li["login_count"] == 2 and li["last_login"] and li["active_sessions"] == 2 and li["chats"] == 0
    s = out["summary"]
    assert (s["total"], s["active"], s["suspended"], s["admins"], s["members"]) == (4, 4, 0, 1, 3)
    assert s["signed_in_24h"] >= 2 and s["active_sessions"] >= 3 and s["never_signed_in"] == 2 and s["new_7_days"] == 4
    hc = login("chen")[1]
    chat(hc, new_chat(hc), "hello")
    c.post("/api/admin/users/wang/ban", headers=ha, json={"banned": True})
    s2 = c.get("/api/admin/users", headers=ha).json()["summary"]
    assert s2["suspended"] == 1 and s2["active"] == 3 and s2["chats"] == 1


def test_admin_can_create_accounts_with_validation_and_the_new_member_can_sign_in():
    ha = admin()
    r = c.post("/api/admin/users", headers=ha, json={"username": "Maya.K", "password": "temp-pass-1", "display_name": "Maya", "role": "client"})
    assert r.status_code == 200 and r.json()["username"] == "maya.k" and r.json()["role"] == "client"
    assert login("maya.k", "temp-pass-1")[0].status_code == 200
    assert c.post("/api/admin/users", headers=ha, json={"username": "maya.k", "password": "temp-pass-1"}).status_code == 409
    assert c.post("/api/admin/users", headers=ha, json={"username": "x", "password": "temp-pass-1"}).status_code == 400
    assert c.post("/api/admin/users", headers=ha, json={"username": "okname", "password": "123"}).status_code == 400
    assert c.post("/api/admin/users", headers=ha, json={"username": "okname", "password": "temp-pass-1", "role": "wizard"}).status_code == 400
    assert c.post("/api/admin/users", headers=login("li")[1], json={"username": "sneaky", "password": "temp-pass-1"}).status_code == 403
    assert c.post("/api/admin/users", headers=ha, json={"username": "boss", "password": "temp-pass-1", "role": "admin"}).json()["role"] == "admin"


def test_sign_out_everywhere_revokes_every_session_of_that_account_only():
    ha = admin()
    _, h1 = login("li")
    _, h2 = login("li")
    _, hc = login("chen")
    assert c.post("/api/admin/users/li/signout", headers=ha).json() == {"signed_out": 2}
    assert c.get("/api/auth/me", headers=h1).status_code == 401 and c.get("/api/auth/me", headers=h2).status_code == 401
    assert c.get("/api/auth/me", headers=hc).status_code == 200
    assert login("li")[0].status_code == 200                                      # not suspended: they can sign in again
    assert c.post("/api/admin/users/nobody/signout", headers=ha).status_code == 404
    assert c.post("/api/admin/users/li/signout", headers=hc).status_code == 403


def test_deleting_an_account_removes_it_and_everything_it_owns_and_nothing_else():
    ha = admin()
    _, hl = login("li")
    _, hc = login("chen")
    cid = new_chat(hl)
    chat(hl, cid, "remember that I prefer low fees")
    acc = c.post("/api/fin/accounts", headers=hl, json={"name": "Cash", "type": "cash", "opening_balance": "100"}).json()
    c.post("/api/fin/transactions", headers=hl, json={"type": "expense", "account_id": acc["id"], "amount": "5", "category": "food"})
    other = new_chat(hc)
    chat(hc, other, "hello")
    c.post("/api/fin/accounts", headers=hc, json={"name": "Cash", "type": "cash", "opening_balance": "50"})
    assert c.post("/api/admin/users/li/delete", headers=ha, json={"confirm": "wrong"}).status_code == 400
    assert c.post("/api/admin/users/admin/delete", headers=ha, json={"confirm": "admin"}).status_code == 400          # not yourself
    r = c.post("/api/admin/users/li/delete", headers=ha, json={"confirm": "LI"})                                      # confirmation is case-insensitive
    assert r.status_code == 200 and r.json() == {"deleted": "li", "conversations": 1}
    for table in ("users", "conversations", "memories", "fin_accounts", "fin_transactions", "auth_tokens"):
        assert store._one(f"SELECT COUNT(*) AS n FROM {table} WHERE username='li'", ())["n"] == 0, table
    assert store._one("SELECT COUNT(*) AS n FROM clients WHERE id=?", (cid,))["n"] == 0
    assert store._one("SELECT COUNT(*) AS n FROM messages WHERE client_id=?", (cid,))["n"] == 0
    assert login("li")[0].status_code == 401 and c.get("/api/auth/me", headers=hl).status_code == 401
    assert c.get("/api/fin/accounts", headers=hc).json()[0]["name"] == "Cash" and c.get(f"/api/conversations/{other}", headers=hc).status_code == 200   # chen untouched
    assert "admin_user_deleted" in c.get("/api/admin/activity", headers=ha).text


def test_the_last_administrator_cannot_be_deleted_and_members_cannot_use_the_portal_endpoints():
    ha = admin()
    c.post("/api/admin/users", headers=ha, json={"username": "boss", "password": "temp-pass-1", "role": "admin"})
    hb = login("boss", "temp-pass-1")[1]
    c.post("/api/admin/users/admin/ban", headers=hb, json={"banned": True})                     # boss suspends the original admin
    r = c.post("/api/admin/users/boss/delete", headers=hb, json={"confirm": "boss"})
    assert r.status_code == 400                                                               # cannot delete yourself
    hm = login("wang")[1]
    for method, path, body in [("get", "/api/admin/activity", None), ("post", "/api/admin/users/li/signout", None), ("post", "/api/admin/users/li/delete", {"confirm": "li"})]:
        r = getattr(c, method)(path, headers=hm, **({"json": body} if body else {}))
        assert r.status_code == 403, path


def test_the_activity_feed_shows_sign_ins_and_admin_actions_but_never_contents():
    ha = admin()
    _, hl = login("li")
    c.post("/api/admin/users/wang/ban", headers=ha, json={"banned": True})
    c.post("/api/admin/users/chen/permissions", headers=ha, json={"permissions": {"ledger": False}})
    c.post("/api/auth/password", headers=hl, json={"old_password": "123", "new_password": "a-new-pass1"})
    out = c.get("/api/admin/activity?limit=20", headers=ha).json()["entries"]
    acts = [e["action"] for e in out]
    assert {"login", "admin_suspend", "admin_permissions", "password_changed"} <= set(acts)
    assert out[0]["ts"] >= out[-1]["ts"] and "a-new-pass1" not in str(out)
    assert next(e for e in out if e["action"] == "admin_suspend")["detail"] == {"admin": "admin", "target": "wang"}


def test_the_admin_page_wiring_is_independent_of_the_advisor_screens():
    app_js = Path("static/app.js").read_text(encoding="utf-8")
    admin_js = Path("static/admin.js").read_text(encoding="utf-8")
    html = Path("static/index.html").read_text(encoding="utf-8")
    start = app_js.index("async function init() {")
    assert start < app_js.index('if (me.role === "admin") return;', start) < app_js.index("await Promise.all", start)       # before any advisor request
    assert "WGAuth.onReady(init)" in admin_js and html.index("/static/admin.js") > html.index("/static/auth.js")
    for ep in ["/users", "/activity", "/signout", "/delete", "/ban", "/role", "/permissions", "/password", "/ai-usage"]:
        assert ep in admin_js, ep
