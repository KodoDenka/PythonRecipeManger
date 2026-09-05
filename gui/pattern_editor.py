"""Sword-pattern editor (PySide6): paintable 3x3 grids, per version, with tier overrides.

A **Template set** selector chooses what you're editing: the version's *Base* grids (used by
every tier by default) or a specific *tier*'s overrides. Editing a tier's grid creates an
override for just that (tier, sword); overridden swords are marked, and *Reset to base* drops
the override. The backing :class:`core.patterns_model.PatternsModel` keeps both the base file
and the per-tier override file in the shape the generator reads.
"""

from typing import Callable

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QComboBox, QButtonGroup, QGroupBox, QInputDialog, QMessageBox,
)

from core.patterns_model import PatternsModel, GRID, EMPTY

CELL_INFO = {
    EMPTY: ("·", "#e6e6e6", "#999999"),
    "H":   ("H", "#8d6e63", "#ffffff"),
    "M":   ("M", "#4f79c7", "#ffffff"),
    "B":   ("B", "#e08a2b", "#ffffff"),
}
BRUSHES = ((EMPTY, "Empty"), ("H", "Handle"), ("M", "Material"), ("B", "Binder"))
_SWORD_ROLE = Qt.UserRole
_BASE_LABEL = "Base (all tiers)"


def _cell_style(char: str) -> str:
    _, bg, fg = CELL_INFO[char]
    return (f"background:{bg}; color:{fg}; border:1px solid #00000033;"
            f"border-radius:6px; font-weight:bold; font-size:20px;")


class PatternEditor(QWidget):
    statusMessage = Signal(str)
    dirtyChanged = Signal(bool)

    def __init__(self, model: PatternsModel,
                 get_tier_names: Callable[[], list[str]], parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._get_tier_names = get_tier_names
        self._brush = "M"
        self._cells: list[list[QPushButton]] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._build_list_panel())
        layout.addWidget(self._build_grid_panel(), 1)
        self.reload()

    # --- construction ---------------------------------------------------------

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)

        v.addWidget(QLabel("<b>Template set</b>"))
        self._set_combo = QComboBox()
        self._set_combo.currentIndexChanged.connect(self._on_set_changed)
        v.addWidget(self._set_combo)

        v.addWidget(QLabel("<b>Sword</b>"))
        self._list = QListWidget()
        self._list.currentItemChanged.connect(lambda *_: self._refresh_grid())
        v.addWidget(self._list, 1)

        row = QHBoxLayout()
        for text, slot in (("Add…", self._on_add), ("Rename…", self._on_rename),
                           ("Delete", self._on_delete)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        v.addLayout(row)
        panel.setMaximumWidth(260)
        return panel

    def _build_grid_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)

        pal_box = QGroupBox("Brush")
        pal = QHBoxLayout(pal_box)
        self._brush_group = QButtonGroup(self)
        self._brush_group.setExclusive(True)
        for char, name in BRUSHES:
            label, bg, fg = CELL_INFO[char]
            btn = QPushButton(f"{label}  {name}")
            btn.setCheckable(True)
            btn.setStyleSheet(f"QPushButton{{padding:6px 10px;}}"
                              f"QPushButton:checked{{background:{bg}; color:{fg};"
                              f"font-weight:bold; border-radius:4px;}}")
            btn.clicked.connect(lambda _c=False, ch=char: self._set_brush(ch))
            self._brush_group.addButton(btn)
            pal.addWidget(btn)
            if char == self._brush:
                btn.setChecked(True)
        pal.addStretch(1)
        v.addWidget(pal_box)

        self._grid_title = QLabel()
        v.addWidget(self._grid_title)

        grid_wrap = QGridLayout()
        grid_wrap.setSpacing(6)
        for r in range(GRID):
            row_cells = []
            for c in range(GRID):
                cell = QPushButton()
                cell.setFixedSize(QSize(60, 60))
                cell.clicked.connect(lambda _c=False, rr=r, cc=c: self._on_cell(rr, cc))
                grid_wrap.addWidget(cell, r, c)
                row_cells.append(cell)
            self._cells.append(row_cells)
        grid_holder = QWidget()
        grid_holder.setLayout(grid_wrap)
        v.addWidget(grid_holder, 0, Qt.AlignLeft)

        self._note = QLabel()
        self._note.setStyleSheet("color: gray;")
        v.addWidget(self._note)

        self._reset_btn = QPushButton("Reset this sword to base")
        self._reset_btn.clicked.connect(self._on_reset)
        v.addWidget(self._reset_btn)

        v.addStretch(1)
        self._save_btn = QPushButton("Save patterns")
        self._save_btn.clicked.connect(self.save)
        v.addWidget(self._save_btn)
        return panel

    # --- population -----------------------------------------------------------

    def reload(self) -> None:
        """Repopulate the template-set combo (Base + tiers) and sword list for the model."""
        self._set_combo.blockSignals(True)
        keep = self._set_combo.currentText()
        self._set_combo.clear()
        self._set_combo.addItem(_BASE_LABEL)
        self._set_combo.addItems(self._get_tier_names())
        idx = self._set_combo.findText(keep)
        self._set_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._set_combo.blockSignals(False)
        self._refresh_list()
        self._refresh_grid()
        self._emit_dirty()

    def _current_tier(self) -> str | None:
        return None if self._set_combo.currentIndex() <= 0 else self._set_combo.currentText()

    def _current_sword(self) -> str | None:
        item = self._list.currentItem()
        return item.data(_SWORD_ROLE) if item else None

    def _refresh_list(self) -> None:
        """Rebuild the sword list, marking overridden swords when a tier is selected."""
        tier = self._current_tier()
        prev = self._current_sword()
        self._list.blockSignals(True)
        self._list.clear()
        for sword in self._model.names():
            marked = tier is not None and self._model.is_overridden(tier, sword)
            item = QListWidgetItem(f"● {sword}" if marked else sword)
            item.setData(_SWORD_ROLE, sword)
            if marked:
                item.setToolTip("Overridden for this tier")
            self._list.addItem(item)
        self._list.blockSignals(False)
        # Restore selection.
        target = 0
        if prev is not None:
            for i in range(self._list.count()):
                if self._list.item(i).data(_SWORD_ROLE) == prev:
                    target = i
                    break
        if self._list.count():
            self._list.setCurrentRow(target)

    def _refresh_grid(self) -> None:
        tier = self._current_tier()
        sword = self._current_sword()
        rows = self._model.effective_grid(sword, tier) if sword else [EMPTY * GRID] * GRID
        for r in range(GRID):
            for c in range(GRID):
                ch = rows[r][c]
                cell = self._cells[r][c]
                cell.setText(CELL_INFO[ch][0])
                cell.setStyleSheet(_cell_style(ch))
                cell.setEnabled(sword is not None)
        overridden = bool(sword and tier and self._model.is_overridden(tier, sword))
        if sword is None:
            self._grid_title.setText("<i>No sword selected</i>")
        elif tier is None:
            self._grid_title.setText(f"<b>{sword}</b> · base")
        else:
            tag = "override" if overridden else "inherits base"
            self._grid_title.setText(f"<b>{sword}</b> · tier <b>{tier}</b> ({tag})")
        self._reset_btn.setEnabled(overridden)
        self._refresh_note(sword, tier)

    def _refresh_note(self, sword, tier) -> None:
        if not sword:
            self._note.setText("")
            return
        binder = self._model.uses_binder(sword, tier)
        base = "Uses binder (B)." if binder else "No binder."
        if tier is not None and not self._model.is_overridden(tier, sword):
            self._note.setText(f"{base}  Editing will create a {tier} override from this base grid.")
        else:
            self._note.setText(base)

    # --- actions --------------------------------------------------------------

    def _on_set_changed(self, _idx: int) -> None:
        self._refresh_list()
        self._refresh_grid()

    def _set_brush(self, char: str) -> None:
        self._brush = char

    def _on_cell(self, row: int, col: int) -> None:
        sword = self._current_sword()
        if sword is None:
            return
        tier = self._current_tier()
        was_overridden = tier is not None and self._model.is_overridden(tier, sword)
        self._model.set_cell(sword, row, col, self._brush, tier=tier)
        # If a new override just appeared, refresh the list marker for it.
        if tier is not None and not was_overridden:
            self._refresh_list()
        self._refresh_grid()
        self._emit_dirty()

    def _on_reset(self) -> None:
        sword = self._current_sword()
        tier = self._current_tier()
        if sword is None or tier is None:
            return
        self._model.reset_override(tier, sword)
        self._refresh_list()
        self._refresh_grid()
        self._emit_dirty()
        self.statusMessage.emit(f"Reset {tier}/{sword} to the base template.")

    def _on_add(self) -> None:
        name, ok = QInputDialog.getText(self, "Add sword", "New sword name (lowercase):")
        name = name.strip()
        if not ok or not name:
            return
        try:
            self._model.add(name)
        except ValueError as e:
            QMessageBox.warning(self, "Add sword", str(e))
            return
        self._refresh_list()
        for i in range(self._list.count()):
            if self._list.item(i).data(_SWORD_ROLE) == name:
                self._list.setCurrentRow(i)
                break
        self._emit_dirty()
        self.statusMessage.emit(f"Added sword '{name}'.")

    def _on_rename(self) -> None:
        old = self._current_sword()
        if old is None:
            return
        new, ok = QInputDialog.getText(self, "Rename sword", "New name:", text=old)
        new = new.strip()
        if not ok or not new or new == old:
            return
        try:
            self._model.rename(old, new)
        except ValueError as e:
            QMessageBox.warning(self, "Rename sword", str(e))
            return
        self._refresh_list()
        self._emit_dirty()
        self.statusMessage.emit(f"Renamed '{old}' → '{new}'.")

    def _on_delete(self) -> None:
        sword = self._current_sword()
        if sword is None:
            return
        if QMessageBox.question(self, "Delete sword",
                                f"Delete sword '{sword}' (and any tier overrides of it)?"
                                ) != QMessageBox.Yes:
            return
        self._model.delete(sword)
        self._refresh_list()
        self._refresh_grid()
        self._emit_dirty()
        self.statusMessage.emit(f"Deleted sword '{sword}'.")

    def save(self) -> None:
        self._model.save()
        self._emit_dirty()
        self.statusMessage.emit("Saved sword_patterns.json and tier_patterns.json.")

    def _emit_dirty(self) -> None:
        self._save_btn.setEnabled(self._model.dirty)
        self.dirtyChanged.emit(self._model.dirty)
