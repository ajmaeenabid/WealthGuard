import re
from pathlib import Path

import pytest

from app import envcheck
from app.finance import jurisdictions as J

ROOT = Path(__file__).resolve().parent.parent
SECRET = "sk-super-secret-value-123456"


def _rows(env):
    return {r["name"]: r for r in envcheck.audit(env)}


def test_every_environ_reference_is_in_the_registry():
    found = set()
    for folder in ("app", "api", "scripts"):
        for p in (ROOT / folder).rglob("*.py"):
            src = p.read_text(encoding="utf-8", errors="ignore")
            found |= set(re.findall(r"environ(?:\.get)?\(\s*[\"']([A-Z][A-Z0-9_]+)[\"']", src))
            found |= set(re.findall(r"environ\[\s*[\"']([A-Z][A-Z0-9_]+)[\"']", src))
            found |= set(re.findall(r"getenv\(\s*[\"']([A-Z][A-Z0-9_]+)[\"']", src))
    ours = {n for n in found if n.startswith(("GROQ", "FIN", "WEALTH", "QDRANT", "ANTHROPIC", "LLM", "USE_MOCK", "WHISPER", "RECEIPT"))}
    assert ours - set(envcheck.BY_NAME) == set()


def test_example_documents_every_registry_variable():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    names = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", example, re.M))
    assert set(envcheck.BY_NAME) - names == set()


def test_status_detection():
    r = _rows({"GROQ_API_KEY": "your-key-here", "FIN_AI_RPM": "abc", "FIN_AI_CONCURRENCY": "4", "FIN_TZ": "Nowhere/Land", "QDRANT_URL": "http://x"})
    assert r["GROQ_API_KEY"]["status"] == "placeholder"
    assert r["FIN_AI_RPM"]["status"] == "invalid"
    assert r["FIN_AI_CONCURRENCY"]["status"] == "set"
    assert r["FIN_TZ"]["status"] == "invalid"
    assert r["QDRANT_URL"]["status"] == "invalid"
    assert r["RECEIPT_KEY"]["status"] == "unset"


def test_no_secret_value_in_any_output(capsys):
    env = {"GROQ_API_KEY": SECRET, "RECEIPT_KEY": "short", "ANTHROPIC_API_KEY": SECRET, "LLM_PROVIDER": "bogus"}
    blob = repr(envcheck.audit(env)) + repr(envcheck.startup_report(env)) + repr(envcheck.cross_checks(env)) + repr(envcheck.feature_status(env))
    envcheck.enforce_at_startup(env)
    blob += capsys.readouterr().out
    assert SECRET not in blob and "short" not in blob


def test_feature_status_and_cross_checks():
    assert envcheck.feature_status({"GROQ_API_KEY": SECRET})["money_assistant_ai"] == "live"
    assert envcheck.feature_status({"GROQ_API_KEY": SECRET, "USE_MOCK_LLM": "1"})["money_assistant_ai"] == "built-in rules"
    assert envcheck.feature_status({})["speech_to_text"] == "browser speech only"
    assert any("ANTHROPIC_API_KEY" in m for m in envcheck.cross_checks({"LLM_PROVIDER": "anthropic"}))
    assert any("QDRANT" in m for m in envcheck.cross_checks({"QDRANT_URL": "https://x.io", "GROQ_API_KEY": SECRET}))


def test_strict_mode_stops_only_on_invalid():
    envcheck.enforce_at_startup({"FIN_AI_RPM": "abc"})  # warns, continues
    with pytest.raises(SystemExit) as e:
        envcheck.enforce_at_startup({"FIN_AI_RPM": "abc", "WEALTHGUARD_STRICT_CONFIG": "1"})
    assert "FIN_AI_RPM" in str(e.value) and "abc" not in str(e.value)
    envcheck.enforce_at_startup({"WEALTHGUARD_STRICT_CONFIG": "1"})  # nothing invalid


def test_jurisdiction_config_has_no_invented_rates_and_separates_currencies():
    assert set(J.codes()) == {"BD", "CN"}
    assert J.currency("BD") == "BDT" and J.currency("CN") == "CNY"
    for code in J.codes():
        d = J.details(code)
        assert d["unverified"] and d["sources"] and d["integrations"]["bank_sync"] is False
        assert not re.search(r"\d+(\.\d+)?\s*%", repr(d))
        assert d["supported_currencies"] == [d["currency"]]
    with pytest.raises(J.JurisdictionError):
        J.get("US")
