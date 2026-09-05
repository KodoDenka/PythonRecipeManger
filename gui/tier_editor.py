"""Tier editor (PySide6): pick a tier and assign catalog items/tags to its slots.

The heavy lifting (key reuse/creation, tiers.json/keys.json shape) lives in
:class:`core.tiers_model.TiersModel`; this widget is just the controls. It pulls the
currently-selected catalog item via a callback supplied by the main window, so it stays
decoupled from the catalog list.
"""

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QPushButton,
    QLabel, QGroupBox, QInputDialog, QMessageBox,
)

from core.tiers_model import TiersModel, SLOTS
from catalog.jar_loader import ItemEntry


class TierEditor(QWidget):
    """Edit one tier's mod_id + material/handle/binder ingredients."""

    statusMessage = Signal(str)
    dirtyChanged = Signal(bool)

    def __init__(self, model: TiersModel,
                 get_selected_item: Callable[[], ItemEntry | None], parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._get_selected = get_selected_item
        self._slot_value_labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- tier selection row ---
        top = QHBoxLayout()
        top.addWidget(QLabel("Tier:"))
        self._tier_combo = QComboBox()
        self._tier_combo.currentTextChanged.connect(self._on_tier_changed)
        top.addWidget(self._tier_combo, 1)
        add_btn = QPushButton("Add…")
        add_btn.clicked.connect(self._on_add_tier)
        top.addWidget(add_btn)
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self._on_delete_tier)
        top.addWidget(del_btn)
        layout.addLayout(top)

        # --- mod_id ---
        form = QFormLayout()
        self._mod_combo = QComboBox()
        self._mod_combo.setEditable(True)
        self._mod_combo.currentTextChanged.connect(self._on_mod_changed)
        form.addRow("mod_id:", self._mod_combo)
        layout.addLayout(form)

        # --- slots ---
        slots_box = QGroupBox("Ingredients")
        slots_layout = QVBoxLayout(slots_box)
        for slot in SLOTS:
            row = QHBoxLayout()
            row.addWidget(QLabel(slot.capitalize() + ":"), 0)
            value = QLabel("—")
            value.setStyleSheet("font-family: monospace;")
            self._slot_value_labels[slot] = value
            row.addWidget(value, 1)
            assign = QPushButton("← Assign selected item")
            assign.clicked.connect(lambda _=False, s=slot: self._assign_item(s))
            row.addWidget(assign)
            tag = QPushButton("Tag…")
            tag.clicked.connect(lambda _=False, s=slot: self._assign_tag(s))
            row.addWidget(tag)
            slots_layout.addLayout(row)
        layout.addWidget(slots_box)

        self._save_btn = QPushButton("Save tiers.json / keys.json")
        self._save_btn.clicked.connect(self.save)
        layout.addWidget(self._save_btn)

        self.reload()

    # --- population -----------------------------------------------------------

    def reload(self) -> None:
        """Repopulate combos from the model (call after load or external change)."""
        self._tier_combo.blockSignals(True)
        self._mod_combo.blockSignals(True)
        self._tier_combo.clear()
        self._tier_combo.addItems(self._model.tier_names())
        self._mod_combo.clear()
        self._mod_combo.addItems(self._model.mod_ids())
        self._tier_combo.blockSignals(False)
        self._mod_combo.blockSignals(False)
        self._refresh_slots()
        self._emit_dirty()

    def _current_tier(self) -> str | None:
        return self._tier_combo.currentText() or None

    def _refresh_slots(self) -> None:
        tier = self._current_tier()
        if tier is None:
            for lbl in self._slot_value_labels.values():
                lbl.setText("—")
            return
        self._mod_combo.blockSignals(True)
        self._mod_combo.setCurrentText(self._model.tier_mod_id(tier))
        self._mod_combo.blockSignals(False)
        for slot, lbl in self._slot_value_labels.items():
            ing = self._model.slot_ingredient(tier, slot)
            if ing is None:
                key = self._model.slot_key_name(tier, slot)
                lbl.setText(f"⚠ unset ({key})" if key else "⚠ unset")
            else:
                prefix, value = ing
                lbl.setText(f"[{prefix}] {value}")

    # --- actions --------------------------------------------------------------

    def _on_tier_changed(self, _text: str) -> None:
        self._refresh_slots()

    def _on_mod_changed(self, text: str) -> None:
        tier = self._current_tier()
        if tier is not None and text != self._model.tier_mod_id(tier):
            self._model.set_mod_id(tier, text)
            self._emit_dirty()

    def _assign_item(self, slot: str) -> None:
        tier = self._current_tier()
        if tier is None:
            return
        entry = self._get_selected()
        if entry is None:
            self.statusMessage.emit("Select an item in the catalog first.")
            return
        self._model.set_slot(tier, slot, "item", entry.id)
        self._refresh_slots()
        self._emit_dirty()
        self.statusMessage.emit(f"{tier}.{slot} = {entry.id}")

    def _assign_tag(self, slot: str) -> None:
        tier = self._current_tier()
        if tier is None:
            return
        current = self._model.slot_ingredient(tier, slot)
        default = current[1] if current and current[0] == "tag" else "c:"
        value, ok = QInputDialog.getText(
            self, "Assign tag", "Tag id (e.g. c:wood_sticks):", text=default)
        value = value.strip()
        if not ok or not value:
            return
        self._model.set_slot(tier, slot, "tag", value)
        self._refresh_slots()
        self._emit_dirty()
        self.statusMessage.emit(f"{tier}.{slot} = tag {value}")

    def _on_add_tier(self) -> None:
        name, ok = QInputDialog.getText(self, "Add tier", "New tier name (lowercase):")
        name = name.strip()
        if not ok or not name:
            return
        mod_id = self._mod_combo.currentText() or (self._model.mod_ids()[0]
                                                   if self._model.mod_ids() else "")
        try:
            self._model.add_tier(name, mod_id)
        except ValueError as e:
            QMessageBox.warning(self, "Add tier", str(e))
            return
        self.reload()
        self._tier_combo.setCurrentText(name)
        self.statusMessage.emit(f"Added tier '{name}' — now pick its material.")

    def _on_delete_tier(self) -> None:
        tier = self._current_tier()
        if tier is None:
            return
        if QMessageBox.question(self, "Delete tier",
                                f"Delete tier '{tier}'?") != QMessageBox.Yes:
            return
        self._model.delete_tier(tier)
        self.reload()
        self.statusMessage.emit(f"Deleted tier '{tier}'.")

    def save(self) -> None:
        self._model.save()
        self._emit_dirty()
        self.statusMessage.emit("Saved tiers.json and keys.json.")

    def _emit_dirty(self) -> None:
        self._save_btn.setEnabled(self._model.dirty)
        self.dirtyChanged.emit(self._model.dirty)
