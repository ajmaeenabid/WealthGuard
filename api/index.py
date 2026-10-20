"""Vercel entry point: serves the FastAPI app (API and static UI) as one serverless function."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("WEALTHGUARD_DB", os.path.join(tempfile.gettempdir(), "wealthguard.db"))

from urllib.parse import parse_qsl, urlencode

from app.main import app as _fastapi_app


async def app(scope, receive, send):
    if scope["type"] in ("http", "websocket") and scope.get("path", "").startswith("/api/index"):
        pairs = parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
        orig = next((v for k, v in pairs if k == "__p"), "")
        rest = [(k, v) for k, v in pairs if k != "__p"]
        scope = dict(scope, path="/" + orig.lstrip("/"), raw_path=("/" + orig.lstrip("/")).encode(),
                     query_string=urlencode(rest).encode("latin-1"))
    await _fastapi_app(scope, receive, send)
