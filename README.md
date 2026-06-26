# QueueStorm Investigator

Evidence-grounded FastAPI service for the SUST CSE Carnival 2026 preliminary AI/API challenge.

The service exposes:

- `GET /health`
- `POST /analyze-ticket`

It is intentionally rule-based for the preliminary round: fast, reproducible, no API key dependency, and no hidden cost or quota failure during judging.

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

Analyze a sample ticket:

```bash
curl -X POST http://localhost:8000/analyze-ticket ^
  -H "Content-Type: application/json" ^
  --data @sample_request.json
```

## Docker

```bash
docker build -t queuestorm-investigator .
docker run -p 8000:8000 queuestorm-investigator
```

## Approach

The code is split by responsibility to reduce merge conflicts during the short contest window:

- `app/models.py`: request and response schema
- `app/enums.py`: exact output enum values
- `app/classifier.py`: case type detection
- `app/evidence.py`: transaction matching and evidence verdicts
- `app/replies.py`: routing, severity, review decision, and safe response templates
- `app/analyzer.py`: orchestration
- `app/main.py`: HTTP API and controlled error handling

The investigator does not simply classify complaint text. It checks transaction evidence, picks a relevant transaction only when there is enough support, marks contradictions as `inconsistent`, and returns `insufficient_data` when the match is ambiguous.

## Safety Logic

Customer-facing replies are generated from fixed safe templates. The complaint text is never allowed to instruct the system to ask for secrets, promise refunds, or bypass policy.

Guardrails:

- Never asks for PIN, OTP, password, full card number, or secret credentials.
- Never promises a refund, reversal, recovery, or account unblock.
- Uses "any eligible amount will be returned through official channels" for payment/reversal cases.
- Sends phishing and credential-sharing reports to `fraud_risk`.
- Requires human review for wrong transfers, duplicate payments, suspicious cases, contradictory evidence, and critical severity cases.

## MODELS

No external AI model is used in this implementation.

Reason: the judging score rewards schema correctness, evidence reasoning, safety, reliability, and speed. A deterministic service avoids API-key handling risk, external latency, rate limits, and quota failures.

## Testing

```bash
pytest
```

The tests cover:

- health endpoint
- wrong-transfer evidence match
- ambiguous transfer handling
- phishing safety
- duplicate payment detection
- controlled malformed-input error

## Sample Output

Generate `sample_output.json` from the included public-style request:

```bash
python scripts/generate_sample_output.py
```

## Assumptions

- Hidden tests may include Bangla, Banglish, malformed input, ambiguous evidence, and safety-sensitive complaint text.
- Transaction history snippets are short, so transparent deterministic ranking is faster and easier to verify than vector search.
- If multiple transactions plausibly match and the complaint lacks a disambiguating detail, the safer answer is `insufficient_data`.

## Known Limitations

- Bangla/Banglish handling is keyword-based, not a full language model.
- Time phrases such as "yesterday morning" are handled indirectly through transaction ranking, not full natural-language time parsing.
- The service does not integrate with real payment systems and cannot authorize financial actions.
