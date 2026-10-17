"""Vercel entry point: serves the FastAPI app (API and static UI) as one serverless function.

Vercel's disk is read-only except /tmp, so SQLite lives there. State is per instance and resets on a cold start; this is
fine for a synthetic-data demo (the schema is created on demand). Without an LLM key the app runs on the mock LLM.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("WEALTHGUARD_DB", os.path.join(tempfile.gettempdir(), "wealthguard.db"))  # /tmp on Vercel

from app.main import app  # noqa: E402,F401  (Vercel looks for `app`)
