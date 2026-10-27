#!/bin/sh
set -eu

data_dir=${XDG_DATA_HOME:-"$HOME/.local/share"}
rm -f "$data_dir/applications/org.screenmask.ScreenMask.desktop"
rm -f "$data_dir/icons/hicolor/scalable/apps/org.screenmask.ScreenMask.svg"
rm -rf "$data_dir/screenmask"
if command -v update-desktop-database >/dev/null 2>&1 && [ -d "$data_dir/applications" ]; then
    update-desktop-database "$data_dir/applications"
fi
printf '%s\n' 'ScreenMask uninstalled. Saved preferences were retained.'
