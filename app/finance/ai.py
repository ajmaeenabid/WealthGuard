"""The one place the finance module talks to Groq (openai/gpt-oss-20b through the OpenAI-compatible endpoint).

Verified against the Groq documentation on 2026-10-19:
  * model openai/gpt-oss-20b: 131,072-token context, tool use, JSON object mode and json_schema structured outputs
    with strict:true (structured outputs cannot be combined with tool use or streaming, so this client uses structured
    outputs and the application, not the model, performs every action);
  * limits are per organisation and tier (the documented Developer-plan base for this model is 30 requests/min and
    8K tokens/min), so the client paces itself, honours Retry-After, and never assumes a limit it was not told.
Nothing here reaches the browser: the key is read from the environment on the server only.
"""
import json
import logging
import os
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app import config, db, store

log = logging.getLogger("wealthguard.ai")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-20b"
# USD per million tokens, from the Groq model page on 2026-10-19; override with GROQ_PRICE_INPUT_PER_M / GROQ_PRICE_OUTPUT_PER_M
DEFAULT_PRICES = (0.075, 0.30)


class AIError(Exception):
    """kind: disabled | auth | rate_limited | timeout | unavailable | format"""
    def __init__(self, kind: str, message: str, *, retry_after: Optional[float] = None, correlation_id: str = ""):
        super().__init__(message)
        self.kind, self.message, self.retry_after, self.correlation_id = kind, message, retry_after, correlation_id


@dataclass
class AIResult:
    content: str
    parsed: Any = None
    usage: dict = field(default_factory=dict)
    correlation_id: str = ""
    retries: int = 0
    latency_ms: int = 0
    model: str = DEFAULT_MODEL
    est_cost_usd: Optional[float] = None


def _env_num(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


def enabled() -> bool:
    """Live AI is on only when a Groq key exists and the mock switch is off. Otherwise callers use their offline path."""
    return os.environ.get("USE_MOCK_LLM", "0") != "1" and bool(config.groq_key())


def model_name() -> str:
    return os.environ.get("FINANCE_MODEL", DEFAULT_MODEL)


def estimate_cost(prompt_tokens: int, completion_tokens: int) -> Optional[float]:
    pin = _env_num("GROQ_PRICE_INPUT_PER_M", DEFAULT_PRICES[0])
    pout = _env_num("GROQ_PRICE_OUTPUT_PER_M", DEFAULT_PRICES[1])
    return round((prompt_tokens * pin + completion_tokens * pout) / 1_000_000, 8)


class _Resp:                       # the small surface of an HTTP response this client relies on
    def __init__(self, status_code: int, headers: dict, body: Any):
        self.status_code, self.headers, self.body = status_code, {k.lower(): v for k, v in headers.items()}, body


def _httpx_post(url: str, payload: dict, headers: dict, timeout: float) -> _Resp:
    import httpx
    r = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    try:
        body = r.json()
    except ValueError:
        body = {"error": {"message": r.text[:200]}}
    return _Resp(r.status_code, dict(r.headers), body)


class GroqClient:
    def __init__(self, *, post: Callable = _httpx_post, sleep: Callable = time.sleep, base_url: str = GROQ_BASE_URL,
                 key_getter: Callable = config.groq_key):
        self._post, self._sleep, self.base_url, self._key = post, sleep, base_url.rstrip("/"), key_getter
        self._gate = threading.BoundedSemaphore(int(_env_num("FIN_AI_CONCURRENCY", 2)))
        self._pace = threading.Lock()
        self._next_slot = 0.0

    # ---- pacing: at most FIN_AI_RPM request starts per minute, at most FIN_AI_CONCURRENCY in flight
    def _wait_for_slot(self) -> None:
        rpm = _env_num("FIN_AI_RPM", 20)
        if rpm <= 0:                                                        # 0 switches pacing off
            return
        interval = 60.0 / rpm
        with self._pace:
            now = time.monotonic()
            wait = max(0.0, self._next_slot - now)
            self._next_slot = max(now, self._next_slot) + interval
        if wait > 0:
            self._sleep(min(wait, 30))

    def _backoff(self, attempt: int, retry_after: Optional[float]) -> float:
        cap = _env_num("FIN_AI_MAX_WAIT", 20)
        jitter = random.uniform(0, min(cap, 1.0 * (2 ** attempt)))          # full jitter
        return min(cap, max(retry_after or 0.0, jitter)) if retry_after else jitter

    def chat(self, messages: list, *, purpose: str, user: Optional[str] = None, schema: Optional[dict] = None,
             schema_name: str = "result", validate: Optional[Callable[[Any], Any]] = None, max_tokens: int = 1500,
             temperature: float = 0.1, prompt_version: str = "v1", correlation_id: Optional[str] = None) -> AIResult:
        cid = correlation_id or uuid.uuid4().hex[:12]
        key = self._key()
        if os.environ.get("USE_MOCK_LLM", "0") == "1" or not key:
            raise AIError("disabled", "The AI service is not configured.", correlation_id=cid)
        started = time.monotonic()
        retries, repaired, dropped = 0, False, set()
        msgs = list(messages)
        max_retries = int(_env_num("FIN_AI_MAX_RETRIES", 3))
        timeout = _env_num("FIN_AI_TIMEOUT", 30)
        status_label = "ok"
        try:
            while True:
                body = {"model": model_name(), "messages": msgs, "max_tokens": max_tokens, "temperature": temperature}
                effort = os.environ.get("FIN_REASONING_EFFORT", "low")
                if effort and "reasoning" not in dropped:
                    body["reasoning_effort"] = effort
                if schema and "schema" not in dropped:
                    body["response_format"] = {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}}
                elif schema:
                    body["response_format"] = {"type": "json_object"}
                self._gate.acquire()
                try:
                    self._wait_for_slot()
                    try:
                        resp = self._post(f"{self.base_url}/chat/completions", body, {"Authorization": f"Bearer {key}"}, timeout)
                    except Exception as e:                                  # network failure or timeout
                        kind = "timeout" if "timeout" in type(e).__name__.lower() else "unavailable"
                        if retries >= max_retries:
                            raise AIError(kind, "The AI service did not answer in time." if kind == "timeout" else "The AI service could not be reached.", correlation_id=cid)
                        retries += 1
                        self._sleep(self._backoff(retries, None))
                        continue
                finally:
                    self._gate.release()
                sc = resp.status_code
                if sc == 200:
                    result = self._finish(resp, cid, retries, started, schema, validate, user, purpose, prompt_version)
                    if result is not None:
                        return result
                    # the reply was not valid JSON for the schema: one repair attempt, then give up
                    if repaired:
                        raise AIError("format", "The AI reply could not be understood.", correlation_id=cid)
                    repaired = True
                    msgs = msgs + [{"role": "assistant", "content": (resp.body["choices"][0]["message"].get("content") or "")[:1500]},
                                   {"role": "user", "content": "That reply was not valid. Return only one JSON object that matches the schema exactly."}]
                    retries += 1
                    continue
                msg = str((resp.body or {}).get("error", {}).get("message", ""))[:200] if isinstance(resp.body, dict) else ""
                if sc in (401, 403):
                    raise AIError("auth", "The AI service rejected the API key.", correlation_id=cid)
                if sc == 400 and "reasoning" in msg.lower() and "reasoning" not in dropped:
                    dropped.add("reasoning")
                    continue
                if sc == 400 and schema and "schema" not in dropped:         # model or schema mode refused: fall back to JSON object mode
                    dropped.add("schema")
                    msgs = msgs + [{"role": "user", "content": "Reply with one JSON object only. Schema: " + json.dumps(schema)[:2500]}]
                    continue
                if sc in (429, 500, 502, 503, 504):
                    ra = None
                    try:
                        ra = float(resp.headers.get("retry-after")) if resp.headers.get("retry-after") else None
                    except ValueError:
                        ra = None
                    too_long = ra is not None and ra > _env_num("FIN_AI_MAX_WAIT", 20)
                    if retries >= max_retries or too_long:
                        kind = "rate_limited" if sc == 429 else "unavailable"
                        raise AIError(kind, "The AI service is busy right now." if sc == 429 else "The AI service is temporarily unavailable.",
                                      retry_after=ra, correlation_id=cid)
                    retries += 1
                    self._sleep(self._backoff(retries, ra))
                    continue
                raise AIError("unavailable", f"The AI service returned an unexpected error ({sc}).", correlation_id=cid)
        except AIError as e:
            status_label = e.kind
            raise
        finally:
            ms = int((time.monotonic() - started) * 1000)
            if status_label != "ok":
                self._record(user, purpose, prompt_version, cid, {}, ms, retries, status_label)
            log.info("ai purpose=%s cid=%s status=%s retries=%s ms=%s", purpose, cid, status_label, retries, ms)

    def _finish(self, resp: _Resp, cid: str, retries: int, started: float, schema, validate, user, purpose, version) -> Optional[AIResult]:
        try:
            choice = resp.body["choices"][0]["message"]
            content = choice.get("content") or ""
            usage = resp.body.get("usage") or {}
        except (KeyError, IndexError, TypeError):
            return None
        parsed = None
        if schema:
            try:
                parsed = json.loads(content)
                if validate:
                    parsed = validate(parsed)
            except Exception:
                return None
        pt, ct = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
        cost = estimate_cost(pt, ct)
        ms = int((time.monotonic() - started) * 1000)
        res = AIResult(content=content, parsed=parsed, usage={"prompt_tokens": pt, "completion_tokens": ct}, correlation_id=cid,
                       retries=retries, latency_ms=ms, model=model_name(), est_cost_usd=cost)
        self._record(user, purpose, version, cid, res.usage, ms, retries, "ok", cost)
        return res

    def _record(self, user, purpose, version, cid, usage, ms, retries, status, cost=None) -> None:
        try:
            store._write("INSERT INTO fin_ai_usage (ts, username, purpose, model, prompt_version, correlation_id, prompt_tokens, "
                         "completion_tokens, est_cost_usd, latency_ms, retries, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (store.now(), user, purpose, model_name(), version, cid, usage.get("prompt_tokens"), usage.get("completion_tokens"),
                          cost, ms, retries, status))
        except Exception:                                       # usage logging must never break a user request
            log.warning("could not record ai usage cid=%s", cid)


_CLIENT: Optional[GroqClient] = None


def client() -> GroqClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = GroqClient()
    return _CLIENT


def call(messages: list, **kw) -> AIResult:
    """Module-level entry point used by the assistant and reports; tests replace `client()` or this function."""
    return client().chat(messages, **kw)


def usage_summary(user: Optional[str] = None, days: int = 30) -> dict:
    from datetime import date, timedelta
    where, args = "ts >= ?", [(date.today() - timedelta(days=days)).isoformat()]
    if user:
        where += " AND username=?"
        args.append(user)
    c = db.connect()
    try:
        r = c.execute(f"SELECT COUNT(*) AS calls, COALESCE(SUM(prompt_tokens),0) AS pt, COALESCE(SUM(completion_tokens),0) AS ct, "
                      f"COALESCE(SUM(est_cost_usd),0) AS cost, COALESCE(SUM(CASE WHEN status<>'ok' THEN 1 ELSE 0 END),0) AS failed, "
                      f"COALESCE(AVG(latency_ms),0) AS ms FROM fin_ai_usage WHERE {where}", tuple(args)).fetchone()
        by = c.execute(f"SELECT purpose, COUNT(*) AS n, COALESCE(SUM(est_cost_usd),0) AS cost FROM fin_ai_usage WHERE {where} GROUP BY purpose", tuple(args)).fetchall()
    finally:
        c.close()
    return {"days": days, "model": model_name(), "calls": r["calls"], "prompt_tokens": r["pt"], "completion_tokens": r["ct"],
            "est_cost_usd": round(r["cost"], 6), "failed_calls": r["failed"], "avg_latency_ms": int(r["ms"]),
            "by_purpose": {x["purpose"]: {"calls": x["n"], "est_cost_usd": round(x["cost"], 6)} for x in by},
            "prices_usd_per_million": {"input": _env_num("GROQ_PRICE_INPUT_PER_M", DEFAULT_PRICES[0]),
                                      "output": _env_num("GROQ_PRICE_OUTPUT_PER_M", DEFAULT_PRICES[1])},
            "note": "Estimates from token counts and the configured per-million prices; your Groq invoice is authoritative."}
