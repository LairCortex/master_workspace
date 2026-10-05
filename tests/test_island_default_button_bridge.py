"""Guard PR-029: мост Return→``defaultButton`` живёт в одном месте.

Остров объявляет маркер действия по умолчанию ``readonly property Item
defaultButton: <кнопка>``, а Qt-механика ``QDialog`` его не видит: внутри
острова нет ``QPushButton`` с ``autoDefault``, поэтому Return обязан читать и
нажимать маркер Python-мост. Это одно знание (какие клавиши, где лежит маркер,
когда он его берёт) принадлежит mixin'у островной жизни —
``app/presentation/qml/island.py::IslandDialogMixin.take_island_default_key``.

До PR-029 тот же трёхстрочный мост был размазан копипастой по фасадом
``app/presentation/views/**``: xlsx и image имели копию, диалог события и
карточка сущности — нет, и их Enter молчал при объявленном маркере
(spec qml-shell «Минразмер и defaultButton»). Guard и мешает третьему
забытому фасаду, и не даёт возврату копипасты прорасти незамеченным.

Долг, зафиксированный белым списком (следующий срез, не этот): четыре фасада
чар-листов всё ещё читают маркер сами. Их мосты старше PR-029, работают живьём
и несут свои условия (``not read_only`` у листа заполнения, где кнопка скрыта,
«no-op без выделения» у списка), поэтому переводится отдельным срезом с их
же пинами — молча расширять белый список нельзя.

Механика — AST-скан (прецеденты ``tests/test_no_dialog_exec.py``,
``tests/test_architecture_layers.py``): литерал ``"defaultButton"`` узла
``ast.Constant``, а не упоминание в докстринге или комментарии.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
#: фасадное дерево, где мост обязан читаться, а не переизобретаться
VIEWS_ROOT = REPO_ROOT / "app" / "presentation" / "views"
#: имя маркера, читаемое из QML через ``root.property(...)``
MARKER_NAME = "defaultButton"
#: единственное место, где маркер читается
MECHANISM_FILE = REPO_ROOT / "app" / "presentation" / "qml" / "island.py"
#: известный долг (следующий срез): фасады чар-листов со своими условиями
CHAR_SHEET_DEBT = frozenset(
    {
        "editor_dialog.py",
        "fill_dialog.py",
        "list_dialog.py",
        "preset_dialog.py",
    }
)
#: фасады, уже переведённые на общий мост (PR-029)
MIGRATED_FACADES = (
    "xlsx_import_dialog.py",
    "image_viewer_dialog.py",
    "event_dialog.py",
    "entity_card_dialog.py",
)


def _marker_reader_files() -> list[Path]:
    """Фасады под views/, читающие литерал маркера в коде (не в тексте)."""
    readers: list[Path] = []
    assert VIEWS_ROOT.is_dir(), f"область скана сломана: {VIEWS_ROOT}"
    for path in sorted(VIEWS_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.Constant) and node.value == MARKER_NAME
            for node in ast.walk(tree)
        ):
            readers.append(path)
    return readers


def _bridge_call_sites(path: Path) -> int:
    """Сколько раз фасад зовёт общий мост ``take_island_default_key``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "take_island_default_key"
    )


def test_marker_is_read_by_the_mixin_and_the_debt_only():
    """Зелёное дерево: ни один фасад вне белого списка долга не читает маркер —
    остальные едут через ``take_island_default_key``."""
    readers = _marker_reader_files()
    offenders = [p for p in readers if p.name not in CHAR_SHEET_DEBT]
    assert not offenders, (
        "Return→defaultButton переизобретается в фасаде вместо общего моста "
        f"{MECHANISM_FILE.relative_to(REPO_ROOT)} (PR-029, принцип 2 AGENTS "
        "«одно знание — одно место»):\n"
        + "\n".join(str(p.relative_to(REPO_ROOT)) for p in offenders)
    )
    # Sanity области скана: белый список — не декорация, а зафиксированный долг
    # ровно из этих четырёх файлов (срез-перевод обязан обновить его, а не молча
    # оставить пустым и «победившим»).
    assert {p.name for p in readers} == set(CHAR_SHEET_DEBT), (
        "состав долга разъехался: читают маркер "
        f"{sorted(p.name for p in readers)}, зафиксирован "
        f"{sorted(CHAR_SHEET_DEBT)}"
    )


def test_migrated_facades_stay_marker_free():
    """Переведённые фасады не оставляют личной копии моста и зовут общий."""
    readers = {p.name for p in _marker_reader_files()}
    for facade in MIGRATED_FACADES:
        assert facade not in readers, f"{facade} снова читает маркер сам"
        path = VIEWS_ROOT / facade
        assert _bridge_call_sites(path) == 1, (
            f"{facade} обязан звать общий мост ровно один раз "
            "(keyPressEvent → take_island_default_key)"
        )


def test_the_mixin_is_the_single_marker_reader():
    """Механизм на месте: читает маркер ровно mixin, и ровно один раз."""
    tree = ast.parse(MECHANISM_FILE.read_text(encoding="utf-8"))
    reads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == MARKER_NAME
    ]
    assert len(reads) == 1, (
        "мост mixin перестал быть единственным читателем маркера — знание "
        "снова размазано (PR-029)"
    )


def test_planted_marker_read_in_a_facade_is_caught(tmp_path, monkeypatch):
    """Возврат копипасты ловится: фасад, читающий маркер сам, краснеет."""
    views = tmp_path / "views"
    views.mkdir(parents=True)
    (views / "bad_dialog.py").write_text(
        "class BadDialog:\n"
        "    def keyPressEvent(self, event):\n"
        '        marker = self._root.property("defaultButton")\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("tests.test_island_default_button_bridge.VIEWS_ROOT", views)
    readers = _marker_reader_files()
    assert [p.name for p in readers] == ["bad_dialog.py"]
