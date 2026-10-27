"""Persist selected displays and the mask color with Qt settings."""

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

    def save(self, selected, color):
        """Save the display selection and color, then synchronize the store.

        Args:
            selected (Iterable[str]): Display identifiers to remember.
            color (QColor): Color to use for masks.
        """
        self.backend.setValue("displays", list(selected))
        self.backend.setValue("color", color.name())
        self.backend.setValue("configured", True)
        self.backend.sync()
