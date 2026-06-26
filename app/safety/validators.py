import re

from app.models import TicketResponse
from app.text_utils import normalize


CREDENTIAL_TERMS = [
    "otp",
    "o t p",
    "o.t.p",
    "pin",
    "pin number",
    "pincode",
    "password",
    "pass word",
    "passcode",
    "cvv",
    "full card number",
    "verification code",
    "secret code",
]

PROMISE_PATTERNS = [
    r"\bwe will refund\b",
    r"\bwill be refunded\b",
    r"\brefund (is )?confirmed\b",
    r"\brefund approved\b",
    r"\brefund diye dibo\b",
    r"\brefund dibo\b",
    r"\btaka ferot (diye )?dibo\b",
    r"\btk ferot (diye )?dibo\b",
    r"\bfund (diye )?dibo\b",
    r"\bmoney will be returned\b",
    r"\bwe (have )?reversed\b",
    r"\breversal confirmed\b",
    r"\baccount (is )?unblocked\b",
    r"\brecovery confirmed\b",
]

THIRD_PARTY_PATTERNS = [
    r"\bwhatsapp\b",
    r"\bfacebook\b",
    r"\bimo\b",
    r"\btelegram\b",
    r"\bcall this number\b",
    r"\bcall (him|her|them)\b",
    r"\bcall kore\b",
    r"\bmessage this\b",
    r"\binbox\b",
    r"\bcontact this agent\b",
    r"\bcontact the caller\b",
]

PHONE_PATTERN = r"(?:\+?88)?01[3-9]\d{8}"

SAFE_CREDENTIAL_WARNING = (
    "Please do not share your PIN, OTP, password, full card number, or secret credentials with anyone. "
    "Use official support channels only."
)


def has_credential_request(text: str) -> bool:
    clean = normalize(text)
    if not any(term in clean for term in CREDENTIAL_TERMS):
        return False
    request_words = ["share", "send", "provide", "give", "tell", "confirm", "enter", "submit"]
    safe_words = ["do not share", "never ask", "never share", "do not provide"]
    return any(word in clean for word in request_words) and not any(word in clean for word in safe_words)


def has_unsafe_promise(text: str) -> bool:
    clean = normalize(text)
    return any(re.search(pattern, clean) for pattern in PROMISE_PATTERNS)


def has_third_party_direction(text: str) -> bool:
    clean = normalize(text)
    return any(re.search(pattern, clean) for pattern in THIRD_PARTY_PATTERNS) or bool(re.search(PHONE_PATTERN, clean))


def safe_customer_fallback(response: TicketResponse) -> str:
    if response.case_type == "phishing_or_social_engineering":
        return (
            "Thank you for reporting this. We never ask for your PIN, OTP, password, or full card number. "
            "Please do not share these with anyone. Our fraud team will review the incident through official channels."
        )
    return (
        f"We have received your request regarding transaction {response.relevant_transaction_id or 'the reported issue'}. "
        "Our team will review the case and contact you through official support channels. "
        + SAFE_CREDENTIAL_WARNING
    )


def safe_action_fallback(response: TicketResponse) -> str:
    if response.case_type == "phishing_or_social_engineering":
        return "Escalate to fraud_risk and guide the customer to official support channels only."
    return "Review the case through the official workflow. Do not promise financial action before eligibility is confirmed."
