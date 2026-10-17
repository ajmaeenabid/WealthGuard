"""EN <-> ZH translation: detection, fixed disclaimers, re-checking of model output, endpoint limits."""
import pytest
from fastapi.testclient import TestClient

from app import config, translate
from app.agent import llm
from app.main import app
from app.security import audit

c = TestClient(app)


def test_detect_language():
    assert translate.detect("Hello, how are you?") == "en"
    assert translate.detect("你好，请给我建议") == "zh"
    assert translate.detect("P03 12%") == "en"
    assert translate.detect("我想买P03基金") == "zh"


def test_disclaimer_uses_fixed_translation_in_mock_mode(monkeypatch):
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    out, mode = translate.translate_one(config.DISCLAIMER, "zh")
    assert out == config.DISCLAIMER_ZH and mode == "glossary"
    back, mode = translate.translate_one(config.DISCLAIMER_ZH, "en")
    assert back == config.DISCLAIMER and mode == "glossary"


def test_mock_mode_never_guesses(monkeypatch):
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    text = "A balanced mix of bonds and cash suits your 8-year goal."
    assert translate.translate_one(text, "zh") == (text, "fallback")


def test_same_language_is_untouched():
    assert translate.translate_one("你好", "zh") == ("你好", "same")
    assert translate.translate_one("Hello", "en") == ("Hello", "same")


def _live(monkeypatch, reply):
    monkeypatch.setenv("USE_MOCK_LLM", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(llm, "complete", lambda *a, **k: reply)


def test_live_translation_accepted(monkeypatch):
    _live(monkeypatch, '{"t": "该组合以债券和现金为主，适合您的8年目标。"}')
    out, mode = translate.translate_one("Mostly bonds and cash for your 8-year goal.", "zh")
    assert mode == "llm" and "债券" in out


def test_live_translation_with_guarantee_wording_falls_back(monkeypatch):
    _live(monkeypatch, '{"t": "这款产品保证收益，稳赚不赔。"}')
    text = "This note has a higher yield but higher risk."
    assert translate.translate_one(text, "zh") == (text, "fallback")


def test_live_english_guarantee_wording_falls_back(monkeypatch):
    _live(monkeypatch, '{"t": "This fund is guaranteed to grow."}')
    text = "该基金风险较低。"
    assert translate.translate_one(text, "en") == (text, "fallback")


def test_live_disclaimer_is_restored_not_reworded(monkeypatch):
    seen = {}

    def fake(system, prompt, **k):
        seen["prompt"] = prompt
        return '{"t": "收益说明。[[S0]]"}'
    monkeypatch.setenv("USE_MOCK_LLM", "0"); monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(llm, "complete", fake)
    out, mode = translate.translate_one("Return note. " + config.DISCLAIMER, "zh")
    assert config.DISCLAIMER not in seen["prompt"]  # the model never sees the disclaimer
    assert out.endswith(config.DISCLAIMER_ZH) and mode == "llm"


def test_model_failure_falls_back(monkeypatch):
    monkeypatch.setenv("USE_MOCK_LLM", "0"); monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    def boom(*a, **k):
        raise RuntimeError("network")
    monkeypatch.setattr(llm, "complete", boom)
    assert translate.translate_one("Some text.", "zh") == ("Some text.", "fallback")


def test_endpoint_translates_and_audits(monkeypatch):
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    cid = c.post("/api/session", json={"persona_id": "persona_li"}).json()["client_id"]
    r = c.post("/api/translate", json={"client_id": cid, "target": "zh", "texts": [config.DISCLAIMER, "Hello"]})
    assert r.status_code == 200 and r.json()["texts"][0] == config.DISCLAIMER_ZH
    assert "translate" in [e["action"] for e in c.get("/api/audit", params={"client_id": cid}).json()]
    assert c.get("/api/audit/verify").json()["valid"]


@pytest.mark.parametrize("body,code", [
    ({"target": "fr", "texts": ["a"]}, 422),
    ({"target": "zh", "texts": ["a"] * 41}, 422),
    ({"target": "zh", "texts": ["a" * 2001]}, 422),
    ({"target": "zh", "texts": ["a"], "client_id": "nope"}, 404),
])
def test_endpoint_validation(body, code):
    assert c.post("/api/translate", json=body).status_code == code
