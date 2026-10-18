"""A small vector database on SQLite + numpy.

Chunks are embedded with a deterministic hashing TF-IDF embedder (Chinese character 2/3-grams, Latin words), stored as
float32 BLOBs, and searched by cosine similarity. It needs no network, no model download and no extra service, so mock
mode, the tests and the Vercel build all work the same way. The embedder is a thin class: a neural model could replace
it later without touching the store. Lexical overlap is what it measures, not deep semantics; knowledge.py adds a small
English->Chinese glossary so English questions can reach the Chinese regulation text.
"""
import hashlib
import math
import re
import threading
import time
import unicodedata
from collections import Counter
from functools import lru_cache

import numpy as np

from app import config, db, qdrant_backend

DIM = 1024
_CJK = re.compile(r"[一-鿿]+")
_LATIN = re.compile(r"[a-z0-9]{2,}")
_LOCK = threading.RLock()
_CACHE: dict = {}
COOLDOWN_S = 60
REMOTE: dict = {"state": "off", "collection": None, "error": None, "until": 0.0, "synced_fp": None}


@lru_cache(maxsize=100_000)
def _slot(token: str) -> tuple[int, int]:
    h = int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big")
    return h % DIM, 1 if (h >> 40) & 1 else -1


def tokens(text: str) -> list[str]:
    t = unicodedata.normalize("NFKC", text).lower()
    out = []
    for run in _CJK.findall(t):
        for n in (2, 3):
            out += [run[i:i + n] for i in range(len(run) - n + 1)]
        if len(run) == 1:
            out.append(run)
    for w in _LATIN.findall(t):
        out.append(w[:-1] if len(w) > 3 and w.endswith("s") else w)
    return out


def _tf(text: str) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    for tok, c in Counter(tokens(text)).items():
        i, sign = _slot(tok)
        v[i] += sign * (1.0 + math.log(c))
    return v


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n else v


def _ensure_schema(conn) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS kb_chunks (
      id TEXT PRIMARY KEY, source TEXT NOT NULL, ref TEXT NOT NULL, lang TEXT NOT NULL, title TEXT NOT NULL,
      text TEXT NOT NULL, url TEXT NOT NULL, vec BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS kb_meta (key TEXT PRIMARY KEY, value BLOB NOT NULL);""")


def fingerprint() -> str | None:
    conn = db.connect()
    _ensure_schema(conn)
    r = conn.execute("SELECT value FROM kb_meta WHERE key='fingerprint'").fetchone()
    conn.close()
    return r["value"].decode() if r else None


def count(source: str | None = None) -> int:
    conn = db.connect()
    _ensure_schema(conn)
    q, p = "SELECT COUNT(*) FROM kb_chunks", ()
    if source:
        q, p = q + " WHERE source=?", (source,)
    n = conn.execute(q, p).fetchone()[0]
    conn.close()
    return n


def build(items: list[dict], fp: str) -> int:
    """Replace the whole index with `items` (id, source, ref, lang, title, text, url) and record its fingerprint."""
    raws = [_tf(f"{it['title']} {it['text']}") for it in items]
    df = np.zeros(DIM, dtype=np.float32)
    for r in raws:
        df += (r != 0)
    idf = (np.log((len(items) + 1) / (df + 1)) + 1.0).astype(np.float32)
    with db.LOCK, _LOCK:
        conn = db.connect()
        _ensure_schema(conn)
        conn.execute("DELETE FROM kb_chunks")
        for it, r in zip(items, raws):
            vec = _unit(r * idf).astype(np.float32)
            conn.execute("INSERT INTO kb_chunks VALUES (?,?,?,?,?,?,?,?)",
                         (it["id"], it["source"], it["ref"], it["lang"], it["title"], it["text"], it["url"],
                          vec.tobytes()))
        conn.execute("INSERT OR REPLACE INTO kb_meta VALUES ('idf', ?)", (idf.tobytes(),))
        conn.execute("INSERT OR REPLACE INTO kb_meta VALUES ('fingerprint', ?)", (fp.encode(),))
        conn.commit()
        conn.close()
        _CACHE.clear()
    ensure_remote(fp)
    return len(items)


def _load():
    key = (config.db_path(), fingerprint())
    with _LOCK:
        if _CACHE.get("key") == key:
            return _CACHE["data"]
        conn = db.connect()
        _ensure_schema(conn)
        rows = conn.execute("SELECT id, source, ref, lang, title, text, url, vec FROM kb_chunks ORDER BY rowid").fetchall()
        idf_row = conn.execute("SELECT value FROM kb_meta WHERE key='idf'").fetchone()
        conn.close()
        mat = np.vstack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows]) if rows else np.zeros((0, DIM), np.float32)
        idf = np.frombuffer(idf_row["value"], dtype=np.float32) if idf_row else np.ones(DIM, np.float32)
        _CACHE.update(key=key, data=(rows, mat, idf))
        return _CACHE["data"]


def _remote_failed(e: Exception) -> None:
    REMOTE.update(state="error", error=str(e)[:120], until=time.time() + COOLDOWN_S)


def ensure_remote(fp: str) -> None:
    """Mirror the local index to Qdrant when configured (once per index version). Never raises."""
    if not qdrant_backend.configured():
        REMOTE.update(state="off", collection=None, error=None)
        return
    if REMOTE["synced_fp"] == fp and REMOTE["state"] == "ok":
        return
    if time.time() < REMOTE["until"]:
        return
    try:
        rows, mat, _ = _load()
        info = qdrant_backend.sync(rows, mat, fp)
        REMOTE.update(state="ok", collection=info["collection"], error=None, synced_fp=fp, until=0.0)
    except Exception as e:  # network, auth, allowlist, bad response: stay local
        _remote_failed(e)


def backend_status() -> dict:
    """What answers searches now. Never includes the URL or key."""
    on = qdrant_backend.configured()
    return {"backend": "qdrant" if on and REMOTE["state"] == "ok" else "local", "qdrant_configured": on,
            "qdrant_state": REMOTE["state"] if on else "off", "qdrant_error": REMOTE["error"] if on else None}


def search(query: str, k: int = 3, source: str | None = None, min_score: float = 0.0) -> list[dict]:
    return search_ex(query, k, source, min_score)[0]


def search_ex(query: str, k: int = 3, source: str | None = None, min_score: float = 0.0) -> tuple[list[dict], str]:
    """(hits, backend). Qdrant answers when configured and healthy; any failure falls back to the local index."""
    rows, mat, idf = _load()
    if not len(rows):
        return [], "local"
    q = _unit(_tf(query) * idf)
    if not float(np.linalg.norm(q)):
        return [], "local"
    fp = fingerprint()
    if qdrant_backend.configured() and REMOTE["state"] == "ok" and REMOTE["synced_fp"] == fp:
        try:
            return qdrant_backend.search(q, fp, k, source, min_score), "qdrant"
        except Exception as e:
            _remote_failed(e)
    elif qdrant_backend.configured():
        ensure_remote(fp)  # retry after the cooldown
        if REMOTE["state"] == "ok":
            try:
                return qdrant_backend.search(q, fp, k, source, min_score), "qdrant"
            except Exception as e:
                _remote_failed(e)
    return _local_search(rows, mat, q, k, source, min_score), "local"


def _local_search(rows, mat, q, k, source, min_score) -> list[dict]:
    scores = mat @ q
    order = np.argsort(-scores, kind="stable")
    out = []
    for i in order:
        r = rows[int(i)]
        if source and r["source"] != source:
            continue
        s = float(scores[int(i)])
        if s < min_score:
            break
        out.append({"id": r["id"], "source": r["source"], "ref": r["ref"], "lang": r["lang"], "title": r["title"],
                    "text": r["text"], "url": r["url"], "score": round(s, 4)})
        if len(out) >= k:
            break
    return out
