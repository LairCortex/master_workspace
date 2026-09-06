## Context

См. `proposal.md` — Why и delta-спеки `qml-shell`/`ui-testing`. R7 идёт после R3–R6: общий QML engine и lifecycle R1, image provider R3, `ThemeDateField` R4, `MentionField` и popup-мост R5, `RelatedSection`, нативный picker, AI-прокси и `saveRequested`/`finish_saving` + close guard R6 считаются доступными.

Текущий `EntityCardDialog` — `QDialog` с программно собранной widgets-формой. Общие поля: name, rating 1–20, start/end + «Бессрочно», characteristics/backstory, music URL; `_FIELD_SPECS` добавляет personality/image/tasks по типу, `_RELATED_CONFIG` — related-вкладки. Фасад используется wiring через `saved`, `create_related_requested`, `mention_clicked`, `image_picked`, `open_character_sheet_requested`, `populate`, `get_data`, `get_mention_edits`, `get_ai_buttons`, `get_entity_button`, `set_*` и свойства `entity_type`/`populated_entity_id`.

## Goals / Non-Goals

**Goals:**
- Один `EntityCardRoot.qml` для всех типов, без widgets-контрола внутри острова и без character-ветвления в QML.
- Сохранить публичный Python API и wiring-контракты карточки 1:1, сменив lifecycle Save на подтверждаемую схему R6.
- Удалить последнего потребителя legacy mention/related/AI/date/image widgets-обёрток и закрепить это grep-инвариантом.
- Закрыть дизайн эпика R после семантической и live-retheme приёмки карточки.

**Non-Goals:**
- Изменение domain/entities, БД, сервисов сохранения, mention storage-формата или rewrite/search/detail-семантики.
- Новая валидация формы: у карточки нет valid-гейта.
- Перенос системных файловых/предупреждающих диалогов, image viewer, picker, date/mention popup в QML.
- Новые библиотечные компоненты для rating; `ThemeRatingCard` не переиспользуется.

## Decisions

### D1. Нативный фасад и один корень острова

`EntityCardDialog` остаётся `QDialog`, сохраняет путь импорта, ctor `(entity_vm, entity_type="organization", parent=None, theme=None)`, сигналы, свойства и публичные методы. Внутри — один `QQuickWidget` с deferred teardown по принятому island lifecycle и один `EntityCardRoot.qml`; context содержит `entityCardVm` и `islandPalette`, а разрешённые bridge/proxy-объекты выставляются тем же способом, что R6.

Один root выбран вместо файлов по типам: различия сущностей уже являются данными `_FIELD_SPECS`/`_RELATED_CONFIG`, а отдельные roots вернули бы расходящиеся формы. Нативная рамка, Esc и системные диалоги остаются на фасаде.

### D2. Python-модель формы — единственный источник состава

Python VM адаптирует `_FIELD_SPECS` в модель строк с ролями `name`, `label`, `kind`, `value`, `mentionHost`, `aiProxy` и предоставляет общие свойства `hasImage`, `relatedSections`, `characterSheetAvailable`. QML строит дополнительные mention-поля `Repeater`-ом, image-колонку и related-область показывает по этим свойствам. В QML запрещены проверки `entityType === "character"` и второй список полей.

`_RELATED_CONFIG` также остаётся Python-данными. `set_available_entities`/`add_related_entity` адресуют relation-прокси по `attr`, а `create_related_requested(attr, entity_type)` сохраняется. Альтернатива — повторить матрицу типов в JS — отклонена как вторая реализация конфигурации.

### D3. Общие поля и rating остаются локальными острову

Name использует библиотечное однострочное поле; characteristics/backstory и extra mention-поля — `MentionField`; даты — `ThemeDateField` с checkbox «Бессрочно»; related — библиотечный `RelatedSection`; AI — `ThemeAiButton` через Python proxies R6. Рейтинг — Qt Quick Controls `SpinBox` с range 1…20 и токенами, локально в `EntityCardRoot.qml`: второго потребителя для библиотечного rating-input нет, а `ThemeRatingCard` — поверхность отображения, не ввод.

Локальная стилизация SpinBox читает только `islandPalette`, без literal hex/JS-производных. Это контрол потребителя внутри цельного острова, поэтому не образует разрешённый widgets-хвост.

### D4. Image 280×280 через provider R3 и нативные действия

Image-блок существует только при `hasImage`: фиксированный слот 280×280, `Image.PreserveAspectFit`, `MouseArea` для viewer и card-placeholder «Нет изображения». VM выдаёт provider key/URL, фасад регистрирует original/preview в принятом R3 in-memory provider; picked file доступен до появления durable entity id.

«Выбрать файл» вызывает фасадный `QFileDialog`, чтение/декодирование и warning остаются Python-стороной. После валидного выбора фасад эмитит прежний `image_picked(bytes)`, а `set_stored_image_id(id)` обновляет результат. Клик вызывает нативный `ImageViewerDialog(original, preview).exec()` с fallback original → preview → текст. Clear сбрасывает id и provider keys. Ключи освобождаются в `done()`; байты/QPixmap не передаются property в QML.

### D5. Music URL открывает только Python

VM хранит trimmed music URL и edit/display mode. QML показывает ссылочный текст и кнопку `✎`, но активация эмитит sync-сигнал фасаду; `QDesktopServices.openUrl` вызывается Python-стороной после построения `QUrl`. Это сохраняет link/edit UX 1:1 и не доверяет QML внешнюю навигацию.

### D6. Прокси R6 сохраняют wiring 1:1

`get_mention_edits()` возвращает host/proxy объектов `MentionField` для characteristics, backstory и всех extra mention-полей в том же порядке; `get_ai_buttons()` и `get_entity_button()` возвращают AI proxies с API прежних classes. `show_mention_results`, current storage, `mention_clicked`, `generate_requested`, `aiState`, `set_save_locked` и `set_close_guard` повторяют EventDialog R6, чтобы `_wire_mentions`/`_wire_ai_buttons` не ветвились по экрану.

Related picker остаётся нативным multi-select dialog. Пустые кандидаты — no-op, create/open/remove и current ids сохраняют текущую семантику.

### D7. Save — request/finish без valid-гейта

QML Save вызывает VM/facade, который собирает `get_data()` 1:1 и эмитит `saveRequested`/совместимый `saved(dict)` ровно один раз. Карточка переходит в `_saving`, блокирует повторный Save и не принимает `QDialog` заранее. `finish_saving(True)` принимает диалог; `finish_saving(False)` оставляет его открытым, сохраняет форму и разблокирует повтор.

Проверок имени, текста или дат перед emit не добавляется: это фиксированное отличие от valid-логики EventDialog. `set_save_locked` от AI и `_saving` объединяются для enabled Save. Escape/X/Cancel во время `_saving` глушатся; во время генерации идут через R6 close guard; вне этих состояний сохраняют прежнее поведение.

### D8. Public API и result shape фиксируются characterization-тестами

До реализации добавляются красные/characterization-тесты на ctor/entity_type, `populated_entity_id`, `populate`→`get_data`, набор и порядок mention/AI proxies, relation methods, `image_picked`/`set_stored_image_id`, `set_character_sheet_available`, `open_character_sheet_requested` и save lifecycle. Shape результата остаётся: общие keys, extra mention keys по `_FIELD_SPECS`, `image_id` только image-типам и `related_changes[attr].current_ids`.

Новые QML-тесты адресуют root и интерактивные элементы по стабильным `objectName`: общие имена фиксированы, динамические поля/relations получают детерминированный suffix из data key. По каждому типу проверяется точный состав, отсутствие QML character-branch — source invariant.

### D9. Legacy-файлы удаляются только после переключения всех потребителей

После зелёной карточки удаляются класс и файл `mention_text_edit.py` (popup уже вынесен R5 и остаётся), `related_section.py`, `ai_assist_button.py`, `clickable_label.py`, `custom_date_edit.py`. `_CustomCalendar` и однодатовый popup-мост R4 остаются в их новых модулях. Все импорты переводятся на proxies/components до удаления.

Инвариантный тест сканирует production Python/QML на определения/импорты `MentionTextEdit`, legacy `RelatedSection`, `AiAssistButton`/`EntityGenerateButton`, `ClickableLabel`, `CustomDateEdit` и на наличие запрещённого character-ветвления в `EntityCardRoot.qml`; popup-классы и QML `RelatedSection` не считаются нарушением. Альтернатива оставить compatibility aliases отклонена: они сохранят мёртвую вторую реализацию и не закроют эпик R.

### D10. TDD и приёмка

Порядок: characterization/red tests публичного API и result shape → red QML tests состава/действий/save failure → VM/proxies → root → нативные мосты → удаление legacy и grep-гейт. Для каждого типа проверяются base/extra/image/related controls, populate/get_data, mention/AI, dates/no-end, rating, music, image pick/view/clear и character sheet.

Один live-retheme-тест переключает тему при заполненной и прокрученной карточке и проверяет сохранение текста/выбора/scroll. Поэлементные pixel-тесты `MentionField`, `ThemeDateField`, `RelatedSection`, `ThemeAiButton` считаются приёмкой R4–R6 и здесь не дублируются; локальный SpinBox проверяется семантически и source-инвариантом токенов. Bundle-тест фиксирует `EntityCardRoot.qml`. Полный headless pytest остаётся финальным гейтом.

### D11. Принятый mention-долг не расширяется

Storage остаётся `@[Имя](тип:id)`, визуальный редактор не показывает raw markers. Copy-out наружу может терять `type:id`; `LIKE`-поиск и detail могут матчить/показывать raw storage. R7 не вводит sanitize/конвертацию и не меняет LLM prompt. Эти пункты закрепляются regression-тестом только в объёме, необходимом не ухудшить R5/R2.

## Risks / Trade-offs

- [Динамические delegates теряют proxy identity при пересборке] → Python владеет стабильными host/proxy по field key; модель обновляет значения, а не заменяет hosts.
- [In-memory image key переживает диалог или пересекается между карточками] → уникальный namespace/key на экземпляр, сброс в `done()`, тест двух последовательных карточек.
- [Совместимость `saved` с новым async-result lifecycle] → characterization wiring-тест и единая точка `finish_saving`; accept запрещён до success.
- [Удаление спутников ломает скрытого потребителя] → сначала grep всех импортов и перевод потребителей, затем удаление и полный pytest.
- [Большая форма и related-вкладки теряют scroll/focus при retheme] → root не пересоздаётся, модели стабильны; live-retheme тест фиксирует state.
- [Локальная стилизация SpinBox расходится с библиотекой] → только tokens/Basic pattern, без нового общего API; source invariant запрещает literals.

## Migration Plan

Один forward-only UI merge без схемы данных: сначала совместимые VM/proxies и остров за существующим фасадом, затем переключение тестов/потребителей и удаление legacy-файлов. Откат — revert change целиком; storage и БД не мигрируются. После зелёного полного pytest и grep-инварианта R7 закрывает дизайн эпика R.

## Open Questions

_(нет)_
