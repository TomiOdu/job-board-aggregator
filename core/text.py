"""Small text helpers shared across adapters."""
from __future__ import annotations

import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(value: str | None) -> str:
    """Strip HTML tags, unescape entities and collapse whitespace."""
    if not value:
        return ""
    text = _TAG_RE.sub(" ", str(value))
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def truncate(value: str, limit: int) -> str:
    """Cut to `limit` chars on a word boundary, adding an ellipsis."""
    if len(value) <= limit:
        return value
    cut = value[:limit].rsplit(" ", 1)[0]
    return f"{cut}..."
