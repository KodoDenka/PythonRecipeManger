"""Searchable item grid (PySide6).

The catalog is shown as a grid of icons (no labels) to stay compact; the name and id of
the item under the cursor are revealed in a caption below when it is selected, and on
hover as a tooltip. Items whose jar had no flat texture get a neutral placeholder tile.
"""

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QLabel,
)

from catalog.cache import Catalog
from catalog.jar_loader import ItemEntry

_ENTRY_ROLE = Qt.UserRole
_ICON_PX = 40
_CELL_PX = 54


def _placeholder_icon() -> QIcon:
    """A neutral tile for items with no texture, so grid cells stay visible."""
    pm = QPixmap(_ICON_PX, _ICON_PX)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#d0d0d0"))
    p.setPen(QPen(QColor("#00000033")))
    p.drawRoundedRect(4, 4, _ICON_PX - 8, _ICON_PX - 8, 6, 6)
    p.setPen(QColor("#888888"))
    p.drawText(pm.rect(), Qt.AlignCenter, "?")
    p.end()
    return QIcon(pm)


class CatalogView(QWidget):
    """Filter box + icon grid. Emits :attr:`selectionChanged` with the current entry."""

    selectionChanged = Signal(object)  # ItemEntry or None

    def __init__(self, catalog: Catalog, parent=None) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self._placeholder = _placeholder_icon()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search items by name or id…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self.refresh)
        layout.addWidget(self._search)

        self._count = QLabel()
        self._count.setStyleSheet("color: gray;")
        layout.addWidget(self._count)

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.IconMode)
        self._list.setResizeMode(QListWidget.Adjust)
        self._list.setMovement(QListWidget.Static)
        self._list.setUniformItemSizes(True)
        self._list.setSpacing(2)
        self._list.setIconSize(QSize(_ICON_PX, _ICON_PX))
        self._list.setGridSize(QSize(_CELL_PX, _CELL_PX))
        self._list.currentItemChanged.connect(self._on_current_changed)
        layout.addWidget(self._list, 1)

        # Caption: reveals the selected item's name/id (the "name on click").
        self._caption = QLabel("Click an item to see its name.")
        self._caption.setWordWrap(True)
        self._caption.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._caption.setStyleSheet("padding:4px; font-family:monospace;")
        layout.addWidget(self._caption)

        self.refresh()

    def refresh(self) -> None:
        """Rebuild the visible grid from the catalog and current search text."""
        self._list.clear()
        results = self._catalog.search(self._search.text())
        for entry in results:
            item = QListWidgetItem()  # no text — icon-only grid
            item.setData(_ENTRY_ROLE, entry)
            item.setToolTip(f"{entry.display_name}\n{entry.id}")
            icon_path = self._catalog.icon_abs_path(entry)
            item.setIcon(QIcon(icon_path) if icon_path else self._placeholder)
            self._list.addItem(item)
        total = len(self._catalog.items)
        self._count.setText(
            f"{len(results)} shown / {total} items" if total else
            "No items yet — drop .jar files onto the window or use ‘Add jars…’.")

    def current_item(self) -> ItemEntry | None:
        item = self._list.currentItem()
        return item.data(_ENTRY_ROLE) if item else None

    def _on_current_changed(self, current, _previous) -> None:
        entry = current.data(_ENTRY_ROLE) if current else None
        if entry is None:
            self._caption.setText("Click an item to see its name.")
        else:
            self._caption.setText(f"{entry.display_name}\n{entry.id}")
        self.selectionChanged.emit(entry)
