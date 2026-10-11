"""Хранилище гримуаров модуля (add-dnd-game-face, task 4.2; design Д8).

Юнит-контур на ``tmp_path`` (тот же дуэт, что у тестов датасетного хранилища):
каталог создаётся при первом обращении, файл пишется атомарно через tmp+rename,
имя выводится из валидированного id, нечитаемый файл остаётся в списке под
именем файла. Подтверждение замены — уровень сервиса (соседний файл); здесь
только перо и бумага.
"""
from __future__ import annotations

import json
import os

import pytest

from app.dd.infrastructure.grimoire_storage import GrimoireStorage
from app.infrastructure import paths
from tests.dd.grimoire_fixtures import (
    content_of,
    foundry_compendium_export,
    foundry_item_list_export,
)


def _storage(tmp_path) -> GrimoireStorage:
    return GrimoireStorage(tmp_path / "grimoires")


# ── адрес полки ─────────────────────────────────────────────────────────────


def test_default_root_is_the_paths_constant(monkeypatch, tmp_path):
    """Путь — из единой константы ``app.infrastructure.paths`` (AGENTS)."""
    monkeypatch.setattr(paths, "GRIMOIRES_DIR", tmp_path / "гримуары")
    assert GrimoireStorage().root == tmp_path / "гримуары"


@pytest.mark.parametrize(
    "bad_id",
    ["", ".", "..", ".hidden", "hidden.", "a/b", "a\\b", "A-bad", "x" * 65, "a b", "~/x"],
)
def test_invalid_id_never_becomes_a_file_name(bad_id, tmp_path):
    storage = GrimoireStorage(tmp_path)
    with pytest.raises(ValueError):
        storage.document_path(bad_id)
    with pytest.raises(ValueError):
        storage.save(bad_id, "{}")
    with pytest.raises(ValueError):
        storage.load_content(bad_id)
    with pytest.raises(ValueError):
        storage.exists(bad_id)


@pytest.mark.parametrize("good_id", ["tina-grimoire", "my-spells_1.2", "x"])
def test_valid_ids_shape_the_file_name(good_id, tmp_path):
    storage = GrimoireStorage(tmp_path)
    assert storage.document_path(good_id) == tmp_path / f"{good_id}.json"


# ── создание каталога при первом обращении ─────────────────────────────────


def test_shelf_created_on_first_list(tmp_path):
    storage = _storage(tmp_path)
    assert storage.list_grimoires() == []
    assert (tmp_path / "grimoires").is_dir()


def test_shelf_created_on_first_save(tmp_path):
    storage = _storage(tmp_path)
    storage.save("tina", content_of(foundry_compendium_export()))
    assert (tmp_path / "grimoires" / "tina.json").is_file()


def test_no_access_no_directory(tmp_path):
    """Ни список, ни запись не случались — каталога нет (ленивость Д4)."""
    storage = _storage(tmp_path)
    assert storage.root == tmp_path / "grimoires"
    assert not storage.root.exists()


# ── запись и чтение ─────────────────────────────────────────────────────────


def test_save_keeps_the_bytes_byte_identical(tmp_path):
    """Модуль гримуары не правит: то, что принял импорт, и лежит на полке."""
    storage = _storage(tmp_path)
    content = content_of(foundry_item_list_export())
    storage.save("world-items", content)
    assert storage.document_path("world-items").read_text(encoding="utf-8") == content
    assert storage.load_content("world-items") == content
    assert storage.exists("world-items")


def test_missing_shelf_reads_absent(tmp_path):
    storage = _storage(tmp_path)
    assert storage.load_content("ghost") is None
    assert not storage.exists("ghost")


def test_save_replaces_the_shelf(tmp_path):
    """Уровень хранилища — просто перо: повторная запись заменяет файл целиком
    (правило «только с подтверждением» сервисное)."""
    storage = _storage(tmp_path)
    storage.save("pack", json.dumps({"name": "Первый"}))
    storage.save("pack", json.dumps({"name": "Второй"}))
    assert json.loads(storage.load_content("pack"))["name"] == "Второй"
    assert sorted(p.name for p in storage.root.glob("pack*")) == ["pack.json"]


def test_atomic_write_leaves_no_tmp_and_keeps_old_on_replace_failure(
    tmp_path, monkeypatch
):
    """tmp+rename: после успеха временного файла нет; если rename упал, старые
    байты целы и мусор не остаётся."""
    storage = _storage(tmp_path)
    storage.save("pack", json.dumps({"name": "Старый"}))
    assert not any(p.name.endswith(".tmp") for p in storage.root.iterdir())

    def refuse(*_args):
        raise OSError("disk on fire")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError):
        storage.save("pack", json.dumps({"name": "Новый"}))
    assert json.loads(storage.load_content("pack"))["name"] == "Старый"
    assert not any(p.name.endswith(".tmp") for p in storage.root.iterdir())


# ── список хранилища ────────────────────────────────────────────────────────


def test_list_reads_title_from_the_document_itself(tmp_path):
    storage = _storage(tmp_path)
    storage.save("zeta", json.dumps({"name": "Гримуар Зеты"}, ensure_ascii=False))
    storage.save("anna", json.dumps({"title": "Заметки Анны"}, ensure_ascii=False))
    storage.save("bare", json.dumps([{"name": "Просто список"}], ensure_ascii=False))

    assert [(e.grimoire_id, e.title) for e in storage.list_grimoires()] == [
        ("anna", "Заметки Анны"),
        ("bare", "bare"),  # массив себя не называет — полка под именем файла
        ("zeta", "Гримуар Зеты"),
    ]


def test_list_survives_damaged_file(tmp_path, caplog):
    """Нечитаемый файл остаётся в списке под именем файла — список есть
    доказательство, что файл мастера на месте."""
    storage = _storage(tmp_path)
    storage.document_path("broken").parent.mkdir(parents=True, exist_ok=True)
    storage.document_path("broken").write_text("{битый", encoding="utf-8")
    storage.save("healthy", json.dumps({"name": "Целый"}))

    with caplog.at_level("WARNING"):
        assert [(e.grimoire_id, e.title) for e in storage.list_grimoires()] == [
            ("broken", "broken"),
            ("healthy", "Целый"),
        ]
    assert any("broken.json" in record.getMessage() for record in caplog.records)
