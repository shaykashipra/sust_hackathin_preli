"""
Main pipeline — orchestrates steps 1-8 as described in the spec.
All scored/classified fields are determined by deterministic rules.
Groq provides draft text + extraction hints; the rules always have final authority.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.classifier import (
    classify_case_type,
    classify_department,
    classify_severity,
    has_phishing_signal,
    requires_human_review,
)
from app.groq_client import call_groq
from app.matcher import determine_verdict, find_best_transaction
from app.safety import scrub_customer_reply, scrub_next_action
from app.schemas import (
    CaseType,
    EvidenceVerdict,
    Language,
    Severity,
    TicketRequest,
    TicketResponse,
    UserType,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rule-based signal extraction (always runs; Groq supplements when available)
# ---------------------------------------------------------------------------

_AMOUNT_RE = re.compile(
    r"(?:৳|BDT|Taka|taka)\s*(\d[\d,]*(?:\.\d+)?)"
    r"|(\d[\d,]*(?:\.\d+)?)\s*(?:BDT|Taka|taka|৳|টাকা)",
    re.IGNORECASE,
)
_GENERIC_AMOUNT_RE = re.compile(r"(?<!\d)(\d{2,7})(?!\d)")
_PHONE_RE = re.compile(r"01[3-9]\d{8}")
_FUNDING_RE = re.compile(
    r"\b("
    r"funding|fund\s+support|fund\s+chai|fund\s+lagbe|fund\s+dorkar|"
    r"financial\s+assistance|grant|loan|micro\s*loan|"
    r"tk\s+lagbe|taka\s+lagbe|money\s+needed"
    r")\b",
    re.IGNORECASE,
)


def _is_funding_request(complaint: str) -> bool:
    return bool(_FUNDING_RE.search(complaint))


def _extract_rule_signals(complaint: str) -> Dict[str, Any]:
    signals: Dict[str, Any] = {
        "claimed_amount": None,
        "counterparty_hint": None,
        "time_hint": None,
        "intent": None,
        "phishing_flag": False,
    }

    m = _AMOUNT_RE.search(complaint)
    if m:
        raw = (m.group(1) or m.group(2)).replace(",", "")
        try:
            signals["claimed_amount"] = float(raw)
        except ValueError:
            pass
    elif not _PHONE_RE.search(complaint):
        m = _GENERIC_AMOUNT_RE.search(complaint)
        if m:
            signals["claimed_amount"] = float(m.group(1))

    ph = _PHONE_RE.search(complaint)
    if ph:
        signals["counterparty_hint"] = ph.group(0)

    return signals


def _detect_language(complaint: str) -> str:
    """Guess language by Unicode script presence."""
    bangla_chars = sum(1 for c in complaint if "ঀ" <= c <= "৿")
    if bangla_chars > 5:
        latin_chars = sum(1 for c in complaint if c.isascii() and c.isalpha())
        return "mixed" if latin_chars > 5 else "bn"
    return "en"


# ---------------------------------------------------------------------------
# Rule-only draft text (used when Groq is unavailable)
# ---------------------------------------------------------------------------

_SUMMARIES: Dict[CaseType, str] = {
    CaseType.phishing_or_social_engineering: (
        "Customer reports a possible social-engineering or phishing attempt. "
        "Account has not been compromised but security review is advised."
    ),
    CaseType.payment_failed: (
        "Customer reports a payment that failed; their account may have been debited."
    ),
    CaseType.duplicate_payment: (
        "Customer reports being charged twice for the same transaction."
    ),
    CaseType.refund_request: (
        "Customer requests a refund for a completed payment."
    ),
    CaseType.wrong_transfer: (
        "Customer claims a transfer was sent to an unintended recipient."
    ),
    CaseType.merchant_settlement_delay: (
        "Merchant reports a settlement payment has not been received."
    ),
    CaseType.agent_cash_in_issue: (
        "Customer reports a cash-in through an agent that has not been credited."
    ),
    CaseType.other: (
        "Customer reports an unspecified account issue requiring further investigation."
    ),
}

_NEXT_ACTIONS: Dict[CaseType, str] = {
    CaseType.phishing_or_social_engineering: (
        "Flag the account for a security audit and advise the customer to change their PIN immediately through the bKash app."
    ),
    CaseType.payment_failed: (
        "Verify the transaction status in the payment system and initiate a reversal if the debit was applied without a successful payment."
    ),
    CaseType.duplicate_payment: (
        "Retrieve both transaction records, confirm the duplicate, and escalate to Dispute Resolution for reversal of the second charge."
    ),
    CaseType.refund_request: (
        "Check merchant's refund policy; escalate to Customer Support for review and merchant contact."
    ),
    CaseType.wrong_transfer: (
        "Verify the recipient's account, note the transfer details, and escalate to Dispute Resolution for a reversal attempt."
    ),
    CaseType.merchant_settlement_delay: (
        "Check settlement batch status for this merchant and escalate to Merchant Operations if processing is delayed beyond SLA."
    ),
    CaseType.agent_cash_in_issue: (
        "Verify the cash-in transaction with the agent's terminal log and escalate to Agent Operations to credit the customer's account."
    ),
    CaseType.other: (
        "Review the customer's recent account activity and escalate to Customer Support for further investigation."
    ),
}

_REPLIES_EN: Dict[CaseType, str] = {
    CaseType.phishing_or_social_engineering: (
        "Dear Customer, thank you for alerting us. We have noted your report about the suspicious contact. "
        "Please be assured that bKash will never call you and ask for your PIN or OTP. "
        "If you have not shared any credentials, your account is safe. "
        "If you did share any credentials, please change your PIN immediately in the bKash app."
    ),
    CaseType.payment_failed: (
        "Dear Customer, we are sorry to hear about your payment issue. "
        "We have received your complaint and our team will investigate the failed transaction. "
        "If any amount was deducted from your account in error, any eligible amount will be returned "
        "through official channels after investigation."
    ),
    CaseType.duplicate_payment: (
        "Dear Customer, we sincerely apologise for the inconvenience. "
        "We have noted your report of a duplicate payment. "
        "Our Dispute Resolution team will investigate and any eligible amount will be returned "
        "through official bKash channels after investigation is complete."
    ),
    CaseType.refund_request: (
        "Dear Customer, thank you for contacting bKash support. "
        "We have received your refund request. Please note that refund eligibility depends on "
        "the merchant's policy. Our team will review your case and contact you."
    ),
    CaseType.wrong_transfer: (
        "Dear Customer, we understand your concern about the transfer. "
        "We have logged your complaint. Our Dispute Resolution team will investigate this matter. "
        "Please note that recovery depends on the recipient's cooperation and our investigation outcome."
    ),
    CaseType.merchant_settlement_delay: (
        "Dear Merchant, we apologise for the delay in your settlement. "
        "Our Merchant Operations team is investigating the issue and will ensure your settlement "
        "is processed as soon as possible through official channels."
    ),
    CaseType.agent_cash_in_issue: (
        "Dear Customer, we are sorry for the inconvenience with your cash-in. "
        "We have received your complaint and our Agent Operations team will verify your transaction "
        "with the agent's records. Any eligible amount will be credited through official channels."
    ),
    CaseType.other: (
        "Dear Customer, thank you for contacting bKash support. "
        "We have received your complaint and our team will investigate and contact you shortly."
    ),
}

_REPLIES_BN: Dict[CaseType, str] = {
    CaseType.phishing_or_social_engineering: (
        "প্রিয় গ্রাহক, আমাদের অবহিত করার জন্য ধন্যবাদ। "
        "আপনার সন্দেহজনক কলের রিপোর্টটি আমরা নথিভুক্ত করেছি। "
        "bKash কখনো ফোন করে আপনার পিন বা ওটিপি চায় না। "
        "যদি আপনি কোনো তথ্য শেয়ার না করে থাকেন, তাহলে আপনার একাউন্ট নিরাপদ।"
    ),
    CaseType.payment_failed: (
        "প্রিয় গ্রাহক, আপনার পেমেন্ট সমস্যার জন্য আমরা দুঃখিত। "
        "আমরা আপনার অভিযোগ পেয়েছি এবং আমাদের দল তদন্ত করবে। "
        "তদন্তের পর যোগ্য ক্ষেত্রে অফিসিয়াল চ্যানেলে টাকা ফেরত দেওয়া হবে।"
    ),
    CaseType.duplicate_payment: (
        "প্রিয় গ্রাহক, দ্বৈত পেমেন্টের জন্য আমরা আন্তরিকভাবে ক্ষমা চাইছি। "
        "আমরা আপনার অভিযোগ নথিভুক্ত করেছি। তদন্ত সম্পন্ন হলে "
        "যোগ্য ক্ষেত্রে অফিসিয়াল bKash চ্যানেলে টাকা ফেরত দেওয়া হবে।"
    ),
    CaseType.refund_request: (
        "প্রিয় গ্রাহক, bKash সাপোর্টে যোগাযোগ করার জন্য ধন্যবাদ। "
        "আমরা আপনার রিফান্ড অনুরোধ পেয়েছি। "
        "রিফান্ডের যোগ্যতা মার্চেন্টের নীতির উপর নির্ভর করে। আমাদের দল বিষয়টি পর্যালোচনা করবে।"
    ),
    CaseType.wrong_transfer: (
        "প্রিয় গ্রাহক, আপনার ট্রান্সফার সম্পর্কে আমরা উদ্বিগ্ন। "
        "আমরা আপনার অভিযোগ নথিভুক্ত করেছি। আমাদের বিরোধ নিষ্পত্তি দল বিষয়টি তদন্ত করবে।"
    ),
    CaseType.merchant_settlement_delay: (
        "প্রিয় মার্চেন্ট, সেটেলমেন্ট বিলম্বের জন্য আমরা ক্ষমাপ্রার্থী। "
        "আমাদের দল বিষয়টি তদন্ত করছে এবং যত দ্রুত সম্ভব সেটেলমেন্ট প্রক্রিয়া করা হবে।"
    ),
    CaseType.agent_cash_in_issue: (
        "প্রিয় গ্রাহক, ক্যাশ-ইন সমস্যার জন্য আমরা দুঃখিত। "
        "আমরা আপনার অভিযোগ পেয়েছি এবং এজেন্ট অপারেশন দল বিষয়টি যাচাই করবে।"
    ),
    CaseType.other: (
        "প্রিয় গ্রাহক, bKash সাপোর্টে যোগাযোগ করার জন্য ধন্যবাদ। "
        "আমরা আপনার অভিযোগ পেয়েছি এবং দ্রুত যোগাযোগ করব।"
    ),
}


def _fallback_draft(case_type: CaseType, language: Optional[str]) -> tuple[str, str, str]:
    """Return (agent_summary, next_action, customer_reply) for rule-only mode."""
    summary = _SUMMARIES.get(case_type, _SUMMARIES[CaseType.other])
    action = _NEXT_ACTIONS.get(case_type, _NEXT_ACTIONS[CaseType.other])
    if language == "bn":
        reply = _REPLIES_BN.get(case_type, _REPLIES_BN[CaseType.other])
    else:
        reply = _REPLIES_EN.get(case_type, _REPLIES_EN[CaseType.other])
    return summary, action, reply


def _matched_transaction(txns: List[Any], txn_id: Optional[str]) -> Optional[Any]:
    if not txn_id:
        return None
    return next((txn for txn in txns if txn.transaction_id == txn_id), None)


def _customize_customer_reply(
    reply: str,
    case_type: CaseType,
    verdict: EvidenceVerdict,
    relevant_txn_id: Optional[str],
    txns: List[Any],
    language: Optional[str],
    funding_request: bool = False,
) -> str:
    """Add evidence-aware detail while preserving the safe template wording."""
    if funding_request and case_type == CaseType.other:
        if language == "bn":
            return (
                "Dear Customer, we understand that you are asking about fund or financial support. "
                "This support ticket cannot approve, send, or guarantee funds. Please check eligible bKash "
                "products or official support channels for available options. Do not share any PIN, OTP, "
                "password, or full card number."
            )
        return (
            "Dear Customer, we understand that you are asking about fund or financial support. "
            "This support ticket cannot approve, send, or guarantee funds. Please check eligible bKash "
            "products or official support channels for available options. Do not share any PIN, OTP, "
            "password, or full card number."
        )

    if language == "bn":
        return reply

    txn = _matched_transaction(txns, relevant_txn_id)
    if txn:
        amount = f"{txn.amount:g} BDT"
        status = txn.status.value if hasattr(txn.status, "value") else str(txn.status)
        txn_type = txn.type.value.replace("_", " ") if hasattr(txn.type, "value") else str(txn.type).replace("_", " ")
        details = [
            f"We have linked transaction {txn.transaction_id} ({amount}, {txn_type}, status: {status}) to this case.",
        ]
        if case_type == CaseType.wrong_transfer:
            details.append("Our team will verify the transfer details and attempt recovery according to policy; recovery depends on investigation outcome and recipient cooperation.")
        elif case_type == CaseType.payment_failed:
            details.append("Our team will compare the debit record with the payment status and return any eligible amount through official channels after review.")
        elif case_type == CaseType.duplicate_payment:
            details.append("Our team will verify whether this is the duplicate charge before any reversal decision is made.")
        elif case_type == CaseType.refund_request:
            details.append("Our team will review the payment and merchant policy before confirming whether a refund is eligible.")
        elif case_type == CaseType.merchant_settlement_delay:
            details.append("Our team will check the settlement batch and update you through official support channels.")
        elif case_type == CaseType.agent_cash_in_issue:
            details.append("Our team will verify the cash-in record with agent operations before any balance correction.")
        return f"{reply}\n\n" + " ".join(details)

    if case_type == CaseType.payment_failed and verdict == EvidenceVerdict.insufficient_data:
        return (
            f"{reply}\n\n"
            "To check the failed payment faster, please share the transaction ID if available, payment amount, "
            "merchant or biller name, and approximate date/time through official support channels."
        )

    if verdict == EvidenceVerdict.insufficient_data:
        return (
            f"{reply}\n\n"
            "To help us resolve this faster, please share the transaction ID, amount, approximate date/time, "
            "and receiver or merchant name through official support channels. Do not include any PIN, OTP, "
            "password, or full card number."
        )
    return reply


# ---------------------------------------------------------------------------
# Confidence + reason codes
# ---------------------------------------------------------------------------

def _compute_confidence(
    case_type: CaseType,
    evidence_verdict: str,
    groq_ok: bool,
    relevant_txn_id: Optional[str],
) -> float:
    base = 0.4
    if evidence_verdict == EvidenceVerdict.consistent:
        base += 0.3
    elif evidence_verdict == EvidenceVerdict.inconsistent:
        base += 0.15
    if relevant_txn_id:
        base += 0.1
    if groq_ok:
        base += 0.1
    if case_type == CaseType.phishing_or_social_engineering:
        base += 0.05
    return round(min(base, 0.95), 2)


def _build_reason_codes(
    case_type: CaseType,
    evidence_verdict: str,
    groq_ok: bool,
    phishing_pre: bool,
    relevant_txn_id: Optional[str],
) -> List[str]:
    codes: List[str] = [f"case:{case_type.value}", f"verdict:{evidence_verdict}"]
    if phishing_pre:
        codes.append("phishing_keyword_detected")
    if not groq_ok:
        codes.append("groq_unavailable")
        codes.append("fallback_rules")
    if evidence_verdict == EvidenceVerdict.inconsistent:
        codes.append("established_recipient")
    if relevant_txn_id:
        codes.append("transaction_matched")
    else:
        codes.append("no_transaction_matched")
    return codes


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

async def analyze_ticket(request: TicketRequest) -> TicketResponse:
    # ── Step 2: Pre-scan ──────────────────────────────────────────────────
    phishing_pre = has_phishing_signal(request.complaint)
    funding_request = _is_funding_request(request.complaint)
    detected_lang = _detect_language(request.complaint)
    effective_lang = request.language.value if request.language else detected_lang

    # Always extract rule-based signals as the reliable baseline
    rule_signals = _extract_rule_signals(request.complaint)

    # ── Step 3: Groq call ─────────────────────────────────────────────────
    txns = request.transaction_history or []
    groq_signals, groq_ok = await call_groq(request.complaint, txns)

    # Merge: Groq overrides rule signals where it provides non-null values
    claimed_amount: Optional[float] = rule_signals.get("claimed_amount")
    time_hint: Optional[str] = rule_signals.get("time_hint")
    counterparty_hint: Optional[str] = rule_signals.get("counterparty_hint")
    groq_intent: Optional[str] = None
    groq_phishing: bool = False

    if groq_ok and groq_signals:
        if groq_signals.get("claimed_amount") is not None:
            claimed_amount = groq_signals["claimed_amount"]
        if groq_signals.get("time_hint"):
            time_hint = groq_signals["time_hint"]
        if groq_signals.get("counterparty_hint"):
            counterparty_hint = groq_signals["counterparty_hint"]
        groq_intent = groq_signals.get("intent")
        groq_phishing = bool(groq_signals.get("phishing_flag", False))

    phishing_flag = phishing_pre or groq_phishing

    # ── Steps 4–6: Classification (rules authoritative) ───────────────────
    case_type = classify_case_type(request.complaint, phishing_flag, groq_intent)

    # Use intent as a string for matcher (mirrors case_type value, minus _phishing suffix)
    _ct_to_intent: Dict[CaseType, str] = {
        CaseType.wrong_transfer: "wrong_transfer",
        CaseType.payment_failed: "payment_failed",
        CaseType.refund_request: "refund_request",
        CaseType.duplicate_payment: "duplicate_payment",
        CaseType.merchant_settlement_delay: "merchant_settlement_delay",
        CaseType.agent_cash_in_issue: "agent_cash_in_issue",
        CaseType.phishing_or_social_engineering: "phishing",
        CaseType.other: "other",
    }
    matcher_intent = _ct_to_intent.get(case_type, "other")
    if groq_intent and not phishing_flag:
        matcher_intent = groq_intent  # Groq gives finer-grained hint

    is_duplicate = case_type == CaseType.duplicate_payment

    relevant_txn_id = find_best_transaction(
        transactions=txns,
        claimed_amount=claimed_amount,
        time_hint=time_hint,
        counterparty_hint=counterparty_hint,
        intent=matcher_intent,
        is_duplicate=is_duplicate,
    )

    verdict_str = determine_verdict(
        relevant_txn_id=relevant_txn_id,
        transactions=txns,
        intent=matcher_intent,
        counterparty_hint=counterparty_hint,
    )
    verdict = EvidenceVerdict(verdict_str)

    department = classify_department(case_type, request.user_type)
    is_inconsistent = verdict == EvidenceVerdict.inconsistent
    severity = classify_severity(case_type, verdict_str, claimed_amount, is_inconsistent)
    review_required = requires_human_review(case_type, severity, verdict_str, claimed_amount)

    # ── Step 7: Draft text ────────────────────────────────────────────────
    if groq_ok and groq_signals:
        agent_summary = groq_signals.get("draft_summary") or _SUMMARIES.get(case_type, _SUMMARIES[CaseType.other])
        next_action = groq_signals.get("draft_next_action") or _NEXT_ACTIONS.get(case_type, _NEXT_ACTIONS[CaseType.other])
        customer_reply = groq_signals.get("draft_reply") or (
            _REPLIES_BN if effective_lang == "bn" else _REPLIES_EN
        ).get(case_type, "")
    else:
        agent_summary, next_action, customer_reply = _fallback_draft(case_type, effective_lang)

    customer_reply = _customize_customer_reply(
        customer_reply,
        case_type,
        verdict,
        relevant_txn_id,
        txns,
        effective_lang,
        funding_request,
    )

    # ── Step 7: Safety scrub (ALWAYS) ─────────────────────────────────────
    customer_reply = scrub_customer_reply(customer_reply, effective_lang)
    next_action = scrub_next_action(next_action)

    # ── Step 8: Build response ────────────────────────────────────────────
    reason_codes = _build_reason_codes(
        case_type, verdict_str, groq_ok, phishing_pre, relevant_txn_id
    )
    if funding_request and case_type == CaseType.other:
        reason_codes.append("funding_request_detected")
    confidence = _compute_confidence(case_type, verdict_str, groq_ok, relevant_txn_id)

    return TicketResponse(
        ticket_id=request.ticket_id,
        relevant_transaction_id=relevant_txn_id,
        evidence_verdict=verdict,
        case_type=case_type,
        severity=severity,
        department=department,
        agent_summary=agent_summary,
        recommended_next_action=next_action,
        customer_reply=customer_reply,
        human_review_required=review_required,
        confidence=confidence,
        reason_codes=reason_codes,
    )
