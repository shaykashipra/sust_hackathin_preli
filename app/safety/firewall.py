from app.models import TicketRequest, TicketResponse
from app.safety.audit import SafetyAudit
from app.safety.consistency import enforce_consistency
from app.safety.injection import has_prompt_injection
from app.safety.validators import (
    has_credential_request,
    has_third_party_direction,
    has_unsafe_promise,
    safe_action_fallback,
    safe_customer_fallback,
)


def apply_safety_firewall(ticket: TicketRequest, response: TicketResponse) -> TicketResponse:
    audit = SafetyAudit()

    injection_detected = has_prompt_injection(ticket)
    audit.set_check("prompt_injection_absorbed", True)
    if injection_detected:
        audit.add("Prompt injection pattern detected in complaint and ignored.")
        if "prompt_injection_ignored" not in response.reason_codes:
            response.reason_codes.append("prompt_injection_ignored")

    for change in enforce_consistency(response):
        audit.add(change)
    audit.set_check("decision_consistency", True)

    customer_text = response.customer_reply
    action_text = response.recommended_next_action

    credential_request = has_credential_request(customer_text) or has_credential_request(action_text)
    unsafe_promise = has_unsafe_promise(customer_text) or has_unsafe_promise(action_text)
    third_party = has_third_party_direction(customer_text) or has_third_party_direction(action_text)

    audit.set_check("no_credential_request", not credential_request)
    audit.set_check("no_unsafe_promise", not unsafe_promise)
    audit.set_check("official_channel_only", not third_party)

    if credential_request or unsafe_promise or third_party:
        response.customer_reply = safe_customer_fallback(response)
        response.recommended_next_action = safe_action_fallback(response)
        response.human_review_required = True
        if "safety_rewritten" not in response.reason_codes:
            response.reason_codes.append("safety_rewritten")
        audit.add("Unsafe output rewritten by safety firewall.")

    if audit.events and "safety_firewall_applied" not in response.reason_codes:
        response.reason_codes.append("safety_firewall_applied")

    return response
