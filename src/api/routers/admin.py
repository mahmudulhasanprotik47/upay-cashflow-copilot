# Admin panel API: accounts, feature switches, API keys, audit log, consent overview, monitoring and
# the "reset all live data" button. Admin may change things; analyst may only read the audit log,
# consents, switches and monitoring. All data is simulated; nothing here moves money.

import datetime  # Readable timestamps.
import re  # Username rule.
import sqlite3  # Unique-constraint errors.
import statistics  # Median scoring time.
from typing import Literal  # Allowed values.

from fastapi import APIRouter, Depends, Query  # Routing.
from pydantic import BaseModel, ConfigDict, Field  # Request body checks.

from src import config as cfg  # Roles, switches, page size.
from src.api import deps, service  # Access rules; the list of simulated users.
from src.db import database  # Storage and audit.
from src.security import auth  # Password hashing, sessions, API keys.

router = APIRouter(prefix="/admin")
USERNAME_RULE = re.compile(r"^[A-Za-z0-9_.-]{3,40}$")  # Letters, digits, _ . - only.


def iso(t):
    """Epoch seconds as an ISO time in UTC (None stays None)."""
    return None if t is None else datetime.datetime.fromtimestamp(t, datetime.UTC).isoformat(timespec="seconds")


def known_user(user_id):
    """True if this user_id exists in the simulated data."""
    return any(u["user_id"] == user_id for u in service.list_users())


# ---------------------------------------------------------------------------
# Accounts (admin only).
# ---------------------------------------------------------------------------

class NewAccount(BaseModel):
    """Body for POST /admin/accounts."""
    model_config = ConfigDict(strict=True, extra="forbid")
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=1, max_length=200)
    role: Literal["admin", "analyst", "customer"]
    user_id: int | None = Field(default=None, ge=1)


class AccountChange(BaseModel):
    """Body for POST /admin/accounts/{id}. Only the fields sent are changed; user_id null unlinks."""
    model_config = ConfigDict(strict=True, extra="forbid")
    disabled: bool | None = None
    password: str | None = Field(default=None, max_length=200)
    role: Literal["admin", "analyst", "customer"] | None = None
    user_id: int | None = Field(default=None, ge=1)
    unlock: bool | None = None


def account_view(a):
    """One account as the admin panel sees it: never the password hash."""
    return {"id": a["id"], "username": a["username"], "role": a["role"], "user_id": a["user_id"],
            "disabled": bool(a["disabled"]), "locked": a["locked_until"] > database.now(),
            "created_at": iso(a["created_at"])}


def check_link(role, user_id):
    """A customer may be linked to a real simulated user (or not yet linked); staff are never linked."""
    if role == "customer" and user_id is not None and not known_user(user_id):
        raise deps.ApiError(422, "invalid")
    if role != "customer" and user_id is not None:
        raise deps.ApiError(422, "invalid")


@router.get("/accounts")
def list_accounts(_p=Depends(deps.admin)):
    """Every account, newest last."""
    return [account_view(a) for a in database.get().query("SELECT * FROM accounts ORDER BY id")]


@router.post("/accounts")
def create_account(body: NewAccount, p=Depends(deps.admin)):
    """Create an account with a hashed password. The password is never shown or stored in plain text."""
    if not USERNAME_RULE.match(body.username):
        raise deps.ApiError(422, "invalid")
    check_link(body.role, body.user_id)
    try:
        new_id = auth.create_account(body.username, body.password, body.role, body.user_id)
    except auth.AuthError as e:
        raise deps.ApiError(422, e.code)
    except sqlite3.IntegrityError:
        raise deps.ApiError(409, "conflict")  # Username taken, or user_id already linked.
    database.audit(p, "account_created", body.user_id, f"{body.username} ({body.role})")
    return account_view(database.get().one("SELECT * FROM accounts WHERE id = ?", (new_id,)))


@router.post("/accounts/{account_id}")
def change_account(account_id: int, body: AccountChange, p=Depends(deps.admin)):
    """Disable or enable, reset the password, set the role, link or unlink a user_id, or unlock."""
    db = database.get()
    a = db.one("SELECT * FROM accounts WHERE id = ?", (account_id,))
    if a is None:
        raise deps.ApiError(404, "not_found")
    sent = body.model_fields_set
    if account_id == p["account_id"] and (("role" in sent and body.role != a["role"]) or body.disabled):
        raise deps.ApiError(409, "conflict")  # An admin cannot lock themselves out.
    role = body.role if "role" in sent and body.role else a["role"]
    user_id = body.user_id if "user_id" in sent else (a["user_id"] if role == "customer" else None)
    check_link(role, user_id)
    changes = []
    try:
        with db.transaction():
            if body.password is not None:
                auth.check_password_rule(body.password)
                db.execute("UPDATE accounts SET pw_hash = ? WHERE id = ?", (auth.hash_password(body.password), account_id))
                changes.append("password_reset")
            if body.disabled is not None:
                db.execute("UPDATE accounts SET disabled = ? WHERE id = ?", (int(body.disabled), account_id))
                changes.append("disabled" if body.disabled else "enabled")
            if role != a["role"] or user_id != a["user_id"]:
                db.execute("UPDATE accounts SET role = ?, user_id = ? WHERE id = ?", (role, user_id, account_id))
                changes.append(f"role={role} user_id={user_id}")
            if body.unlock:
                db.execute("UPDATE accounts SET failed_count = 0, locked_until = 0 WHERE id = ?", (account_id,))
                changes.append("unlocked")
    except auth.AuthError as e:
        raise deps.ApiError(422, e.code)
    except sqlite3.IntegrityError:
        raise deps.ApiError(409, "conflict")
    if set(changes) - {"unlocked"}:
        auth.end_sessions(account_id)  # Any real change signs the account out everywhere.
    database.audit(p, "account_changed", user_id, f"{a['username']}: {', '.join(changes) or 'nothing'}")
    return account_view(db.one("SELECT * FROM accounts WHERE id = ?", (account_id,)))


# ---------------------------------------------------------------------------
# Feature switches (admin changes, analyst reads).
# ---------------------------------------------------------------------------

class SwitchChange(BaseModel):
    """Body for POST /admin/settings. on null removes the setting (back to the default: on)."""
    model_config = ConfigDict(strict=True, extra="forbid")
    key: Literal["live_transactions", "budget_warnings", "unusual_check"]
    on: bool | None
    user_id: int | None = Field(default=None, ge=1)


@router.get("/settings")
def get_settings(_p=Depends(deps.staff)):
    """The global value of each switch and every per-user override."""
    rows = database.get().query("SELECT scope, key, value FROM settings ORDER BY scope, key")
    glob = {k: True for k in cfg.FEATURE_SWITCHES}
    users = []
    for r in rows:
        if r["scope"] == "global":
            glob[r["key"]] = r["value"] == "on"
        else:
            users.append({"user_id": int(r["scope"].split(":")[1]), "key": r["key"], "on": r["value"] == "on"})
    return {"switches": cfg.FEATURE_SWITCHES, "global": glob, "users": users}


@router.post("/settings")
def set_setting(body: SwitchChange, p=Depends(deps.admin)):
    """Turn a switch on or off for everyone, or for one user."""
    if body.user_id is not None and not known_user(body.user_id):
        raise deps.ApiError(404, "not_found")
    scope = "global" if body.user_id is None else f"user:{body.user_id}"
    db = database.get()
    if body.on is None:
        db.execute("DELETE FROM settings WHERE scope = ? AND key = ?", (scope, body.key))
    else:
        db.execute("INSERT INTO settings (scope, key, value, updated_at) VALUES (?, ?, ?, ?) "
                   "ON CONFLICT(scope, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                   (scope, body.key, "on" if body.on else "off", database.now()))
    database.audit(p, "setting_changed", body.user_id, f"{scope} {body.key}={body.on}")
    return get_settings(p)


# ---------------------------------------------------------------------------
# API keys (admin only). The key is returned once, at creation.
# ---------------------------------------------------------------------------

class NewKey(BaseModel):
    """Body for POST /admin/api-keys."""
    model_config = ConfigDict(strict=True, extra="forbid")
    label: str = Field(min_length=1, max_length=80)


@router.get("/api-keys")
def list_keys(_p=Depends(deps.admin)):
    """Every key's id, label, prefix and state; never the key or its hash."""
    return [{"id": k["id"], "label": k["label"], "prefix": k["prefix"], "revoked": bool(k["revoked"]),
             "created_at": iso(k["created_at"])}
            for k in database.get().query("SELECT * FROM api_keys ORDER BY id")]


@router.post("/api-keys")
def create_key(body: NewKey, p=Depends(deps.admin)):
    """Create a key. The answer holds the key once; it cannot be shown again."""
    key_id, key, prefix = auth.create_api_key(body.label, p["account_id"])
    database.audit(p, "api_key_created", detail=f"id {key_id} {prefix}")
    return {"id": key_id, "label": body.label, "prefix": prefix, "key": key, "shown_once": True}


@router.post("/api-keys/{key_id}/revoke")
def revoke_key(key_id: int, p=Depends(deps.admin)):
    """Revoke a key: it stops working at once."""
    if database.get().execute("UPDATE api_keys SET revoked = 1 WHERE id = ?", (key_id,)).rowcount == 0:
        raise deps.ApiError(404, "not_found")
    database.audit(p, "api_key_revoked", detail=f"id {key_id}")
    return {"id": key_id, "revoked": True}


# ---------------------------------------------------------------------------
# Audit log, consent overview and monitoring (admin and analyst).
# ---------------------------------------------------------------------------

@router.get("/audit")
def audit_log(user_id: int | None = Query(default=None, ge=1),
              limit: int = Query(default=cfg.AUDIT_PAGE_SIZE, ge=1, le=cfg.AUDIT_PAGE_SIZE),
              _p=Depends(deps.staff)):
    """Latest audit entries, newest first, optionally only those about one user_id."""
    sql = "SELECT * FROM audit_log" + (" WHERE target_user_id = ?" if user_id else "") + " ORDER BY id DESC LIMIT ?"
    rows = database.get().query(sql, ((user_id,) if user_id else ()) + (limit,))
    return [{"at": iso(r["at"]), "actor": r["actor"], "role": r["role"], "action": r["action"],
             "user_id": r["target_user_id"], "detail": r["detail"]} for r in rows]


@router.get("/consents")
def consents(_p=Depends(deps.staff)):
    """Each customer account with its linked user_id and the state of its latest consent."""
    out = []
    for a in database.get().query("SELECT id, username, user_id FROM accounts WHERE role = 'customer' ORDER BY id"):
        c = database.get().one("SELECT * FROM consents WHERE user_id = ? ORDER BY id DESC LIMIT 1", (a["user_id"],)) \
            if a["user_id"] is not None else None
        out.append({"username": a["username"], "user_id": a["user_id"],
                    "state": "none" if c is None else ("withdrawn" if c["withdrawn_at"] else
                                                       ("given" if c["notice_version"] == cfg.CONSENT_NOTICE_VERSION
                                                        else "old_notice")),
                    "notice_version": c and c["notice_version"], "given_at": iso(c and c["given_at"]),
                    "withdrawn_at": iso(c and c["withdrawn_at"])})
    return {"notice_version": cfg.CONSENT_NOTICE_VERSION, "customers": out}


@router.get("/monitoring")
def monitoring(_p=Depends(deps.staff)):
    """Counts from the prediction and audit logs. Simulated data; no probabilities."""
    db = database.get()
    scored = "outcome = 'scored'"
    ms = [r["ms"] for r in db.query(f"SELECT ms FROM predictions_log WHERE {scored} AND ms IS NOT NULL")]
    return {
        "simulated": True,
        "live_processed": db.one(f"SELECT COUNT(*) n FROM predictions_log WHERE {scored}")["n"],
        "rejected_by_code": {r["error_code"]: r["n"] for r in db.query(
            "SELECT error_code, COUNT(*) n FROM predictions_log WHERE outcome = 'rejected' GROUP BY error_code")},
        "alerts_by_level": {r["band"]: r["n"] for r in db.query(
            f"SELECT band, COUNT(*) n FROM predictions_log WHERE {scored} GROUP BY band")},
        "unusual_flags": db.one(f"SELECT COALESCE(SUM(unusual), 0) n FROM predictions_log WHERE {scored}")["n"],
        "budget_warnings": db.one(
            f"SELECT COALESCE(SUM(budget_warnings), 0) n FROM predictions_log WHERE {scored}")["n"],
        "median_scoring_ms": round(statistics.median(ms), 1) if ms else None,
        "live_rows_stored": db.one("SELECT COUNT(*) n FROM live_transactions")["n"],
        "staff_wallet_views": db.one("SELECT COUNT(*) n FROM audit_log WHERE action LIKE 'view_%'")["n"],
        # Feedback answers per A/B group, e.g. {"A": {"helpful:yes": 3}}. Groups are recorded only.
        "feedback_by_group": feedback_counts(db),
    }


def feedback_counts(db):
    """{group: {"question:answer": count}} from the feedback table."""
    out = {}
    for r in db.query("SELECT ab_group, question, answer, COUNT(*) n FROM feedback GROUP BY ab_group, question, answer"):
        out.setdefault(r["ab_group"], {})[f"{r['question']}:{r['answer']}"] = r["n"]
    return out


@router.delete("/live")
def reset_all_live(p=Depends(deps.admin)):
    """Delete every live transaction for every user, so the demo can be repeated."""
    from src.live import engine  # Imported here: the live engine loads the model data.
    n = engine.reset(None)
    database.audit(p, "live_reset_all", detail=f"{n} rows")
    return {"deleted": n}
