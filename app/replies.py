from app.enums import CaseType, Department, EvidenceVerdict, Severity
from app.evidence import EvidenceResult
from app.models import TicketRequest
from app.text_utils import money, normalize


def route(case_type: CaseType) -> Department:
    return {
        CaseType.WRONG_TRANSFER: Department.DISPUTE_RESOLUTION,
        CaseType.PAYMENT_FAILED: Department.PAYMENTS_OPS,
        CaseType.REFUND_REQUEST: Department.CUSTOMER_SUPPORT,
        CaseType.DUPLICATE_PAYMENT: Department.PAYMENTS_OPS,
        CaseType.MERCHANT_SETTLEMENT_DELAY: Department.MERCHANT_OPERATIONS,
        CaseType.AGENT_CASH_IN_ISSUE: Department.AGENT_OPERATIONS,
        CaseType.PHISHING: Department.FRAUD_RISK,
        CaseType.OTHER: Department.CUSTOMER_SUPPORT,
    }[case_type]


def severity_for(case_type: CaseType, evidence: EvidenceResult, ticket: TicketRequest) -> Severity:
    amount = evidence.transaction.amount if evidence.transaction else max_amount(ticket)
    if case_type == CaseType.PHISHING:
        return Severity.CRITICAL
    if case_type == CaseType.DUPLICATE_PAYMENT:
        return Severity.HIGH
    if case_type == CaseType.WRONG_TRANSFER and evidence.ambiguous:
        return Severity.MEDIUM
    if case_type == CaseType.WRONG_TRANSFER and evidence.verdict == EvidenceVerdict.INCONSISTENT:
        return Severity.MEDIUM
    if case_type in {CaseType.WRONG_TRANSFER, CaseType.AGENT_CASH_IN_ISSUE}:
        return Severity.HIGH if (amount or 0) >= 1000 else Severity.MEDIUM
    if case_type == CaseType.PAYMENT_FAILED:
        return Severity.HIGH if evidence.verdict == EvidenceVerdict.CONSISTENT else Severity.MEDIUM
    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        return Severity.MEDIUM
    if case_type == CaseType.REFUND_REQUEST:
        return Severity.LOW if (amount or 0) <= 1000 else Severity.MEDIUM
    return Severity.LOW


def needs_human_review(case_type: CaseType, evidence: EvidenceResult, severity: Severity) -> bool:
    return (
        case_type in {CaseType.WRONG_TRANSFER, CaseType.DUPLICATE_PAYMENT, CaseType.PHISHING}
        or severity == Severity.CRITICAL
        or evidence.verdict == EvidenceVerdict.INCONSISTENT
        or evidence.ambiguous
    )


def build_messages(
    ticket: TicketRequest,
    case_type: CaseType,
    evidence: EvidenceResult,
    department: Department,
) -> tuple[str, str, str]:
    txn = evidence.transaction
    txid = txn.transaction_id if txn else "the reported transaction"
    amount = money(txn.amount if txn else max_amount(ticket))
    counterparty = txn.counterparty or "the counterparty" if txn else "the counterparty"
    lang = normalize(ticket.language)

    if case_type == CaseType.PHISHING:
        return (
            "Customer reports a suspicious contact asking for secret credentials. This is likely social engineering and should be handled by fraud risk.",
            "Escalate to fraud_risk immediately, record any reported caller or message details, and remind the customer to use official support channels only.",
            safe_reply(lang, "phishing", txid),
        )

    if evidence.verdict == EvidenceVerdict.INSUFFICIENT and evidence.ambiguous:
        return (
            f"Customer complaint appears related to {case_type.value}, but multiple transactions could match. More detail is needed before selecting a transaction.",
            "Ask for the exact counterparty, transaction ID, amount, or time before starting any dispute or reversal workflow.",
            safe_reply(lang, "clarify_ambiguous", txid),
        )

    if evidence.verdict == EvidenceVerdict.INSUFFICIENT:
        return (
            "Customer provided insufficient detail to identify a matching transaction from the supplied history.",
            "Ask the customer for the transaction ID, amount, approximate time, and a short description of what went wrong.",
            safe_reply(lang, "clarify", txid),
        )

    if case_type == CaseType.WRONG_TRANSFER:
        if evidence.verdict == EvidenceVerdict.INCONSISTENT:
            return (
                f"Customer claims {txid} was a wrong transfer, but transaction history suggests an established recipient pattern with {counterparty}.",
                "Flag for human review and verify whether this was genuinely a wrong transfer before opening the dispute workflow.",
                safe_reply(lang, "review", txid),
            )
        return (
            f"Customer reports sending {amount} via {txid} to {counterparty} and believes it was the wrong recipient.",
            f"Verify {txid} with the customer and initiate the wrong-transfer dispute workflow per policy.",
            safe_reply(lang, "review", txid),
        )

    if case_type == CaseType.PAYMENT_FAILED:
        return (
            f"Customer reports a failed payment or deducted balance linked to {txid} for {amount}.",
            f"Check {txid} ledger state in payments_ops and start the standard reversal process only if the deduction is confirmed eligible.",
            safe_reply(lang, "eligible_return", txid),
        )

    if case_type == CaseType.REFUND_REQUEST:
        return (
            f"Customer requests a refund for {txid} involving {amount}. Eligibility depends on policy or merchant confirmation.",
            "Explain the refund eligibility path and route only contested or policy-sensitive cases for review.",
            safe_reply(lang, "merchant_refund", txid),
        )

    if case_type == CaseType.DUPLICATE_PAYMENT:
        return (
            f"Customer reports a duplicate payment. {txid} appears to be the likely duplicate transaction for {amount}.",
            f"Verify {txid} with payments_ops or the biller, then process only any eligible reversal through official channels.",
            safe_reply(lang, "eligible_return", txid),
        )

    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        return (
            f"Merchant reports delayed settlement for {txid} involving {amount}; supplied evidence points to a pending settlement.",
            "Route to merchant_operations to verify settlement batch status and communicate an official ETA.",
            safe_reply(lang, "merchant_settlement", txid),
        )

    if case_type == CaseType.AGENT_CASH_IN_ISSUE:
        return (
            f"Customer reports cash-in issue for {txid} involving {amount}; agent operations should verify the cash-in state.",
            f"Investigate {txid} with agent_operations and resolve according to the standard cash-in SLA.",
            safe_reply(lang, "review", txid),
        )

    return (
        "Customer has a general support concern that does not fit a more specific taxonomy from the supplied evidence.",
        "Handle through customer_support and ask concise follow-up questions if transaction details are missing.",
        safe_reply(lang, "clarify", txid),
    )


def safe_reply(language: str, kind: str, txid: str) -> str:
    if language == "bn":
        if kind == "phishing":
            return (
                "ধন্যবাদ আমাদের জানানোর জন্য। আমরা কখনও আপনার PIN, OTP বা password চাই না। "
                "অনুগ্রহ করে এগুলো কারও সাথে শেয়ার করবেন না। বিষয়টি আমাদের fraud team পর্যালোচনা করবে।"
            )
        return (
            f"আপনার {txid} লেনদেনের বিষয়ে আমরা তথ্য পেয়েছি। সংশ্লিষ্ট দল অফিসিয়াল চ্যানেলের মাধ্যমে "
            "আপডেট জানাবে। অনুগ্রহ করে আপনার PIN বা OTP কারও সাথে শেয়ার করবেন না।"
        )

    if kind == "phishing":
        return (
            "Thank you for reporting this. We never ask for your PIN, OTP, password, or full card number. "
            "Please do not share these with anyone, even if they claim to be from us. Our fraud team will review the incident."
        )
    if kind == "clarify_ambiguous":
        return (
            "Thank you for reaching out. We see more than one possible matching transaction, so please share the transaction ID, "
            "counterparty, or approximate time so we can identify the right one. Please do not share your PIN or OTP with anyone."
        )
    if kind == "clarify":
        return (
            "Thank you for reaching out. To help you faster, please share the transaction ID, amount, approximate time, "
            "and what went wrong. Please do not share your PIN or OTP with anyone."
        )
    if kind == "eligible_return":
        return (
            f"We have noted your concern about transaction {txid}. Our team will verify the case, and any eligible amount "
            "will be returned through official channels. Please do not share your PIN or OTP with anyone."
        )
    if kind == "merchant_refund":
        return (
            "Thank you for reaching out. Refund eligibility for a completed merchant payment depends on the applicable "
            "merchant or service policy. We can guide you through the official support process. Please do not share your PIN or OTP with anyone."
        )
    if kind == "merchant_settlement":
        return (
            f"We have noted your concern about settlement {txid}. Our merchant operations team will check the batch status "
            "and update you through official channels."
        )
    return (
        f"We have received your request regarding transaction {txid}. The relevant team will review it and contact you "
        "through official support channels. Please do not share your PIN or OTP with anyone."
    )


def max_amount(ticket: TicketRequest) -> float | None:
    amounts = [float(t.amount) for t in ticket.transaction_history if t.amount is not None]
    return max(amounts) if amounts else None
