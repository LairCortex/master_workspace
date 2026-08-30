## Why

W2a (механика + каталог + пилоты) закрыл только два экрана: остальные ~12 экранов живут на палитре ОС с inline-шестами (`gray`, `#888`, `#5b9bd5` mention, rgba AI-кнопки, monospace-QFont), а разделители и выделения строк рисуются `palette(mid)/highlight`. Без массового перевода остатка цель эпика W — «одна палитра на мастере и игроке, без трёх копий цвета» — недостижима, а QML-эпик (Q1) нельзя начинать.

## What Changes

- Все оставшиеся chrome-экраны подключаются к теме через `attach_theme` и переодеваются на каталог W2a; один merge, задачи-коммиты по группам:
  - **обычные диалоги**: `LlmSetupDialog` (page-title/hint-фабрики, status ok/error-роли вместо `#2e7d32/#c62828`-свопов; error на `color.danger`), `EventDialog`, `XlsxImportDialog` (mono-токен вместо inline-QSS), `ImageViewerDialog`, `EntityCardDialog` (card-роль placeholder вместо `palette(mid/base)`);
  - **character_sheet-диалоги** (preset, list, editor, fill): chrome-формы через `attach_theme` + роли; канвас, `QGraphicsProxyWidget`-поля и QPainter-цвета канваса не трогаются;
  - **виджеты главного окна**: `detail_panel` (card-роль, 4 related-списка → list-роль, `rating_to_color()` читает концы градиента из `color.rating.low/high`), `timeline_widget` (list-роль, palette → border/accent), `search_bar` (list-роль попапа, `setBackground(palette().mid())` → border-токен), `world_snapshot_widget` (оставшиеся bold/italic-шрифты дерева), `main_window` (`QSplitter::handle` → border; `_DocViewerDialog` → mono-токен), `table_host/panel.py` (Qt-chrome → attach_theme), календарь `CustomDateEdit` (проверка покрытия popup-листом без inline-переопределений);
  - **mention/AI-цвета (решение Q8=a)**: inline-HTML `#5b9bd5` у @-упоминаний → accent из токенов; ACTIVE/DISABLED rgba `ai_assist_button` → производные accent/border из компилятора W2a (маркеры тестов переведены на `testProperty` в W2a);
  - **лаунчер**: title bold-16 (остаток W1) → фабрика `title(size="xl")`, inline-`setStyleSheet` убираются;
  - **зачистка**: ноль `setStyleSheet` с hex/цветом и ноль `palette()` для chrome-целей в `app/presentation/views/**`, кроме канвас-слоя char-sheet.
- E2E-приёмка (по образцу W2a, выборочно): пиксели одного character_sheet-диалога (форма = токены), rating-карточки detail_panel (концы градиента из токенов), mention-text = accent; все существующие UI-тесты зелёные на трёх ОС.

Не входит: сам канвас char-sheet и его QPainter-цвета, W3/QML, новые экраны и фичи.

## Capabilities

### New Capabilities

_(нет — каталог введён W2a, токены W1)_

### Modified Capabilities

- `ui-theme`: MODIFIED «Область применения QSS» — все экраны мастера подключены к теме, исключение только канвас и его поля; ADDED «Хром без палитры ОС и hex» — в chrome-коде экранов мастера не остаётся `palette()`-цветов и literal-hex.
- `ui-widget-catalog`: MODIFIED «Роли каталога читаются из токенов» — упоминания и состояния AI-кнопки становятся рольями/производными токенов вместо собственного цвета; MODIFIED «Экран подключается к теме одной точкой» — сценарий «пилоты» заменяется полным покрытием экранов мастера.

## Impact

- `app/presentation/views/**` (все перечисленные файлы); `app/presentation/theme/` — только вызовы компилятора, правил новых не предвидится (кроме решения про `color.selection` при подтверждённом accent-slip — до финального merge, отдельной задачей).
- Тесты: новые пиксельные E2E + правки существующих, ожидавшие старые шрифты/цвета (`llm_setup`, `entity_card`, `detail_panel` и др.).
- Визуал (намеренно): синий mention/AI становится accent; все диалоги теряют палитру ОС; выделение/hover строк — accent.
- PyInstaller `nri_manager.spec`: новых файлов нет.
- Порядок применения: только после влития W2a (его каталог/роли/токены — зависимость).
