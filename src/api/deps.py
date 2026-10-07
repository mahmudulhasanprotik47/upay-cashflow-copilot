# Access control for the API, as small functions the routers call or use as FastAPI dependencies.
# Roles: a customer may read and change only their own user_id; an analyst may read any wallet, the
# results and the monitoring but change nothing; an admin may do everything; an API key (machine
# client) may read wallets. Every staff or machine view of a wallet is written to the audit log.

from fastapi import Request  # The incoming request (the middleware put the principal on it).
from fastapi.responses import JSONResponse  # Error responses.

from src import config as cfg  # Central settings.
from src.db import database  # Audit log, consents, accounts.
from src.i18n.messages import render  # Error messages in English and Bangla.


class ApiError(Exception):
    """An error with a fixed code; the app turns it into {code, error, error_bn} with this status."""

    def __init__(self, status, code, headers=None):
        super().__init__(code)
        self.status, self.code, self.headers = status, code, headers


def error_response(status, code, headers=None):
    """A short generic error in both languages plus a machine-readable code. Never echoes the input."""
    key = f"error_{code}"
    return JSONResponse(status_code=status, headers=headers,
                        content={"code": code, "error": render(key, "en"), "error_bn": render(key, "bn")})


# ---------------------------------------------------------------------------
# Who is calling. The security middleware sets request.state.principal (None when signed out).
# ---------------------------------------------------------------------------

def principal(request: Request):
    """Dependency: any signed-in user or valid API key; otherwise 401."""
    p = getattr(request.state, "principal", None)
    if p is None:
        raise ApiError(401, "auth_required")
    return p


def staff(request: Request):
    """Dependency: admin or analyst; customers and API keys get 403."""
    p = principal(request)
    if p["role"] not in ("admin", "analyst"):
        raise ApiError(403, "forbidden")
    return p


def admin(request: Request):
    """Dependency: admin only."""
    p = principal(request)
    if p["role"] != "admin":
        raise ApiError(403, "forbidden")
    return p


def customer(request: Request):
    """Dependency: a signed-in customer linked to a user_id."""
    p = principal(request)
    if p["role"] != "customer" or p["user_id"] is None:
        raise ApiError(403, "forbidden")
    return p


# ---------------------------------------------------------------------------
# Consent: needed only for user_ids linked to a customer account. Unlinked ids are simulated fixtures.
# ---------------------------------------------------------------------------

def is_linked(user_id):
    """True if a customer account is linked to this user_id."""
    return database.get().one("SELECT id FROM accounts WHERE user_id = ?", (user_id,)) is not None


def has_consent(user_id):
    """True if the latest consent for this user_id is for the current notice and not withdrawn."""
    row = database.get().one("SELECT notice_version, withdrawn_at FROM consents WHERE user_id = ? "
                             "ORDER BY id DESC LIMIT 1", (user_id,))
    return bool(row) and row["withdrawn_at"] is None and row["notice_version"] == cfg.CONSENT_NOTICE_VERSION


def consent_ok(user_id):
    """Unlinked simulated fixtures need no consent; linked users need a current, unwithdrawn one."""
    return not is_linked(user_id) or has_consent(user_id)


def data_subject(user_id):
    """'linked_customer' or 'simulated_fixture', shown next to wallet data so staff know which it is."""
    return "linked_customer" if is_linked(user_id) else "simulated_fixture"


def feature_on(key, user_id=None):
    """Is a feature switch on for this user? A per-user setting wins over the global one; default on."""
    db = database.get()
    for scope in ([f"user:{user_id}"] if user_id is not None else []) + ["global"]:
        row = db.one("SELECT value FROM settings WHERE scope = ? AND key = ?", (scope, key))
        if row:
            return row["value"] == "on"
    return True


# ---------------------------------------------------------------------------
# Wallet access rules.
# ---------------------------------------------------------------------------

def check_read(p, user_id, what="wallet"):
    """May p read this user's wallet? Raises 403 otherwise. Staff and machine views are audited."""
    if p["role"] == "customer" and p["user_id"] != user_id:
        raise ApiError(403, "forbidden")
    if p["role"] not in cfg.ROLES + ["machine"]:
        raise ApiError(403, "forbidden")
    if not consent_ok(user_id):
        raise ApiError(403, "consent_required")
    if p["role"] != "customer":
        database.audit(p, f"view_{what}", user_id)


def check_write(p, user_id, consent=True):
    """May p change this user's data? Customers: own id only. Admin: any. Analyst and API keys: never.

    consent=False leaves the consent check to the caller (the live engine logs that rejection itself).
    """
    if p["role"] == "customer" and p["user_id"] == user_id:
        pass
    elif p["role"] != "admin":
        raise ApiError(403, "forbidden")
    if consent and not consent_ok(user_id):
        raise ApiError(403, "consent_required")
