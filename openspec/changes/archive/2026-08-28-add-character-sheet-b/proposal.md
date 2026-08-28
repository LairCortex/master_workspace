# Proposal: add-character-sheet-b

## Why

После A-editor мастер умеет нарисовать шаблон, но заполненный лист персонажа нигде не живёт. B даёт экземпляр в той же игре и Fill на том же канвасе: мастер заполняет до хоста (D1). Без этого нет ни раздачи, ни PDF заполненного листа.

Зависит от [`add-character-sheet-a1`](../add-character-sheet-a1/), [`add-character-sheet-a-playable`](../add-character-sheet-a-playable/), [`add-character-sheet-a-editor`](../add-character-sheet-a-editor/) (применять четвёртым).

## What Changes

- Своя сущность заполненного листа в `game.db`: уникальное в игре имя, неизменяемый `template_id`, карта `{field_id: значение}`, необязательный уникальный FK на `Character`.
- Несколько экземпляров на один шаблон. Не больше одного экземпляра на персонажа. Шаблон с экземплярами нельзя удалить. Шаблон у листа сменить нельзя.
- Лейаут Fill всегда из **сохранённого** шаблона. Нет ключа → default шаблона. Ключ есть → значение экземпляра (в т.ч. явная пустая картинка). Сиротский id хранится, на канвасе не рисуется. Смена default шаблона не перетирает существующие ключи.
- Меню «Чар-листы»: вкладки **Шаблоны | Листы**. Создание листа: шаблон + имя → сразу INSERT, значения = default, Fill открывается чистым.
- Fill: тот же канвас-лента; клик начинает ввод; без палитры, snap, z-order, duplicate, смены ориентации, add/delete/reorder страниц. Рейка только навигация. Явное «Сохранить», dirty. Undo — снапшоты карты значений, 50.
- Окна: не больше одного Design и одного Fill. Design шаблона и Fill его листа можно вместе. Save шаблона → открытый Fill перечитывает лейаут из БД, значения не затирает. Несохранённый Design на Fill не течёт.
- Привязка к персонажу опциональна; удаление персонажа — SET NULL. Карточка персонажа открывает лист, если связан.
- ImageStore: `image_id` в карте экземпляра участвует в refcount/GC.

Не входит: хост (D1), пресеты (C), PDF (P), смена шаблона у листа, формулы, клиент игрока.

## Capabilities

### New Capabilities

- `character-sheet-instance`: CRUD заполненных листов, карта значений и join с шаблоном, привязка к Character, запреты удаления/смены шаблона.

### Modified Capabilities

- `character-sheet-storage`: шаблон с экземплярами нельзя удалить.
- `character-sheet-editor`: вкладки списка; одно окно Design и одно Fill; Fill-хром и ввод по типам; reload лейаута после Save шаблона; undo значений.
- `image-storage`: ссылки `image_id` из JSON экземпляров в refcount, GC и startup-скане.

## Impact

- Схема: таблица `character_sheet_instances` через `create_all` в `init_db()` (ALTER существующих таблиц не нужен).
- Domain/repo/service экземпляра; Fill ViewModel (карта значений, не макет); список с вкладками; окно Fill переиспользует канвас A-playable.
- `CharacterService.delete`: SET NULL на FK, лист остаётся.
- ImageStore: сканер JSON экземпляров рядом со сканером `pages` шаблона.
- Тесты offscreen + E2E Fill; round-trip `.nri` через `game.db`. Без сети.
- `docs/CHANGELOG.md`, `docs/character-sheets-roadmap.md`.
- Без новых runtime-зависимостей. `schema_version` шаблона остаётся 2.
