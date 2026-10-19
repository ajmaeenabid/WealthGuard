"""Vercel entry point: serves the FastAPI app (API and static UI) as one serverless function.

Vercel's disk is read-only except /tmp, so SQLite lives there. State is per instance and resets on a cold start; this is
fine for a synthetic-data demo (the schema is created on demand). Without an LLM key the app runs on the mock LLM.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("WEALTHGUARD_DB", os.path.join(tempfile.gettempdir(), "wealthguard.db"))  # /tmp on Vercel

from urllib.parse import parse_qsl, urlencode  # noqa: E402

from app.main import app as _fastapi_app  # noqa: E402


async def app(scope, receive, send):
    """Vercel rewrites every URL to /api/index?__p=<original path>; restore the original path before FastAPI routes it."""
    if scope["type"] in ("http", "websocket") and scope.get("path", "").startswith("/api/index"):
        pairs = parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
        orig = next((v for k, v in pairs if k == "__p"), "")
        rest = [(k, v) for k, v in pairs if k != "__p"]
        scope = dict(scope, path="/" + orig.lstrip("/"), raw_path=("/" + orig.lstrip("/")).encode(),
                     query_string=urlencode(rest).encode("latin-1"))
    await _fastapi_app(scope, receive, send)
