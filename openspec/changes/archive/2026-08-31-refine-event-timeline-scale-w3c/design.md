# Design: refine-event-timeline-scale-w3c

## Context

HEAD после W3b: панель `TimelineWidget` = шапка («+», чип-фильтр, jump-ряд) + `TimelineListView` (`QListWidget` + `_RowDelegate`), чистое ядро `timeline_rows.py`. Зона рейки глотается `eventFilter` (press/dblclick левее `rail_width()`), hover-отслеживание уже ведётся (`mouseMoveEvent` + `_hover_row`), sticky-оверлей — child-`QLabel` с `WA_TransparentForMouseEvents` и top-отступом вьюпорта (`setViewportMargins`), шаг колеса зафиксирован в `wheelEvent`, live-применение фильтра идёт через `TimelineWidget.filter_changed(start, end)` (поповер чина — единственный источник). Мотивация и границы — proposal.md → Why; UX-решения D1–D7 зафиксированы grill-сессией 2026-08-31.

## Goals / Non-Goals

**Goals:**
- Интерактив in-list рейки (клик-прыжок, follow-дата, drag-диапазон) без новой топологии и без новых виджетов.
- 1:1 внешние контракты: `filter_changed`, id-сигналы, контракт VM/wiring, семантика чина.
- Тонкая Qt-обвязка: геометрия дня — чистые функции вне Qt (традиция `timeline_rows`), тестируемые без QApplication.
- Токен-инвариант и live-retheme без новых токенов.

**Non-Goals:**
- Toggle-сжатие пустых дней, auto-scroll при drag'е, зум, клавиатурные аналоги, жесты сброса на рейке — вне (roadmap/predlog).
- Изменение `build_rows`, высоты строк, ширины рейки, колёсного шага, Alt+Up/Down.

## Decisions

- **D1 Обработка ввода рейки — в `TimelineListView.mousePressEvent/mouseMoveEvent/mouseReleaseEvent`, eventFilter рейки удаляется.** Нативные обработчики дают press/release/drag-фазы в одной точке; eventFilter остаётся только если Qt успевает отрисовать hover до нас — не нужно. Альтернатива (оставить eventFilter и эмулировать state machine в `event.type()`) разводила бы логику жеста по двум местам. Текстовая зона: при `x >= rail_width()` обработчик ДЕЛЕГИРует базовому `QListView` поведению (клик/dblclick как раньше).
- **D2 Разведение клик/drag — порог Смещения `DRAG_START_THRESHOLD_PX = 4`, только ЛКМ.** На press в рейке — арм (якорь-день), на move до порога — ничего, после — drag-режим (мышь уже grab'ится виджетом); release до порога = клик-прыжок. Альтернатива (клик на press) несовместима с drag: прыжок случался бы в начале каждого drag'а.
- **D3 Чистые хелперы в `timeline_rows.py`: `index_at_y(rows, row_height, y) -> int | None` (нормализация к первому ряду дня) и `normalize_range(day_a, day_b) -> (date, date)`.** y→ряд делением на `ROW_HEIGHT` с учётом viewport-смещения — инвариант равновысоких строк (D4 W3b) делает hit-test тривиальным; Qt-слой передаёт `y - viewport.top + scrollbar.value`. Альтернатива (`itemAt`/`indexAt`) привязывает юнит-тесты к QApplication; `indexAt` всё же остаётся fallback для edge-случаев, но детерминированная математика — источник истины для клика/якорей drag'а. Нормализация к первому ряду дня — по `indices_by_day` (уже строится в `_rebuild`), экспорт — компактный метод view `day_anchor_index(day)`.
- **D4 Прыжок = `scrollToItem(PositionAtTop)` по верхнему viewport-краю (с учётом viewport margins) + `setCurrentIndex` без сигналов выделения.** Повторяет семантику D8 («навигация, не выбор»): выделение/`_selected_id`/id-сигналы не трогаются. Альтернатива `PositionAtCenter` оставляет половину дня над глазами — «пришлёпка к верху» даёт полный контекст вниз от дня; sticky-оверлей после прыжка автоматически покажет этот же день.
- **D5 Follow-дата — временное переписание текста sticky в hover/drag-обработчике, флаг `_follow_date_active`.** Никаких новых виджетов: `_sync_overlays` пересчитывает текст как раньше, но если follow активен — пишет дату под курсором (drag: `clamp` по вертикали к `[первый, последний]` видимый день). On leave без drag — флаг гаснет, следующий sync возвращает верхний день. Альтернатива (`QToolTip`/floating-`QLabel`) — новый top-level/оверлей с отдельной skin-обвязкой и тестами.
- **D6 Drag диапазона: wash-полоса рисуется delegate'том по `_drag_range: tuple[date, date] | None` в view; wash-цвет — производная `color.accent` (альфа уровня `ROW_HOVER_ALPHA`), вне скина — Qt-глобал.** Делегат уже красит строки по состоянию view (`hover_index`, палитра) — drag-полоса то же самое состояние. Применение — ровно один `filter_changed`-emit при release, нормализованный `normalize_range`; промежуточных пересборок модели нет, поэтому дни не убегают из-под курсора. Альтернатива (live-apply на move) пересобирает строки под курсором и ломает якорь; отдельный overlay-виджет дублирует геометрию delegate.
- **D7 Канал фильтра — сигнал панели `filter_changed`, wiring VM не меняется.** `TimelineWidget` проксирует событие view в свой существующий emit (как делает поповер); чип-подпись обновляется тем же путём, что и от поповера (единая точка `_on_filter_range`). Сброс — только поповер (кнопка), рейка сброса не знает.
- **D8 Двойной клик в рейке — early-return (consume), ЛКМ.** Требование спеки «глушится»; реализация тривиальна, пока dblclick не ушёл базовому классу.

## Risks / Trade-offs

- Следующее за drag'ом live-применение пересобирает модель и сбрасывает скролл/выбор по правилам W3b (выбор вне нового диапазона снимается) — ожидаемо, контракт не меняем; тест фиксирует, что это единственный источник пересборки во время жеста.
- Порог 4 px на сенсорных треках macOS может ловить дрог — константа модуля, правится одной правкой; E2E-тест жеста использует явные позиции.
- Конфликт follow- sticky с `_sync_overlays` по `valueChanged` при прыжке: прыжок меняет верхний день — следом hover-flag может перезаписать; порядок «sync сначала, follow поверх» фиксируется одним вспомогательным `_refresh_sticky_text()`.
- Drag на списке из 10³–10⁴ item'ов использует ту же математику деления, что и `ROW_HEIGHT` — O(1), без обращения к Qt-модели на move; при деградации — та же константа, контракт не меняется.
- Grab мыши при release вне виджета даёт `mouseReleaseEvent` с координатами вне viewport — clamp обязателен и покрыт юнитом `normalize_range`/`index_at_y`.

## Migration Plan

Один PR в main под `NRI-0009`, порядок: чистые хелперы + юниты → обработчики рейки (клик, follow) с view-тестами → drag (wash в delegate + применение) с grab/E2E → инварианты (hex, live-retheme во время drag) → CHANGELOG/roadmap «влито» только фактом коммита. Откат — revert PR; БД/форматы данных не тронуты; поведение W3b при откате восстанавливается целиком (рейка снова декоративна).

## Open Questions

- Точный alpha wash-полосы drag'а против hover-wash (0.25 как `ROW_HOVER_ALPHA` или темнее для различения при наведении на строку внутри диапазона) — подбирается ручным smoke; константа, на контракт не влияет.
