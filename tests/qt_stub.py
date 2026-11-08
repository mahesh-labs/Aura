"""A tiny fake of the parts of PySide6.QtCore the backend uses, so backend LOGIC can be tested without Qt.
Signals call their slots synchronously in the emitting thread (real Qt queues them to the main thread)."""
import sys, types, threading


class _Sig:
    def __init__(self): self.slots = []
    def connect(self, f): self.slots.append(f)
    def disconnect(self, *a): self.slots.clear()
    def emit(self, *a):
        for f in list(self.slots):
            f.emit(*a) if isinstance(f, _Sig) else f(*a)
    __call__ = emit


class Signal:
    def __init__(self, *types): pass
    def __set_name__(self, owner, name): self.name = name
    def __get__(self, obj, cls=None):
        if obj is None: return self
        return obj.__dict__.setdefault("_sig_" + self.name, _Sig())


class QObject:
    def __init__(self, parent=None): pass


def Slot(*a, **k):
    return lambda fn: fn


class Property:
    def __init__(self, typ, fget=None, fset=None, notify=None, constant=False): self.fget = fget
    def __get__(self, obj, cls=None): return self if obj is None else self.fget(obj)


class QModelIndex:
    def isValid(self): return False


class QAbstractListModel(QObject):
    dataChanged = Signal()
    def beginResetModel(self): pass
    def endResetModel(self): pass
    def beginInsertRows(self, *a): pass
    def endInsertRows(self): pass
    def index(self, row): return row


class _Qt:
    UserRole = 256; DisplayRole = 0


class QTimer:
    @staticmethod
    def singleShot(ms, fn): threading.Timer(ms / 1000, fn).start()


def install():
    core = types.ModuleType("PySide6.QtCore")
    for n, v in dict(QObject=QObject, Signal=Signal, Slot=Slot, Property=Property, QTimer=QTimer,
                     QAbstractListModel=QAbstractListModel, QModelIndex=QModelIndex, Qt=_Qt).items():
        setattr(core, n, v)
    pkg = types.ModuleType("PySide6"); pkg.QtCore = core
    sys.modules["PySide6"] = pkg; sys.modules["PySide6.QtCore"] = core
