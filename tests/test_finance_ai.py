"""The Groq client: structured output, retries with backoff, Retry-After, 429/401/timeout handling, pacing, usage and cost."""
import pytest

from app import db
from app.finance import ai
from app.finance.ai import AIError, GroqClient, _Resp


@pytest.fixture(autouse=True)
def live(monkeypatch):
    monkeypatch.setenv("USE_MOCK_LLM", "0")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_not_a_real_key")
    monkeypatch.setenv("FIN_AI_RPM", "0")
    monkeypatch.setenv("FIN_AI_MAX_WAIT", "5")
    monkeypatch.delenv("FIN_REASONING_EFFORT", raising=False)


def ok(content, pt=100, ct=40):
    body = {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": pt, "completion_tokens": ct}}
    return _Resp(200, {}, body)


def err(status, message="", **headers):
    return _Resp(status, headers, {"error": {"message": message}})


class Script:
    def __init__(self, *items):
        self.items, self.sent, self.slept = list(items), [], []

    def post(self, url, payload, headers, timeout):
        self.sent.append((url, payload, headers, timeout))
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def client(self):
        return GroqClient(post=self.post, sleep=self.slept.append)


SCHEMA = {"type": "object", "properties": {"intent": {"type": "string"}}, "required": ["intent"], "additionalProperties": False}
MSG = [{"role": "user", "content": "hi"}]


def test_request_uses_the_documented_endpoint_model_schema_and_a_bearer_key_that_is_never_logged(caplog):
    t = Script(ok('{"intent": "create"}'))
    r = t.client().chat(MSG, purpose="extract", schema=SCHEMA, schema_name="turn", user="alice", prompt_version="extract-v1")
    url, body, headers, timeout = t.sent[0]
    assert url == "https://api.groq.com/openai/v1/chat/completions" and body["model"] == "openai/gpt-oss-20b"
    assert body["response_format"] == {"type": "json_schema", "json_schema": {"name": "turn", "strict": True, "schema": SCHEMA}}
    assert headers["Authorization"].startswith("Bearer ") and "tools" not in body
    assert r.parsed == {"intent": "create"} and r.usage == {"prompt_tokens": 100, "completion_tokens": 40} and r.correlation_id
    assert "gsk_test" not in caplog.text


def test_usage_and_estimated_cost_are_recorded_with_prompt_version_and_correlation_id():
    Script(ok("{}", pt=2000, ct=500)).client().chat(MSG, purpose="report", user="alice", prompt_version="report-v3", correlation_id="abc123")
    row = db.connect().execute("SELECT * FROM fin_ai_usage").fetchone()
    assert (row["purpose"], row["prompt_version"], row["correlation_id"], row["status"], row["username"]) == ("report", "report-v3", "abc123", "ok", "alice")
    assert row["prompt_tokens"] == 2000 and row["est_cost_usd"] == pytest.approx((2000 * 0.075 + 500 * 0.30) / 1e6)
    s = ai.usage_summary("alice")
    assert s["calls"] == 1 and s["est_cost_usd"] > 0 and s["failed_calls"] == 0 and "report" in s["by_purpose"]
    assert ai.usage_summary("bob")["calls"] == 0


def test_prices_are_configurable_not_hardcoded(monkeypatch):
    monkeypatch.setenv("GROQ_PRICE_INPUT_PER_M", "1")
    monkeypatch.setenv("GROQ_PRICE_OUTPUT_PER_M", "2")
    assert ai.estimate_cost(1_000_000, 1_000_000) == 3.0


def test_a_429_is_retried_after_the_retry_after_header_then_succeeds():
    t = Script(err(429, "rate limit", **{"Retry-After": "3"}), ok('{"intent": "x"}'))
    r = t.client().chat(MSG, purpose="p", schema=SCHEMA)
    assert r.retries == 1 and len(t.sent) == 2 and t.slept and 3 <= t.slept[0] <= 5


def test_a_long_retry_after_is_not_waited_for_it_degrades_immediately():
    t = Script(err(429, "daily limit", **{"Retry-After": "600"}))
    with pytest.raises(AIError) as e:
        t.client().chat(MSG, purpose="p")
    assert e.value.kind == "rate_limited" and e.value.retry_after == 600 and len(t.sent) == 1 and t.slept == []


def test_retries_are_bounded_and_back_off_with_jitter(monkeypatch):
    monkeypatch.setenv("FIN_AI_MAX_RETRIES", "3")
    t = Script(err(503), err(503), err(503), err(503))
    with pytest.raises(AIError) as e:
        t.client().chat(MSG, purpose="p")
    assert e.value.kind == "unavailable" and len(t.sent) == 4 and len(t.slept) == 3
    assert all(0 <= s <= 5 for s in t.slept)
    row = db.connect().execute("SELECT status, retries FROM fin_ai_usage").fetchone()
    assert (row["status"], row["retries"]) == ("unavailable", 3)


def test_authentication_failures_are_not_retried_and_never_echo_the_key():
    t = Script(err(401, "invalid api key gsk_test_not_a_real_key"))
    with pytest.raises(AIError) as e:
        t.client().chat(MSG, purpose="p")
    assert e.value.kind == "auth" and len(t.sent) == 1 and "gsk_" not in e.value.message


def test_timeouts_and_network_errors_are_retried_then_reported_in_plain_words():
    class ReadTimeout(Exception):
        pass
    t = Script(ReadTimeout("slow"), ConnectionError("down"), ok("{}"))
    assert t.client().chat(MSG, purpose="p").retries == 2
    t = Script(*[ReadTimeout("slow")] * 4)
    with pytest.raises(AIError) as e:
        t.client().chat(MSG, purpose="p")
    assert e.value.kind == "timeout"


def test_a_malformed_model_reply_gets_one_repair_attempt_then_fails_cleanly():
    t = Script(ok("not json at all"), ok('{"intent": "fixed"}'))
    r = t.client().chat(MSG, purpose="p", schema=SCHEMA)
    assert r.parsed == {"intent": "fixed"} and "not valid" in t.sent[1][1]["messages"][-1]["content"]
    t = Script(ok("nope"), ok("still nope"))
    with pytest.raises(AIError) as e:
        t.client().chat(MSG, purpose="p", schema=SCHEMA)
    assert e.value.kind == "format"


def test_the_reply_is_validated_against_the_callers_model():
    def must_have_amount(d):
        assert "amount" in d
        return d
    t = Script(ok('{"intent": "x"}'), ok('{"amount": 5}'))
    assert t.client().chat(MSG, purpose="p", schema=SCHEMA, validate=must_have_amount).parsed == {"amount": 5}


def test_schema_mode_falls_back_to_json_object_mode_when_the_api_refuses_it():
    t = Script(err(400, "response_format json_schema is not supported"), ok('{"intent": "y"}'))
    r = t.client().chat(MSG, purpose="p", schema=SCHEMA)
    assert r.parsed == {"intent": "y"} and t.sent[1][1]["response_format"] == {"type": "json_object"}


def test_the_reasoning_parameter_is_dropped_if_the_api_rejects_it(monkeypatch):
    monkeypatch.setenv("FIN_REASONING_EFFORT", "low")
    t = Script(err(400, "unknown parameter: reasoning_effort"), ok("{}"))
    t.client().chat(MSG, purpose="p")
    assert t.sent[0][1]["reasoning_effort"] == "low" and "reasoning_effort" not in t.sent[1][1]


def test_without_a_key_or_in_mock_mode_the_client_refuses_without_touching_the_network(monkeypatch):
    t = Script()
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    with pytest.raises(AIError) as e:
        t.client().chat(MSG, purpose="p")
    assert e.value.kind == "disabled" and t.sent == [] and ai.enabled() is False
    monkeypatch.setenv("USE_MOCK_LLM", "0")
    monkeypatch.delenv("GROQ_API_KEY")
    assert ai.enabled() is False


def test_requests_are_paced_to_the_configured_rate(monkeypatch):
    monkeypatch.setenv("FIN_AI_RPM", "30")
    t = Script(ok("{}"), ok("{}"), ok("{}"))
    c = t.client()
    for _ in range(3):
        c.chat(MSG, purpose="p")
    assert len(t.slept) == 2 and 1.5 <= t.slept[0] <= 2.0 and 3.5 <= t.slept[1] <= 4.0
