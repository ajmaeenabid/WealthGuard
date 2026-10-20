import os

import pytest

os.environ["WEALTHGUARD_NO_DOTENV"] = "1"
os.environ["USE_MOCK_LLM"] = "1"
os.environ["FX_PROVIDER"] = "off"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("WEALTHGUARD_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    monkeypatch.setenv("WEALTHGUARD_AUTH", "0")
    from app import state
    state.HISTORY.clear()
    yield


FAKE_RATES = [{"source": "er-api", "date": "2026-10-19", "rates": {"CNY": 6.69274, "BDT": 123.400189}},
              {"source": "fawaz", "date": "2026-10-19", "rates": {"CNY": 6.68315324, "BDT": 123.38683111}}]


@pytest.fixture
def fx_live(monkeypatch):
    from app.finance import fx
    monkeypatch.setenv("FX_PROVIDER", "auto")
    calls = {"n": 0, "data": [dict(r, rates=dict(r["rates"])) for r in FAKE_RATES]}

    def fake():
        calls["n"] += 1
        if calls["data"] is None:
            return []
        return [dict(r, rates=dict(r["rates"])) for r in calls["data"]]
    monkeypatch.setattr(fx, "_fetch_all", fake)
    return calls
