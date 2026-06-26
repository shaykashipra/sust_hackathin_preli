from typing import Any, Literal

from pydantic import BaseModel, Field


class Transaction(BaseModel):
    transaction_id: str
    timestamp: str | None = None
    type: Literal["transfer", "payment", "cash_in", "cash_out", "settlement", "refund"] | str
    amount: float | int | None = None
    counterparty: str | None = None
    status: Literal["completed", "failed", "pending", "reversed"] | str


class TicketRequest(BaseModel):
    ticket_id: str
    complaint: str
    language: Literal["en", "bn", "mixed"] | str | None = None
    channel: Literal[
        "in_app_chat",
        "call_center",
        "email",
        "merchant_portal",
        "field_agent",
    ] | str | None = None
    user_type: Literal["customer", "merchant", "agent", "unknown"] | str | None = None
    campaign_context: str | None = None
    transaction_history: list[Transaction] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TicketResponse(BaseModel):
    ticket_id: str
    relevant_transaction_id: str | None
    evidence_verdict: str
    case_type: str
    severity: str
    department: str
    agent_summary: str
    recommended_next_action: str
    customer_reply: str
    human_review_required: bool
    confidence: float = Field(ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: str
