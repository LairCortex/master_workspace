## Context

См. proposal.md — Why. Widgets-`MentionTextEdit` — HTML-якоря в `QTextEdit`; `_MENTION_RE` и `_MentionPopup` живут в том же файле. QML `TextEdit` не держит кликабельный rich-text; гибрид остров+widgets-поле запрещён. R2 (предшественник) отдаёт `domain/mentions` (`parse` / ranges по индексам storage). R6/R7 — потребители `MentionField` в островах; здесь потребителя-продукта нет. Попавер выше края острова — widgets-мост (рамка карты).

## Goals / Non-Goals

**Goals:**
- Двухслойный `MentionField` в `nri.components` + тонкий хост; приёмка `QQuickWidget`+хост.
- Shared `_MentionPopup`; оба редактора до R7; widgets-разбор через domain.
- Послойный pixel + objectName; live-retheme без мутации storage/document.

**Non-Goals:**
- Острова event/entity, AI, rewrite rename, смена формата, QML-Popup, продуктовый стенд.

## Decisions

### D1. Хост — тонкий QObject, не VM экрана

`MentionFieldHost`: `storage` (QString, notify), сигналы `searchRequested(query)`, `mentionClicked(type, id)`, слоты `insertMention(type, id, name)`, `showResults(results)`. Поиск/клик наружу — wiring позже (R6); в R5 тесты подписываются напрямую. Альтернатива «хост сам ходит в репозиторий» отклонена (сервисы не в QML/хосте).

### D2. Display ≠ storage; ranges из domain, геометрия из plain

Хост держит storage. Domain `parse` даёт spans в индексах storage. Display-строка: маркеры заменены display-name (без `@[…](тип:id)`). Overlay Repeater только display-rect: `TextEdit.positionToRectangle` на индексах display. Маппинг storage↔display пересчитывается на Python после каждого коммита текста (не JS-грамматика). Альтернатива «показывать storage и маскировать оверлеем» отклонена (сырые маркеры видны при сбое оверлея).

### D3. Чипы и каретка в том же Flickable/content

`TextEdit` + overlay Repeater + каретка-маркер — дети одного content item, скролл общий. Overlay не отдельный `Popup`. Клик чипа: `MouseArea` на чипе, `mentionClicked`, каретку не трогать; клик мимо проходит в `TextEdit`.

### D4. Атомарный span

Каретка в `(start,end)` display-span → snap к ближайшему краю (после IME composing, не во время preedit). Backspace/Delete на границе и selection, пересекающая span, расширяются до целого маркера; undo — нативный plain. Paste: если буфер содержит storage-маркер — принять; strip скобок не здесь.

### D5. Клавиши попавера vs newline

Видимый попавер: Up/Down/Enter/Esc как `MentionTextEdit.keyPressEvent`. Скрыт: Enter = newline (`TextEdit` multiline). `@` + ≥2 символа → `searchRequested`; Space / backspace за `@` → cancel. IME: не фильтровать `inputMethodEvent`.

### D6. Chrome = ThemeTextArea; цвет чипа = accent overlay

Обёртка field-токенов как `ThemeTextArea` (не копировать QSS widgets). Чип — overlay-цвет `color.accent` / accent.fg; off-skin — Qt-глобалы, без hex. Live-retheme: биндинг палитры на overlay; `storage` и `isModified` plain-документа не трогать (не `setText` roundtrip).

### D7. `_MentionPopup` — отдельный модуль

Файл вроде `views/mention_popup.py`: `_MentionPopup`, `MentionPopupListView`, иконки типов. QSS-селекторы классов без смены имён. `MentionTextEdit` и QML-мост (Python-сторона хоста позиционирует `mapToGlobal` каретки) вызывают один класс. `mentions_to_html` остаётся у widgets-редактора до R7.

### D8. Тесты без стенда

Фикстура: shared engine + `QQuickWidget` + хост в context (`mentionFieldHost` + `islandPalette`). Нет `EventDialog`. Красные тесты до QML/host. objectName: `mentionField`, `mentionPlain`, `mentionCaret`, `mentionChip_<type>_<id>`. Pixel слоёв отдельно (chip / caret / chrome). Бандл: `MentionField.qml` в qmldir + spec datas.

### D9. Предшественник R2

Импорт `app.domain.mentions` (или фактический путь R2). Views не держат `_MENTION_RE`. Если apply идёт до merge R2 — блокируется; не дублировать regex «временно».

## Risks / Trade-offs

- [Рассинхрон display/storage при IME] → ranges/snap только после `inputMethodComposing == false`.
- [QML-Popup обрежется островом] → widgets-мост (D7).
- [Live-retheme пачкает modified] → не писать в `TextEdit` при смене темы, только overlay color.
- [Два редактора до R7] → один попавер-модуль; расхождение клавиш ловят тесты попавера.

## Migration Plan

Один merge после R2. Откат — revert. Event/entity поля не переключать. R6 берёт `MentionField`+хост как есть.

## Open Questions

_(нет)_
