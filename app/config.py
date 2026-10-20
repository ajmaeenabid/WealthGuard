"""Environment variables, risk-bucket tables and limits."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_dotenv(path: str | None = None) -> int:
    path = path or os.path.join(ROOT, ".env")
    if not os.path.isfile(path):
        return 0
    n = 0
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            if k and v and k not in os.environ:
                os.environ[k] = v
                n += 1
    return n


if os.environ.get("WEALTHGUARD_NO_DOTENV") != "1":
    load_dotenv()

DISCLAIMER = "Educational demo with synthetic products. Not real financial advice."
DISCLAIMER_ZH = "教育演示，产品均为合成数据，不构成真实的投资建议。"

BUCKET_ORDER = ["Conservative", "Moderate", "Balanced", "Growth", "Aggressive"]

BUCKETS = {
    "Conservative": {"max_risk": 2, "max_equity_pct": 10, "max_single_pct": 40},
    "Moderate": {"max_risk": 3, "max_equity_pct": 30, "max_single_pct": 35},
    "Balanced": {"max_risk": 3, "max_equity_pct": 50, "max_single_pct": 30},
    "Growth": {"max_risk": 4, "max_equity_pct": 70, "max_single_pct": 30},
    "Aggressive": {"max_risk": 5, "max_equity_pct": 90, "max_single_pct": 30},
}

EQUITY_LIKE = {"equity_fund", "balanced_fund", "structured_note"}

TEMPLATES = {
    "Conservative": {"cash": 0.35, "bond": 0.55, "gold": 0.10},
    "Moderate": {"cash": 0.20, "bond": 0.50, "balanced_fund": 0.20, "gold": 0.10},
    "Balanced": {"cash": 0.10, "bond": 0.35, "balanced_fund": 0.20, "equity_fund": 0.25, "gold": 0.10},
    "Growth": {"cash": 0.05, "bond": 0.20, "balanced_fund": 0.20, "equity_fund": 0.45, "gold": 0.10},
    "Aggressive": {
        "cash": 0.05, "bond": 0.10, "balanced_fund": 0.15, "equity_fund": 0.50,
        "gold": 0.05, "structured_note": 0.15,
    },
}

VULNERABLE_AGE = 65
VULNERABLE_HORIZON_YEARS = 2
VULNERABLE_CAP_BUCKET = "Moderate"

MAX_REVISIONS = 3
MC_PATHS = 5000
MC_SEED = 42

URL_ALLOWLIST = ["https://api.anthropic.com", "https://api.groq.com"]


def qdrant_url() -> str | None:
    return (os.environ.get("QDRANT_URL") or "").strip().rstrip("/") or None


def qdrant_key() -> str | None:
    return (os.environ.get("QDRANT_API_KEY") or "").strip() or None


def qdrant_prefix() -> str:
    return (os.environ.get("QDRANT_COLLECTION") or "wealthguard_kb").strip()


def url_allowlist() -> list[str]:
    out = list(URL_ALLOWLIST)
    u = qdrant_url()
    if u:
        from urllib.parse import urlparse
        p = urlparse(u)
        if p.scheme == "https" and p.netloc:
            out.append(f"https://{p.netloc}")
    return out


def provider() -> str:
    p = os.environ.get("LLM_PROVIDER", "").lower()
    if p in ("anthropic", "groq"):
        return p
    return "anthropic" if os.environ.get("ANTHROPIC_API_KEY") or not os.environ.get("GROQ_API_KEY") else "groq"


def use_mock_llm() -> bool:
    key = "GROQ_API_KEY" if provider() == "groq" else "ANTHROPIC_API_KEY"
    return os.environ.get("USE_MOCK_LLM", "0") == "1" or not os.environ.get(key)


def describe_llm() -> str:
    if not use_mock_llm():
        return f"{provider()} (live), model {groq_model() if provider() == 'groq' else anthropic_model()}"
    if os.environ.get("USE_MOCK_LLM", "0") == "1":
        return "mock (USE_MOCK_LLM=1)"
    return f"mock (no {'GROQ' if provider() == 'groq' else 'ANTHROPIC'}_API_KEY found)"


def anthropic_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY")


def anthropic_model() -> str:
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")


def groq_key() -> str | None:
    return os.environ.get("GROQ_API_KEY")


def groq_model() -> str:
    return os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")


def db_path() -> str:
    default = os.path.join(os.getcwd(), "wealthguard.db")
    if os.environ.get("VERCEL"):
        import tempfile
        default = os.path.join(tempfile.gettempdir(), "wealthguard.db")
    return os.environ.get("WEALTHGUARD_DB", default)


def lower_bucket(a: str, b: str) -> str:
    return a if BUCKET_ORDER.index(a) <= BUCKET_ORDER.index(b) else b


def effective_bucket(bucket: str, age: int, horizon_years: float) -> str:
    if age >= VULNERABLE_AGE or horizon_years < VULNERABLE_HORIZON_YEARS:
        return lower_bucket(bucket, VULNERABLE_CAP_BUCKET)
    return bucket

RISK_WARNING = "Investing involves risk, and you can lose part or all of your capital."
PERF_DISCLAIMER = "Past performance is not a reliable indicator of future results."
FEE_MARKER = "annual fees"
