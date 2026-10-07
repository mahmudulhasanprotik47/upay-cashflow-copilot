# The original wallet endpoints (users, forecast, summary, savings plan, what-if), now behind sign-in.
# Same paths and same response fields as before; one field is added: data_subject, which says whether
# the user_id is a linked customer or an unlinked simulated fixture. All data is simulated.

from typing import Annotated, Literal  # Input types for validation.

from fastapi import APIRouter, Depends, Path, Query  # Routing.
from pydantic import BaseModel, ConfigDict, Field  # Request body checks.

from src import config as cfg  # Central settings.
from src.api import deps, service  # Access rules; all the real work.
from src.live import risk_factors  # Risk-factor codes, levels and the model target (new fields).

router = APIRouter()

# Shared input types: whole-number user id, month 0..N_MONTHS-1, language en or bn.
UserId = Annotated[int, Path(ge=1)]
Month = Annotated[int, Path(ge=0, le=cfg.N_MONTHS - 1)]
Lang = Annotated[Literal["en", "bn"], Query()]


class SavingsRequest(BaseModel):
    """Body for POST /savings-plan. Strict: numbers must be numbers, no extra fields."""
    model_config = ConfigDict(strict=True, extra="forbid")
    user_id: int = Field(ge=1)
    month: int = Field(ge=0, le=cfg.N_MONTHS - 1)
    goal_bdt: int = Field(ge=1, le=cfg.WHATIF_MAX_BDT)
    months: int = Field(ge=1, le=cfg.SAVINGS_MAX_MONTHS)
    lang: Literal["en", "bn"] = "en"


class WhatIfRequest(BaseModel):
    """Body for POST /whatif. The service checks each override value."""
    model_config = ConfigDict(strict=True, extra="forbid")
    user_id: int = Field(ge=1)
    month: int = Field(ge=0, le=cfg.N_MONTHS - 1)
    overrides: dict[str, object] = Field(min_length=1, max_length=len(service.FEATURES))
    lang: Literal["en", "bn"] = "en"


def check_exists(user_id, month):
    """404 for an unknown user-month, after the access check so a customer cannot probe other ids."""
    service.check_user_month(user_id, month)


@router.get("/users")
def users(p=Depends(deps.principal)):
    """User ids and income types for a dropdown. A customer sees only their own entry."""
    everyone = service.list_users()
    if p["role"] == "customer":
        return [u for u in everyone if u["user_id"] == p["user_id"]]
    return everyone


@router.get("/users/{user_id}/months/{month}/forecast")
def forecast(user_id: UserId, month: Month, lang: Lang = "en", p=Depends(deps.principal)):
    """Risk band, reasons, suggestions and chart data for one user-month."""
    deps.check_read(p, user_id, "forecast")
    check_exists(user_id, month)
    out = risk_factors.enrich(service.forecast(user_id, month, lang), service.features_for(user_id, month), lang)
    return {**out, "data_subject": deps.data_subject(user_id)}


@router.get("/users/{user_id}/months/{month}/summary")
def summary(user_id: UserId, month: Month, lang: Lang = "en", p=Depends(deps.principal)):
    """Spending on days 1-20 by category and by week."""
    deps.check_read(p, user_id, "summary")
    check_exists(user_id, month)
    return service.month_summary(user_id, month, lang)


@router.post("/savings-plan")
def savings_plan(body: SavingsRequest, p=Depends(deps.principal)):
    """Savings plan for a goal (none while the user has an alert). Reading only, so the read rule applies."""
    deps.check_read(p, body.user_id, "savings_plan")
    check_exists(body.user_id, body.month)
    return service.savings_plan(body.user_id, body.month, body.goal_bdt, body.months, body.lang)


@router.post("/whatif")
def whatif(body: WhatIfRequest, p=Depends(deps.principal)):
    """Forecast with some inputs changed, next to the original. Changes nothing stored."""
    deps.check_read(p, body.user_id, "whatif")
    check_exists(body.user_id, body.month)
    out = service.whatif(body.user_id, body.month, body.overrides, body.lang)
    original = service.features_for(body.user_id, body.month)
    risk_factors.enrich(out["original"], original, body.lang)  # Both sides get codes, levels, targets.
    risk_factors.enrich(out["whatif"], {**original, **out["changed_inputs"]}, body.lang)
    return out
