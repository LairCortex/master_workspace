# Tasks: redesign-timeline-day-ladder

## 1. Ядро строк: лента дней, провалы, дно

- [x] 1.1 В `timeline_rows.py` ввести `content_bottom(events)` = max(поздняя закрытая `end_date`, поздний старт бессрочного + 1 год, clamp `CALENDAR_MAX`) и `_range_for(events, window)` (без окна: min..bottom; с окном: дни окна); покрыть юнит-тестами (`pytest tests/ -k content_bottom`: бессрочные задают дно, пустой список)
- [x] 1.2 Переписать `build_rows` на суточный уровень: `DayHeaderRow | EventRow(dup по дням start..min(end,bottom)) | EmptyDayRow | GapCollapsedRow(>14 дней)`; сортировка событий ` (start_date, id)`; тесты: многодневка даёт карточку в каждый день, пустой день ровно одна позиция, провал 40 дней = 1 позиция, равновысокость как инвариант типа строки
- [x] 1.3 Уровни периодов: `PeriodHeaderRow + PeriodCardRow(count)` для месяца/года окна, где count = уникальные события, пересекающие период; пустой период = позиция «нет событий»; тесты: счётчик, пустой период, пересечение границы периода многодневкой/бессрочным
- [x] 1.4 Чистые функции зума/дропа: `zoom_target(level, anchor_row)`, `drop_actions(event, target_day) -> {move, extend_down, start_earlier}`, `apply_drop_action(event, action, target_day) -> (start, end)` с clamp календарём; тесты всех направлений: вниз-вне-конца, вверх-вне-начала, внутри промежутка (только move), same-day, бессрочные (extend_down отсутствует)
- [x] 1.5 `hide_empty`-фильтр в `build_rows` (вырезает EmptyDay/GapCollapsed/пустые PeriodCard) и overlap-видимость событий по окну (`start <= win_end AND (end is None OR end >= win_start)`); тесты: тумблер прячет/возвращает, пересекающее окно событие видно

## 2. ViewModel

- [x] 2.1 Заменить `unit`/`group_by`/`_current_filter` на `level` (DAY/MONTH/YEAR, default на load), `window`, `hide_empty`; setter-ы вызывает `_rebuild_rows()`; мемо-ключ `_version_of()` расширить новыми полями; тесты в `tests/presentation/test_viewmodels.py` (переписать группировочные кейсы на window/level/hide_empty; удалённые тесты не оставляют coverage-дыр)
- [x] 2.2 `select_event_by_id`: если событие не представлено — `level=DAY`, `window=None`, затем выбор; выбор, исключённый окном, сбрасывает selection/панель; тесты внешних выборов (из поиска) внутри/снаружи окна

## 3. Делегат и sticky

- [x] 3.1 Переработать `_RowDelegate`: отрисовка `EventRow` (метка типа `color.chart.k`, название, tooltip `name + start — end`), `EmptyDayRow` («+» иконка + «нет события»), `GapCollapsedRow` (границы игровым форматом, приглушённый), `PeriodHeaderRow/PeriodCardRow` («N событий» / «нет событий»); удалить `_paint_rail`, скобки/засечки, `ROLE_SHOW_*`; widget-тесты цветов из токенов (обновить `test_e2e_timeline_theme`)
- [x] 3.2 Перевести sticky-оверлей на два `QLabel` с push-out анимацией (~120 ms, QPropertyAnimation) по строкам заголовков секций; текст из ядра (`sticky_state` в `timeline_rows.py`); удалить rail-follow; widget-тест: позиции оверлеев при переходе заголовка, отсутствие перехвата мыши

## 4. Зум и навигация

- [x] 4.1 `wheelEvent`: Alt/Opt+колесо = смена уровня с якорем от строки под курсором (карточка → её день/период, header → свой период); удалить Ctrl-ветку, `_step_scale`, `zoom_into_unit`, `scale_buttons`, `LADDER_CAPTIONS`; тесты: Alt-колесо с уровня на уровень, Ctrl игнорируется, якорь от мыши
- [x] 4.2 Drill-in: клик по `PeriodCardRow` → `level` глубже + `window` = период (год→месяцы, месяц→сутки), без сигналов выбора; тесты на оба проваливания и отсутствие id-сигналов

## 5. Drag с контекстным меню

- [x] 5.1 Жест в `TimelineListView`: press на `EventRow` → порог 4px → `drag_preview` (приглушённая исходная карточка + призрак из акцент-токенов на строке целевого дня, sticky = целевая дата); отпускание над `GapCollapsedRow`/вне строк/после Esc = cancel; внешняя пересборка = cancel; удалённая экстраполяция за край подтверждается тестом (release за последним рядом — cancel)
- [x] 5.2 На валидном отпускании — `QMenu` у курсора из `drop_actions`; выбор действия → `apply_drop_action` → сигнал `event_dates_moved(event_id, start, end)`; закрытие меню/Esc — cancel без записей; тесты присутствия пунктов по правилам 1.4
- [x] 5.3 `wiring.on_event_dates_moved`: `cover_filter_for_span` → `cover_window_for_span` (расширение ACTIVE-окна до новых дат до записи); один commit, reload, selection-сохранение/подъём, rollback + `QMessageBox` при сбое — поведение и тесты перенести на окно; тест: перенос за окно расширяет окно
- [x] 5.4 На уровнях месяц/год жест недоступен (press-drag — no-op вместо прокрутки); тест-заглушка в e2e

## 6. Инлайн-создание из пустого дня

- [x] 6.1 Клик по `EmptyDayRow` показывает один переиспользуемый `QLineEdit`-оверлей на координатах строки; Enter → `vm.create_event_at(day, name)` (новый метод: `EventService.create_event` c `start=end=day`, тип None, затем reload+выбор); Esc/blur без текста → скрытие; тесты: создание, пустое поле не создаёт, новый event выбран

## 7. «Выбор даты» и тумблер скрытия

- [x] 7.1 Батон чипа «Все дни» → «Выбор даты» (переименовать класс/сигналы `filter_*` → `window_*`); попап применяется сразу, сброс = «Все дни»; клик по `GapCollapsedRow` открывает попап предзаполненным провалом; тесты: single-day window=1 день, live-apply, предзаполнение
- [x] 7.2 Переименовать легаси-каналы фильтра (`_DateFilterPopup`, сигналы) и убедиться, что `grep -rn filter` по timeline-файлам не находит старых имён
- [x] 7.3 Тумблер «Скрыть даты без событий» в шапке (checkable `QToolButton`/`QCheckBox`) → `vm.hide_empty`; по умолчанию выкл, не persists; e2e-тест: позиции пустоты исчезают/возвращаются на всех уровнях

## 8. Удаления

- [x] 8.1 Вырезать группировку: `EntityKind`, `group_by`, `_group_map`, `build_event_groups`, `GROUPING_*`, `group_button`, `NO_GROUP_KEY`, `Row.group_key`, `groups`-параметры; удалить/переписать затронутые тесты (`test_timeline_widget.py`, `test_timeline_scale_widget.py`, `test_viewmodels.py`)
- [x] 8.2 Вырезать рейковый код: `_RailPress`/`_SerifPress`, `serif_targets/serif_hit`, `bracket_lanes`, `BRACKET_*`/`SERIF_*`/`RAIL_*`/`EXTRAPOLATION_STEP_PX`, drag диапазона по рейке, rail-хитзоны; e2e `test_e2e_timeline_scale.py` переписать на ленту/зум-колесо
- [x] 8.3 Удалить drag-редактирование дат засечкой/тягой (`RESIZE`/`START` жеста) — остаётся только новый drop-жест; проверить отсутствие битых ссылок (`grep serif`, `grep bracket`) и зелёный `python -m pytest`

## 9. Финальная проверка

- [x] 9.1 `QT_QPA_PLATFORM=offscreen python -m pytest` — всё зелёное; прогнать e2e `tests/ui/test_e2e_timeline_theme.py`, `test_e2e_event_types.py`, обновление/удаление Scale-e2e (согласовано в задачах выше)
- [x] 9.2 Ручная smoke-проверка на реальном запуске: лента дней с дублями, контекстное меню дропа (все 3 действия), Alt/Opt-зум день↔месяц↔год с проваливанием, «Выбор даты» (1 день и окно) + тумблер скрытия, sticky push-out при скролле плотного дня, инлайн-создание в пустом дне, бессрочное с пометкой до дна ленты (каждый пункт покрыт offscreen-аналогом: дубли — ядро/widget, меню дропа — наборы пунктов по всем 3 действиям, зум+проваливание — TestWheel/TestPeriodDrill + boot-e2e, «Выбор даты»/тумблер — chip-тесты + e2e_hide_empty_toggle, push-out — TestStickyPushOut, инлайн-создание — e2e_inline_create, бессрочное — content_bottom/OPEN_MARK; субъективные ощущения живого запуска — за ревьюером)
- [x] 9.3 Обновить `docs/CHANGELOG.md` (без изменения версии: правки только в UI-логике, версии синхронизируются на релизе) и `docs/README.md`, если там описана механика таймлайна
