# Self-check 17: passwords, lockout, sessions, API keys, the access rules and the rate limiter.
# Runs against a temporary in-memory database, so data/copilot.db is never touched. ASCII output only.

import types  # A stand-in for a request carrying a principal.

from src import config as cfg  # Lockout settings.
from src.api import deps  # The access rules under test.
from src.db import database  # Temporary database.
from src.security import auth  # Passwords, sessions, keys.
from src.security.ratelimit import SlidingWindow  # A fresh limiter.


def raises(fn, *args):
    """The ApiError/AuthError code fn raises, or None if it returns normally."""
    try:
        fn(*args)
    except (deps.ApiError, auth.AuthError) as e:
        return e.code
    return None


def fake_request(p):
    """An object shaped like a request whose middleware set this principal."""
    return types.SimpleNamespace(state=types.SimpleNamespace(principal=p))


def check_access(report):
    """Check 17. Returns True if every case behaves as the access rules say."""
    db = database.Database(":memory:")
    database.use(db)
    bad = []  # Names of the cases that failed.
    try:
        pw = "correct-horse-1"
        ids = {name: auth.create_account(name, pw, role, uid) for name, role, uid in
               [("adm", "admin", None), ("ana", "analyst", None), ("cus1", "customer", 1), ("cus2", "customer", 2)]}
        for uid in (1, 2):  # Consent given, so this check tests roles only (consent is check 19).
            db.execute("INSERT INTO consents (user_id, notice_version, given_at) VALUES (?, ?, ?)",
                       (uid, cfg.CONSENT_NOTICE_VERSION, database.now()))

        # Passwords are stored only as salted scrypt hashes; two hashes of one password differ.
        stored = db.one("SELECT pw_hash FROM accounts WHERE username = 'adm'")["pw_hash"]
        if pw in stored or not stored.startswith("scrypt$") or auth.hash_password(pw) == stored:
            bad.append("hash")
        if not auth.verify_password(pw, stored) or auth.verify_password(pw + "x", stored):
            bad.append("verify")
        if raises(auth.create_account, "short", "abc", "analyst") != "weak_password":
            bad.append("weak")

        # Wrong password, unknown user, lockout after LOGIN_MAX_FAILURES, and still locked with the right one.
        if raises(auth.login, "cus1", "wrong-password") != "bad_credentials" or \
                raises(auth.login, "nobody", pw) != "bad_credentials":
            bad.append("bad_login")
        for _ in range(cfg.LOGIN_MAX_FAILURES - 1):  # One wrong password already counted above.
            raises(auth.login, "cus1", "wrong-password")
        if raises(auth.login, "cus1", pw) != "locked":
            bad.append("lockout")
        db.execute("UPDATE accounts SET locked_until = 0 WHERE username = 'cus1'")

        # Sessions: valid token -> principal; logout, expiry and disabling all end it.
        token, p_cus1 = auth.login("cus1", pw)
        stored_tokens = [r["token_hash"] for r in db.query("SELECT token_hash FROM sessions")]
        if token in stored_tokens or auth.session_principal(token) != p_cus1:
            bad.append("session")
        auth.logout(token)
        if auth.session_principal(token) is not None:
            bad.append("logout")
        token, _ = auth.login("cus1", pw)
        db.execute("UPDATE sessions SET expires_at = 0")
        if auth.session_principal(token) is not None:
            bad.append("expiry")
        token, _ = auth.login("cus2", pw)
        db.execute("UPDATE accounts SET disabled = 1 WHERE username = 'cus2'")
        if auth.session_principal(token) is not None or raises(auth.login, "cus2", pw) != "bad_credentials":
            bad.append("disabled")

        # API keys: shown once, stored hashed, revocable.
        key_id, key, _ = auth.create_api_key("check", ids["adm"])
        p_key = auth.api_key_principal(key)
        if p_key is None or p_key["role"] != "machine" or db.one("SELECT * FROM api_keys WHERE key_hash = ?", (key,)):
            bad.append("key")
        db.execute("UPDATE api_keys SET revoked = 1 WHERE id = ?", (key_id,))
        if auth.api_key_principal(key) is not None or auth.api_key_principal("cfk_made_up") is not None:
            bad.append("revoke")

        # The access matrix.
        p = {name: auth.principal_of(db.one("SELECT * FROM accounts WHERE id = ?", (i,))) for name, i in ids.items()}
        views_before = db.one("SELECT COUNT(*) n FROM audit_log")["n"]
        cases = [
            ("cus own read", raises(deps.check_read, p["cus1"], 1), None),
            ("cus other read", raises(deps.check_read, p["cus1"], 2), "forbidden"),
            ("cus own write", raises(deps.check_write, p["cus1"], 1), None),
            ("cus other write", raises(deps.check_write, p["cus1"], 2), "forbidden"),
            ("analyst read", raises(deps.check_read, p["ana"], 2), None),
            ("analyst write", raises(deps.check_write, p["ana"], 1), "forbidden"),
            ("admin write", raises(deps.check_write, p["adm"], 2), None),
            ("machine read", raises(deps.check_read, p_key, 1), None),
            ("machine write", raises(deps.check_write, p_key, 1), "forbidden"),
            ("analyst admin route", raises(deps.admin, fake_request(p["ana"])), "forbidden"),
            ("customer staff route", raises(deps.staff, fake_request(p["cus1"])), "forbidden"),
            ("admin admin route", raises(deps.admin, fake_request(p["adm"])), None),
            ("signed out", raises(deps.principal, fake_request(None)), "auth_required"),
        ]
        bad += [name for name, got, want in cases if got != want]
        # Staff and machine reads are audited (analyst + machine = 2), the customer's own read is not.
        if db.one("SELECT COUNT(*) n FROM audit_log")["n"] - views_before != 2:
            bad.append("audit")

        # Rate limiter: the request after the limit is refused with a wait time.
        limiter = SlidingWindow()
        if [limiter.hit("k", 3, 60) for _ in range(4)][-1] < 1 or limiter.hit("other", 3, 60) != 0:
            bad.append("ratelimit")
    finally:
        db.close()
        database.use(None)
    return report(17, "access control, passwords, lockout, sessions, keys, rate limit", not bad,
                  f"failed: {', '.join(bad)}" if bad else "all cases as expected")
