# Tasks: add-character-sheet-p

TDD. `QT_QPA_PLATFORM=offscreen python -m pytest`. Без сети. Печать, импорт PDF, хост, Fill, экземпляр не делать. `schema_version` не менять.

## 1. Зависимости

- [x] 1.1 Добавить `reportlab` в runtime `pyproject.toml`, `pypdf` в `[dev]`, `hiddenimports` в `nri_manager.spec` (D1). Проверка: `pip install -e ".[dev]"` проходит; `python -c "import reportlab, pypdf"` ок.

## 2. Рендер PDF

- [x] 2.1 Тесты: две страницы; альбомный mediabox; виджеты text/textarea/checkbox/number/dropdown по `id` и value; label/rect/image не в `get_fields`; кириллица в label; number «3.5» без JS; битый image_id — файл есть и text на месте. Проверка: `tests/domain/test_character_sheet_pdf.py` красные до 2.2.
- [x] 2.2 `write_sheet_pdf` (D2–D4): tempfile+replace. Проверка: тесты 2.1 зелёные.

## 3. Design

- [x] 3.1 Тесты: кнопка «Экспорт в PDF…» рядом с «Сохранить»; отмена пикера не зовёт write; suggested name = имя шаблона + `.pdf`; в list_dialog кнопки нет. Проверка: `tests/presentation/test_character_sheet_editor_dialog.py` (+ list) красные до 3.2.
- [x] 3.2 Кнопка, пикер, сбор байт ImageStore, вызов `write_sheet_pdf` от канваса (dirty), `OSError` → QMessageBox, без открытия файла (D5). Проверка: тесты 3.1 зелёные.

## 4. Документы

- [x] 4.1 `docs/CHANGELOG.md` (экспорт PDF из Design); roadmap P = этот change; телефон/софт-AP остаются незавершёнными. Проверка: `openspec validate add-character-sheet-p --strict` зелёный.
- [x] 4.2 `QT_QPA_PLATFORM=offscreen python -m pytest` — весь набор зелёный.
