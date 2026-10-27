#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
data_dir=${XDG_DATA_HOME:-"$HOME/.local/share"}
app_dir="$data_dir/screenmask"
applications_dir="$data_dir/applications"
icons_dir="$data_dir/icons/hicolor/scalable/apps"

mkdir -p "$app_dir" "$applications_dir" "$icons_dir"
# Build in a simple temporary path. Some setuptools versions interpret dollar
# signs in a virtualenv's path as variables while building a wheel.
build_dir=$(mktemp -d /tmp/screenmask-build.XXXXXX)
trap 'rm -rf "$build_dir"' EXIT HUP INT TERM
python3 -m venv --system-site-packages "$build_dir/venv"
"$build_dir/venv/bin/python" -m pip wheel --no-build-isolation --no-deps --wheel-dir "$build_dir/wheels" "$project_dir"
python3 -m venv --system-site-packages "$app_dir/venv"
"$app_dir/venv/bin/python" -m pip install --no-deps --force-reinstall "$build_dir"/wheels/*.whl
if ! "$app_dir/venv/bin/python" -c 'import PySide6' 2>/dev/null; then
    "$app_dir/venv/bin/python" -m pip install 'PySide6>=6.4'
fi
cp "$project_dir/assets/org.screenmask.ScreenMask.svg" "$icons_dir/org.screenmask.ScreenMask.svg"
"$app_dir/venv/bin/python" - "$applications_dir/org.screenmask.ScreenMask.desktop" "$app_dir/venv/bin/python" <<'PY'
import sys

desktop, executable = sys.argv[1:]
# Escape a quoted Exec argument as required by the desktop entry specification.
executable = executable.replace("%", "%%")
for character in ('\\', '"', '`', '$'):
    executable = executable.replace(character, '\\' + character)
# Desktop entry values have their own escaping before Exec is parsed.
executable = executable.replace('\\', '\\\\')
with open(desktop, "w", encoding="utf-8") as output:
    output.write("[Desktop Entry]\nType=Application\nName=ScreenMask\n")
    output.write("Comment=Cover selected displays with a solid color\n")
    # Invoke Python directly: generated script wrappers may expand a dollar
    # sign in the virtualenv path when run by a shell.
    output.write(f'Exec="{executable}" -m screenmask\n')
    output.write("Icon=org.screenmask.ScreenMask\nTerminal=false\nCategories=Utility;\n")
    output.write("StartupWMClass=org.screenmask.ScreenMask\n")
PY

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$applications_dir"
fi
printf '%s\n' 'ScreenMask installed. Find it in the application launcher and pin it to the panel.'
