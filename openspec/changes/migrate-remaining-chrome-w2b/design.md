## Context

W2a (влит) принёс: `uiRole`-селекторы + `catalog.attach_theme/set_role/title/hint`, popup-лист на `QApplication`, токены каталога + `accent_rgba()`, пилоты month_settings/world_snapshot, маркеры `testProperty("aiState")`. Остаток инвентаризации (W1-ревизия): диалоги и виджеты со `setStyleSheet`/`palette()` — llm_setup (titles×4, hints×3, status-своп), event/xlsx/image_viewer/entity_card, 4 character_sheet-диалога (OS, но канвас исключение), detail_panel (card, lists×4, `rating_to_color` QColor-концы), timeline, search_bar (попап + `palette().mid()`), splitter, mention (`#5b9bd5` inline-HTML), AI-кнопка (rgba), doc-viewer (`QFont("Menlo...")`), launcher title-16, table_host Qt-chrome, CustomDateEdit (попап календаря). Мотивация/скоуп — proposal.md; контракты — specs-дельты.

## Goals / Non-Goals

**Goals:**
- Ноль chrome-`setStyleSheet`/hex/`palette()` в `app/presentation/views/**` кроме канвас-слоя char-sheet.
- Mention/AI цвета = производные accent; rating gradient endpoints = токены.
- Все экраны мастера переключают тему live через W2a-реестр; пиксельные E2E по образцу W2a.

**Non-Goals:**
- Компилятор/токены — только если всплывает оговорённый `color.selection` (решение на середине куска, не заранее).
- Канвас char-sheet (QPainter-цвета, шрифты листа), бумага/D1 CSS, формат mention-разметки (storage `@[..](..)`) — не трогаем.
- Композиция экранов (layout) — только стили.

## Decisions

### D1. Порядок = 5 коммитов-групп с зелёным pytest после каждого

`1) обычные диалоги → 2) detail/timeline/search/splitter/doc-viewer/table_host → 3) character_sheet-диалоги (chrome) → 4) mention + AI-кнопка → 5) launcher title-xl + зачистка-скан + финальные E2E`. Каждый промежуточный merge-scope остаётся рабочим: неподключённый экран просто живёт на палитре ОС до своего коммита.

### D2. Mention-цвет: inline-HTML остаётся, цвет спрашивается у компилятора

Qt rich text внутри QTextEdit не умеет QSS-наследование, и inline-`<a style>` — часть форматированного документа, а не виджета. Решение: `compiler.mention_style(tokens, theme)` отдаёт готовую inline-строку (`color:<accent>; font-weight:bold; ...`); `_MENTION_STYLE` становится function-based. Live-смена темы: `attach_theme` расширяется необязательным `on_retheme`-колбэком (вызывается в `ThemeRuntime.apply`/`set_theme` после смены); `MentionTextEdit` регистрируется с колбэком `refresh_content()` = `setContent(getContent())`.
*Alt:* QTextCharFormat + перекраска по документу — больше кода, эквивалентный результат; QSS-псевдо-класс для `<a>` в Qt отсутствует.

### D3. AI-кнопка: состояния остаются вычисляемыми, палитра — из компилятора

`ai_assist_button` хранит бизнес-логику состояний; ACTIVE/DISABLED строки строятся из `accent_rgba(tokens, theme, α)` и border/muted токенов (одна helper-функция стилей в модуле кнопки, вызывается при смене темы через listener или `on_retheme`). Маркеры `aiState` (W2a) не меняются — тесты слепы к цвету.

### D4. `rating_to_color`: endpoints только из токенов (токены заводятся в W2b)

`color.rating.low/high` (как и `color.font.family.mono`) в W2a не заведены: их не читал ни один лист/CSS, а обязательность в `REQUIRED_TOKEN_KEYS` лишь ужесточала валидацию (ревью W2a). Ключи добавляются в `tokens.json` + `REQUIRED_TOKEN_KEYS` тем же коммитом, что и читающий код.

Функция принимает endpoints из runtime (`color.rating.low/high` текущей темы); интерполяция и alpha-логика не меняются (плавный градиент — фича, не W2b). При невалидных токенах runtime уже no-op (W1-D7): экран остаётся на палитре ОС — отдельного fallback в функции нет.

### D5. Character-sheet-диалоги: `attach_theme` на QDialog, канвас защищён точечно

Формы/таблицы/кнопки наследуют chrome `[uiRole]`-правила. Канвас: QSS chrome не попадает внутрь QGraphicsScene-виджетов автоматически (proxy-виджеты — отдельные top-levels сцены), плюс regression-тест W2a «поле на канвасе не перекрашено» закрывает риск. Item-level QFont (bold/italic в деревьях snapshot) остаётся кодом контента, без токенов — зафиксированное grill-допущение.

### D6. Зачистка-скан как тест, не как grep-скрипт

Новый тест `test_no_chrome_hex.py`: AST/regex-проход по `app/presentation/views/**` кроме `character_sheet/canvas*` — запрещает hex-литералы (`#[0-9a-fA-F]{3,6}`) и `palette(` вне белого списка. Белый список: canvas-слой, `QPalette.Control`-специфичное (если всплывёт в review). Регулярная защита W2-инвариантов для будущих экранов.

## Risks / Trade-offs

- Live re-render mention-редактора при смене темы может сбросить unsaved cursor position → mitigation: `refresh_content()` сохраняет/restores позицию курсора (есть готовый `QTextCursor` state).
- Accent-slip на выделениях списков detail/timeline (оговорка Q13): проверяется визуальным прогоном по группе 2 до группы 3; при подтверждении — единственный токен `color.selection` + переключение `::item:selected` (малый isolated-commit, не блокирует остальной W2b).
- Массовые правки 12+ файлов = риск регрессий в существующих UI-тестах (ожидали старые шрифты/цвета) → обновляем ожидания осознанно, коммитами группы.
- `_MentionPopup` уже покрыт popup-листом (W2a) — если его класс был вне правила, поправляется в группе 4 (isolated).
- Ревью-размер: один merge >20 файлов осознанное решение grill (Q20); mitigation — коммиты-группы D1, ревью по history.

## Migration Plan

Коммиты D1 по порядку; после каждой группы `QT_QPA_PLATFORM=offscreen python -m pytest`. Финальная приёмка: полный проход + ручной smoke (обе темы × лаунчер, диалоги, char-sheet editor, mention, AI). Откат — revert merge-коммита; данных/артефактов нет. CHANGELOG: эпик W остаётся открытым до влития W2b; roadmap: обе строки W2 → «влито», Q1 разблокирован (с оговоркой W3-до-Q1).

## Open Questions

- Точный alpha для ACTIVE/DISABLED AI-кнопки (0.35/0.15 как сейчас или новые) — косметика, решается на apply визуальным прогоном; на specs не влияет.
- Нужен ли `status-ok/error`-роль-хелпер в llm_setup или переиспользовать фабрики W2a напрямую — код-стиль, на contract не влияет.
