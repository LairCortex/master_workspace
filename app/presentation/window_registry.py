"""Open-window registry for menu entries (NRI-0014, design D1).

One mechanism for every single-instance menu window (defect AB4: a repeated
entry stacked a second sheet): the composition root builds a single
registry, hands it to ``MainWindow`` and uses it itself for the launcher
entry. ``open(key, factory)`` raises and activates the live window when the
key already has one; otherwise it builds the window through the factory,
shows it non-modally and hooks auto-``forget`` on ``finished``, so the next
open after a close creates a fresh window. The behaviour is the char-sheet
list precedent (``sheet_windows.on_char_sheets``) lifted out of its usage
site — no parallel dedup mechanics live in the windows themselves
(AGENTS "one knowledge, one place").
"""
from __future__ import annotations

from typing import Callable, Dict, Optional

from PySide6.QtWidgets import QDialog

# Contract keys of this change (spec qml-shell «Повторный пункт меню
# поднимает существующее окно», design D1): the two document windows are
# distinct single instances, and so are the «Сменить игру…» launcher and
# the «Настройка LLM…» window — the contract names all four non-modal
# entries of the format norm («Формат диалогов задан точкой входа»).
DOCS_README_KEY = "docs_readme"
DOCS_CHANGELOG_KEY = "docs_changelog"
LAUNCHER_SWITCH_KEY = "launcher_switch"
LLM_SETUP_KEY = "llm_setup"


class MenuWindowRegistry:
    """Tracks at most one open window per menu-entry key."""

    def __init__(self) -> None:
        self._windows: Dict[str, QDialog] = {}

    def open(self, key: str, factory: Callable[[], QDialog]) -> QDialog:
        """Return the live window for ``key``, or create, show and track one.

        Reuse raises and activates the existing window (spec «Второй вызов
        не дублирует»); a fresh window is shown non-modally and forgets
        itself on ``finished``, so closing releases the key (spec «После
        закрытия открывается заново») — including windows closed with
        ``WA_DeleteOnClose``, which forget before the C++ object dies.
        """
        existing = self._windows.get(key)
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return existing
        window = factory()
        self._windows[key] = window
        # Default-arg capture: the hook must see THIS window and key even
        # after the slot is replaced (the ``_forget_*`` binding pattern).
        window.finished.connect(
            lambda _result, _w=window, _k=key: self._forget(_k, _w)
        )
        window.show()
        return window

    def get(self, key: str) -> Optional[QDialog]:
        """The currently tracked window for ``key`` (test-visible, read-only)."""
        return self._windows.get(key)

    def _forget(self, key: str, window: QDialog) -> None:
        # Stale-guard: only release the key this very window still owns.
        if self._windows.get(key) is window:
            del self._windows[key]
