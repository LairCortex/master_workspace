# Proposal: MentionField в nri.components (R5)

## Why

QML `TextEdit` не редактирует богатый текст, а гибрид «остров + widgets-редактор» запрещён; формат `@[Имя](тип:id)` не меняется. R5 даёт двухслойный `MentionField` до R6/R7, чтобы диалоги события и карточки не тащили widgets-редактор внутрь острова.

## What Changes

- В `nri.components` — `MentionField.qml`: chrome как `ThemeTextArea`; plain-слой + overlay только spans; чипы и каретка в том же flick/content; ranges из `domain/mentions`; геометрия `positionToRectangle`.
- Тонкий `QObject`-хост: `storage`, `searchRequested`, `mentionClicked`, `insertMention`, `showResults`. Нет продуктового диалога/стенда и нет AI.
- Клик чипа → `mentionClicked` без постановки каретки внутрь; клик мимо → `TextEdit`. Caret в `(start,end)` → snap к ближайшему краю. Backspace/Delete на границе и выделение, пересекающее маркер, снимают весь span. Paste storage-маркеров разрешён; strip скобок только у попавера/rename (R2).
- Многострочность: попавер скрыт → Enter = newline; виден → Up/Down/Enter/Esc как widgets. IME не перехватываем.
- `_MentionPopup` выносится в отдельный shared widgets-модуль; его зовут QML-мост и `MentionTextEdit` до R7. Widgets-редактор переводится на `domain/mentions`. Поля event/entity на QML не переключаем.
- Live-retheme красит overlay, document/`storage` не мутирует. `objectName`: корень, plain-слой, каретка, `mentionChip_<type>_<id>`.
- Приёмка: pytest `QQuickWidget`+хост; round-trip; попавер ≥2 / Esc / Space / backspace-за-`@` / Enter|click; послойный пиксель (чип=accent, каретка, off-skin без выдуманного hex); без golden.

## Capabilities

### New Capabilities

_(нет)_

### Modified Capabilities

- `qml-components`: в библиотеку — `MentionField` (два слоя, field-chrome как `ThemeTextArea`); послойная пиксельная приёмка; live-retheme overlay без мутации документа.
- `qml-shell`: попавер завершения упоминаний — widgets-мост (не QML-Popup); тестовый остров `QQuickWidget`+хост; продуктовые диалоги события/карточки остаются widgets.
- `ui-widget-catalog`: `_MentionPopup` — shared-модуль двух потребителей; widgets-`MentionTextEdit` жив до R7 и импортирует domain, не наоборот.
- `ui-testing`: сценарии mentions для QML-поля через `QQuickWidget`+хост, не через продуктовый диалог.

## Impact

- `app/presentation/qml/nri/components/MentionField.qml` + qmldir; тонкий host (новый Python-модуль рядом с views).
- `_MentionPopup` + `MentionPopupListView` — отдельный widgets-модуль; `mention_text_edit.py` импортирует попавер и `domain.mentions`.
- `nri_manager.spec` datas + `MentionField.qml`; тесты presentation/ui на хосте и попавере.
- Не входит: R6/R7 острова, AI, rewrite/rename (R2), смена формата маркера, QML-Popup.
