# Live transactions, budgets and the customer's own live-data reset. All data is simulated.
# A live transaction is scored by the saved model in this process; nothing here moves money.

from typing import Annotated, Literal  # Input types.

from fastapi import APIRouter, Depends, Path, Query  # Routing.
from pydantic import BaseModel, ConfigDict, Field  # Request body checks.

from src import config as cfg  # Types, months, limits.
from src.api import deps, service  # Access rules; user-month checks.
from src.db import database  # Budgets and the audit log.
from src.live import budgets, engine  # Budget bars; validation, storage and rescoring.

router = APIRouter()
UserId = Annotated[int, Path(ge=1)]


class LiveTransaction(BaseModel):
    """Body for POST /live/transactions. Ranges are checked by the engine so each failure gets its own code."""
    model_config = ConfigDict(strict=True, extra="forbid")
    user_id: int = Field(ge=1)
    month: int = Field(ge=0, le=cfg.N_MONTHS - 1)
    day: int
    type: str = Field(min_length=1, max_length=40)
    amount: int | float
    idempotency_key: str = Field(min_length=1, max_length=64)
    lang: Literal["en", "bn"] = "en"


class BudgetChange(BaseModel):
    """Body for PUT /users/{id}/budgets: {type: amount, or null to go back to the default}."""
    model_config = ConfigDict(strict=True, extra="forbid")
    budgets: dict[str, int | None] = Field(min_length=1, max_length=len(cfg.BUDGET_TYPES))


@router.post("/live/transactions")
def add_transaction(body: LiveTransaction, p=Depends(deps.principal)):
    """Add one transaction, rescore the month, and return the new assessment and what changed.

    The customer for their own user_id, or an admin. Analysts and API keys get 403.
    """
    deps.check_write(p, body.user_id, consent=False)  # Consent is checked (and logged) by the engine.
    try:
        return engine.submit(body.user_id, body.month, body.day, body.type, body.amount, body.idempotency_key,
                             body.lang)
    except engine.Rejected as e:
        raise deps.ApiError(e.status, e.code)


@router.get("/users/{user_id}/budgets")
def get_budgets(user_id: UserId, month: int = Query(ge=0, le=cfg.N_MONTHS - 1), p=Depends(deps.principal)):
    """Budget bars for one user-month (a rule, not AI)."""
    deps.check_read(p, user_id, "budgets")
    service.check_user_month(user_id, month)
    if not deps.feature_on("budget_warnings", user_id):
        return {"enabled": False, "bars": [], "warnings": 0}
    return budgets.budget_bars(user_id, month)


@router.put("/users/{user_id}/budgets")
def set_budgets(user_id: UserId, body: BudgetChange, p=Depends(deps.principal)):
    """Set your own monthly budget per type (null removes it and the default comes back)."""
    deps.check_write(p, user_id)
    if any(t not in cfg.BUDGET_TYPES or (v is not None and not 1 <= v <= cfg.WHATIF_MAX_BDT)
           for t, v in body.budgets.items()):
        raise deps.ApiError(422, "invalid")
    db = database.get()
    with db.transaction():
        for t, v in body.budgets.items():
            if v is None:
                db.execute("DELETE FROM budgets WHERE user_id = ? AND type = ?", (user_id, t))
            else:
                db.execute("INSERT INTO budgets (user_id, type, amount_bdt, updated_at) VALUES (?, ?, ?, ?) "
                           "ON CONFLICT(user_id, type) DO UPDATE SET amount_bdt = excluded.amount_bdt, "
                           "updated_at = excluded.updated_at", (user_id, t, v, database.now()))
    database.audit(p, "budgets_set", user_id, ", ".join(f"{t}={v}" for t, v in body.budgets.items()))
    return {"saved": True, "budgets": budgets.custom_budgets(user_id)}


@router.delete("/me/live")
def reset_my_live(p=Depends(deps.customer)):
    """Delete this customer's live transactions so the demo can be repeated."""
    n = engine.reset(p["user_id"])
    database.audit(p, "live_reset_own", p["user_id"], f"{n} rows")
    return {"deleted": n}
