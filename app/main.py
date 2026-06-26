from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.analyzer import analyze
from app.models import ErrorResponse, TicketRequest, TicketResponse


app = FastAPI(
    title="QueueStorm Investigator",
    version="1.0.0",
    description="Evidence-grounded support ticket investigator for the SUST preliminary round.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze-ticket", response_model=TicketResponse)
def analyze_ticket(ticket: TicketRequest) -> TicketResponse:
    if not ticket.complaint.strip():
        return JSONResponse(status_code=422, content={"error": "complaint must not be empty"})
    if not ticket.ticket_id.strip():
        return JSONResponse(status_code=422, content={"error": "ticket_id must not be empty"})
    return analyze(ticket)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content=ErrorResponse(error="invalid or missing request fields").model_dump())


@app.exception_handler(Exception)
async def generic_exception_handler(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content=ErrorResponse(error="internal error").model_dump())
