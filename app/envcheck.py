"""Configuration inventory and validation. Reports variable names, presence and validity only; a value is never read into a report, logged or returned."""
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

PLACEHOLDERS = {"", "your-key-here", "your_key_here", "changeme", "change-me", "xxx", "xxxx", "todo", "none", "null", "replace-me", "<key>"}


def _num(lo: float, hi: float) -> Callable[[str], Optional[str]]:
    def check(v: str) -> Optional[str]:
        try:
            x = float(v)
        except ValueError:
            return "must be a number"
        return None if lo <= x <= hi else f"must be between {lo:g} and {hi:g}"
    return check


def _one_of(*opts: str) -> Callable[[str], Optional[str]]:
    return lambda v: None if v.lower() in opts else "must be one of: " + ", ".join(opts)


def _https(v: str) -> Optional[str]:
    return None if re.match(r"^https://[^\s/]+", v) else "must be an https URL"


def _tz(v: str) -> Optional[str]:
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(v)
        return None
    except Exception:
        return "is not a known time zone name (for example Asia/Dhaka); a fixed UTC+6 is used instead"


@dataclass
class Var:
    name: str
    purpose: str
    feature: str
    used_by: str
    requirement: str = "optional"
    secret: bool = False
    validator: Optional[Callable[[str], Optional[str]]] = None
    obtain: str = ""
    free: str = ""
    depends_on: list = field(default_factory=list)


REGISTRY = [
    Var("GROQ_API_KEY", "Key for Groq's OpenAI-compatible API (chat model, Whisper speech-to-text)", "Live AI chat, money assistant, report explanations, voice transcription",
        "app/config.py, app/finance/ai.py, app/transcribe.py", "conditional", True, None, "https://console.groq.com/keys",
        "Free tier with rate limits (the documented Developer-plan base for openai/gpt-oss-20b is 30 requests/min and 8K tokens/min); paid tiers need billing"),
    Var("GROQ_MODEL", "Model for the advisor chat", "Advisor chat", "app/config.py", "optional", False, None, "https://console.groq.com/docs/models", "Same key and limits as above"),
    Var("FINANCE_MODEL", "Model for the money assistant and report explanations (default openai/gpt-oss-20b)", "Money assistant", "app/finance/ai.py", "optional"),
    Var("LLM_PROVIDER", "Which provider answers the advisor chat: groq or anthropic", "Advisor chat", "app/config.py", "optional", False, _one_of("groq", "anthropic")),
    Var("ANTHROPIC_API_KEY", "Key for Anthropic's API", "Advisor chat when LLM_PROVIDER=anthropic", "app/config.py", "conditional", True, None, "https://console.anthropic.com/settings/keys",
        "No free API tier; requires billing"),
    Var("ANTHROPIC_MODEL", "Anthropic model name", "Advisor chat when LLM_PROVIDER=anthropic", "app/config.py"),
    Var("USE_MOCK_LLM", "1 forces the deterministic offline mock (demo safety net and tests)", "Offline mode", "app/config.py, app/finance/ai.py, app/transcribe.py", "optional", False, _one_of("0", "1")),
    Var("FIN_AI_TIMEOUT", "Seconds before an AI request times out", "Money assistant", "app/finance/ai.py", "optional", False, _num(1, 300)),
    Var("FIN_AI_MAX_RETRIES", "Retries on 429/5xx/timeouts (exponential backoff with jitter)", "Money assistant", "app/finance/ai.py", "optional", False, _num(0, 10)),
    Var("FIN_AI_CONCURRENCY", "Simultaneous AI calls", "Money assistant", "app/finance/ai.py", "optional", False, _num(1, 16)),
    Var("FIN_AI_RPM", "AI calls per minute the app allows itself (0 turns pacing off); keep below your account limit", "Money assistant", "app/finance/ai.py", "optional", False, _num(0, 10000)),
    Var("FIN_AI_DEADLINE", "Hard limit in seconds for one AI call including retries (default 25); after it the app shows a clear notice", "Money assistant", "app/finance/ai.py", "optional", False, _num(3, 300)),
    Var("WEALTHGUARD_LLM_DEADLINE", "Same hard limit for the advisor chat (default 30 seconds)", "Advisor chat", "app/agent/llm.py", "optional", False, _num(3, 300)),
    Var("FX_PROVIDER", "auto fetches real exchange rates (open.er-api.com, cross-checked with jsDelivr currency-api, no key needed); off disables conversion", "Currency conversion", "app/finance/fx.py", "optional", False, _one_of("auto", "off")),
    Var("FX_CACHE_HOURS", "How long a fetched rate table is reused before a new one is fetched (default 12)", "Currency conversion", "app/finance/fx.py", "optional", False, _num(0, 168)),
    Var("FX_MAX_STALE_HOURS", "If rate services cannot be reached, the last rate is still used for this many hours and flagged stale (default 72)", "Currency conversion", "app/finance/fx.py", "optional", False, _num(0, 720)),
    Var("FX_TIMEOUT", "Seconds to wait for each rate service (default 6)", "Currency conversion", "app/finance/fx.py", "optional", False, _num(1, 60)),
    Var("FIN_AI_MAX_WAIT", "Longest wait (seconds) for a rate-limit reset before falling back to the built-in rules", "Money assistant", "app/finance/ai.py", "optional", False, _num(0, 600)),
    Var("FIN_AI_MAX_INPUT_TOKENS", "Most estimated tokens sent to the model per request; older turns and long text are trimmed to fit (default 3500)", "Money assistant", "app/finance/tokens.py", "optional", False, _num(500, 100000)),
    Var("FIN_AI_MAX_OUTPUT_TOKENS", "Most tokens the model may write per reply (default 1200)", "Money assistant", "app/finance/tokens.py", "optional", False, _num(64, 8000)),
    Var("FIN_REASONING_EFFORT", "Reasoning effort for gpt-oss: low, medium or high", "Money assistant", "app/finance/ai.py", "optional", False, _one_of("low", "medium", "high")),
    Var("GROQ_PRICE_INPUT_PER_M", "USD per million input tokens for the cost estimate", "AI usage view", "app/finance/ai.py", "optional", False, _num(0, 1000)),
    Var("GROQ_PRICE_OUTPUT_PER_M", "USD per million output tokens for the cost estimate", "AI usage view", "app/finance/ai.py", "optional", False, _num(0, 1000)),
    Var("FIN_TZ", "Time zone for today/yesterday and transaction dates (default Asia/Dhaka)", "Money assistant, reports", "app/finance/money.py", "optional", False, _tz),
    Var("WHISPER_PROVIDER", "Speech-to-text engine: groq (default), local (faster-whisper) or off", "Voice input", "app/transcribe.py", "optional", False, _one_of("groq", "local", "off")),
    Var("WHISPER_MODEL", "Whisper model name (groq default whisper-large-v3-turbo; local default base)", "Voice input", "app/transcribe.py"),
    Var("QDRANT_URL", "https URL of a Qdrant Cloud cluster (REST port 6333)", "Vector database for the regulation knowledge base", "app/config.py", "optional", False, _https,
        "https://cloud.qdrant.io/", "Free 1 GB cluster (check current terms)"),
    Var("QDRANT_API_KEY", "Qdrant Cloud API key", "Vector database", "app/config.py", "conditional", True, None, "https://cloud.qdrant.io/", "Free cluster available"),
    Var("QDRANT_COLLECTION", "Collection name prefix", "Vector database", "app/config.py"),
    Var("RECEIPT_KEY", "Long random string that seals advice receipts (HMAC); if empty a key is stored with the database", "Verifiable advice receipts", "app/receipt.py", "optional", True,
        lambda v: None if len(v) >= 16 else "should be at least 16 characters"),
    Var("WEALTHGUARD_AUTH", "0 switches the sign-in requirement off (tests only; never in production)", "Sign-in", "app/accounts.py", "optional", False, _one_of("0", "1")),
    Var("WEALTHGUARD_DB", "Path of the SQLite database file (default ./wealthguard.db; on Vercel use /tmp)", "Storage", "app/config.py, api/index.py", "deployment"),
    Var("WEALTHGUARD_NO_DOTENV", "1 stops the app reading .env (tests)", "Configuration loading", "app/config.py", "optional", False, _one_of("0", "1")),
    Var("WEALTHGUARD_STRICT_CONFIG", "1 makes an invalid configuration value stop the server at startup", "Startup validation", "app/envcheck.py", "optional", False, _one_of("0", "1")),
]
BY_NAME = {v.name: v for v in REGISTRY}


def audit(environ: Optional[dict] = None) -> list[dict]:
    env = os.environ if environ is None else environ
    rows = []
    for v in REGISTRY:
        raw = env.get(v.name)
        status, problems = "unset", []
        if raw is not None and raw.strip() != "":
            status = "set"
            if raw.strip().lower() in PLACEHOLDERS:
                status, problems = "placeholder", ["still a placeholder; replace it with a real value"]
            elif v.validator:
                msg = v.validator(raw.strip())
                if msg:
                    status, problems = "invalid", [msg]
        elif raw is not None:
            status = "empty"
        rows.append({"name": v.name, "purpose": v.purpose, "requirement": v.requirement, "status": status, "problems": problems, "feature": v.feature,
                     "used_by": v.used_by, "obtain": v.obtain, "free": v.free, "secret": v.secret})
    return rows


def feature_status(environ: Optional[dict] = None) -> dict:
    env = os.environ if environ is None else environ
    ok = lambda n: (env.get(n) or "").strip().lower() not in PLACEHOLDERS
    mock = env.get("USE_MOCK_LLM") == "1"
    groq = ok("GROQ_API_KEY")
    provider = (env.get("LLM_PROVIDER") or "").lower()
    anth = ok("ANTHROPIC_API_KEY")
    live = not mock and ((provider == "anthropic" and anth) or (provider != "anthropic" and groq))
    return {"advisor_ai": "live" if live else "offline mock", "money_assistant_ai": "live" if (groq and not mock) else "built-in rules",
            "speech_to_text": "groq whisper" if (groq and (env.get("WHISPER_PROVIDER") or "groq").lower() == "groq") else
                              ("local faster-whisper" if (env.get("WHISPER_PROVIDER") or "").lower() == "local" else "browser speech only"),
            "vector_database": "qdrant cloud" if ok("QDRANT_URL") and ok("QDRANT_API_KEY") else "local index"}


def cross_checks(environ: Optional[dict] = None) -> list[str]:
    env = os.environ if environ is None else environ
    out = []
    has = lambda n: (env.get(n) or "").strip().lower() not in PLACEHOLDERS
    if (env.get("LLM_PROVIDER") or "").lower() == "anthropic" and not has("ANTHROPIC_API_KEY") and env.get("USE_MOCK_LLM") != "1":
        out.append("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set: the advisor chat will use the offline mock.")
    if has("QDRANT_URL") != has("QDRANT_API_KEY"):
        out.append("Only one of QDRANT_URL and QDRANT_API_KEY is set: the local vector index is used until both are present.")
    if (env.get("WHISPER_PROVIDER") or "groq").lower() == "groq" and not has("GROQ_API_KEY"):
        out.append("Speech transcription is on 'groq' but GROQ_API_KEY is not set: the browser's own speech recognition is the only voice input.")
    if env.get("WEALTHGUARD_AUTH") == "0":
        out.append("WEALTHGUARD_AUTH=0: sign-in is switched OFF. Use this only for tests.")
    return out


def startup_report(environ: Optional[dict] = None) -> dict:
    rows = audit(environ)
    bad = [r for r in rows if r["status"] in ("invalid", "placeholder")]
    return {"problems": [f"{r['name']}: {r['problems'][0]}" for r in bad] + cross_checks(environ), "features": feature_status(environ), "invalid": [r["name"] for r in bad]}


def enforce_at_startup(environ: Optional[dict] = None) -> dict:
    rep = startup_report(environ)
    for p in rep["problems"]:
        print(f"WealthGuard config warning: {p}", flush=True)
    f = rep["features"]
    print("WealthGuard features: advisor AI " + f["advisor_ai"] + ", money assistant " + f["money_assistant_ai"] + ", speech " + f["speech_to_text"] + ", vector DB " + f["vector_database"], flush=True)
    env = os.environ if environ is None else environ
    if env.get("WEALTHGUARD_STRICT_CONFIG") == "1" and rep["invalid"]:
        raise SystemExit("Invalid configuration: " + ", ".join(rep["invalid"]) + ". Fix these variables (values are not shown) or unset WEALTHGUARD_STRICT_CONFIG.")
    return rep
