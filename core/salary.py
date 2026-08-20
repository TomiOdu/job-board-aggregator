"""Salary parsing and normalisation.

Sources disagree wildly: Adzuna gives clean annual GBP numbers, Reed gives
bare numbers whose period you have to infer, and free-text fields carry
things like "450 per day" or "60,000 - 70,000 DOE". This module lands
everything on (min, max, currency, period).
"""
from __future__ import annotations

import re

ANNUAL = "annual"
DAILY = "daily"
HOURLY = "hourly"

_NUMBER = r"(\d[\d,]*(?:\.\d+)?)"
_RANGE_RE = re.compile(_NUMBER + r"\s*(?:-|to|and)\s*" + _NUMBER, re.I)
_SINGLE_RE = re.compile(_NUMBER)

_PERIOD_HINTS = [
    (DAILY, r"\bper day\b|\bp\.?d\.?\b|/\s*day\b|\bday rate\b|\bdaily\b"),
    (HOURLY, r"\bper hour\b|\bp\.?h\.?\b|/\s*hour\b|\bhourly\b|\ban hour\b"),
    (ANNUAL, r"\bper annum\b|\bp\.?a\.?\b|/\s*(?:year|annum)\b|\bannual(?:ly)?\b|\bper year\b"),
]

_CURRENCY_HINTS = [
    ("GBP", r"£|\bgbp\b|\bpounds?\b"),
    ("EUR", r"€|\beur\b"),
    ("USD", r"\$|\busd\b"),
]

# Thresholds for inferring an unlabelled figure's period. A UK data role runs
# roughly 30-150 per hour, 300-1000 per day, 30k-200k per year, so the bands
# do not realistically overlap.
_HOURLY_CEILING = 250
_DAILY_CEILING = 3000


def infer_period(amount: float | None) -> str:
    """Guess the period of an unlabelled figure from its magnitude."""
    if amount is None:
        return ""
    if amount < _HOURLY_CEILING:
        return HOURLY
    if amount < _DAILY_CEILING:
        return DAILY
    return ANNUAL


def _to_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def detect_period(text: str) -> str:
    lowered = (text or "").lower()
    for period, pattern in _PERIOD_HINTS:
        if re.search(pattern, lowered):
            return period
    return ""


def detect_currency(text: str) -> str:
    lowered = (text or "").lower()
    for currency, pattern in _CURRENCY_HINTS:
        if re.search(pattern, lowered):
            return currency
    return ""


def parse_salary_text(text: str) -> tuple[float | None, float | None, str, str]:
    """Parse a free-text salary string into (min, max, currency, period)."""
    if not text:
        return None, None, "", ""

    currency = detect_currency(text)
    period = detect_period(text)

    match = _RANGE_RE.search(text)
    if match:
        low, high = _to_float(match.group(1)), _to_float(match.group(2))
    else:
        singles = [_to_float(m.group(1)) for m in _SINGLE_RE.finditer(text)]
        singles = [s for s in singles if s is not None]
        low = high = singles[0] if singles else None

    if not period:
        period = infer_period(low if low is not None else high)

    return low, high, currency, period


def normalise(
    minimum: float | None,
    maximum: float | None,
    currency: str = "",
    period: str = "",
    raw: str = "",
) -> tuple[float | None, float | None, str, str]:
    """Tidy a source's salary fields, filling in currency/period where missing.

    Also swaps min/max if a source has them backwards, and drops zeros
    (several boards use 0 to mean "not disclosed").
    """
    if minimum in (0, 0.0):
        minimum = None
    if maximum in (0, 0.0):
        maximum = None

    if minimum is not None and maximum is not None and minimum > maximum:
        minimum, maximum = maximum, minimum

    if not period:
        period = detect_period(raw) or infer_period(
            minimum if minimum is not None else maximum
        )
    if not currency:
        currency = detect_currency(raw) or ("GBP" if (minimum or maximum) else "")

    return minimum, maximum, currency, period
