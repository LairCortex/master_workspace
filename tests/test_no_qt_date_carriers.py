"""C6: запрет возвращения Qt-носителей даты в прод и тесты (изменение close-custom-calendar-map, design D1).

Qt-прокси дат умерли в C3b: `QDate`/`QCalendarWidget` не должны вернуться
ни импортами, ни объявлениями/вызовами удалённого прокси-метода `setDate`.
Проверка — AST-скан, а не текстовый grep (прецедент spec-datas отвергнут:
он ловил бы docstring и QSS-строки). Упоминания `QDate`/`QCalendarWidget`
в докстрингах и комментариями не являются AST-узлами и остаются легальны.

Ложные срабатывания недопустимы: `vm.set_dates` — другое имя атрибута,
а `.date()` легален у `datetime` (гейтится только ровно `setDate`; прокси
`date()` закрыть нечем без запрета легального `.date()`, но его подпись
обязана возвращать `QDate` — это ловит запрет импорта).
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_ROOTS = (REPO_ROOT / "app", REPO_ROOT / "tests")

# Имена, чей импорт запрещён в любом .py под app/ и tests/ (design D1, п.1)
BANNED_IMPORT_NAMES = frozenset({"QDate", "QCalendarWidget"})
# Имена, запрещённые как атрибут (обращение) или объявление (design D1, п.2)
BANNED_MEMBER_NAMES = frozenset({"setDate"})


def _collect_py_files() -> list[Path]:
    """Все .py под app/ и tests/ без __pycache__."""
    files: list[Path] = []
    for root in SCAN_ROOTS:
        assert root.is_dir(), f"scan root is missing: {root}"
        files.extend(
            path
            for path in sorted(root.rglob("*.py"))
            if "__pycache__" not in path.parts
        )
    return files


def _violations_in_tree(tree: ast.AST, path: Path) -> list[tuple[Path, int, str]]:
    """Обходит дерево импорта-за-импортом и собирает нарушения (файл, строка, текст)."""
    violations: list[tuple[Path, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in BANNED_IMPORT_NAMES:
                    violations.append(
                        (
                            path,
                            node.lineno,
                            f"запрещённый импорт Qt-носителя даты «{alias.name}» "
                            f"из «{node.module}»",
                        )
                    )
        elif isinstance(node, ast.Attribute) and node.attr in BANNED_MEMBER_NAMES:
            violations.append(
                (path, node.lineno, f"обращение к запрещённому атрибуту «{node.attr}»")
            )
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and (
            node.name in BANNED_MEMBER_NAMES
        ):
            violations.append(
                (
                    path,
                    node.lineno,
                    f"объявление запрещённого метода «{node.name}»",
                )
            )
    return violations


def _scan_source(source: str, path: Path) -> list[tuple[Path, int, str]]:
    return _violations_in_tree(ast.parse(source), path)


def _format_violations(violations: list[tuple[Path, int, str]]) -> str:
    return "\n".join(
        f"{path.relative_to(REPO_ROOT)}:{lineno}: {text}"
        for path, lineno, text in violations
    )


def test_repo_tree_has_no_qt_date_carriers():
    """Всё текущее дерево app/ и tests/ чисто (докстринговые упоминания не мешают)."""
    violations: list[tuple[Path, int, str]] = []
    py_files = _collect_py_files()
    assert py_files, "no .py files found under app/ and tests/ — scan paths broken"
    for path in py_files:
        violations.extend(_scan_source(path.read_text(encoding="utf-8"), path))
    assert not violations, (
        "Qt-носители даты вернулись в код (design D1: только AST-скан, "
        "docstring/комментарии легальны):\n" + _format_violations(violations)
    )


def test_docstring_mention_of_qdate_is_allowed():
    """Сценарий спеке: имя Qt-класса даты только в docstring — проверка проходит."""
    source = (
        "class Grid:\n"
        '    """Сетка пришла на смену QDate/QCalendarWidget — упоминание текстом."""\n'
        "\n"
        "    # комментарий: QCalendarWidget убран, setDate удалён\n"
    )
    assert _scan_source(source, Path("snippet.py")) == []


def test_import_from_of_banned_names_is_a_violation():
    for name, module in (("QDate", "PySide6.QtCore"), ("QCalendarWidget", "PySide6.QtWidgets")):
        source = f"from {module} import {name}\n"
        violations = _scan_source(source, Path("snippet.py"))
        assert len(violations) == 1, f"импорт {name} должен ронять проверку"
        path, lineno, text = violations[0]
        assert path == Path("snippet.py") and lineno == 1, (
            "ошибка обязана содержать файл и номер строки"
        )
        assert name in text


def test_banned_import_in_nested_file_lands_in_tree_message(tmp_path, monkeypatch):
    """Возврат импорта в файл под app/ роняет проверку с указанием файла и строки."""
    (tmp_path / "app").mkdir()
    target = tmp_path / "app" / "some_view.py"
    target.write_text("from PySide6.QtCore import QDate\n", encoding="utf-8")
    monkeypatch.setattr("tests.test_no_qt_date_carriers.SCAN_ROOTS", (tmp_path / "app",))
    violations = []
    for path in _collect_py_files():
        violations.extend(_scan_source(path.read_text(encoding="utf-8"), path))
    assert len(violations) == 1
    path, lineno, text = violations[0]
    assert path == target and lineno == 1
    assert "QDate" in text


def test_setdate_attribute_and_declaration_are_violations():
    call_src = "dialog.setDate(coord)\n"
    violations = _scan_source(call_src, Path("snippet.py"))
    assert len(violations) == 1 and violations[0][2].startswith("обращение")
    assert violations[0][1] == 1

    def_src = "class Dialog:\n    def setDate(self, coord):\n        pass\n"
    violations = _scan_source(def_src, Path("snippet.py"))
    assert len(violations) == 1 and violations[0][2].startswith("объявление")
    assert violations[0][1] == 2


def test_set_dates_attribute_is_not_a_false_positive():
    """vm.set_dates — другое имя атрибута; вызов и объявление не задеваются."""
    source = (
        "class VM:\n"
        "    def set_dates(self, start, end):\n"
        "        self._start, self._end = start, end\n"
        "\n"
        "vm = VM()\n"
        "vm.set_dates(1, 2)\n"
    )
    assert _scan_source(source, Path("snippet.py")) == []
    # и в реальном дереве вызовы vm.set_dates уже живут — скан их не роняет
    real_calls = [
        path
        for path in _collect_py_files()
        if ".vm.set_dates(" in path.read_text(encoding="utf-8")
    ]
    assert real_calls, "ожидались реальные вызовы vm.set_dates в дереве"


def test_datetime_dot_date_call_is_not_a_false_positive():
    """.date() легален у datetime — атрибут «date» не гейтится."""
    source = (
        "import datetime\n"
        "\n"
        "value = datetime.datetime.now()\n"
        "day = value.date()\n"
    )
    assert _scan_source(source, Path("snippet.py")) == []
    # и в реальном дереве .date() у datetime уже есть — скан его не роняет
    real_calls = [
        path
        for path in _collect_py_files()
        if ".date()" in path.read_text(encoding="utf-8")
    ]
    assert real_calls, "ожидались реальные вызовы .date() в дереве"
