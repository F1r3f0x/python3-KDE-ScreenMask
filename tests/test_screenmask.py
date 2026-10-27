"""Exercise settings, mask windows, and controller behavior with Qt."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QSystemTrayIcon

from screenmask.app import Controller, app_icon
from screenmask.dialog import SettingsDialog
from screenmask.displays import screen_id
from screenmask.layer_windows import LayerIdentifyWindow, LayerMaskWindow
from screenmask.settings import Settings
from screenmask.windows import IdentifyWindow, MaskWindow, prepare_screen_window


app = QApplication.instance() or QApplication([])
app.setQuitOnLastWindowClosed(False)


class ScreenMaskTests(unittest.TestCase):
    """Check display selection, painting, dismissal, and recovery flows."""

    def setUp(self):
        """Create temporary settings and select the offscreen display."""
        self.directory = tempfile.TemporaryDirectory()
        backend = QSettings(os.path.join(self.directory.name, "settings.ini"), QSettings.Format.IniFormat)
        self.settings = Settings(backend)
        self.screen = app.screens()[0]

    def tearDown(self):
        """Process pending Qt events and remove temporary settings."""
        app.processEvents()
        self.directory.cleanup()

    def test_app_icon_uses_bundled_svg(self):
        """Use the bundled SVG for application and tray icons."""
        svg = Path(__file__).resolve().parent.parent / "assets/org.screenmask.ScreenMask.svg"
        expected = QIcon(str(svg)).pixmap(64, 64).toImage()
        self.assertFalse(expected.isNull())
        self.assertEqual(app_icon().pixmap(64, 64).toImage(), expected)

    def test_settings_and_disconnected_display_selection_survive_edits(self):
        """Keep disconnected selections when editing connected displays."""
        missing = '["disconnected"]'
        self.settings.save([missing, screen_id(self.screen)], QColor("#123456"))
        dialog = SettingsDialog(self.settings, app.screens())
        self.assertTrue(dialog.checkboxes[screen_id(self.screen)].isChecked())
        dialog.checkboxes[screen_id(self.screen)].setChecked(False)
        dialog.save()
        self.assertEqual(self.settings.selected, [missing])
        self.assertEqual(self.settings.color.name(), "#123456")
        self.assertTrue(self.settings.configured)

    def test_double_click_dismisses_only_the_mask(self):
        """Dismiss a mask on double-click release, but not on a single click."""
        mask = MaskWindow(self.screen, QColor("black"))
        dismissed = []
        mask.dismissed.connect(lambda: dismissed.append(True))
        mask.showFullScreen()
        app.processEvents()
        QTest.mouseClick(mask, Qt.MouseButton.LeftButton)
        self.assertEqual(dismissed, [])
        QTest.mouseDClick(mask, Qt.MouseButton.LeftButton)
        self.assertEqual(dismissed, [])
        QTest.mouseRelease(mask, Qt.MouseButton.LeftButton)
        self.assertEqual(dismissed, [True])
        mask.close()

    def test_mask_paints_saved_color_over_fullscreen_surface(self):
        """Paint the selected color across the fullscreen surface."""
        mask = MaskWindow(self.screen, QColor("#345678"))
        mask.showFullScreen()
        app.processEvents()
        self.assertEqual(mask.size(), self.screen.geometry().size())
        image = mask.grab().toImage()
        for x, y in ((0, 0), (image.width() // 2, image.height() // 2),
                     (image.width() - 1, image.height() - 1)):
            self.assertEqual(image.pixelColor(x, y).name(), "#345678")
        mask.close()

    def test_mask_and_identification_are_fullscreen_top_level_windows(self):
        """Create fullscreen mask and identification windows on their screen."""
        for window in (MaskWindow(self.screen, QColor("black")), IdentifyWindow(self.screen, 1)):
            self.assertEqual(window.windowType(), Qt.WindowType.Window)
            self.assertIs(window.screen(), self.screen)
            window.showFullScreen()
            app.processEvents()
            self.assertTrue(window.isFullScreen())
            self.assertIs(window.windowHandle().screen(), self.screen)
            window.close()

    def test_wayland_sets_screen_without_requesting_global_geometry(self):
        """Avoid requesting global window geometry on Wayland."""
        window, screen = Mock(), Mock()
        with patch("screenmask.windows.QGuiApplication.platformName", return_value="wayland"):
            prepare_screen_window(window, screen)
        window.setScreen.assert_called_once_with(screen)
        window.setGeometry.assert_not_called()

    def test_layer_shell_window_screen_color_and_dismissal(self):
        """Keep the layer target, update its color, and handle dismissal."""
        try:
            mask = LayerMaskWindow(self.screen, QColor("red"))
            identify = LayerIdentifyWindow(self.screen, 2)
        except RuntimeError as error:
            if "module \"org.kde.layershell\" is not installed" in str(error):
                self.skipTest(str(error))
            raise
        self.assertIs(mask.window.property("layerTarget"), self.screen)
        self.assertIs(identify.window.property("layerTarget"), self.screen)
        self.assertEqual(mask.window.property("color").name(), "#ff0000")
        mask.color = QColor("blue")
        mask.update()
        self.assertEqual(mask.window.property("color").name(), "#0000ff")
        # Offscreen Qt does not implement layer-shell anchoring, so provide a
        # size to exercise its actual QML mouse handler.
        mask.window.resize(300, 200)
        mask.showFullScreen()
        app.processEvents()
        dismissed = []
        mask.dismissed.connect(lambda: dismissed.append(True))
        QTest.mouseDClick(mask.window, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
        QTest.mouseRelease(mask.window, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
        self.assertEqual(dismissed, [True])
        mask.close()
        identify.close()

    def test_activate_restores_dismissed_mask_and_applies_saved_color(self):
        """Restore dismissed connected masks with the saved color."""
        self.settings.save([screen_id(self.screen), '["disconnected"]'], QColor("#345678"))
        controller = Controller(app, self.settings)
        controller.activate()
        self.assertEqual(len(controller.masks), 1)
        key = screen_id(self.screen)
        self.assertEqual(controller.masks[key].color.name(), "#345678")
        controller.dismiss(key)
        self.assertEqual(controller.masks, {})
        controller.activate()
        self.assertIn(key, controller.masks)
        controller.dismiss_all()
        app.screenAdded.disconnect(controller.screen_added)
        app.screenRemoved.disconnect(controller.screen_removed)

    def test_tray_click_toggles_masks_and_ignores_other_actions(self):
        """Toggle visible masks on primary clicks and ignore other activations."""
        key = screen_id(self.screen)
        self.settings.save([key], QColor("black"))
        controller = Controller(app, self.settings)
        self.addCleanup(app.screenAdded.disconnect, controller.screen_added)
        self.addCleanup(app.screenRemoved.disconnect, controller.screen_removed)
        self.addCleanup(controller.dismiss_all)

        controller.tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
        self.assertIn(key, controller.masks)
        controller.tray_activated(QSystemTrayIcon.ActivationReason.Context)
        self.assertIn(key, controller.masks)
        controller.tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
        self.assertFalse(controller.masks)
        controller.tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
        self.assertIn(key, controller.masks)

    def test_setting_changes_update_and_remove_visible_masks(self):
        """Apply color changes and remove masks for deselected displays."""
        key = screen_id(self.screen)
        self.settings.save([key], QColor("black"))
        controller = Controller(app, self.settings)
        controller.activate()
        self.settings.save([key], QColor("red"))
        # Exercise the post-save behavior without requiring an interactive dialog.
        controller.tray = object()
        controller.settings_closed(QDialog.DialogCode.Accepted, False)
        self.assertEqual(controller.masks[key].color.name(), "#ff0000")
        self.settings.save([], QColor("red"))
        controller.settings_closed(QDialog.DialogCode.Accepted, False)
        self.assertFalse(controller.masks)
        app.screenAdded.disconnect(controller.screen_added)
        app.screenRemoved.disconnect(controller.screen_removed)

    def test_first_save_with_no_displays_does_not_reopen_settings(self):
        """Allow an empty selection without immediately reopening settings."""
        self.settings.save([], QColor("black"))
        controller = Controller(app, self.settings)
        controller.tray = object()
        with patch.object(controller, "open_settings") as open_settings:
            controller.settings_closed(QDialog.DialogCode.Accepted, True)
            open_settings.assert_not_called()
        app.screenAdded.disconnect(controller.screen_added)
        app.screenRemoved.disconnect(controller.screen_removed)

    def test_disconnecting_a_masked_display_closes_only_its_mask(self):
        """Close the disconnected display's mask and retain its preference."""
        key = screen_id(self.screen)
        self.settings.save([key], QColor("black"))
        controller = Controller(app, self.settings)
        controller.activate()
        other_mask = Mock()
        controller.masks["other"] = other_mask
        self.assertIn(key, controller.masks)
        controller.screen_removed(self.screen)
        self.assertNotIn(key, controller.masks)
        self.assertIs(controller.masks["other"], other_mask)
        controller.dismiss_all()
        self.assertIn(key, self.settings.selected)
        app.screenAdded.disconnect(controller.screen_added)
        app.screenRemoved.disconnect(controller.screen_removed)

    def test_screens_without_connector_names_have_distinct_fallback_ids(self):
        """Distinguish unnamed displays by their geometry."""
        first = Mock()
        second = Mock()
        for screen in (first, second):
            screen.name.return_value = ""
            screen.manufacturer.return_value = ""
            screen.model.return_value = ""
            screen.serialNumber.return_value = ""
        first.geometry.return_value = self.screen.geometry()
        second_rect = self.screen.geometry()
        second_rect.moveLeft(second_rect.x() + second_rect.width())
        second.geometry.return_value = second_rect
        self.assertNotEqual(screen_id(first), screen_id(second))

    def test_first_launch_save_dismiss_and_restore(self):
        """Exercise first-run settings, mask dismissal, and reactivation."""
        controller = Controller(app, self.settings)
        # The offscreen Qt platform has no tray; exercise the KDE tray path.
        controller.tray = Mock()
        self.addCleanup(app.screenAdded.disconnect, controller.screen_added)
        self.addCleanup(app.screenRemoved.disconnect, controller.screen_removed)
        self.addCleanup(controller.dismiss_all)
        controller.start()
        dialog = controller.dialog
        self.assertIsNotNone(dialog)
        key = screen_id(self.screen)
        dialog.checkboxes[key].setChecked(True)
        buttons = dialog.findChild(QDialogButtonBox)
        QTest.mouseClick(buttons.button(QDialogButtonBox.StandardButton.Save), Qt.MouseButton.LeftButton)
        self.assertTrue(self.settings.configured)
        self.assertIn(key, self.settings.selected)
        self.assertIn(key, controller.masks)

        mask = controller.masks[key]
        QTest.mouseDClick(mask, Qt.MouseButton.LeftButton)
        QTest.mouseRelease(mask, Qt.MouseButton.LeftButton)
        self.assertNotIn(key, controller.masks)
        controller.activate()
        self.assertIn(key, controller.masks)

    def test_saving_new_display_shows_it_without_restoring_dismissed_masks(self):
        """Show newly selected displays without restoring dismissed masks."""
        first_key = screen_id(self.screen)
        second = Mock()
        second.name.return_value = "DP-test"
        second.manufacturer.return_value = "Test"
        second.model.return_value = "Display"
        second.serialNumber.return_value = "2"
        second.geometry.return_value = self.screen.geometry()
        second_key = screen_id(second)
        self.settings.save([first_key], QColor("black"))
        controller = Controller(app, self.settings)
        controller.tray = Mock()
        controller.mask_window_type = Mock(side_effect=lambda screen, color: Mock())
        self.addCleanup(app.screenAdded.disconnect, controller.screen_added)
        self.addCleanup(app.screenRemoved.disconnect, controller.screen_removed)
        self.addCleanup(controller.dismiss_all)
        with patch.object(app, "screens", return_value=[self.screen, second]):
            controller.activate()
            controller.dismiss(first_key)
            controller.open_settings()
            controller.dialog.checkboxes[second_key].setChecked(True)
            controller.dialog.save()
            self.assertNotIn(first_key, controller.masks)
            self.assertIn(second_key, controller.masks)
            controller.masks[second_key].showFullScreen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
