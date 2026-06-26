from __future__ import annotations

import logging
import os
import time
import uuid
from collections import defaultdict
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
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

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
_API_KEY = os.getenv("API_KEY")  # if unset, key check is skipped (dev mode)
_MAX_BODY_BYTES = int(os.getenv("MAX_BODY_BYTES", str(1 * 1024 * 1024)))  # 1 MB
_RATE_LIMIT_RPM = int(os.getenv("RATE_LIMIT_RPM", "20"))  # requests per minute per IP
_ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="QueueStorm Investigator",
    description="Fintech support copilot API — classifies and routes customer complaints.",
    version="1.0.0",
)

# CORS — only allow configured domains
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# ---------------------------------------------------------------------------
# In-memory rate limiter — sliding window per IP
# ---------------------------------------------------------------------------
_rate_data: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(ip: str) -> None:
    now = time.monotonic()
    hits = _rate_data[ip]
    _rate_data[ip] = [t for t in hits if now - t < 60.0]
    if len(_rate_data[ip]) >= _RATE_LIMIT_RPM:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
    _rate_data[ip].append(now)


# ---------------------------------------------------------------------------
# Middleware: X-Request-ID + request size limit + rate limiting
# ---------------------------------------------------------------------------
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _MAX_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={"detail": f"Request body too large. Max {_MAX_BODY_BYTES} bytes allowed."},
            headers={"X-Request-ID": request_id},
        )

    if request.method == "POST":
        ip = request.client.host if request.client else "unknown"
        try:
            _check_rate_limit(ip)
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers={"X-Request-ID": request_id},
            )

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "rid=%s method=%s path=%s status=%s",
        request_id, request.method, request.url.path, response.status_code,
    )
    return response


# ---------------------------------------------------------------------------
# API Key dependency (B2B header auth)
# ---------------------------------------------------------------------------
async def verify_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    if _API_KEY and x_api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header.")


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
    dependencies=[Depends(verify_api_key)],
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
