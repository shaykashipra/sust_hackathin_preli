from dataclasses import dataclass

from app.enums import CaseType, EvidenceVerdict
from app.models import TicketRequest, Transaction
from app.text_utils import extract_amounts, minutes_between, normalize, phone_fragments


TYPE_HINTS = {
    CaseType.WRONG_TRANSFER: {"transfer"},
    CaseType.PAYMENT_FAILED: {"payment"},
    CaseType.REFUND_REQUEST: {"payment", "refund"},
    CaseType.DUPLICATE_PAYMENT: {"payment"},
    CaseType.MERCHANT_SETTLEMENT_DELAY: {"settlement"},
    CaseType.AGENT_CASH_IN_ISSUE: {"cash_in"},
}


@dataclass
class EvidenceResult:
    transaction: Transaction | None
    verdict: EvidenceVerdict
    confidence: float
    reasons: list[str]
    ambiguous: bool = False


def evaluate_evidence(ticket: TicketRequest, case_type: CaseType) -> EvidenceResult:
    txns = ticket.transaction_history or []
    if case_type == CaseType.PHISHING:
        return EvidenceResult(None, EvidenceVerdict.INSUFFICIENT, 0.95, ["phishing", "no_transaction_needed"])
    if not txns:
        return EvidenceResult(None, EvidenceVerdict.INSUFFICIENT, 0.55, ["no_transaction_history"])

    if case_type == CaseType.DUPLICATE_PAYMENT:
        duplicate = find_duplicate_payment(txns)
        if duplicate:
            return EvidenceResult(duplicate, EvidenceVerdict.CONSISTENT, 0.93, ["duplicate_payment", "near_identical_payment"])

    amounts = extract_amounts(ticket.complaint)
    phones = phone_fragments(ticket.complaint)
    candidates = rank_transactions(txns, case_type, amounts, phones)
    if not candidates:
        return EvidenceResult(None, EvidenceVerdict.INSUFFICIENT, 0.55, ["no_plausible_transaction"])

    best, best_score = candidates[0]
    close = [txn for txn, score in candidates if score >= best_score - 1 and score >= 3]
    if len(close) > 1 and not phones:
        return EvidenceResult(None, EvidenceVerdict.INSUFFICIENT, 0.65, ["ambiguous_match"], ambiguous=True)

    verdict, extra_reasons = verdict_for(ticket, best, case_type)
    confidence = min(0.95, 0.5 + (best_score * 0.07))
    if verdict == EvidenceVerdict.INCONSISTENT:
        confidence = min(confidence, 0.78)

    return EvidenceResult(best, verdict, round(confidence, 2), ["transaction_match", *extra_reasons])


def rank_transactions(
    txns: list[Transaction],
    case_type: CaseType,
    amounts: list[float],
    phones: set[str],
) -> list[tuple[Transaction, int]]:
    wanted_types = TYPE_HINTS.get(case_type, set())
    ranked: list[tuple[Transaction, int]] = []
    for txn in txns:
        score = 0
        txn_type = normalize(txn.type)
        status = normalize(txn.status)
        counterparty = normalize(txn.counterparty)

        if txn_type in wanted_types:
            score += 3
        if any(txn.amount is not None and abs(float(txn.amount) - amount) < 0.01 for amount in amounts):
            score += 3
        if phones and any(phone in counterparty for phone in phones):
            score += 3
        if case_type == CaseType.PAYMENT_FAILED and status in {"failed", "pending"}:
            score += 2
        if case_type == CaseType.AGENT_CASH_IN_ISSUE and status in {"pending", "failed"}:
            score += 2
        if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY and status == "pending":
            score += 2
        if case_type == CaseType.WRONG_TRANSFER and status == "completed":
            score += 1
        if case_type == CaseType.REFUND_REQUEST and status == "completed":
            score += 1

        if score >= 3:
            ranked.append((txn, score))
    return sorted(ranked, key=lambda item: item[1], reverse=True)


def find_duplicate_payment(txns: list[Transaction]) -> Transaction | None:
    payments = [t for t in txns if normalize(t.type) == "payment" and normalize(t.status) == "completed"]
    payments = sorted(payments, key=lambda t: t.timestamp or "")
    for i, left in enumerate(payments):
        for right in payments[i + 1 :]:
            same_amount = left.amount is not None and right.amount is not None and float(left.amount) == float(right.amount)
            same_counterparty = normalize(left.counterparty) == normalize(right.counterparty)
            minutes = minutes_between(left.timestamp, right.timestamp)
            if same_amount and same_counterparty and (minutes is None or minutes <= 5):
                return right
    return None


def verdict_for(ticket: TicketRequest, txn: Transaction, case_type: CaseType) -> tuple[EvidenceVerdict, list[str]]:
    status = normalize(txn.status)
    if case_type == CaseType.WRONG_TRANSFER and has_established_recipient_pattern(ticket, txn):
        return EvidenceVerdict.INCONSISTENT, ["established_recipient_pattern"]
    if case_type == CaseType.PAYMENT_FAILED and status == "completed":
        return EvidenceVerdict.INCONSISTENT, ["completed_payment_contradicts_failed_claim"]
    if case_type == CaseType.AGENT_CASH_IN_ISSUE and status == "completed":
        return EvidenceVerdict.INCONSISTENT, ["completed_cash_in_contradicts_claim"]
    return EvidenceVerdict.CONSISTENT, [f"{case_type.value}_evidence"]


def has_established_recipient_pattern(ticket: TicketRequest, txn: Transaction) -> bool:
    target = normalize(txn.counterparty)
    if not target:
        return False
    same_recipient = [
        t
        for t in ticket.transaction_history
        if t.transaction_id != txn.transaction_id
        and normalize(t.type) == "transfer"
        and normalize(t.status) == "completed"
        and normalize(t.counterparty) == target
    ]
    return len(same_recipient) >= 2
