"""Shared thermal ticket layout for app.py and backend/api.py."""
from __future__ import annotations

import logging
import os
import textwrap
import threading
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_print_lock = threading.Lock()
print_lock = _print_lock

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DEFAULT_LOGO = STATIC_DIR / "cursor-logo.png"

try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass


def _layout_settings() -> dict[str, int | str]:
    """Read ticket layout from environment on each print (respects .env updates after restart)."""
    return {
        "title": os.getenv("TICKET_TITLE", "Cafe Cursor Bali").strip(),
        "line_width": int(os.getenv("TICKET_LINE_WIDTH", "32")),
        "logo_max_width": int(os.getenv("TICKET_LOGO_MAX_WIDTH", "200")),
        "logo_threshold": int(os.getenv("TICKET_LOGO_THRESHOLD", "200")),
        "logo_contrast": float(os.getenv("TICKET_LOGO_CONTRAST", "2.4")),
    }


def _rule(width: int) -> str:
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


def prepare_logo_image(path: Path, max_width: int, threshold: int, contrast: float):
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
    if width > max_width:
        scale = max_width / width
        print_layer = print_layer.resize(
            (max_width, max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )

    print_layer = ImageEnhance.Contrast(print_layer).enhance(contrast)
    return print_layer.point(
        lambda pixel: 0 if pixel < threshold else 255, mode="1"
    )


def release_printer(printer) -> None:
    """Release USB/serial handle so the next job can open the device."""
    if printer is None:
        return
    try:
        printer.close()
    except Exception as exc:
        logger.warning("Could not release printer: %s", exc)
    # Brief pause so the OS/printer can drop the USB claim before reopening.
    time.sleep(0.15)


def format_ticket(printer, from_name: str, question: str) -> bool:
    """Print ticket matching Cafe Cursor receipt layout."""
    layout = _layout_settings()
    title = layout["title"]
    line_width = layout["line_width"]

    with _print_lock:
        try:
            return _format_ticket_body(printer, layout, title, line_width, from_name, question)
        finally:
            release_printer(printer)


def _format_ticket_body(
    printer,
    layout: dict,
    title: str,
    line_width: int,
    from_name: str,
    question: str,
) -> bool:
    try:
        now = datetime.now()
        time_str = now.strftime("%I:%M %p")
        date_str = now.strftime("%B %d, %Y")
        name = (from_name or "").strip() or "Anonymous"
        message = (question or "").strip()

        logger.info(
            "Ticket layout: title=%r logo_max_width=%s logo_threshold=%s",
            title,
            layout["logo_max_width"],
            layout["logo_threshold"],
        )

        printer.set(align="center", font="a", width=1, height=1, bold=False)
        printer.text(_rule(line_width))

        logo = resolve_logo_path()
        if logo:
            try:
                printer.image(
                    prepare_logo_image(
                        logo,
                        layout["logo_max_width"],
                        layout["logo_threshold"],
                        layout["logo_contrast"],
                    ),
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
        printer.text(f"{title}\n")
        printer.text(_rule(line_width))

        printer.set(align="left", font="a", width=1, height=1, bold=False)
        printer.text(f"From: {name}\n")
        printer.text(f"Date: {date_str}\n")
        printer.text(f"Time: {time_str}\n")
        printer.text(_rule(line_width))

        printer.text("Message:\n")
        wrapped = textwrap.wrap(message, width=line_width) or [""]
        for line in wrapped:
            printer.text(f"{line}\n")

        printer.text(_rule(line_width))
        printer.text("\n\n")
        printer.cut()
        return True
    except Exception as exc:
        logger.error("Error printing ticket: %s", exc)
        return False