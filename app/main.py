from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.pipeline import analyze_ticket
from app.schemas import TicketRequest, TicketResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent.parent / "static"

app = FastAPI(
    title="QueueStorm Investigator",
    description="Fintech support copilot API — classifies and routes customer complaints.",
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Validation error handler — maps Pydantic errors to correct HTTP codes:
#   json_invalid  → 400  (malformed JSON body)
#   missing field → 400
#   wrong enum    → 400
#   empty complaint (value_error) → 422
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    complaint_empty = any(
        "complaint" in str(e.get("loc", "")) and "empty" in str(e.get("msg", "")).lower()
        for e in errors
    )
    json_invalid = any(e.get("type") == "json_invalid" for e in errors)

    if complaint_empty:
        status = 422
    elif json_invalid:
        status = 400
    else:
        # missing fields, wrong enum, wrong type → 400
        status = 400

    return JSONResponse(
        status_code=status,
        content={
            "detail": [
                {"field": " -> ".join(str(l) for l in e["loc"]), "msg": e["msg"]}
                for e in errors
            ]
        },
    )


# ---------------------------------------------------------------------------
# Global exception handler — never leak stack traces or keys
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled error on %s: %s", request.url.path, type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please try again later."},
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(str(_STATIC_DIR / "index.html"))


@app.post(
    "/analyze-ticket",
    response_model=TicketResponse,
    tags=["tickets"],
    summary="Analyze a customer support ticket",
)
async def analyze_ticket_endpoint(ticket: TicketRequest) -> TicketResponse:
    return await analyze_ticket(ticket)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)
