"""Accounts: username + password sign-up and sign-in, bearer tokens, password change, and what an administrator can do
(suspend accounts, change roles, switch individual features on or off per account). Passwords are salted PBKDF2."""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Optional

from app import db, store

TOKEN_TTL_S = 12 * 3600
MIN_PASSWORD = 6          # for new passwords; the seeded demo accounts start with "123" and should be changed
PBKDF2_ROUNDS = 120_000
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")
MAX_FAILS, FAIL_WINDOW_S = 5, 300

# username -> (display name, role, demo profile the account may load from the Memory panel)
SEED = {
    "admin": ("Administrator", "admin", None),
    "li": ("Ms. Li", "client", "persona_li"),
    "chen": ("Mr. Chen", "client", "persona_chen"),
    "wang": ("Mr. Wang", "client", "persona_wang"),
}
SEED_PASSWORD = "123"
_FAILS: dict[str, list[float]] = {}

# Features an administrator can switch on or off per account. Everything is on by default.
FEATURES = {
    "chat": "Advice chat",
    "orders": "Order tickets and reports",
    "ledger": "Purchase history",
    "replay": "History replay",
    "documents": "Document upload",
    "voice": "Voice input",
    "knowledge": "Regulation search",
    "receipt": "Advice receipt",
    "insights": "Red-team arena and self-inspection",
}
# (route prefix, feature) checked by the API gate; tools are checked in the tier engine (see denied_tools)
ROUTE_FEATURES = [("/api/chat", "chat"), ("/api/ledger", "ledger"), ("/api/replay", "replay"), ("/api/documents", "documents"),
                  ("/api/approve", "orders"), ("/api/reject", "orders"), ("/api/transcribe", "voice"),
                  ("/api/knowledge", "knowledge"), ("/api/receipt", "receipt"), ("/api/redteam", "insights"),
                  ("/api/selfinspection", "insights")]
TOOL_FEATURES = {"create_order_ticket": "orders", "generate_report": "orders", "search_knowledge": "knowledge",
                 "get_behaviour_insights": "ledger"}


class AuthError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


def auth_required() -> bool:
    return os.environ.get("WEALTHGUARD_AUTH", "1") != "0"


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()


def _insert(username: str, display: str, role: str, persona: Optional[str], password: str) -> None:
    salt = secrets.token_hex(16)
    store._write("INSERT INTO users (username, display_name, role, persona_id, salt, pw_hash, created) VALUES (?,?,?,?,?,?,?)",
                 (username, display, role, persona, salt, _hash(password, salt), store.now()))


def ensure_seed() -> None:
    """Create the demo accounts that do not exist yet. Existing accounts (and changed passwords) are never touched."""
    c = db.connect()
    have = {r["username"] for r in c.execute("SELECT username FROM users").fetchall()}
    c.close()
    for name, (display, role, persona) in SEED.items():
        if name not in have:
            _insert(name, display, role, persona, SEED_PASSWORD)


def permissions_of(row) -> dict:
    """Every feature -> bool. Administrators always have everything; others default to on unless switched off."""
    try:
        stored = json.loads(row["permissions"] or "{}")
    except ValueError:
        stored = {}
    return {f: True if row["role"] == "admin" else bool(stored.get(f, True)) for f in FEATURES}


def public(row) -> dict:
    return {"username": row["username"], "display_name": row["display_name"], "role": row["role"],
            "demo_persona_id": row["persona_id"], "permissions": permissions_of(row), "banned": bool(row["banned"])}


def _user_row(username: str):
    return store._one("SELECT * FROM users WHERE username=?", (username,))


def _issue_token(username: str) -> str:
    token = secrets.token_urlsafe(32)
    store._write("INSERT INTO auth_tokens VALUES (?,?,?,?)",
                 (hashlib.sha256(token.encode()).hexdigest(), username, store.now(), time.time() + TOKEN_TTL_S))
    return token


def signup(username: str, password: str, display_name: str = "") -> dict:
    username = (username or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise AuthError("Username must be 3-32 characters: letters, numbers, dot, dash or underscore.")
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"Password must be at least {MIN_PASSWORD} characters.")
    ensure_seed()
    if _user_row(username):
        raise AuthError("That username is already taken.", 409)
    _insert(username, (display_name or username).strip()[:40] or username, "client", None, password)
    return {"token": _issue_token(username), "user": public(_user_row(username))}


def login(username: str, password: str) -> dict:
    username = (username or "").strip().lower()
    now = time.time()
    recent = [t for t in _FAILS.get(username, []) if now - t < FAIL_WINDOW_S]
    if len(recent) >= MAX_FAILS:
        raise AuthError("Too many failed attempts. Wait a few minutes and try again.", 429)
    ensure_seed()
    row = _user_row(username)
    ok = bool(row) and hmac.compare_digest(_hash(password or "", row["salt"]), row["pw_hash"])
    if not ok:
        _FAILS[username] = recent + [now]
        raise AuthError("Wrong username or password.", 401)
    _FAILS.pop(username, None)
    if row["banned"]:
        raise AuthError("This account has been suspended. Please contact an administrator.", 403)
    return {"token": _issue_token(username), "user": public(row)}


def user_for_token(token: str) -> Optional[dict]:
    if not token:
        return None
    r = store._one("SELECT username, expires FROM auth_tokens WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
    if not r or r["expires"] < time.time():
        return None
    row = _user_row(r["username"])
    return public(row) if row and not row["banned"] else None


def logout(token: str) -> None:
    store._write("DELETE FROM auth_tokens WHERE token_hash=?", (hashlib.sha256((token or "").encode()).hexdigest(),))


def change_password(username: str, old: str, new: str, keep_token: str = "") -> None:
    row = _user_row(username)
    if not row or not hmac.compare_digest(_hash(old or "", row["salt"]), row["pw_hash"]):
        raise AuthError("Your current password is not correct.", 403)
    _set_password(username, new, keep_token, must_differ_from=old)


def _set_password(username: str, new: str, keep_token: str = "", must_differ_from: Optional[str] = None) -> None:
    if len(new or "") < MIN_PASSWORD:
        raise AuthError(f"New password must be at least {MIN_PASSWORD} characters.")
    if must_differ_from is not None and new == must_differ_from:
        raise AuthError("Choose a password that is different from the current one.")
    salt = secrets.token_hex(16)
    store._write("UPDATE users SET salt=?, pw_hash=? WHERE username=?", (salt, _hash(new, salt), username))
    # every other signed-in device is signed out; the one that made the change stays
    keep = hashlib.sha256(keep_token.encode()).hexdigest()
    store._write("DELETE FROM auth_tokens WHERE username=? AND token_hash<>?", (username, keep))


# ------------------------------------------------------------------------------------------ what features an account may use
def feature_for(path: str, method: str = "GET") -> Optional[str]:
    if path == "/api/conversations" and method == "POST":
        return "chat"
    for prefix, feat in ROUTE_FEATURES:
        if path == prefix or path.startswith(prefix + "/"):
            return feat
    return None


def denied_tools(username: Optional[str]) -> frozenset:
    row = _user_row(username) if username else None
    if row is None:
        return frozenset()
    perms = permissions_of(row)
    return frozenset(t for t, f in TOOL_FEATURES.items() if not perms.get(f, True))


# ------------------------------------------------------------------------------------------ administration
def list_users() -> list[dict]:
    c = db.connect()
    rows = c.execute("SELECT * FROM users ORDER BY role='admin' DESC, username").fetchall()
    chats = {r["username"]: r["n"] for r in c.execute("SELECT username, COUNT(*) AS n FROM conversations GROUP BY username")}
    c.close()
    return [dict(public(r), created=r["created"], chats=chats.get(r["username"], 0)) for r in rows]


def _target(username: str):
    row = _user_row((username or "").strip().lower())
    if not row:
        raise AuthError("No such account.", 404)
    return row


def _active_admins(excluding: str = "") -> int:
    c = db.connect()
    n = c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND banned=0 AND username<>?", (excluding,)).fetchone()[0]
    c.close()
    return n


def set_banned(actor: str, username: str, banned: bool) -> dict:
    row = _target(username)
    if row["username"] == actor:
        raise AuthError("You cannot suspend your own account.", 400)
    if banned and row["role"] == "admin" and _active_admins(row["username"]) == 0:
        raise AuthError("At least one active administrator must remain.", 400)
    store._write("UPDATE users SET banned=? WHERE username=?", (1 if banned else 0, row["username"]))
    if banned:
        store._write("DELETE FROM auth_tokens WHERE username=?", (row["username"],))   # signed out everywhere, immediately
    return public(_user_row(row["username"]))


def set_role(actor: str, username: str, role: str) -> dict:
    row = _target(username)
    if role not in ("admin", "client"):
        raise AuthError("Role must be 'admin' or 'client'.")
    if row["username"] == actor and role != "admin":
        raise AuthError("You cannot remove your own administrator role.", 400)
    if row["role"] == "admin" and role != "admin" and _active_admins(row["username"]) == 0:
        raise AuthError("At least one active administrator must remain.", 400)
    store._write("UPDATE users SET role=? WHERE username=?", (role, row["username"]))
    return public(_user_row(row["username"]))


def set_permissions(username: str, perms: dict) -> dict:
    row = _target(username)
    unknown = [k for k in perms if k not in FEATURES]
    if unknown:
        raise AuthError("Unknown feature: " + ", ".join(sorted(unknown)))
    current = permissions_of(row) if row["role"] != "admin" else {f: True for f in FEATURES}
    current.update({k: bool(v) for k, v in perms.items()})
    store._write("UPDATE users SET permissions=? WHERE username=?", (json.dumps({k: v for k, v in current.items() if not v}), row["username"]))
    return public(_user_row(row["username"]))


def admin_reset_password(username: str, new: str) -> None:
    row = _target(username)
    _set_password(row["username"], new)
