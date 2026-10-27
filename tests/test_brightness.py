"""Check per-display brightness selection and restoration."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QSettings

from screenmask.brightness import BrightnessError, BrightnessManager, PowerDevilBackend
from screenmask.displays import ScreenSnapshot, monitor_identity, screen_id
from screenmask.settings import Settings


def make_screen(name, model):
    """Create a named mock display for brightness tests.

    Args:
        name (str): Display connector.
        model (str): Monitor model.

    Returns:
        Mock: Screen exposing the methods used for identification.
    """
    screen = Mock()
    screen.name.return_value = name
    screen.model.return_value = model
    screen.manufacturer.return_value = "Test"
    screen.serialNumber.return_value = name
    return screen


class BrightnessTests(unittest.TestCase):
    """Exercise mapping, preservation, and safe recovery of brightness."""

    def setUp(self):
        """Create temporary settings and a controllable display."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        path = str(Path(self.directory.name) / "settings.ini")
        self.settings = Settings(QSettings(path, QSettings.Format.IniFormat))
        self.screen = make_screen("DP-1", "G241")
        self.backend = Mock()
        self.backend.displays.return_value = [("/display0", "MSI G241")]
        self.backend.read.return_value = 72

    def test_lower_and_restore_preserve_per_display_brightness(self):
        """Save the original value before lowering, then restore it."""
        manager = BrightnessManager(self.settings, self.backend)
        manager.lower(self.screen, [self.screen])
        self.backend.set.assert_called_once_with("/display0", 0)
        self.assertEqual(self.settings.brightness_recovery()[screen_id(self.screen)]["brightness"], 72)
        self.backend.read.return_value = 0
        manager.restore(screen_id(self.screen), [self.screen])
        self.backend.set.assert_called_with("/display0", 72)
        self.assertEqual(self.settings.brightness_recovery(), {})

    def test_failed_recovery_save_does_not_dim_the_monitor(self):
        """Avoid changing brightness if the recovery record cannot be saved."""
        manager = BrightnessManager(self.settings, self.backend)
        with patch.object(self.settings, "save_brightness_recovery", side_effect=OSError("write failed")):
            with self.assertRaises(OSError):
                manager.lower(self.screen, [self.screen])
        self.backend.set.assert_not_called()
        self.assertEqual(manager.pending, {})

    def test_recovery_survives_interruption_and_unavailable_display(self):
        """Keep pending values until a later process can restore them."""
        BrightnessManager(self.settings, self.backend).lower(self.screen, [self.screen])
        self.backend.displays.return_value = []
        manager = BrightnessManager(self.settings, self.backend)
        self.assertTrue(manager.restore_all([]))
        self.assertIn(screen_id(self.screen), self.settings.brightness_recovery())
        self.backend.displays.return_value = [("/display1", "MSI G241")]
        self.backend.read.return_value = 0
        self.assertEqual(manager.restore_all([self.screen]), [])
        self.backend.set.assert_called_with("/display1", 72)

    def test_manual_brightness_change_is_not_overwritten(self):
        """Preserve a brightness change made by the user while masked."""
        manager = BrightnessManager(self.settings, self.backend)
        manager.lower(self.screen, [self.screen])
        self.backend.read.return_value = 33
        manager.restore(screen_id(self.screen), [self.screen])
        self.backend.set.assert_called_once_with("/display0", 0)
        self.assertEqual(manager.pending, {})

    def test_duplicate_model_is_not_changed(self):
        """Avoid changing either monitor when a label cannot be matched uniquely."""
        manager = BrightnessManager(self.settings, self.backend)
        with self.assertRaises(BrightnessError):
            manager.lower(self.screen, [self.screen, make_screen("DP-2", "G241")])
        self.backend.set.assert_not_called()
        self.assertEqual(self.settings.brightness_recovery(), {})

    def test_recovery_rejects_replacement_with_the_same_model(self):
        """Never restore one monitor's brightness to a replacement monitor."""
        manager = BrightnessManager(self.settings, self.backend)
        manager.lower(self.screen, [self.screen])
        replacement = make_screen("DP-1", "G241")
        replacement.serialNumber.return_value = "different-serial"
        self.backend.displays.return_value = [("/display1", "MSI G241")]
        self.backend.read.return_value = 0
        with self.assertRaises(BrightnessError):
            manager.restore(screen_id(self.screen), [replacement])
        self.backend.set.assert_called_once_with("/display0", 0)
        self.assertIn(screen_id(self.screen), manager.pending)

    def test_legacy_recovery_record_is_not_applied_without_identity(self):
        """Keep older unverifiable records instead of changing a monitor."""
        key = screen_id(self.screen)
        self.settings.save_brightness_recovery({key: {"label": "MSI G241", "brightness": 72}})
        manager = BrightnessManager(self.settings, self.backend)
        with self.assertRaises(BrightnessError):
            manager.restore(key, [self.screen])
        self.backend.set.assert_not_called()

    def test_recovery_rejects_changed_edid_on_same_connector(self):
        """Reject a replacement even when Qt reports no monitor serial."""
        original = ScreenSnapshot("same-key", "DP-1", "G241", "MSI", "", "edid:original")
        replacement = ScreenSnapshot("same-key", "DP-1", "G241", "MSI", "", "edid:replacement")
        manager = BrightnessManager(self.settings, self.backend)
        manager.lower(original, [original])
        self.backend.read.return_value = 0
        with self.assertRaises(BrightnessError):
            manager.restore(original.key, [replacement])
        self.backend.set.assert_called_once_with("/display0", 0)

    def test_placeholder_serial_uses_edid_fingerprint(self):
        """Use the EDID fingerprint when the monitor reports a placeholder serial."""
        screen = make_screen("DP-1", "G241")
        screen.serialNumber.return_value = ""
        data = bytearray(128)
        data[12:16] = (1).to_bytes(4, "little")
        edid = Mock()
        edid.read_bytes.return_value = bytes(data)
        with patch("screenmask.displays.Path.glob", return_value=[edid]):
            self.assertTrue(monitor_identity(screen).startswith("edid:"))

    def test_distinct_kde_labels_match_the_correct_monitor(self):
        """Match a selected monitor independently of KDE's display ordering."""
        screens = [make_screen("HDMI-A-1", "CX070"), self.screen,
                   make_screen("DP-2", "VX2758-SERIES")]
        self.backend.displays.return_value = [
            ("/display0", "ViewSonic Corporation VX2758-SERIES"),
            ("/display1", "Microstep MSI G241"),
            ("/display2", "NewTek CX070"),
        ]
        BrightnessManager(self.settings, self.backend).lower(self.screen, screens)
        self.backend.set.assert_called_once_with("/display1", 0)

    def test_powerdevil_commands_parse_and_set_typed_values(self):
        """Parse KDE's display properties and call the typed brightness method."""
        backend = PowerDevilBackend()
        responses = ['as 1 "display0"', 's "MSI G241"', 'i 72', '']
        with patch.object(backend, "_run", side_effect=responses) as run:
            self.assertEqual(backend.displays(), [('/org/kde/ScreenBrightness/display0', 'MSI G241')])
            self.assertEqual(backend.read('/org/kde/ScreenBrightness/display0'), 72)
            backend.set('/org/kde/ScreenBrightness/display0', 0)
            self.assertEqual(run.call_args.args[-3:], ("iu", "0", "1"))


if __name__ == "__main__":
    unittest.main()
