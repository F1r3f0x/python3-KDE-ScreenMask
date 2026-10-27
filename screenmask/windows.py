"""Provide Qt widget masks and display-identification windows."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget


def prepare_screen_window(window, screen):
    """Assign a target display and, where supported, its geometry.

    Args:
        window (QWidget): Top-level window being prepared.
        screen (QScreen): Target display.
    """
    # Set QWidget's initial screen before its native window is created. Qt
    # Wayland uses that screen for the fullscreen output request.
    window.setScreen(screen)
    # Wayland controls top-level positions itself; coordinates supplied here
    # can cause Qt to reassociate a window with a different screen.
    if not QGuiApplication.platformName().startswith("wayland"):
        window.setGeometry(screen.geometry())


class MaskWindow(QWidget):
    """Display a solid-color mask that can be dismissed with a double-click.

    Attributes:
        dismissed (Signal): Emitted when the user dismisses the mask.
    """
    dismissed = Signal()

    def __init__(self, screen, color):
        """Create a mask for a display.

        Args:
            screen (QScreen): Display to cover.
            color (QColor): Initial mask color.
        """
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("ScreenMask")
        self.color = QColor(color)
        self._dismiss_on_release = False
        prepare_screen_window(self, screen)

    def paintEvent(self, event):
        """Paint the entire window with the current mask color.

        Args:
            event (QPaintEvent): Paint event supplied by Qt.
        """
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.color)

    def mouseDoubleClickEvent(self, event):
        """Schedule dismissal on release after a left-button double-click.

        Args:
            event (QMouseEvent): Double-click event supplied by Qt.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            # Keep the window present until the final button release so the
            # release cannot be delivered to a window underneath the mask.
            self._dismiss_on_release = True
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        """Dismiss after the final release of a left-button double-click.

        Args:
            event (QMouseEvent): Mouse release event supplied by Qt.
        """
        if self._dismiss_on_release and event.button() == Qt.MouseButton.LeftButton:
            self._dismiss_on_release = False
            event.accept()
            self.dismissed.emit()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        """Dismiss on Escape when the mask has keyboard focus.

        Args:
            event (QKeyEvent): Key press event supplied by Qt.
        """
        if event.key() == Qt.Key.Key_Escape:
            self.dismissed.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class IdentifyWindow(QWidget):
    """Show a display number in a temporary full-screen widget."""

    def __init__(self, screen, number):
        """Create an identification window for a display.

        Args:
            screen (QScreen): Display to identify.
            number (int): One-based display number to draw.
        """
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.number = str(number)
        prepare_screen_window(self, screen)

    def paintEvent(self, event):
        """Paint the background and centered display number.

        Args:
            event (QPaintEvent): Paint event supplied by Qt.
        """
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#20242b"))
        painter.setPen(QColor("white"))
        font = QFont()
        font.setPixelSize(max(48, min(self.width(), self.height()) // 4))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.number)
