# Proposal: add-event-timeline-tracks-w3

## Why

Дорога событий сейчас — `QListWidget` с двухстрочными items: длительности, параллельные события и пересечения по датам не читаются. Эпик W roadmap-графики требует W3 — Gantt-подобные дорожки событий на Widgets с токенами W1/W2, до старта QML-эпика (Q1).

## What Changes

- Таймлайн-панель главного окна: вместо `QListWidget` — кастомное полотно `TimelineCanvas` (`QWidget` + `QPainter`), одна полоса на событие, пересекающиеся события упаковываются по вертикали в дорожки (greedy first-fit по `(start_date, id)`).
- Непрерывная линейная шкала времени: вьюпорт = весь отфильтрованный диапазон, без зума и горизонтального скролла; тики и подписи по границам игровых месяцев (`game_settings` custom months, формат `format_game_date`).
- Адаптивная высота дорожек (кламп 14–26 px) с внутренним вертикальным скроллом при переполнении; прогрессивная детализация подписей на полосах; tooltip при нехватке места.
- Идущие события (`end_date is None`) — полоса до правого края со скосом-маркером.
- **BREAKING** (внутренний контракт UI-слоя): выбор события — id-центричный (`event_selected(event_id)`, `select_event_by_id(id)`);Signals с индексом строки и обращения к `list_widget` из wiring/E2E-хелперов удаляются.
- Цвета полос — только производные токенов (`color.accent` / `accent_rgba`-паттерн W2b); живая ре-тема через `attach_theme(on_retheme=)` / `ThemeRuntime.add_listener`; новых токенов не заводим.
- Шапка панели (`+`, фильтр по датам) и семантика `filter_by_dates` — без изменений. World-snapshot (дерево) и канвас чар-листа не трогаем.

## Capabilities

### New Capabilities

- `event-timeline`: визуальная шкала событий — геометрия шкалы, упаковка дорожек, id-выбор/контракт сигналов, пустые/краевые состояния, ре-тема и токен-инвариант.

### Modified Capabilities

- `ui-theme`: шкала обязана перекрашиваться сменой `color.accent` без правок экранов; инвариант «нет hex/palette()» над новым файлом действует как есть — `test_no_chrome_hex.py` с W2b сканирует весь `app/presentation/views/**`, поэтому правок теста не потребовалось (исключение инварианта сужено до канваса листа персонажа).

## Impact

- `app/presentation/views/timeline_widget.py` — полотно вместо списка; шапка остаётся.
- Новый чистый модуль `app/presentation/views/track_layout.py` (dates→lanes/rects, hit-test — без Qt-рендеринга).
- `app/presentation/viewmodels/timeline_viewmodel.py` — select по id + притенка выбора при смене видимого набора (фильтр/reload).
- `app/presentation/theme/compiler.py` — `token_rgb(tokens, theme, key)`: токен как `(r, g, b)` для QPainter-кода вне QSS (альфы считает канвас; новых токенов нет).
- `app/application/wiring.py` — 4 точки: selection/dblclick/search-jump уходят с row/`list_widget` на id + слушатель `selected_event_changed` (сброшенный выбор чистит панель деталей).
- Тесты: `tests/presentation/test_viewmodels.py`, `test_views.py`, `test_widget_gaps.py`, `tests/ui/helpers.py`, E2E `test_e2e_events.py`, `test_e2e_wiring_gaps.py`, `test_e2e_months.py`, `test_e2e_images.py`, `test_e2e_crud.py`, `test_e2e_import.py`, `test_e2e_launcher.py`, `test_w2b_review_fixes.py`.
- Попутное в diff (без отдельных задач): `tests/ui/test_theme_grab.py` — удалён дубль `test_accent_token_change_moves_mention_ai_and_selection_together` (на HEAD две одноимённые функции, первая мертва); неиспользуемые импорты убраны из `event_dialog.py` и `game_launcher_dialog.py`. Инвариант `tests/presentation/test_no_chrome_hex.py` не менялся.
- Вне скоупа: drag-редактирование дат, зум, типы/цвета событий, дорожки по сущностям, сжатие пустых периодов.
