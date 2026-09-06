## 1. Shared popup + domain (TDD)

- [x] 1.1 Красные тесты импорта: `_MentionPopup` / `MentionPopupListView` из нового `views/mention_popup.py`; существующие `test_mention_text_edit.py` / grab попавера падают на старом пути. `python -m pytest tests/presentation/test_mention_text_edit.py tests/ui/test_theme_grab.py -k mention` красный на импорте.
- [x] 1.2 Вынести попавер+иконки в `mention_popup.py`; реэкспорт из `mention_text_edit.py` для совместимости; QSS-имена классов без смены. Тесты 1.1 зелёные.
- [x] 1.3 Красный: `MentionTextEdit` не содержит `_MENTION_RE`; parse/ranges — `domain.mentions`. `pytest -k mention` красный.
- [x] 1.4 Widgets-редактор на domain; `mentions_to_html` без локального regex. Тесты 1.3 и прежний round-trip зелёные. Event/entity поля не переключать на QML.

## 2. Хост (TDD)

- [x] 2.1 Красные юниты `MentionFieldHost`: `storage` round-trip маркера; `searchRequested` при query ≥2; `insertMention` заменяет `@query`; `showResults` пустой скрывает; `mentionClicked` эмит. Без репозитория/LLM. `pytest` на файл хоста красный.
- [x] 2.2 Реализация хоста (D1/D2 mapping storage↔display, paste маркера). Тесты 2.1 зелёные.

## 3. MentionField.qml (TDD)

- [x] 3.1 Красный остров: `QQuickWidget`+хост+`islandPalette`; `objectName` `mentionField` / `mentionPlain` / `mentionCaret` / `mentionChip_<type>_<id>`; сырой `@[` в plain не виден. Без EventDialog. `pytest` красный.
- [x] 3.2 `MentionField.qml` + qmldir: chrome как `ThemeTextArea`; overlay Repeater только spans; чипы/каретка в том же flick/content; `positionToRectangle`. Тест 3.1 зелёный.
- [x] 3.3 Красные: клик чипа → `mentionClicked` без каретки внутрь; клик мимо → plain; snap каретки; Backspace/Delete/selection = целый маркер; paste storage. `pytest` красный.
- [x] 3.4 Поведение D3/D4 в QML+хосте. Тесты 3.3 зелёные.

## 4. Клавиатура, попавер-мост, IME (TDD)

- [x] 4.1 Красные: Enter при скрытом попавере = newline; при видимом Up/Down/Enter/Esc как widgets; ≥2 → `searchRequested`; Esc/Space/backspace-за-`@`; IME composing не даёт snap. `pytest` красный.
- [x] 4.2 Хост позиционирует shared `_MentionPopup` (`mapToGlobal`); клавиши D5; IME не фильтровать. Тесты 4.1 зелёные. Нет QML-Popup.

## 5. Пиксель и live-retheme (TDD)

- [x] 5.1 Красный послойный pixel: чип = hex `color.accent` обеих тем; каретка на своём слое; chrome = field-токен как `ThemeTextArea`; off-skin без выдуманного hex; без golden. `pytest` красный.
- [x] 5.2 Overlay из палитры (D6). Тест 5.1 зелёный.
- [x] 5.3 Красный: смена темы не меняет `storage` и modified plain-документа. `pytest` красный.
- [x] 5.4 Retheme только цвет overlay. Тест 5.3 зелёный.

## 6. Бандл и гейт

- [x] 6.1 `nri_manager.spec` datas + `MentionField.qml`; бандл-тест qml видит файл; `test_no_chrome_hex` на новом qml.
- [x] 6.2 `docs/CHANGELOG.md`; `docs/design-system-roadmap.md`: R5 реализован, R6 впереди.
- [x] 6.3 `python -m pytest` зелёный, coverage-гейт Python 100%.
