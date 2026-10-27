# Author: Patricio Labin Correa <plabin@outlook.cl>
"""Persist ScreenMask preferences and brightness recovery state."""

import json

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor


class Settings:
    """Read and write ScreenMask preferences using a QSettings backend."""

    def __init__(self, backend=None):
        """Create settings backed by the supplied store or the user store.

        Args:
            backend (QSettings | None): Optional settings backend.
        """
        self.backend = backend if backend is not None else QSettings("ScreenMask", "ScreenMask")

    @property
    def configured(self):
        """bool: Whether the user has saved settings at least once."""
        return self.backend.value("configured", False, type=bool)

    @property
    def selected(self):
        """list[str]: Saved display identifiers, including disconnected displays."""
        return self.backend.value("displays", [], type=list)

    @property
    def color(self):
        """QColor: Saved color, falling back to black if it is invalid."""
        color = QColor(self.backend.value("color", "#000000", type=str))
        return color if color.isValid() else QColor("#000000")

    @property
    def lower_brightness(self):
        """bool: Whether masked displays should use minimum brightness."""
        return self.backend.value("lower_brightness", False, type=bool)

    @property
    def avoid_panels(self):
        """bool: Whether masks should leave reserved panel areas visible."""
        return self.backend.value("avoid_panels", False, type=bool)

    def brightness_recovery(self):
        """Return brightness values awaiting restoration after an interruption.

        Returns:
            dict: Saved brightness records indexed by display identifier.
        """
        try:
            value = json.loads(self.backend.value("brightness_recovery", "{}", type=str))
            return value if isinstance(value, dict) else {}
        except (ValueError, TypeError):
            return {}

    def save_brightness_recovery(self, records):
        """Persist brightness restoration records before changing a display.

        Args:
            records (dict): Display identifiers mapped to restoration records.
        """
        self.backend.setValue("brightness_recovery", json.dumps(records))
        self.backend.sync()
        if self.backend.status() != QSettings.Status.NoError:
            raise OSError("Could not save the brightness recovery record.")

    def save(self, selected, color, lower_brightness=False, avoid_panels=False):
        """Save the display selection and color, then synchronize the store.

        Args:
            selected (Iterable[str]): Display identifiers to remember.
            color (QColor): Color to use for masks.
            lower_brightness (bool): Lower brightness while displays are masked.
            avoid_panels (bool): Leave desktop panel areas uncovered.
        """
        self.backend.setValue("displays", list(selected))
        self.backend.setValue("color", color.name())
        self.backend.setValue("lower_brightness", lower_brightness)
        self.backend.setValue("avoid_panels", avoid_panels)
        self.backend.setValue("configured", True)
        self.backend.sync()
