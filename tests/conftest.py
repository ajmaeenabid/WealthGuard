import os

import pytest

os.environ["WEALTHGUARD_NO_DOTENV"] = "1"  # never read a real key from .env during tests
os.environ["USE_MOCK_LLM"] = "1"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("WEALTHGUARD_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    monkeypatch.setenv("WEALTHGUARD_AUTH", "0")   # API tests call routes directly; tests/test_accounts.py turns sign-in on
    from app import state
    state.HISTORY.clear()
    yield
