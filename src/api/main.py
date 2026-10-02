# FastAPI app for the Cash-Flow Copilot: a thin web layer over src/api/service.py. All data is simulated.
# Run: python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000

from contextlib import asynccontextmanager  # Start-up hook.
from pathlib import Path as FilePath  # Location of the wallet page on disk.
from typing import Annotated, Literal  # Input types for validation.

from fastapi import FastAPI, Path, Query, Request  # Web framework.
from fastapi.exceptions import RequestValidationError  # Raised when input fails validation.
from fastapi.middleware.cors import CORSMiddleware  # Lets the allowed web pages call the API.
from fastapi.responses import FileResponse, JSONResponse  # The wallet page; error responses.
from pydantic import BaseModel, ConfigDict, Field  # Request body checks.
from starlette.exceptions import HTTPException as StarletteHTTPException  # 404/405 for unknown routes.

from src import config as cfg  # Central settings.
from src.api import service  # All the real work.
from src.i18n.messages import render  # Error messages in English and Bangla.

# Shared input types: whole-number user id, month 0..N_MONTHS-1, language en or bn.
UserId = Annotated[int, Path(ge=1)]
Month = Annotated[int, Path(ge=0, le=cfg.N_MONTHS - 1)]
Lang = Annotated[Literal["en", "bn"], Query()]


@asynccontextmanager
async def lifespan(_app):
    """Load data, features and models once when the server starts."""
    service.state()
    yield


app = FastAPI(title="upay Cash-Flow Copilot (simulated)", lifespan=lifespan)

# Only the listed local pages may call the API. No wildcard.
app.add_middleware(CORSMiddleware, allow_origins=cfg.CORS_ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type"])


def error(status, key):
    """A short generic error in both languages. Never a stack trace, never the raw input."""
    return JSONResponse(status_code=status,
                        content={"error": render(key, "en"), "error_bn": render(key, "bn")})


@app.exception_handler(RequestValidationError)
async def on_bad_request(_request: Request, _exc):
    """Input failed pydantic checks -> 422."""
    return error(422, "error_invalid")


@app.exception_handler(service.InvalidInput)
async def on_invalid(_request: Request, _exc):
    """Input failed the service's checks -> 422."""
    return error(422, "error_invalid")


@app.exception_handler(service.NotFound)
async def on_not_found(_request: Request, _exc):
    """Unknown user or month -> 404."""
    return error(404, "error_not_found")


@app.exception_handler(StarletteHTTPException)
async def on_http_error(_request: Request, exc):
    """Unknown route (404), wrong method (405) and similar."""
    return error(exc.status_code, "error_not_found" if exc.status_code in (404, 405) else "error_invalid")


@app.exception_handler(Exception)
async def on_crash(_request: Request, _exc):
    """Anything unexpected -> 500 with a generic message."""
    return error(500, "error_server")


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


@app.get("/", include_in_schema=False)
def wallet_page():
    """The wallet screen: one self-contained HTML file, hidden from the API docs."""
    return FileResponse(FilePath(__file__).resolve().parents[2] / "frontend" / "index.html", media_type="text/html")


@app.get("/health")
def health():
    """Is the server up, and how long did start-up take?"""
    return {"status": "ok", "startup_seconds": service.state()["startup_seconds"]}


@app.get("/users")
def users():
    """User ids and income types for a dropdown."""
    return service.list_users()


@app.get("/users/{user_id}/months/{month}/forecast")
def forecast(user_id: UserId, month: Month, lang: Lang = "en"):
    """Risk band, reasons, suggestions and chart data for one user-month."""
    return service.forecast(user_id, month, lang)


@app.get("/users/{user_id}/months/{month}/summary")
def summary(user_id: UserId, month: Month, lang: Lang = "en"):
    """Spending on days 1-20 by category and by week."""
    return service.month_summary(user_id, month, lang)


@app.post("/savings-plan")
def savings_plan(body: SavingsRequest):
    """Savings plan for a goal (none while the user has an alert)."""
    return service.savings_plan(body.user_id, body.month, body.goal_bdt, body.months, body.lang)


@app.post("/whatif")
def whatif(body: WhatIfRequest):
    """Forecast with some inputs changed, next to the original."""
    return service.whatif(body.user_id, body.month, body.overrides, body.lang)


@app.get("/model-results")
def model_results():
    """Metrics, fairness, global SHAP and the honest summary."""
    return service.model_results()


@app.get("/results")
def results():
    """Trimmed results for the judges' tab plus the cached cash-out fee base (English only)."""
    return service.results()
