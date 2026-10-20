"""A slow or silent AI service ends in a clear error within a fixed time; long prompts are trimmed; the chats show progress, not silence."""
import json
from pathlib import Path

import pytest

from app.finance import ai, tokens
from app.finance.ai import AIError, GroqClient, _Resp

STATIC = Path(__file__).resolve().parent.parent / "static"
MSG = [{"role": "user", "content": "hi"}]


@pytest.fixture(autouse=True)
def live(monkeypatch):
    monkeypatch.setenv("USE_MOCK_LLM", "0")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_not_a_real_key")
    monkeypatch.setenv("FIN_AI_RPM", "0")
    monkeypatch.delenv("FIN_REASONING_EFFORT", raising=False)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_whole_call_gives_up_at_the_deadline_even_with_retries_left(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(ai.time, "monotonic", clock.monotonic)
    monkeypatch.setenv("FIN_AI_DEADLINE", "10")
    monkeypatch.setenv("FIN_AI_MAX_RETRIES", "50")
    monkeypatch.setenv("FIN_AI_MAX_WAIT", "5")
    calls = []

    def post(url, payload, headers, timeout):
        calls.append(timeout)
        clock.t += min(4, timeout)
        return _Resp(503, {}, {"error": {"message": "busy"}})
    with pytest.raises(AIError) as e:
        GroqClient(post=post, sleep=clock.sleep).chat(MSG, purpose="t")
    assert e.value.kind == "timeout" and clock.t - 1000.0 <= 12.5 and len(calls) <= 5


def test_a_silent_service_times_out_with_a_readable_message(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(ai.time, "monotonic", clock.monotonic)
    monkeypatch.setenv("FIN_AI_DEADLINE", "6")

    class ReadTimeout(Exception):
        pass

    def post(url, payload, headers, timeout):
        clock.t += timeout
        raise ReadTimeout()
    with pytest.raises(AIError) as e:
        GroqClient(post=post, sleep=clock.sleep).chat(MSG, purpose="t")
    assert e.value.kind == "timeout" and "in time" in e.value.message


def test_advisor_llm_trims_the_prompt_caps_output_and_has_a_deadline(monkeypatch):
    import httpx
    from app.agent import llm
    monkeypatch.setenv("FIN_AI_MAX_INPUT_TOKENS", "700")
    monkeypatch.setenv("FIN_AI_MAX_OUTPUT_TOKENS", "300")
    sent = {}

    class R:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url, json=None, timeout=None, headers=None):
        sent.update(json or {})
        sent["timeout"] = timeout
        return R()
    monkeypatch.setattr(httpx, "post", fake_post)
    big = [{"role": "system", "content": "s"}] + [{"role": "user" if i % 2 == 0 else "assistant", "content": "word " * 600} for i in range(30)]
    llm._groq_chat(big, max_tokens=5000)
    assert tokens.estimate(json.dumps(sent["messages"])) < 1100 and sent["max_tokens"] == 300 and sent["timeout"] <= 25


def test_advisor_failure_is_flagged_so_the_page_can_tell_the_person(monkeypatch):
    from app.agent import llm
    monkeypatch.setattr(llm, "_real_respond", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("slow")))
    state = {}
    r = llm.respond("sys", [{"role": "user", "content": "hello there, advise me"}], [], state)
    assert r.fallback is True and state["llm_error"] == "TimeoutError"


def test_chats_show_thinking_then_reveal_and_report_slow_or_failed_calls():
    think = (STATIC / "thinking.js").read_text(encoding="utf-8")
    assert "Still working" in think and "taking longer than usual" in think and "AbortController" in think
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    fin = (STATIC / "finance.js").read_text(encoding="utf-8")
    for js in (app, fin):
        assert "WGThinking.start" in js and "withTimeout" in js and "th.stop()" in js
    assert "llm_fallback" in app and 'r.ai === "fallback"' in fin
    assert "/static/thinking.js" in (STATIC / "index.html").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in think or "prefers-reduced-motion" in (STATIC / "styles.css").read_text(encoding="utf-8")
