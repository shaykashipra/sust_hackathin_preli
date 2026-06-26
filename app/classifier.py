"""
Deterministic classification: case_type, department, severity, human_review_required.
Groq's 'intent' field is used only as a secondary hint — rules are authoritative.
"""
from __future__ import annotations

from typing import Optional

from app.schemas import CaseType, Department, EvidenceVerdict, Severity, UserType

# ---------------------------------------------------------------------------
# Phishing keyword detection
# ---------------------------------------------------------------------------

_PHISHING_EN = [
    "otp", "one time password", "pin", "password", "passcode",
    "share code", "share your code", "account will be blocked", "account blocked",
    "verify your account", "verification code", "your account has been",
    "suspended", "bkash agent called", "called from bkash",
    "bkash office called", "lottery", "prize", "you won", "free money",
    "send money to activate", "bkash helpline", "impersonat",
    "do not share", "never share",  # already warned — maybe user quoting attacker
]

_PHISHING_BN = [
    "ওটিপি", "পিন", "পাসওয়ার্ড", "কোড শেয়ার", "একাউন্ট বন্ধ",
    "একাউন্ট ব্লক", "ভেরিফাই", "যাচাই করুন", "ভেরিফিকেশন",
    "বিকাশ অফিস থেকে ফোন", "বিকাশ এজেন্ট ফোন", "লটারি", "পুরস্কার",
    "ফ্রি টাকা", "টাকা পাঠান", "একাউন্ট সাসপেন্ড",
]


def has_phishing_signal(complaint: str) -> bool:
    c = complaint.lower()
    for kw in _PHISHING_EN:
        if kw in c:
            return True
    # Bangla check — no .lower() needed, just substring
    for kw in _PHISHING_BN:
        if kw in complaint:
            return True
    return False


# ---------------------------------------------------------------------------
# Keyword sets for other case types
# ---------------------------------------------------------------------------

_PAYMENT_FAILED_KW = [
    "payment failed", "failed to pay", "not completed", "unsuccessful",
    "didn't go through", "deducted but not received", "deducted but merchant",
    "money deducted", "charged but", "transaction failed",
]

_DUPLICATE_KW = [
    "charged twice", "twice", "two times", "double charge", "billed two times",
    "duplicate", "two payments", "same payment twice", "double deduction",
    "deducted twice",
]

_REFUND_KW = [
    "refund", "return my money", "give back", "cancel", "want back",
    "reversal", "money back", "get it back",
]

_WRONG_TRANSFER_KW = [
    "wrong number", "wrong person", "wrong account", "mistake", "accidentally",
    "wrong transfer", "sent to wrong", "by mistake", "mistakenly",
]

_SETTLEMENT_KW = [
    "settlement", "pending settlement", "not received payment", "merchant payment",
    "shop payment", "settlement delay", "settlement pending",
]

_AGENT_CASH_IN_KW = [
    "cash in", "cash-in", "agent cash", "cash in not reflected", "cash in not received",
    "cash in pending", "deposited through agent", "recharge through agent",
    "cash in but", "did a cash in",
]


def classify_case_type(
    complaint: str,
    phishing_flag: bool,
    groq_intent: Optional[str],
) -> CaseType:
    """Priority order: phishing > payment_failed > duplicate > refund > wrong_transfer >
    settlement_delay > agent_cash_in > other."""
    if phishing_flag or has_phishing_signal(complaint):
        return CaseType.phishing_or_social_engineering

    c = complaint.lower()

    if any(kw in c for kw in _PAYMENT_FAILED_KW):
        return CaseType.payment_failed

    if any(kw in c for kw in _DUPLICATE_KW):
        return CaseType.duplicate_payment

    if any(kw in c for kw in _REFUND_KW):
        return CaseType.refund_request

    if any(kw in c for kw in _WRONG_TRANSFER_KW):
        return CaseType.wrong_transfer

    if any(kw in c for kw in _SETTLEMENT_KW):
        return CaseType.merchant_settlement_delay

    if any(kw in c for kw in _AGENT_CASH_IN_KW):
        return CaseType.agent_cash_in_issue

    # Use Groq intent as a secondary hint only
    _groq_map: dict[str, CaseType] = {
        "wrong_transfer": CaseType.wrong_transfer,
        "payment_failed": CaseType.payment_failed,
        "refund_request": CaseType.refund_request,
        "duplicate_payment": CaseType.duplicate_payment,
        "merchant_settlement_delay": CaseType.merchant_settlement_delay,
        "agent_cash_in_issue": CaseType.agent_cash_in_issue,
        "phishing": CaseType.phishing_or_social_engineering,
    }
    if groq_intent and groq_intent in _groq_map:
        return _groq_map[groq_intent]

    return CaseType.other


# ---------------------------------------------------------------------------
# Department mapping
# ---------------------------------------------------------------------------

_BASE_DEPT: dict[CaseType, Department] = {
    CaseType.phishing_or_social_engineering: Department.fraud_risk,
    CaseType.payment_failed: Department.customer_support,
    CaseType.duplicate_payment: Department.dispute_resolution,
    CaseType.refund_request: Department.customer_support,
    CaseType.wrong_transfer: Department.dispute_resolution,
    CaseType.merchant_settlement_delay: Department.merchant_operations,
    CaseType.agent_cash_in_issue: Department.agent_operations,
    CaseType.other: Department.customer_support,
}


def classify_department(case_type: CaseType, user_type: Optional[UserType]) -> Department:
    dept = _BASE_DEPT.get(case_type, Department.customer_support)
    # Merchant users: payment issues route to merchant_operations
    if user_type == UserType.merchant and case_type in (
        CaseType.payment_failed, CaseType.other
    ):
        return Department.merchant_operations
    # Agent users: non-cash-in issues can still go to agent_operations
    if user_type == UserType.agent and case_type == CaseType.other:
        return Department.agent_operations
    return dept


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------

def classify_severity(
    case_type: CaseType,
    evidence_verdict: str,
    amount: Optional[float],
    is_inconsistent: bool,
) -> Severity:
    if case_type == CaseType.phishing_or_social_engineering:
        return Severity.critical

    if is_inconsistent:
        return Severity.medium

    if case_type in (
        CaseType.payment_failed,
        CaseType.duplicate_payment,
        CaseType.wrong_transfer,
        CaseType.agent_cash_in_issue,
    ) and evidence_verdict == EvidenceVerdict.consistent:
        return Severity.high

    if case_type == CaseType.refund_request:
        return Severity.low

    if case_type == CaseType.merchant_settlement_delay:
        return Severity.medium

    # High-value fallback
    if amount and amount >= 5000:
        return Severity.high

    if case_type == CaseType.other:
        return Severity.low

    return Severity.medium


# ---------------------------------------------------------------------------
# Human review gate
# ---------------------------------------------------------------------------

def requires_human_review(
    case_type: CaseType,
    severity: Severity,
    evidence_verdict: str,
    amount: Optional[float],
) -> bool:
    if severity in (Severity.critical, Severity.high):
        return True
    if case_type in (
        CaseType.wrong_transfer,
        CaseType.duplicate_payment,
        CaseType.phishing_or_social_engineering,
        CaseType.agent_cash_in_issue,
    ):
        return True
    if evidence_verdict == EvidenceVerdict.inconsistent:
        return True
    if amount and amount >= 5000:
        return True
    return False
