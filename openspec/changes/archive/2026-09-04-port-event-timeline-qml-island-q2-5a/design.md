# Design: port-event-timeline-qml-island-q2-5a

## Context

Действующий контракт — спек `event-timeline` (редизайн «лестница суток»: лента дней со sticky-заголовками, дубли многодневок, схлопнутые провалы >14 дней, бессрочные до дна ленты, «Выбор даты», скрытие пустых, Alt/⌥+колесо с якорем, drill-клики, drop-меню «Перенести/Расширить вниз/Начать раньше», инлайн-создание, jump-кнопки, tooltip карточки). Инфраструктура Q1/Q2a1: один `QQmlEngine`, `QQuickWidget`-острова, `islandPalette` в контексте, `nri.components`, `walk_items`-тесты, софт-бэкенд, бандл-tест. Ключи переносимого экрана (проверено): `TimelineListView(QListWidget)` + `_RowDelegate` ≈2042 строк с ручными жестами; Qt-нулевое ядро `timeline_rows.py` (`build_rows`, `drop_actions`/`apply_drop_action`, `zoom_anchor_level`, `sticky_state`, `window_chip_text`, `content_bottom`, clamp'ы календаря); `TimelineViewModel` — единственный хозяин `level/window/hide_empty/events/selection` с memo-пересборкой; wiring (`app/application/wiring.py`) работает с публичным API панели через `_spawn` под сессионным локом; drag-коммит и инлайн-создание уже честные (пути с rollback + ровно одним `QMessageBox`). tooltip-шим в кодовой базе отсутствует — шкала первый потребитель.

## Goals / Non-Goals

**Goals:**
- 1:1 перенос наблюдаемого поведения `event-timeline` в QML-остров в слоте `QSplitter`; widgets-реализация удалена целиком.
- Публичный API панели (методы+сигналы) сохранён — проводка меняется почтилитерально (diff только по импортам/атрибуту конструирования).
- Единственность расчётов: `timeline_rows.py` остаётся qt-нулевым ядром; JS-вторых реализаций правил нет; копий событий на острове нет.
- Инфраструктурные приобретения остаются в общем каркасе: списочная модель-питание QML, tooltip-шим, widgets-поповер-мост как документированное исключение.

**Non-Goals:**
- Диалоги `event_dialog`/`entity_card_dialog`, `MentionTextEdit` — не трогаются (заблокированное решение grill 2026-09-03).
- Изменения поведения шкалы (новая механика, «сегодня», undo, сохранение вида между сессиями).
- Шелл (`QMainWindow`/`QMenuBar`/`statusBar`/`QSplitter`) и соседние панели; `table_host`.
- Переезд поповера календарей в QML.

## Decisions

### D1. Python-фасад сохраняет имя и публичный API панели

Новый класс-остров `TimelineWidget` в `app/presentation/views/timeline_island.py` держит те же методы (`update_events`, `set_selected`, `scroll_to_event`, `jump_prev_event/jump_next_event`, `cover_window_for_span`) и те же сигналы (`event_selected`, `event_double_clicked`, `add_event_requested`, `add_entity_requested`, `event_types_requested`, `window_changed`, `event_dates_moved`, `event_create_requested`, …); атрибут `window.timeline_widget` и весь `wiring.connect` остаются текстово-неизменными. Внутри: `QQuickWidget` по образцу лаунчера (SizeRootToView, `assert Ready`, teardown `setSource(QUrl())` через `singleShot(0)`), контекст острова — VM и `islandPalette` (дети фасада, raw pointers). Контракт «синхронные входы/сигналы VM, async в wiring» соблюдается: QML не дергает сервисы. Альтернатива «новое имя + перетирание wiring» отклонена: diff проводки был бы шумом поверх переноса и удвоил бы риск.

### D2. Списочная модель строк поверх qt-нулевого ядра

`TimelineRowModel(QAbstractListModel)` на `build_rows` VM: роли `kind/event_id/day/caption/token_key/count/flags`. Пересборка ленты = reset модели (ядро и так строит ряды целиком; memo версий виджета умирает); выбор/наведение/призраки drag'а — свойства корня острова (делегат биндится на `selectedId == model.event_id`), model-emit'ов на них нет. Память: `__slots__`-структуры/кортежи вместо QObject-строк. Патологически длинные многодневки — тот же принятый trade-off, что в redesign (лечится следующим шагом, не здесь).

### D3. Sticky: Python-расчёт, QML-анимация

ListView владеет `contentY`; при скролле QML берёт верхний видимый индекс строки-заголовка и вызывает sync-инвайкейбл `timeline_rows.sticky_state(rows, first_visible_y)` (через обёртку на VM с готовым индексом), получая пару подписей `current/next`. Push-out 120 ms ease-out — чистая косметика QML, прерывается новым скроллом; authoritative — подписи из Python. Альтернативы (JS-реализация sticky_state) запрещены решением о «третьем компиляторе».

### D4. Жесты и колеса — тонкие Qt-обёртки поверх чистой геометрии

- Нормальное колесо — попиксельный скролл ListView с шагом строки (сохраняя нотч-за-строку виджета).
- Alt/⌥+колесо: индекс строки под курсором (ListView `indexAt`) → `zoom_anchor_level`/`zoom_level` → запись `vm.level/window` (facade-slot) → reset модели с якорем по заякоренной позиции. Ctrl мёртв (как сейчас).
- Drill: клик `PERIOD_CARD` → инвайкейбл спуска (level глубже, window = период) — состояние пишет VM.
- Drop-жест: MouseArea карточки; порог `DRAG_THRESHOLD_PX=4` (ядро); цель — материализованный ряд суток (`indexAt`, kind-валидация), провал/за краем — невалидны, ghost гаснет; release на чужой день → façade слот открывает нативную `QMenu` (пункты из `drop_actions`, результат через `apply_drop_action`) в глобальных координатах курсора; выбор → существующий сигнал `event_dates_moved`; Esc/release-мимо — cancel без emit. Sticky во время жеста показывает целевую дату (свойство корня).
- Alt+Up/Down — `QShortcut(WidgetWithChildrenShortcut, island)` на фасаде, «jump никогда не выбирает» 1:1.
- Инлайн-создание: один переиспользуемый `TextField`-оверлей на координатах пустого дня (`editingDay` свойство корня), Enter → `event_create_requested(day, name)`, Esc/пусто → скрыть (зеркало D4 redesign).

### D5. Системные попапы и единственный widgets-поповер-мост

- «+»-меню (5 create-пунктов + «Типы событий…») и drop-меню — нативный `QMenu`, строится Python-стороной фасада по сигналу из QML (правило системных попапов карты; темы/клавиатура бесплатно).
- «Выбор даты»: поповер двух игровых календарей (`_CustomCalendar` остаётся в `custom_date_edit.py`) переезжает из `timeline_widget.py` в `app/presentation/views/timeline_date_popup.py` без изменения механики (два тапа live-apply, откат-повтор по обратному тапу, «Сбросить», предзаполнение провала, низкоэкранный фолбэк). QML-чип emits `datePopupRequested(prefill)`; фасад позиционирует попап от глобального прямоугольника чипа (QML репортом координат) — top-level widget обрезку не знает; результат идёт в VM тем же каналом `window_changed`. Обрезка QML-поповера прямоугольником низкого острова — причина исключения (зафиксирована в спеке как единственное такое исключение).
- Подсказки — tooltip-шим (D9), тексты всех шести текущих точек объявляются в QML.

### D6. Шапка острова — QML

Одна QML-строка шапки над ListView: чип даты (текст из ядра `window_chip_text`, приходит свойством), `ThemeCheckBox` «Скрыть даты без событий», «+»-кнопка (меню — системное), jump ⤒/⤓ (`ThemeButton`). objectName-контракты: `windowChip`, `hideEmptyToggle`, `addButton`, `jumpPrev`, `jumpNext`, лента — `eventList`, делегат-частей — по образцу (`RowItem.textObjectName` приём). Смена тумблера/чипа пишет VM, VM remodel'ит модель — обратных связей через фасад нет.

### D7. Контур данных VM

`TimelineViewModel` дописывается без смены существующих контрактов: `row_model` (property), инвайкейблы `scrollToEvent(event_id)` (посадка по id с сохранением текущего скролла, если выбранное видимо, иначе rewind — семантика текущего `update_events` 1:1, ре-анкер по верхнему дню при смене ручек через якорь-индекс), `stickyInfo(top_index)`, `zoomStep(anchor_index, delta)`, `drill(index)`, `jump(step)` (цель — индекс; скролл выполняет QML по сигналу). События-источник — `vm.events`; `update_events(events)` фасада — мост в существующую path'у VM/re-model (wiring не меняется). Скролл/hover/drag/editing-дни — не лезут в VM (свойства острова), выбор/уровень/окно/скрытие — только VM (как сейчас).

### D8. Оформление и off-skin

Делегаты: цвета из плоских ключей `islandPalette` (точки типов `color.chart.N` через `token_key` строки; wash выделения/hover/gost/dim — производные accent из Python- derivations); оф-скин — только именованные Qt-глобалы; literal-hex/palette() в qml/js запрещены (инвариант `test_no_chrome_hex` уже сканирует qml; live-retheme без потери скролла/выбора — сигнал палитры). Форматирование дат — игровое из Python (подписи строк приходят готовыми в модели; в QML — только рендер).

### D9. Tooltip-шим живёт в библиотеке, показывает Python

В `nri/components` — прикреплённое свойство объявления подсказки (например `Nri.tooltip: "…"`); наведение QML передаёт текст+локальные координаты мосту фасада, фасад вызывает `QToolTip.showText(globalPos, text)` — уже темизованный общий лист (W2a). Работает и в скинутом виде, и вне скина; текст может быть биндингом (динамическая подсказка карточки). Мост-сигнал — общий контракт острова (переиспользуется Q2b-панелями).

### D10. Удаления

`timeline_widget.py` — файл удаляется (виджет, `TimelineListView`, `_RowDelegate`, `_Palette`, memo-хозяйство, `_DateWindowPopup` — в новый файл по D5); `timeline_rows.py` остаётся qt-нулевым ядром без изменений правил (переносится, не переписывается); внутренностные тесты виджета удаляются; e2e/smoke-тесты переезжают на адресацию QML-объектов (walk_items + пиксели — уже рабочие механизмы conftest).

### D11. Тесты (приёмка по требованиям спецификации)

Чек-лист приёмки = Requirement'ы `event-timeline`; каждый покрыт QML-островным тестом через objectName (лестница/drill/колесо, жесты+меню (QMenu mock-ом решения), sticky-анимация — позиции оверлеев/смены, chip-поповер через мок фасада, инлайн-создание key-событиями, тумблер, jump-семика «не выбирает», id-контракты, дубли/провалы). Пиксельная тема (обе темы, live-retheme, токен палитры не трогая выбор/скролл) — зеркало текущего `test_e2e_timeline_theme.py` на QQuickWidget. Чистые юниты ядра и VM не меняются; `.spec`-бандл тест + новые qml-файлы (datas рекурсивно уже покрыто образом Q2a1, список файлов расширяется); coverage-гейт Python-стороны.

## Risks / Trade-offs

- [QQuickWidget+ListView против QListWidget по fps на длинной ленте] — recycling-модель штатно виртуализует; при регрессе — следующий шаг (кандидат: clamp строк из redesign), не откат переезда.
- [Alt-колесо и macOS-жесты] — тот же принятый риск redesign; поведение не меняется.
- [QMenu.exec из-под QML-release блокирует] — показ через façade-слот после возврата из MouseArea-обработчика; precedent: меню Q1-лаунчера.
- [Сдвоенные пути прокрутки (ListView flicker + ручная нотч-шаг)] — нормальный wheel перехватывается и делает ровно шаг строки, инерция ListView отключается — иначе семантика «нотч = строка» уплывёт.
- [Долгий reset модели на гигантской ленте] — принятый trade-off redesign; профильных кампаний не касается; измеряется тестом-смоук на годе-диапазоне.

## Open Questions

_(нет — все ветки закрыты grill 2026-09-03: фасад/API, модель, sticky, попапы, шим, объём переезда, приёмка, порядок.)_
