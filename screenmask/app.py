"""Coordinate application startup, display masks, settings, and tray actions."""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox, QSystemTrayIcon

from .brightness_async import AsyncBrightness
from .dialog import SettingsDialog
from .displays import screen_id
from .layer_windows import LayerIdentifyWindow, LayerMaskWindow
from .settings import Settings
from .single_instance import SingleInstance
from .windows import IdentifyWindow, MaskWindow


def configure_renderer():
    """Default Qt Quick to software rendering unless explicitly configured."""
    os.environ.setdefault("QT_QUICK_BACKEND", "software")


def app_icon():
    """Return the bundled application icon or a simple fallback icon.

    Returns:
        QIcon: The icon used for the application and system tray.
    """
    icon_name = "org.screenmask.ScreenMask.svg"
    locations = (
        Path(__file__).resolve().parent.parent / "assets" / icon_name,
        Path(sys.prefix) / "share/icons/hicolor/scalable/apps" / icon_name,
    )
    for path in locations:
        if path.is_file():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon
    icon = QIcon.fromTheme("org.screenmask.ScreenMask")
    if not icon.isNull():
        return icon
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor("#262d3a"))
    return QIcon(pixmap)


class Controller:
    """Manage mask windows and the application's desktop controls."""

    def __init__(self, app, settings=None):
        """Initialize the controller and connect display and tray signals.

        Args:
            app (QApplication): The running Qt application.
            settings (Settings | None): Settings to use, or the default store.
        """
        self.app = app
        self.settings = settings or Settings()
        self.brightness = AsyncBrightness(self.settings)
        self.brightness.set_screens(self.app.screens())
        self.brightness.errors.connect(self.report_brightness_errors)
        self.brightness.drained.connect(self.app.quit)
        self._quitting = False
        self.masks = {}
        self.identifiers = []
        self.identify_timer = QTimer()
        self.identify_timer.setSingleShot(True)
        self.identify_timer.timeout.connect(self.clear_identifiers)
        self.dialog = None
        self.selection_before_edit = set()
        self.brightness_before_edit = self.settings.lower_brightness
        self.activate_after_save = False
        self.tray = None
        wayland = QGuiApplication.platformName().startswith("wayland")
        self.mask_window_type = LayerMaskWindow if wayland else MaskWindow
        self.identify_window_type = LayerIdentifyWindow if wayland else IdentifyWindow
        self.app.screenRemoved.connect(self.screen_removed)
        self.app.screenAdded.connect(self.screen_added)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(app_icon(), self.app)
            self.tray.setToolTip("ScreenMask")
            menu = QMenu()
            menu.addAction("Show Masks", self.activate)
            menu.addAction("Dismiss All", self.dismiss_all)
            menu.addSeparator()
            menu.addAction("Settings…", self.open_settings)
            menu.addSeparator()
            menu.addAction("Quit", self.quit)
            self.tray.setContextMenu(menu)
            self.menu = menu
            self.tray.activated.connect(self.tray_activated)
            self.tray.show()

    def start(self):
        """Show initial settings or activate the saved display selection."""
        self.brightness.restore_all()
        if not self.settings.configured or not self.tray:
            self.open_settings(activate_after_save=True)
        else:
            self.activate()

    def tray_activated(self, reason):
        """Toggle masks when the tray icon receives a primary click.

        Args:
            reason (QSystemTrayIcon.ActivationReason): Tray activation reason.
        """
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_masks()

    def toggle_masks(self):
        """Hide visible masks or show masks using the saved settings."""
        if self.masks:
            self.dismiss_all()
        else:
            self.activate()

    def toggle_masks_from_dialog(self):
        """Toggle masks using the settings currently displayed in the dialog."""
        if self.dialog is None:
            return
        self.activate_after_save = False
        if self.masks:
            self.dismiss_all()
        else:
            self.dialog.persist()
            self.selection_before_edit = set(self.settings.selected)
            self.brightness_before_edit = self.settings.lower_brightness
            self.activate()

    def update_dialog_mask_state(self):
        """Keep the settings toggle in sync with visible masks."""
        if self.dialog is not None:
            self.dialog.set_masks_visible(bool(self.masks))

    def activate(self):
        """Show masks on selected, connected displays or open settings."""
        if self._quitting:
            return
        if not self.settings.configured:
            self.open_settings(activate_after_save=True)
            return
        selected = set(self.settings.selected)
        screens = [screen for screen in self.app.screens() if screen_id(screen) in selected]
        if not screens:
            self.open_settings()
            return
        self.show_masks(screens)

    def show_masks(self, screens):
        """Create a mask for each requested screen that is not already masked.

        Args:
            screens (Iterable[QScreen]): Displays to cover.
        """
        for screen in screens:
            key = screen_id(screen)
            if key not in self.masks:
                try:
                    mask = self.mask_window_type(screen, self.settings.color, self.settings.avoid_panels)
                except RuntimeError as error:
                    QMessageBox.critical(None, "ScreenMask", str(error))
                    return
                mask.dismissed.connect(lambda key=key: self.dismiss(key))
                self.masks[key] = mask
                mask.showFullScreen()
                self.update_dialog_mask_state()
                if self.settings.lower_brightness:
                    self.brightness.lower(screen, self.app.screens())

    def report_brightness_errors(self, errors):
        """Report brightness problems without blocking the tray application.

        Args:
            errors (Iterable[str]): Problems to report to the user.
        """
        errors = list(errors)
        if not errors:
            return
        message = "\n".join(errors)
        if self.tray:
            self.tray.showMessage("ScreenMask brightness", message, QSystemTrayIcon.MessageIcon.Warning)
        else:
            QMessageBox.warning(None, "ScreenMask brightness", message)

    def dismiss(self, key):
        """Close and forget the mask associated with a display identifier.

        Args:
            key (str): Identifier returned by ``screen_id``.
        """
        mask = self.masks.pop(key, None)
        if mask is not None:
            mask.close()
            mask.deleteLater()
            self.update_dialog_mask_state()
            self.brightness.restore(key)

    def dismiss_all(self):
        """Close every currently visible mask."""
        for key in list(self.masks):
            self.dismiss(key)

    def open_settings(self, activate_after_save=False):
        """Open or raise the settings dialog.

        Args:
            activate_after_save (bool): Show saved masks after accepting the dialog.
        """
        if self.dialog is not None:
            self.dialog.showNormal()
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        dialog = SettingsDialog(self.settings, self.app.screens())
        self.selection_before_edit = set(self.settings.selected)
        self.brightness_before_edit = self.settings.lower_brightness
        self.activate_after_save = activate_after_save
        self.dialog = dialog
        dialog.identify_requested.connect(self.identify_displays)
        dialog.toggle_requested.connect(self.toggle_masks_from_dialog)
        self.update_dialog_mask_state()
        dialog.finished.connect(lambda result: self.settings_closed(result, self.activate_after_save))
        dialog.show()

    def settings_closed(self, result, activate_after_save):
        """Apply accepted settings and handle the no-tray recovery flow.

        Args:
            result (int): The dialog's completion code.
            activate_after_save (bool): Whether to activate all saved displays.
        """
        dialog = self.dialog
        self.dialog = None
        if dialog is not None:
            dialog.deleteLater()
        if result == QDialog.DialogCode.Accepted:
            # Apply changes to currently visible masks, without restoring ones
            # the user deliberately dismissed.
            selected = set(self.settings.selected)
            for key, mask in list(self.masks.items()):
                if key not in selected:
                    self.dismiss(key)
                else:
                    mask.color = self.settings.color
                    mask.update()
                    mask.set_panel_avoidance(self.settings.avoid_panels)
            if self.brightness_before_edit != self.settings.lower_brightness:
                if self.settings.lower_brightness:
                    for screen in self.app.screens():
                        if screen_id(screen) in self.masks:
                            self.brightness.lower(screen, self.app.screens())
                else:
                    self.brightness.restore_all()
            # An empty selection is a valid saved configuration. Leave the
            # app in the tray instead of reopening settings immediately.
            if activate_after_save and selected:
                self.activate()
            elif selected - self.selection_before_edit:
                newly_selected = selected - self.selection_before_edit
                self.show_masks([screen for screen in self.app.screens()
                                 if screen_id(screen) in newly_selected])
        if not self.tray:
            if self.masks:
                # Without a tray, the settings window stays available for recovery.
                self.open_settings()
            elif self.dialog is None:
                self.quit()

    def identify_displays(self):
        """Briefly show a numbered identification window on each display."""
        self.clear_identifiers()
        for index, screen in enumerate(self.app.screens(), 1):
            try:
                window = self.identify_window_type(screen, index)
            except RuntimeError as error:
                self.clear_identifiers()
                QMessageBox.critical(None, "ScreenMask", str(error))
                return
            self.identifiers.append(window)
            window.showFullScreen()
        self.identify_timer.start(2000)

    def clear_identifiers(self):
        """Stop the identification timer and close its windows."""
        self.identify_timer.stop()
        for window in self.identifiers:
            window.close()
            window.deleteLater()
        self.identifiers.clear()

    def screen_removed(self, screen):
        """Dismiss a disconnected screen's mask and refresh open settings.

        Args:
            screen (QScreen): The display removed by Qt.
        """
        key = screen_id(screen)
        self.brightness.set_screens(self.app.screens(), excluded=key)
        self.dismiss(key)
        if self.dialog is not None:
            QTimer.singleShot(0, lambda: self.dialog and self.dialog.refresh_screens(self.app.screens()))

    def screen_added(self, screen):
        """Refresh open settings when a display is connected.

        Args:
            screen (QScreen): The display added by Qt.
        """
        QTimer.singleShot(0, self.restore_unmasked_brightness)
        if self.dialog is not None:
            QTimer.singleShot(0, lambda: self.dialog and self.dialog.refresh_screens(self.app.screens()))

    def restore_unmasked_brightness(self):
        """Retry recovery for displays that do not have an active mask."""
        self.brightness.set_screens(self.app.screens())
        self.brightness.restore_unmasked(self.masks)

    def quit(self):
        """Remove masks and exit once queued brightness work finishes."""
        if self._quitting:
            return
        self._quitting = True
        self.clear_identifiers()
        self.dismiss_all()
        if self.tray:
            self.tray.hide()
        self.brightness.finish()

    def shutdown_on_exit(self):
        """Queue restoration if Qt is exiting outside the normal quit action."""
        if not self._quitting:
            self._quitting = True
            self.dismiss_all()
            self.brightness.finish()


def main():
    """Start the application or forward activation to an existing instance.

    Returns:
        int: The application exit status, or zero after forwarding activation.
    """
    configure_renderer()
    app = QApplication(sys.argv)
    app.setApplicationName("ScreenMask")
    app.setDesktopFileName("org.screenmask.ScreenMask")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())
    instance = SingleInstance()
    try:
        if not instance.start():
            return 0
    except RuntimeError as error:
        QMessageBox.critical(None, "ScreenMask", str(error))
        return 1
    controller = Controller(app)
    instance.activated.connect(controller.activate)
    app.aboutToQuit.connect(instance.close)
    app.aboutToQuit.connect(controller.shutdown_on_exit)
    QTimer.singleShot(0, controller.start)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
