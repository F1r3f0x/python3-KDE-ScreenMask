# Author: Patricio Labin Correa <plabin@outlook.cl>
"""Short, isolated display-placement diagnostic; run from a desktop terminal."""

import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QApplication

from .displays import screen_label
from .layer_windows import LayerMaskWindow
from .windows import MaskWindow


def describe(screen):
    """Format a display's connector and logical geometry for diagnostics.

    Args:
        screen (QScreen | None): Display to describe, if available.

    Returns:
        str: Connector and geometry, or ``none`` if no screen was supplied.
    """
    if screen is None:
        return "none"
    rect = screen.geometry()
    return f"{screen.name()} ({rect.x()},{rect.y()} {rect.width()}x{rect.height()})"


def main():
    """Display a temporary mask and report its backend and placement.

    Returns:
        int: The Qt exit status, or a nonzero status for invalid input or setup.
    """
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    screens = app.screens()
    print(f"Qt backend: {QGuiApplication.platformName()}", flush=True)
    for index, screen in enumerate(screens, 1):
        print(f"Display {screen_label(screen, index)}; geometry {describe(screen)}", flush=True)
    try:
        index = int(sys.argv[1]) if len(sys.argv) > 1 else 2
        if not 1 <= index <= len(screens):
            raise ValueError
    except ValueError:
        print(f"Choose a display number from 1 to {len(screens)}.", file=sys.stderr, flush=True)
        return 2

    screen = screens[index - 1]
    print(f"Requested display {index}: {describe(screen)}", flush=True)
    window_type = LayerMaskWindow if QGuiApplication.platformName().startswith("wayland") else MaskWindow
    try:
        mask = window_type(screen, QColor("#0066cc"))
    except RuntimeError as error:
        print(f"Could not create mask: {error}", file=sys.stderr, flush=True)
        return 1
    print(f"Window type: {window_type.__name__}", flush=True)
    mask.dismissed.connect(app.quit)
    mask.showFullScreen()

    def report():
        """Print the layer target and the window's reported screen and size."""
        window = mask.window if isinstance(mask, LayerMaskWindow) else mask.windowHandle()
        if window is None:
            print("No native window was created", flush=True)
        else:
            rect = window.geometry()
            if isinstance(mask, LayerMaskWindow):
                print(f"Layer-shell target: {describe(window.property('layerTarget'))}", flush=True)
            print(f"Qt-reported window screen: {describe(window.screen())}", flush=True)
            print(f"Qt-reported window geometry: {rect.x()},{rect.y()} {rect.width()}x{rect.height()}", flush=True)
        print("The blue test mask will close automatically.", flush=True)

    QTimer.singleShot(2000, report)
    QTimer.singleShot(6000, app.quit)
    result = app.exec()
    mask.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
