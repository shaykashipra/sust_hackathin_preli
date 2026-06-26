"""
Transaction scoring and evidence verdict — all deterministic rules, no LLM.
Groq signals (claimed_amount, time_hint, counterparty_hint, intent) are used
as inputs but this module decides everything.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from app.schemas import Transaction, TransactionStatus, TransactionType

MATCH_THRESHOLD = 0.45
RUNNERUP_GAP = 0.15


# ---------------------------------------------------------------------------
# Sub-scorers (each returns 0.0–1.0)
# ---------------------------------------------------------------------------

def _parse_ts(ts: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _amount_score(txn_amount: float, claimed: Optional[float]) -> float:
    if claimed is None:
        return 0.3
    diff = abs(txn_amount - claimed)
    if diff == 0:
        return 1.0
    if claimed > 0 and diff / claimed <= 0.05:
        return 0.7
    if claimed > 0 and diff / claimed <= 0.20:
        return 0.4
    return 0.0


def _time_score(txn_ts: Optional[datetime], time_hint: Optional[str]) -> float:
    if not time_hint or not txn_ts:
        return 0.3
    hint_dt = _parse_ts(time_hint)
    if not hint_dt:
        return 0.3
    delta_h = abs((txn_ts - hint_dt).total_seconds()) / 3600
    if delta_h <= 1:
        return 1.0
    if delta_h <= 6:
        return 0.7
    if delta_h <= 24:
        return 0.4
    if delta_h <= 72:
        return 0.2
    return 0.05


def _counterparty_score(txn_cp: str, hint: Optional[str]) -> float:
    if not hint:
        return 0.3
    t = txn_cp.replace("-", "").replace(" ", "").lower()
    h = hint.replace("-", "").replace(" ", "").lower()
    if t == h:
        return 1.0
    if t in h or h in t:
        return 0.75
    if len(h) >= 4 and (t.endswith(h[-4:]) or h.endswith(t[-4:])):
        return 0.5
    return 0.0


_INTENT_TYPES: dict[str, list[TransactionType]] = {
    "wrong_transfer": [TransactionType.transfer],
    "payment_failed": [TransactionType.payment],
    "refund_request": [TransactionType.payment, TransactionType.transfer],
    "duplicate_payment": [TransactionType.payment],
    "merchant_settlement_delay": [TransactionType.settlement, TransactionType.payment],
    "agent_cash_in_issue": [TransactionType.cash_in],
}


def _type_score(txn_type: TransactionType, intent: Optional[str]) -> float:
    if not intent or intent not in _INTENT_TYPES:
        return 0.3
    return 1.0 if txn_type in _INTENT_TYPES[intent] else 0.0


def score_transaction(
    txn: Transaction,
    claimed_amount: Optional[float],
    time_hint: Optional[str],
    counterparty_hint: Optional[str],
    intent: Optional[str],
) -> float:
    txn_ts = _parse_ts(txn.timestamp)
    return round(
        _amount_score(txn.amount, claimed_amount) * 0.35
        + _time_score(txn_ts, time_hint) * 0.25
        + _counterparty_score(txn.counterparty, counterparty_hint) * 0.25
        + _type_score(txn.type, intent) * 0.15,
        4,
    )


# ---------------------------------------------------------------------------
# Top-level match selection
# ---------------------------------------------------------------------------

def find_best_transaction(
    transactions: List[Transaction],
    claimed_amount: Optional[float],
    time_hint: Optional[str],
    counterparty_hint: Optional[str],
    intent: Optional[str],
    is_duplicate: bool = False,
) -> Optional[str]:
    if not transactions:
        return None

    if is_duplicate:
        return _find_duplicate_second(transactions, claimed_amount, time_hint, counterparty_hint)

    scored = sorted(
        [(t, score_transaction(t, claimed_amount, time_hint, counterparty_hint, intent))
         for t in transactions],
        key=lambda x: x[1],
        reverse=True,
    )
    best_txn, best_score = scored[0]
    if best_score < MATCH_THRESHOLD:
        return None

    # Only apply runner-up gap when the runner-up also clears the threshold
    if len(scored) > 1:
        runner_score = scored[1][1]
        if runner_score >= MATCH_THRESHOLD and (best_score - runner_score) < RUNNERUP_GAP:
            return None

    return best_txn.transaction_id


def _find_duplicate_second(
    transactions: List[Transaction],
    claimed_amount: Optional[float],
    time_hint: Optional[str],
    counterparty_hint: Optional[str],
) -> Optional[str]:
    """Find the second transaction in a near-identical pair."""
    candidates = [
        t for t in transactions
        if t.type == TransactionType.payment
    ]
    if not candidates:
        candidates = transactions

    # Sort by timestamp to find temporal pairs
    def sort_key(t: Transaction) -> datetime:
        dt = _parse_ts(t.timestamp)
        return dt if dt else datetime(1970, 1, 1, tzinfo=timezone.utc)

    candidates.sort(key=sort_key)

    best_pair: Optional[tuple[Transaction, Transaction]] = None
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            t1, t2 = candidates[i], candidates[j]
            if (
                abs(t1.amount - t2.amount) < 1.0
                and t1.counterparty == t2.counterparty
                and t1.type == t2.type
            ):
                ts1, ts2 = _parse_ts(t1.timestamp), _parse_ts(t2.timestamp)
                if ts1 and ts2:
                    best_pair = (t1, t2)
                    break
        if best_pair:
            break

    if best_pair:
        ts1 = _parse_ts(best_pair[0].timestamp)
        ts2 = _parse_ts(best_pair[1].timestamp)
        if ts1 and ts2:
            return (best_pair[1] if ts2 >= ts1 else best_pair[0]).transaction_id

    # Fallback: score-based
    scored = sorted(
        [(t, score_transaction(t, claimed_amount, time_hint, counterparty_hint, "duplicate_payment"))
         for t in transactions],
        key=lambda x: x[1],
        reverse=True,
    )
    if scored and scored[0][1] >= MATCH_THRESHOLD:
        return scored[0][0].transaction_id
    return None


# ---------------------------------------------------------------------------
# Evidence verdict
# ---------------------------------------------------------------------------

def determine_verdict(
    relevant_txn_id: Optional[str],
    transactions: List[Transaction],
    intent: Optional[str],
    counterparty_hint: Optional[str],
) -> str:
    if not relevant_txn_id:
        return "insufficient_data"

    txn = next((t for t in transactions if t.transaction_id == relevant_txn_id), None)
    if not txn:
        return "insufficient_data"

    # Inconsistency: "wrong transfer" but this counterparty is a repeat recipient
    if intent == "wrong_transfer" and counterparty_hint:
        cp_norm = counterparty_hint.replace("-", "").replace(" ", "").lower()
        prior_completed = sum(
            1 for t in transactions
            if t.transaction_id != relevant_txn_id
            and t.type == TransactionType.transfer
            and t.counterparty.replace("-", "").replace(" ", "").lower() == cp_norm
            and t.status == TransactionStatus.completed
        )
        if prior_completed >= 2:
            return "inconsistent"

    # Consistency checks aligned with each intent
    if intent == "payment_failed" and txn.status == TransactionStatus.failed:
        return "consistent"
    if intent == "wrong_transfer" and txn.status == TransactionStatus.completed:
        return "consistent"
    if intent in ("refund_request", "duplicate_payment") and txn.status in (
        TransactionStatus.completed, TransactionStatus.pending
    ):
        return "consistent"
    if intent == "merchant_settlement_delay" and txn.status in (
        TransactionStatus.pending, TransactionStatus.completed
    ):
        return "consistent"
    if intent == "agent_cash_in_issue" and txn.status in (
        TransactionStatus.failed, TransactionStatus.pending
    ):
        return "consistent"

    return "insufficient_data"
