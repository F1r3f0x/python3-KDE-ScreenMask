"""Wayland masks backed by KDE's per-output layer-shell interface."""

from PySide6.QtCore import QByteArray, QObject, QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtQml import QQmlComponent, QQmlEngine


_LAYER_WINDOW = b'''
import QtQuick
import org.kde.layershell 1.0 as LayerShell

Window {
    id: root
    color: initialColor
    property bool identifying: identifyDisplay
    property string displayNumber: identifyNumber
    property bool avoidPanels: initialAvoidPanels
    readonly property var layerTarget: LayerShell.Window.screen
    readonly property int panelExclusionZone: LayerShell.Window.exclusionZone
    signal dismissRequested()

    LayerShell.Window.screen: targetScreen
    LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom
                               | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
    LayerShell.Window.layer: LayerShell.Window.LayerOverlay
    LayerShell.Window.exclusionZone: root.avoidPanels ? 0 : -1
    LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
    LayerShell.Window.activateOnShow: false
    LayerShell.Window.scope: "screenmask"

    Text {
        anchors.centerIn: parent
        visible: root.identifying
        text: root.displayNumber
        color: "white"
        font.bold: true
        font.pixelSize: Math.max(48, Math.min(root.width, root.height) / 4)
    }
    MouseArea {
        anchors.fill: parent
        enabled: !root.identifying
        acceptedButtons: Qt.LeftButton
        property bool dismissOnRelease: false
        onDoubleClicked: dismissOnRelease = true
        onReleased: {
            if (dismissOnRelease) {
                dismissOnRelease = false
                root.dismissRequested()
            }
        }
    }
}
'''


class LayerWindow(QObject):
    """Wrap a KDE layer-shell window targeting a specific Wayland display.

    Attributes:
        dismissed (Signal): Emitted after the mask is double-clicked.
    """
    dismissed = Signal()

    def __init__(self, screen, color, number=None, avoid_panels=False):
        """Create a mask or numbered identification surface.

        Args:
            screen (QScreen): Display targeted by the layer surface.
            color (QColor): Initial background color.
            number (int | None): Display number for an identification surface.
            avoid_panels (bool): Respect the compositor's reserved panel areas.

        Raises:
            RuntimeError: If the layer-shell QML component cannot be created.
        """
        super().__init__()
        self.engine = QQmlEngine(self)
        context = self.engine.rootContext()
        context.setContextProperty("targetScreen", screen)
        context.setContextProperty("initialColor", QColor(color))
        context.setContextProperty("identifyDisplay", number is not None)
        context.setContextProperty("identifyNumber", str(number or ""))
        context.setContextProperty("initialAvoidPanels", avoid_panels)
        self.component = QQmlComponent(self.engine, self)
        self.component.setData(QByteArray(_LAYER_WINDOW), QUrl())
        self.window = self.component.create()
        if self.window is None:
            errors = "; ".join(error.toString() for error in self.component.errors())
            raise RuntimeError("Could not create a KDE layer-shell window: " + errors)
        self.window.dismissRequested.connect(self.dismissed.emit)
        self.color = QColor(color)

    def showFullScreen(self):
        """Show the layer surface, which is anchored to every display edge."""
        # Layer-shell anchors fill the target output; an xdg fullscreen request
        # would use a different shell surface and lose the output selection.
        self.window.show()

    def update(self):
        """Apply the current color to the QML window."""
        self.window.setProperty("color", self.color)

    def set_panel_avoidance(self, enabled):
        """Choose whether the layer surface avoids reserved panel areas.

        Args:
            enabled (bool): Whether panel areas should remain uncovered.
        """
        self.window.setProperty("avoidPanels", enabled)

    def close(self):
        """Close the underlying QML window."""
        self.window.close()


class LayerMaskWindow(LayerWindow):
    """Create a dismissible solid-color Wayland mask."""

    def __init__(self, screen, color, avoid_panels=False):
        """Initialize the mask for a display and color.

        Args:
            screen (QScreen): Display to cover.
            color (QColor): Initial mask color.
            avoid_panels (bool): Whether to leave panel areas uncovered.
        """
        super().__init__(screen, color, avoid_panels=avoid_panels)


class LayerIdentifyWindow(LayerWindow):
    """Create a numbered Wayland display-identification surface."""

    def __init__(self, screen, number):
        """Initialize the identification surface for a display.

        Args:
            screen (QScreen): Display to identify.
            number (int): One-based display number to draw.
        """
        super().__init__(screen, QColor("#20242b"), number)
