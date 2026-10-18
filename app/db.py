"""SQLite helpers. One connection per call; schema created on demand."""
import sqlite3
import threading

from app import config
from app.finance.schema import SQL as FINANCE_SQL

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
CREATE TABLE IF NOT EXISTS ledger (
  id TEXT PRIMARY KEY, client_id TEXT NOT NULL, ts TEXT NOT NULL, item TEXT NOT NULL, category TEXT NOT NULL,
  amount_cny REAL NOT NULL, status TEXT NOT NULL, impulse INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL,
  updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ledger_changes (
  id TEXT PRIMARY KEY, client_id TEXT NOT NULL, data TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY, display_name TEXT NOT NULL, role TEXT NOT NULL, persona_id TEXT,
  salt TEXT NOT NULL, pw_hash TEXT NOT NULL, created TEXT NOT NULL,
  banned INTEGER NOT NULL DEFAULT 0, permissions TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL,
  text TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL, UNIQUE (username, kind, key));
CREATE TABLE IF NOT EXISTS auth_tokens (
  token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, created TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS conversations (
  client_id TEXT PRIMARY KEY, username TEXT NOT NULL, title TEXT NOT NULL, persona_id TEXT, name TEXT NOT NULL,
  pending_question TEXT, created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, client_id TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL, ts TEXT NOT NULL);
"""

SCHEMA += FINANCE_SQL


_MIGRATED: set = set()


def _migrate(conn: sqlite3.Connection) -> None:
    """Databases created before bans and permissions existed get the two columns once per process."""
    path = config.db_path()
    if path in _MIGRATED:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    if "banned" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN banned INTEGER NOT NULL DEFAULT 0")
    if "permissions" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN permissions TEXT NOT NULL DEFAULT '{}'")
    conn.commit()
    _MIGRATED.add(path)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def reset() -> None:
    with LOCK:
        conn = connect()
        for t in ["clients", "allocations", "tickets", "documents", "audit", "ledger", "ledger_changes", "conversations", "messages"]:
            conn.execute(f"DELETE FROM {t}")
        conn.execute("DELETE FROM sqlite_sequence")
        conn.commit()
        conn.close()
