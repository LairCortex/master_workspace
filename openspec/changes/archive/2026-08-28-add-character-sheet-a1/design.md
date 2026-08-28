## Context

См. `proposal.md` — зачем. Приложение: PySide6 + qasync, одна SQLite на игру (`games/<name>/game.db`), слои presentation → services → repositories, схема только через `init_db()` / `create_all` (не alembic). Сеть в A1 не нужна. Код NRI-0007 не переносим.

Требования: `specs/character-sheet-storage/spec.md`, `specs/character-sheet-editor/spec.md`.

## Goals / Non-Goals

**Goals:**

- Модель шаблона, которую A-playable расширит новыми типами/страницами без ломания `schema_version = 1` читателя (неизвестные ключи игнорировать нельзя — в A1 неизвестных нет; версия колонки есть, чтобы следующий кусок бампнул её явно).
- Канвас на Qt без новых runtime-зависимостей; геометрия в тех же единицах, что потом понадобятся PDF (pt), origin сверху как в Qt.
- ViewModel — единственный источник правды макета в памяти; сцена и панель — проекции.

**Non-Goals (дизайн, не продукт):**

- Стек undo, collision-движок, отдельный JSON-файл шаблона, PDF-пайплайн, клиент игрока.
- Нормализованные таблицы полей (отдельная строка БД на поле) — лишняя миграционная поверхность для A1.

## Decisions

### D1. Одна таблица, страницы как JSON

`character_sheets`: `id`, `name` UNIQUE, `schema_version` INTEGER NOT NULL DEFAULT 1, `orientation` TEXT NOT NULL DEFAULT `'portrait'`, `pages` TEXT NOT NULL (JSON), `created_at`, `updated_at`.

`pages` — массив из одного элемента `{ "fields": [ ... ] }`. Поле: `{ "id", "type", "x", "y", "w", "h", "font_size", "content" }`. `type`: `label` | `text` | `textarea`. Координаты — float, pt.

Альтернативы: таблица `character_sheet_fields` (FK + порядок) — миграции на каждый новый атрибут; отложено. Orientation колонка при одном значении — чтобы A-playable не двигал JSON-корень.

Новая таблица появляется через `Base.metadata.create_all` в существующем `init_db()`. ALTER старых таблиц не нужен.

### D2. Domain-датакклассы и чистые функции геометрии

`SheetTemplate`, `SheetPage`, `SheetField`, `FieldType` в `app/domain/`. Зажим в A4 (`PAGE_WIDTH_PT = 595.28`, `PAGE_HEIGHT_PT = 841.89`), дефолтные размеры, min size — чистые функции, unit-тесты без Qt.

Дефолты постановки (левый верх в точке клика, затем зажим): label 72×18, text 120×18, textarea 120×54; min 16×16; кегль по умолчанию 10. Зум 25–400%.

`id` поля — `uuid4` hex-строка в момент `add_field`.

### D3. Канвас = QGraphicsView, не WebEngine

`QGraphicsScene` в координатах страницы (1 единица сцены = 1 pt, Y вниз). Страница — фон-прямоугольник A4. Поля — `QGraphicsRectItem` (или тонкая обёртка) с `zValue = индекс в массиве`. Wheel на view масштабирует (не скроллит); панорама — полосы прокрутки.

Альтернативы: HTML в `QWebEngine` (вторая вёрстка, лишняя зависимость); голый `QWidget` paint (ресайз/хит-тест руками). Qt scene — стандартный hit-test и transform для зума.

Инлайн-текст: `QGraphicsProxyWidget` + `QLineEdit` (label/text) / `QPlainTextEdit` (textarea) в координатах айтема. На время правки item flags без move/resize.

Шрифт: один TTF с кириллицей, bundled (DejaVu Sans, SIL), `QFontDatabase.addApplicationFont` при старте редактора. Не системный семейный пикер.

### D4. ViewModel держит макет; сцена подписана на него

`CharacterSheetViewModel` (QObject): шаблон в памяти, `dirtyChanged`, `templateChanged` / точечные сигналы (`fieldAdded`, `fieldRemoved`, `fieldGeometryChanged`, `fieldContentChanged`, `selectionChanged`). Операции: place (type + сцена-точка), move, resize, remove, set_content, set_font_size, set_geometry. `save()` / `reload()` — корутины через qasync, как остальные VM.

Панель свойств пишет в VM; VM эмитит; канвас и панель читают одно `content`. Нет второго буфера.

Инструмент постановки: `pointer` | `place_label` | `place_text` | `place_textarea`. После успешного `place_*` VM сбрасывает в `pointer`.

### D5. Сервис и уникальность имени

`CharacterSheetRepository` по образцу `BaseRepository` + `get_by_name`. `CharacterSheetService`: `list`, `create` (пустой pages JSON, unique check до insert и `IntegrityError`), `update_pages` (макет + `updated_at`), `rename` (сразу commit, не трогает `pages`), `delete`.

Create из UI: диалог имени → `create` → открыть редактор с загруженной моделью, `dirty=False`.

Rename из списка: `rename` сразу; если редактор открыт на этот id — только `setWindowTitle`, dirty макета не менять.

Delete: если `Application._sheet_editor` открыт на этот id — кнопка неактивна; иначе confirm → `delete`.

### D6. Одно окно, список может быть открыт

`Application` хранит `_sheet_list_dialog` и `_sheet_editor` (оба optional). Меню «Чар-листы» на `MainWindow` → сигнал → показать/поднять список.

Открыть/создать при живом редакторе: если dirty — `QMessageBox`; отказ — ничего; согласие — закрыть без `update_pages`, затем открыть другой. Смена игры (`_on_switch_game`): тот же dirty-prompt; при согласии закрыть оба окна, затем существующий shutdown/start.

Список — немодальный `QDialog`. Редактор — немодальный `QDialog` (не четвёртая колонка главного окна).

### D7. Смена игры и `.nri`

Шаблоны в `game.db` → экспорт v2 подхватывает их без изменения `export_game`. E2E/интеграционный тест roundtrip `.nri` (как `test_character_sheet_nri_roundtrip` в откатанном коммите, но новый) фиксирует требование storage.

При `start()` новый `create_all` создаёт таблицу на старых каталогах игр.

## Risks / Trade-offs

- [Инлайн-виджет на масштабированной сцене прыгает/ломает фокус] → прокси строго в item-координатах; тесты даблклик + Enter/Esc/клик мимо на offscreen.
- [Wheel-зум вместо скролла неудобен на маленьком экране] → вписать страницу при открытии (spec); ползунки остаются для панорамы после зума.
- [Наложение: нижнее поле не выбрать] → принято в spec; сдвинуть верхнее.
- [Пустые шаблоны копятся после «создать и закрыть»] → принято в spec; удаление из списка.
- [JSON в TEXT без валидации на битых данных] → парсер в сервисе при load: битый JSON → ошибка пользователю, шаблон не открывать; A1 не пишет битое.

## Migration Plan

1. Выкат: обычный коммит в `main`; при первом открытии игры `create_all` добавляет `character_sheets`.
2. Откат версии приложения: таблица остаётся в SQLite, старый код её не трогает; данные не теряются. Drop таблицы не делаем.
3. Обратной миграции данных нет (новая сущность).

## Open Questions

Нет. Дефолтные размеры/кегль/лимиты зума зафиксированы в D2; смена констант не ломает spec, пока зажим и три типа соблюдены.
