"""Shared limits and validation for ticket submissions."""
from __future__ import annotations

import re

MAX_FROM_NAME_LEN = 50
MAX_QUESTION_LEN = 500

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002700-\U000027BF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U0000200D"
    "\U0000FE0F"
    "]+",
    flags=re.UNICODE,
)


def contains_emoji(text: str) -> bool:
    return bool(_EMOJI_RE.search(text))


def validate_submission(from_name: str | None, question: str | None) -> str | None:
    """Return an error message, or None if valid."""
    name = (from_name or "").strip()
    body = (question or "").strip()

    if not name:
        return "Please enter your name."
    if len(name) > MAX_FROM_NAME_LEN:
        return f"Name must be {MAX_FROM_NAME_LEN} characters or less."
    if contains_emoji(name):
        return "Name cannot contain emoji."

    if not body:
        return "Please enter a question or comment."
    if len(body) > MAX_QUESTION_LEN:
        return f"Message must be {MAX_QUESTION_LEN} characters or less."
    if contains_emoji(body):
        return "Message cannot contain emoji."

    return None
