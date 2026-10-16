"""Environment variables, risk-bucket tables and limits."""
import os

DISCLAIMER = "Educational demo with synthetic products. Not real financial advice."

BUCKET_ORDER = ["Conservative", "Moderate", "Balanced", "Growth", "Aggressive"]

# bucket -> limits (CLAUDE.md table)
BUCKETS = {
    "Conservative": {"max_risk": 2, "max_equity_pct": 10, "max_single_pct": 40},
    "Moderate": {"max_risk": 3, "max_equity_pct": 30, "max_single_pct": 35},
    "Balanced": {"max_risk": 3, "max_equity_pct": 50, "max_single_pct": 30},
    "Growth": {"max_risk": 4, "max_equity_pct": 70, "max_single_pct": 30},
    "Aggressive": {"max_risk": 5, "max_equity_pct": 90, "max_single_pct": 30},
}

# asset classes counted towards the "equity-like" limit
EQUITY_LIKE = {"equity_fund", "balanced_fund", "structured_note"}

# Template weights per asset class (sum = 1) used as the allocation starting point.
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

# URL allowlist for any outbound call (T3: anything else is refused).
URL_ALLOWLIST = ["https://api.anthropic.com"]


def use_mock_llm() -> bool:
    return os.environ.get("USE_MOCK_LLM", "0") == "1" or not os.environ.get("ANTHROPIC_API_KEY")


def anthropic_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY")


def anthropic_model() -> str:
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")


def db_path() -> str:
    return os.environ.get("WEALTHGUARD_DB", os.path.join(os.getcwd(), "wealthguard.db"))


def lower_bucket(a: str, b: str) -> str:
    return a if BUCKET_ORDER.index(a) <= BUCKET_ORDER.index(b) else b


def effective_bucket(bucket: str, age: int, horizon_years: float) -> str:
    """R5: vulnerable clients are capped at Moderate regardless of score."""
    if age >= VULNERABLE_AGE or horizon_years < VULNERABLE_HORIZON_YEARS:
        return lower_bucket(bucket, VULNERABLE_CAP_BUCKET)
    return bucket

# R6 disclosure marker phrases (lower-case) - client text must contain all three.
RISK_WARNING = "Investing involves risk, and you can lose part or all of your capital."
PERF_DISCLAIMER = "Past performance is not a reliable indicator of future results."
FEE_MARKER = "annual fees"
