## 1. Ядро строк (timeline_rows.py)

- [x] 1.1 Переписать `app/presentation/views/timeline_rows.py`: `Row` = одно событие (`event_id`, `start`, `end|None`, `name`, тип-индекс, готовый `caption` `start — end · name` / `start — ∞ · name`); `build_rows(events, window)` фильтрует по пересечению интервала с окном и сортирует `(`start_date`, `id`)`. Удалить генерацию пустых дней, схлопывание провалов, карточки периодов, `RowKind`, `index_at_y`/`normalize_range`, `sticky_state`/`zoom_level`/`zoom_target`/`drill_target`/`drop_actions`/`apply_drop_action`/`jump`. Проверить: модуль импортируется без QApplication.
- [x] 1.2 Переписать `tests/presentation/test_timeline_rows.py` под плоское ядро: одно событие = одна строка (многодневка не дублируется), бессрочное даёт `∞`, правило пересечения окна (вкл. бессрочное и начинающееся раньше окна), сортировка `(`start_date`, `id`)`, пустая выборка/пустое окно → пустой список. Проверить: `python -m pytest tests/presentation/test_timeline_rows.py` зелёный.

## 2. View model

- [x] 2.1 В `app/presentation/viewmodels/timeline_viewmodel.py` удалить `level`/`Level`, sticky/zoom/drill/jump-состояние; `window`+`_reproject_window` перевести на правило пересечения из 1.1; `select_event_by_id` — если событие вне окна, сбросить окно в `None` («Все дни»), иначе выбрать; `row_model` питается новым `build_rows`. `all_events`/`events`/`selected_event`/`events_changed`/`selected_event_changed` сохраняются. Проверить: существующие юниты VM зелёны + новый юнит на «выбор вне окна сбрасывает окно» и «бессрочное видно в окне».
- [x] 2.2 Переписать `tests/presentation/test_timeline_row_model.py`: `get(index)` отдаёт скаляры упрощённой строки (`event_id`, `caption`, `token_key`, `flags` только `selectable`); `rowCount` == длина плоского списка. Проверить: `python -m pytest tests/presentation/test_timeline_row_model.py` зелёный.

## 3. Фасад и остров

- [x] 3.1 В `app/presentation/views/timeline_island.py` удалить сигналы `event_dates_moved`/`event_create_requested`, обработчики drop/inline/sticky/zoom/hideEmpty/jump, `QShortcut Alt+Up/Down`, `_show_drop_menu`, `_descend_for_jump`, путь `cover_window_for_span`. Публичные `update_events`/`set_selected`/`scroll_to_event` и сигналы `event_selected`/`event_double_clicked`/`add_event_requested`/`add_entity_requested`/`event_types_requested`/`window_changed` сохраняются (id-контракт). Проверить: `python -c "import app.presentation.views.timeline_island"` и widget-тест импорта фасада зелёны.
- [x] 3.2 Переписать `app/presentation/qml/TimelineRoot.qml` и `TimelineRowDelegate.qml` на плоский список: одна текстовая строка `caption` + левая метка по `token_key`; sticky-оверлей, drop-жест, inline-поле, jump-кнопки, тумблер скрытия и zoom-обработчики колеса удалены; колесо = обычная прокрутка. Чип `windowText` остался и по-прежнему вызывает попап. Проверить: `python -m pytest tests/presentation/test_timeline_island.py` зелёный.
- [x] 3.3 В `_show_add_menu` фасада оставить ровно 6 пунктов («Новое событие» + character/location/organization/item + «Типы событий…»); «Типы событий…» эмитит `event_types_requested`. Проверить: widget-тест открывает меню и по каждому пункту приходит нужный сигнал.
- [x] 3.4 `timeline_date_popup.py` — проверить без изменений логики тап-старт/тап-финиш/«Сбросить»; если есть ветки предзаполнения от провала/drill-окна — удалить их точки входа (сам попап остаётся widgets-мостом). Проверить: попап открывается из чипа, применяет окно и сбрасывает; `python -m pytest tests/presentation -k date` зелёный.

## 4. Проводка приложения

- [x] 4.1 В `app/application/wiring.py` убрать подключение `event_dates_moved` и инлайн-создания у панели шкалы; сохранить вейринг `event_selected`→детали, `event_double_clicked`→редактор, `add_event_requested`/`add_entity_requested`, `event_types_requested`→`EventTypesDialog` и `window_changed`. Проверить: `python -m pytest tests/application` зелёный; grep `event_dates_moved`/`event_create_requested` в `wiring.py` пуст.

## 5. Тесты поверхности

- [x] 5.1 Переписать `tests/presentation/test_timeline_island.py` под плоский список: клик по строке эмитит `event_selected(id)`, двойной клик — `event_double_clicked(id)`, клик вне строк (пусто) ничего не эмитит, чип открывает попап, «+»-меню (6 пунктов). Проверить: файл зелёный в offscreen (`QT_QPA_PLATFORM=offscreen`).
- [x] 5.2 Переписать `tests/ui/test_e2e_timeline_theme.py` на строку+метку типа+выделение: grab-пиксели метки == токену `color.chart.k`, подсветка == accent обеих тем, live-retheme без потери выбора/скролла (без карточек/периодов/призрака). Проверить: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_e2e_timeline_theme.py` зелёный.
- [x] 5.3 Удалить `tests/presentation/test_timeline_day_ladder.py`, `tests/ui/test_e2e_timeline_scale.py`, `tests/ui/test_timeline_smoke_w3b.py`; `tests/ui/timeline_probe.py` упростить под плоскую ленту или удалить вместе с его потребителями. Проверить: `python -m pytest tests/presentation tests/ui` зелёный; мёртвых импортов удалённых модулей нет (`grep` по имени не находит ссылок).
- [x] 5.4 Проверить инварианты без правок: `python -m pytest tests/presentation/test_no_chrome_hex.py` зелёный; `grep` по `app/presentation/views/timeline_island.py` и `app/presentation/qml/Timeline*.qml` не находит hex-литералов/`palette()`/`QGraphics`.

## 6. Интеграция и приёмка

- [x] 6.1 Прогнать весь набор и гейт покрытия: `QT_QPA_PLATFORM=offscreen python -m pytest` зелёный с существующим `--cov-fail-under`. Проверить: команда завершается успешно, CI-гейт пройден.
- [x] 6.2 Ручная/семантическая приёмка на реальном старте (`python -m app.main`): плоский список событий, одна строка на событие, `∞` у бессрочных, метка типа, клик→детали, двойной клик→карточка, чип «Выбор даты» фильтрует по пересечению, «+»-меню создаёт сущности и открывает «Типы событий…», поиск подсвечивает событие (вне окна — сбрасывает окно). Проверить: сценарии проходятся без исключений в логе.

## 7. Плейсмент в документации

- [x] 7.1 Добавить срез в `docs/design-system-roadmap.md`: сложность лестницы (`W3c`-лестница/`W4`-ступени/`W5`-drag/inline/sticky/провалы) откатана к плоскому списку; QML-остров, чип-календарь и метки типов сохранены; статус текущей карты обновить.
- [x] 7.2 Запись в `docs/CHANGELOG.md` в разделе «Unreleased» (упрощение шкалы до плоского списка; удалённые жесты и ступени). Версию `0.17.0` в `pyproject.toml`/`nri_manager.spec` не менять. Проверить: текст прочитан, диффом затронуты только roadmap и CHANGELOG.
- [x] 7.3 При архивации изменения синхронизировать основной спек: заменить текст `## Purpose` в `openspec/specs/event-timeline/spec.md` на описание плоского списка (дельта Purpose для существующей возможности не применяется автоматически). Проверить: основной спек после archive/staging описывает плоский список без упоминаний лестницы.

## 8. Описание в строке и поле колонки (замечания приёмки)

- [x] 8.1 Ядро: `Row.detail` + `row_detail(event)` — «характеристики», при их пустоте «предыстория», пробелы свёрнуты, текст ограничен `DETAIL_MAX_CHARS` с многоточием, пустого описания нет (`""`). Юниты: источник, фолбэк, пустое, сворачивание переносов, обрезка, совпадение текста с ролью. Проверить: `python -m pytest tests/presentation/test_timeline_rows.py` зелёный, модуль по-прежнему импортируется без QApplication.
- [x] 8.2 Доставка: роль `detail` в `TimelineRowModel` (`get`/`data`/`roleNames`/`_RowEntry`), ключ мемоизации `rows` читает `row_detail` — правка одного описания перестраивает ленту. Проверить: `tests/presentation/test_timeline_row_model.py` и `tests/presentation/test_viewmodels.py` зелёные (включая новый юнит про правку описания).
- [x] 8.3 Изом: `TimelineRowDelegate.qml` — вторая строка `rowDetail` (`maximumLineCount: 2`, `ElideRight`, `color.fg.muted`, на выделении — `color.accent.fg`), метка типа выровнена по строке дат; `TimelineRoot.qml` — высота строки по виду (`rowHeight` / `detailedRowHeight`), список переехал в `CardPanel` с `color.bg.canvas` (объект `timelineListCard`), ловушка промаха и подсказка пустоты — внутри поля. Проверить: `tests/ui/test_e2e_timeline_theme.py` и `tests/ui/test_e2e_timeline_flat_acceptance.py` зелёные в offscreen.
- [x] 8.4 Инварианты и доки: `tests/presentation/test_no_chrome_hex.py` зелёный, hex/`palette()`/`QGraphics` в панели не появились; полный прогон с гейтом покрытия зелёный; записи в `docs/CHANGELOG.md` (Unreleased) и срез в `docs/design-system-roadmap.md` дополнены второй строкой описания и полем колонки.
