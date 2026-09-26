// Timeline flat-list island (change simplify-event-timeline-flat-list,
// tasks 3.2, design D2–D5) — the QML half of the panel facade in
// app/presentation/views/timeline_island.py, whose module docstring pins the
// exact root contract this file implements:
//
//   * context     — ``vm`` (the TimelineViewModel: rows reach the list ONLY
//                   through ``vm.rowModel``; the island calls the sync
//                   invokable ``scrollToEvent`` and never an async entry —
//                   the «Контракт биндингов» rule), ``islandPalette`` (the
//                   token bridge) and ``tooltipBridge`` (the shared shim);
//   * facade WRITES — ``windowText`` (chip caption; the facade is its ONE
//                   writer) and ``selectedId`` (int, -1 = none — the row of
//                   that id washes);
//   * facade EMITS  — ``scrollToIndex(index)``: every reveal from the Python
//                   side is a scroll request by row index;
//   * root reports  — the click / miss / chip / «+» channels of the facade
//                   contract; all popups stay native on the Python side.
//
// The ladder machinery it replaces is gone, not ported: one event is one
// row, so there is no sticky pair, no drop gesture, no inline field, no
// jump buttons, no hide-empty toggle and no wheel step handler — the wheel
// here is the plain ListView scrolling Qt Quick gives this Flickable.
// A click that lands past every row reports ``selectionMissed()``; the
// facade drops the selection through the ViewModel (spec «Клик-промах
// сбрасывает выбор»), so no id-contract signal leaves the island there.
//
// Colors come from ``islandPalette`` only; off-skin the guarded lookups land
// on the pinned named Qt globals (library fallback set) — no hex, no OS
// palette, no JS color math, no async (the test_no_chrome_hex invariants).
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
    property int selectedId: -1

    // Flat-list geometry. Rows are equal-height per kind: one caption line, or
    // the caption plus the bounded description glimpse beneath it (the core
    // delivers at most that much text). The density knobs the list clamps rows
    // to; the recycling window sizes on the taller kind.
    readonly property int rowHeight: 24
    readonly property int detailedRowHeight: 54
    // NRI-0018 task 1.3: the header square lost its private knob («+» wears
    // the library ThemeIconButton gauge now — no island side constants left).
    // Inset of the list inside the content field: the card's own rounding, so a
    // full-width row wash can never square off the field's rounded corner or
    // cross its hairline border (see the field node below).
    readonly property real listInset:
        Tokens.px(islandTokens, "radius.sm", 6)
    // Chip/add rhythm of header row 1 — the library's space scale.
    readonly property real headerSpacing:
        Tokens.px(islandTokens, "space.sm", 8)

    // ── the facade contract (mirrored by its module docstring) ──────────────
    signal scrollToIndex(int index)
    signal addRequested()
    signal addMenuRequested(real x, real y)
    signal datePopupRequested(real x, real y, real width, real height)
    signal eventClicked(int eventId)
    signal eventDoubleClicked(int eventId)
    signal selectionMissed()

    // ── palette bridge (colors/spacing only ever come from here) ────────────
    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor: Tokens.token(islandTokens, "color.bg.surface", "white")
    // The list sits in the same bordered content field every other column puts
    // its body in (CardPanel: bg/border/radius are the card rule's tokens) —
    // the canvas token is what the detail panel's tab pane and the world
    // snapshot list paint, so the rows read as THIS column's content.
    readonly property color canvasColor: Tokens.token(islandTokens, "color.bg.canvas", "white")

    color: surfaceColor

    // ───────────────────────── root behavior (the flat list logic) ──────────
    function rowIndexAt(listX, listY) {
        // ListView.indexAt speaks contentItem coordinates; the viewport's own
        // point (in eventList space) maps by adding contentY. -1 = past every
        // row (the flat list has no gap/period positions to distinguish).
        if (eventList.count === 0)
            return -1
        return eventList.indexAt(listX, listY + eventList.contentY)
    }

    function requestDatePopup() {
        // The chip is the popover's only opener; the facade maps the scene
        // coordinates to global and seeds the applied window (task 3.2).
        const topLeft = windowChip.mapToItem(null, Qt.point(0, 0))
        root.datePopupRequested(topLeft.x, topLeft.y,
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

        // Header — title, «Выбор даты» chip, «+» (design D4: the header keeps
        // exactly these three; the hide-empty toggle and the jump pair left
        // with the features they steered).
        //
        // ANCHOR geometry, not a nested RowLayout: this Qt build treats an
        // item's effective layout minimum as its implicitWidth even against an
        // explicit Layout.minimumWidth: 0, so row children never squeeze below
        // their hints and the library square glyph (ThemeIconButton, NRI-0018)
        // slides off the clipped QQuickWidget at narrow panels. Anchors
        // reproduce the old QHBoxLayout contract deterministically: the
        // chip/add group rides the right edge, the title hugs the left, the
        // stretch (and the elision) is swallowed by the title first, then by
        // the chip.
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
                                            windowChip.x - headerSpacing))
            }

            ThemeIconButton {
                id: addButton
                objectName: "addButton"
                text: "+"
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                Nri.tooltip: "Добавить событие (правый клик — другие сущности)"
                // Accessibility (change nri-0012-qml-accessibility, task 2.1):
                // the button's only glyph is «+», so its name is the usage-site
                // label, mirroring the tooltip's primary action.
                Accessible.name: "Добавить событие"
                onClicked: root.addRequested()
                // Right click opens the native «+» menu through the facade
                // (system-popups rule); the left click keeps its channel.
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
                                         - headerSpacing * 2))
                anchors.right: addButton.left
                anchors.rightMargin: headerSpacing
                anchors.verticalCenter: parent.verticalCenter
                Nri.tooltip: "Выбор даты"
                onClicked: root.requestDatePopup()
                HoverHandler {
                    onHoveredChanged: {
                        if (typeof tooltipBridge === "undefined" || tooltipBridge === null)
                            return
                        tooltipBridge.tooltipRequested(
                            hovered ? (windowChip).Nri.tooltip : "", point.scenePosition)
                    }
                }
            }
        }

        // The list area: the flat ListView plus the emptiness hint, inside the
        // same bordered content field the other columns use. The wheel is NOT
        // intercepted anywhere — the Flickable's own pixel scrolling is the
        // spec's «обычная прокрутка».
        //
        // Geometry of the field's corners: a Rectangle clip is RECTANGULAR, so
        // clipping inside the card cannot respect its radius — the full-width
        // row washes used to paint a square accent block over the rounded
        // corner and the hairline border. Instead the list itself is inset by
        // the card's radius (its own clip respects those bounds), so a wash can
        // never reach the rounded corner or the border; the corner keeps the
        // card's canvas, and the ring between the list and the outline reads
        // as the field's padding.
        CardPanel {
            objectName: "timelineListCard"
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: root.canvasColor
            clip: false

            // One pixel off the hairline border (the detail panel's tab pane
            // does the same); the LIST adds the radius inset on top of this.
            Item {
                objectName: "timelineListArea"
                anchors.fill: parent
                anchors.margins: 1

                ListView {
                    id: eventList
                    objectName: "eventList"
                    anchors.fill: parent
                    anchors.margins: root.listInset     // clear of the corners
                    model: vm.rowModel
                    clip: true
                    // Recycling delivery: delegate reuse is the view's, the cache
                    // buffer keeps a few rows beyond the viewport ready (sized on
                    // the taller row kind, so a scrolled-away row is never gone).
                    cacheBuffer: root.detailedRowHeight * 4
                    boundsBehavior: Flickable.StopAtBounds

                    delegate: TimelineRowDelegate {
                        width: eventList.width
                        // Equal height per kind: the caption line alone, or the
                        // caption plus the description glimpse the core delivered.
                        height: detail && detail.length > 0
                            ? root.detailedRowHeight : root.rowHeight
                        selectedRow: root.selectedId >= 0 && eventId === root.selectedId
                        onRowClicked: root.eventClicked(eventId)
                        onRowDoubleClicked: root.eventDoubleClicked(eventId)
                    }

                    // An external re-model restores the READING POSITION the old
                    // ``update_events`` kept (the selection's row, PositionAtCenter;
                    // a selection the re-model no longer pictures — or none at all
                    // — rewinds to the list head, after which the facade re-lands
                    // any explicit selection through ``scrollToIndex``).
                    Connections {
                        target: eventList.model
                        function onModelReset() {
                            if (typeof tooltipBridge !== "undefined" && tooltipBridge !== null)
                                tooltipBridge.tooltipRequested("", Qt.point(0, 0))
                            const landing = root.selectedId >= 0
                                ? vm.scrollToEvent(root.selectedId) : -1
                            if (landing >= 0) {
                                Qt.callLater(function () {
                                    root.revealIndex(landing)
                                })
                            } else {
                                eventList.contentY = 0
                            }
                        }
                    }
                }

                // The miss-click catcher laid OVER the list (spec «Клик-промах
                // сбрасывает выбор»): it only accepts presses that land PAST every
                // row and propagates the rest, so rows keep their whole gesture to
                // the delegates below («клики — только по строкам»).
                MouseArea {
                    objectName: "timelineMissLayer"
                    anchors.fill: parent
                    propagateComposedEvents: true
                    acceptedButtons: Qt.LeftButton
                    property bool pressWasMiss: false
                    onPressed: (mouse) => {
                        const p = mapToItem(eventList, mouse.x, mouse.y)
                        pressWasMiss = root.rowIndexAt(p.x, p.y) < 0
                        if (!pressWasMiss)
                            mouse.accepted = false  // a row: the delegate owns the gesture
                    }
                    onClicked: (mouse) => {
                        if (!pressWasMiss) {
                            mouse.accepted = false
                            return
                        }
                        pressWasMiss = false
                        const p = mapToItem(eventList, mouse.x, mouse.y)
                        if (root.rowIndexAt(p.x, p.y) < 0)
                            root.selectionMissed()
                    }
                }

                // The window text is the ONLY filter, so emptiness has one face
                // (spec «Событий ещё нет»): no events at all and an event-free
                // window both land on this single muted hint.
                HintText {
                    objectName: "emptyHint"
                    anchors.centerIn: parent
                    text: "Событий ещё нет"
                    visible: eventList.count === 0
                }
            }
        }
    }
}
