from app.enums import CaseType, Department, EvidenceVerdict, Severity
from app.models import TicketResponse


DEPARTMENT_BY_CASE = {
    CaseType.WRONG_TRANSFER.value: Department.DISPUTE_RESOLUTION.value,
    CaseType.PAYMENT_FAILED.value: Department.PAYMENTS_OPS.value,
    CaseType.REFUND_REQUEST.value: Department.CUSTOMER_SUPPORT.value,
    CaseType.DUPLICATE_PAYMENT.value: Department.PAYMENTS_OPS.value,
    CaseType.MERCHANT_SETTLEMENT_DELAY.value: Department.MERCHANT_OPERATIONS.value,
    CaseType.AGENT_CASH_IN_ISSUE.value: Department.AGENT_OPERATIONS.value,
    CaseType.PHISHING.value: Department.FRAUD_RISK.value,
    CaseType.OTHER.value: Department.CUSTOMER_SUPPORT.value,
}


def enforce_consistency(response: TicketResponse) -> list[str]:
    changes: list[str] = []
    expected_department = DEPARTMENT_BY_CASE.get(response.case_type)
    if expected_department and response.department != expected_department:
        response.department = expected_department
        changes.append(f"department corrected to {expected_department}")

    if response.case_type == CaseType.PHISHING.value:
        if response.severity not in {Severity.HIGH.value, Severity.CRITICAL.value}:
            response.severity = Severity.CRITICAL.value
            changes.append("phishing severity raised to critical")
        if not response.human_review_required:
            response.human_review_required = True
            changes.append("phishing human review enabled")

    risky_or_unclear = (
        response.evidence_verdict in {EvidenceVerdict.INCONSISTENT.value}
        or response.case_type in {
            CaseType.PHISHING.value,
            CaseType.WRONG_TRANSFER.value,
            CaseType.DUPLICATE_PAYMENT.value,
        }
        or response.severity == Severity.CRITICAL.value
    )
    if risky_or_unclear and not response.human_review_required:
        response.human_review_required = True
        changes.append("human review enabled for risky case")

    return changes
