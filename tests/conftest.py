import os

import pytest

os.environ["USE_MOCK_LLM"] = "1"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("WEALTHGUARD_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    from app import state
    state.HISTORY.clear()
    yield
