"""
Functional tests against SUST_Preli_Sample_Cases.json.
Runs without GROQ_API_KEY so the pure-rules fallback is exercised.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

# Ensure no Groq key so every test exercises the fallback path
os.environ.pop("GROQ_API_KEY", None)

from app.main import app  # noqa: E402 — imported after env is cleared

_CASES_PATH = Path(__file__).parent.parent / "SUST_Preli_Sample_Cases.json"
_SEVERITY_ORDER = ["low", "medium", "high", "critical"]

if not _CASES_PATH.exists():
    pytest.skip(
        "SUST_Preli_Sample_Cases.json is not present; skipping optional public sample pack tests.",
        allow_module_level=True,
    )


def _load_cases():
    with open(_CASES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def cases():
    return _load_cases()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_malformed_json(client: TestClient) -> None:
    r = client.post(
        "/analyze-ticket",
        content=b"not-json{{{",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_missing_required_field(client: TestClient) -> None:
    r = client.post("/analyze-ticket", json={"ticket_id": "X"})
    assert r.status_code in (400, 422)


def test_empty_complaint_422(client: TestClient) -> None:
    r = client.post("/analyze-ticket", json={"ticket_id": "X", "complaint": "   "})
    assert r.status_code == 422


def test_empty_complaint_empty_string(client: TestClient) -> None:
    r = client.post("/analyze-ticket", json={"ticket_id": "X", "complaint": ""})
    assert r.status_code == 422


def test_bad_enum_returns_400(client: TestClient) -> None:
    r = client.post("/analyze-ticket", json={
        "ticket_id": "X",
        "complaint": "test complaint text",
        "language": "fr",  # not a valid enum
    })
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# No crash on valid but unusual input
# ---------------------------------------------------------------------------

def test_no_transactions(client: TestClient) -> None:
    r = client.post("/analyze-ticket", json={
        "ticket_id": "NC-001",
        "complaint": "Something went wrong with my account",
        "transaction_history": [],
    })
    assert r.status_code == 200
    body = r.json()
    assert "case_type" in body
    assert "evidence_verdict" in body


def test_response_schema_complete(client: TestClient) -> None:
    r = client.post("/analyze-ticket", json={
        "ticket_id": "SC-001",
        "complaint": "I paid 500 BDT but the payment failed",
    })
    assert r.status_code == 200
    body = r.json()
    required_keys = {
        "ticket_id", "evidence_verdict", "case_type", "severity", "department",
        "agent_summary", "recommended_next_action", "customer_reply",
        "human_review_required", "confidence", "reason_codes",
    }
    for k in required_keys:
        assert k in body, f"Missing key: {k}"


# ---------------------------------------------------------------------------
# Safety assertions helpers
# ---------------------------------------------------------------------------

_CREDENTIAL_REQUEST_PATTERNS = [
    "please share your otp",
    "please share your pin",
    "please share your password",
    "provide your otp",
    "send your pin",
    "what is your pin",
    "what is your otp",
]

_BARE_REFUND_PROMISES = [
    "we will refund immediately",
    "we will immediately refund",
    "we will reverse immediately",
    "we guarantee a refund",
    "we guarantee refund",
]


def _reply_has_no_credential_request(reply: str) -> bool:
    low = reply.lower()
    return not any(p in low for p in _CREDENTIAL_REQUEST_PATTERNS)


def _reply_has_no_bare_refund_promise(reply: str) -> bool:
    low = reply.lower()
    return not any(p in low for p in _BARE_REFUND_PROMISES)


def _reply_has_otp_reminder(reply: str) -> bool:
    low = reply.lower()
    has_cred_word = (
        "pin" in low or "otp" in low
        or "পিন" in reply or "ওটিপি" in reply
    )
    has_warning_word = (
        "share" in low or "never" in low or "do not" in low or "don't" in low
        or "শেয়ার" in reply or "কখনো" in reply or "না" in reply
    )
    return has_cred_word and has_warning_word


# ---------------------------------------------------------------------------
# Per-case functional assertions
# ---------------------------------------------------------------------------

def _severity_within_one(actual: str, expected: str) -> bool:
    try:
        ai = _SEVERITY_ORDER.index(actual)
        ei = _SEVERITY_ORDER.index(expected)
        return abs(ai - ei) <= 1
    except ValueError:
        return False


def _run_case_assertions(client: TestClient, case: Dict[str, Any]) -> None:
    inp = case["input"]
    exp = case["expected"]

    r = client.post("/analyze-ticket", json=inp)
    assert r.status_code == 200, f"[{case['id']}] Expected 200, got {r.status_code}: {r.text}"
    body = r.json()

    # Echo ticket_id
    assert body["ticket_id"] == inp["ticket_id"], f"[{case['id']}] ticket_id mismatch"

    # Functional equivalence assertions
    assert body["relevant_transaction_id"] == exp["relevant_transaction_id"], (
        f"[{case['id']}] relevant_transaction_id: got {body['relevant_transaction_id']!r}, "
        f"expected {exp['relevant_transaction_id']!r}"
    )

    assert body["evidence_verdict"] == exp["evidence_verdict"], (
        f"[{case['id']}] evidence_verdict: got {body['evidence_verdict']!r}, "
        f"expected {exp['evidence_verdict']!r}"
    )

    assert body["case_type"] == exp["case_type"], (
        f"[{case['id']}] case_type: got {body['case_type']!r}, expected {exp['case_type']!r}"
    )

    assert body["department"] == exp["department"], (
        f"[{case['id']}] department: got {body['department']!r}, expected {exp['department']!r}"
    )

    assert _severity_within_one(body["severity"], exp["severity"]), (
        f"[{case['id']}] severity: got {body['severity']!r}, "
        f"expected within one level of {exp['severity']!r}"
    )

    # Safety assertions on customer_reply
    reply = body["customer_reply"]
    assert _reply_has_no_credential_request(reply), (
        f"[{case['id']}] customer_reply contains a credential request: {reply[:200]}"
    )
    assert _reply_has_no_bare_refund_promise(reply), (
        f"[{case['id']}] customer_reply contains a bare refund promise: {reply[:200]}"
    )
    assert _reply_has_otp_reminder(reply), (
        f"[{case['id']}] customer_reply missing PIN/OTP reminder: {reply[:200]}"
    )


@pytest.mark.parametrize("case", _load_cases(), ids=[c["id"] for c in _load_cases()])
def test_sample_case(client: TestClient, case: Dict[str, Any]) -> None:
    _run_case_assertions(client, case)
