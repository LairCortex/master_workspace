"""Хранитель изоляции встроенного модуля (add-dnd-module-foundation, task 1.3;
spec architecture-integrity «Ядро не знает о модуле», design Д2/Д3).

Два правила, механика — AST-скан (прецеденты ``tests/test_architecture_layers.py``,
``tests/test_no_dialog_exec.py``: докстринги и комментарии — не узлы):

1. ``app.dd`` имеет право импортировать РОВНО ОДИН файл ядра — точка сборки
   ``app/main.py``. Любое ядро (``app/**`` вне ``app/dd/``), поймавший импорт
   пакета модуля, краснеет с файлом и строкой: ядро не знает о модуле, пока
  composition point не решит обратное по флагу игры.

2. Ядро модуля (``app/dd/domain``, ``app/dd/application``) не импортирует UI
   модуля ``app.dd.presentation``: модуль крепится к UI только через
   ``attach`` (design Д2). UI ядра модульному ядру уже запрещает
   ``tests/test_architecture_layers.py`` (R1 распространён на дерево ``app/dd``).

3. ``app/dd`` (всё дерево) не зовёт ``register_external`` — дверь внешних
   типов в реестре открывает только точка сборки ``app/main.py``; модуль свои
   типы лишь объявляет в ``type_descriptors`` источников (add-dnd-game-face,
   design Д2; парное правило ядра — R8 в guard'е архитектуры).

Пин живого шва: ``app/main.py`` действительно импортирует ``app.dd`` (лениво,
внутри factory composition — иначе guard висел бы на пустоте), протокол
``GameSystemModule`` — единственная поверхность договора, и обе реализации
(``DndModule``/``NoopGameSystemModule``) ему соответствуют.

Статический предел (фиксируем честно, как у соседних guard'ов): динамические
заходы (``importlib.import_module("app.dd")``) AST не виден; точка сборки не
использует их, а текстовые упоминания имени легальны — тот же закон, что у
R5/R7 архитектуры.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = REPO_ROOT / "app"
#: пакет модуля — единственный объект охраны
MODULE_ROOT = APP_ROOT / "dd"
#: единственная точка, которой разрешён импорт пакета модуля (spec: точка сборки)
ALLOWED_IMPORTER_PARTS = ("app", "main.py")
#: слои ядра модуля, которым запрещён его собственный UI
DD_CORE_DIRS = (MODULE_ROOT / "domain", MODULE_ROOT / "application")
#: UI модуля — недоступен ядру модуля
DD_PRESENTATION_PREFIX = "app.dd.presentation"
#: дверь регистрации внешних типов — правом точки сборки (правило 3, design Д2)
EXTERNAL_REGISTRATION_FUNC = "register_external"


def _collect_py_files(roots: tuple[Path, ...]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        assert root.is_dir(), f"scan root is missing: {root}"
        files.extend(
            path
            for path in sorted(root.rglob("*.py"))
            if "__pycache__" not in path.parts
        )
    return files


def _repo_relative_parts(path: Path) -> tuple[str, ...]:
    """Части пути относительно корня репозитория (для синтетических путей —
    как есть; схема ``app/<pkg>`` от них работает — прецедент kernel guard'а)."""
    try:
        return path.resolve().relative_to(REPO_ROOT).parts
    except ValueError:
        return path.parts


def _package_parts(path: Path) -> list[str]:
    """Каталожные части файла без имени файла."""
    return list(_repo_relative_parts(path)[:-1])


def _resolved_module(
    own_parts: list[str], module: str | None, level: int, alias_name: str
) -> str:
    """Полный dotted-путь импорта: абсолютного и относительного (``from ..x``).

    ``from app import dd`` и относительные заходы, чья база — пакет ``app``,
    дополняются именем alias (``from . import dd`` из ``app/`` — это ``app.dd``).
    """
    if level == 0:
        segments = (module or "").split(".")
        if segments == ["app"]:
            return f"app.{alias_name}"
        return ".".join(segments)
    base = own_parts[: len(own_parts) - (level - 1)] if level > 1 else list(own_parts)
    if module:
        base = base + module.split(".")
    if base == ["app"]:
        return f"app.{alias_name}"
    return ".".join(base)


def _import_paths_in_tree(tree: ast.AST, path: Path):
    """(дotted-путь, строка) для каждого импорта файла."""
    own_parts = _package_parts(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                yield _resolved_module(
                    own_parts, node.module, node.level, alias.name
                ), node.lineno


def _is_allowed_importer(path: Path) -> bool:
    """Импорт ``app.dd`` легален ровно в ``app/main.py`` (spec: одна точка)."""
    return _repo_relative_parts(path) == ALLOWED_IMPORTER_PARTS


def _dd_import_violations_in_tree(
    tree: ast.AST, path: Path
) -> list[tuple[Path, int, str]]:
    """Ядро (не ``app/dd/``) не импортирует ``app.dd`` вне точки сборки."""
    if MODULE_ROOT in path.parents or _is_allowed_importer(path):
        return []
    violations: list[tuple[Path, int, str]] = []
    for dotted, lineno in _import_paths_in_tree(tree, path):
        if dotted == "app.dd" or dotted.startswith("app.dd."):
            violations.append((
                path,
                lineno,
                f"импорт пакета модуля «{dotted}» из ядра запрещён — правом "
                "обладает только точка сборки app/main.py (аддитивность: "
                "ядро не знает о модуле, add-dnd-module-foundation)",
            ))
    return violations


def _dd_core_layer_violations_in_tree(
    tree: ast.AST, path: Path
) -> list[tuple[Path, int, str]]:
    """Ядро модуля не импортирует UI модуля: связь только через attach."""
    parts = _repo_relative_parts(path)
    if not (
        parts[:3] == ("app", "dd", "domain")
        or parts[:3] == ("app", "dd", "application")
    ):
        return []
    violations: list[tuple[Path, int, str]] = []
    for dotted, lineno in _import_paths_in_tree(tree, path):
        if dotted == DD_PRESENTATION_PREFIX or dotted.startswith(
            DD_PRESENTATION_PREFIX + "."
        ):
            violations.append((
                path,
                lineno,
                f"импорт «{dotted}» в ядро модуля запрещён: модуль знает о UI "
                "только через attach(window, wiring) (design Д2)",
            ))
    return violations


def _is_external_registration_call(node: ast.AST) -> bool:
    """Вызов двери реестра в любой форме: ``reg.register_external(…)`` по
    атрибуту и ``register_external(…)`` по прямому имени (add-dnd-game-face,
    design Д2). Определение функции и проза — не узлы вызова."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (
        isinstance(func, ast.Attribute) and func.attr == EXTERNAL_REGISTRATION_FUNC
    ) or (isinstance(func, ast.Name) and func.id == EXTERNAL_REGISTRATION_FUNC)


def _external_registration_violations_in_tree(
    tree: ast.AST, path: Path
) -> list[tuple[Path, int, str]]:
    """Правило 3: ``app/dd`` не открывает дверь ``register_external`` — типы
    модуль только объявляет (``type_descriptors`` источников), регистрирует их
    единственная точка composition (design Д2, прецедент R8 в guard'е
    архитектуры)."""
    if _repo_relative_parts(path)[:2] != ("app", "dd"):
        return []
    violations: list[tuple[Path, int, str]] = []
    for node in ast.walk(tree):
        if _is_external_registration_call(node):
            violations.append((
                path,
                node.lineno,
                "модуль не регистрирует типы сам: дверь register_external "
                "открывает только точка сборки app/main.py, модуль объявляет "
                "типы через type_descriptors источников (add-dnd-game-face, "
                "design Д2)",
            ))
    return violations


def _scan(roots: tuple[Path, ...], checker) -> list[tuple[Path, int, str]]:
    violations: list[tuple[Path, int, str]] = []
    for path in _collect_py_files(roots):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        violations.extend(checker(tree, path))
    return violations


# --------------------------------------------------------------------------
# Зелёное дерево
# --------------------------------------------------------------------------


def test_kernel_never_imports_the_module_outside_the_composition_point():
    """Единственный импорт ``app.dd`` в ядре — точка сборки; всё остальное
    (``app/**`` вне ``app/dd/``) зелено."""
    violations = _scan((APP_ROOT,), _dd_import_violations_in_tree)
    assert not violations, (
        "ядро снова знает о модуле напрямую — состав собирает только main.py "
        "по флагу игры:\n"
        + "\n".join(f"{p}:{ln}: {t}" for p, ln, t in violations)
    )
    # sanity: шов живой — guard не висит на пустоте. Точка сборки действительно
    # импортирует app.dd; её скан с отключённым allow-list'ом даёт находки.
    main_tree = ast.parse((APP_ROOT / "main.py").read_text(encoding="utf-8"))
    hits = _dd_import_violations_in_tree(main_tree, Path("app/would_be_kernel.py"))
    assert hits, (
        "app/main.py перестал импортировать app.dd — либо шов мёртв, либо "
        "его пора убирать из guard'а вместе с модулем"
    )


def test_module_core_never_imports_module_ui():
    """``app/dd/{domain,application}`` не касаются ``app.dd.presentation``."""
    violations = _scan(DD_CORE_DIRS, _dd_core_layer_violations_in_tree)
    assert not violations, (
        "ядро модуля потянуло его UI — связь только через attach:\n"
        + "\n".join(f"{p}:{ln}: {t}" for p, ln, t in violations)
    )
    # sanity: правило живое — snippet с запрещённым импортом ловится
    snippet = "from app.dd.presentation.sheet import DndSheet\n"
    assert _dd_core_layer_violations_in_tree(
        ast.parse(snippet), Path("app/dd/application/x.py")
    ), "правило ядро→UI модуля потеряло зубы"


def test_module_tree_mirrors_the_kernel_layers():
    """Форма пакета (design Д3): четыре слоя-пакета есть, façade на месте."""
    for layer in ("domain", "application", "infrastructure", "presentation"):
        assert (MODULE_ROOT / layer / "__init__.py").is_file(), (
            f"слой модуля app/dd/{layer} потерян (дерево повторяет слои ядра)"
        )
    assert (MODULE_ROOT / "module.py").is_file()


def test_protocol_stub_bodies_stay_inert_placeholders():
    """Precedent test_sheet_field_model 6.5.4: a Protocol's contract is the
    type shape, not behavior — its stub bodies are called directly and must
    stay inert (return nothing, touch no state). This pin is also the reason
    the ellipsis lines survive the 100 % coverage gate: the contract is
    consumed, never implemented. async-тела (поиск/кандидаты внешних источников)
    раскрываются только await'ом — их многоточия покрывает async-побратим ниже."""
    from app.presentation.modules.protocol import GameSystemModule

    assert GameSystemModule.enabled.fget(None) is None
    assert GameSystemModule.attach(None, None, None) is None
    assert GameSystemModule.detach(None) is None
    # add-dnd-game-face (design Д1): внешние двери того же протокола и самого
    # источника — те же безмолвные многоточия
    from app.presentation.modules.protocol import ExternalEntitySource

    assert GameSystemModule.external_sources.fget(None) is None
    assert ExternalEntitySource.type_descriptors.fget(None) is None
    assert ExternalEntitySource.visible.fget(None) is None
    assert ExternalEntitySource.card_source(None, "spell", "x") is None
    assert ExternalEntitySource.resolve_mention(None, "spell", "x") is None
    assert ExternalEntitySource.card_tabs(None, None) is None
    assert ExternalEntitySource.event_marks(None, ()) is None


async def test_protocol_async_stub_bodies_return_nothing():
    """Тот же безмолвный контракт на async-дверях ExternalEntitySource: тело
    многоточие выполняется в None (контракт потребляется, не реализуется)."""
    from app.presentation.modules.protocol import ExternalEntitySource

    assert await ExternalEntitySource.search(None, "q") is None
    assert await ExternalEntitySource.mention_candidates(None, "q") is None
    assert await ExternalEntitySource.warm(None) is None  # task 6.2


def test_both_compositions_satisfy_the_kernel_protocol(qtbot):
    """Протокол — единственная поверхность договора; обе реализации ему
    соответствуют, stub безмолвен, façade включён между attach/detach.

    С attach'а группы 2 façade строит секцию окна (меню/бейдж), поэтому
    «окном» служит genuine QMainWindow со штатной menuBar — подставной
    ``object()`` больше не проходит, и это честная цена: контракт attach
    требует именно окно с меню."""
    from PySide6.QtWidgets import QMainWindow

    from app.dd.module import DndModule
    from app.presentation.modules.protocol import (
        GameSystemModule,
        NoopGameSystemModule,
    )

    assert isinstance(DndModule(), GameSystemModule)
    assert isinstance(NoopGameSystemModule(), GameSystemModule)

    stub = NoopGameSystemModule()
    stub.attach(object(), object())  # type: ignore[arg-type]
    assert stub.enabled is False
    stub.detach()

    window = QMainWindow()
    qtbot.addWidget(window)
    ordinary_menus = len(window.menuBar().actions())
    module = DndModule()
    assert module.enabled is False
    module.attach(window, object())  # type: ignore[arg-type]
    assert module.enabled is True
    assert len(window.menuBar().actions()) == ordinary_menus + 1
    module.detach()
    assert module.enabled is False
    # detach вернул строку меню в исходный вид — секция не оставляет следов
    assert len(window.menuBar().actions()) == ordinary_menus


# --------------------------------------------------------------------------
# Нарушения падают с файлом и строкой (control fakes)
# --------------------------------------------------------------------------


def test_planted_kernel_import_falls_the_isolation_guard(tmp_path, monkeypatch):
    """Подложный нарушитель правила 1: ядро импортирует app.dd — находка с
    файлом и строкой; тот же импорт из app/main.py легален (allow-list)."""
    monkeypatch.setattr("tests.test_dd_module_isolation.REPO_ROOT", tmp_path)
    kernel = tmp_path / "app" / "presentation"
    kernel.mkdir(parents=True)
    bad = kernel / "bad_view.py"
    bad.write_text("from app.dd.module import DndModule\n", encoding="utf-8")
    violations = _dd_import_violations_in_tree(
        ast.parse(bad.read_text(encoding="utf-8")), bad
    )
    assert len(violations) == 1
    path, lineno, text = violations[0]
    assert path == bad and lineno == 1
    assert "app/main.py" in text

    allowed = tmp_path / "app" / "main.py"
    allowed.write_text("from app.dd.module import DndModule\n", encoding="utf-8")
    assert _dd_import_violations_in_tree(
        ast.parse(allowed.read_text(encoding="utf-8")), allowed
    ) == []


def test_planted_module_core_ui_import_falls_the_layer_guard(tmp_path, monkeypatch):
    """Подложный нарушитель правила 2: ядро модуля тянет его presentation."""
    monkeypatch.setattr("tests.test_dd_module_isolation.REPO_ROOT", tmp_path)
    core = tmp_path / "app" / "dd" / "application"
    core.mkdir(parents=True)
    bad = core / "bad_service.py"
    bad.write_text(
        "from app.dd.presentation import sheet\n", encoding="utf-8"
    )
    violations = _dd_core_layer_violations_in_tree(
        ast.parse(bad.read_text(encoding="utf-8")), bad
    )
    assert len(violations) == 1
    path, lineno, text = violations[0]
    assert path == bad and lineno == 1 and "attach" in text
    # тот же импорт из слоя presentation модуля — легален (не ядро)
    views = tmp_path / "app" / "dd" / "presentation"
    views.mkdir(parents=True)
    legal = views / "sheet.py"
    legal.write_text("from app.dd.presentation.helper import X\n", encoding="utf-8")
    assert _dd_core_layer_violations_in_tree(
        ast.parse(legal.read_text(encoding="utf-8")), legal
    ) == []


def test_import_forms_all_reach_the_guard():
    """Все синтаксические формы импорта пакета ловятся, похожие имена — нет."""
    cases = {
        "import app.dd\n": True,
        "import app.dd as m\n": True,
        "import app.dd.module\n": True,
        "import app.dd.module as m\n": True,
        "from app import dd\n": True,
        "from app import dd as m\n": True,
        "from app.dd import module\n": True,
        "from app.dd.module import DndModule\n": True,
        "from app.dd.domain import things\n": True,
        # из app/presentation/views/x.py: в app.dd ведёт только level=3
        "from ...dd import module\n": True,
        "from ...dd.module import DndModule\n": True,
        "from ..dd import module\n": False,  # это app.presentation.dd
        "from . import dd\n": False,  # это app.presentation.views.dd
        # похожие имена — другие пакеты
        "import app.ddx\n": False,
        "from app.dd_extra import thing\n": False,
        "from app.addon import dd\n": False,
        'PROSE = "app.dd.module"\n': False,
    }
    for source, should_hit in cases.items():
        violations = _dd_import_violations_in_tree(
            ast.parse(source), Path("app/presentation/views/x.py")
        )
        if should_hit:
            assert len(violations) == 1, source
            assert violations[0][1] == 1, source
        else:
            assert not violations, source
    # относительные заходы из файла пакета app (own_parts == ["app"])
    for source in ("from . import dd\n", "from .dd import module\n"):
        violations = _dd_import_violations_in_tree(
            ast.parse(source), Path("app/some_top_file.py")
        )
        assert len(violations) == 1, source


def test_docstring_prose_is_not_an_import():
    source = (
        '"""Экран ядра больше не импортирует app.dd — текст документа."""\n'
        "\n# app.dd.module — комментарий, не узел\n"
    )
    assert _dd_import_violations_in_tree(
        ast.parse(source), Path("app/presentation/views/x.py")
    ) == []


# --------------------------------------------------------------------------
# Правило 3: модуль не открывает дверь реестра сам (add-dnd-game-face, Д2)
# --------------------------------------------------------------------------


def test_module_never_opens_the_external_registration_door():
    """Ни один файл ``app/dd`` не зовёт ``register_external`` — регистрация
    внешних типов — право точки сборки (design Д2)."""
    violations = _scan((MODULE_ROOT,), _external_registration_violations_in_tree)
    assert not violations, (
        "app/dd снова регистрирует типы в обход composition — объявляй через "
        "type_descriptors источников:\n"
        + "\n".join(f"{p}:{ln}: {t}" for p, ln, t in violations)
    )
    # sanity: правило живое — оба синтаксических snippet'а ловятся
    for snippet in (
        "from app.domain import entity_registry\n"
        "entity_registry.register_external([])\n",
        "from app.domain.entity_registry import register_external\n"
        "register_external(batch)\n",
    ):
        assert _external_registration_violations_in_tree(
            ast.parse(snippet), Path("app/dd/application/x.py")
        ), "правило внешней регистрации потеряло зубы"


def test_external_registration_prose_and_definition_are_not_calls():
    """Дочерние формы, легальные по закону AST: строки/докстринги и само
    определение двери (не Call-узел) — не нарушения."""
    source = (
        '"""Мы НЕ зовём register_external сами — это право main.py."""\n'
        "\n"
        "# register_external(batch) — комментарий\n"
        "def register_external(descriptors):\n"
        "    pass\n"
    )
    assert _external_registration_violations_in_tree(
        ast.parse(source), Path("app/dd/application/x.py")
    ) == []
    # тот же вызов вне app/dd — чужое дерево, правило модуля его не касается
    assert _external_registration_violations_in_tree(
        ast.parse("entity_registry.register_external([])\n"),
        Path("app/main.py"),
    ) == []


def test_planted_module_registration_call_falls_the_isolation_guard(tmp_path, monkeypatch):
    """Подложный нарушитель правила 3: файл модуля зовёт дверь реестра —
    находка с файлом и строкой (тот же закон REPO_ROOT, что у правил 1/2)."""
    monkeypatch.setattr("tests.test_dd_module_isolation.REPO_ROOT", tmp_path)
    core = tmp_path / "app" / "dd" / "application"
    core.mkdir(parents=True)
    bad = core / "bad_types.py"
    bad.write_text(
        "from app.domain import entity_registry\n"
        "\n"
        "def publish(batch):\n"
        "    entity_registry.register_external(batch)\n",
        encoding="utf-8",
    )
    violations = _external_registration_violations_in_tree(
        ast.parse(bad.read_text(encoding="utf-8")), bad
    )
    assert len(violations) == 1
    path, lineno, text = violations[0]
    assert path == bad and lineno == 4
    assert "register_external" in text and "main.py" in text
