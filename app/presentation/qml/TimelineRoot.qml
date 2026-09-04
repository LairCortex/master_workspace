// Timeline day-ladder island (change port-event-timeline-qml-island-q2-5a,
// tasks 4.1–4.5; designs D2–D9) — the QML half of the panel facade in
// app/presentation/views/timeline_island.py, whose module docstring pins the
// exact root contract this file implements:
//
//   * context     — ``vm`` (the TimelineViewModel: rows reach the tape ONLY
//                   through ``vm.rowModel``, task 1.1; the island calls the
//                   sync invokables ``stickyInfo``/``zoomStep``/``drill`` and
//                   never an async entry — the «Контракт биндингов» rule),
//                   ``islandPalette`` (the token bridge, D8) and
//                   ``tooltipBridge`` (the shared shim, D9);
//   * facade WRITES — ``windowText`` (chip caption; the facade is its ONE
//                   writer), ``hideEmpty`` (toggle mirror/seed), ``selectedId``
//                   (int, -1 = none — every duplicate of the id washes, D2);
//   * facade EMITS  — ``scrollToIndex(index)``: every reveal/jump landing from
//                   the Python side is a scroll request by row index (D7);
//   * root reports  — the click/drop/edit/jump/toggle channels of the facade
//                   contract; all popups stay native on the Python side (D5).
//
// Behavior is the migrated widgets widget 1:1 («поведение не меняется ни на
// пункт»): the header (title, «Выбор даты» chip, «Скрыть даты без событий»
// toggle, «+», jump ⤒/⤓) sits over the recycling ListView ``eventList``; one
// notch of the wheel == exactly one row (inertia off — «Шаг прокрутки»);
// Alt/Opt+wheel steps the ladder anchored at the row under the cursor (the
// core answers through ``vm.zoomStep``, the island only performs the scroll);
// Ctrl/Cmd+wheel stays dead; a sticky pair pushes the top caption out in a
// 120 ms ease-out while Python (``vm.stickyInfo``) decides what it SAYS (D3);
// the card drop gesture arms past 4 px, ghosts the target day and hands the
// release menu to the facade; a click on an empty day opens the ONE reused
// inline TextField («Инлайн-создание»); the six scale tooltips declare their
// texts through the library shim (4.5).
//
// Colors come from ``islandPalette`` only; off-skin the guarded lookups land
// on the pinned named Qt globals (library fallback set) — no hex, no OS
// palette, no JS color math, no async (test_no_chrome_hex / «Контракт
// биндингов» invariants). Ladder geometry constants mirror the migrated
// widget's module knobs (ROW_HEIGHT/STICKY_HEIGHT/DRAG_START_THRESHOLD_PX/
// STICKY_PUSH_MS).
import QtQuick
import QtQuick.Layouts
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "timelineRoot"

    implicitWidth: 320
    implicitHeight: 480

    // ── chrome surface the facade writes (the root contract) ────────────────
    // The chip caption seeds at «Все дни ▾» (the old header button's own
    // default); every real move lands through the facade's ``windowText``.
    property string windowText: "Все дни ▾"
    property bool hideEmpty: false
    property int selectedId: -1

    // ── island-owned transient state (D2/D4: never reaches the VM) ──────────
    property int editingDayIndex: -1            // the inline field's row
    readonly property var editingDay:
        editingDayIndex >= 0 ? eventList.model.get(editingDayIndex).day : null
    property int dragSourceIndex: -1            // the drop gesture record —
    property int dragEventId: -1                // the migrated _DragGesture,
    property real dragStartSceneY: 0            // expressed as root properties
    property bool dragActive: false
    property int dragTargetIndex: -1            // -1: gap/off-tape → no ghost
    property string dragSourceDayKey: ""        // delivered-day identity for
                                                // the «drop on own day» rule

    // Migrated ladder geometry knobs (timeline_widget module constants).
    readonly property int rowHeight: 24         // ROW_HEIGHT — the density knob
    readonly property int stickyHeight: 26      // STICKY_HEIGHT == the band
    readonly property int dragThresholdPx: 4    // DRAG_START_THRESHOLD_PX
    readonly property int stickyPushMs: 120     // STICKY_PUSH_MS (D3)
    readonly property int squareSide: 30        // the header's setFixedSize(30, 30)
    // Row-1 chip/toggle/add rhythm — the migrated QHBoxLayout's default gap,
    // tokenized like the library's other scales.
    readonly property real headerSpacing:
        Tokens.px(islandTokens, "space.sm", 8)

    // Sticky pair truth (Python is authoritative through vm.stickyInfo — D3).
    property string stickyCommitted: ""
    property string stickyIncoming: ""
    readonly property bool stickyPushRunning: pushOutAnim.running || pushInAnim.running

    // ── the facade contract (mirrored by its module docstring) ──────────────
    signal scrollToIndex(int index)
    signal addRequested()
    signal addMenuRequested(real x, real y)
    signal datePopupRequested(int gapIndex, real x, real y, real width, real height)
    signal hideEmptyToggled(bool checked)
    signal eventClicked(int eventId)
    signal eventDoubleClicked(int eventId)
    signal inlineCreateCommitted(int dayIndex, string name)
    signal dropMenuRequested(int eventId, int targetIndex, real x, real y)
    signal jumpRequested(int step)

    // ── palette bridge (colors/spacing only ever come from here, D8) ────────
    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor: Tokens.token(islandTokens, "color.bg.surface", "white")
    readonly property color fgColor: Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color accentColor: Tokens.token(islandTokens, "color.accent", "black")

    color: surfaceColor

    // ───────────────────────── root behavior (the migrated list logic) ───────
    function topVisibleIndex() {
        // ListView.indexAt speaks contentItem coordinates: the viewport's own
        // top edge sits at (mid, contentY) in that space.
        return eventList.indexAt(eventList.width / 2, eventList.contentY)
    }

    function syncSticky() {
        // The migrated _sync_sticky: the band follows the GESTURE while the
        // ghost is lit, else the core's section truth at the top edge; a
        // caption change while one shows plays the push-out (never an instant
        // swap), an unfinished push overtaken by a new change snaps back and
        // re-drives (the animation is cosmetic, D3).
        if (eventList.count === 0) {
            stopStickyPush()
            root.stickyCommitted = ""
            return
        }
        let text = ""
        if (root.dragActive && root.dragTargetIndex >= 0) {
            text = vm.stickyInfo(root.dragTargetIndex).currentText
        } else {
            const info = vm.stickyInfo(topVisibleIndex())
            text = info.currentIndex >= 0 ? info.currentText : ""
        }
        if (root.stickyPushRunning) {
            if (text === root.stickyIncoming)
                return  // the running push already heads for this caption
            stopStickyPush()  // scroll moved on: snap back, re-drive below
        }
        if (text === root.stickyCommitted)
            return
        const wasShowing = root.stickyCommitted !== ""
        if (wasShowing && text !== "")
            pushStickyOut(text)
        else
            root.stickyCommitted = text  // commit (or hide "" — both overlays)
    }

    function pushStickyOut(text) {
        root.stickyIncoming = text
        stickyNext.visible = true
        pushOutAnim.from = stickyCurrent.y
        pushOutAnim.to = -root.stickyHeight
        pushInAnim.from = root.stickyHeight
        pushInAnim.to = 0
        pushOutAnim.start()
        pushInAnim.start()
    }

    function stopStickyPush() {
        pushOutAnim.stop()
        pushInAnim.stop()
        stickyNext.visible = false
        stickyNext.y = root.stickyHeight
        stickyCurrent.y = 0
    }

    // ── the date-drop gesture (the migrated _DragGesture machinery, D4/D5) ──
    function beginCardPress(rowIdx, evtId, sceneY) {
        // Press arms the record at the DAY rung (only event cards carry the
        // MouseArea, and they only exist there — «Жестов нет на крупных
        // уровнях» holds by construction). Below the threshold the base
        // machinery still turns press+release into the ordinary click.
        root.dragSourceIndex = rowIdx
        root.dragEventId = evtId
        root.dragStartSceneY = sceneY
        root.dragActive = false
        root.dragTargetIndex = -1
        root.dragSourceDayKey = String(eventList.model.get(rowIdx).day)
    }

    function cardDragMoved(sceneX, sceneY) {
        if (root.dragEventId < 0)
            return
        if (!root.dragActive) {
            if (Math.abs(sceneY - root.dragStartSceneY) < root.dragThresholdPx)
                return
            root.dragActive = true  // vertical threshold crossed: the drop lives
        }
        updateDropTarget(sceneX, sceneY)
    }

    function updateDropTarget(sceneX, sceneY) {
        // A materialized day — day header, event card or empty-day row —
        // owns the target; past the row block there is NO extrapolation
        // (gaps/off-tape clear the ghost, the release lands on cancel).
        // The gesture reports ROOT-scene positions; ListView.indexAt speaks
        // contentItem coordinates, so the content layer does the mapping.
        const content =
            eventList.contentItem.mapFromItem(null, Qt.point(sceneX, sceneY))
        const idx = eventList.indexAt(content.x, content.y)
        let ok = false
        if (idx >= 0) {
            const k = eventList.model.get(idx).kind
            ok = k === "dayHeader" || k === "event" || k === "emptyDay"
        }
        root.dragTargetIndex = ok ? idx : -1
        syncSticky()  // the band rides the target date (spec 5.1)
    }

    function cardDragReleased(sceneX, sceneY) {
        // The release branch of an active gesture: gap / off-tape / the
        // event's own day stay silent cancels; another materialized day hands
        // the release menu to the facade at the cursor (the native QMenu
        // commits through ``event_dates_moved``, Esc/past-items cancel).
        updateDropTarget(sceneX, sceneY)
        const target = root.dragTargetIndex
        const sourceDay = root.dragSourceDayKey
        const evt = root.dragEventId
        const targetDay = target >= 0
            ? String(eventList.model.get(target).day)
            : ""
        cancelDrag()  // ghost and dim wash out on any release
        if (target < 0 || targetDay === sourceDay)
            return
        root.dropMenuRequested(evt, target, sceneX, sceneY)
    }

    function cancelDrag() {
        // Esc, an external re-model or a finished gesture: no menu, no
        // signal, no record (spec «Отмена по Esc»).
        root.dragSourceIndex = -1
        root.dragEventId = -1
        root.dragTargetIndex = -1
        root.dragActive = false
        syncSticky()
    }

    // ── the inline create editor (the migrated one-reused QLineEdit, 4.4) ───
    function showEditor(rowIdx) {
        // Re-clicking another empty day just moves the one field (a delegate
        // editor is rejected — there is never a second one).
        if (!eventList.itemAtIndex(rowIdx))
            return
        inlineEditor.text = ""
        root.editingDayIndex = rowIdx
        inlineEditor.forceActiveFocus()
    }

    function hideEditor() {
        // Return the row to its «нет события» placeholder: no text committed,
        // no signal — idempotent (safe from every re-model path).
        if (root.editingDayIndex < 0 && inlineEditor.text === "")
            return
        inlineEditor.text = ""
        root.editingDayIndex = -1
    }

    // ── the wheel (D4: «нормальное колесо = шаг строки», Alt anchored,
    //    Ctrl dead — the migrated wheelEvent branch-for-branch) ───────────────
    function handleWheel(wheel) {
        // WheelEvent carries its position in plain x/y, relative to the
        // Item the handler lives on (the tape area) — rebased onto the
        // list for indexAt (the wheel belongs to the tape).
        const dy = wheel.angleDelta.y
        const anchorX = wheel.x - eventList.x
        const anchorY = wheel.y - eventList.y
        if (wheel.modifiers & Qt.AltModifier) {
            if (dy !== 0) {
                // One ladder step anchored at the row under the cursor; the
                // core's verdict (rung, window, landing index — the migrated
                // «якорь на месте») is vm.zoomStep; the island only re-pins
                // that index to the tape top.
                const landing = vm.zoomStep(
                    wheelAnchorIndex(anchorX, anchorY), dy > 0 ? 1 : -1)
                if (landing >= 0) {
                    Qt.callLater(function () {
                        eventList.positionViewAtIndex(landing, ListView.Beginning)
                    })
                }
            }
            wheel.accepted = true  // the wheel belongs to the ladder while Alt rides
            return
        }
        if (wheel.modifiers & (Qt.ControlModifier | Qt.MetaModifier)) {
            wheel.accepted = true  // deleted interaction — no reaction on any layer
            return
        }
        if (dy !== 0) {
            // One notch == exactly one row, in either direction (the macOS
            // 3-lines-per-notch multiplication the widget pinned stays out).
            // A direct contentY write bypasses the flick bounds, so the
            // clamps the old scrollbar.getValue pinned stay here. Other
            // modifiers keep the plain one-row step (spec «иные
            // модификаторы шаг прокрутки менять НЕ SHALL»).
            const step = dy < 0 ? root.rowHeight : -root.rowHeight
            const bottom = Math.max(0, eventList.contentHeight - eventList.height)
            eventList.contentY = Math.min(Math.max(0, eventList.contentY + step), bottom)
        }
        wheel.accepted = true
    }

    function wheelAnchorIndex(anchorX, anchorY) {
        // The migrated anchor fallback: a gap row (or a cursor past the rows)
        // falls back onto the first-visible row — the spec's «верхняя позиция».
        // Coordinates are list-local; indexAt wants contentItem ones.
        if (eventList.count === 0)
            return -1
        let idx = eventList.indexAt(anchorX, anchorY + eventList.contentY)
        if (idx < 0)
            idx = topVisibleIndex()
        if (idx >= 0 && eventList.model.get(idx).kind === "gap") {
            const top = topVisibleIndex()
            if (top >= 0 && top !== idx)
                idx = top
        }
        return idx
    }

    function requestDatePopup(gapIndex) {
        // Chip clicks report -1; a collapsed-gap click reports its own row
        // index but still positions the popover under the CHIP rect (the
        // facade maps the scene coordinates to global, task 3.2).
        const topLeft = windowChip.mapToItem(null, Qt.point(0, 0))
        root.datePopupRequested(gapIndex, topLeft.x, topLeft.y,
                                windowChip.width, windowChip.height)
    }

    function revealIndex(index) {
        // Just enough to show the row (the migrated PositionAtCenter).
        eventList.positionViewAtIndex(index, ListView.Center)
    }

    onScrollToIndex: (index) => {
        if (index >= 0) {
            Qt.callLater(function () { root.revealIndex(index) })
        }
    }

    // ───────────────────────────── visual tree ───────────────────────────────
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 4        // the migrated chrome layout margins
        spacing: 4                // …and spacing

        // Header row 1 — title, «Выбор даты» + hide toggle, «+» (D6).
        //
        // ANCHOR geometry, not a nested RowLayout: this Qt 6.10 build treats
        // an item's effective layout minimum as its implicitWidth even against
        // an explicit Layout.minimumWidth: 0 (reproduced with stock Controls
        // in a bare QQuickWidget), so row children never squeeze below their
        // hints and the fixed 30 px squares slid off the clipped QQuickWidget
        // at narrow panels. Anchors reproduce the old QHBoxLayout's contract
        // deterministically: the chip/toggle/add group rides the right edge,
        // the title hugs the left, the stretch (and the elision) is swallowed
        // by the title first, then by the toggle and the chip.
        Item {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            implicitHeight: 32
            Layout.preferredHeight: implicitHeight

            TitleText {
                objectName: "timelineTitle"
                text: "Таймлайн событий"
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                // Stretches into the free space, shrinks (elides) first.
                width: Math.max(0, Math.min(implicitWidth,
                                            hideToggle.x - headerSpacing))
            }

            ThemeButton {
                id: addButton
                objectName: "addButton"
                text: "+"
                width: root.squareSide        // the migrated setFixedSize(30, 30)
                height: root.squareSide
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                Nri.tooltip: "Добавить событие (правый клик — другие сущности)"
                onClicked: root.addRequested()
                // Right click opens the native «+» menu through the facade
                // (system-popups rule, D5); the left click keeps its channel.
                TapHandler {
                    acceptedButtons: Qt.RightButton
                    onTapped: {
                        const p = point.scenePosition
                        root.addMenuRequested(p.x, p.y)
                    }
                }
                HoverHandler {
                    onHoveredChanged: {
                        if (typeof tooltipBridge === "undefined" || tooltipBridge === null)
                            return
                        tooltipBridge.tooltipRequested(
                            hovered ? (addButton).Nri.tooltip : "", point.scenePosition)
                    }
                }
            }

            ThemeButton {
                id: windowChip
                objectName: "windowChip"
                text: root.windowText
                readonly property real minSideFloor: 46
                // Implicit width; the floor keeps it tappable when the row
                // squeezes, the contentItem eliding at that point.
                width: Math.max(minSideFloor,
                                Math.min(implicitWidth,
                                         parent.width - addButton.width
                                         - headerSpacing * 2
                                         - hideToggle.minSideFloor))
                anchors.right: addButton.left
                anchors.rightMargin: headerSpacing
                anchors.verticalCenter: parent.verticalCenter
                Nri.tooltip: "Выбор даты"
                onClicked: root.requestDatePopup(-1)
                HoverHandler {
                    onHoveredChanged: {
                        if (typeof tooltipBridge === "undefined" || tooltipBridge === null)
                            return
                        tooltipBridge.tooltipRequested(
                            hovered ? (windowChip).Nri.tooltip : "", point.scenePosition)
                    }
                }
            }

            ThemeCheckBox {
                id: hideToggle
                objectName: "hideEmptyToggle"
                text: "Скрыть даты без событий"
                readonly property real minSideFloor: 24
                // Takes what the title left on its left (the chip group rode
                // the right); floors at the bare indicator + a glyph margin.
                width: Math.max(minSideFloor,
                                Math.min(implicitWidth,
                                         windowChip.x - headerSpacing))
                anchors.right: windowChip.left
                anchors.rightMargin: headerSpacing
                anchors.verticalCenter: parent.verticalCenter
                Nri.tooltip: "Скрыть пустые дни, схлопнутые провалы и пустые периоды"
                // The facade seeds/echoes ``root.hideEmpty``; a user flip
                // emits and re-arms so the binding never fights a round trip.
                property bool externalChecked: root.hideEmpty
                checked: externalChecked
                onToggled: {
                    externalChecked = checked
                    root.hideEmptyToggled(checked)
                }
                onExternalCheckedChanged: checked = externalChecked
                HoverHandler {
                    onHoveredChanged: {
                        if (typeof tooltipBridge === "undefined" || tooltipBridge === null)
                            return
                        tooltipBridge.tooltipRequested(
                            hovered ? (hideToggle).Nri.tooltip : "", point.scenePosition)
                    }
                }
            }
        }

        // Header row 2 — jump navigation (the buttons ride the same jump
        // commands as the facade's Alt+Up/Down shortcuts, «jump не выбирает»).
        // Anchored for the same reason as row 1.
        Item {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            implicitHeight: root.squareSide
            Layout.preferredHeight: implicitHeight

            ThemeButton {
                id: jumpNextButton
                objectName: "jumpNext"
                text: "⤓"
                width: root.squareSide
                height: root.squareSide
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                Nri.tooltip: "К следующему событию (Alt+Down)"
                onClicked: root.jumpRequested(1)
                HoverHandler {
                    onHoveredChanged: {
                        if (typeof tooltipBridge === "undefined" || tooltipBridge === null)
                            return
                        tooltipBridge.tooltipRequested(
                            hovered ? (jumpNextButton).Nri.tooltip : "", point.scenePosition)
                    }
                }
            }
            ThemeButton {
                id: jumpPrevButton
                objectName: "jumpPrev"
                text: "⤒"
                width: root.squareSide
                height: root.squareSide
                anchors.right: jumpNextButton.left
                anchors.rightMargin: headerSpacing
                anchors.verticalCenter: parent.verticalCenter
                Nri.tooltip: "К предыдущему событию (Alt+Up)"
                onClicked: root.jumpRequested(-1)
                HoverHandler {
                    onHoveredChanged: {
                        if (typeof tooltipBridge === "undefined" || tooltipBridge === null)
                            return
                        tooltipBridge.tooltipRequested(
                            hovered ? (jumpPrevButton).Nri.tooltip : "", point.scenePosition)
                    }
                }
            }
        }

        // The tape area: ListView + the overlays that float above it (the
        // sticky pair, the empty hint, the one reused inline editor).
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            // The migrated ``resizeEvent``/construction overlay sync: the
            // sticky pair rides the geometry too (a taller/wider viewport
            // changes which rows are under the band; a fresh island has not
            // seen a scroll yet, so its first sync also starts here).
            Component.onCompleted: root.syncSticky()
            onHeightChanged: root.syncSticky()
            onWidthChanged: root.syncSticky()

            ListView {
                id: eventList
                objectName: "eventList"
                anchors.left: parent.left
                anchors.right: parent.right
                // The sticky band is a CONSTANT top margin (the migrated
                // setViewportMargins(0, STICKY_HEIGHT, …)): the overlays
                // float over it and may animate freely — the tape's own
                // geometry NEVER rides the push-out animation (D7).
                anchors.top: parent.top
                anchors.topMargin: root.stickyHeight
                anchors.bottom: parent.bottom
                model: vm.rowModel
                clip: true
                // Recycling delivery (4.0): delegate reuse is the view's, the
                // cache buffer keeps a few rows beyond the viewport ready.
                cacheBuffer: root.rowHeight * 4
                boundsBehavior: Flickable.StopAtBounds
                maximumFlickVelocity: 0   // inertia off — the notch/row step
                focus: true               // the gesture's Esc receiver
                Keys.onEscapePressed: root.cancelDrag()

                delegate: TimelineRowDelegate {
                    width: eventList.width
                    height: root.rowHeight        // the equal-height contract
                    gestureActive: root.dragActive
                    selectedRow: root.selectedId >= 0
                        && kind === "event" && eventId === root.selectedId
                    dimmed: root.dragActive && root.dragSourceIndex === index
                    ghosted: root.dragActive && root.dragTargetIndex === index
                    onCardPressed: (sceneY) => root.beginCardPress(index, eventId, sceneY)
                    onCardMoved: (sceneX, sceneY) => root.cardDragMoved(sceneX, sceneY)
                    onCardReleased: (sceneX, sceneY) => root.cardDragReleased(sceneX, sceneY)
                    onCardClicked: root.eventClicked(eventId)
                    onCardDoubleClicked: root.eventDoubleClicked(eventId)
                    onEmptyClicked: root.showEditor(index)
                    onGapClicked: root.requestDatePopup(index)
                    onPeriodClicked: {
                        // Descent through the VM invokable (window-then-rung);
                        // the events_changed it emits re-mirrors the chip
                        // caption from the facade — root never writes it.
                        vm.drill(index)
                    }
                }

                // An external re-model cancels the in-flight gesture and the
                // transient field (the migrated ``_rebuild``), restores the
                // READING POSITION the old ``update_events`` kept (the
                // selection's first card, ``PositionAtCenter``; a selection
                // the re-model no longer pictures — or none at all — rewinds
                // to the tape head) and re-reads the sticky section with
                // NO push (animation belongs to scrolls, task 3.2).
                Connections {
                    target: eventList.model
                    function onModelReset() {
                        root.dragSourceIndex = -1
                        root.dragEventId = -1
                        root.dragTargetIndex = -1
                        root.dragActive = false
                        root.hideEditor()
                        const landing = root.selectedId >= 0
                            ? vm.scrollToEvent(root.selectedId) : -1
                        if (landing >= 0) {
                            Qt.callLater(function () {
                                root.revealIndex(landing)
                            })
                        } else {
                            eventList.contentY = 0
                        }
                        root.stickyCommitted = ""
                        root.stickyIncoming = ""
                        root.syncSticky()
                    }
                }
            }

            // Wheel handling lives in a pass-through MouseArea laid OVER the
            // list (D4, the «сдвоенные пути прокрутки» risk): a consumed
            // wheel never reaches the Flickable underneath (handlers do NOT
            // shadow the item's own delivery), so every wheel event over the
            // tape turns into exactly one decision — one row, an anchored
            // ladder step, or the dead Ctrl gesture. NoButton-accepted keeps
            // presses/hover flowing to the delegates below untouched.
            MouseArea {
                objectName: "timelineWheelArea"
                anchors.fill: parent
                acceptedButtons: Qt.NoButton
                onWheel: (wheel) => root.handleWheel(wheel)
            }

            // Inline create field (4.4): ONE reused overlay standing over the
            // clicked empty-day row; Enter commits through the facade, Esc
            // discards the draft, a focus loss WITHOUT text returns the
            // placeholder (a draft stays on screen, spec «потеря фокуса»).
            ThemeField {
                id: inlineEditor
                objectName: "timelineInlineEditor"
                x: 0
                width: parent.width
                height: root.rowHeight
                readonly property var editedItem:
                    root.editingDayIndex >= 0
                        ? eventList.itemAtIndex(root.editingDayIndex)
                        : null
                y: editedItem ? editedItem.mapToItem(parent, 0, 0).y : 0
                visible: root.editingDayIndex >= 0
                placeholderText: "+  нет события"
                onAccepted: {
                    // The facade guards the empty name (spec «Пустое поле не
                    // создаёт»); the field hides either way.
                    root.inlineCreateCommitted(root.editingDayIndex, text)
                    root.hideEditor()
                }
                Keys.onEscapePressed: root.hideEditor()
                onActiveFocusChanged: {
                    if (!activeFocus && text.trim() === "")
                        root.hideEditor()
                }
            }

            // The two sticky overlays (D3: Python says, QML slides). Mouse
            // transparent by construction — no input handlers exist here.
            Rectangle {
                id: stickyCurrent
                objectName: "stickyCurrent"
                anchors.left: parent.left
                anchors.right: parent.right
                y: 0
                z: 2
                height: root.stickyHeight
                color: root.surfaceColor
                visible: eventList.count > 0 && root.stickyCommitted !== ""
                // The band underline: the migrated accent hairline.
                Rectangle {
                    anchors.bottom: parent.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 1
                    color: root.accentColor
                }
                TitleText {
                    objectName: "stickyCurrentText"
                    anchors.left: parent.left
                    anchors.leftMargin: 8      // the migrated padding-left
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.stickyCommitted
                }
            }
            Rectangle {
                id: stickyNext
                objectName: "stickyNext"
                anchors.left: parent.left
                anchors.right: parent.right
                y: root.stickyHeight           // parked below at rest
                z: 3                           // rides ABOVE the pushed-out band
                height: root.stickyHeight
                color: root.surfaceColor
                visible: false
                Rectangle {
                    anchors.bottom: parent.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 1
                    color: root.accentColor
                }
                TitleText {
                    objectName: "stickyNextText"
                    anchors.left: parent.left
                    anchors.leftMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.stickyIncoming
                }
            }
            NumberAnimation {
                id: pushOutAnim
                target: stickyCurrent
                property: "y"
                duration: root.stickyPushMs
                easing.type: Easing.OutQuad     // «120 ms ease-out» (D3)
            }
            NumberAnimation {
                id: pushInAnim
                target: stickyNext
                property: "y"
                duration: root.stickyPushMs
                easing.type: Easing.OutQuad
                onFinished: {
                    // The next caption becomes the committed one (natural
                    // finish; an interrupted push is committed by the pair's
                    // owner — syncSticky always re-drives from Python's truth).
                    root.stickyCommitted = root.stickyIncoming
                    root.stickyIncoming = ""
                    stopStickyPush()
                }
            }

            // The empty-state hint (spec «Событий нет вовсе»): text stays,
            // the sticky pair hides — the overlays' visible bindings already
            // hinge on the row count.
            HintText {
                objectName: "emptyHint"
                anchors.centerIn: eventList
                text: "Нет событий в диапазоне"
                visible: eventList.count === 0
            }

            // A scroll dismisses the editor (its row moves out from under the
            // overlay) and re-reads the sticky pair (the migrated
            // _on_scroll_value).
            Connections {
                target: eventList
                function onContentYChanged() {
                    root.hideEditor()
                    root.syncSticky()
                }
            }
        }
    }
}
