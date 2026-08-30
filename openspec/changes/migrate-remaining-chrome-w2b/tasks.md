## 1. Обычные диалоги

- [ ] 1.1 `llm_setup_dialog.py`: `attach_theme`, page-title×4 → фабрика `title()`, hint×3 → `hint()`, статус проверки соединения → `set_role(..., "status-ok"/"status-error")` вместо `_CHECK_OK/ERROR_STYLE`; удалить hex-константы; `python -m pytest tests/ -k llm_setup` зелёный (ожидания старых стилей поправить осознанно)

- [ ] 1.2 `event_dialog.py`: required-section bold → `title()`; `xlsx_import_dialog.py`: format-label → `title()`, `format_text` mono → роль `field` + mono-токен вместо inline-QSS; **`color.font.family.mono` заводится здесь** (в `tokens.json` + `REQUIRED_TOKEN_KEYS`; в W2a токен снят как мёртвый — его никто не читал), правило/роль, которая его применяет, появляется в этом же коммите; пиксель/свойство-тесты моноширинного блока зелёные

- [ ] 1.3 `image_viewer_dialog.py`, `entity_card_dialog.py`: `attach_theme`; placeholder изображения → `card`-роль вместо `palette(mid/base)`; правка существующих entity_card-тестов; `python -m pytest tests/ -k "image or entity_card"` зелёный

## 2. Панели главного окна

- [ ] 2.1 `detail_panel.py`: `attach_theme`, panel-title → `title()`, карточки → `card`-роль, 4 related-списка → list-роль (удалить `_list_style`); `rating_to_color()` читает концы градиента из runtime-токенов `color.rating.low/high` (интерполяция/alpha без изменений); **оба токена заводятся здесь** (в `tokens.json` + `REQUIRED_TOKEN_KEYS`; в W2a сняты как мёртвые: `rating_to_color` продолжала держать literals), смена значения токена обязана менять UI без правок экранов; пиксельный E2E: фон rating-карточки при max-rating == `color.rating.high` (обе темы, как E2E пилотов W2a)

- [ ] 2.2 `timeline_widget.py`: title → фабрика, list → list-роль (удалить `palette(mid/highlight)`-QSS); `search_bar.py`: попап результатов → list-роль, `header.setBackground(palette().mid())` → border-токен из runtime; визуальный прогон accent-slip выделений — при подтверждении «слипания» завести `color.selection` (isolated-commit: токен + `::item:selected`) и зафиксировать решение в CHANGELOG

- [ ] 2.3 `main_window.py`: `QSplitter::handle` → border-токен (роль/правило), `_DocViewerDialog` → mono-токен вместо `QFont("Menlo...")`; `related_section.py` — проверка покрытия (ожидаемо без правок); `table_host/panel.py` → `attach_theme` Qt-chrome; `python -m pytest tests/ -k main_window` зелёный

## 3. Character-sheet-диалоги

- [ ] 3.1 `preset_dialog.py`, `list_dialog.py`: `attach_theme` + роли на формы/таблицы/кнопки; regression: канвас/таблицы значений не перекрашены правилами каталога; `python -m pytest tests/ -k "preset or list_dialog"` зелёный

- [ ] 3.2 `editor_dialog.py`, `fill_dialog.py`: `attach_theme` chrome-форм (панели инструментов, поля настроек), канвас и `QGraphicsProxyWidget`-поля — без правок; пиксельный E2E: chrome editor-диалога == токены, пиксель канваса == прежнему цвету (обе темы); существующие char-sheet-тесты зелёные

## 4. Mention и AI

- [ ] 4.1 `compiler.py`: добавить `mention_style(tokens, theme)` (inline-HTML-строка с accent); `mention_text_edit.py`: убрать `_MENTION_STYLE`-литерал, стили брать из компилятора; `attach_theme` расширить `on_retheme`-колбэком, `MentionTextEdit` регистрирует `refresh_content()` (сохранение/восстановление позиции курсора); юнит-тесты: HTML упоминания содержит accent обеих тем; live-смена темы не роняет редактор и сохраняет/markup через `getContent()`

- [ ] 4.2 `ai_assist_button.py`: строки ACTIVE/DISABLED — производные `accent_rgba()`/muted из компилятора вместо hardcoded rgba; пересборка стилей по theme-listener; e2e проходят по `aiState`-маркеру (цвета не grep-аются), `python -m pytest tests/ -k ai_assist` зелёный

- [ ] 4.3 `_MentionPopup`: проверить, что попап покрыт popup-листом W2a целиком (правила по классам `_MentionPopup` — фон контейнера, и `MentionPopupListView` — элементы); при промахе — поправить селектор popup-листа (isolated); пиксель: выделенный элемент == accent/accent.fg, полоса под списком == `color.bg.surface`

## 5. Лаунчер-остаток и зачистка

- [ ] 5.1 `game_launcher_dialog.py`: title bold-16 → `title(size="xl")`, удалить `setStyleSheet`; существующие лаунчер-тесты (включая пиксель W1) зелёные

- [ ] 5.2 Новый тест `tests/presentation/test_no_chrome_hex.py`: проход по `app/presentation/views/**` (кроме канвас-слоя `character_sheet/canvas*`) — ни hex-литералов, ни вызовов `palette(` вне белого списка; тест зелёный на текущем состоянии

## 6. Приёмка и документация

- [ ] 6.1 Ручной smoke в обеих темах: лаунчер, llm_setup (статусы), entity_card, char-sheet editor (канвас не тронут), mention (ввод @, клик), AI-кнопка, комбо/календарь/тултип; `QT_QPA_PLATFORM=offscreen python -m pytest` полностью зелёный

- [ ] 6.2 `docs/CHANGELOG.md`: эпик W — W2 завершён (W2a+W2b, эпик открыт до W3); `docs/design-system-roadmap.md`: строки W2 (обе) → «влито», остаток W2 → вычеркнут; финальная приёмка: смена `color.accent` в токенах меняет mention, AI-active, выделения списков и кнопку «Показать» без правок экранов (сценарий specs `ui-theme`)
