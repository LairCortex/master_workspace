## Context

См. `proposal.md`. База — A1 (`add-character-sheet-a1`): одна сцена = одна страница, колесо = зум, три типа, `schema_version = 1`, ImageStore считает только FK трёх сущностей (`store.py` `_REFERRER_MODELS`). Этот change применяется **после** A1.

Спеки: `character-sheet-storage`, `character-sheet-editor`, `image-storage`.

## Goals / Non-Goals

**Goals:**

- Сцена-лента в тех же pt, что A1; локальные координаты поля не знают индекс страницы в геометрии зажима.
- v1 читается без миграции строк ALTER; неизвестный тип — жёсткий отказ.
- Refcount картинок включает поля листов, не ломая GC сущностей.

**Non-Goals:**

- Undo/snap/z-order/duplicate (A-editor).
- Нормализация полей в отдельные таблицы.
- Отдельная таблица `character_sheet_images` (двойная запись). Ссылки живут в JSON, store их сканирует.

## Decisions

### D1. Лента в одной QGraphicsScene

Страница `i`: сцена-Y = `i * (page_h + GUTTER_PT)`, `GUTTER_PT = 24`. `page_h`/`page_w` от ориентации (книжная 595.28×841.89, альбом — наоборот).

Чисто: `scene_to_page(x, y) -> (index, local_x, local_y) | None` (None = зазор). `clamp_rect` как в A1, но в локале страницы.

Альтернатива: виджет на страницу в QScrollArea — отдельный зум/хит-тест на каждый лист. Отклонено.

### D2. Колесо

`wheelEvent`: `modifiers & Control` → `scale` (лимиты A1 25–400%); иначе `verticalScrollBar`. При открытии `fitInView` по ширине **первого** page-rect (не всей сцены).

Альтернатива: оставить колесо=зум A1 — ломает «как Word».

### D3. JSON v2

Страница: `{ "name": str, "fields": [...] }`. Поле A1 + опционально:

| type | extra |
|---|---|
| checkbox | `content`: `"true"` / `"false"` |
| number | `content`: десятичная строка или `""`; `min`/`max` optional number |
| dropdown | `content`: выбранная опция или `""`; `options`: string[] |
| image | `image_id`: int \| null; `content` пустой |
| rect, line | без данных |

Load: v1 (`schema_version==1` или pages без `name`) → одна страница «Страница 1», типы только A1. Иной `type` → `UnknownFieldTypeError`, не открывать. Save всегда пишет version 2.

Create: сразу v2, одна «Страница 1».

### D4. Ориентация

`orientation` колонка уже есть в A1. Смена: новые `page_w/h`, каждое поле `clamp_rect` без scale. VM помечает dirty.

### D5. Перенос между страницами

На `mouseRelease` после move: если курсор над другим листом — вырезать поле из `pages[src].fields`, вставить в `pages[dst].fields` (конец массива = сверху), локальные координаты от дропа, clamp. Если над зазором — clamp обратно на src.

### D6. ImageStore и JSON-ссылки

Расширить `refcount` / `_null_references` / startup unused: плюс все `image_id` из `character_sheets.pages`. Парсер общий (`iter_sheet_image_ids(pages_json)`).

`gc_after_commit` после: save шаблона (старые id полей-картинок), очистка поля, delete шаблона.

Выбор файла в редакторе: тот же `ImageStore.store()`, как карточка сущности.

Альтернатива: M2M таблица — отвергнута (расхождение с JSON).

### D7. Дефолты постановки

checkbox 18×18; number 72×18; dropdown 120×18; image 120×120; rect 120×72; line 120×2. Min 16×16 (линия: толщина ≥ 1 pt).

Палитра: pointer + 9 типов. Рейка — отдельный виджет слева от view.

### D8. Приёмка типа

Общий pytest-набор на тип (параметризация): place, select, move, resize+clamp, properties/default, save/open, portrait→landscape clamp. Для image — ingest + refcount 0 после delete поля и save. Нет набора — тип не мержится.

## Risks / Trade-offs

- [QGraphicsView ест колесо сам] → переопределить `wheelEvent`, не звать `super` при скролле.
- [refcount JSON медленный] → шаблонов мало; полный parse при GC, не на каждый move.
- [v1 без ключа name] → нормализовать при load в памяти, на диск — только после Save (тогда v2).
- [картинка в dirty-макете ещё не в БД, а файл уже ingest] → ingest при выборе; если закрыть без save — orphan до startup_gc (unused, если id не в сохранённом JSON). Принимаем: либо не store до save (сложнее UX), либо startup_gc как A1-сущности. **Решение:** ingest сразу, startup_gc подберёт, если шаблон не сохранили (id нет в JSON на диске). Если dirty шаблон открыт — запись «используется» только в памяти; после crash без save файл станет сиротой и удалится при следующем старте. Ок.

## Migration Plan

1. Только после влитого A1.
2. ALTER не нужен (колонки те же). Старые строки v1 читаются; Save пишет v2.
3. Откат приложения: v2 JSON может содержать новые типы — A1-only бинарь не откроет (отказ unknown type, если бэкпортировать парсер; иначе A1 упадёт на enum). **Принято:** не открывать A1-кодом шаблоны v2. Откат = не редактировать v2-шаблоны старым билдом.

## Open Questions

Нет.
