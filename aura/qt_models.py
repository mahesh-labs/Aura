"""Qt list models used by the QML views."""
from __future__ import annotations

import time

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    Qt,
    Signal,
)


class MessagesModel(QAbstractListModel):
    ROLE = Qt.UserRole + 1
    TEXT = Qt.UserRole + 2
    STATUS = Qt.UserRole + 3
    NAME = Qt.UserRole + 4
    DETAIL = Qt.UserRole + 5
    CALL = Qt.UserRole + 6

    countChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict] = []
        self._streaming = False

    # -- Qt API --------------------------------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        it = self._items[index.row()]
        return {
            self.ROLE: it.get("role", ""),
            self.TEXT: it.get("text", ""),
            self.STATUS: it.get("status", ""),
            self.NAME: it.get("name", ""),
            self.DETAIL: it.get("detail", ""),
            self.CALL: it.get("call_id", ""),
        }.get(role)

    def roleNames(self):
        return {
            self.ROLE: QByteArray(b"role"),
            self.TEXT: QByteArray(b"text"),
            self.STATUS: QByteArray(b"status"),
            self.NAME: QByteArray(b"name"),
            self.DETAIL: QByteArray(b"detail"),
            self.CALL: QByteArray(b"callId"),
        }

    def _get_count(self):
        return len(self._items)

    count = Property(int, _get_count, notify=countChanged)

    # -- mutation ------------------------------------------------------------
    def set_items(self, items: list[dict]) -> None:
        self.beginResetModel()
        self._items = [dict(i) for i in items]
        self._streaming = False
        self.endResetModel()
        self.countChanged.emit()

    def append(self, item: dict) -> None:
        self._streaming = False
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append(dict(item))
        self.endInsertRows()
        self.countChanged.emit()

    def append_delta(self, text: str) -> None:
        if not self._streaming or not self._items or self._items[-1].get("role") != "assistant":
            self.append({"role": "assistant", "text": text, "status": "streaming"})
            self._streaming = True
            return
        last = len(self._items) - 1
        self._items[last]["text"] += text
        idx = self.index(last)
        self.dataChanged.emit(idx, idx, [self.TEXT])

    def end_stream(self) -> None:
        if self._streaming and self._items:
            last = len(self._items) - 1
            self._items[last]["status"] = ""
            idx = self.index(last)
            self.dataChanged.emit(idx, idx, [self.STATUS])
        self._streaming = False

    def update_call(self, call_id: str, **fields) -> bool:
        for i in range(len(self._items) - 1, -1, -1):
            if self._items[i].get("call_id") == call_id:
                self._items[i].update(fields)
                idx = self.index(i)
                self.dataChanged.emit(idx, idx, [self.STATUS, self.DETAIL, self.TEXT])
                return True
        return False


class ConversationsModel(QAbstractListModel):
    ID = Qt.UserRole + 1
    TITLE = Qt.UserRole + 2
    WHEN = Qt.UserRole + 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        it = self._items[index.row()]
        return {self.ID: it["id"], self.TITLE: it["title"], self.WHEN: _when(it["updated"])}.get(role)

    def roleNames(self):
        return {
            self.ID: QByteArray(b"convId"),
            self.TITLE: QByteArray(b"title"),
            self.WHEN: QByteArray(b"when"),
        }

    def set_items(self, items: list[dict]) -> None:
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()


def _when(ts: float) -> str:
    d = time.time() - ts
    if d < 60:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400:
        return f"{int(d // 3600)} h ago"
    return time.strftime("%d %b", time.localtime(ts))
