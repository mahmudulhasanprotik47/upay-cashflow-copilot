# Sign-in, sign-out, "who am I", and the customer's consent to the data notice. All data is simulated.

from fastapi import APIRouter, Depends, Request  # Routing and dependencies.
from fastapi.responses import JSONResponse  # Login answer with the cookie.
from pydantic import BaseModel, ConfigDict, Field  # Request body checks.

from src import config as cfg  # Cookie name, notice version.
from src.api import deps  # Access rules and errors.
from src.db import database  # Consent rows and the audit log.
from src.i18n.messages import render  # The notice text in both languages.
from src.security import auth  # Passwords and sessions.

router = APIRouter()


class LoginRequest(BaseModel):
    """Body for POST /auth/login. JSON only (no form posts)."""
    model_config = ConfigDict(strict=True, extra="forbid")
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class ConsentRequest(BaseModel):
    """Body for POST /me/consent: the notice version the customer read."""
    model_config = ConfigDict(strict=True, extra="forbid")
    notice_version: str = Field(min_length=1, max_length=40)


def consent_state(p):
    """Consent details for /auth/me: needed only for a customer linked to a user_id."""
    required = p["role"] == "customer" and p["user_id"] is not None
    return {"required": required, "given": required and deps.has_consent(p["user_id"]),
            "notice_version": cfg.CONSENT_NOTICE_VERSION,
            "notice": {"en": render("consent_notice", "en"), "bn": render("consent_notice", "bn")}}


def me_body(p):
    """The signed-in identity as the pages see it (never a hash or token)."""
    return {"username": p["name"], "role": p["role"], "user_id": p["user_id"], "consent": consent_state(p),
            "simulated": True}


@router.post("/auth/login")
def login(body: LoginRequest, request: Request):
    """Check the password; on success set an HttpOnly, SameSite=Strict session cookie."""
    try:
        token, p = auth.login(body.username, body.password)
    except auth.AuthError as e:
        database.audit({"name": body.username[:80], "role": "unknown"}, "login_failed", detail=e.code)
        raise deps.ApiError(423 if e.code == "locked" else 401, e.code)
    database.audit(p, "login_ok")
    response = JSONResponse(me_body(p))
    response.set_cookie(cfg.SESSION_COOKIE, token, max_age=cfg.SESSION_HOURS * 3600, httponly=True,
                        samesite="strict", path="/")  # No Secure flag: localhost runs plain HTTP.
    return response


@router.post("/auth/logout")
def logout(request: Request):
    """Delete the session (if any) and clear the cookie."""
    p = getattr(request.state, "principal", None)
    auth.logout(request.cookies.get(cfg.SESSION_COOKIE))
    if p:
        database.audit(p, "logout")
    response = JSONResponse({"signed_out": True})
    response.delete_cookie(cfg.SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    return response


@router.get("/auth/me")
def me(p=Depends(deps.principal)):
    """Who is signed in, their role, their linked user_id and their consent state."""
    return me_body(p)


@router.post("/me/consent")
def give_consent(body: ConsentRequest, p=Depends(deps.customer)):
    """Record the customer's consent to the current notice (the old one is closed first)."""
    if body.notice_version != cfg.CONSENT_NOTICE_VERSION:
        raise deps.ApiError(409, "conflict")  # They read an older notice: show the new one first.
    db = database.get()
    with db.transaction():
        db.execute("UPDATE consents SET withdrawn_at = ? WHERE user_id = ? AND withdrawn_at IS NULL",
                   (database.now(), p["user_id"]))
        db.execute("INSERT INTO consents (user_id, notice_version, given_at) VALUES (?, ?, ?)",
                   (p["user_id"], cfg.CONSENT_NOTICE_VERSION, database.now()))
    database.audit(p, "consent_given", p["user_id"], cfg.CONSENT_NOTICE_VERSION)
    return me_body(p)


@router.get("/me/export")
def export_my_data(p=Depends(deps.customer)):
    """Everything stored about this customer, as JSON (never the password hash or session tokens)."""
    db, uid = database.get(), p["user_id"]
    account = db.one("SELECT id, username, role, user_id, disabled, created_at FROM accounts WHERE id = ?",
                     (p["account_id"],))
    database.audit(p, "data_exported", uid)
    return {"simulated": True, "account": account,
            "consents": db.query("SELECT notice_version, given_at, withdrawn_at FROM consents WHERE user_id = ?", (uid,)),
            "live_transactions": db.query("SELECT month, day, type, direction, amount, fee, created_at "
                                          "FROM live_transactions WHERE user_id = ? ORDER BY id", (uid,)),
            "budgets": db.query("SELECT type, amount_bdt, updated_at FROM budgets WHERE user_id = ?", (uid,)),
            "feedback": db.query("SELECT suggestion_type, question, answer, created_at FROM feedback "
                                 "WHERE user_id = ?", (uid,)),
            "settings": db.query("SELECT key, value, updated_at FROM settings WHERE scope = ?", (f"user:{uid}",))}


@router.delete("/me/data")
def delete_my_data(p=Depends(deps.customer)):
    """Delete this customer's live transactions, budgets, feedback and per-user settings.

    The account, the consent record and the audit log stay: they show what was agreed and done.
    """
    from src.live import engine  # Imported here: the live engine loads the model data.
    uid, db = p["user_id"], database.get()
    counts = {"live_transactions": engine.reset(uid)}
    with db.transaction():
        counts["budgets"] = db.execute("DELETE FROM budgets WHERE user_id = ?", (uid,)).rowcount
        counts["feedback"] = db.execute("DELETE FROM feedback WHERE user_id = ?", (uid,)).rowcount
        counts["settings"] = db.execute("DELETE FROM settings WHERE scope = ?", (f"user:{uid}",)).rowcount
    database.audit(p, "data_deleted", uid, ", ".join(f"{k}={v}" for k, v in counts.items()))
    return {"deleted": counts}


@router.post("/me/consent/withdraw")
def withdraw_consent(p=Depends(deps.customer)):
    """Withdraw consent: no new assessment is made until consent is given again."""
    database.get().execute("UPDATE consents SET withdrawn_at = ? WHERE user_id = ? AND withdrawn_at IS NULL",
                           (database.now(), p["user_id"]))
    database.audit(p, "consent_withdrawn", p["user_id"])
    return me_body(p)
