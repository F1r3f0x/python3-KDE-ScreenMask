# Author: Patricio Labin Correa <plabin@outlook.cl>
"""Wayland masks backed by KDE's per-output layer-shell interface."""

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlContext, QQmlEngine


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


class LayerRuntime:
    """Share the QML engine and compiled window component across displays."""

    def __init__(self, app):
        """Create the shared engine and compile the layer-window component.

        Args:
            app (QGuiApplication): Application owning the QML engine.
        """
        self.app = app
        self.engine = QQmlEngine(app)
        self.component = QQmlComponent(self.engine, self.engine)
        self.component.setData(QByteArray(_LAYER_WINDOW), QUrl())
        self.windows = 0

    def retain(self):
        """Keep the runtime alive while a layer window uses it."""
        self.windows += 1

    def release(self):
        """Release a window and retire the engine after the last one closes."""
        self.windows -= 1
        if self.windows == 0:
            QTimer.singleShot(0, self.retire_if_unused)

    def retire_if_unused(self):
        """Delete unused QML resources after pending windows are closed."""
        if self.windows == 0 and getattr(self.app, "_screenmask_layer_runtime", None) is self:
            del self.app._screenmask_layer_runtime
            self.engine.deleteLater()


def layer_runtime():
    """Return the application-wide layer-shell QML runtime.

    Returns:
        LayerRuntime: Shared engine and component for the current application.
    """
    app = QGuiApplication.instance()
    runtime = getattr(app, "_screenmask_layer_runtime", None)
    if runtime is None:
        runtime = LayerRuntime(app)
        app._screenmask_layer_runtime = runtime
    return runtime


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
        runtime = layer_runtime()
        self.context = QQmlContext(runtime.engine.rootContext(), self)
        self.context.setContextProperty("targetScreen", screen)
        self.context.setContextProperty("initialColor", QColor(color))
        self.context.setContextProperty("identifyDisplay", number is not None)
        self.context.setContextProperty("identifyNumber", str(number or ""))
        self.context.setContextProperty("initialAvoidPanels", avoid_panels)
        self.window = runtime.component.create(self.context)
        if self.window is None:
            errors = "; ".join(error.toString() for error in runtime.component.errors())
            runtime.retire_if_unused()
            raise RuntimeError("Could not create a KDE layer-shell window: " + errors)
        self.runtime = runtime
        self.runtime.retain()
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
        """Close and schedule deletion of the underlying QML window."""
        if self.window is not None:
            window = self.window
            self.window = None
            window.close()
            window.deleteLater()
            self.runtime.release()


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
