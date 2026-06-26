import re
from datetime import datetime


BD_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def normalize(text: str | None) -> str:
    if not text:
        return ""
    return text.translate(BD_DIGITS).casefold()


def contains_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)


def extract_amounts(text: str) -> list[float]:
    text = normalize(text).replace(",", "")
    amounts: list[float] = []
    for raw in re.findall(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)", text):
        value = float(raw)
        if 10 <= value <= 1_000_000:
            amounts.append(value)
    return amounts


def phone_fragments(text: str) -> set[str]:
    normalized = normalize(text)
    fragments = set()
    for match in re.findall(r"(?:\+?88)?01[3-9]\d{8}", normalized):
        compact = re.sub(r"\D", "", match)
        fragments.add(compact[-11:])
    return fragments


def minutes_between(left: str | None, right: str | None) -> float | None:
    try:
        if not left or not right:
            return None
        left_dt = datetime.fromisoformat(left.replace("Z", "+00:00"))
        right_dt = datetime.fromisoformat(right.replace("Z", "+00:00"))
        return abs((left_dt - right_dt).total_seconds()) / 60
    except ValueError:
        return None


def money(value: float | int | None) -> str:
    if value is None:
        return "the reported amount"
    if float(value).is_integer():
        return f"{int(value)} BDT"
    return f"{value} BDT"
