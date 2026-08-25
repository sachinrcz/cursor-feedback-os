"""Luma API client for guest lookup from check-in QR codes."""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)

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


def _log_responses_enabled() -> bool:
    return os.getenv("LUMA_LOG_RESPONSES", "true").lower() in ("1", "true", "yes")


def _redact_lookup_id(lookup_id: str) -> str:
    if "@" in lookup_id:
        local, _, domain = lookup_id.partition("@")
        if len(local) <= 2:
            return f"***@{domain}"
        return f"{local[:2]}***@{domain}"
    if len(lookup_id) <= 8:
        return lookup_id
    return f"{lookup_id[:4]}...{lookup_id[-4:]}"


def _response_body_for_log(response: requests.Response) -> str:
    try:
        return json.dumps(response.json(), indent=2, default=str)
    except ValueError:
        text = (response.text or "").strip()
        return text[:4000] if text else "<empty body>"


def _luma_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            for key in ("message", "error", "detail", "reason"):
                value = data.get(key)
                if value:
                    return str(value)
            return json.dumps(data, default=str)[:500]
    except ValueError:
        pass
    text = (response.text or "").strip()
    return text[:500] if text else "No response body."


def _unwrap_guest_payload(data: dict) -> dict:
    """Support flat and legacy nested `{ guest: {...} }` shapes."""
    guest = data.get("guest")
    if isinstance(guest, dict):
        merged = dict(guest)
        for key, value in data.items():
            if key != "guest" and key not in merged:
                merged[key] = value
        return merged
    return data


def _pick_text(*values: object) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _extract_guest_name(data: dict) -> str:
    """Resolve a display name from Luma guest payload shapes."""
    user = data.get("user") if isinstance(data.get("user"), dict) else {}

    first = _pick_text(
        data.get("first_name"),
        user.get("first_name"),
        data.get("user_first_name"),
    )
    last = _pick_text(
        data.get("last_name"),
        user.get("last_name"),
        data.get("user_last_name"),
    )
    combined = " ".join(part for part in (first, last) if part).strip()

    return (
        _pick_text(
            data.get("name"),
            data.get("user_name"),
            user.get("name"),
            combined,
            first,
        )
        or "Guest"
    )


def _extract_guest_email(data: dict) -> str | None:
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    return (
        _pick_text(data.get("email"), data.get("user_email"), user.get("email"))
        or None
    )


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

    lookup_label = _redact_lookup_id(lookup_id)
    logger.info(
        "Luma guest lookup request: event_id=%s lookup_id=%s",
        resolved_event,
        lookup_label,
    )

    response = requests.get(
        f"{LUMA_API_BASE}/events/guests/get",
        params={"event_id": resolved_event, "id": lookup_id},
        headers={"x-luma-api-key": _api_key(), "Accept": "application/json"},
        timeout=15,
    )

    if _log_responses_enabled():
        logger.info(
            "Luma guest lookup response: status=%s event_id=%s lookup_id=%s body=%s",
            response.status_code,
            resolved_event,
            lookup_label,
            _response_body_for_log(response),
        )

    if response.status_code == 404:
        detail = _luma_error_message(response)
        logger.warning(
            "Luma guest not found: event_id=%s lookup_id=%s detail=%s",
            resolved_event,
            lookup_label,
            detail,
        )
        raise LumaLookupError(f"Guest not found on Luma. {detail}")
    if response.status_code >= 400:
        detail = _luma_error_message(response)
        logger.error(
            "Luma API error: status=%s event_id=%s lookup_id=%s detail=%s body=%s",
            response.status_code,
            resolved_event,
            lookup_label,
            detail,
            _response_body_for_log(response),
        )
        raise LumaLookupError(f"Luma API error ({response.status_code}): {detail}")

    try:
        raw = response.json()
    except ValueError as exc:
        logger.error(
            "Luma returned non-JSON: event_id=%s lookup_id=%s body=%s",
            resolved_event,
            lookup_label,
            (response.text or "")[:4000],
        )
        raise LumaLookupError("Luma returned an invalid JSON response.") from exc

    data = _unwrap_guest_payload(raw)
    approval_status = (data.get("approval_status") or "").strip()
    if approval_status != "approved":
        logger.warning(
            "Luma guest not approved: event_id=%s lookup_id=%s guest_id=%s status=%s",
            resolved_event,
            lookup_label,
            data.get("id"),
            approval_status or "unknown",
        )
        raise LumaNotApprovedError(
            f"Guest is not approved (status: {approval_status or 'unknown'})."
        )

    guest_id = (data.get("id") or "").strip()
    if not guest_id:
        logger.error(
            "Luma response missing guest id: event_id=%s lookup_id=%s body=%s",
            resolved_event,
            lookup_label,
            json.dumps(raw, default=str)[:4000],
        )
        raise LumaLookupError("Luma response did not include a guest id.")

    name = _extract_guest_name(data)
    email_value = _extract_guest_email(data)

    logger.info(
        "Luma guest lookup ok: event_id=%s lookup_id=%s guest_id=%s name=%r status=%s",
        resolved_event,
        lookup_label,
        guest_id,
        name,
        approval_status,
    )

    return LumaGuest(
        guest_id=guest_id,
        name=name,
        email=email_value,
        approval_status=approval_status,
    )


def lookup_from_scan(scanned_url: str) -> LumaGuest:
    parsed = parse_checkin_url(scanned_url)
    return lookup_guest(event_id=parsed.event_id, guest_key=parsed.guest_key)
