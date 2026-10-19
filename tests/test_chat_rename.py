"""Renaming a chat in the chat list: owner only, plain text, length-limited, and kept when more messages arrive."""
import pytest
from fastapi.testclient import TestClient

from app import accounts
from app.main import app

c = TestClient(app)


@pytest.fixture(autouse=True)
def sign_in_required(monkeypatch):
    monkeypatch.setenv("WEALTHGUARD_AUTH", "1")
    accounts._FAILS.clear()


def login(user):
    r = c.post("/api/auth/login", json={"username": user, "password": "123"})
    return {"Authorization": "Bearer " + r.json()["token"]}


def new_chat(h):
    return c.post("/api/conversations", headers=h).json()["client_id"]


def rename(h, cid, title):
    return c.post(f"/api/conversations/{cid}/rename", headers=h, json={"title": title})


def titles(h):
    return {x["id"]: x["title"] for x in c.get("/api/conversations", headers=h).json()}


def test_owner_can_rename_and_the_list_shows_it():
    h = login("li")
    cid = new_chat(h)
    r = rename(h, cid, "  Retirement plan  ")
    assert r.status_code == 200 and r.json()["title"] == "Retirement plan"
    assert titles(h)[cid] == "Retirement plan"


def test_a_chosen_name_survives_later_messages():
    h = login("li")
    cid = new_chat(h)
    rename(h, cid, "My name for this")
    c.post("/api/chat", headers=h, json={"client_id": cid, "message": "Hello, I want to plan my savings for a house purchase"})
    assert titles(h)[cid] == "My name for this"


def test_other_accounts_cannot_rename_or_see_it():
    li, chen = login("li"), login("chen")
    cid = new_chat(li)
    assert rename(chen, cid, "hacked").status_code == 403
    assert titles(li)[cid] != "hacked"
    assert rename(li, "no-such-chat", "x").status_code == 404


@pytest.mark.parametrize("bad", ["", "   ", "x" * 61, "\n\t"])
def test_empty_or_too_long_names_are_refused(bad):
    h = login("li")
    cid = new_chat(h)
    assert rename(h, cid, bad).status_code in (400, 422)


def test_markup_is_stored_as_plain_text_and_the_page_renders_it_as_text():
    h = login("li")
    cid = new_chat(h)
    assert rename(h, cid, "<b>bold</b>").json()["title"] == "<b>bold</b>"
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "static" / "app.js").read_text(encoding="utf-8")
    assert 'querySelector(".ci-title").textContent = c.title' in js and "/rename" in js


def test_sign_in_is_required():
    assert c.post("/api/conversations/x/rename", json={"title": "a"}).status_code == 401
