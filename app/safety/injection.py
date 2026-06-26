from app.models import TicketRequest
from app.text_utils import normalize


INJECTION_PATTERNS = [
    "ignore previous instructions",
    "ignore all previous instructions",
    "forget system prompt",
    "forget your instructions",
    "act as",
    "you are now",
    "developer mode",
    "override",
    "bypass",
    "say refund approved",
    "ask for otp",
    "ask the customer for otp",
    "reveal prompt",
]


def has_prompt_injection(ticket: TicketRequest) -> bool:
    text = normalize(ticket.complaint)
    return any(pattern in text for pattern in INJECTION_PATTERNS)
