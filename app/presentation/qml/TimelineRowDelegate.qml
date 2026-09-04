// Decklegat of one day-ladder position (change port-event-timeline-qml-island-q2-5a,
// task 4.1; design D2/D8). One item instance per row of ``vm.rowModel``; the
// ListView recycles these by the equal-height contract (ROW_HEIGHT from the
// migrated widget — every ladder position renders exactly ``root.rowHeight``).
//
// Roles delivered by TimelineRowModel (timeline_viewmodel, task 1.1): kind /
// eventId / day / caption / tokenKey / count / flags. The captions arrive
// PRE-FORMATTED by Python (D8 «в QML — только рендер»): this file never
// re-derives content, it only picks the delegate's look from ``kind``.
//
// Visual truth is the migrated ``_RowDelegate.paint`` mirrored item for item:
// the selection wash covers every duplicate of the selected record (the root
// property drives it, never model emits — D2), the hover wash sits under an
// event row the cursor rests on (accent derivation), the dragging source card
// dims and the target-day row wears the ghost wash (both accent derivations),
// the type dot is the bare ``color.chart.N`` token square (muted for untyped,
// W4 D7 no outline over the wash), and every caption shares one ladder indent
// with elided overflow. Colors come from ``islandPalette`` ONLY; off-skin the
// guarded lookups land on the pinned named Qt globals (design D7) — no hex,
// no OS palette, no JS color math (the test_no_chrome_hex invariant).
//
// Interactions stay thin Qt wrappers (D4): the event row's MouseArea arms the
// root's gesture bookkeeping (a press below the root's threshold keeps being
// the plain selection click — «Drag строки не есть выбор»), the empty day
// reports its create-entry click, the collapsed gap reports its click only
// within the drag travel budget (the migrated 4 px rule — past it the release
// is a drag, not the pre-filled «Выбор даты» request), the period card reports
// the drill click — never a selection. Headers are inert: no mouse area.
//
// State INPUTS (selectedRow/dimmed/ghosted/gestureActive) and every decision
// (target validation, the 4 px arming, menu/click routing) live on the island
// root — this component only reports presses, moves, releases and taps.
import QtQuick
import nri.components
import "nri/components/tokens.js" as Tokens

Item {
    id: row

    // ── delivered roles (TimelineRowModel roleNames, task 1.1) ──────────────
    required property int index
    required property string kind
    required property var eventId
    required property var day
    required property string caption
    required property var tokenKey
    required property int count
    required property var flags

    // ── island-owned state fed by the root's bindings (D2) ──────────────────
    property bool selectedRow: false      // the washed card of selectedId
    property bool dimmed: false           // dragging source card stays put, dimmed
    property bool ghosted: false          // target-day row under the ghost
    property bool gestureActive: false    // root's drop gesture is live

    // ── interaction channel to the root ─────────────────────────────────────
    signal cardPressed(real sceneY)
    signal cardMoved(real sceneX, real sceneY)
    signal cardReleased(real sceneX, real sceneY)
    signal cardClicked()
    signal cardDoubleClicked()
    signal emptyClicked()
    signal gapClicked()
    signal periodClicked()

    // The delegate contract for the acceptance harness: the row kind names the
    // item («eventRow», «dayHeaderRow», «emptyDayRow», «gapRow» — from the
    // model kind strings — «periodCardRow», «periodHeaderRow»).
    objectName: kind + "Row"

    // Ladder geometry of the migrated widget: dot at TEXT_LEFT_PAD, dot side
    // DOT_SIZE, text at TEXT_INDENT = 8 + 8 + 4, right bleed TEXT_LEFT_PAD.
    readonly property int textLeftPad: 8
    readonly property int dotSize: 8
    readonly property int textIndent: 20

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)

    readonly property color fgColor: Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color mutedColor: Tokens.token(islandTokens, "color.fg.muted", "gray")
    readonly property color accentColor: Tokens.token(islandTokens, "color.accent", "black")
    readonly property color accentFgColor: Tokens.token(islandTokens, "color.accent.fg", "white")
    // Row washes are Python compiler derivations (D8) delivered as a token
    // COLOR plus a scalar alpha pair: QML's color parser cannot read an
    // rgba() string, so the accent derivation reaches the paint as
    // (hex color) × (opacity) — every factor still comes from the bridge.
    // Off-skin they fall back to the same named global the muted captions
    // use (the widget's off-skin stand-in for every wash was the plain Qt
    // gray) at the migrated wash alphas.
    readonly property color rowWashColor: Tokens.token(islandTokens, "color.accent.rowHover", "gray")
    readonly property color ghostWashColor: Tokens.token(islandTokens, "color.accent.ghost", "gray")
    readonly property real rowWashAlpha: Tokens.px(islandTokens, "opacity.accent.rowHover", 0.25)
    readonly property real ghostWashAlpha: Tokens.px(islandTokens, "opacity.accent.ghost", 0.35)

    // The dynamic card tooltip (4.5): declared with the library shim, shown
    // by the island's bridge on hover. «summary» is None on every non-event
    // role, which the shim's empty text maps to "no tooltip".
    Nri.tooltip: (flags && flags.summary) ? String(flags.summary) : ""

    // The dragging source card keeps its place dimmed (GHOST_ALPHA 0.35 of
    // the migrated delegate's painter opacity — an alpha, not a color).
    opacity: row.kind === "event" && row.dimmed ? 0.35 : 1.0

    // Hover wash input: only event rows carried a hover wash in the migrated
    // delegate, and never under the selection wash.
    readonly property bool hoveredEvent:
        kind === "event" && !selectedRow && cardHover.hovered

    // Selection / hover washes, full row width exactly like fillRect(option.rect).
    // The selection is the accent itself (alpha 1); the hover wash is the same
    // accent under the migrated 0.25 wash alpha (see the pair above).
    Rectangle {
        anchors.fill: parent
        visible: row.selectedRow || row.hoveredEvent
        color: row.selectedRow ? row.accentColor : row.rowWashColor
        opacity: row.selectedRow ? 1.0 : row.rowWashAlpha
    }

    // The target-day ghost: one accent wash over the row the cursor points at
    // (cards, day heads and placeholders materialize a day; the root only
    // marks delivered-day rows, so no wash lands over gaps or off-tape).
    Rectangle {
        anchors.fill: parent
        visible: row.ghosted
        color: row.ghostWashColor
        opacity: row.ghostWashAlpha
    }

    // Event card body: the bare type-dot square (keeps its token color over
    // the selection wash, gets no outline — W4 D7).
    Rectangle {
        objectName: "eventTypeDot"
        visible: row.kind === "event"
        x: row.textLeftPad
        width: row.dotSize
        height: row.dotSize
        anchors.verticalCenter: parent.verticalCenter
        // tokenKey is the delivered "color.chart.N" key (None/undefined for
        // the untyped card — token() then answers the muted fallback).
        color: Tokens.token(row.islandTokens,
                            row.tokenKey ? String(row.tokenKey) : "", row.mutedColor)
    }

    // One shared-indent caption for every row kind. muted = placeholders,
    // gaps and the empty-period counter (the widget's muted_text rows); the
    // selected card flips to accent.fg while washed.
    Text {
        id: rowText
        objectName: "rowText"
        x: row.textIndent
        width: Math.max(row.width - row.textIndent - row.textLeftPad, 0)
        anchors.verticalCenter: parent.verticalCenter
        text: row.caption
        elide: Text.ElideRight
        font.pixelSize: Tokens.px(row.islandTokens, "font.size.md", 13)
        readonly property bool mutedKind:
            row.kind === "emptyDay" || row.kind === "gap"
            || (row.kind === "periodCard" && !!(row.flags && row.flags.empty))
        color: row.selectedRow ? row.accentFgColor
             : mutedKind ? row.mutedColor : row.fgColor
    }

    // Hover: the wash under the cursor + the bridge's tooltip report (4.5).
    // Only selectable (event) rows react — headers/gaps/empty days carried no
    // hover wash in the migrated delegate.
    HoverHandler {
        id: cardHover
        enabled: row.kind === "event"
        onHoveredChanged: {
            if (hovered) {
                const tip = (row).Nri.tooltip
                if (typeof tooltipBridge !== "undefined" && tooltipBridge !== null && tip)
                    tooltipBridge.tooltipRequested(tip, point.scenePosition)
            } else if (typeof tooltipBridge !== "undefined" && tooltipBridge !== null) {
                tooltipBridge.tooltipRequested("", Qt.point(0, 0))
            }
        }
    }

    // ── per-kind input areas (a press on a header stays inert, spec «Заголовок дня не кликабелен») ──
    MouseArea {
        anchors.fill: parent
        enabled: !!(row.flags && row.flags.draggable)
        acceptedButtons: Qt.LeftButton
        property real pressSceneY: 0
        property bool gestureConsumed: false
        onPressed: (mouse) => {
            gestureConsumed = false  // a recycled delegate never owes the old gesture
            const p = row.mapToItem(null, Qt.point(mouse.x, mouse.y))
            pressSceneY = p.y
            row.cardPressed(p.y)
        }
        onPositionChanged: (mouse) => {
            if (!pressed) return
            const p = row.mapToItem(null, Qt.point(mouse.x, mouse.y))
            row.cardMoved(p.x, p.y)
        }
        onReleased: (mouse) => {
            const p = row.mapToItem(null, Qt.point(mouse.x, mouse.y))
            if (row.gestureActive) {
                // The gesture consumed this press: the click must not leak
                // (a drag is never a selection — «Drag строки не есть выбор»).
                gestureConsumed = true
                row.cardReleased(p.x, p.y)
            }
        }
        onClicked: {
            if (gestureConsumed) {
                gestureConsumed = false
                return
            }
            row.cardClicked()
        }
        onDoubleClicked: row.cardDoubleClicked()
    }

    MouseArea {
        anchors.fill: parent
        enabled: !!(row.flags && row.flags.creatable)
        acceptedButtons: Qt.LeftButton
        onClicked: row.emptyClicked()
    }

    MouseArea {
        anchors.fill: parent
        enabled: !!(row.flags && row.flags.windowable)
        acceptedButtons: Qt.LeftButton
        // The migrated 4 px travel budget: past it the release is a drag, not
        // the pre-filled «Выбор даты» request (task 7.1 of the redesign).
        property real pressSceneY: 0
        onPressed: (mouse) => {
            pressSceneY = row.mapToItem(null, Qt.point(mouse.x, mouse.y)).y
        }
        onReleased: (mouse) => {
            const p = row.mapToItem(null, Qt.point(mouse.x, mouse.y))
            if (Math.abs(p.y - pressSceneY) < 4)
                row.gapClicked()
        }
    }

    MouseArea {
        anchors.fill: parent
        enabled: !!(row.flags && row.flags.drillable)
        acceptedButtons: Qt.LeftButton
        onClicked: row.periodClicked()
    }
}
