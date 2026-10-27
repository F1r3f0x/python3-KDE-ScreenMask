"""Provide the display and mask-color settings dialog."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QDialog, QDialogButtonBox, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .displays import screen_id, screen_label


class SettingsDialog(QDialog):
    """Edit saved display selections and the mask color.

    Attributes:
        identify_requested (Signal): Requests numbered display overlays.
        toggle_requested (Signal): Requests showing or hiding masks.
    """
    identify_requested = Signal()
    toggle_requested = Signal()

    def __init__(self, settings, screens, parent=None):
        """Build the settings dialog for the currently connected displays.

        Args:
            settings (Settings): Persistent settings to edit.
            screens (Iterable[QScreen]): Currently connected displays.
            parent (QWidget | None): Optional parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("ScreenMask Settings")
        self.settings = settings
        self.color = settings.color
        self.checkboxes = {}
        self.saved_ids = set(settings.selected)
        self.masks_visible = False
        self.resize(480, 350)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose the displays to cover:"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        contents = QWidget()
        self.display_layout = QVBoxLayout(contents)
        self.display_layout.addStretch()
        scroll.setWidget(contents)
        layout.addWidget(scroll)

        identify = QPushButton("Identify Displays")
        identify.clicked.connect(self.identify_requested.emit)
        self.toggle_button = QPushButton("Show Masks")
        self.toggle_button.setToolTip("Showing masks saves the current settings.")
        self.toggle_button.clicked.connect(self.toggle_requested.emit)
        actions = QHBoxLayout()
        actions.addWidget(identify)
        actions.addWidget(self.toggle_button)
        actions.addStretch()
        layout.addLayout(actions)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Mask color:"))
        self.preset_buttons = {}
        for name, value in (("Black", "#000000"), ("White", "#ffffff"),
                            ("Red", "#ff0000"), ("Green", "#00ff00"),
                            ("Blue", "#0000ff")):
            button = QPushButton()
            button.setFixedSize(24, 24)
            button.setToolTip(name)
            button.setAccessibleName(name)
            button.setStyleSheet(f"background-color: {value}; border: 1px solid #808080;")
            button.clicked.connect(lambda checked=False, value=value: self.set_color(QColor(value)))
            color_row.addWidget(button)
            self.preset_buttons[name] = button
        self.color_button = QPushButton()
        self.color_button.clicked.connect(self.choose_color)
        color_row.addWidget(self.color_button)
        color_row.addStretch()
        layout.addLayout(color_row)
        self.update_color_button()

        self.brightness_checkbox = QCheckBox("Lower brightness to minimum while masked")
        self.brightness_checkbox.setChecked(settings.lower_brightness)
        self.brightness_checkbox.setToolTip("Requires per-display brightness control in KDE. Previous brightness is restored when the mask is dismissed.")
        layout.addWidget(self.brightness_checkbox)
        self.avoid_panels_checkbox = QCheckBox("Keep KDE panels visible")
        self.avoid_panels_checkbox.setChecked(settings.avoid_panels)
        layout.addWidget(self.avoid_panels_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh_screens(screens)

    def refresh_screens(self, screens):
        """Rebuild display choices while preserving current selections.

        Args:
            screens (Iterable[QScreen]): Currently connected displays.
        """
        selected = {key for key, checkbox in self.checkboxes.items() if checkbox.isChecked()}
        if not self.checkboxes:
            selected = self.saved_ids.copy()
        else:
            # Retain the state of displays that disappeared during editing.
            selected |= self.saved_ids - set(self.checkboxes)
        self.saved_ids = selected
        for checkbox in self.checkboxes.values():
            self.display_layout.removeWidget(checkbox)
            checkbox.deleteLater()
        self.checkboxes = {}
        for index, screen in enumerate(screens, 1):
            key = screen_id(screen)
            checkbox = QCheckBox(screen_label(screen, index))
            checkbox.setChecked(key in selected)
            checkbox.toggled.connect(self.update_toggle_button)
            self.display_layout.insertWidget(self.display_layout.count() - 1, checkbox)
            self.checkboxes[key] = checkbox
        self.update_toggle_button()

    def set_masks_visible(self, visible):
        """Update the toggle button to reflect the current masks.

        Args:
            visible (bool): Whether at least one mask is visible.
        """
        self.masks_visible = visible
        self.update_toggle_button()

    def update_toggle_button(self):
        """Show the next toggle action and disable it without a display."""
        self.toggle_button.setText("Hide Masks" if self.masks_visible else "Show Masks")
        self.toggle_button.setEnabled(self.masks_visible or any(
            checkbox.isChecked() for checkbox in self.checkboxes.values()))

    def update_color_button(self):
        """Update the color button's label and contrasting preview."""
        self.color_button.setText(self.color.name())
        self.color_button.setStyleSheet(f"background-color: {self.color.name()}; color: {'black' if self.color.lightness() > 140 else 'white'};")

    def choose_color(self):
        """Open the color picker and retain a valid selection."""
        color = QColorDialog.getColor(self.color, self, "Choose Mask Color")
        if color.isValid():
            self.set_color(color)

    def set_color(self, color):
        """Select a preset or custom color and refresh its preview.

        Args:
            color (QColor): Color to use for the mask.
        """
        self.color = color
        self.update_color_button()

    def save(self):
        """Persist the color and display choices, then accept the dialog."""
        self.persist()
        self.accept()

    def persist(self):
        """Save the current selections and options without closing the dialog."""
        selected = self.saved_ids - set(self.checkboxes)
        selected |= {key for key, checkbox in self.checkboxes.items() if checkbox.isChecked()}
        self.settings.save(sorted(selected), self.color,
                           self.brightness_checkbox.isChecked(),
                           self.avoid_panels_checkbox.isChecked())
        self.saved_ids = selected
