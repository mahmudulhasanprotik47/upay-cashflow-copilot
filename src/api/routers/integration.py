# Machine-client integration: a batch of simulated transactions is accepted with an API key, queued on the
# event bus, and scored in the background. Not a real upay integration. All data is simulated.

import datetime  # Readable timestamps.
import secrets  # Batch ids.

from fastapi import APIRouter, Depends, Request  # Routing.
from fastapi.responses import JSONResponse  # 202 answer.
from pydantic import BaseModel, ConfigDict, Field  # Request body checks.

from src import config as cfg  # Batch limit.
from src.api import deps  # Access rules.
from src.db import database  # event_batches.
from src.integration.event_bus import BUS  # The queue.

router = APIRouter(prefix="/integration")


class Event(BaseModel):
    """One transaction in a batch. Ranges are checked by the live engine, as for the page."""
    model_config = ConfigDict(strict=True, extra="forbid")
    user_id: int = Field(ge=1)
    month: int = Field(ge=0, le=cfg.N_MONTHS - 1)
    day: int
    type: str = Field(min_length=1, max_length=40)
    amount: int | float
    idempotency_key: str = Field(min_length=1, max_length=64)


class Batch(BaseModel):
    """Body for POST /integration/events."""
    model_config = ConfigDict(strict=True, extra="forbid")
    events: list[Event] = Field(min_length=1, max_length=cfg.INTEGRATION_MAX_BATCH)


def machine(request: Request):
    """Dependency: an API key only (sessions get 403)."""
    p = deps.principal(request)
    if p["kind"] != "api_key":
        raise deps.ApiError(403, "forbidden")
    return p


@router.post("/events")
def publish(body: Batch, p=Depends(machine)):
    """Accept a batch: store its status row, queue it, answer 202 with the batch id at once."""
    batch_id = secrets.token_hex(8)
    database.get().execute("INSERT INTO event_batches (id, api_key_id, status, total, created_at) "
                           "VALUES (?, ?, 'queued', ?, ?)", (batch_id, p["key_id"], len(body.events), database.now()))
    BUS.publish(batch_id, [e.model_dump() for e in body.events])
    return JSONResponse(status_code=202, content={"batch_id": batch_id, "status": "queued", "total": len(body.events),
                                                  "simulated": True})


@router.get("/events/{batch_id}")
def status(batch_id: str, request: Request):
    """Status of one batch: the API key that sent it, or staff."""
    p = deps.principal(request)
    row = database.get().one("SELECT * FROM event_batches WHERE id = ?", (batch_id[:32],))
    if row is None:
        raise deps.ApiError(404, "not_found")
    if not (p["role"] in ("admin", "analyst") or (p["kind"] == "api_key" and p["key_id"] == row["api_key_id"])):
        raise deps.ApiError(403, "forbidden")
    iso = lambda t: None if t is None else datetime.datetime.fromtimestamp(t, datetime.UTC).isoformat(timespec="seconds")  # noqa: E731
    return {"batch_id": row["id"], "status": row["status"], "total": row["total"], "accepted": row["accepted"],
            "rejected": row["rejected"], "created_at": iso(row["created_at"]), "finished_at": iso(row["finished_at"]),
            "simulated": True}
