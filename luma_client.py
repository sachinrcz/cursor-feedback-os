"""Luma API client for guest lookup from check-in QR codes."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

BASE_DIR = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

LUMA_API_BASE = "https://public-api.luma.com/v1"

_CHECKIN_PATH_RE = re.compile(
    r"^/check-in/(?P<event_id>[^/?#]+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedCheckIn:
    event_id: str
    guest_key: str


@dataclass(frozen=True)
class LumaGuest:
    guest_id: str
    name: str
    email: str | None
    approval_status: str


class LumaError(Exception):
    """Base error for Luma integration."""


class LumaConfigError(LumaError):
    pass


class LumaLookupError(LumaError):
    pass


class LumaNotApprovedError(LumaError):
    pass


class LumaWrongEventError(LumaError):
    pass


def _expected_event_id() -> str:
    event_id = os.getenv("LUMA_EVENT_ID", "").strip()
    if not event_id:
        raise LumaConfigError("LUMA_EVENT_ID is not configured.")
    return event_id


def _api_key() -> str:
    key = os.getenv("LUMA_API_KEY", "").strip()
    if not key:
        raise LumaConfigError("LUMA_API_KEY is not configured.")
    return key


def parse_checkin_url(raw: str) -> ParsedCheckIn:
    """Parse a Luma check-in URL or raw pk value."""
    text = (raw or "").strip()
    if not text:
        raise LumaLookupError("Empty scan value.")

    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        match = _CHECKIN_PATH_RE.match(parsed.path)
        if not match:
            raise LumaLookupError("Not a Luma check-in URL.")
        event_id = match.group("event_id")
        params = parse_qs(parsed.query)
        pk_values = params.get("pk") or params.get("PK")
        if not pk_values or not pk_values[0].strip():
            raise LumaLookupError("Check-in URL is missing the pk parameter.")
        return ParsedCheckIn(event_id=event_id, guest_key=pk_values[0].strip())

    # Allow scanning just the guest/ticket key in some setups.
    return ParsedCheckIn(event_id=_expected_event_id(), guest_key=text)


def lookup_guest(*, event_id: str | None = None, guest_key: str | None = None, email: str | None = None) -> LumaGuest:
    """Look up a guest by check-in key or email."""
    expected_event = _expected_event_id()
    lookup_id = (guest_key or email or "").strip()
    if not lookup_id:
        raise LumaLookupError("Guest key or email is required.")

    resolved_event = (event_id or expected_event).strip()
    if resolved_event != expected_event:
        raise LumaWrongEventError(
            f"This ticket is for a different event ({resolved_event}). "
            f"Expected {expected_event}."
        )

    response = requests.get(
        f"{LUMA_API_BASE}/events/guests/get",
        params={"event_id": resolved_event, "id": lookup_id},
        headers={"x-luma-api-key": _api_key(), "Accept": "application/json"},
        timeout=15,
    )
    if response.status_code == 404:
        raise LumaLookupError("Guest not found on Luma.")
    if response.status_code >= 400:
        raise LumaLookupError(f"Luma API error ({response.status_code}).")

    data = response.json()
    approval_status = (data.get("approval_status") or "").strip()
    if approval_status != "approved":
        raise LumaNotApprovedError(
            f"Guest is not approved (status: {approval_status or 'unknown'})."
        )

    guest_id = (data.get("id") or "").strip()
    if not guest_id:
        raise LumaLookupError("Luma response did not include a guest id.")

    user = data.get("user") or {}
    name = (
        (data.get("name") or "").strip()
        or (user.get("name") or "").strip()
        or (user.get("first_name") or "").strip()
        or "Guest"
    )
    email_value = (data.get("email") or user.get("email") or "").strip() or None

    return LumaGuest(
        guest_id=guest_id,
        name=name,
        email=email_value,
        approval_status=approval_status,
    )


def lookup_from_scan(scanned_url: str) -> LumaGuest:
    parsed = parse_checkin_url(scanned_url)
    return lookup_guest(event_id=parsed.event_id, guest_key=parsed.guest_key)
