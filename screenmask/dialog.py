"""Provide the display and mask-color settings dialog."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QDialog, QDialogButtonBox, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .displays import screen_id, screen_label


class SettingsDialog(QDialog):
    """Edit saved display selections and the mask color.

    Attributes:
        identify_requested (Signal): Requests numbered display overlays.
    """
    identify_requested = Signal()

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
        layout.addWidget(identify, alignment=Qt.AlignmentFlag.AlignLeft)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Mask color:"))
        self.color_button = QPushButton()
        self.color_button.clicked.connect(self.choose_color)
        color_row.addWidget(self.color_button)
        color_row.addStretch()
        layout.addLayout(color_row)
        self.update_color_button()

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
            self.display_layout.insertWidget(self.display_layout.count() - 1, checkbox)
            self.checkboxes[key] = checkbox

    def update_color_button(self):
        """Update the color button's label and contrasting preview."""
        self.color_button.setText(self.color.name())
        self.color_button.setStyleSheet(f"background-color: {self.color.name()}; color: {'black' if self.color.lightness() > 140 else 'white'};")

    def choose_color(self):
        """Open the color picker and retain a valid selection."""
        color = QColorDialog.getColor(self.color, self, "Choose Mask Color")
        if color.isValid():
            self.color = color
            self.update_color_button()

    def save(self):
        """Persist the color and display choices, then accept the dialog."""
        selected = self.saved_ids - set(self.checkboxes)
        selected |= {key for key, checkbox in self.checkboxes.items() if checkbox.isChecked()}
        self.settings.save(sorted(selected), self.color)
        self.accept()
