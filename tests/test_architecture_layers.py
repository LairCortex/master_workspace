"""Хранители границ архитектуры (изменение nri-0005, design D7; R5/R6 — nri-0011, design D5).

Шесть AST-проверок, механика — прецедент ``tests/test_no_qt_date_carriers.py``:
скан дерева импортов/вызовов, а не текстовый grep (докстринги и комментарии
не являются AST-узлами и остаются легальны). Каждое нарушение сообщает файл
и строку; сбой нельзя «починить» переименованием в подстроку или переносом
в комментарий.

1. Направление слоёв: ``app/application/**`` и ``app/domain/**`` не импортируют
   ``app.presentation`` (соединитель переехал в представление задачей 1.3,
   каталог пресетов — в домен задачей 1.1; список исключений пуст — design D7).
2. Граница БД: в ``app/presentation/**`` запрещены импорт ``AsyncSession``,
   импорт ORM-моделей ``app.infrastructure.db.models`` и вызовы
   ``commit()``/``rollback()`` (волна 5: единица работы + переименование слотов
   ``commit_*`` → ``apply_*``; список исключений пуст — решение grill).
3. Приватные имена между пакетами: импорт имени с ведущим ``_`` из пакета,
   отличного от пакета импортирующего, запрещён (тот же закон Деметры, что
   снял ``_TYPE_UNSET``/``_RELATED_CONFIG``/``repo._session``). Импорт
   приватного внутри своего пакета легален; псевдоним ``Public as _Public``
   импортирует публичное имя и не является нарушением. Обращение
   ``obj._x`` статически нерешаемо — его закрывают публичные контракты волн
   1/5/6 (`wiring.*`, `BaseRepository.session`, `fill_dialog.instance_id`).
4. Пин обхода реестра типов (A4): в прикладном/доменном слое не допускается
   словарь, где строковый литерал-тип сущности сопоставляется модели или
   репозиторию. Единоместные отображения живут вне области скана и ключуются
   `EntityType`: тип→ORM в `infrastructure/repositories/__init__.py`,
   тип→репозиторий в точке сборки `main.py` (design D2).
5. (nri-0011, design D5) Представление не знает конкретный класс LLM-провайдера:
   в ``app/presentation/**`` запрещён импорт ``RemoteLlmProvider``, его модуля
   и псевдонима модуля ``remote_provider`` — единственная фабрика провайдеров
   собирается в точке сборки ``main.py`` и внедряется параметром.
6. (nri-0011, design D5) Единственный источник статусов подключения LLM:
   строковые литералы значений ``LlmStatus`` запрещены в Python-коде ``app/``
   вне модуля-источника ``app/application/services/llm_status.py`` (QML/QJS
   не сканируются; метки ``active``/``disabled`` не затрагиваются).
"""
from __future__ import annotations

import ast
from pathlib import Path

from app.application.services.llm_status import LlmStatus
from app.domain.enums.entity_type import EntityType

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = REPO_ROOT / "app"

#: откуда запрещён импорт presentation (прикладной и доменный слои)
LAYER_GUARD_DIRS = (APP_ROOT / "application", APP_ROOT / "domain")
#: где запрещены сессия/ORM/завершение транзакции
DB_GUARD_DIR = APP_ROOT / "presentation"
#: где запрещены словари тип→модель/репозиторий в обход реестра
REGISTRY_GUARD_DIRS = (APP_ROOT / "application", APP_ROOT / "domain")
#: откуда запрещён импорт конкретного LLM-провайдера (R5)
PROVIDER_GUARD_DIRS = (APP_ROOT / "presentation",)
#: где запрещены литералы статусов LLM вне источника (R6)
LITERAL_GUARD_DIRS = (APP_ROOT,)

#: строковые значения EntityType — ключи-маркеры параллельных словарей (A4)
ENTITY_TYPE_VALUES = frozenset(member.value for member in EntityType)
#: окончания имён классов, по которым значение словаря считается моделью/репозиторием
STORAGE_SUFFIXES = ("Model", "Repository")

#: конкретный класс LLM-провайдера и его модуль — имя и путь под запретом (R5)
CONCRETE_PROVIDER_CLASS = "RemoteLlmProvider"
CONCRETE_PROVIDER_MODULE = "app.infrastructure.llm.remote_provider"
#: модуль-источник статусов подключения LLM — единственное место литералов (R6)
LLM_STATUS_SOURCE = APP_ROOT / "application" / "services" / "llm_status.py"
#: текстовые значения статусов — выводятся из самого перечисления (R6)
LLM_STATUS_VALUES = frozenset(member.value for member in LlmStatus)


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


def _package_parts(path: Path) -> list[str]:
    """Каталожные части файла относительно корня репозитория (без имени файла).

    Для синтетических путей вне репозитория (``Path("app/...")`` из кейсов на
    snippets) — части как есть: схема ``app/<pkg>`` от них работает.
    """
    try:
        return list(path.resolve().relative_to(REPO_ROOT).parts[:-1])
    except ValueError:
        return list(path.parts[:-1])


def _top_package(parts: list[str]) -> str:
    """Пакет верхнего уровня по схеме ``app.<pkg>`` (например ``app.presentation``)."""
    return ".".join(parts[:2]) if len(parts) >= 2 else ".".join(parts)


def _resolve_source_package(
    own_parts: list[str], module: str | None, level: int, alias_name: str = ""
) -> str:
    """Пакет-источник импорта: абсолютного или относительного (``from ..x``).

    ``from app import presentation``/``from app import _foo`` смотрят в
    подпакет/элемент самого ``app`` — источником считается ``app.<имя>``.
    """
    if level == 0:
        segments = (module or "").split(".")
        if segments == ["app"]:
            return f"app.{alias_name}"
        return _top_package(segments)
    base = own_parts[: len(own_parts) - (level - 1)] if level > 1 else list(own_parts)
    if module:
        base = base + module.split(".")
    return _top_package(base)


def _imports_db_models(node: ast.AST, module: str | None, alias_name: str) -> bool:
    """Любой заход в модуль ORM-моделей ``app.infrastructure.db.models``."""
    if isinstance(node, ast.Import):
        return alias_name == "app.infrastructure.db.models" or alias_name.startswith(
            "app.infrastructure.db.models."
        )
    if module is None:
        return False
    if module == "app.infrastructure.db":
        return alias_name == "models"
    return module == "app.infrastructure.db.models" or module.startswith(
        "app.infrastructure.db.models."
    )


def _imports_concrete_provider(module: str | None, level: int, alias_name: str) -> bool:
    """Любая форма импорта конкретного провайдера (R5): класс, модуль, псевдоним модуля.

    Ловит ``from …remote_provider import RemoteLlmProvider``,
    ``import app…remote_provider [as x]`` и ``from …llm import remote_provider``;
    относительные формы перекрываются именами (класс/псевдоним модуля).
    """
    if alias_name in (CONCRETE_PROVIDER_CLASS, "remote_provider"):
        return True
    if level == 0 and module:
        return module == CONCRETE_PROVIDER_MODULE or module.endswith(
            ".llm.remote_provider"
        )
    return False


def _violations_in_tree(
    tree: ast.AST, path: Path, *,
    check_layers: bool = False, check_db: bool = False,
    check_private: bool = False, check_dicts: bool = False,
    check_provider: bool = False, check_status: bool = False,
) -> list[tuple[Path, int, str]]:
    violations: list[tuple[Path, int, str]] = []
    own_parts = _package_parts(path)
    own_package = _top_package(own_parts)
    # R6: единственный источник литералов статусов — сам модуль llm_status.py
    literals_allowed_here = path == LLM_STATUS_SOURCE

    def import_sources(node: ast.Import | ast.ImportFrom):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                yield node.module, node.level, alias
        else:
            for alias in node.names:
                yield alias.name, 0, alias

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for module, level, alias in import_sources(node):
                source_package = _resolve_source_package(
                    own_parts, module, level, alias.name
                )
                # R1: прикладной/доменный слой не видит представление
                if check_layers and source_package == "app.presentation":
                    violations.append((
                        path, node.lineno,
                        f"импорт из пакета «app.presentation» (модуль "
                        f"«{module or alias.name}») в слой «{own_package}» "
                        "запрещён (design D7)",
                    ))
                # R2: представление не видит сессию и ORM-модели
                if check_db:
                    if alias.name == "AsyncSession":
                        violations.append((
                            path, node.lineno,
                            "импорт «AsyncSession» в слой представления запрещён "
                            "(доступ к данным — только через сервисы, design D7)",
                        ))
                    if _imports_db_models(node, module, alias.name):
                        violations.append((
                            path, node.lineno,
                            f"импорт «{alias.name}» из модуля ORM-моделей "
                            f"«{module or alias.name}» в слой представления "
                            "запрещён (design D7)",
                        ))
                # R3: приватное имя из чужого пакета
                if check_private and alias.name.startswith("_") and alias.name != "*":
                    if source_package != own_package:
                        violations.append((
                            path, node.lineno,
                            f"импорт приватного имени «{alias.name}» из пакета "
                            f"«{source_package}» в пакет «{own_package}» запрещён "
                            "(только внутри своего пакета, design D7)",
                        ))
                # R5: представление не знает конкретный класс LLM-провайдера
                if check_provider and _imports_concrete_provider(
                    module, level, alias.name
                ):
                    violations.append((
                        path, node.lineno,
                        f"импорт конкретного LLM-провайдера «{CONCRETE_PROVIDER_CLASS}» "
                        f"(модуль «{module or alias.name}») — единственная фабрика "
                        "собирается в точке сборки main.py, представление "
                        "не импортирует его (nri-0011, design D5)",
                    ))
        elif check_db and isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in ("commit", "rollback"):
                violations.append((
                    path, node.lineno,
                    f"вызов «.{func.attr}()» в слое представления запрещён "
                    "(транзакцию завершает единица работы, design D4/D7)",
                ))
        elif check_dicts and isinstance(node, ast.Dict):
            violation = _parallel_type_dict(node)
            if violation is not None:
                violations.append((path, node.lineno, violation))
        elif (
            check_status
            and not literals_allowed_here
            and isinstance(node, ast.Constant)
            and node.value in LLM_STATUS_VALUES
        ):
            # R6: дубль строки статуса вне единственного источника
            violations.append((
                path, node.lineno,
                f"строковый литерал статуса подключения LLM «{node.value}» "
                f"вне модуля-источника «{LLM_STATUS_SOURCE.relative_to(APP_ROOT)}» "
                "запрещён — используется перечисление LlmStatus "
                "(nri-0011, design D5)",
            ))
    return violations


def _identifier_leaves(expr: ast.AST):
    """Имена классов/атрибутов, видимые в выражении-значении словаря."""
    for sub in ast.walk(expr):
        if isinstance(sub, ast.Name):
            yield sub.id
        elif isinstance(sub, ast.Attribute):
            yield sub.attr


def _parallel_type_dict(node: ast.Dict) -> str | None:
    """Текст нарушения, если словарь сопоставляет строковый тип с моделью/репозиторием."""
    storage_refs: list[str] = []
    has_type_literal = False
    for key, value in zip(node.keys, node.values):
        if (
            isinstance(key, ast.Constant)
            and isinstance(key.value, str)
            and key.value in ENTITY_TYPE_VALUES
        ):
            has_type_literal = True
        if isinstance(value, ast.Constant):
            continue
        leaves = [
            name for name in _identifier_leaves(value)
            if name.endswith(STORAGE_SUFFIXES)
        ]
        storage_refs.extend(leaves)
    if has_type_literal and storage_refs:
        return (
            "словарь «строковый тип сущности → "
            + ", ".join(sorted(set(storage_refs)))
            + "» в обход единого реестра (design D2: ключ — EntityType; "
            "тип↔ORM — infrastructure/repositories, тип↔репозиторий — main.py)"
        )
    return None


def _scan_source(source: str, path: Path, **checks: bool) -> list[tuple[Path, int, str]]:
    return _violations_in_tree(ast.parse(source), path, **checks)


def _format_violations(violations: list[tuple[Path, int, str]]) -> str:
    return "\n".join(
        f"{path.relative_to(REPO_ROOT)}:{lineno}: {text}"
        for path, lineno, text in violations
    )


def _scan_tree(roots: tuple[Path, ...], **checks: bool) -> list[tuple[Path, int, str]]:
    violations: list[tuple[Path, int, str]] = []
    for path in _collect_py_files(roots):
        violations.extend(_scan_source(path.read_text(encoding="utf-8"), path, **checks))
    return violations


_ALL_CHECKS = dict(
    check_layers=True, check_db=True, check_private=True, check_dicts=True
)


# --------------------------------------------------------------------------
# Зелёное дерево
# --------------------------------------------------------------------------

def test_repo_tree_respects_layer_direction():
    violations = _scan_tree(LAYER_GUARD_DIRS, check_layers=True)
    assert not violations, (
        "прикладной/доменный слой снова импортирует представление "
        "(исключения запрещены design D7):\n" + _format_violations(violations)
    )
    # sanity: скан не выродился — запрещённый корень действительно сканируется
    assert _collect_py_files(LAYER_GUARD_DIRS), "нет файлов под application/domain"


def test_repo_tree_keeps_db_out_of_presentation():
    violations = _scan_tree((DB_GUARD_DIR,), check_db=True)
    assert not violations, (
        "сессия/ORM/завершение транзакции вернулись в представление "
        "(единица работы — GameSessionUoW):\n" + _format_violations(violations)
    )


def test_repo_tree_has_no_private_imports_across_packages():
    violations = _scan_tree((APP_ROOT,), check_private=True)
    assert not violations, (
        "приватные имена снова пересекают пакеты:\n" + _format_violations(violations)
    )
    # sanity: легальныеSame-package импорты приватного есть — правило их не трогает
    same_package_private = [
        (path, name)
        for path in _collect_py_files((APP_ROOT,))
        for name in _same_package_private_imports(path)
    ]
    assert same_package_private, (
        "ожидались легальные same-package приватные импорты "
        "(например app.domain.game_calendar -> date_era._gregorian_key)"
    )


def _same_package_private_imports(path: Path) -> list[str]:
    own_parts = _package_parts(path)
    own_package = _top_package(own_parts)
    found: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            source = _resolve_source_package(own_parts, node.module, node.level)
            if source == own_package and any(
                alias.name.startswith("_") and alias.name != "*"
                for alias in node.names
            ):
                found.extend(a.name for a in node.names if a.name.startswith("_"))
    return found


def test_repo_tree_has_no_parallel_type_dicts():
    violations = _scan_tree(REGISTRY_GUARD_DIRS, check_dicts=True)
    assert not violations, (
        "в прикладном/доменном слое появился словарь тип→модель/репозиторий "
        "в обход реестра EntityType:\n" + _format_violations(violations)
    )
    # sanity: единые места живут вне области скана и они на месте (design D2)
    from app.infrastructure.repositories import ORM_MODEL_BY_ENTITY_TYPE
    assert ORM_MODEL_BY_ENTITY_TYPE, "инфраструктурный тип↔ORM словарь потерян"
    main_src = (APP_ROOT / "main.py").read_text(encoding="utf-8")
    assert "_build_entity_services" in main_src, (
        "тип↔репозиторий карта потеряна из точки сборки main.py"
    )


def test_repo_tree_keeps_concrete_provider_out_of_presentation():
    """R5: фабрика провайдеров — только в точке сборки, представление слепое."""
    violations = _scan_tree(PROVIDER_GUARD_DIRS, check_provider=True)
    assert not violations, (
        "конкретный LLM-провайдер вернулся в представление "
        "(единственная фабрика — main.py, nri-0011 design D5):\n"
        + _format_violations(violations)
    )
    # sanity: скан не выродился — запрещённый корень сканируется,
    # а провайдер по-прежнему собран ровно в точке сборки
    assert _collect_py_files(PROVIDER_GUARD_DIRS), "нет файлов под presentation"
    main_src = (APP_ROOT / "main.py").read_text(encoding="utf-8")
    assert main_src.count(f"{CONCRETE_PROVIDER_CLASS}(") == 1, (
        "фабрика провайдеров должна собираться ровно в одном месте main.py"
    )


def test_repo_tree_has_llm_status_literals_only_in_source():
    """R6: единственный источник текстовых статусов — модуль LlmStatus."""
    violations = _scan_tree(LITERAL_GUARD_DIRS, check_status=True)
    assert not violations, (
        "дубль строки статуса подключения LLM вернулся в app/ "
        "(единственный источник — llm_status.py, nri-0011 design D5):\n"
        + _format_violations(violations)
    )
    # sanity: модуль-источник на месте и содержит литералы — правило живое,
    # просто пропускает ровно этот путь (под другим именем тот же код ловится)
    assert LLM_STATUS_SOURCE.is_file(), "модуль-источник LlmStatus потерян"
    shifted = LLM_STATUS_SOURCE.with_name("not_a_source.py")
    assert _scan_source(
        LLM_STATUS_SOURCE.read_text(encoding="utf-8"), shifted, check_status=True
    ), "правило R6 потеряло зубы"


# --------------------------------------------------------------------------
# Нарушения падают с файлом и строкой
# --------------------------------------------------------------------------

def test_layer_violation_reports_file_and_line():
    source = (
        "from dataclasses import dataclass\n"
        "\n"
        "from app.presentation.views.entity_card_dialog import EntityCardDialog\n"
    )
    violations = _scan_source(
        source, Path("app/application/services/x.py"), check_layers=True
    )
    assert len(violations) == 1, violations
    path, lineno, text = violations[0]
    assert path == Path("app/application/services/x.py") and lineno == 3
    assert "app.presentation" in text and "app.application" in text


def test_db_violations_report_file_and_line():
    cases = {
        "from sqlalchemy.ext.asyncio import AsyncSession\n":
            (1, "AsyncSession"),
        "from app.infrastructure.db.models import CharacterModel\n":
            (1, "CharacterModel"),
        "async def save(self):\n    await self._session.commit()\n":
            (2, ".commit()"),
        "async def abort(self):\n    await self._session.rollback()\n":
        (2, ".rollback()"),
    }
    for source, (lineno, needle) in cases.items():
        violations = _scan_source(
            source, Path("app/presentation/viewmodels/x.py"), check_db=True
        )
        assert len(violations) == 1, (source, violations)
        path, got_line, text = violations[0]
        assert path == Path("app/presentation/viewmodels/x.py") and got_line == lineno
        assert needle in text


def test_relative_layer_import_reaches_presentation_is_violation():
    """from ..presentation.views import X из app/application/x_service.py — нарушение."""
    source = "from ..presentation.views import EventDialog\n"
    violations = _scan_source(
        source, Path("app/application/x_service.py"), check_layers=True
    )
    assert len(violations) == 1 and violations[0][1] == 1
    assert "app.presentation" in violations[0][2]


def test_private_import_across_packages_reports_file_and_line():
    source = "from app.domain.date_era import _gregorian_key\n"
    violations = _scan_source(
        source, Path("app/presentation/viewmodels/x.py"), check_private=True
    )
    assert len(violations) == 1, violations
    path, lineno, text = violations[0]
    assert path == Path("app/presentation/viewmodels/x.py") and lineno == 1
    assert "_gregorian_key" in text


def test_parallel_type_dict_reports_file_and_line():
    source = (
        "TYPE_TO_MODEL = {\n"
        '    "character": CharacterModel,\n'
        '    "item": ItemRepository,\n'
        "}\n"
    )
    violations = _scan_source(
        source, Path("app/application/services/x.py"), check_dicts=True
    )
    assert len(violations) == 1, violations
    path, lineno, text = violations[0]
    assert path == Path("app/application/services/x.py") and lineno == 1
    assert "CharacterModel" in text and "реестра" in text


def test_provider_import_forms_report_file_and_line():
    """R5 на snippets: все три формы импорта конкретного провайдера ловятся."""
    cases = {
        "from app.infrastructure.llm.remote_provider import RemoteLlmProvider\n": 1,
        "import app.infrastructure.llm.remote_provider as rp\n": 1,
        "from app.infrastructure.llm import remote_provider\n": 1,
    }
    for source, lineno in cases.items():
        violations = _scan_source(
            source, Path("app/presentation/views/x.py"), check_provider=True
        )
        assert len(violations) == 1, (source, violations)
        path, got_line, text = violations[0]
        assert path == Path("app/presentation/views/x.py") and got_line == lineno
        assert "RemoteLlmProvider" in text


def test_llm_status_literals_report_file_and_line():
    """R6 на snippets: литералы значений ловятся, члены перечисления — нет."""
    source = (
        "class Proxy:\n"
        "    def __init__(self):\n"
        '        self._status = "not_configured"\n'
        "\n"
        'DEFAULT = "ready"\n'
    )
    violations = _scan_source(
        source, Path("app/presentation/viewmodels/x.py"), check_status=True
    )
    # ast.walk обходит дерево широко-приоритетно — порядок находок не по строкам
    assert sorted(v[1] for v in violations) == [3, 5], violations
    assert all("LlmStatus" in v[2] for v in violations)
    # легальная форма: импорт перечисления и доступ к члену (не Constant-литерал)
    enum_source = (
        "from app.application.services.llm_status import LlmStatus\n"
        "\n"
        "s = LlmStatus.READY\n"
    )
    assert _scan_source(
        enum_source, Path("app/presentation/viewmodels/x.py"), check_status=True
    ) == []


def test_broken_file_lands_in_tree_message(tmp_path, monkeypatch):
    """Возврат нарушения в файл под app/ роняет древовидную проверку с файлом и строкой."""
    service = tmp_path / "application" / "services"
    service.mkdir(parents=True)
    target = service / "bad_service.py"
    target.write_text(
        "from app.presentation.views.event_dialog import EventDialog\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "tests.test_architecture_layers.LAYER_GUARD_DIRS", (tmp_path / "application",)
    )
    monkeypatch.setattr(
        "tests.test_architecture_layers.REPO_ROOT", tmp_path
    )
    violations = _scan_tree(LAYER_GUARD_DIRS, check_layers=True)
    assert len(violations) == 1
    path, lineno, _ = violations[0]
    assert path == target and lineno == 1


def test_planted_provider_import_falls_the_provider_guard(tmp_path, monkeypatch):
    """Подложный нарушитель R5: импорт RemoteLlmProvider в презентацию ловится деревом."""
    views = tmp_path / "presentation" / "views"
    views.mkdir(parents=True)
    target = views / "bad_view.py"
    target.write_text(
        "from app.infrastructure.llm.remote_provider import RemoteLlmProvider\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "tests.test_architecture_layers.PROVIDER_GUARD_DIRS",
        (tmp_path / "presentation",),
    )
    monkeypatch.setattr(
        "tests.test_architecture_layers.REPO_ROOT", tmp_path
    )
    violations = _scan_tree(PROVIDER_GUARD_DIRS, check_provider=True)
    assert len(violations) == 1
    path, lineno, _ = violations[0]
    assert path == target and lineno == 1


def test_planted_status_literal_falls_the_literal_guard(tmp_path, monkeypatch):
    """Подложный нарушитель R6: литерал статуса вне источника ловится всего app/."""
    vms = tmp_path / "presentation" / "viewmodels"
    vms.mkdir(parents=True)
    target = vms / "bad_vm.py"
    target.write_text('DEFAULT_STATUS = "ready"\n', encoding="utf-8")
    monkeypatch.setattr(
        "tests.test_architecture_layers.LITERAL_GUARD_DIRS",
        (tmp_path / "presentation",),
    )
    monkeypatch.setattr(
        "tests.test_architecture_layers.REPO_ROOT", tmp_path
    )
    violations = _scan_tree(LITERAL_GUARD_DIRS, check_status=True)
    assert len(violations) == 1
    path, lineno, _ = violations[0]
    assert path == target and lineno == 1


# --------------------------------------------------------------------------
# Ложные срабатывания отсутствует
# --------------------------------------------------------------------------

def test_docstring_and_prose_mentions_are_not_violations():
    source = (
        '"""Сервис больше не импортирует app.presentation, не трогает\n'
        'AsyncSession и не делает commit()/rollback()."""\n'
        "\n"
        "# app.presentation, AsyncSession, commit, rollback — просто текст\n"
    )
    assert _scan_source(source, Path("app/application/services/x.py"), **_ALL_CHECKS) == []


def test_provider_and_status_prose_in_docstrings_is_not_violation():
    """R5/R6 ловят синтаксические узлы: имена и строки-status'ы в прозе легальны."""
    source = (
        '"""Диалог больше не импортирует RemoteLlmProvider и не сравнивает\n'
        'статус со строкой "not_configured" или "ready" — это текст документа.»"""\n'
        "\n"
        "# RemoteLlmProvider, not_configured, ready — комментарий, не узел\n"
    )
    assert _scan_source(
        source,
        Path("app/presentation/views/x.py"),
        check_provider=True,
        check_status=True,
    ) == []


def test_longer_package_name_is_not_layer_violation():
    """app.presentation_extra — другой пакет (проверка по сегментам, не по подстроке)."""
    source = "from app.presentation_extra.thing import X\n"
    assert _scan_source(
        source, Path("app/application/services/x.py"), check_layers=True
    ) == []


def test_string_constant_naming_presentation_is_not_violation():
    source = 'module_name = "app.presentation.views.event_dialog"\n'
    assert _scan_source(
        source, Path("app/domain/registry.py"), **_ALL_CHECKS
    ) == []


def test_commit_substring_and_non_call_attrs_are_not_db_violations():
    """Точное совпадение атрибута: apply_drag/commit_protected-подобные имена и
    адрес метода (без вызова) не нарушения — прецедент переименований волны 5."""
    source = (
        "class Sheet:\n"
        "    def apply_drag(self):\n"
        "        self.guarded_commit_attribute = None\n"
        "\n"
        "s = Sheet()\n"
        "s.apply_drag()\n"
        "handler = s.guarded_commit_attribute\n"
    )
    assert _scan_source(
        source, Path("app/presentation/viewmodels/x.py"), check_db=True
    ) == []


def test_orm_like_names_outside_db_models_are_not_db_violations():
    """Такие же имена из легальных модулей (не app.infrastructure.db*) не ловятся."""
    source = (
        "from app.domain.entity_registry import descriptor\n"
        "from app.presentation.some_helper import build_model\n"
    )
    # правило B сканирует presentation-файлы; импорт доменного модуля легален
    assert _scan_source(
        source, Path("app/presentation/viewmodels/x.py"), check_db=True
    ) == []


def test_same_package_private_import_is_not_violation():
    """Реальный легальный кейс дерева: домен → домен (тот же пакет)."""
    source = "from app.domain.date_era import BC_YEAR_STEP, _gregorian_key\n"
    assert _scan_source(
        source, Path("app/domain/game_calendar.py"), check_private=True
    ) == []
    # и относительный импорт внутри пакета
    source2 = "from .popup import _MentionPopup\n"
    assert _scan_source(
        source2, Path("app/presentation/viewmodels/x.py"), check_private=True
    ) == []


def test_public_alias_with_underscore_is_not_violation():
    """`Public as _Public` (`game_launcher_dialog`, `main_window`) — псевдоним, не приват."""
    source = "from app.presentation.a import QmlPalette as _QmlPalette\n"
    assert _scan_source(
        source, Path("app/presentation/views/game_launcher_dialog.py"),
        check_private=True,
    ) == []


def test_registry_shaped_dicts_are_not_parallel_type_dicts():
    """Формы реестра и его потребителей: ключ-EntityType, ключи из реестра,
    строковые значения-метки (прецедент:xlsx_template) — не нарушения."""
    registry = (
        "ORM_MODEL_BY_ENTITY_TYPE = {\n"
        "    EntityType.CHARACTER: CharacterModel,\n"
        "    EntityType.ITEM: ItemRepository,\n"
        "}\n"
    )
    derived_keys = (
        "self._repos = {\n"
        '    entity_registry.descriptor(EntityType.CHARACTER).plural: character_repo,\n'
        "}\n"
    )
    label_dict = 'PLURALS = {"character": "персонажи", "rating": None}\n'
    unrelated = '{"model": ThingModel}\n'
    for source in (registry, derived_keys, label_dict, unrelated):
        assert _scan_source(
            source, Path("app/application/services/x.py"), check_dicts=True
        ) == [], source


def test_real_registry_consumers_are_not_parallel_type_dicts():
    """Живой SearchService (ключи из реестра) проходит проверку."""
    path = APP_ROOT / "application" / "services" / "search_service.py"
    violations = _scan_source(
        path.read_text(encoding="utf-8"), path, check_dicts=True
    )
    assert violations == [], _format_violations(violations)
