# Tasks: port-event-timeline-qml-island-q2-5a

## 1. Ядро и модель данных (без QML)

- [x] 1.1 `TimelineRowModel(QAbstractListModel)` поверх `timeline_rows.build_rows`: роли kind/event_id/day/caption/token_key/count/flags, `__slots__`-строки, reset на пересборку; юниты модели (роли, счётчики, пустой набор).
- [x] 1.2 `TimelineViewModel`: `row_model` property + инвайкейблы `scrollToEvent`, `stickyInfo(top_index)` (обёртка `sticky_state` с готовым рядом), `zoomStep(anchor_index, delta)`, `drill(index)`, `jump(step)`; существующие property/сигналы не меняются; юниты (seed AsyncMock/service, как текущие `TestTimelineViewModel`).
- [x] 1.3 Мемо-хозяйство панелей не наследуется: проверка, что после 1.1–1.2 в VM нет второй копии событий для рендера (тест-инвариант единственности).

## 2. Карта: tooltip-шим в библиотеке

- [x] 2.1 `nri/components`: прикреплённое свойство объявления подсказки (+ запись в `qmldir`, `.pragma`-нужды по образцу библиотеки); галерея-тест `test_qml_components.py` + контракт типа, off-skin-проверка.
- [x] 2.2 Общий мост фасада острова: сигнал QML→Python (текст+координаты) → `QToolTip.showText`; smoke-тест на лаунчере или галерее.

## 3. Python-фасад острова

- [x] 3.1 `app/presentation/views/timeline_island.py`: класс `TimelineWidget` (QQuickWidget-остров по образцу лаунчера: SizeRootToView, `assert Ready`, teardown defer), контекст `vm`+`islandPalette`, публичные методы/сигналы — 1:1 текущего виджета; `update_events/set_selected/scroll_to_event/jump_*/cover_window_for_span` разворачиваются в инвайкейблы/свойства.
- [x] 3.2 Поповер «Выбора даты»: `_DateWindowPopup` переезжает в `app/presentation/views/timeline_date_popup.py` без изменения механики (два тапа, реарм, «Сбросить», предзаполнение провала, низкоэкранный фолбэк); вызов по сигналу чипа, позиция от прямоугольника чипа (репорт QML-координат), live-apply в прежний канал `window_changed`; тесты chip-поповера мигрируют с новой точкой входа.
- [x] 3.3 Системные меню: «+» (5 create + «Типы событий…») и drop-меню («Перенести/Расширить вниз/Начать раньше» из `drop_actions`, результат `apply_drop_action` → `event_dates_moved`); Esc/промах = cancel без emit; тесты меню через mock выбора.
- [x] 3.4 Alt+Up/Down — `QShortcut(WidgetWithChildrenShortcut)` на фасаде; «jump никогда не выбирает» 1:1.

## 4. QML-остров

- [x] 4.1 `TimelineRoot.qml`: шапка (`windowChip`/`hideEmptyToggle`/`addButton`/`jumpPrev`/`jumpNext` на компонентах библиотеки) + `ListView` `eventList` recycling по модели (4.0: cacheBuffer/reuse, инерция выключена, нормальное колесо = шаг строки), делегаты лент 1:1 по `event-timeline` (sticky-заголовок, карточка с точкой типа/«бессрочно», пустой день, «+ нет события», схлопнутый провал, заголовок/карточка периода со счётчиком) — цвета только из `islandPalette`, оф-скин — именованные Qt-глобалы; `objectName`-контракты делегатов.
- [x] 4.2 Sticky: два оверлея подписей, push-out 120 ms ease-out с прерыванием, подписи из `stickyInfo(top_index)`, follow при drag'е (целевая дата), скрытие при пустой ленте.
- [x] 4.3 Жесты: Alt/⌥+колесо с якорем (`indexAt` → `zoomStep`), drill-клик `PERIOD_CARD`, drop-жест карточки (порог 4 px, ghost/dim, валидация цели по виду ряда, запуск меню через фасад), Ctrl-мёртв.
- [x] 4.4 Инлайн-создание: переиспользуемый `TextField`-оверлей (`editingDay`), Enter → `event_create_requested(day, name)`, Esc/пусто → скрыть; правый клик/меню «+» не перекрывают жест.
- [x] 4.5 Подсказки: шесть текстов шкалы (карточка — динамический, чип, тумблер, «+», jump×2) объявлены шимом 2.1.

## 5. Вклейка в приложение и удаление старого

- [x] 5.1 Точка конструирования (`app/main.py`/`main_window.py`): остров вместо виджета в том же слоте `QSplitter`; wiring — сверка diff'а (атрибут/импорты; сигнальные имена не менялись).
- [x] 5.2 Удаление `app/presentation/views/timeline_widget.py` и внутренностных тестов (`test_timeline_widget.py` и внутрянники соседей); чистые юниты `timeline_rows`/ladder не тронуты; проверка отсутствия импортов удалённого модуля.

## 6. Приёмка

- [x] 6.1 Тесты по чек-листу Requirement'ов `event-timeline`: каждый пункт покрыт тестом на острове (walk_items/objectName; QMenu mock-ом выбора; chip-поповер — мок фасада); id-контракты и окно/уровень пишутся сквозь реальный VM (образец `test_timeline_scale_widget.py`).
- [x] 6.2 Пиксельная тематическая приёмка: зеркала `test_e2e_timeline_theme.py` (обе темы, live-retheme без потери выбора/скролла, пиксель = производная токена); golden PNG нет.
- [x] 6.3 E2E/smoke (`test_e2e_timeline_*`, `test_timeline_smoke_*`) переведены на адресацию QML; оф-скин-проверка острова.
- [x] 6.4 `.spec`: datas новых qml-файлов + tooltip-шим; `tests/test_spec_qml_bundle.py` расширен; локальная проверка сборки (macOS) по практике Q2a1.
- [x] 6.5 Полный `python -m pytest` (offscreen) зелёный, coverage-гейт без просадки; инвариант `test_no_chrome_hex` проходит (qml/js включены).
- [x] 6.6 `docs/CHANGELOG.md` (переезд шкалы, эпик Q открыт); `docs/design-system-roadmap.md`: Q2.5 → «шкала+долг, реализовано», диалоги/`MentionTextEdit` — заблокированный пункт вне порядка, tooltip-шим зафиксирован в рамках карты.
