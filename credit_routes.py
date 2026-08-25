"""Flask blueprint for the credit QR desk."""
from __future__ import annotations

import logging
import os
from functools import wraps
from typing import Callable

from flask import Blueprint, jsonify, render_template, request, session

from credit_store import (
    claim_for_guest,
    get_claimed_url,
    import_urls,
    mark_printed,
    pool_status,
)
from luma_client import (
    LumaConfigError,
    LumaError,
    LumaLookupError,
    LumaNotApprovedError,
    LumaWrongEventError,
    lookup_from_scan,
    lookup_guest,
)
from ticket_format import format_credit_ticket

logger = logging.getLogger(__name__)

SESSION_KEY = "credits_unlocked"


def _credits_pin() -> str:
    return os.getenv("CREDITS_PIN", "").strip()


def _is_unlocked() -> bool:
    pin = _credits_pin()
    if not pin:
        return True
    return bool(session.get(SESSION_KEY))


def _require_unlock(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not _is_unlocked():
            return jsonify({"success": False, "error": "PIN required."}), 401
        return f(*args, **kwargs)

    return wrapped


def create_credit_blueprint(get_printer: Callable):
    bp = Blueprint("credits", __name__)

    @bp.route("/credits")
    def credits_page():
        return render_template("credits.html", pin_required=bool(_credits_pin()))

    @bp.route("/credits/unlock", methods=["POST"])
    def unlock():
        pin = _credits_pin()
        if not pin:
            session[SESSION_KEY] = True
            return jsonify({"success": True, "message": "Desk unlocked."})

        data = request.get_json(silent=True) or {}
        supplied = (data.get("pin") or "").strip()
        if supplied != pin:
            return jsonify({"success": False, "error": "Incorrect PIN."}), 403

        session[SESSION_KEY] = True
        session.permanent = True
        return jsonify({"success": True, "message": "Desk unlocked."})

    @bp.route("/credits/status", methods=["GET"])
    @_require_unlock
    def status():
        stats = pool_status()
        return jsonify(
            {
                "success": True,
                "available": stats.available,
                "claimed": stats.claimed,
                "void": stats.void,
                "total": stats.total,
                "recent": stats.recent,
            }
        )

    @bp.route("/credits/import", methods=["POST"])
    @_require_unlock
    def import_links():
        data = request.get_json(silent=True) or {}
        urls = data.get("urls")
        if isinstance(urls, str):
            lines = urls.splitlines()
        elif isinstance(urls, list):
            lines = [str(line) for line in urls]
        else:
            return jsonify({"success": False, "error": "Provide urls as a string or list."}), 400

        result = import_urls(lines)
        stats = pool_status()
        return jsonify(
            {
                "success": True,
                "added": result["added"],
                "skipped": result["skipped"],
                "available": stats.available,
                "total": stats.total,
            }
        )

    def _print_claim(claim, *, reprint: bool) -> tuple[dict, int]:
        printer = get_printer()
        if printer is None:
            return {"success": False, "error": "Printer not available."}, 500

        printed = format_credit_ticket(printer, claim.guest_name, claim.url)
        if not printed:
            return {"success": False, "error": "Failed to print credit slip."}, 500

        mark_printed(claim.link_id)
        action = "reprinted" if reprint or claim.already_claimed else "issued"
        logger.info(
            "Credit %s for guest %s (link id %s)",
            action,
            claim.guest_name,
            claim.link_id,
        )
        stats = pool_status()
        return {
            "success": True,
            "action": action,
            "guest_name": claim.guest_name,
            "guest_email": claim.guest_email,
            "already_claimed": claim.already_claimed,
            "available": stats.available,
            "claimed": stats.claimed,
        }, 200

    @bp.route("/credits/issue", methods=["POST"])
    @_require_unlock
    def issue():
        data = request.get_json(silent=True) or {}
        scanned_url = (data.get("scanned_url") or "").strip()
        email = (data.get("email") or "").strip()

        try:
            if scanned_url:
                guest = lookup_from_scan(scanned_url)
            elif email:
                guest = lookup_guest(email=email)
            else:
                return jsonify(
                    {"success": False, "error": "Scan a Luma ticket or enter an email."}
                ), 400

            claim = claim_for_guest(guest.guest_id, guest.name, guest.email)
            body, code = _print_claim(claim, reprint=claim.already_claimed)
            return jsonify(body), code
        except LumaConfigError as exc:
            logger.error("Credit issue config error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500
        except LumaWrongEventError as exc:
            logger.warning("Credit issue wrong event: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 400
        except LumaNotApprovedError as exc:
            logger.warning("Credit issue guest not approved: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 403
        except LumaLookupError as exc:
            logger.warning("Credit issue Luma lookup failed: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 404
        except LumaError as exc:
            logger.warning("Credit issue Luma error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"success": False, "error": str(exc)}), 409
        except Exception as exc:
            logger.exception("Credit issue failed")
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/credits/reprint", methods=["POST"])
    @_require_unlock
    def reprint():
        data = request.get_json(silent=True) or {}
        guest_id = (data.get("guest_id") or "").strip()
        if not guest_id:
            return jsonify({"success": False, "error": "guest_id is required."}), 400

        claim = get_claimed_url(guest_id)
        if claim is None:
            return jsonify(
                {"success": False, "error": "No credit has been issued for this guest."}
            ), 404

        body, code = _print_claim(claim, reprint=True)
        return jsonify(body), code

    return bp
