"""The .env loader: parsing, precedence, safety (no secrets committed, never read during tests)."""
import os
import subprocess

import pytest

from app import config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = ["GROQ_API_KEY", "ANTHROPIC_API_KEY", "LLM_PROVIDER", "GROQ_MODEL", "USE_MOCK_LLM", "DEMO_X", "DEMO_Y", "DEMO_Z"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)


def write(tmp_path, text, encoding="utf-8"):
    p = tmp_path / ".env"
    p.write_bytes(text.encode(encoding))
    return str(p)


def test_parses_values_quotes_comments_and_blank_lines(tmp_path):
    path = write(tmp_path, "# comment\n\nDEMO_X=abc\nDEMO_Y = \"quoted value\"\nDEMO_Z='single'\nnot a pair\n")
    assert config.load_dotenv(path) == 3
    assert (os.environ["DEMO_X"], os.environ["DEMO_Y"], os.environ["DEMO_Z"]) == ("abc", "quoted value", "single")


def test_real_environment_wins_over_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_X", "from-shell")
    assert config.load_dotenv(write(tmp_path, "DEMO_X=from-file\nDEMO_Y=1\n")) == 1
    assert os.environ["DEMO_X"] == "from-shell" and os.environ["DEMO_Y"] == "1"


def test_empty_values_are_skipped_so_a_blank_template_stays_mock(tmp_path):
    assert config.load_dotenv(write(tmp_path, "GROQ_API_KEY=\nLLM_PROVIDER=groq\n")) == 1
    assert "GROQ_API_KEY" not in os.environ and config.use_mock_llm()


def test_windows_bom_and_crlf_are_handled(tmp_path):
    path = write(tmp_path, "DEMO_X=1\r\nDEMO_Y=2\r\n", "utf-8-sig")
    assert config.load_dotenv(path) == 2 and os.environ["DEMO_Y"] == "2"


def test_missing_file_is_fine(tmp_path):
    assert config.load_dotenv(str(tmp_path / "nope.env")) == 0


def test_key_from_env_file_switches_to_live_groq(tmp_path, monkeypatch):
    config.load_dotenv(write(tmp_path, "LLM_PROVIDER=groq\nGROQ_API_KEY=test-key-123\nGROQ_MODEL=m1\n"))
    monkeypatch.delenv("USE_MOCK_LLM", raising=False)
    assert not config.use_mock_llm() and config.provider() == "groq"
    d = config.describe_llm()
    assert "groq (live)" in d and "m1" in d and "test-key-123" not in d


def test_describe_llm_explains_why_it_is_mock(monkeypatch):
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    assert "USE_MOCK_LLM=1" in config.describe_llm()
    monkeypatch.delenv("USE_MOCK_LLM")
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    assert "no GROQ_API_KEY" in config.describe_llm()


def test_health_reports_the_active_model_without_secrets():
    from fastapi.testclient import TestClient
    from app.main import app
    body = TestClient(app).get("/api/health").json()
    assert "llm" in body and "key" not in body["llm"].lower().replace("no groq_api_key", "").replace("no anthropic_api_key", "")


def test_tests_never_load_the_developers_env_file():
    assert os.environ.get("WEALTHGUARD_NO_DOTENV") == "1"


def test_env_file_is_ignored_by_git_and_vercel_and_the_example_has_no_secret():
    assert ".env" in open(os.path.join(ROOT, ".gitignore")).read().splitlines()
    assert ".env" in open(os.path.join(ROOT, ".vercelignore")).read().splitlines()
    ex = open(os.path.join(ROOT, ".env.example"), encoding="utf-8").read()
    for line in ex.splitlines():
        if line.startswith(("GROQ_API_KEY=", "ANTHROPIC_API_KEY=")):
            assert line.split("=", 1)[1].strip() == "", line
    tracked = subprocess.run(["git", "ls-files", ".env"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    assert tracked == ""
