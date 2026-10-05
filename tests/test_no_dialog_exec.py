"""2.6 guard (change nri-0024-modal-sheets-contract): прикладные диалоги
представления не входят во вложенный цикл событий (spec modal-sheets «Прикладные
диалоги не входят во вложенный цикл событий», design Д7).

Ни один ``.exec()``/``.exec_()`` (блокирующий показ с вложенным циклом; на
qasync он печалится ошибкой вида «Cannot enter into task») не живёт в
``app/presentation/**/*.py`` вне белого списка системных Qt-вызовов. Единственный
класс исключений — всплывающие меню ``QMenu``: ``menu = QMenu(...)`` строится
в этом же файле и ``menu.exec(pos)`` поднимает нативное меню-попап
(spec: всплывашки — класс исключений; design Д3 «Non-Goals»). Реальные
вхождения на момент написания guard'а — ровно два ``menu.exec(...)`` в
``views/timeline_island.py`` (меню «+» и контекстное меню строки ленты).
Механизм — по факту построения, а не по имени: одно и то же имя ``menu``,
привязанное к прикладному диалогу, под запретом.

Механика — AST-скан, а не текстовый grep (прецеденты
``tests/test_no_qt_date_carriers.py``, ``tests/test_architecture_layers.py``):
упоминания ``.exec()`` в докстрингах и комментариях — не узлы и легальны.
Гейтится любой узел ``ast.Attribute`` с именем ``exec``/``exec_`` — не только
вызов ``dlg.exec()``, но и передача адресата (``button.clicked.connect(dlg.exec)``
вложит цикл при клике). Область скана — только ``app/presentation/``:
мастер календаря и лаунчер в ``app/main.py`` живут вне этой задачи (срез 3).

Статический предел (зафиксирован честно): привязка имени к конструктору
белого списка ищется в масштабе файла, а не области видимости — файл, где
``menu`` в одной функции есть ``QMenu``, а в другой является прикладным
диалогом, пропустит вторую точку. Расширять ``SYSTEM_POPUP_CLASSES`` можно
только осознанным изменением под реальное системное вхождение.

QML-контракты этот guard не касаются: ``tests/qml_a11y_scan.py`` сканирует
исключительно ``*.qml`` и токены ``Accessible.*`` — пересечения логики нет.

PR-010 (первый кусок «среза 3»): стартовый контур ``app/main.py`` закрыт
отдельной точечной проверкой — внутри сборки окна запуска запрещены и
``.exec``/``.exec_``, и статические модальные показы ``QMessageBox``
(``warning``/``information``/``critical``/``question``/``about`` — внутри них
тот же вложенный exec-цикл, которым статический ``QMessageBox.warning`` убил
qasync до показа MainWindow).Runtime-половину пина держит
``tests/test_application_settings_errors.py`` (ловушка на ``app.main.QMessageBox``).
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
#: корень скана: только представление (мастер календаря в app/main.py — срез 3)
SCAN_ROOTS = (REPO_ROOT / "app" / "presentation",)
#: блокирующие имена показа Qt (``exec_`` — унаследованный алиас того же цикла)
BANNED_EXEC_ATTRS = frozenset({"exec", "exec_"})
#: имена системных попапов-конструкторов: их экземплярам ``.exec()`` легален —
#: всплывающие меню являются исключением трёхклассового контракта (design Д3)
SYSTEM_POPUP_CLASSES = frozenset({"QMenu"})


def _collect_py_files() -> list[Path]:
    """Все .py под корнями скана без __pycache__."""
    files: list[Path] = []
    for root in SCAN_ROOTS:
        assert root.is_dir(), f"scan root is missing: {root}"
        files.extend(
            path
            for path in sorted(root.rglob("*.py"))
            if "__pycache__" not in path.parts
        )
    return files


def _called_class_name(call: ast.Call) -> str | None:
    """Имя конструируемого класса в вызове: ``QMenu(...)`` или ``X.QMenu(...)``."""
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _system_popup_names(tree: ast.AST) -> set[str]:
    """Имена, привязанные в файле к конструктору системного попапа из белого
    списка: ``menu = QMenu(self)`` (в т.ч. с аннотацией ``menu: QMenu = ...``)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if (
            isinstance(value, ast.Call)
            and _called_class_name(value) in SYSTEM_POPUP_CLASSES
        ):
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _violations_in_tree(tree: ast.AST, path: Path) -> list[tuple[Path, int, str]]:
    """Каждое обращение ``X.exec``/``X.exec_`` вне белого списка — нарушение."""
    system_names = _system_popup_names(tree)
    violations: list[tuple[Path, int, str]] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Attribute) and node.attr in BANNED_EXEC_ATTRS
        ):
            continue
        receiver = node.value
        if isinstance(receiver, ast.Name) and receiver.id in system_names:
            continue  # системное всплывающее меню — исключение контракта
        violations.append((
            path,
            node.lineno,
            f"блокирующий вызов «.{node.attr}()» — прикладные диалоги "
            "показываются open()/show() на общей асинхронной петле, вложенный "
            "цикл событий запрещён (nri-0024, design Д7); белым списком "
            f"проходят только всплывающие меню системного класса "
            f"{sorted(SYSTEM_POPUP_CLASSES)} из этого же файла",
        ))
    return violations


def _exec_attrs_in_tree(tree: ast.AST) -> list[ast.Attribute]:
    """Все обращения ``.exec``/``.exec_`` в дереве (для sanity, что скан живой)."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in BANNED_EXEC_ATTRS
    ]


def _scan_source(source: str, path: Path) -> list[tuple[Path, int, str]]:
    return _violations_in_tree(ast.parse(source), path)


def _format_violations(violations: list[tuple[Path, int, str]]) -> str:
    lines: list[str] = []
    for path, lineno, text in violations:
        try:
            shown = path.relative_to(REPO_ROOT)
        except ValueError:
            shown = path
        lines.append(f"{shown}:{lineno}: {text}")
    return "\n".join(lines)


def _scan_tree() -> list[tuple[Path, int, str]]:
    violations: list[tuple[Path, int, str]] = []
    for path in _collect_py_files():
        violations.extend(_scan_source(path.read_text(encoding="utf-8"), path))
    return violations


# --------------------------------------------------------------------------
# Зелёное дерево
# --------------------------------------------------------------------------

def test_repo_tree_has_no_blocking_dialog_exec_in_presentation():
    """Ни одного прикладного ``.exec()`` под app/presentation/ (докстринги и
    комментарии не мешают — они не узлы AST)."""
    py_files = _collect_py_files()
    assert py_files, "нет .py под app/presentation — область скана сломана"
    violations = _scan_tree()
    assert not violations, (
        "блокирующий показ прикладного диалога вернулся в представление "
        "(вложенный цикл событий на qasync запрещён, nri-0024 design Д7):\n"
        + _format_violations(violations)
    )


def test_real_qmenu_exec_sites_pass_the_whitelist():
    """Белый список живой, а не декоративный: реальные ``menu.exec(...)``
    ленты существуют и проходят именно как системные всплывающие меню."""
    island = REPO_ROOT / "app" / "presentation" / "views" / "timeline_island.py"
    tree = ast.parse(island.read_text(encoding="utf-8"))
    exec_attrs = _exec_attrs_in_tree(tree)
    assert len(exec_attrs) >= 2, (
        "белый список проверялся на меню ленты времени — их вызовы потерялись "
        "(или область исключений изменилась без обновления guard'а)"
    )
    assert _violations_in_tree(tree, island) == [], (
        "системные QMenu-меню ленты времени больше не проходят белый список:\n"
        + _format_violations(_violations_in_tree(tree, island))
    )


# --------------------------------------------------------------------------
# Нарушения падают с файлом и строкой
# --------------------------------------------------------------------------

def test_dialog_exec_call_reports_file_and_line():
    source = "def show(self):\n    return self._dialog.exec()\n"
    violations = _scan_source(source, Path("app/presentation/views/bad.py"))
    assert len(violations) == 1, violations
    path, lineno, text = violations[0]
    assert path == Path("app/presentation/views/bad.py") and lineno == 2
    assert ".exec()" in text and "вложенный цикл" in text


def test_legacy_exec_alias_is_a_violation_too():
    """``exec_`` — унаследованный алиас того же блокирующего цикла, обход
    переименованием не проходит."""
    violations = _scan_source(
        "dlg.exec_(self)\n", Path("app/presentation/views/bad.py")
    )
    assert len(violations) == 1 and violations[0][1] == 1
    assert ".exec_()" in violations[0][2]


def test_exec_address_without_call_is_a_violation():
    """``button.clicked.connect(dlg.exec)`` вложит цикл при клике — адрес
    гейтится так же, как вызов."""
    violations = _scan_source(
        "self.ok_button.clicked.connect(self._viewer.exec)\n",
        Path("app/presentation/views/bad.py"),
    )
    assert len(violations) == 1 and violations[0][1] == 1


def test_system_qmenu_exec_is_whitelisted():
    """Исключение трёхклассового контракта: нативное всплывающее меню,
    построенное в этом же файле (прямым именем и через атрибут модуля)."""
    direct = (
        "menu = QMenu(self)\n"
        "menu.addAction('Пункт')\n"
        "picked = menu.exec(global_pos)\n"
    )
    assert _scan_source(direct, Path("app/presentation/views/ok.py")) == []
    module_qualified = (
        "menu = QtWidgets.QMenu(self)\n"
        "picked = menu.exec(global_pos)\n"
    )
    assert _scan_source(
        module_qualified, Path("app/presentation/views/ok.py")
    ) == []


def test_menu_name_bound_to_application_dialog_is_a_violation():
    """Белый список — по факту построения, а не по имени: ``menu`` из
    прикладного класса под запретом."""
    source = (
        "menu = SheetMenuDialog(self)\n"
        "picked = menu.exec(global_pos)\n"
    )
    violations = _scan_source(source, Path("app/presentation/views/bad.py"))
    assert len(violations) == 1 and violations[0][1] == 2
    assert ".exec()" in violations[0][2]


def test_planted_exec_call_falls_the_tree_guard(tmp_path, monkeypatch):
    """Возврат ``.exec()`` в файл под app/presentation/ роняет древовидную
    проверку с указанием файла и строки."""
    views = tmp_path / "presentation" / "views"
    views.mkdir(parents=True)
    target = views / "bad_viewer.py"
    target.write_text(
        "class ImageViewer:\n"
        "    def show_event(self, event):\n"
        "        return self.exec()\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("tests.test_no_dialog_exec.SCAN_ROOTS", (tmp_path / "presentation",))
    violations = _scan_tree()
    assert len(violations) == 1
    path, lineno, _ = violations[0]
    assert path == target and lineno == 3


# --------------------------------------------------------------------------
# Ложные срабатывания отсутствует
# --------------------------------------------------------------------------

def test_docstring_and_comment_mentions_are_not_violations():
    source = (
        '"""Диалог больше не делает self.exec() — показ идёт open() на общей\n'
        "петле; exec_ здесь упоминается только текстом.\"\"\"\n"
        "\n"
        "# viewer.exec() удалён задачей 2.5 — комментарий, не узел\n"
    )
    assert _scan_source(source, Path("app/presentation/views/x.py")) == []


def test_unrelated_attrs_are_not_violations():
    """Точное имя атрибута: execute/executor-подобные имена и ``run_in_executor``
    не задеваются."""
    source = (
        "self.executor.submit(job)\n"
        "self.run_in_executor(job)\n"
        "plan.execute()\n"
    )
    assert _scan_source(source, Path("app/presentation/views/x.py")) == []


# --------------------------------------------------------------------------
# PR-010: стартовый контур app/main.py (статическая половина «среза 3»)
# --------------------------------------------------------------------------

#: функции старта, на которых вложенная модальность убила qasync (PR-010:
#: статический ``QMessageBox.warning`` внутри сборки окна — и есть регрессия)
BOOT_CONTOUR_FUNCTIONS = frozenset(
    {"_build_main_window", "_show_calendar_corruption_warning"}
)
#: статические показы QMessageBox — внутри каждого свой вложенный exec-цикл,
#: поэтому на стартовом контуре они запрещены наравне с ``.exec()``
BANNED_MSGBOX_STATICS = frozenset(
    {"warning", "information", "critical", "question", "about"}
)


def _boot_contour_violations_in_tree(
    tree: ast.AST, path: Path
) -> list[tuple[Path, int, str]]:
    """Внутри функций стартового контура — ни ``.exec``/``.exec_``, ни
    статического модального показа QMessageBox; конструктор + show()/open()
    легальны (штатный невкладывающий механизм)."""
    violations: list[tuple[Path, int, str]] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in BOOT_CONTOUR_FUNCTIONS
        ):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Attribute):
                continue
            if inner.attr in BANNED_EXEC_ATTRS:
                violations.append((
                    path,
                    inner.lineno,
                    f"блокирующий вызов «.{inner.attr}()» на стартовом контуре "
                    "(PR-010: вложенный цикл событий убивает qasync до показа "
                    "MainWindow)",
                ))
            elif (
                inner.attr in BANNED_MSGBOX_STATICS
                and isinstance(inner.value, ast.Name)
                and inner.value.id == "QMessageBox"
            ):
                violations.append((
                    path,
                    inner.lineno,
                    f"статический модальный показ «QMessageBox.{inner.attr}()» "
                    "на стартовом контуре (PR-010: внутри него вложенный "
                    "exec-цикл; предупреждение показывается отложенным "
                    "show() после window.show())",
                ))
    return violations


def _scan_boot_contour() -> list[tuple[Path, int, str]]:
    main = REPO_ROOT / "app" / "main.py"
    return _boot_contour_violations_in_tree(
        ast.parse(main.read_text(encoding="utf-8")), main
    )


def test_boot_contour_functions_still_live_in_main():
    """Sanity области скана: защищаемые функции на месте — guard не висит
    на пустоте после переименования."""
    names = {
        node.name
        for node in ast.walk(
            ast.parse((REPO_ROOT / "app" / "main.py").read_text(encoding="utf-8"))
        )
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert BOOT_CONTOUR_FUNCTIONS <= names


def test_boot_contour_has_no_modal_shows():
    """Зелёное дерево: в стартовом контуре app/main.py нет ни exec-подобных
    показов, ни статических QMessageBox (PR-010 зафиксирован статически)."""
    violations = _scan_boot_contour()
    assert not violations, (
        "модальный показ вернулся на стартовый контур — qasync умирает до "
        "показа MainWindow (PR-010):\n" + _format_violations(violations)
    )


def test_planted_static_msgbox_warning_on_boot_contour_is_a_violation():
    """Регрессия PR-010 ловится: статический ``QMessageBox.warning`` внутри
    ``_build_main_window`` краснеет с файлом и строкой."""
    source = (
        "class Application:\n"
        "    async def _build_main_window(self):\n"
        "        QMessageBox.warning(None, 't', 'b')\n"
    )
    violations = _boot_contour_violations_in_tree(
        ast.parse(source), Path("app/main.py")
    )
    assert len(violations) == 1 and violations[0][1] == 3
    assert "PR-010" in violations[0][2]


def test_planted_exec_on_boot_contour_is_a_violation():
    source = (
        "class Application:\n"
        "    async def _build_main_window(self):\n"
        "        return self._dialog.exec_()\n"
    )
    violations = _boot_contour_violations_in_tree(
        ast.parse(source), Path("app/main.py")
    )
    assert len(violations) == 1 and violations[0][1] == 3
    assert ".exec_()" in violations[0][2]


def test_deferred_warning_show_is_not_a_boot_contour_violation():
    """Штатный механизм легален: конструктор + ``show()``/``open()`` — не
    нарушение (иначе зелёное дерево было бы недостижимо)."""
    source = (
        "class Application:\n"
        "    def _show_calendar_corruption_warning(self, body):\n"
        "        box = QMessageBox(self._window)\n"
        "        box.setWindowTitle('t')\n"
        "        box.setText(body)\n"
        "        box.show()\n"
    )
    assert _boot_contour_violations_in_tree(
        ast.parse(source), Path("app/main.py")
    ) == []


def test_msgbox_static_outside_boot_contour_is_untouched():
    """Точечность скана: те же статические показы вне стартового контура
    (экспорт, упоминания) этим guard'ом не гейтятся."""
    source = (
        "class Application:\n"
        "    def _on_export_game(self):\n"
        "        QMessageBox.information(self._window, 't', 'b')\n"
    )
    assert _boot_contour_violations_in_tree(
        ast.parse(source), Path("app/main.py")
    ) == []
