## Context

См. `proposal.md`. Применять после A1, A-playable и A-editor. Макет шаблона и `schema_version = 2` не меняются. ImageStore уже сканирует `character_sheets.pages`; этот change добавляет сканер JSON экземпляров. Спеки: `character-sheet-instance`, `character-sheet-storage`, `character-sheet-editor`, `image-storage`.

## Goals / Non-Goals

**Goals:**

- Экземпляр — отдельная строка БД; join значений с сохранённым шаблоном чистой функцией (нет ключа / есть ключ / сирота).
- Fill переиспользует сцену-ленту A-playable как read-only геометрию; мутации только карты значений.
- Два окна в `Application` (`_sheet_editor`, `_sheet_fill`); Save Design шлёт reload лейаута в открытый Fill.

**Non-Goals:**

- Нормализация значений в колонки/таблицы полей.
- Синхронизация несохранённого Design в Fill.
- Хост, PDF, формулы, смена `template_id`.

## Decisions

### D1. Таблица `character_sheet_instances`

`id`, `name` UNIQUE NOT NULL, `template_id` INTEGER NOT NULL FK `character_sheets.id` ON DELETE RESTRICT, `character_id` INTEGER NULL FK `characters.id` ON DELETE SET NULL, `values` TEXT NOT NULL (JSON object), `created_at`, `updated_at`.

UNIQUE на `character_id`: в SQLite несколько NULL допустимы — листы без персонажа не конфликтуют. Один не-NULL персонаж — не больше одной строки.

Новая таблица через `create_all` в `init_db()`. ALTER старых таблиц не нужен.

Альтернатива: JSON экземпляров внутри шаблона — отвергнута (имя, персонаж, GC картинок, удаление шаблона).

### D2. Карта значений

JSON: `{ "<field_id>": <value> }`. Нет ключа ≠ пустое значение.

| type | value |
|---|---|
| text, textarea | string |
| checkbox | JSON bool |
| number | десятичная строка или `""` |
| dropdown | string (в т.ч. сирота) |
| image | `image_id` int или JSON `null` (ключ есть = своя картинка/пусто) |
| label, rect, line | ключа нет |

Create: для каждого заполняемого поля шаблона записать текущий default (картинка — `image_id` шаблона или `null`). После create ключи всех тогдашних полей есть → смена default шаблона их не затирает. Поле, добавленное в шаблон позже, ключа не имеет → inherit.

`resolve_display(field, values) -> display`: нет ключа → default поля шаблона; ключ есть → value. Поле без id в шаблоне не рендерится.

Альтернатива: хранить только отличия от default — отвергнута (не отличить «оставил default» от «ещё не трогал новое поле» после смены default).

### D3. Fill ViewModel

Отдельный `CharacterSheetFillViewModel`: `template` (read-only снимок из БД), `values` (мутируемая карта), `dirty` относительно last-saved `values`. Операции: set_text/toggle_checkbox/set_number/set_dropdown/set_image/clear_image. Нет place/move/resize/pages/orientation/snap/z-order.

Undo: `copy.deepcopy(values)`, стек 50, как A-editor, но только карта. Коммит инлайна = один push.

`reload_layout()`: заново load шаблона по `template_id`; `values` не трогать. Вызывать после успешного `update_pages` Design, если Fill открыт на этом шаблоне.

Канвас: тот же `QGraphicsView`/сцена-лента; флаг режима или отдельный хендлер: press = select/edit, не rubber-band move. Рейка без кнопок мутации страниц.

### D4. Окна в Application

`_sheet_list_dialog` с `QTabWidget`. `_sheet_editor` (Design) и `_sheet_fill` (Fill) — optional, независимо. Меню «Правка» Fill: только Undo/Redo + StandardKey.

Открыть Fill при живом Fill: dirty-prompt, затем закрыть и открыть другой (или поднять, если тот же id).

Смена игры: dirty-prompt Design и Fill по очереди; отказ оставляет игру.

Сигнал: после `CharacterSheetViewModel.save()` успех → если `_sheet_fill` и тот же `template_id` → `reload_layout()`. Не стримить `templateChanged` из грязного Design.

### D5. Сервис экземпляра и персонаж

`CharacterSheetInstanceService`: list/create/rename/delete/update_values/bind_character/unbind. Create: unique name, copy defaults, INSERT. Delete: запрет если Fill открыт на этот id (UI); FK RESTRICT уже блокирует delete шаблона. Bind: unique `character_id` → `IntegrityError` → сообщение.

`CharacterService.delete` (или репозиторий): FK `ON DELETE SET NULL` снимает ссылку сам; после delete персонажа лист остаётся. Карточка персонажа: если `get_by_character_id` не пусто — действие «Открыть чар-лист».

### D6. ImageStore

Рядом с `iter_sheet_image_ids(pages)`: `iter_instance_image_ids(values_json)` — все int `image_id` в карте. `refcount` / `_null_references` / unused startup: сумма шаблонов + экземпляров + сущности.

`gc_after_commit` после: save Fill (старые image_id значений), clear image, delete экземпляра. Ingest в Fill сразу, как Design (сирота после закрытия без save — startup_gc).

Альтернатива: колонка `image_id` на экземпляре — не покрывает N полей-картинок.

### D7. Валидация числа и списка

`min`/`max`/`options` читаются с текущего снимка шаблона в Fill VM (после reload_layout — новые). Сеттер числа отвергает parse-fail и вне диапазона. Список: выбрать можно только текущие опции; уже сохранённая сирота отображается и остаётся, пока пользователь не выберет другую.

## Risks / Trade-offs

- [Fill держит грязные values, шаблон удалил поле] → поле пропадает с канваса, ключ в карте; Save пишет сироту. По контракту ок.
- [RESTRICT delete шаблона vs UI] → кнопка disabled по `count_instances(template_id)`; IntegrityError как страховка.
- [Два окна, два dirty] → смена игры: сначала Fill, потом Design (или наоборот), любой отказ — стоп.
- [Картинка-inherit vs ключ на create] → create копирует default image_id в карту, поэтому смена картинки шаблона не меняет уже созданные листы. Новое поле-картинка без ключа inherit'ит. Сознательно.

## Migration Plan

1. После влитых A1, A-playable, A-editor. `create_all` добавляет таблицу на существующих играх.
2. Откат приложения: таблица остаётся, старый код её не трогает. Drop не делаем.
3. Шаблон schema 2 без изменений.

## Open Questions

Нет.
