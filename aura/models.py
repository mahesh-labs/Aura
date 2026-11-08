"""A generic list model exposing dict rows to QML."""
from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal, Property


class DictModel(QAbstractListModel):
    countChanged = Signal()

    def __init__(self, roles: list[str], parent=None):
        super().__init__(parent)
        self._keys = {int(Qt.UserRole) + 1 + i: r for i, r in enumerate(roles)}
        self._items: list[dict] = []

    # --- Qt API
    def roleNames(self):
        return {k: v.encode() for k, v in self._keys.items()}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        key = self._keys.get(role)
        return self._items[index.row()].get(key) if key else None

    def _count(self) -> int:
        return len(self._items)

    count = Property(int, _count, notify=countChanged)

    # --- mutation helpers (main thread only)
    def set_items(self, items: list[dict]) -> None:
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()
        self.countChanged.emit()

    def append(self, item: dict) -> int:
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append(item)
        self.endInsertRows()
        self.countChanged.emit()
        return row

    def prepend(self, item: dict) -> None:
        self.beginInsertRows(QModelIndex(), 0, 0)
        self._items.insert(0, item)
        self.endInsertRows()
        self.countChanged.emit()

    def update(self, row: int, patch: dict) -> None:
        if 0 <= row < len(self._items):
            self._items[row].update(patch)
            ix = self.index(row)
            self.dataChanged.emit(ix, ix)

    def find(self, key: str, value) -> int:
        for i, it in enumerate(self._items):
            if it.get(key) == value:
                return i
        return -1
