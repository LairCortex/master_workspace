"""QML code for the app shell (change Q1).

Two things live here:

* the engine bootstrap (``engine.py`` — the Python half of the qml-shell);
* the QML sources of the islands, as plain files, NOT Qt resources
  (spec qml-shell «Размещение qml-файлов и поставка»). This directory is the
  engine's import path: islands load it by file URL, no qmldir module is
  introduced in this chunk (modularity — a later chunk). The directory must
  therefore exist on disk at runtime; ``Qt`` silently drops non-existent
  entries from ``addImportPath``.
"""
from app.presentation.qml.engine import (
    QML_IMPORT_PATH,
    qml_engine,
    reset_qml_shell,
    setup_qml_shell,
)

__all__ = ["QML_IMPORT_PATH", "qml_engine", "reset_qml_shell", "setup_qml_shell"]
