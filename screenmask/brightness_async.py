# Author: Patricio Labin Correa <plabin@outlook.cl>
"""Serialize brightness operations outside Qt's user-interface thread."""

from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from PySide6.QtCore import QObject, QSettings, Signal

from .brightness import BrightnessError, BrightnessManager
from .displays import screen_id, snapshot_screen
from .settings import Settings


class AsyncBrightness(QObject):
    """Queue brightness work and deliver errors or completion to Qt.

    Attributes:
        errors (Signal): Messages from failed brightness operations.
        drained (Signal): Emitted when queued work has finished during shutdown.
    """

    errors = Signal(object)
    drained = Signal()

    def __init__(self, settings):
        """Create a serial worker using a thread-local settings backend.

        Args:
            settings (Settings): Settings describing the persistent store.
        """
        super().__init__()
        self._filename = settings.backend.fileName()
        self._format = settings.backend.format()
        self._pending_keys = set(settings.brightness_recovery())
        self._active_keys = set()
        self._screens = ()
        self._screen_lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="screenmask-brightness")
        self._manager = None
        self._closing = False

    def set_screens(self, screens, excluded=None):
        """Update immutable display snapshots from the UI thread.

        Args:
            screens (Iterable[QScreen]): Currently connected displays.
            excluded (str | None): Identifier to exclude during removal.
        """
        snapshots = tuple(snapshot_screen(screen) for screen in screens if screen_id(screen) != excluded)
        with self._screen_lock:
            self._screens = snapshots

    def _current_screens(self):
        """Return the latest immutable snapshots to a worker operation."""
        with self._screen_lock:
            return self._screens

    def _get_manager(self):
        """Create the manager and its QSettings on the worker thread."""
        if self._manager is None:
            backend = QSettings(self._filename, self._format)
            self._manager = BrightnessManager(Settings(backend))
        return self._manager

    def _submit(self, operation):
        """Queue an operation and report errors through the Qt event loop."""
        if self._closing:
            return

        def run():
            try:
                return operation(self._get_manager()) or []
            except BrightnessError as error:
                return [str(error)]
            except Exception as error:
                return [f"Brightness operation failed: {error}"]

        def finished(future):
            messages = future.result()
            if messages:
                self.errors.emit(messages)

        self._executor.submit(run).add_done_callback(finished)

    def lower(self, screen, screens):
        """Queue dimming for a display using the latest connected screens.

        Args:
            screen (QScreen): Display to dim.
            screens (Iterable[QScreen]): Connected displays.
        """
        self.set_screens(screens)
        target = snapshot_screen(screen)
        self._pending_keys.add(target.key)
        with self._screen_lock:
            self._active_keys.add(target.key)
        self._submit(lambda manager: manager.lower(target, self._current_screens,
                                                    lambda: self._is_active(target.key)))

    def _is_active(self, key):
        """Return whether brightness lowering is still requested for a display."""
        with self._screen_lock:
            return key in self._active_keys

    def restore(self, key):
        """Queue restoration of a display's previous brightness.

        Args:
            key (str): Display identifier.
        """
        with self._screen_lock:
            self._active_keys.discard(key)
        if key in self._pending_keys:
            self._submit(lambda manager: None if self._is_active(key)
                         else manager.restore(key, self._current_screens))

    def restore_all(self):
        """Queue recovery of all recorded brightness values."""
        with self._screen_lock:
            self._active_keys.clear()
        if self._pending_keys:
            self._submit(lambda manager: manager.restore_all(self._current_screens))

    def restore_unmasked(self, active_keys):
        """Retry recovery for displays without a visible mask.

        Args:
            active_keys (Iterable[str]): Identifiers of currently masked screens.
        """
        active = set(active_keys)

        def recover(manager):
            errors = []
            for key in set(manager.pending) - active:
                try:
                    manager.restore(key, self._current_screens)
                except BrightnessError as error:
                    errors.append(str(error))
            return errors

        if self._pending_keys:
            self._submit(recover)

    def finish(self):
        """Emit ``drained`` once every queued operation has completed."""
        if self._closing:
            return
        self._closing = True

        def finished(_future):
            self._executor.shutdown(wait=False)
            self.drained.emit()

        def dispose():
            self._manager = None

        self._executor.submit(dispose).add_done_callback(finished)
