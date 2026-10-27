# ScreenMask

ScreenMask covers selected displays with a solid color so you can focus on another screen. It is a Python and Qt application for KDE Plasma, with a panel launcher and system tray controls.

## Install

Requires Python 3.10 or newer, Python's `venv` and `pip` modules, and PySide6. On Wayland it also requires KDE's Layer Shell Qt QML module (`org.kde.layershell`) built for the same Qt version as PySide6. The installer uses an existing system PySide6 when available; otherwise it installs PySide6 into the application's virtual environment. It installs only for the current user.

```sh
./scripts/install.sh
```

Find **ScreenMask** in the application launcher, then right-click it and choose **Add to Panel** (the wording can vary with Plasma version). Launch it to choose displays and a color. Saving the initial settings shows the masks.

The installer creates a virtual environment in `$XDG_DATA_HOME/screenmask` (normally `~/.local/share/screenmask`), plus a desktop entry and the bundled ScreenMask icon in the corresponding standard directories. Python packaging tools such as `setuptools` and `wheel` need to be available to the virtual environment.

To update, quit ScreenMask from its tray menu, run `./scripts/install.sh` again, and relaunch it. Quitting first ensures the running process loads the updated code.

## Use

- Click the tray icon to toggle masks: if any are visible, all are dismissed; otherwise, masks are shown on selected connected displays.
- Use **Show Masks** or **Hide Masks** in the settings window to toggle them. Showing masks also saves the settings currently displayed.
- Launch ScreenMask again or choose **Show Masks** in its tray menu to restore masks on selected connected displays.
- Double-click a mask to dismiss that display's mask. Escape also dismisses a mask if that window has keyboard focus.
- Use the tray menu to dismiss every mask, open settings, or quit. The app stays in the tray after masks are dismissed.
- **Identify Displays** briefly displays a number on each screen. Numbers match the settings list.
- Use the color swatches for black, white, red, green, or blue, or choose a custom color.
- **Keep KDE panels visible** leaves reserved panel areas outside the mask. Auto-hidden panels may behave differently.
- **Lower brightness to minimum while masked** uses KDE's per-display brightness controls and `busctl`. The previous value is restored when the mask is dismissed; if a display cannot be matched or controlled, the mask still works and ScreenMask reports the issue. ScreenMask identifies a display using its connector and serial number or EDID fingerprint. After an interruption, reopening ScreenMask retries recovery when the identity matches. Identical monitors with identical EDIDs connected to the same port cannot be distinguished; records created by older versions without an identity require manual brightness adjustment. External monitors need supported and enabled brightness control in KDE; the minimum may still be visible.
- Saved displays that are disconnected are skipped; newly connected displays are not selected automatically. A display's connector and monitor information are used to recognize it, so changing its connector may require selecting it again. If a connector name is unavailable, its position and size are used as a fallback; changing the layout may require selecting that display again.

On systems without a tray, the settings window remains available while masks are active; closing it after dismissing the masks exits the app. ScreenMask does not automatically mask screens when you log in.

## Run from the checkout

With PySide6 installed for your Python interpreter:

```sh
python3 -m screenmask
```

## Uninstall

Quit ScreenMask, then run `./scripts/uninstall.sh`. Saved preferences are retained in Qt's user settings.

## Desktop behavior

On Wayland, the app uses KDE's layer-shell interface to cover the selected outputs without requesting keyboard focus. On X11, it requests fullscreen, always-on-top windows without activating them. Actual stacking and focus behavior are controlled by the window manager and may differ for games and exclusive fullscreen modes. Verify the behavior with your game and display setup; use the tray menu to recover if needed.

ScreenMask defaults to Qt Quick's software renderer to reduce graphics-driver memory use. Set `QT_QUICK_BACKEND` explicitly before starting the app to choose a different backend. For example, quit the running instance and launch the checkout with:

```sh
env QT_QUICK_BACKEND=rhi python3 -m screenmask
```

To compare memory usage between renderers, use the same masked displays and inspect `Pss` in `/proc/<pid>/smaps_rollup`; PSS accounts for shared library pages more accurately than RSS when comparing processes.

## Tests

```sh
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -v
```

To validate on KDE, select a secondary display, activate its mask, and check that it covers the whole screen while the primary display stays usable. Double-click the mask, then launch ScreenMask again and check that it returns without creating another tray icon. Check **Dismiss All**, unplug a masked display, and try the same workflow while your game is running. If displays use different scaling, check that both masks cover their displays. This live check is needed to establish how your particular compositor and game handle focus and stacking.

If a mask appears on the wrong display, quit ScreenMask and run `python3 -m screenmask.diagnose 2` from the checkout. This displays a blue test mask for six seconds and prints the Qt backend, requested display and reported window geometry. Replace `2` with another display number to test it.
