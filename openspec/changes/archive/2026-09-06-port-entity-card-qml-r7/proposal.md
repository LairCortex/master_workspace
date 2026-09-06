## Why

Карточка сущности — последний содержательный widgets-экран эпика R. После реализованных R3–R6 её перенос на цельный QML-остров завершает дизайн эпика без гибридного редактора и сохраняет все внешние контракты карточки 1:1.

## What Changes

- Содержимое `EntityCardDialog` переносится в один `EntityCardRoot.qml` внутри прежнего `QDialog`; публичный API фасада, `entity_type` в конструкторе и контракт `open_character_sheet_requested` сохраняются 1:1.
- Дополнительные поля строятся `Repeater`-ом из Python `_FIELD_SPECS`; видимость image-колонки и related-вкладок приходит из модели, без ветвления по character в QML.
- Рейтинг остаётся локальным для острова `SpinBox` с токенами. Изображение показывается через `Image` + `MouseArea` и провайдер превью R3; выбор файла и просмотр остаются нативными `QFileDialog`/`ImageViewerDialog`. URL музыки открывается Python-стороной.
- Карточка переиспользует контракты R6: related/picker, AI-прокси, `ThemeDateField`, `MentionField`, `saveRequested` + `finish_saving` и close guard. Сохранение не получает valid-гейт.
- Удаляются legacy widgets-класс/файл `MentionTextEdit`, `related_section.py`, `ai_assist_button.py`, `clickable_label.py` и wrapper `CustomDateEdit`; popup-модуль упоминаний, `_CustomCalendar` и date-popup мост сохраняются. Grep-инвариант запрещает возвращение удалённых классов.
- Семантика тестов карточки мигрирует на QML `objectName`, применяется TDD; добавляется live-retheme-приёмка без новой поэлементной pixel-приёмки уже принятых библиотечных компонентов.
- Принятый долг не меняется: copy-out из mention-поля теряет `type:id`, а `LIKE`-поиск и detail продолжают работать с сырыми markers.

## Capabilities

### New Capabilities

_(нет)_

### Modified Capabilities

- `qml-shell`: карточка сущности становится цельным QML-островом с сохранённым нативным фасадом, синхронным VM-контрактом, системными мостами и правилами сохранения/закрытия; legacy widgets-контролы удаляются.
- `ui-testing`: приёмка карточки сущности переезжает с widget-адресации на реальный QML-остров, сохраняя семантические сценарии по типам, save-failure и live-retheme.

## Impact

- `app/presentation/views/entity_card_dialog.py`, view model/прокси карточки и wiring — фасад острова при сохранённых внешних сигналах и методах.
- `app/presentation/qml/EntityCardRoot.qml` и bundle-проверки QML.
- Переиспользуются артефакты R3–R6: image provider, `MentionField`, `ThemeDateField`, related/picker, AI-прокси и lifecycle сохранения.
- Удаляются widgets-спутники карточки и обновляются их импорты/grep-инварианты.
- Тесты карточки, ошибок сохранения, изображений, AI/mentions/related и QML live-retheme; приложение, roadmap и changelog в этом planning change не изменяются.
