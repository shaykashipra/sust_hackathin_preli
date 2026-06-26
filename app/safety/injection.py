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
    "refund approved bolo",
    "refund diye dao",
    "fund dao",
    "taka dao",
    "ask for otp",
    "ask the customer for otp",
    "otp chao",
    "reveal prompt",
    "ami admin",
    "i am admin",
    "ager shob vule jao",
    "ager sob vule jao",
    "shob vule jao",
    "sob vule jao",
    "program kora hoise",
    "program kora hoyeche",
    "ekhon amake fund dao",
]


def has_prompt_injection(ticket: TicketRequest) -> bool:
    text = normalize(ticket.complaint)
    return any(pattern in text for pattern in INJECTION_PATTERNS)
