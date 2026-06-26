"""
Safety scrubber — runs ALWAYS on every LLM-drafted or rule-drafted text before
it leaves the service. Enforces bKash's safe-communication policy in both
English and Bangla without relying on the LLM.
"""
from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Credential-request patterns to detect and replace
# ---------------------------------------------------------------------------

_CRED_REQUEST_PATTERNS_EN = [
    r"\bplease\s+(share|provide|send|give)\s+(your\s+)?(otp|pin|password|code)\b",
    r"\b(share|provide|enter|send)\s+(your\s+)?(otp|one.time.password|pin|password)\b",
    r"\bwhat\s+is\s+(your\s+)?(otp|pin|password)\b",
    r"\bask\s+(for\s+)?(your\s+)?(otp|pin|password)\b",
]

_CRED_REQUEST_PATTERNS_BN = [
    r"আপনার\s+(ওটিপি|পিন|পাসওয়ার্ড)\s+(শেয়ার|দিন|বলুন|পাঠান)",
    r"(ওটিপি|পিন|পাসওয়ার্ড)\s+(দিন|বলুন|শেয়ার করুন)",
]

_CRED_SAFE_MSG_EN = (
    "We will never ask for your PIN, OTP, or password. "
    "Please do not share your PIN or OTP with anyone, including bKash staff."
)

_CRED_SAFE_MSG_BN = (
    "আমরা কখনো আপনার পিন, ওটিপি বা পাসওয়ার্ড জিজ্ঞেস করব না। "
    "আপনার পিন বা ওটিপি কারো সাথে শেয়ার করবেন না, bKash কর্মীদের সাথেও নয়।"
)

# ---------------------------------------------------------------------------
# Bare refund/reversal promise patterns
# ---------------------------------------------------------------------------

_REFUND_PROMISE_PATTERNS_EN = [
    r"\bwe\s+will\s+(refund|reverse|return|unblock|credit)\b",
    r"\byour\s+(refund|reversal|money)\s+will\s+be\s+(processed|issued|credited|sent)\b",
    r"\b(refund|reversal|return)\s+will\s+(happen|occur|be\s+done)\s+(immediately|right away|now)\b",
    r"\bimmediately\s+(refund|reverse|credit)\b",
    r"\bguarantee\s+(a\s+)?(refund|reversal|return)\b",
]

_REFUND_PROMISE_PATTERNS_BN = [
    r"টাকা\s+(ফেরত|ফিরিয়ে)\s+(দেওয়া হবে|দেব)",
    r"এখনই\s+(রিফান্ড|টাকা ফেরত)",
    r"গ্যারান্টি\s+(দিচ্ছি|রিফান্ড)",
]

_REFUND_SAFE_MSG_EN = (
    "Any eligible amount will be returned through official bKash channels "
    "after investigation is complete."
)

_REFUND_SAFE_MSG_BN = (
    "তদন্ত সম্পন্ন হওয়ার পর প্রযোজ্য ক্ষেত্রে অফিসিয়াল bKash চ্যানেলের মাধ্যমে "
    "টাকা ফেরত দেওয়া হবে।"
)

# ---------------------------------------------------------------------------
# Third-party redirect patterns
# ---------------------------------------------------------------------------

_THIRD_PARTY_PATTERNS_EN = [
    r"\bcontact\s+(a\s+)?(third.party|external|other\s+agent|unofficial)\b",
    r"\bvisit\s+(a\s+)?(third.party|unofficial)\b",
    r"\bdownload\s+(a\s+)?(third.party|external)\b",
]

_THIRD_PARTY_SAFE_MSG_EN = (
    "Please use official bKash support channels only: "
    "the bKash app, bKash website, or the official helpline 16247."
)

_THIRD_PARTY_SAFE_MSG_BN = (
    "অনুগ্রহ করে শুধুমাত্র অফিসিয়াল bKash সাপোর্ট চ্যানেল ব্যবহার করুন: "
    "bKash অ্যাপ, bKash ওয়েবসাইট, অথবা সরকারি হেল্পলাইন ১৬২৪৭।"
)

# ---------------------------------------------------------------------------
# Mandatory reminder to always include
# ---------------------------------------------------------------------------

_OTP_REMINDER_EN = (
    "Reminder: Never share your PIN or OTP with anyone. "
    "bKash will never call and ask for your PIN or OTP."
)

_OTP_REMINDER_BN = (
    "মনে রাখবেন: কখনো কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না। "
    "bKash কখনো ফোন করে পিন বা ওটিপি চায় না।"
)


def _sub_all(text: str, patterns: list[str], replacement: str, flags: int = re.IGNORECASE) -> str:
    for pat in patterns:
        text = re.sub(pat, replacement, text, flags=flags)
    return text


def scrub_customer_reply(reply: str, language: Optional[str]) -> str:
    """Apply all safety rules to the customer-facing reply."""
    is_bn = language == "bn"

    # 1. Remove credential requests
    reply = _sub_all(reply, _CRED_REQUEST_PATTERNS_EN, _CRED_SAFE_MSG_EN)
    reply = _sub_all(reply, _CRED_REQUEST_PATTERNS_BN, _CRED_SAFE_MSG_BN, flags=0)

    # 2. Replace bare refund promises
    reply = _sub_all(reply, _REFUND_PROMISE_PATTERNS_EN, _REFUND_SAFE_MSG_EN)
    reply = _sub_all(reply, _REFUND_PROMISE_PATTERNS_BN, _REFUND_SAFE_MSG_BN, flags=0)

    # 3. Strip third-party redirects
    reply = _sub_all(reply, _THIRD_PARTY_PATTERNS_EN,
                     _THIRD_PARTY_SAFE_MSG_BN if is_bn else _THIRD_PARTY_SAFE_MSG_EN)

    # 4. Always append the PIN/OTP reminder
    reminder = _OTP_REMINDER_BN if is_bn else _OTP_REMINDER_EN
    if reminder not in reply:
        reply = reply.rstrip() + "\n\n" + reminder

    return reply.strip()


def scrub_next_action(action: str) -> str:
    """Scrub the recommended_next_action field — must not request credentials."""
    action = _sub_all(action, _CRED_REQUEST_PATTERNS_EN, "[Credential request removed — never ask for PIN/OTP]")
    action = _sub_all(action, _THIRD_PARTY_PATTERNS_EN, "[Use official bKash channels only]")
    return action.strip()
