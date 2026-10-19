"""Token budgeting so a long conversation or a large ledger can never overflow the model's input or output limit.

There is no tokenizer for gpt-oss in the standard library, so counts are a conservative ESTIMATE (never an under-count for the scripts used here):
Latin text ~ 1 token per 3.5 characters, Chinese ~ 1 token per character, Bangla ~ 1 token per 1.5 characters. The real usage reported by the
provider is still stored in fin_ai_usage; this module only keeps requests safely inside the budget before they are sent.
"""
import os
import re
from typing import Optional

DEFAULT_MAX_INPUT = 3500      # leaves room under the documented 8K tokens/min Developer-plan limit for the reply and a second call
DEFAULT_MAX_OUTPUT = 1200
_CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿]")
_BN = re.compile(r"[ঀ-৿]")


def _env(name: str, default: int) -> int:
    try:
        v = int(float(os.environ.get(name, "")))
        return v if v > 0 else default
    except ValueError:
        return default


def max_input() -> int:
    return _env("FIN_AI_MAX_INPUT_TOKENS", DEFAULT_MAX_INPUT)


def max_output() -> int:
    return _env("FIN_AI_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT)


def estimate(text: str) -> int:
    t = text or ""
    cjk = len(_CJK.findall(t))
    bn = len(_BN.findall(t))
    rest = len(t) - cjk - bn
    return int(cjk * 1.0 + bn / 1.5 + rest / 3.5) + 1


def truncate(text: str, budget: int, *, keep: str = "head") -> str:
    """Cut text to roughly `budget` tokens. keep='tail' keeps the end (recent turns); a marker shows that something was cut."""
    if estimate(text) <= budget:
        return text
    lo, hi = 0, len(text)
    while lo < hi:                                         # largest prefix/suffix that fits
        mid = (lo + hi + 1) // 2
        piece = text[:mid] if keep == "head" else text[len(text) - mid:]
        if estimate(piece) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo] + " …[truncated]") if keep == "head" else ("[truncated]… " + text[len(text) - lo:])


def fit_messages(messages: list, budget: Optional[int] = None) -> tuple[list, dict]:
    """Keeps the system message and the newest turns inside the budget. Older turns are dropped first, then the longest remaining message is
    truncated. Returns (messages, report) where report says what was cut, so the cut is never silent."""
    budget = budget or max_input()
    msgs = [dict(m) for m in messages]
    before = sum(estimate(m.get("content", "")) + 4 for m in msgs)
    dropped = truncated = 0
    total = before
    while total > budget and len(msgs) > 2:               # drop the oldest non-system turn
        i = next((k for k, m in enumerate(msgs) if m["role"] != "system"), None)
        if i is None or i >= len(msgs) - 1:
            break
        total -= estimate(msgs[i].get("content", "")) + 4
        del msgs[i]
        dropped += 1
    guard = 0
    while total > budget and guard < 6:                   # still too big: shrink the largest message (never below a floor)
        guard += 1
        i = max(range(len(msgs)), key=lambda k: estimate(msgs[k].get("content", "")))
        cur = estimate(msgs[i].get("content", ""))
        target = max(200, cur - (total - budget))
        keep = "tail" if msgs[i]["role"] == "user" else "head"
        msgs[i]["content"] = truncate(msgs[i]["content"], target, keep=keep)
        truncated += 1
        total = sum(estimate(m.get("content", "")) + 4 for m in msgs)
    return msgs, {"estimated_before": before, "estimated_after": total, "dropped_turns": dropped, "truncated_messages": truncated, "budget": budget}


def clamp_output(requested: int) -> int:
    return max(64, min(int(requested), max_output()))
