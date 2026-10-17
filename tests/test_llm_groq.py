import json

from app import config
from app.agent import llm


def test_provider_selection(monkeypatch):
    for k in ("LLM_PROVIDER", "ANTHROPIC_API_KEY", "GROQ_API_KEY", "USE_MOCK_LLM"):
        monkeypatch.delenv(k, raising=False)
    assert config.use_mock_llm()
    monkeypatch.setenv("GROQ_API_KEY", "x")
    assert config.provider() == "groq" and not config.use_mock_llm()
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    assert config.use_mock_llm()


def test_message_conversion():
    msgs = [{"role": "user", "content": "hi"},
            {"role": "assistant", "content": [{"type": "text", "text": "ok"},
                                              {"type": "tool_use", "id": "c1", "name": "list_products", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "{}"}]}]
    out = llm._to_openai_messages("sys", msgs)
    assert [m["role"] for m in out] == ["system", "user", "assistant", "tool"]
    assert out[2]["tool_calls"][0]["function"]["name"] == "list_products"
    assert out[3]["tool_call_id"] == "c1"


def test_groq_respond_parses_tool_calls(monkeypatch):
    monkeypatch.setattr(llm, "_groq_chat", lambda *a, **k: {
        "content": None, "tool_calls": [{"id": "c9", "function": {"name": "list_products", "arguments": "{}"}}]})
    r = llm._groq_respond("sys", [{"role": "user", "content": "hi"}],
                          [{"name": "list_products", "description": "d", "input_schema": {}}])
    assert r.tool_calls == [{"id": "c9", "name": "list_products", "input": {}}]
