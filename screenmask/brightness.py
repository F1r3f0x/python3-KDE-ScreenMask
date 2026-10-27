# Author: Patricio Labin Correa <plabin@outlook.cl>
"""Lower and restore individual display brightness through KDE PowerDevil."""

import shlex
import subprocess

from .displays import monitor_identity, screen_id

SERVICE = "org.kde.ScreenBrightness"
ROOT = "/org/kde/ScreenBrightness"
DISPLAY_INTERFACE = "org.kde.ScreenBrightness.Display"


class BrightnessError(RuntimeError):
    """Indicate that a display's brightness could not be controlled safely."""


class PowerDevilBackend:
    """Read and set per-display brightness using the user's D-Bus service."""

    def _run(self, *args):
        """Run a busctl command and return its output.

        Args:
            *args (str): Arguments following ``busctl --user``.

        Returns:
            str: Standard output from the command.

        Raises:
            BrightnessError: If the bus or brightness service is unavailable.
        """
        try:
            result = subprocess.run(["busctl", "--user", "--no-pager", *args],
                                    capture_output=True, text=True, timeout=4, check=True)
        except (OSError, subprocess.SubprocessError) as error:
            raise BrightnessError("KDE per-display brightness control is unavailable.") from error
        return result.stdout.strip()

    def _property(self, path, interface, name):
        """Read a single D-Bus property in busctl's terse format.

        Args:
            path (str): D-Bus object path.
            interface (str): D-Bus interface name.
            name (str): Property name.

        Returns:
            list[str]: Parsed type and value tokens.
        """
        try:
            return shlex.split(self._run("get-property", SERVICE, path, interface, name))
        except ValueError as error:
            raise BrightnessError("KDE returned an unreadable brightness response.") from error

    def displays(self):
        """List controllable displays and their user-visible labels.

        Returns:
            list[tuple[str, str]]: Pairs of D-Bus object path and display label.
        """
        tokens = self._property(ROOT, SERVICE, "DisplaysDBusNames")
        try:
            if tokens[0] != "as" or int(tokens[1]) != len(tokens[2:]):
                raise ValueError
            names = tokens[2:]
        except (IndexError, ValueError) as error:
            raise BrightnessError("KDE returned an invalid display list.") from error
        displays = []
        for name in names:
            if not name.replace("_", "").isalnum():
                continue
            path = f"{ROOT}/{name}"
            label = self._property(path, DISPLAY_INTERFACE, "Label")
            if len(label) == 2 and label[0] == "s":
                displays.append((path, label[1]))
        return displays

    def read(self, path):
        """Read the brightness of a KDE display object.

        Args:
            path (str): Display's D-Bus object path.

        Returns:
            int: Current brightness in the display's native range.
        """
        tokens = self._property(path, DISPLAY_INTERFACE, "Brightness")
        try:
            if len(tokens) != 2 or tokens[0] != "i":
                raise ValueError
            return int(tokens[1])
        except ValueError as error:
            raise BrightnessError("KDE returned an invalid brightness value.") from error

    def set(self, path, value):
        """Set display brightness without showing KDE's brightness indicator.

        Args:
            path (str): Display's D-Bus object path.
            value (int): Requested brightness in the display's native range.
        """
        self._run("call", SERVICE, path, DISPLAY_INTERFACE, "SetBrightness", "iu", str(value), "1")


def _matches(screen, label):
    """Check whether a KDE brightness label identifies a Qt screen.

    Args:
        screen (QScreen): Display to match.
        label (str): User-visible label from PowerDevil.

    Returns:
        bool: Whether the label matches the display model or connector.
    """
    label = " ".join(label.casefold().split())
    model = " ".join(screen.model().casefold().split())
    connector = screen.name().casefold()
    if model and model in label:
        return True
    if connector and connector == label:
        return True
    return connector.startswith(("edp-", "lvds-")) and label == "built-in screen"


def _connected(screens):
    """Resolve either a display snapshot list or a live snapshot provider."""
    return list(screens() if callable(screens) else screens)


class BrightnessManager:
    """Track and restore the brightness of displays lowered by ScreenMask."""

    def __init__(self, settings, backend=None):
        """Load pending recovery records and initialize the KDE backend.

        Args:
            settings (Settings): Persistent preferences and recovery store.
            backend (PowerDevilBackend | None): Optional brightness backend.
        """
        self.settings = settings
        self.backend = backend if backend is not None else PowerDevilBackend()
        self.pending = settings.brightness_recovery()

    def lower(self, screen, screens, should_apply=lambda: True):
        """Save and lower one display's brightness when it can be identified.

        Args:
            screen (QScreen): Display to dim.
            screens (Iterable[QScreen]): Connected displays, used to detect ambiguity.
            should_apply (Callable[[], bool]): Whether dimming is still requested.

        Raises:
            BrightnessError: If the matching display or brightness is unavailable.
        """
        key = screen_id(screen)
        if not should_apply():
            return
        if key in self.pending:
            record = self.pending[key]
            self._verify_screen(key, record.get("identity"), record.get("label", "the display"), screens)
            return
        screens_now = _connected(screens)
        physical_id = monitor_identity(screen)
        if physical_id is None:
            raise BrightnessError(f"Cannot verify the identity of {screen.name()} for brightness recovery.")
        displays = self.backend.displays()
        matches = [(path, label) for path, label in displays if _matches(screen, label)]
        if len(matches) != 1 or sum(_matches(other, matches[0][1]) for other in screens_now) != 1:
            raise BrightnessError(f"Cannot uniquely identify brightness control for {screen.name()}.")
        path, label = matches[0]
        original = self.backend.read(path)
        if not should_apply():
            return
        self._verify_screen(key, physical_id, label, screens)
        self.pending[key] = {"label": label, "brightness": original, "identity": physical_id}
        try:
            self.settings.save_brightness_recovery(self.pending)
        except OSError:
            del self.pending[key]
            raise
        if not should_apply():
            del self.pending[key]
            self.settings.save_brightness_recovery(self.pending)
            return
        self.backend.set(path, 0)

    def _verify_screen(self, key, identity, label, screens):
        """Ensure the recorded physical monitor is still connected uniquely."""
        current = _connected(screens)
        matching = [screen for screen in current if screen_id(screen) == key]
        if (not identity or len(matching) != 1 or monitor_identity(matching[0]) != identity
                or sum(_matches(screen, label) for screen in current) != 1):
            raise BrightnessError(f"Cannot verify the original display for {label}; brightness was not changed.")

    def restore(self, key, screens):
        """Restore a display's saved brightness if it is still at minimum.

        Args:
            key (str): Display identifier returned by ``screen_id``.
            screens: Connected display snapshots or a provider returning them.

        Raises:
            BrightnessError: If the display is unavailable or cannot be restored.
        """
        record = self.pending.get(key)
        if record is None:
            return
        self._verify_screen(key, record.get("identity"), record.get("label", "the display"), screens)
        matches = [path for path, label in self.backend.displays() if label == record.get("label")]
        if len(matches) != 1:
            raise BrightnessError(f"Cannot restore brightness for {record.get('label', 'the display')}: display unavailable or ambiguous.")
        path = matches[0]
        if self.backend.read(path) == 0:
            self._verify_screen(key, record.get("identity"), record.get("label", "the display"), screens)
            self.backend.set(path, int(record["brightness"]))
        del self.pending[key]
        self.settings.save_brightness_recovery(self.pending)

    def restore_all(self, screens):
        """Try to restore all saved brightness values, retaining failures.

        Returns:
            list[str]: Messages for displays that could not be restored.
        """
        errors = []
        for key in list(self.pending):
            try:
                self.restore(key, screens)
            except BrightnessError as error:
                errors.append(str(error))
        return errors
