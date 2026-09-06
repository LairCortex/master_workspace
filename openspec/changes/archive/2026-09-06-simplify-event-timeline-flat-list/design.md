## Context

См. `proposal.md` — Why. Текущее состояние (HEAD `552f302`): панель шкалы — QML-остров (`app/presentation/qml/TimelineRoot.qml` + `TimelineRowDelegate.qml`) за фасадом `app/presentation/views/timeline_island.py`; строки ленты питаются списочной моделью `TimelineRowModel` поверх qt-нулевого ядра `app/presentation/views/timeline_rows.py`; view-состояние — `app/presentation/viewmodels/timeline_viewmodel.py`. Попап «Выбора даты» — `app/presentation/views/timeline_date_popup.py` (единственный widgets-мост-поповер, спецификация `qml-shell`). Проводка — `app/application/wiring.py` (сигналы `event_selected`/`event_double_clicked` уже id-контракт; `event_dates_moved` — drag; `event_types_requested` — из «+»-меню). Инвариант цвета `tests/presentation/test_no_chrome_hex.py` сканирует `views/**` и `*.qml`. Мотивация и границы — в `proposal.md` и дельте `specs/event-timeline/spec.md`; здесь только решения по «как».

## Goals / Non-Goals

**Goals:**
- Сохранить поверхность фасада, на которую опирается `wiring.py`: класс `TimelineWidget`(псевдоним фасада), `event_selected(int)`, `event_double_clicked(int)`, `add_event_requested()`, `add_entity_requested(str)`, `event_types_requested()`, `window_changed(...)`, публичные `update_events`/`set_selected`/`scroll_to_event`.
- Сжать ядро и VM до «набор событий → плоские строки», не заводя новых токенов и не ломая id-контракт.
- Оставить остров + токены + chip-попоп как есть по способу отрисовки.

**Non-Goals:**
- Не возвращать нативный `QListWidget`/`palette()`/`С:/По:` (решение Q1.A).
- Не менять модель данных (`start_date`/`end_date`), БД и миграции.
- Не трогать спек `event-types` и доступность диалога типов.
- Не поднимать версию релиза.

## Decisions

**D1. Ядро `timeline_rows.py` → `build_rows(events, window)` возвращает `list[Row]`, где `Row` — одно событие.** Убираются `RowKind` (EVENT/EMPTY_DAY), генерация пустых дней, схлопывание провалов, карточки периодов, `index_at_y`/`normalize_range` рейки, `sticky_state`/`zoom_level`/`zoom_target`/`drill_target`/`drop_actions`/`apply_drop_action`/`jump` и связанные хелперы. Фильтрация окна = «интервал события пересекает окно»: `start <= window.end and (event.open_end or event.start? ...)`. Точное правило: событие видно, если `window` пуст ИЛИ `event.start_date <= window.end` И (`event.end_date is None` ИЛИ `event.end_date >= window.start`). Сортировка `(start_date, id)`. *Альтернатива* — оставить ядро и «заглушить» лишние параметры: отвергнута, мёртвый код и тесты тянутся за ним.

**D2. `TimelineRowModel`/`rowModel` остаётся, у fields строки убираются `kind`/`day`-семантика и флаги `drillable`/`windowable`; остаются `event_id`, `caption` (`start — end · name`, открытый `∞`), `detail` (описание — см. D6), `token_key` (метка типа), `flags` (только `selectable`).** QML-делегат рисует строку дат + вторую строку по `detail` + левую метку по `token_key`. *Альтернатива* — убрать модель и отдавать готовый список в QML-модель `ListProperty`: отвергнута ради ленивой поставки/переиспользования делегатов и сохранения теста `test_timeline_row_model`.

**D3. `TimelineViewModel` теряет `level`/`Level`, `sticky_state`/zoom/drill/jump-состояние; сохраняет `all_events`, `events`, `window`, `select_event_by_id`, `selected_event`, `row_model`.** `select_event_by_id(event_id)`: если событие есть в `all_events`, но не в текущем окне (не пересекает) — сбросить `window = None` («Все дни»), перепроецировать, выбрать; иначе просто выбрать. `_reproject_window` фильтрует по правилу D1. `events_changed`/`selected_event_changed` без изменений. Пустой набор даёт `row_model` с нулём строк (текст пустоты рисует остров).

**D4. Фасад `timeline_island.py` — срезаем лишние каналы.** Удаляются сигналы `event_dates_moved`, `event_create_requested` и внутренности drop/inline/sticky/zoom/hideEmpty/jump (в т.ч. `QShortcut Alt+Up/Down`, `_show_drop_menu`, `_descend_for_jump`, `cover_window_for_span`-путь расширения окна). Шапка острова (`TimelineRoot.qml`) оставляет: заголовок, чип `windowText`, «+»-меню (`_show_add_menu`, теперь 6 пунктов: событие + 4 сущности + «Типы событий…» → `event_types_requested`). Чип по-прежнему открывает `timeline_date_popup.py` (без изменения). *Альтернатива* — удалить и «Типы событий…»: отвергнута, это единственный вход в `EventTypesDialog` (`wiring.py:257`).

**D5. Тема/цвета — только существующие токены.** Метка типа = `color.chart.1..8`, без типа, вторая строка описания и подсказка пустоты = `color.fg.muted` (единственный в скине токен текста второго ранга; отдельного `color.fg.secondary` в скине нет, и выдумывать его незачем), выделение/hover = производные `color.accent`, фон панели = `color.bg.surface`, фон списка = `color.bg.canvas`, границы `color.border`; chip — как сейчас. Призрака/sticky/period-card нет. Инвариант `test_no_chrome_hex` остаётся зелёным (hex/palette() не заводим).

**D6. Строка события несёт описание (принято после приёмки плоского списка).** `Row` дополняется полем `detail`, `TimelineRowModel` — ролью `detail`: это описание самого события, одна логическая строка — «характеристики», при их пустоте «предыстория», свёрнутые пробелы и обрезка по `DETAIL_MAX_CHARS = 160` с многоточием. Полное правило text-формата живёт в Qt-нулевом ядре (`row_detail`), QML решает только число выводимых строк (`maximumLineCount: 2` + `ElideRight`). Высота строки — одна из двух констант острова (`rowHeight` без описания, `detailedRowHeight` с ним), вид определяется непустой `detail`, поэтому события без описания не оставляют пустого места. Ключ мемоизации `rows` (`_version_of`) читает ровно `row_detail(e)`: правка одного описания в карточке обязана перестроить ленту. *Альтернатива* — отдавать в QML весь текст: отвергнута, лента остаётся сводкой, полный текст — в карточке события.

**D7. Список шкалы — в том же окаймлённом поле, что и остальные панели.** Корень острова остаётся `color.bg.surface`, тело (ListView + ловушка промаха + подсказка пустоты) переезжает в `CardPanel` с `color: color.bg.canvas`, то есть в ту же роль поля (`bg.canvas` + `color.border` + `radius.sm`), что и вкладочная панель деталей, и список обзора мира; внутренние отступ 1 px — как у вклада деталей; сам список отступлён ещё на радиус карточки (`radius.sm`), иначе полноширинная заливка выбранной строки квадратным пятном перекрывает скругление и рамку поля (прямоугольный `clip` у `Rectangle` радиуса не уважает). Метка типа выравнивается по строке дат, чтобы двухстрочная строка не уезжала от метки. *Альтернатива* — оставить список на фоне панели и только нарисовать рамку: отвергнута, поле без собственного фона по-прежнему не читается как контент колонки.

## Risks / Trade-offs

- [Регресс проводки при удалении сигналов `event_dates_moved`/`event_create_requested`] → синхронно убрать их подключение в `wiring.py` (`_wire_*` шкалы) и проверить сборкой/тестами; публичные каналы выбора/добавления/типов не трогаем.
- [Срезка ядра задевает соседние тесты, ожидающие EMPTY_DAY/провалы] → тесты `test_timeline_rows.py`/`test_timeline_row_model.py` переписываются в этом же change (см. `tasks.md`), не оставляем «красных».
- [Правило пересечения окна расходится с ожиданиями «бессрочные включаются»] → зафиксировано в D1 и сценарии «Бессрочное видно в окне после начала»; покрыть юнитом.
- [Пиксельный тем-тест завязан на карточки/period/призрак] → `test_e2e_timeline_theme.py` переписать на строку+метку типа+выделение (обе темы, live-retheme), golden отсутствует.

## Migration Plan

Шаги и откат — в `tasks.md`. Схлопнуто: ядро+юниты → VM → фасад+QML/шапка+меню → правка `wiring.py` (снять drag/inline, оставить выбор/добавление/типы) → тесты → docs (roadmap-срез + CHANGELOG Unreleased). БД и данные не трогаются, откат = revert PR.
