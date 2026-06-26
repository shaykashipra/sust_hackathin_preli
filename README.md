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

## Render

This repository includes `render.yaml`.

Manual Render settings:

```text
Build Command: pip install -r requirements.txt
Start Command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
Health Check Path: /health
```

## Approach

The code is split by responsibility to reduce merge conflicts during the short contest window:

- `app/models.py`: request and response schema
- `app/enums.py`: exact output enum values
- `app/classifier.py`: case type detection
- `app/evidence.py`: transaction matching and evidence verdicts
- `app/replies.py`: routing, severity, review decision, and safe response templates
- `app/analyzer.py`: orchestration
- `app/safety/`: final safety firewall, prompt-injection detection, decision consistency checks
- `app/main.py`: HTTP API and controlled error handling

The investigator does not simply classify complaint text. It checks transaction evidence, picks a relevant transaction only when there is enough support, marks contradictions as `inconsistent`, and returns `insufficient_data` when the match is ambiguous.

## Safety Logic

Customer-facing replies are generated from fixed safe templates. The complaint text is never allowed to instruct the system to ask for secrets, promise refunds, or bypass policy.

After the investigator creates a response, a final safety firewall runs before JSON is returned:

1. Prompt-injection detector ignores instructions such as "ignore previous instructions", "say refund approved", or "ask for OTP".
2. Decision consistency checker corrects impossible combinations, such as phishing routed away from `fraud_risk`.
3. Severity and human-review validator raises risky cases to review.
4. Output validator blocks credential requests, unauthorized refund/reversal promises, and suspicious third-party contact instructions.
5. Unsafe drafts are rewritten to a safe official-channel response.

Guardrails:

- Never asks for PIN, OTP, password, full card number, or secret credentials.
- Never promises a refund, reversal, recovery, or account unblock.
- Uses "any eligible amount will be returned through official channels" for payment/reversal cases.
- Sends phishing and credential-sharing reports to `fraud_risk`.
- Requires human review for wrong transfers, duplicate payments, suspicious cases, contradictory evidence, and critical severity cases.

The API response schema stays exactly as required. Internal safety events are represented only through compact `reason_codes`, such as `prompt_injection_ignored` or `safety_rewritten`, so the judge still receives valid JSON.

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
- prompt-injection resistance
- unsafe promise and third-party rewrite checks
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
