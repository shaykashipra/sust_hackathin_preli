from app.enums import CaseType
from app.models import TicketRequest
from app.text_utils import contains_any, normalize


PHISHING_WORDS = [
    "otp",
    "pin",
    "password",
    "credential",
    "blocked if",
    "account block",
    "verify your account",
    "share code",
    "secret",
    "scam",
    "fraud",
    "call kore",
    "otp চেয়েছে",
    "পিন",
    "ওটিপি",
    "পাসওয়ার্ড",
]


def detect_case_type(ticket: TicketRequest) -> CaseType:
    text = normalize(ticket.complaint)
    user_type = normalize(ticket.user_type)
    channel = normalize(ticket.channel)

    if contains_any(text, PHISHING_WORDS):
        return CaseType.PHISHING

    if contains_any(text, ["duplicate", "twice", "double", "deducted twice", "charged twice", "দুইবার"]):
        return CaseType.DUPLICATE_PAYMENT

    if "merchant" in user_type or "merchant_portal" in channel:
        if contains_any(text, ["settlement", "settled", "sales", "merchant", "সেটেল"]):
            return CaseType.MERCHANT_SETTLEMENT_DELAY

    if contains_any(text, ["cash in", "cash-in", "cashin", "agent", "এজেন্ট", "ক্যাশ ইন"]):
        if contains_any(text, ["not reflected", "not received", "pending", "আসেনি", "পাইনি", "balance"]):
            return CaseType.AGENT_CASH_IN_ISSUE

    if contains_any(text, ["failed", "failure", "deducted", "balance was deducted", "but my balance", "ফেইল"]):
        return CaseType.PAYMENT_FAILED

    if contains_any(
        text,
        [
            "wrong number",
            "wrong person",
            "wrong recipient",
            "mistake",
            "reverse it",
            "did not get it",
            "didn't get it",
            "did not receive",
            "not received",
            "ভুল",
        ],
    ):
        return CaseType.WRONG_TRANSFER

    if contains_any(text, ["refund", "return my money", "money back", "রিফান্ড", "ফেরত"]):
        return CaseType.REFUND_REQUEST

    return CaseType.OTHER
