## 1. Обычные диалоги

- [x] 1.1 `llm_setup_dialog.py`: `attach_theme`, page-title×4 → фабрика `title()`, hint×3 → `hint()`, статус проверки соединения → `set_role(..., "status-ok"/"status-error")` вместо `_CHECK_OK/ERROR_STYLE`; удалить hex-константы; `python -m pytest tests/ -k llm_setup` зелёный (ожидания старых стилей поправить осознанно)

- [x] 1.2 `event_dialog.py`: required-section bold → `title()`; `xlsx_import_dialog.py`: format-label → `title()`, `format_text` mono → роль `field` + mono-токен вместо inline-QSS; **`font.family.mono` заводится здесь** (в `tokens.json` + `REQUIRED_TOKEN_KEYS`; в W2a токен снят как мёртвый — его никто не читал), правило/роль, которая его применяет, появляется в этом же коммите; пиксель/свойство-тесты моноширинного блока зелёные

- [x] 1.3 `image_viewer_dialog.py`, `entity_card_dialog.py`: `attach_theme`; placeholder изображения → `card`-роль вместо `palette(mid/base)`; правка существующих entity_card-тестов; `python -m pytest tests/ -k "image or entity_card"` зелёный

## 2. Панели главного окна

- [x] 2.1 `detail_panel.py`: `attach_theme`, panel-title → `title()`, карточки → `card`-роль, 4 related-списка → list-роль (удалить `_list_style`); `rating_to_color()` читает концы градиента из runtime-токенов `color.rating.low/high` (интерполяция/alpha без изменений); **оба токена заводятся здесь** (в `tokens.json` + `REQUIRED_TOKEN_KEYS`; в W2a сняты как мёртвые: `rating_to_color` продолжала держать literals), смена значения токена обязана менять UI без правок экранов; пиксельный E2E: фон rating-карточки при max-rating == `color.rating.high` (обе темы, как E2E пилотов W2a)

- [x] 2.2 `timeline_widget.py`: title → фабрика, list → list-роль (удалить `palette(mid/highlight)`-QSS); `search_bar.py`: попап результатов → list-роль, `header.setBackground(palette().mid())` → border-токен из runtime; визуальный прогон accent-slip выделений — при подтверждении «слипания» завести `color.selection` (isolated-commit: токен + `::item:selected`) и зафиксировать решение в CHANGELOG

- [x] 2.3 `main_window.py`: `QSplitter::handle` → border-токен (роль/правило), `_DocViewerDialog` → mono-токен вместо `QFont("Menlo...")`; `related_section.py` — проверка покрытия (ожидаемо без правок); `table_host/panel.py` → `attach_theme` Qt-chrome; `python -m pytest tests/ -k main_window` зелёный

## 3. Character-sheet-диалоги

- [x] 3.1 `preset_dialog.py`, `list_dialog.py`: `attach_theme` + роли на формы/таблицы/кнопки; regression: канвас/таблицы значений не перекрашены правилами каталога; `python -m pytest tests/ -k "preset or list_dialog"` зелёный

- [x] 3.2 `editor_dialog.py`, `fill_dialog.py`: `attach_theme` chrome-форм (панели инструментов, поля настроек), канвас и `QGraphicsProxyWidget`-поля — без правок; пиксельный E2E: chrome editor-диалога == токены, пиксель канваса == прежнему цвету (обе темы); существующие char-sheet-тесты зелёные

## 4. Mention и AI

- [x] 4.1 `compiler.py`: добавить `mention_style(tokens, theme)` (inline-HTML-строка с accent); `mention_text_edit.py`: убрать `_MENTION_STYLE`-литерал, стили брать из компилятора; `attach_theme` расширить `on_retheme`-колбэком — это sugar над `ThemeRuntime.add_listener` для контента вне QSS, в production его используют `detail_panel` (rating-тинты), `search_bar` (шапки результатов) и `world_snapshot_widget` (узлы дерева); `MentionTextEdit` сам является виджетом, а не chrome-корнем, поэтому подписывает `refresh_content()` напрямую через `add_listener` (тот же путь): сохранение позиции курсора + `document().isModified()` не пачкается; юнит-тесты: HTML упоминания содержит accent обеих тем; live-смена темы не роняет редактор, сохраняет markup через `getContent()`, undo-историю и флаг modified (изменённый документ остаётся изменённым)

- [x] 4.2 `ai_assist_button.py`: строки ACTIVE/DISABLED — производные `accent_rgba()`/muted из компилятора вместо hardcoded rgba; пересборка стилей по theme-listener; e2e проходят по `aiState`-маркеру (цвета не grep-аются нигде, включая финальную приёмку 6.2 — там accent pin'ится пиксельным композитом), `python -m pytest tests/ -k ai_assist` зелёный

- [x] 4.3 `_MentionPopup`: проверить, что попап покрыт popup-листом W2a целиком (правила по классам `_MentionPopup` — фон контейнера, и `MentionPopupListView` — элементы); при промахе — поправить селектор popup-листа (isolated); пиксель: выделенный элемент == accent/accent.fg, полоса под списком == `color.bg.surface`

## 5. Лаунчер-остаток и зачистка

- [x] 5.1 `game_launcher_dialog.py`: title bold-16 → `title(size="xl")`, удалить `setStyleSheet`; существующие лаунчер-тесты (включая пиксель W1) зелёные

- [x] 5.2 Новый тест `tests/presentation/test_no_chrome_hex.py`: проход по `app/presentation/views/**` (кроме канвас-слоя `character_sheet/canvas*`) — ни hex-литералов, ни вызовов `palette(` вне белого списка; тест зелёный на текущем состоянии

## 6. Приёмка и документация

- [x] 6.1 Ручной smoke в обеих темах: лаунчер, llm_setup (статусы), entity_card, char-sheet editor (канвас не тронут), mention (ввод @, клик), AI-кнопка, комбо/календарь/тултип; `QT_QPA_PLATFORM=offscreen python -m pytest` полностью зелёный

- [x] 6.2 `docs/CHANGELOG.md`: эпик W — W2 завершён (W2a влит, W2b реализован и ждёт коммита/мерджа; эпик открыт до W3 — честный статус до фактического мерджа, review-фикс); `docs/design-system-roadmap.md`: строки W2 (обе) → правдивый статус (W2a «влито», W2b «ждёт мерджа»), остаток W2 → вычеркнут; финальная приёмка: смена `color.accent` в токенах меняет mention, AI-active, выделения списков и кнопку «Показать» без правок экранов (сценарий specs `ui-theme`)

- [x] 6.3 Аудит W2b (второй проход) — все пункты исправлены: cleanup app-stylesheet в приёмочном тесте (иначе персонализированный popup-лист утекает на последующие тесты); приёмка AI-кнопки переведена на `aiState`-маркер + пиксель-композит вместо grep rgba-подстроки (контракт spec «цвета не grep-аются»); `isValid` для border-токена шапок поиска (битый токен больше не рисует чёрное); `refresh_content()` восстанавливает `document().isModified()` (live-смена темы не делает открытые карточки «грязными»); rating-тинт рисуется внутри card-рамки + `WA_StyledBackground` на карточке (рамка из border-токена снова разделяет строки related-списка); убран `_check_theme_runtime` (half-theming вопреки D7); `color.font.family.mono` → `font.family.mono` (namespace `color.*` = только цвета, иначе web-игроку уходит `--color-font-family-mono`); `on_retheme` выведен в production (detail/search/snapshot) вместо мёртвого параметра; снята тавтология off-skin-теста mention; документация: user-visible оф-скин-деградация rating, честный статус D1, опечатки CHANGELOG; `QT_QPA_PLATFORM=offscreen python -m pytest` зелёный (1837 passed)
