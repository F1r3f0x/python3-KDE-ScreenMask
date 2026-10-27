"""Exercise asynchronous brightness operation and shutdown ordering."""

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication

from screenmask.brightness import BrightnessManager
from screenmask.brightness_async import AsyncBrightness
from screenmask.displays import screen_id
from screenmask.settings import Settings


app = QApplication.instance() or QApplication([])
app.setQuitOnLastWindowClosed(False)


class AsyncBrightnessTests(unittest.TestCase):
    """Verify that queued brightness calls do not block the Qt thread."""

    def test_slow_dimming_can_be_cancelled_without_blocking_ui(self):
        """A hide during a slow read prevents a later brightness change."""
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat))
            screen = Mock()
            screen.name.return_value = "DP-1"
            screen.model.return_value = "G241"
            screen.manufacturer.return_value = "MSI"
            screen.serialNumber.return_value = "unique-serial"
            backend = Mock()
            started = threading.Event()
            release = threading.Event()

            def displays():
                started.set()
                release.wait(3)
                return [("/display0", "MSI G241")]

            backend.displays.side_effect = displays
            backend.read.return_value = 72
            loop = QEventLoop()
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            with patch("screenmask.brightness_async.BrightnessManager",
                       side_effect=lambda worker_settings: BrightnessManager(worker_settings, backend)):
                service = AsyncBrightness(settings)
                service.set_screens([screen])
                service.lower(screen, [screen])
                self.assertTrue(started.wait(2))
                ticks = []
                QTimer.singleShot(0, lambda: ticks.append(True))
                app.processEvents()
                self.assertEqual(ticks, [True])
                service.restore(screen_id(screen))
                service.drained.connect(loop.quit)
                service.finish()
                release.set()
                timer.start(5000)
                loop.exec()
                self.assertTrue(timer.isActive(), "brightness worker did not finish")
                timer.stop()
                backend.set.assert_not_called()

    def test_shutdown_waits_for_dimming_then_restores_brightness(self):
        """Queue restoration after an in-flight brightness change before exit."""
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat))
            screen = Mock()
            screen.name.return_value = "DP-1"
            screen.model.return_value = "G241"
            screen.manufacturer.return_value = "MSI"
            screen.serialNumber.return_value = "unique-serial"
            backend = Mock()
            backend.displays.return_value = [("/display0", "MSI G241")]
            backend.read.side_effect = [72, 0]
            started = threading.Event()
            release = threading.Event()

            def set_brightness(_path, value):
                if value == 0:
                    started.set()
                    release.wait(3)

            backend.set.side_effect = set_brightness
            loop = QEventLoop()
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            with patch("screenmask.brightness_async.BrightnessManager",
                       side_effect=lambda worker_settings: BrightnessManager(worker_settings, backend)):
                service = AsyncBrightness(settings)
                service.set_screens([screen])
                service.drained.connect(loop.quit)
                service.lower(screen, [screen])
                self.assertTrue(started.wait(2))
                service.restore(screen_id(screen))
                service.finish()
                release.set()
                timer.start(5000)
                loop.exec()
                self.assertTrue(timer.isActive(), "brightness worker did not finish")
                timer.stop()
                self.assertEqual([call.args for call in backend.set.call_args_list],
                                 [("/display0", 0), ("/display0", 72)])
                self.assertEqual(settings.brightness_recovery(), {})

    def test_queued_work_rechecks_connected_display_before_dimming(self):
        """A replacement monitor is not dimmed after a slow detection call."""
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat))
            screen = Mock()
            screen.name.return_value = "DP-1"
            screen.model.return_value = "G241"
            screen.manufacturer.return_value = "MSI"
            screen.serialNumber.return_value = "original"
            replacement = Mock()
            replacement.name.return_value = "DP-1"
            replacement.model.return_value = "G241"
            replacement.manufacturer.return_value = "MSI"
            replacement.serialNumber.return_value = "replacement"
            backend = Mock()
            started = threading.Event()
            release = threading.Event()

            def displays():
                started.set()
                release.wait(3)
                return [("/display0", "MSI G241")]

            backend.displays.side_effect = displays
            backend.read.return_value = 72
            loop = QEventLoop()
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            with patch("screenmask.brightness_async.BrightnessManager",
                       side_effect=lambda worker_settings: BrightnessManager(worker_settings, backend)):
                service = AsyncBrightness(settings)
                errors = []
                error_threads = []
                gui_thread = threading.get_ident()
                service.errors.connect(lambda messages: (errors.extend(messages), error_threads.append(threading.get_ident())))
                service.drained.connect(loop.quit)
                service.lower(screen, [screen])
                self.assertTrue(started.wait(2))
                service.set_screens([replacement])
                service.finish()
                release.set()
                timer.start(5000)
                loop.exec()
                self.assertTrue(timer.isActive(), "brightness worker did not finish")
                timer.stop()
                self.assertTrue(errors)
                self.assertEqual(error_threads, [gui_thread])
                backend.set.assert_not_called()


if __name__ == "__main__":
    unittest.main()
