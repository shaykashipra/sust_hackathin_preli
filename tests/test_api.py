from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_wrong_transfer_with_matching_evidence():
    response = client.post(
        "/analyze-ticket",
        json={
            "ticket_id": "TKT-001",
            "complaint": "I sent 5000 taka to a wrong number around 2pm today. Please help.",
            "language": "en",
            "transaction_history": [
                {
                    "transaction_id": "TXN-9101",
                    "timestamp": "2026-04-14T14:08:22Z",
                    "type": "transfer",
                    "amount": 5000,
                    "counterparty": "+8801719876543",
                    "status": "completed",
                }
            ],
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert body["relevant_transaction_id"] == "TXN-9101"
    assert body["evidence_verdict"] == "consistent"
    assert body["case_type"] == "wrong_transfer"
    assert body["department"] == "dispute_resolution"
    assert body["human_review_required"] is True
    assert "Please do not share your PIN or OTP" in body["customer_reply"]


def test_ambiguous_transfer_does_not_guess():
    response = client.post(
        "/analyze-ticket",
        json={
            "ticket_id": "TKT-008",
            "complaint": "I sent 1000 to my brother yesterday but he says he did not get it.",
            "transaction_history": [
                {
                    "transaction_id": "TXN-9801",
                    "timestamp": "2026-04-13T11:20:00Z",
                    "type": "transfer",
                    "amount": 1000,
                    "counterparty": "+8801712001122",
                    "status": "completed",
                },
                {
                    "transaction_id": "TXN-9802",
                    "timestamp": "2026-04-13T19:45:00Z",
                    "type": "transfer",
                    "amount": 1000,
                    "counterparty": "+8801812334455",
                    "status": "completed",
                },
            ],
        },
    )
    body = response.json()
    assert body["relevant_transaction_id"] is None
    assert body["evidence_verdict"] == "insufficient_data"
    assert "ambiguous_match" in body["reason_codes"]


def test_phishing_is_critical_and_safe():
    response = client.post(
        "/analyze-ticket",
        json={
            "ticket_id": "TKT-005",
            "complaint": "Someone called me and asked for my OTP and PIN.",
            "language": "en",
            "transaction_history": [],
        },
    )
    body = response.json()
    assert body["case_type"] == "phishing_or_social_engineering"
    assert body["severity"] == "critical"
    assert body["department"] == "fraud_risk"
    assert body["human_review_required"] is True
    assert "never ask" in body["customer_reply"].casefold()


def test_duplicate_payment_picks_second_payment():
    response = client.post(
        "/analyze-ticket",
        json={
            "ticket_id": "TKT-010",
            "complaint": "I paid my electricity bill 850 taka but it deducted twice.",
            "transaction_history": [
                {
                    "transaction_id": "TXN-10001",
                    "timestamp": "2026-04-14T08:15:30Z",
                    "type": "payment",
                    "amount": 850,
                    "counterparty": "BILLER-DESCO",
                    "status": "completed",
                },
                {
                    "transaction_id": "TXN-10002",
                    "timestamp": "2026-04-14T08:15:42Z",
                    "type": "payment",
                    "amount": 850,
                    "counterparty": "BILLER-DESCO",
                    "status": "completed",
                },
            ],
        },
    )
    body = response.json()
    assert body["relevant_transaction_id"] == "TXN-10002"
    assert body["evidence_verdict"] == "consistent"
    assert body["case_type"] == "duplicate_payment"


def test_malformed_input_returns_controlled_error():
    response = client.post("/analyze-ticket", json={"ticket_id": "TKT-BAD"})
    assert response.status_code == 400
    assert response.json() == {"error": "invalid or missing request fields"}
