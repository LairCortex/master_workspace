"""Хранилище датасетов модуля (add-dnd-module-foundation, task 3.1).

Юнит-контур на ``tmp_path`` (design Д12: «хранилище — tmp_path»): каталог
создаётся при первом обращении, пара ``*.json`` + ``*.meta.json`` пишется
атомарно через tmp+rename, имя выводится из валидированного ``id``,
повреждённые сайдки деградируют, а не исчезают. Правила подтверждения и
защита SRD — уровень сервиса, они в соседнем файле; здесь — только перо и
бумага.
"""
from __future__ import annotations

import json

import pytest

from app.dd.domain.dataset import DatasetMeta, DatasetSource
from app.dd.infrastructure.dataset_storage import DatasetStorage
from app.infrastructure import paths


def _meta(source: DatasetSource = DatasetSource.HOMEBREW) -> DatasetMeta:
    return DatasetMeta(source=source, imported_at="2026-10-09", sha256="ab" * 32)


def _doc(dataset_id: str, title: str) -> str:
    return json.dumps({"id": dataset_id, "title": title})


# ── адрес полки и валидация имени ────────────────────────────────────────────


def test_default_root_is_the_paths_constant(monkeypatch, tmp_path):
    """Каталог берётся из единой константы ``app.infrastructure.paths`` —
    единственный источник пути (AGENTS: пути приложения только в paths.py)."""
    monkeypatch.setattr(paths, "DATASETS_DIR", tmp_path / "каталог")
    assert DatasetStorage().root == tmp_path / "каталог"


@pytest.mark.parametrize(
    "bad_id",
    ["", ".", "..", ".hidden", "hidden.", "a/b", "a\\b", "A-bad", "x" * 65, "a b", "~/x"],
)
def test_invalid_ids_never_become_a_file_name(bad_id, tmp_path):
    storage = DatasetStorage(tmp_path)
    with pytest.raises(ValueError):
        storage.document_path(bad_id)
    with pytest.raises(ValueError):
        storage.meta_path(bad_id)
    with pytest.raises(ValueError):
        storage.spells_path(bad_id)


@pytest.mark.parametrize("good_id", ["srd51", "home-brew_1.2", "x"])
def test_valid_ids_shape_the_pair_names(good_id, tmp_path):
    storage = DatasetStorage(tmp_path)
    assert storage.document_path(good_id) == tmp_path / f"{good_id}.json"
    assert storage.meta_path(good_id) == tmp_path / f"{good_id}.meta.json"
    assert storage.spells_path(good_id) == tmp_path / f"{good_id}.spells.txt"


# ── создание каталога при первом обращении ──────────────────────────────────


def test_catalog_created_on_first_list(tmp_path):
    storage = DatasetStorage(tmp_path / "datasets")
    assert storage.list_datasets() == []
    assert (tmp_path / "datasets").is_dir()


def test_catalog_created_on_first_save(tmp_path):
    storage = DatasetStorage(tmp_path / "datasets")
    storage.save("srd51", _doc("srd51", "SRD"), _meta())
    assert (tmp_path / "datasets" / "srd51.json").is_file()


# ── запись/чтение пары ───────────────────────────────────────────────────────


def test_save_writes_the_pair_and_load_reads_it_back(tmp_path):
    storage = DatasetStorage(tmp_path)
    storage.save("my-pack", _doc("my-pack", "Мой набор"), _meta())
    assert storage.load_content("my-pack") == _doc("my-pack", "Мой набор")
    meta = storage.load_meta("my-pack")
    assert meta == _meta()


def test_load_absent_shelf_is_none(tmp_path):
    storage = DatasetStorage(tmp_path)
    assert storage.load_content("nope") is None
    assert storage.load_meta("nope") is None


def test_save_replaces_document_and_sidecar(tmp_path):
    """Уровень хранилища — просто перо: повторная запись заменяет полку
    целиком (правило «только с подтверждения» — сервисный, см. соседний файл)."""
    storage = DatasetStorage(tmp_path)
    storage.save("pack", _doc("pack", "Первая"), _meta())
    storage.save("pack", _doc("pack", "Вторая"), _meta(DatasetSource.HOMEBREW))
    assert json.loads(storage.load_content("pack"))["title"] == "Вторая"
    # ни осколков, ни дублей: на полке ровно пара файлов
    # (в tmp_path живёт и сид фикстуры isolated_dd_datasets_dir — считаем полку)
    assert sorted(p.name for p in storage.root.glob("pack*")) == [
        "pack.json",
        "pack.meta.json",
    ]


def test_atomic_write_leaves_no_tmp_and_keeps_old_on_replace_failure(tmp_path, monkeypatch):
    """tmp+rename (design Д4): после успеха временного файла нет; если сам
    rename упал, старые байты документа целы и мусор не остаётся."""
    storage = DatasetStorage(tmp_path)
    storage.save("pack", _doc("pack", "Старый"), _meta())
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())

    import os

    def refuse(*_args):
        raise OSError("disk on fire")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError):
        storage.save("pack", _doc("pack", "Новый"), _meta())
    assert json.loads(storage.load_content("pack"))["title"] == "Старый"
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())


# ── список хранилища ─────────────────────────────────────────────────────────


def test_list_reads_title_from_the_document_itself(tmp_path):
    storage = DatasetStorage(tmp_path)
    storage.save(
        "zeta", _doc("zeta", "Zeta-набор"), _meta(DatasetSource.SRD)
    )
    storage.save("alpha", _doc("alpha", "Alpha-набор"), _meta())
    entries = storage.list_datasets()
    assert [e.dataset_id for e in entries] == ["alpha", "zeta"]  # по id
    assert [e.title for e in entries] == ["Alpha-набор", "Zeta-набор"]
    assert [e.meta.source for e in entries] == [
        DatasetSource.HOMEBREW,
        DatasetSource.SRD,
    ]
    assert entries[0].meta.imported_at == "2026-10-09"
    assert entries[0].meta.check_errors is None


def test_list_skips_meta_files_and_tolerates_damaged_shelves(tmp_path):
    storage = DatasetStorage(tmp_path)
    storage.save("fine", _doc("fine", "Норм"), _meta())
    # повреждённый документ — полка остаётся в списке под именем файла;
    (tmp_path / "broken.json").write_text("{не json", encoding="utf-8")
    # документ без сайдки — деградация в homebrew/не проверялся;
    (tmp_path / "nometa.json").write_text(_doc("nometa", "Без сайдки"), encoding="utf-8")
    # сайдка повреждена/врёт — читаются прощающие значения;
    (tmp_path / "fine.meta.json").write_text("не JSON", encoding="utf-8")
    (tmp_path / "weird.meta.json").write_text(
        json.dumps(
            {
                "source": "mystery",
                "imported_at": 7,
                "sha256": None,
                "check_errors": True,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "weird.json").write_text(json.dumps({"id": "weird"}), encoding="utf-8")

    entries = {e.dataset_id: e for e in storage.list_datasets()}
    assert set(entries) == {"fine", "broken", "nometa", "weird"}
    assert entries["fine"].meta == DatasetMeta(
        source=DatasetSource.HOMEBREW, imported_at="", sha256=""
    )  # повреждённая сайдка → прощающие значения
    assert entries["broken"].title == "broken"
    assert entries["nometa"].meta.source is DatasetSource.HOMEBREW
    assert entries["weird"].title == "weird"  # нет title → id
    assert entries["weird"].meta.source is DatasetSource.HOMEBREW  # чужой source
    assert entries["weird"].meta.check_errors is None  # bool — не число ошибок


# ── итог последней проверки и списки слагов ─────────────────────────────────


def test_set_check_errors_rewrites_sidecar_only(tmp_path):
    storage = DatasetStorage(tmp_path)
    storage.save("pack", _doc("pack", "Пак"), _meta(DatasetSource.SRD))
    storage.set_check_errors("pack", 3)
    meta = storage.load_meta("pack")
    assert meta.check_errors == 3
    assert meta.source is DatasetSource.SRD  # остальные поля сохранены
    assert meta.imported_at == "2026-10-09"


def test_set_check_errors_requires_the_shelf(tmp_path):
    storage = DatasetStorage(tmp_path)
    with pytest.raises(KeyError):
        storage.set_check_errors("ghost", 1)


def test_spell_slugs_roundtrip_and_absence(tmp_path):
    storage = DatasetStorage(tmp_path)
    storage.save("srd51", _doc("srd51", "SRD"), _meta(DatasetSource.SRD))
    assert storage.load_spell_slugs("srd51") is None  # списка нет — проверки слагов пропускаются
    storage.save_spell_slugs("srd51", ("fireball", "shield"))
    assert storage.load_spell_slugs("srd51") == ("fireball", "shield")
    storage.save_spell_slugs("srd51", ())  # пустой список — пустой файл
    assert storage.load_spell_slugs("srd51") == ()
