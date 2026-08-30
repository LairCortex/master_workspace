# Tasks: add-event-timeline-tracks-w3

## 1. Чистое ядро геометрии (track_layout)

- [x] 1.1 Создать `app/presentation/views/track_layout.py` без Qt-импортов: вход (список `(event_id, start, end|None)`, метрики вьюпорта `TrackMetrics`: axis_h, padding, lane gap, min/max высота дорожки, min ширина полосы), выход (plan: rect'ы полос, id, текст-фит flag, число дорожек, content/scroll-высоты). Проверить: модуль импортируется без QApplication.
- [x] 1.2 Реализовать упаковку: sort `(start, id)` + greedy first-fit по дорожкам. Проверить: `tests/presentation/test_track_layout.py` — 3 взаимно пересекающихся события → 3 дорожки; непересекающиеся → 1 дорожка; детерминизм (одинаковый вход дважды → идентичный plan; перестановка входа не меняет plan после сортировки).
- [x] 1.3 Реализовать шкалу: x(date) линейная по ординалам по всему диапазону выборки; padding; одиночное событие → полоса на всю ширину; однодневка → не уже min_bar_w с двусторонним стиранием симметрично. Проверить: юниты на точные rect'ы (день=ровная доля ширины).
- [x] 1.4 Реализовать идущие события (`end=None`): полоса до правого края области полос + флаг маркера скоса. Проверить: юнит — x1 == правый внутренний край, flag открытого конца.
- [x] 1.5 Реализовать вертикаль: высота дорожки = clamp((viewport_h − axis_h)/N − gap, MIN, MAX); переполнение при MIN → content_h > viewport_h (скролл-высота). Текст-фит: bar_w >= text_w+inset && lane_h >= MIN_TEXT_H. Проверить: юниты на границы клампов и текст-фит.
- [x] 1.6 Реализовать hit-test (точка→event_id, верхняя по отрисовке полоса) и scroll-маппинг (visible_y→полоса, `scroll_to` id). Проверить: юниты (попадание между полосами → None; полоса вне вида + scroll_to → в входит).

## 2. Полотно TimelineCanvas

- [x] 2.1 В `timeline_widget.py` добавить `TimelineCanvas(QWidget)`:хранящий plan из track_layout, paintEvent (фон/surface, вертикальные hairline границ месяцев, ось с подписями игровых месяцев через `format_game_date` + game_settings custom months, полосы, скос идущих, выделение/hover), mousePress/mouseDoubleClick → сигналы с **event_id**, wheelEvent → внутренний вертикальный скролл. Проверить: widget-тест в offscreen-режиме — клик по центру полосы эмитит id, dblclick эмитит id, wheel меняет offset и repaint не падает.
- [x] 2.2 Цвета только из токенов: хелпер производных accent (Extend существующий `accent_rgba`/compiler-механизм W2b, без новых токенов); подписи — `color.fg.muted`, сетка — `color.border`, фон — `color.bg.surface`; live re-theme через `ThemeRuntime.add_listener` (пересчёт QColor + update, выбор и scroll сохранены). Проверить: widget-тест — смена темы меняет fill выбранной полосы, selected id не сброшен; grep-инвариант `test_no_chrome_hex.py` зелёный над этим файлом (правка теста не нужна: он с W2b сканирует весь `views/**`).
- [x] 2.3 Tooltip (QToolTip: название + диапазон дат, «—» для открытого конца) и скрытие подписей по текст-фит; hint «Нет событий в диапазоне» (роль hint / `color.fg.muted`) при пустой выборке. Проверить: widget-тесты — нет событий → hint-текст в полотне; узкая полоса → tooltip-текст доступен (через QToolTip.text() или объект хелпера).
- [x] 2.4 Публичный API канваса: `set_events(events, selected_id)`, `set_selected(id)` (идемпотентен), `scroll_to_event(id)`. Проверить: выбор извне подсвечивает полосу; повторный set_selected тем же id не пересобирает plan.

## 3. Замена списка в панели

- [x] 3.1 В `TimelineWidget` заменить `QListWidget` на `TimelineCanvas`, сохранив имя класса, шапку («+»-меню, CustomDateEdit-фильтр, apply/clear) и сигналы `add_event_requested`, `add_entity_requested`, `filter_changed`; удалить `event_selected(int row)`/row-сигналы и `set_role(list_widget,"list")`; attach_theme шапки + listen канваса. Проверить: `tests/presentation/test_views.py` — конструкция панели, наличие фильтр-виджетов и «+», dblclick-сигнал существует.
- [x] 3.2 `TimelineViewModel`: `select_event(index)` → `select_event_by_id(id)` (None при отсутствии id в видимой выборке); сигналы `events_changed`/`selected_event_changed` — прежняя семантика. Проверить: `tests/presentation/test_viewmodels.py` — выбор по id, промах → без сигнала/сброс, filter semantics зелёные.
- [x] 3.3 Переписать wiring (`app/application/wiring.py`): selection→detail по id; dblclick→edit-диалог по id; search-jump → `select_event_by_id` + `scroll_to_event` (убрать `list_widget.setCurrentRow`); все пути мутации остаются с load/update и сохранением выбора по id — это create и edit (delete-пути событий в приложении нет, grep пуст). Проверить: E2E создания/выбора/редактирования проходят. Слои согласованы: VM притеняет `selected_event`, когда видимый набор изменился, wiring по `selected_event_changed` чистит панель деталей.

## 4. Тесты и приёмка

- [x] 4.1 Переписать E2E-хелперы (`tests/ui/helpers.py`): клик/двойной клик по полосе события через `track_layout` (id→центр rect), вместо `list_widget.item(i)`. Проверить: `tests/ui/test_e2e_events.py`, `test_e2e_wiring_gaps.py` (включая search→выбор), `test_e2e_months.py` (названия кастомных месяцев на оси), `test_e2e_images.py`, `test_application_boot.py` — зелёные.
- [x] 4.2 Пиксельная приёмка tok-инварианта (обе темы, grab-пиксель == ожидаемый QColor из токенов): fill/выделение полос, hairline сетки; тест «правка `color.accent` в копия токенов → полоса перекрашивается без правок экранов». Проверить: новый `tests/ui/test_e2e_timeline_theme.py` зелёный в offscreen.
- [x] 4.3 Прогнать полный контур: `QT_QPA_PLATFORM=offscreen python -m pytest`; line coverage по текущему CI-порогу (`python -m pytest --cov`). Локально (macOS): 1899 passed, все файлы W3 — 100%, но гейт `fail_under=100` НЕ проходит: total 99.87%, 15 непокрытых строк и все вне W3 — `detail_panel` 4, `mention_text_edit` 3, `ai_assist_button`, `image_viewer_dialog`, `main_window`, `world_snapshot_widget` по 2; это off-skin- и exception-ветки W2b, а не «платформенно-зависимые» строки. Формулировка статуса: «100%-гейт подтверждается прогоном CI на Linux», а не «все зелёные локально» (цифры финального прогона — в CHANGELOG).
- [x] 4.4 Lint как в CI (`ruff check app/ tests/` — воркфлоу build.yml, lint job, ошибки E+F). Проверить: команда локально завершается без ошибок.

## 5. Документация

- [x] 5.1 `docs/CHANGELOG.md`: запись W3 (шкала событий вместо списка;breaking id-контракт UI-слоя; эпик W — остаток до Q-эпика). Проверить: запись по формату существующих.
- [x] 5.2 `docs/design-system-roadmap.md`: строка W3 → «реализован, ждёт коммита/мерджа» («влито» ставится только фактом коммита/мерджа — migration plan); снять «не начато»; зафиксировать, что зум/drag/дорожки-по-сущностям — вне карты (не закрыто молча), и что W2b уже в main (`4810755`). Проверить: таблица, текст W3-абзаца и заголовок CHANGELOG не противоречат друг другу и git-состоянию.

## 6. Правки по ревью W3

- [x] 6.1 Hit-test: верхняя по порядку отрисовки полоса (`reversed(bars)`), а не первая — расширение до `min_bar_w` реально создаёт перекрытия внутри дорожки. Проверить: `test_hit_test_inside_a_lane_prefers_the_bar_painted_on_top`.
- [x] 6.2 Тики оси — только настоящие границы месяцев; `range_start` больше не подставляется вместо первого числа, подмесячный интервал остаётся без тиков. Удалён мёртвый параметр `tick_months` (`_step_months(d, n)` → `_next_month_start(d)`): прогрессивная детализация осталась только как клиппинг подписей. Проверить: `test_ticks_are_month_boundaries_only`, `test_range_start_on_a_month_border_is_ticked`, `test_sub_month_range_has_no_ticks_but_still_maps_dates`, e2e `test_e2e_months.py` (ожидания подписей — границы месяцев).
- [x] 6.3 Оф-скин палитры: вместо числовых `(128,128,128)/(0,0,0)/(255,255,255)` — именованные Qt-глобалы; ссылка на «D7» (чужой дизайн-легенды W2a) заменена на собственное решение D4 + spec-сценарий «Вне скина». Проверить: `test_off_skin_palette_used_without_runtime`.
- [x] 6.4 Tooltip при наведении на любую полосу зафиксирован в design D5 + spec-сценарий «Подсказка доступна и на подписанной полосе» (дрейф стал решением). Проверить: `test_hover_shows_tooltip_with_name_and_range` (текст на полосе помещается).
- [x] 6.5 Выбор симметричен по слоям: `TimelineViewModel` притеняет `selected_event` при пересчёте видимого набора (filter/reload) и эмитит `selected_event_changed`; wiring по этому сигналу чистит панель деталей и подсветку канваса. Проверить: `test_filter_prunes_selection_that_left_the_visible_set`, `test_reload_keeps_selection_that_is_still_visible`, e2e `test_filtering_out_the_selected_event_clears_every_layer`.
- [x] 6.6 Скролл: `set_events` с другим набором id отматывает полотно в начало (тот же набор — позицию сохраняет). Проверить: `test_membership_change_rewinds_scroll`.
- [x] 6.7 Перф: план и замеры подписей закэшированы по (версия событий, размер вьюпорта, шрифт); комментарий «cheap» переписан по факту. Проверить: `test_plan_is_cached_until_its_inputs_change`.
- [x] 6.8 Колесо: один нотч = одна строка дорожки (`WHEEL_ANGLE_NOTCH`). Проверить: `test_wheel_notch_scrolls_exactly_one_lane_row`.
- [x] 6.9 Документация статуса: roadmap/CHANGELOG больше не противоречат друг другу и git (W2b — в main `4810755`, W3 — ждёт коммита); задача 4.3 переформулирована под реальный локальный coverage; proposal Impact дополнен файлами, реально попавшими в diff.
