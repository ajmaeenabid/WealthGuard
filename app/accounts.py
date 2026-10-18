"""Accounts: username + password sign-up and sign-in, bearer tokens, password change. Passwords are salted PBKDF2."""
import hashlib
import hmac
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

# username -> (display name, role, persona the account is locked to)
SEED = {
    "admin": ("Administrator", "admin", None),
    "li": ("Ms. Li", "client", "persona_li"),
    "chen": ("Mr. Chen", "client", "persona_chen"),
    "wang": ("Mr. Wang", "client", "persona_wang"),
}
SEED_PASSWORD = "123"
_FAILS: dict[str, list[float]] = {}


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
    store._write("INSERT INTO users VALUES (?,?,?,?,?,?,?)",
                 (username, display, role, persona, salt, _hash(password, salt), store.now()))


def ensure_seed() -> None:
    """Create the demo accounts that do not exist yet. Existing accounts (and changed passwords) are never touched."""
    c = db.connect()
    have = {r["username"] for r in c.execute("SELECT username FROM users").fetchall()}
    c.close()
    for name, (display, role, persona) in SEED.items():
        if name not in have:
            _insert(name, display, role, persona, SEED_PASSWORD)


def public(row) -> dict:
    return {"username": row["username"], "display_name": row["display_name"], "role": row["role"],
            "persona_id": row["persona_id"], "can_pick_persona": row["persona_id"] is None}


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
    return {"token": _issue_token(username), "user": public(row)}


def user_for_token(token: str) -> Optional[dict]:
    if not token:
        return None
    r = store._one("SELECT username, expires FROM auth_tokens WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
    if not r or r["expires"] < time.time():
        return None
    row = _user_row(r["username"])
    return public(row) if row else None


def logout(token: str) -> None:
    store._write("DELETE FROM auth_tokens WHERE token_hash=?", (hashlib.sha256((token or "").encode()).hexdigest(),))


def change_password(username: str, old: str, new: str, keep_token: str = "") -> None:
    row = _user_row(username)
    if not row or not hmac.compare_digest(_hash(old or "", row["salt"]), row["pw_hash"]):
        raise AuthError("Your current password is not correct.", 403)
    if len(new or "") < MIN_PASSWORD:
        raise AuthError(f"New password must be at least {MIN_PASSWORD} characters.")
    if new == old:
        raise AuthError("Choose a password that is different from the current one.")
    salt = secrets.token_hex(16)
    store._write("UPDATE users SET salt=?, pw_hash=? WHERE username=?", (salt, _hash(new, salt), username))
    # every other signed-in device is signed out; this one stays
    keep = hashlib.sha256(keep_token.encode()).hexdigest()
    store._write("DELETE FROM auth_tokens WHERE username=? AND token_hash<>?", (username, keep))
