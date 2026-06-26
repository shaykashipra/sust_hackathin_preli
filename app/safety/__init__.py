"""Safety helpers and package exports for QueueStorm Investigator.

The merged codebase has two safety layers:
- pipeline text scrubbers, used before the response object is built
- final firewall validators, used after the response object is built

This module exports the scrubbers so older imports like
`from app.safety import scrub_customer_reply` keep working now that
`app.safety` is a package.
"""

from __future__ import annotations

import re
from typing import Optional


CREDENTIAL_REQUEST_PATTERNS = [
    r"\bplease\s+(share|provide|send|give|tell|enter|submit)\s+(your\s+)?(otp|o\s*t\s*p|pin|password|passcode|code|cvv)\b",
    r"\b(share|provide|send|give|tell|enter|submit)\s+(your\s+)?(otp|o\s*t\s*p|pin|password|passcode|code|cvv)\b",
    r"\bwhat\s+is\s+(your\s+)?(otp|pin|password|passcode|code)\b",
    r"\bask\s+(for\s+)?(your\s+)?(otp|pin|password|passcode|code)\b",
]

REFUND_PROMISE_PATTERNS = [
    r"\bwe\s+will\s+(refund|reverse|return|unblock|credit)\b",
    r"\byour\s+(refund|reversal|money)\s+will\s+be\s+(processed|issued|credited|sent|returned)\b",
    r"\b(refund|reversal)\s+(is\s+)?(approved|confirmed|guaranteed)\b",
    r"\bmoney\s+will\s+be\s+returned\b",
    r"\brefund\s+dibo\b",
    r"\btaka\s+ferot\s+(diye\s+)?dibo\b",
    r"\bfund\s+(diye\s+)?dibo\b",
]

THIRD_PARTY_PATTERNS = [
    r"\bwhatsapp\b",
    r"\bfacebook\b",
    r"\btelegram\b",
    r"\bimo\b",
    r"\bcall\s+this\s+number\b",
    r"\bmessage\s+this\b",
    r"\bcontact\s+this\s+agent\b",
    r"\bcontact\s+the\s+caller\b",
    r"(?:\+?88)?01[3-9]\d{8}",
]

SAFE_CREDENTIAL_MSG = (
    "We will never ask for your PIN, OTP, password, or full card number. "
    "Please do not share these with anyone."
)

SAFE_REFUND_MSG = (
    "Any eligible amount will be returned through official channels after review."
)

SAFE_CHANNEL_MSG = (
    "Please use official support channels only, such as the app, website, or official helpline."
)

OTP_REMINDER = (
    "Reminder: Never share your PIN, OTP, password, or full card number with anyone."
)


def _sub_all(text: str, patterns: list[str], replacement: str) -> str:
    for pattern in patterns:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def scrub_customer_reply(reply: str, language: Optional[str] = None) -> str:
    """Remove unsafe customer-facing instructions from a drafted reply."""
    reply = _sub_all(reply or "", CREDENTIAL_REQUEST_PATTERNS, SAFE_CREDENTIAL_MSG)
    reply = _sub_all(reply, REFUND_PROMISE_PATTERNS, SAFE_REFUND_MSG)
    reply = _sub_all(reply, THIRD_PARTY_PATTERNS, SAFE_CHANNEL_MSG)

    if OTP_REMINDER.casefold() not in reply.casefold():
        reply = reply.rstrip() + "\n\n" + OTP_REMINDER
    return reply.strip()


def scrub_next_action(action: str) -> str:
    """Remove unsafe operational instructions before returning next action."""
    action = _sub_all(action or "", CREDENTIAL_REQUEST_PATTERNS, "Never ask for PIN, OTP, password, or secret credentials.")
    action = _sub_all(action, REFUND_PROMISE_PATTERNS, "Review eligibility through the official workflow before any financial action.")
    action = _sub_all(action, THIRD_PARTY_PATTERNS, "Use official support channels only.")
    return action.strip()
