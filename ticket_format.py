"""Shared thermal ticket layout for app.py and backend/api.py."""
from __future__ import annotations

import logging
import os
import textwrap
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DEFAULT_LOGO = STATIC_DIR / "cursor-logo.png"

TICKET_TITLE = os.getenv("TICKET_TITLE", "Cafe Cursor Bali")
TICKET_LINE_WIDTH = int(os.getenv("TICKET_LINE_WIDTH", "32"))
TICKET_LOGO_MAX_WIDTH = int(os.getenv("TICKET_LOGO_MAX_WIDTH", "280"))
TICKET_LOGO_THRESHOLD = int(os.getenv("TICKET_LOGO_THRESHOLD", "160"))


def _rule(width: int = TICKET_LINE_WIDTH) -> str:
    return "=" * width + "\n"


def resolve_logo_path() -> Path | None:
    """Logo PNG from TICKET_LOGO_PATH or static/cursor-logo.png."""
    env_path = os.getenv("TICKET_LOGO_PATH")
    if env_path:
        path = Path(env_path)
        return path if path.is_file() else None
    if DEFAULT_LOGO.is_file():
        return DEFAULT_LOGO
    legacy = STATIC_DIR / "cursor_logo.png"
    return legacy if legacy.is_file() else None


def prepare_logo_image(path: Path):
    """Resize and darken logo for 58mm thermal printers.

    cursor-logo.png is light gray on transparency (not black ink). Invert luminance
    and use alpha so those areas print solid black on thermal paper.
    """
    from PIL import Image, ImageEnhance, ImageOps

    img = Image.open(path).convert("RGBA")
    gray = img.convert("L")
    alpha = img.split()[3]
    inverted = ImageOps.invert(gray)
    opaque = alpha.point(lambda a: 255 if a >= 128 else 0)
    print_layer = Image.composite(
        inverted, Image.new("L", img.size, 255), opaque
    )

    width, height = print_layer.size
    if width > TICKET_LOGO_MAX_WIDTH:
        scale = TICKET_LOGO_MAX_WIDTH / width
        print_layer = print_layer.resize(
            (TICKET_LOGO_MAX_WIDTH, max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )

    print_layer = ImageEnhance.Contrast(print_layer).enhance(1.9)
    # Lower luminance (logo) -> black (0); higher threshold = bolder print
    return print_layer.point(
        lambda pixel: 0 if pixel < TICKET_LOGO_THRESHOLD else 255, mode="1"
    )


def format_ticket(printer, from_name: str, question: str) -> bool:
    """Print ticket matching Cafe Cursor receipt layout."""
    try:
        now = datetime.now()
        time_str = now.strftime("%I:%M %p")
        date_str = now.strftime("%B %d, %Y")
        name = (from_name or "").strip() or "Anonymous"
        message = (question or "").strip()

        printer.set(align="center", font="a", width=1, height=1, bold=False)
        printer.text(_rule())

        logo = resolve_logo_path()
        if logo:
            try:
                printer.image(
                    prepare_logo_image(logo),
                    center=True,
                    impl="bitImageRaster",
                )
            except Exception as exc:
                logger.warning("Could not print logo (%s): %s", logo, exc)
        else:
            logger.warning(
                "No logo found. Add static/cursor-logo.png or set TICKET_LOGO_PATH"
            )

        printer.set(align="center", font="a", width=1, height=1, bold=False)
        printer.text(f"{TICKET_TITLE}\n")
        printer.text(_rule())

        printer.set(align="left", font="a", width=1, height=1, bold=False)
        printer.text(f"From: {name}\n")
        printer.text(f"Date: {date_str}\n")
        printer.text(f"Time: {time_str}\n")
        printer.text(_rule())

        printer.text("Message:\n")
        wrapped = textwrap.wrap(message, width=TICKET_LINE_WIDTH) or [""]
        for line in wrapped:
            printer.text(f"{line}\n")

        printer.text(_rule())
        printer.text("\n\n")
        printer.cut()
        return True
    except Exception as exc:
        logger.error("Error printing ticket: %s", exc)
        return False
