"""SQLite helpers. One connection per call; schema created on demand."""
import sqlite3
import threading

from app import config

LOCK = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS allocations (
  id TEXT PRIMARY KEY, client_id TEXT NOT NULL, data TEXT NOT NULL,
  compliance TEXT, status TEXT NOT NULL DEFAULT 'draft', seq INTEGER);
CREATE TABLE IF NOT EXISTS tickets (id TEXT PRIMARY KEY, client_id TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT, client_id TEXT, filename TEXT, text TEXT, warnings TEXT);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, client_id TEXT, actor TEXT NOT NULL,
  action TEXT NOT NULL, tier TEXT NOT NULL, payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
  prev_hash TEXT NOT NULL, entry_hash TEXT NOT NULL);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def reset() -> None:
    with LOCK:
        conn = connect()
        for t in ["clients", "allocations", "tickets", "documents", "audit"]:
            conn.execute(f"DELETE FROM {t}")
        conn.execute("DELETE FROM sqlite_sequence")
        conn.commit()
        conn.close()
