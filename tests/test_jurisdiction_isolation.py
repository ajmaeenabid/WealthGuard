"""Language and jurisdiction preferences, and the isolation of conversations between jurisdictions."""
import uuid
from datetime import timedelta

import pytest

from app import store
from app.finance import assistant, books, money, settings
from app.finance.books import FinanceError

U, V = "alice", "bob"


def say(text, user=U):
    return assistant.turn(user, text, uuid.uuid4().hex)


@pytest.fixture
def cash():
    return books.create_account(U, "Cash", "cash", "5000", opening_date=(money.today() - timedelta(days=30)).isoformat())


def test_defaults_and_persistence():
    s = settings.get(U)
    assert (s["ui_lang"], s["jurisdiction"], s["voice_enabled"], s["speech_lang"]) == ("en", "BD", True, "auto")
    s = settings.update(U, {"ui_lang": "zh", "jurisdiction": "CN", "speech_lang": "bn", "large_text": True, "voice_enabled": False})
    assert (s["ui_lang"], s["jurisdiction"], s["speech_lang"], s["large_text"], s["voice_enabled"]) == ("zh", "CN", "bn", True, False)
    again = settings.get(U)                                   # a fresh read (as after a reload or a new login)
    assert again["ui_lang"] == "zh" and again["jurisdiction_config"]["currency"] == "CNY"
    assert settings.get(V)["ui_lang"] == "en"                 # another user is unaffected


@pytest.mark.parametrize("patch", [{"ui_lang": "fr"}, {"jurisdiction": "US"}, {"speech_lang": "xx"}, {"voice_enabled": "yes"}])
def test_invalid_preferences_are_rejected(patch):
    with pytest.raises(FinanceError):
        settings.update(U, patch)


def test_all_four_language_jurisdiction_combinations_are_storable():
    for lang in ("en", "bn", "zh"):
        for jur in ("BD", "CN"):
            s = settings.update(U, {"ui_lang": lang, "jurisdiction": jur})
            assert (s["ui_lang"], s["jurisdiction"]) == (lang, jur)


def test_changing_jurisdiction_starts_a_clean_conversation_and_keeps_old_one_as_history(cash):
    r = say("I spent 120 taka on tea")
    old = r["session_id"]
    assert r["jurisdiction"] == "BD" and r["state"] != "idle"
    res = settings.update(U, {"jurisdiction": "CN"})
    assert res["new_conversation"] is True
    cur = assistant.current(U)
    assert cur["session_id"] is None and cur["messages"] == [] and cur["jurisdiction"] == "CN"      # nothing inherited
    hist = {c["id"]: c for c in assistant.list_sessions(U)["conversations"]}
    assert hist[old]["jurisdiction"] == "BD" and hist[old]["currency"] == "BDT" and hist[old]["open"] and not hist[old]["active_jurisdiction"]
    nxt = say("I spent 30 on lunch")
    assert nxt["session_id"] != old and nxt["jurisdiction"] == "CN"
    # the old pending entry was not touched by the new message
    row = books._one("SELECT state FROM fin_sessions WHERE id=?", (old,))
    assert row["state"] in ("collecting", "awaiting_clarification", "awaiting_confirmation")
    assert all("tea" not in m["text"] for m in assistant.messages(U, nxt["session_id"]))


def test_records_survive_a_jurisdiction_change(cash):
    say("I spent 850 taka at the grocery store today on rice")
    say("yes")
    before = books.list_transactions(U)["total"]
    settings.update(U, {"jurisdiction": "CN"})
    settings.update(U, {"jurisdiction": "BD"})
    assert books.list_transactions(U)["total"] == before and books.list_accounts(U)[0]["currency"] == "BDT"


def test_explicit_resume_returns_to_the_original_jurisdiction_and_state(cash):
    old = say("I spent 120 taka on tea")["session_id"]
    settings.update(U, {"jurisdiction": "CN"})
    out = assistant.resume(U, old)
    assert out["session_id"] == old and out["jurisdiction"] == "BD" and settings.get(U)["jurisdiction"] == "BD"


def test_a_finished_conversation_cannot_be_resumed(cash):
    sid = say("I spent 850 taka at the grocery store today on rice")["session_id"]
    say("yes")
    settings.update(U, {"jurisdiction": "CN"})
    with pytest.raises(FinanceError) as e:
        assistant.resume(U, sid)
    assert e.value.status == 409


def test_conversations_are_private_between_users(cash):
    sid = say("I spent 120 taka on tea")["session_id"]
    with pytest.raises(FinanceError) as e:
        assistant.resume(V, sid)
    assert e.value.status == 404
    with pytest.raises(FinanceError):
        assistant.messages(V, sid)
    assert assistant.list_sessions(V)["conversations"] == []


def test_sessions_record_language_jurisdiction_and_config_version(cash):
    settings.update(U, {"ui_lang": "bn"})
    r = say("I spent 120 taka on tea")
    row = books._one("SELECT jurisdiction, language, config_version FROM fin_sessions WHERE id=?", (r["session_id"],))
    assert (row["jurisdiction"], row["language"]) == ("BD", "bn") and row["config_version"]
    store  # noqa
