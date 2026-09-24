"""Pins NRI-0014 group 6 — spec interface-language (L1).

Qt itself paints the standard dialog chrome (``QMessageBox``/``QDialogButtonBox``
buttons, the file panels); it SHALL read Russian identically from a source
checkout and from the packaged .app. The single install mechanism is
``app.infrastructure.localization.install_russian_localization`` with the
bundled ``qtbase_ru.qm`` resolved through ``QLibraryInfo``; the test session
reproduces the post-startup state (``QTranslator`` right after QApplication,
before the first window) through the session fixture in ``tests/conftest.py``,
exactly like ``main()`` does.

Catalog wording notes (official Qt Russian ``qtbase_ru.qm``):
* Yes/No buttons carry the Alt-mnemonic — «&Да»/«&Нет» — stripped in asserts;
* the OK button stays the Latin "OK" in the Russian catalog — typographically
  the same word («ОК») the spec names — while Cancel really flips to «Отмена»;
* the file panel renames every zone: «Имя файла:», «Сохранить», «Открыть»,
  «Отмена» — no ``Save As:``/``Cancel`` remnants (spec «SHALL не быть
  незакрытых англизмом зон»).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PySide6.QtCore import QLibraryInfo, QTranslator
from PySide6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QFileDialog,
    QMessageBox,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "nri_manager.spec"
APP_ROOT = REPO_ROOT / "app"

# The catalog file the app loads (name, not a path — the path is what
# QLibraryInfo resolves on the dev box AND inside the bundle).
CATALOG_BASE_NAME = "qtbase_ru"
# Bundle destination of the translations folder: the PySide6 runtime hook
# homes the Qt prefix at ``sys._MEIPASS/PySide6/Qt`` and the generated
# qt.conf anchors QLibraryInfo there, so TranslationsPath lands on this dir —
# the same suffix the dev wheel exposes.
TRANSLATIONS_DEST = "PySide6/Qt/translations"

#: every QFileDialog static call site allowed in app/, keyed (module-relative
#: path, enclosing function). Each entry must pass options=…DontUseNativeDialog
#: (task 6.2: game export, xlsx import, image pick, PDF export, launcher
#: import). A new call anywhere else — or one of these losing the option —
#: fails the pin; deleting a site must update this list on purpose.
FILE_DIALOG_SITES = frozenset({
    ("app/main.py", "_on_export_game"),
    ("app/presentation/views/game_launcher_dialog.py", "_on_import_requested"),
    ("app/presentation/views/xlsx_import_dialog.py", "save_template_as"),
    ("app/presentation/views/xlsx_import_dialog.py", "_on_browse"),
    ("app/presentation/views/character_sheet/fill_dialog.py", "_pick_image"),
    ("app/presentation/views/entity_card_dialog.py", "_on_pick_image"),
    ("app/presentation/views/character_sheet/editor_dialog.py", "export_pdf"),
    ("app/presentation/views/character_sheet/editor_dialog.py", "_pick_image"),
})
FILE_DIALOG_STATICS = frozenset({
    "getOpenFileName",
    "getOpenFileNames",
    "getSaveFileName",
    "getExistingDirectory",
})


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _spec_datas_text() -> str:
    text = SPEC_PATH.read_text(encoding="utf-8")
    assert "datas=[" in text, "nri_manager.spec has no datas list"
    return text.split("datas=[", 1)[1].rsplit("]", 1)[0]


def _strip_mnemonic(text: str) -> str:
    return text.replace("&", "")


def _probe_static_dialog(qapp: QApplication, action):
    """Run a blocking static dialog and inspect the live widget it exec()s.

    The static helpers open a nested event loop; a zero-timer fires inside it,
    captures the active modal widget (never raising — a raise there would
    strand the nested loop) and closes it, so the call returns cancelled.
    """
    seen: dict = {}

    def probe() -> None:
        widget = qapp.activeModalWidget()
        if widget is None:  # watchdog: nothing modal — mark and let the loop drain
            return
        seen["widget"] = widget
        if isinstance(widget, QFileDialog):
            seen["non_native"] = widget.testOption(
                QFileDialog.Option.DontUseNativeDialog
            )
            seen["caption"] = widget.windowTitle()
            seen["file_name_label"] = widget.labelText(
                QFileDialog.DialogLabel.FileName
            )
            seen["accept_label"] = widget.labelText(QFileDialog.DialogLabel.Accept)
            seen["reject_label"] = widget.labelText(QFileDialog.DialogLabel.Reject)
            widget.reject()
        else:
            seen["texts"] = {}
            if isinstance(widget, QMessageBox):
                for role in ("Yes", "No", "Cancel", "Ok"):
                    button = widget.button(
                        getattr(QMessageBox.StandardButton, role)
                    )
                    if button is not None:
                        seen["texts"][role] = button.text()
            seen["caption"] = widget.windowTitle()
            widget.done(0)

    from PySide6.QtCore import QTimer

    QTimer.singleShot(0, probe)
    result = action()
    return seen, result


# --------------------------------------------------------------------------
# 6.1 — QTranslator(qtbase_ru) : единственный механизм, один на процесс
# --------------------------------------------------------------------------


def test_catalog_resolves_through_library_info():
    # The install path contract of task 6.1: the catalog is found where
    # QLibraryInfo points (dev wheel today; the bundle gets the same layout
    # through nri_manager.spec datas — pinned below).
    translator = QTranslator()
    assert translator.load(
        CATALOG_BASE_NAME, QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    ), "qtbase_ru.qm must resolve next to the Qt installation"


def test_question_shows_da_net_otmena_after_startup(qapp):
    # Spec scenario «Подтверждение удаления — русское» (the launcher's delete
    # confirmation runs exactly this static). The buttons come from the
    # startup translator, no per-call setText anywhere.
    seen, _ = _probe_static_dialog(
        qapp,
        lambda: QMessageBox.question(
            None,
            "Удаление игры",
            "Удалить игру? Это действие необратимо.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.No,
        ),
    )
    assert isinstance(seen.get("widget"), QMessageBox), (
        "probing failed: no modal QMessageBox passed the run — the startup "
        "translator contract cannot be verified"
    )
    texts = seen["texts"]
    assert _strip_mnemonic(texts["Yes"]) == "Да"
    assert _strip_mnemonic(texts["No"]) == "Нет"
    assert _strip_mnemonic(texts["Cancel"]) == "Отмена"


def test_button_box_ok_cancel_are_russian():
    # Spec scenario «Диалог создания — русский»: EventDialog and the entity
    # card run QDialogButtonBox(Ok|Cancel) — its standard texts SHALL be
    # Russian. The official Russian catalog keeps OK as the Latin "OK"
    # (visually «ОК»), «Отмена» proves the catalog is installed and active.
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    ok_text = _strip_mnemonic(box.button(QDialogButtonBox.StandardButton.Ok).text())
    cancel_text = _strip_mnemonic(
        box.button(QDialogButtonBox.StandardButton.Cancel).text()
    )
    assert ok_text in {"ОК", "OK"}, ok_text
    assert cancel_text == "Отмена"


def test_installer_never_forks_a_second_translator(qapp, monkeypatch):
    # Guard of task 6.1: the session fixture already installed the one
    # mechanism (post-startup state); the installer must be idempotent —
    # a second call returns the same translator and installs nothing new.
    from app.infrastructure.localization import install_russian_localization

    installed: list = []
    original = QApplication.installTranslator

    def counting(self, translator, *args):
        installed.append(translator)
        return original(self, translator, *args)

    monkeypatch.setattr(QApplication, "installTranslator", counting)
    first = install_russian_localization(qapp)
    second = install_russian_localization(qapp)
    assert isinstance(first, QTranslator)
    assert first is second
    assert installed == [], "second translator installed — two sources of truth"


# --------------------------------------------------------------------------
# 6.1 — поставка каталога в собранном .app (nri_manager.spec)
# --------------------------------------------------------------------------


def test_spec_bundles_the_pyside_translations_folder():
    # Frozen apps must see qtbase_ru.qm at QLibraryInfo's TranslationsPath.
    # The PySide6 runtime hook anchors the Qt prefix at sys._MEIPASS/PySide6/Qt,
    # so the wheel's translations folder ships verbatim under that name.
    spec_text = SPEC_PATH.read_text(encoding="utf-8")
    datas = _spec_datas_text()
    assert "TranslationsPath" in spec_text, (
        "the spec must resolve the source folder via QLibraryInfo — the same "
        "lookup the startup installer performs"
    )
    assert TRANSLATIONS_DEST in datas, (
        f"nri_manager.spec datas must ship the PySide6 translations folder to "
        f"{TRANSLATIONS_DEST!r} — otherwise the frozen app loses the Russian "
        "chrome while the dev run keeps it"
    )


# --------------------------------------------------------------------------
# 6.2 — файловые панели: всегда не-нативные, всегда русские
# --------------------------------------------------------------------------


def _real_filedialog_calls() -> dict[tuple[str, str], ast.Call]:
    """Map (module-relative path, enclosing function) → QFileDialog static Call."""
    found: dict[tuple[str, str], ast.Call] = {}

    class Visitor(ast.NodeVisitor):
        def __init__(self, path: Path) -> None:
            self.path = path
            self.stack: list[str] = []

        def _visit_func(self, node) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_FunctionDef = _visit_func
        visit_AsyncFunctionDef = _visit_func

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in FILE_DIALOG_STATICS
                and isinstance(func.value, ast.Name)
                and func.value.id == "QFileDialog"
            ):
                key = (
                    str(self.path.relative_to(REPO_ROOT)),
                    self.stack[-1] if self.stack else "<module>",
                )
                assert key not in found, f"duplicate pinned site {key}"
                found[key] = node
            self.generic_visit(node)

    for py in sorted(APP_ROOT.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        Visitor(py).visit(ast.parse(py.read_text(encoding="utf-8")))
    return found


def test_ast_filedialog_sites_are_exactly_the_pinned_ones():
    found = _real_filedialog_calls()
    assert set(found) == set(FILE_DIALOG_SITES), (
        "QFileDialog call sites drifted from the pinned list — add the new "
        "site WITH DontUseNativeDialog, remove the stale entry on purpose"
    )


def test_ast_every_filedialog_call_forbids_the_native_dialog():
    for (module, function), call in sorted(_real_filedialog_calls().items()):
        options_kwargs = [kw for kw in call.keywords if kw.arg == "options"]
        assert options_kwargs, (
            f"{module}:{function} — QFileDialog call must pass "
            "options=QFileDialog.Option.DontUseNativeDialog (task 6.2: the "
            "native panel is untranslatable and differs between dev and .app)"
        )
        flag_found = any(
            isinstance(node, ast.Attribute) and node.attr == "DontUseNativeDialog"
            for kw in options_kwargs
            for node in ast.walk(kw.value)
        )
        assert flag_found, (
            f"{module}:{function} — options= passed without DontUseNativeDialog"
        )


@pytest.fixture
def launcher_runtime(tmp_path):
    from app.infrastructure.ui_prefs.config import UiPrefsManager
    from app.presentation.theme.compiler import tokens_file_path
    from app.presentation.theme.runtime import ThemeRuntime

    return ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens_file_path(),
    )


def test_launcher_import_panel_is_non_native_and_russian(qapp, qtbot, launcher_runtime):
    # Task 6.2 offscreen pin, open-family, driven through real app code:
    # the launcher's «Импорт» runs QFileDialog.getOpenFileName.
    from app.presentation.views.game_launcher_dialog import GameLauncherDialog

    dialog = GameLauncherDialog(theme=launcher_runtime)
    qtbot.addWidget(dialog)
    seen, result = _probe_static_dialog(
        qapp, lambda: dialog._on_import_requested("")
    )
    assert isinstance(seen.get("widget"), QFileDialog), (
        "no live QFileDialog observed — the import path never reached the panel"
    )
    assert seen["non_native"], "launcher import still opens the native panel"
    assert seen["caption"] == "Импорт игры"
    assert _strip_mnemonic(seen["file_name_label"]) == "Имя файла:"
    assert _strip_mnemonic(seen["accept_label"]) == "Открыть"
    assert _strip_mnemonic(seen["reject_label"]) == "Отмена"
    assert result is None  # cancelled: the handler bails out before importing


def test_template_save_panel_is_non_native_and_russian(qapp, tmp_path, mocker):
    # Save-family pin through real app code (save_template_as runs the same
    # QFileDialog.getSaveFileName static as the game export). Cancelled via
    # the probe, so no workbook is produced.
    mocker.patch(
        "app.presentation.views.xlsx_import_dialog.build_template_workbook"
    )
    from app.presentation.views.xlsx_import_dialog import save_template_as

    seen, result = _probe_static_dialog(
        qapp, lambda: save_template_as(None)
    )
    assert isinstance(seen.get("widget"), QFileDialog), (
        "no live QFileDialog observed — the save path never reached the panel"
    )
    assert seen["non_native"], "template save still opens the native panel"
    assert seen["caption"] == "Сохранить шаблон"
    assert _strip_mnemonic(seen["accept_label"]) == "Сохранить"
    assert _strip_mnemonic(seen["reject_label"]) == "Отмена"
    assert result is None
    assert list(tmp_path.iterdir()) == []
