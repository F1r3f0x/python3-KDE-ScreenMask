"""Stable display identifiers and readable labels."""

import json


def screen_id(screen):
    """Build an identifier from the display's connector and monitor details.

    Args:
        screen (QScreen): Display to identify.

    Returns:
        str: JSON-encoded display identifier, with geometry as a fallback.
    """
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
