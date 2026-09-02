# Design: redesign-timeline-day-ladder

## Context

См. proposal.md — Why. Текущая реализация (результат разведки кода):

- `app/presentation/views/timeline_widget.py`: `TimelineWidget` (панель), `TimelineListView(QListWidget)` + делегат `_RowDelegate` с полной отрисовкой, включая рейку/скобки/засечки; sticky — `QLabel`-оверлей поверх viewport (`setViewportMargins`); жесты handwritten в `mousePress/Move/Release` (`_RailPress`, `_EventPress`, `_SerifPress`), зум Ctrl/Cmd+колесо, попап `_DateFilterPopup`.
- `app/presentation/views/timeline_rows.py` — Qt-free ядро строк: `build_rows(events, start, end, unit, groups)`, `Row`, `RowKind{EVENT,EMPTY_DAY,UNIT,SECTION}`, geometry-хелперы (`index_at_y`, `target_day`, `translate_span`, `serif_targets`, `bracket_lanes`, `clamp_calendar`), `CALENDAR_MIN/MAX`.
- `TimelineViewModel`: `unit`, `group_by`, `_current_filter` ( containment-семантика), `rows`, `load_events()` через `EventService`; коммит drag'а — сигнал `event_dates_moved` → `wiring.on_event_dates_moved` (cover-фильтр → `update_event` → `load_events`).
- Модель события не меняется: `start_date`, `end_date|None`, `event_type` (цвет `color.chart.1..8`).
- Игровой календарь = григорианский с переименованными месяцами (`date_utils`); «сегодня» нет; границы приложения `0100-01-01 … 9999-12-31`.

## Goals / Non-Goals

**Goals:**
- Единый Qt-free ядро-слой строк остаётся источником правды о ленте (день-секции, дубли, провалы, уровни) — весь новый рендер и хит-тесты выводимы из него.
- Все новые взаимодействия (колесо-зум, drop-меню, инлайн-создание, тумблер, «Выбор даты») — чистые функции ядра + тонкие Qt-обёртки, тестируемы без мыши.
- Убрать рейку, скобки, засечки, группировку, кнопки ступени без мёртвого кода.

**Non-Goals:**
- Смена модели данных/миграции (нет).
- Персист окна/уровня/тумблера (нет — только сессия).
- Фильтрация по сущностям в любом виде; «сегодня»; экспорт; undo.
- Замена QListWidget на кастомный view ради гипотетических десятков тысяч строк (см. Risks — при ухудшении это отдельное решение).

## Decisions

### D1. Оставляем `QListWidget` + uniform-rows + `timeline_rows` ядро, переписываем содержимое

Альтернатива — `QListView` с моделью или QGraphicsView. Отклонено: весь текущий делегат, sticky-оверлей, хит-тесты и тестовая инфраструктура завязаны на uniform-rows QListWidget; переписывать view-движок ради этой задачи — больший риск при той же производительности (виртуализация одинаковая). Ядро остаётся Qt-free: новые RowKind'и и правила считаются в `timeline_rows.py`.

### D2. Модель строк ядра

`RowKind` = `DAY_HEADER | DAY_DATE` (sticky/инлайн-заголовки дня на суточном уровне), `EVENT_CARD`, `EMPTY_DAY`, `GAP_COLLAPSED`, `PERIOD_HEADER`, `PERIOD_CARD`, плюс служебная пустота без событий (не Row — оверлей-подсказка как сейчас).

`build_rows(events, window, level, hide_empty)` возвращает строки готовой ленты:

- **Содержательный диапазон без окна**: `[min_start … bottom]`, `bottom = max(max_closed_end, max_open_start + 1 year)` (дни clamp'ом `CALENDAR_MIN/MAX` — пересчёт `content_bottom(events)` в ядре; пересобираемый при каждой загрузке).
- **Уровень суток**: для каждого дня окна/диапазона: `DAY_HEADER` + карточки событий, накрывающих день (`start <= day <= (end or bottom)`; бессрочные — до `bottom`), сортировка `(_start_date, id)` — детерминированность сохраняется; пустой день — `EMPTY_DAY`; провал `> GAP_COLLAPSE_DAYS=14` без событий — одна `GAP_COLLAPSED` (с игровыми границами). `hide_empty` вырезает `EMPTY_DAY/GAP_COLLAPSED` и пустые позиции периодов.
- **Уровни месяц/год**: для каждой единицы диапазона `PERIOD_HEADER` + одна `PERIOD_CARD` с числом перекрывающих период событий (уникальные `event.id`, пересечение `[start, min(end or bottom)]`); «нет событий» — тоже позиция, кликабельна для проваливания.
- Дубли многодневок — строки `EVENT_CARD` с одним `event_id` на разные дни; мутации действуют на запись целиком (ядро хранит `event_id` в строке — фактической дедупликации в данных нет).

Память/скорость: количество строк суточного уровня = Σ длительностей событий + одиночки ≤ O(окно × события). Окно между двумя событиями через года сжимается провалами. Ядро хранит строки списком; для диапазона «весь мир» (0100→9999 с единичными событиями) строк единицы + провалы.

### D3. Sticky push-out: два `QLabel`-оверлея

Текущий один оверлей менял текст мгновенно. Новые два (`_sticky_current`, `_sticky_next`) синхронизируются по строке первого видимого `DAY_HEADER/PERIOD_HEADER`: когда догоняющий заголовок въезжает, следующий оверлей анимируется `QPropertyAnimation` по `pos` (выезд снизу, выезд текущего вверх), по finish текущий становится следующим. Текст/позиция считаются в ядреHelper'ом `sticky_state(rows, first_visible_y)` (чистая функция). Анимация ~120 ms, ease-out; при скролле пера-за-перо анимация прерывается и переставляется. Альтернатива — рисование заголовков в делегате с offset (отклонено: сложнее hit-test и темы, конфликт с «не перехватывает мышь»).

### D4. Инлайн-создание: один переиспользуемый `QLineEdit`-оверлей строки

Не делегат-редактор и не `setItemWidget` на каждой пустой строке. Один `QLineEdit` с плейсхолдером/иконкой поверх viewport на координатах кликнутой `EMPTY_DAY`-строки; Enter → VM-интент `create_event_at(day, name)` (по образцу «+»-меню: `EventService.create_event` c `start=end=day`, тип None) → reload, выбор нового; Esc/blur без текста → скрытие. Альтернатива `QStyledItemDelegate::createEditor` — отклонена: QListWidget-редактирование тянет model/index-обвязку, которой здесь нет (строки не Qt-модель).

### D5. Drag с контекстным меню: жест + `QMenu` на отпускании

- `mousePress` на `EVENT_CARD`-строке → `_CardPress{event_id, source_day, start_pos}`; порог 4 px по вертикали (как сейчас `DRAG_START_THRESHOLD_PX`).
- Во время движения: состояние `drag_preview{event_id, target_day}` в view; делегат рисует приглушённую исходную карточку + «призрака» в строке целевого дня, если день материализован (над `DAY_HEADER/EMPTY_DAY/EVENT_CARD` любой строкой); sticky показывает целевую дату. Ядро даёт `target_day = index_at_y` (существует); **без экстраполяции за край** — над списком/провалом цель недействительна, призрак гаснет, отпускание — cancel.
- `Release` на действительном дне ≠ день источника → `QMenu` (`exec` у глобальных координат курсора): пункты считает чистая функция ядра `drop_actions(event, target_day, bottom) -> (move: bool, extend_down: bool, start_earlier: bool)` по правилам спецификации; выбранное действие → одна функция `apply_drop_action(event, action, target_day) -> (start, end)`.
- Коммит — переиспользование канала `event_dates_moved(event_id, start, end)` и `wiring.on_event_dates_moved` (rename `cover_filter_for_span` → `cover_window_for_span`: расширение окна вместо фильтра; поведение «расширить окно до записи — одна запись — reload» сохраняется).
- Эскапейп меню = cancel; release без выбора = cancel. Альтернатива — собственное frameless popup — отклонена: нативный `QMenu` даёт темы/клавиатуру/закрытие бесплатно.

### D6. Zoom Alt/Opt + wheel → уровни с якорем, drill-in кликом

`wheelEvent`: модификатор Alt (macOS: Option; Qt `QApplication.keyboardModifiers() & Qt.AltModifier`) — не Ctrl; дельта<0 = отдаление. Ядро: `zoom_level(level, delta)` + `zoom_anchor_level(level, anchor_row)` (чистая функция: карточка дня/заголовок дня → период дня; карточка периода → период карточки). Drill: клик по `PERIOD_CARD` → VM: `level := level+1 глубже; window := период`. Удалить: `Ctrl`-обработку, `_step_scale`, `zoom_into_unit`, `LADDER_CAPTIONS`, `scale_buttons`.

### D7. Состояние viewmodel: `level`, `window`, `hide_empty` вместо `unit`/`group_by`/`_current_filter`

- `window: (date|None, date|None)` (None,None = «Все дни») replaces `_current_filter`: семантика — **ограничение диапазона** с overlap-видимостью (`start <= win_end AND (end is None OR end >= win_start)`), не containment. `EventService.get_all_events` остаётся источником; VM фильтрует по пересечению.
- Выбор вне окна/уровня сбрасывает selection как сейчас (`_select_from_visible`, сигнал `selected_event_changed`); внешний выбор: если событие не в ленте — `level=DAY`, `window=None`, затем scroll/select (в `select_event_by_id`).
- `level` default DAY на каждом `load/reset`; ни `window`/`level`/`hide_empty` не persитсятся (как `unit` сегодня).
- Мемо-key пересборки `_version_of()` расширяется `(level, window, hide_empty, bottom)`.

### D8. «Выбор даты» = `_DateFilterPopup` переименованный и перенастроенный

Попап с двумя календарями (`_CustomCalendar`) остаётся кнопкой в шапке с текстом «Все дни» / границы окна игровым форматом; сброс «Все дни» в попапе; клик по `GAP_COLLAPSED` открывает его с предзаполнением провала. Никакого «фильтра» в терминологии кода — классы/сигналы переименовываются: `filter_changed` → `window_changed`, `filter_chip_text` → `window_chip_text`.

### D9. Удаления (мёртвый код, точечно, без флага)

Рейка и всё вокруг: `_paint_rail`, `RAIL_*`, `BRACKET_*`, `SERIF_*`, `_RailPress`/`_SerifPress`, `bracket_lanes`, `serif_targets/serif_hit`, `ROLE_SHOW_TICK/MONTH/YEAR`, `EXTRAPOLATION_STEP_PX` (перестала нужна — нет цели за краем), sticky-rail-follow. Группировка: `EntityKind`, `event_attr`, `group_by`, `_group_map`, `build_event_groups`, `GROUPING_*`, `group_button`, `NO_GROUP_KEY`, `Row.group_key`, `groups` параметр `build_rows`. Кнопки ступени: `scale_buttons`, `LADDER_CAPTIONS`. Тесты группировки/рейки/ступени удаляются или переписываются (см. tasks).

### D10. Тестуемость

Ядро покрывается юнит-тестами без Qt: `content_bottom`, дубли по дням (включая открытые), `GAP_COLLAPSE_DAYS`, overlap-окно, `drop_actions`/`apply_drop_action` (все направления, бессрочные, иннер-дроп, same-day), счётчики периодов, `zoom_anchor_level`, `hide_empty`. Виджет-тесты: sticky push-out (позиции оверлеев после скролла-симуляции), Alt-колесо смена уровня, presence/absence меню (QtTest-посылки кликов), инлайн-создание (key-евенты), тумблер. E2E: `tests/ui/test_e2e_timeline_*` переписываются с новой лентой.

## Risks / Trade-offs

- [Патологически длинная многодневка (например 0100→9999) даёт миллионы строк-карточек на суточном уровне] → Принятый trade-off: окно и провалы обычно ограничивают вид; реальные игровые кампании коротки. Если проявится — следующий шаг: виртуализированный view или clamp числа дублируемых дней с явной подписью. В этой Change — не лечим.
- [Полная пересборка строк на каждое изменение событий O(range+events)] → сохраняется и текущее memo-поведение (`update_events` no-op при том же срезе); для типичных диапазонов (<10⁵ строк) приемлемо.
- [Overlap-семантика окна меняет видимый набор относительно старого containment-фильтра] → сознательное изменение контракта (спецификация); выбранное событие, вышедшее за окно, сбрасывается так же, как раньше.
- [Push-out анимация и агрессивный скролл могут конфликтовать (рывки)] → анимация короткая, прерывается по новому скроллу; позиция всегда догоняет модель (анимация косметика, состояние не authoritative).
- [Alt-колесо на macOS перехватывается системой для мультимониторных жестов] → на практике для колёс мыши Qt отдаёт событие приложению; если проявится в конкретной сборке — fallback: Opt+Shift или клавиши `[`/`]` (не в Scope; фиксируется как известный риск).
- [QMenu в drag'е — потеря «grab-offset» инерции перетаскивания, которой теперь нет] → осознанно: цель берётся под курсором (спецификация), grab-offset удалён.

## Open Questions

_(нет — поведение дерева решено на grilling-сессии; технические детали уровня имён/констант решаются на apply.)_

## Migration Plan

1. Реализация в пределах `event-timeline` capability; схема БД и миграции не затрагиваются → откат = git revert, данных не касается.
2. Удаления (рейка/группировка/кнопки) делаются в тех же коммитах, где появляется замена (лента-дубли, drop-меню), чтобы тесты не «провисали» между состояниями.
3. После archive — отредактировать `Purpose` основного спека `event-timeline` (дельта Purpose переноса не имеет).
