# Proposal: add-character-sheet-p

## Why

Стол (D1) закрывает заполнение в LAN. Часть игроков хочет бумагу или правку в Acrobat/Preview. Сейчас из Design нельзя выгрузить шаблон в `.pdf`. P — последний фичер эпика: пустой fillable PDF текущего чертежа.

Зависит от [`add-character-sheet-a1`](../add-character-sheet-a1/), [`add-character-sheet-a-playable`](../add-character-sheet-a-playable/), [`add-character-sheet-a-editor`](../add-character-sheet-a-editor/). Экземпляр (B), стол (D1) и пресеты (C) не требуются.

## What Changes

- Из открытого Design: кнопка «Экспорт в PDF…» рядом с «Сохранить».
- Пикер файла; имя по умолчанию = имя шаблона; коллизия — диалог ОС. Печать и автооткрытие файла нет.
- Источник — канвас как есть (в т.ч. dirty). Зум Design не влияет. `schema_version` не меняется.
- Одна страница шаблона = одна страница PDF (A4, ориентация шаблона), без зазора ленты. 1:1 pt.
- AcroForm: text, textarea, checkbox, number, dropdown. Дефолт виджета = то, что на канвасе.
- Рисунок: label, rect, line, image (рамка + битмап ImageStore; битое/пустое → пустая рамка, экспорт жив). Image в Acrobat не виджет.
- Без JS: number — строка; dropdown — список, кастом не цель.
- Обратного импорта PDF в шаблон или экземпляр нет. Стол и Fill не трогаем.
- Runtime: PDF-библиотека (reportlab). Тесты читают поля через pypdf (dev).

Не входит: печать, fillable image, импорт PDF, экспорт из списка/Fill/хоста, заполненный экземпляр, софт-AP, телефон.

## Capabilities

### New Capabilities

- `character-sheet-pdf`: запись fillable PDF из макета шаблона (страницы, виджеты, рисунок, картинки, ошибки файла).

### Modified Capabilities

- `character-sheet-editor`: кнопка экспорта в Design, пикер, отсутствие печати и автооткрытия.

## Impact

- `reportlab` в runtime `pyproject.toml`; `pypdf` в `[dev]`; `hiddenimports` в `nri_manager.spec`.
- Domain/сервис экспорта; кнопка в `editor_dialog`; ImageStore только чтение байт.
- Тесты offscreen: поля/страницы/картинки через pypdf; UI пикера. Без сети.
- `docs/CHANGELOG.md`, `docs/character-sheets-roadmap.md`.
- Схема БД и `schema_version` шаблона не меняются.
