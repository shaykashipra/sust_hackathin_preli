from app.classifier import detect_case_type
from app.evidence import evaluate_evidence
from app.models import TicketRequest, TicketResponse
from app.replies import build_messages, needs_human_review, route, severity_for


def analyze(ticket: TicketRequest) -> TicketResponse:
    case_type = detect_case_type(ticket)
    evidence = evaluate_evidence(ticket, case_type)
    department = route(case_type)
    severity = severity_for(case_type, evidence, ticket)
    summary, next_action, customer_reply = build_messages(ticket, case_type, evidence, department)

    reason_codes = list(dict.fromkeys([case_type.value, department.value, *evidence.reasons]))

    return TicketResponse(
        ticket_id=ticket.ticket_id,
        relevant_transaction_id=evidence.transaction.transaction_id if evidence.transaction else None,
        evidence_verdict=evidence.verdict.value,
        case_type=case_type.value,
        severity=severity.value,
        department=department.value,
        agent_summary=summary,
        recommended_next_action=next_action,
        customer_reply=customer_reply,
        human_review_required=needs_human_review(case_type, evidence, severity),
        confidence=evidence.confidence,
        reason_codes=reason_codes,
    )
