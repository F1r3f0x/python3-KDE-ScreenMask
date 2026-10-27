"""Stable display identifiers and readable labels."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScreenSnapshot:
    """Immutable display details that can be safely passed to a worker."""

    key: str
    connector: str
    product: str
    vendor: str
    serial: str
    physical_id: str | None

    def name(self):
        """Return the connector name."""
        return self.connector

    def model(self):
        """Return the monitor model."""
        return self.product

    def manufacturer(self):
        """Return the monitor manufacturer."""
        return self.vendor

    def serialNumber(self):
        """Return the monitor serial reported by Qt."""
        return self.serial


def snapshot_screen(screen):
    """Capture screen details on the Qt thread before passing them to a worker.

    Args:
        screen (QScreen): Connected display.

    Returns:
        ScreenSnapshot: Immutable identity and matching details.
    """
    return ScreenSnapshot(screen_id(screen), screen.name(), screen.model(),
                          screen.manufacturer(), screen.serialNumber(), monitor_identity(screen))


def monitor_identity(screen):
    """Identify a monitor using a serial number or its EDID fingerprint.

    Args:
        screen (QScreen | ScreenSnapshot): The connected display.

    Returns:
        str | None: Identity fingerprint, or None when it cannot be obtained.
    """
    if isinstance(screen, ScreenSnapshot):
        return screen.physical_id
    serial = screen.serialNumber().strip()
    if (serial and serial.strip("0") and serial.lstrip("0") != "1" and
            serial.casefold() not in {"unknown", "none", "ffffffff"}):
        return f"serial:{screen.manufacturer()}:{screen.model()}:{serial}"
    connector = screen.name()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", connector):
        return None
    candidates = []
    for path in Path("/sys/class/drm").glob(f"card[0-9]*-{connector}/edid"):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if len(data) < 128:
            continue
        candidates.append("edid:" + hashlib.sha256(data).hexdigest())
    return candidates[0] if len(candidates) == 1 else None


def screen_id(screen):
    """Build an identifier from the display's connector and monitor details.

    Args:
        screen (QScreen): Display to identify.

    Returns:
        str: JSON-encoded display identifier, with geometry as a fallback.
    """
    if isinstance(screen, ScreenSnapshot):
        return screen.key
    # The connector name disambiguates otherwise identical monitors. Serial
    # numbers alone are often absent or duplicated in monitor EDID data.
    identity = [screen.name(), screen.manufacturer(), screen.model(), screen.serialNumber()]
    if not screen.name():
        # A connector-less screen needs a fallback to avoid merging two
        # otherwise indistinguishable displays. Rearranging such displays can
        # change their identities, so they may need selecting again.
        rect = screen.geometry()
        identity.append([rect.x(), rect.y(), rect.width(), rect.height()])
    return json.dumps(
        identity,
        ensure_ascii=True,
        separators=(",", ":"),
    )


def screen_label(screen, index):
    """Format a numbered display label for the settings dialog.

    Args:
        screen (QScreen): Display to describe.
        index (int): One-based number shown to the user.

    Returns:
        str: Monitor details, connector, and logical resolution.
    """
    description = " ".join(filter(None, (screen.manufacturer(), screen.model())))
    name = screen.name() or "Unknown connector"
    size = screen.geometry().size()
    detail = f"{name} · {size.width()} × {size.height()}"
    return f"{index}. {description} ({detail})" if description else f"{index}. {detail}"
