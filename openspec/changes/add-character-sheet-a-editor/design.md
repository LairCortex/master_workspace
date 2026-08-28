## Context

См. `proposal.md`. Применять после A1 и A-playable. Модель макета и `schema_version = 2` не меняются. A-playable: одно выделение, лента, зажим по странице. ImageStore не трогаем (duplicate картинки копирует тот же `image_id` — refcount вырастет после save).

## Goals / Non-Goals

**Goals:**

- Стек undo — снапшоты JSON макета в VM, без команд на каждый тип поля.
- Один набор `QAction` + StandardKey; визуал кнопок snap/z-order не ветвить по ОС.
- Рамка и Shift пишут в одно `selected_ids: list[str]` (порядок — порядок добавления).

**Non-Goals:**

- Системный clipboard, JSON-файл шаблона, выравнивание, группы.
- Persistence snap/выбора.
- Отдельные e2e «нажать Cmd на раннере macOS» в CI.

## Decisions

### D1. Снапшот undo

Перед мутацией макета: `copy.deepcopy` / сериализованный `SheetTemplate` в стек (max 50). Redo — второй стек, очищается любой мутацией кроме undo/redo. Сравнение dirty: текущий макет vs last-saved снимок (уже есть в A1).

Инлайн: push undo **при открытии** инлайна (состояние «до»), коммит не пушит второй раз; Esc (отмена инлайна) делает pop, если текст не меняли… проще: push только на **успешный коммит** инлайна, один раз, снимок *до* правки сохранён в `_inline_before`. Esc — восстановить `_inline_before` без стека.

Альтернатива: command objects — отклонено (больше кода, чем фича).

### D2. Мультиселект

`selected_ids: list[str]`. Рамка: `QRubberBand` в view, пересечение scene-rect с item.sceneBoundingRect. Старт рамки: press не на выбранном поле (пусто, зазор, или невыбранное поле — wait: press on unselected field is click-select, not marquee).

Press:
- на выбранном поле → готовить move набора;
- на невыбранном поле без Shift → select only that, готовить move;
- на невыбранном с Shift → toggle, не move;
- на пустом/зазоре → rubber band.

### D3. Snap

`SNAP_PT = 4`. `snap_coord(v) = round(v / 4) * 4` после clamp. Флаг `_snap_enabled` в VM, не в БД. Сетка: `drawBackground` листа, шаг 4 pt, только если флаг.

Shift во время move/resize: не вызывать snap.

### D4. Z-order

`bring_to_front(ids)`: на каждой затронутой странице выбранные id идут в конец массива (относительный порядок выбранных сохраняется). `send_to_back`: в начало. Один undo-шаг.

### D5. Clipboard

`_clipboard: list[SheetField]` (копии dataclass, без id). Paste: новые uuid4, страница = current rail page, позиция по правилу spec. Duplicate = copy + paste сразу на ту же страницу с +8,+8 (не зависит от rail, если все исходные на одной; если набор с двух страниц — каждая копия на странице своего оригинала +8,+8). Spec: «Duplicate … зажим на той же странице» — per field's page. Paste «на текущую страницу рейки» — только для paste, не duplicate.

### D6. Клавиши

`QAction` в `QMenu("Правка")` редактора (не MainWindow). Undo/Redo/Copy/Paste → `QKeySequence.StandardKey`. Duplicate → `QKeySequence("Ctrl+D")` (Qt даёт Cmd+D на macOS). Enabled от selection/stack.

Не хардкодить `Ctrl+Z`.

### D7. Картинки при duplicate

Копия поля несёт тот же `image_id`. После save refcount ImageStore (A-playable JSON scan) увидит две ссылки. Не ingest повторно.

## Risks / Trade-offs

- [Rubber band vs скролл ленты] → порог drag > 4 px до старта рамки; короткий клик = снять выделение.
- [Снапшот 50 полных шаблонов с image_id] → память ничтожна.
- [CI не ловит Cmd vs Ctrl] → unit на `QKeySequence.Undo` не пустой; не симулировать native event трёх ОС.

## Migration Plan

Нет миграции БД. Откат = выключить меню/жесты. v2-шаблоны читаются как раньше.

## Open Questions

Нет.
