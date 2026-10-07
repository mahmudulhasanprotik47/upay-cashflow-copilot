# FastAPI app for the Cash-Flow Copilot. This file only builds the app: start-up, middleware,
# error handlers and routers. The routes live in src/api/routers/, the work in src/api/service.py.
# All data is simulated.
# Run: python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000

from contextlib import asynccontextmanager  # Start-up hook.

from fastapi import FastAPI, Request  # Web framework.
from fastapi.exceptions import RequestValidationError  # Raised when input fails validation.
from fastapi.middleware.cors import CORSMiddleware  # Lets the allowed web pages call the API.
from starlette.exceptions import HTTPException as StarletteHTTPException  # 404/405 for unknown routes.

from src import config as cfg  # Central settings.
from src.api import service  # Data, models and the cached results.
from src.api.deps import ApiError, error_response  # Coded, bilingual errors.
from src.api.routers import admin, auth, integration, live, results, wallet  # The routes.
from src.integration.event_bus import BUS  # In-process message queue.
from src.db import database  # SQLite storage.
from src.live import engine  # Live transactions (sets the service overlay).
from src.security import auth as security  # The first admin account.
from src.security.middleware import security_middleware  # Identity, rate limits, JSON rule, headers.


@asynccontextmanager
async def lifespan(_app):
    """Load data and models once, open the database, make sure an admin exists, then switch on live data.

    results() is warmed BEFORE the live overlay is installed, so the judges' figures always come from
    the simulated data as loaded and never from live transactions.
    """
    service.state()
    service.results()
    database.init()
    security.ensure_admin()
    engine.install()
    BUS.start()  # Background worker for integration batches.
    yield
    BUS.stop()


app = FastAPI(title="upay Cash-Flow Copilot (simulated)", lifespan=lifespan)

# Identity, rate limits, the JSON rule and security headers for every request.
app.middleware("http")(security_middleware)

# Only the listed local pages may call the API. No wildcard.
app.add_middleware(CORSMiddleware, allow_origins=cfg.CORS_ORIGINS, allow_methods=["GET", "POST", "PUT", "DELETE"],
                   allow_headers=["Content-Type", "X-API-Key"], allow_credentials=True)


@app.exception_handler(ApiError)
async def on_api_error(_request: Request, exc: ApiError):
    """Sign-in, access, consent, validation and rate-limit errors with their code."""
    return error_response(exc.status, exc.code, exc.headers)


@app.exception_handler(RequestValidationError)
async def on_bad_request(_request: Request, _exc):
    """Input failed pydantic checks -> 422."""
    return error_response(422, "invalid")


@app.exception_handler(service.InvalidInput)
async def on_invalid(_request: Request, _exc):
    """Input failed the service's checks -> 422."""
    return error_response(422, "invalid")


@app.exception_handler(service.NotFound)
async def on_not_found(_request: Request, _exc):
    """Unknown user or month -> 404."""
    return error_response(404, "not_found")


@app.exception_handler(StarletteHTTPException)
async def on_http_error(_request: Request, exc):
    """Unknown route (404), wrong method (405) and similar."""
    return error_response(exc.status_code, "not_found" if exc.status_code in (404, 405) else "invalid")


@app.exception_handler(Exception)
async def on_crash(_request: Request, _exc):
    """Anything unexpected -> 500 with a generic message."""
    return error_response(500, "server")


for module in (results, auth, wallet, live, admin, integration):
    app.include_router(module.router)
