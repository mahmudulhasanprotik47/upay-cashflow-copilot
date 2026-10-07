# Passwords, sessions, API keys, sign-in lockout and the first admin account. Standard library only.
# Nothing here stores or logs a password, session token or API key in plain text: only salted scrypt
# hashes (passwords) and SHA-256 hashes (random tokens and keys) go into the database.

import hashlib  # scrypt and SHA-256.
import hmac  # Constant-time comparison.
import os  # Reads the first admin's password from the environment.
import secrets  # Random salts, tokens, keys and generated passwords.

from src import config as cfg  # Central settings.
from src.db import database  # Storage.


class AuthError(Exception):
    """A sign-in or credential problem. code is one of the API error codes (bad_credentials, locked, ...)."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------
# Passwords: salted scrypt, compared in constant time.
# ---------------------------------------------------------------------------

def hash_password(password):
    """A new salted scrypt hash, stored as 'scrypt$n$r$p$salt$hash' (hex)."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=cfg.SCRYPT_N, r=cfg.SCRYPT_R, p=cfg.SCRYPT_P)
    return f"scrypt${cfg.SCRYPT_N}${cfg.SCRYPT_R}${cfg.SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    """True if the password matches the stored hash (constant-time compare of the digests)."""
    try:
        _, n, r, p, salt, digest = stored.split("$")
        test = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(test, bytes.fromhex(digest))


# A hash of a random password, checked when the username does not exist, so a wrong username
# takes as long as a wrong password (no hint which usernames exist).
_DUMMY_HASH = None


def dummy_hash():
    """Lazily made hash used only to spend the same time on unknown usernames."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
    return _DUMMY_HASH


def check_password_rule(password):
    """Raise AuthError('weak_password') unless the password is a string of at least PASSWORD_MIN_LENGTH."""
    if not isinstance(password, str) or len(password) < cfg.PASSWORD_MIN_LENGTH or len(password) > 200:
        raise AuthError("weak_password")


# ---------------------------------------------------------------------------
# Random tokens (sessions, API keys) are stored only as SHA-256 hashes.
# ---------------------------------------------------------------------------

def token_hash(token):
    """SHA-256 of a session token or API key, as hex."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def principal_of(account):
    """The signed-in identity the rest of the app sees for one accounts row."""
    return {"kind": "session", "account_id": account["id"], "name": account["username"],
            "role": account["role"], "user_id": account["user_id"]}


# ---------------------------------------------------------------------------
# Sign-in, lockout and sessions.
# ---------------------------------------------------------------------------

def login(username, password):
    """Check a username and password. Returns (session_token, principal) or raises AuthError.

    Five wrong passwords in a row lock the account for LOCKOUT_MINUTES. A disabled account, an
    unknown username and a wrong password all give the same 'bad_credentials' answer.
    """
    db = database.get()
    account = db.one("SELECT * FROM accounts WHERE username = ?", (str(username),))
    if account is None:
        verify_password(str(password), dummy_hash())  # Same work as a real check.
        raise AuthError("bad_credentials")
    now = database.now()
    if account["locked_until"] > now:
        raise AuthError("locked")  # The password is not even checked while locked.
    if not verify_password(str(password), account["pw_hash"]) or account["disabled"]:
        failed = account["failed_count"] + 1
        if failed >= cfg.LOGIN_MAX_FAILURES:  # Lock, and start counting again after the lock.
            db.execute("UPDATE accounts SET failed_count = 0, locked_until = ? WHERE id = ?",
                       (now + cfg.LOCKOUT_MINUTES * 60, account["id"]))
        else:
            db.execute("UPDATE accounts SET failed_count = ? WHERE id = ?", (failed, account["id"]))
        raise AuthError("bad_credentials")
    db.execute("UPDATE accounts SET failed_count = 0, locked_until = 0 WHERE id = ?", (account["id"],))
    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO sessions (token_hash, account_id, expires_at) VALUES (?, ?, ?)",
               (token_hash(token), account["id"], now + cfg.SESSION_HOURS * 3600))
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))  # Tidy away old sessions.
    return token, principal_of(account)


def session_principal(token):
    """The principal for a session cookie value, or None if unknown, expired or the account is disabled."""
    if not token or len(token) > 200:
        return None
    account = database.get().one(
        "SELECT a.* FROM sessions s JOIN accounts a ON a.id = s.account_id "
        "WHERE s.token_hash = ? AND s.expires_at > ? AND a.disabled = 0",
        (token_hash(token), database.now()))
    return principal_of(account) if account else None


def logout(token):
    """Delete the session for this cookie value (no error if it does not exist)."""
    if token:
        database.get().execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))


def end_sessions(account_id):
    """Sign an account out everywhere (after a password reset, a role change or disabling)."""
    database.get().execute("DELETE FROM sessions WHERE account_id = ?", (account_id,))


# ---------------------------------------------------------------------------
# API keys for machine clients: shown once, stored hashed, revocable.
# ---------------------------------------------------------------------------

def create_api_key(label, created_by):
    """Make a new key. Returns (id, key, prefix); the key itself is never stored and cannot be shown again."""
    key = "cfk_" + secrets.token_urlsafe(32)
    prefix = key[:10]
    cur = database.get().execute(
        "INSERT INTO api_keys (key_hash, prefix, label, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
        (token_hash(key), prefix, str(label)[:80], created_by, database.now()))
    return cur.lastrowid, key, prefix


def api_key_principal(key):
    """The principal for an X-API-Key value, or None if unknown or revoked."""
    if not key or len(key) > 200:
        return None
    row = database.get().one("SELECT id, label FROM api_keys WHERE key_hash = ? AND revoked = 0", (token_hash(key),))
    if row is None:
        return None
    return {"kind": "api_key", "account_id": None, "key_id": row["id"], "name": f"api-key:{row['id']}",
            "role": "machine", "user_id": None}


# ---------------------------------------------------------------------------
# Accounts and the first admin.
# ---------------------------------------------------------------------------

def create_account(username, password, role, user_id=None):
    """Insert one account with a hashed password. Returns the new id."""
    check_password_rule(password)
    return database.get().execute(
        "INSERT INTO accounts (username, pw_hash, role, user_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (username, hash_password(password), role, user_id, database.now())).lastrowid


def ensure_admin():
    """Create the first admin if there is no admin yet. Returns the admin username.

    The password comes from the COPILOT_ADMIN_PASSWORD environment variable. If it is not set, a random
    one is generated and printed ONCE to the console (ASCII only). Only its hash is stored.
    """
    db = database.get()
    if db.one("SELECT id FROM accounts WHERE role = 'admin'"):
        return cfg.ADMIN_USERNAME
    password = os.environ.get(cfg.ADMIN_PASSWORD_ENV)
    generated = not password
    if generated:
        password = secrets.token_urlsafe(16)
    create_account(cfg.ADMIN_USERNAME, password, "admin")
    if generated:
        print(f"First admin created. Username: {cfg.ADMIN_USERNAME}  Password (shown once): {password}", flush=True)
    else:
        print(f"First admin created. Username: {cfg.ADMIN_USERNAME}  Password: from {cfg.ADMIN_PASSWORD_ENV}", flush=True)
    return cfg.ADMIN_USERNAME
