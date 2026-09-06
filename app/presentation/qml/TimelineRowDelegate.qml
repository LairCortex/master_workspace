// Delegate of one flat-list row (change simplify-event-timeline-flat-list,
// task 3.2; design D2/D5). One item per row of ``vm.rowModel``; the ListView
// recycles these by the equal-height-per-kind contract — a row without a
// description is the root's ``rowHeight`` of one caption line, a row with one
// is ``detailedRowHeight`` (the caption plus the bounded description glimpse).
//
// Roles delivered by TimelineRowModel: eventId / caption / detail / tokenKey /
// flags. The caption and the detail arrive PRE-FORMATTED by Python (dates
// through the game calendar, open end shown as ``∞``, the description already
// collapsed and bounded): this file never re-derives content, it only paints
// the delivered scalars — never a second rule engine. It only decides how many
// PAINTED lines the glimpse takes (two, then elided).
//
// Visual truth (spec «Плоский список событий» / «Оформление списка из
// токенов»): the caption line; the description line in the secondary token
// (``color.accent.fg`` over the selection wash); the type mark is the bare
// ``color.chart.N`` token square on the left (muted ``color.fg.muted`` for
// untyped, no outline, so it keeps its color over the selection wash), riding
// the caption line; the selection wash is the accent itself, hover the
// compiler's accent-derivation pair — a token COLOR plus a scalar alpha,
// because QML's color parser cannot read the sheet's rgba() form; off-skin the
// guarded lookups land on the same pinned named Qt globals the other controls
// degrade to. Colors come from ``islandPalette`` ONLY — no hex, no OS palette,
// no JS color math (the test_no_chrome_hex invariant).
//
// Interactions stay thin Qt wrappers: one MouseArea for click/double-click
// gated on the delivered ``selectable`` flag, one HoverHandler reporting the
// dynamic tooltip (full name + range — the caption itself, readable even
// when the text elides) through the island's bridge. A miss past the rows is
// handled by the island root, not here.
import QtQuick
import nri.components
import "nri/components/tokens.js" as Tokens

Item {
    id: row

    // ── delivered roles (TimelineRowModel roleNames) ────────────────────────
    required property int index
    required property var eventId
    required property string caption
    required property string detail
    required property var tokenKey
    required property var flags

    // ── island-owned state fed by the root's binding (D2) ───────────────────
    property bool selectedRow: false      // the washed row of selectedId

    // ── interaction channel to the root ─────────────────────────────────────
    signal rowClicked()
    signal rowDoubleClicked()

    // The delegate contract for the acceptance harness: the flat list knows
    // exactly one row kind.
    objectName: "eventRow"

    // Row geometry: mark at TEXT_LEFT_PAD, mark side MARK_SIZE, text at
    // TEXT_INDENT = 8 + 8 + 4, right bleed TEXT_LEFT_PAD (the migrated
    // ladder row's rhythm, kept identical so the mark/text pair reads the
    // same as every earlier scale). The block hugs the row's top so the
    // caption line — and the mark riding it — sits at the same height in a
    // one-line and a two-line row.
    readonly property int textLeftPad: 8
    readonly property int markSize: 8
    readonly property int textIndent: 20
    readonly property int textTopPad: 4
    readonly property int lineGap: 1

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)

    readonly property color fgColor: Tokens.token(islandTokens, "color.fg.primary", "black")
    // The secondary text rank of the skin: the same muted token the emptiness
    // hint and the untyped type mark use — the description line is the row's
    // second-rank text, so it takes the row's ONE muted colour (no second
    // colour role invented).
    readonly property color mutedColor: Tokens.token(islandTokens, "color.fg.muted", "gray")
    readonly property color accentColor: Tokens.token(islandTokens, "color.accent", "black")
    readonly property color accentFgColor: Tokens.token(islandTokens, "color.accent.fg", "white")
    // Hover wash = the accent itself under the compiler's row-wash alpha
    // (the pair the Python palette derives; see the comment above). Off-skin
    // it falls back to the same named global the muted captions use, at the
    // migrated 0.25 wash alpha.
    readonly property color rowWashColor: Tokens.token(islandTokens, "color.accent.rowHover", "gray")
    readonly property real rowWashAlpha: Tokens.px(islandTokens, "opacity.accent.rowHover", 0.25)

    // The dynamic row tooltip (spec «Подсказка с названием и датами»): the
    // caption carries the full name and the real range, shown even when the
    // text itself elides. Declared with the library shim, shown by the
    // island's bridge on hover.
    Nri.tooltip: row.caption

    // Selection / hover washes, full row width exactly like fillRect(rect).
    // The selection is the accent itself (alpha 1); the hover wash is the
    // same accent under the migrated 0.25 wash alpha, never under the
    // selection — and only on selectable rows (every delivered row is one
    // today; the flag stays the gate so a filtered-out row stays inert).
    Rectangle {
        anchors.fill: parent
        visible: row.selectedRow
            || (row.hoveredRow && !!(row.flags && row.flags.selectable))
        color: row.selectedRow ? row.accentColor : row.rowWashColor
        opacity: row.selectedRow ? 1.0 : row.rowWashAlpha
    }

    // The type mark: the bare ``color.chart.N`` token square (untyped rows
    // land on the muted fallback). No outline over the wash. It rides the
    // CAPTION line (a sibling anchor), so a two-line row keeps the mark on the
    // same height as a one-line row.
    Rectangle {
        objectName: "eventTypeMark"
        x: row.textLeftPad
        width: row.markSize
        height: row.markSize
        anchors.verticalCenter: rowText.verticalCenter
        // tokenKey is the delivered "color.chart.N" key (None/undefined for
        // the untyped row — token() then answers the muted fallback).
        color: Tokens.token(row.islandTokens,
                            row.tokenKey ? String(row.tokenKey) : "", row.mutedColor)
    }

    // The caption line. Selected rows flip to accent.fg while washed.
    Text {
        id: rowText
        objectName: "rowText"
        x: row.textIndent
        width: Math.max(row.width - row.textIndent - row.textLeftPad, 0)
        anchors.top: parent.top
        anchors.topMargin: row.textTopPad
        text: row.caption
        elide: Text.ElideRight
        font.pixelSize: Tokens.px(row.islandTokens, "font.size.md", 13)
        color: row.selectedRow ? row.accentFgColor : row.fgColor
    }

    // The description glimpse (spec «Плоский список событий»): the delivered
    // one-line text wrapped over AT MOST two painted lines, the rest elided —
    // Python bounded the text, this file only decides how much of it shows.
    // An event with nothing to say paints nothing here (the row drops back to
    // its single-line height).
    Text {
        id: rowDetail
        objectName: "rowDetail"
        x: row.textIndent
        width: Math.max(row.width - row.textIndent - row.textLeftPad, 0)
        anchors.top: rowText.bottom
        anchors.topMargin: row.lineGap
        text: row.detail
        visible: text !== ""
        wrapMode: Text.WordWrap
        elide: Text.ElideRight
        maximumLineCount: 2
        font.pixelSize: Tokens.px(row.islandTokens, "font.size.sm", 11)
        color: row.selectedRow ? row.accentFgColor : row.mutedColor
    }

    // Hover: the wash under the cursor + the bridge's tooltip report.
    readonly property bool hoveredRow: rowHover.hovered
    HoverHandler {
        id: rowHover
        onHoveredChanged: {
            if (typeof tooltipBridge === "undefined" || tooltipBridge === null)
                return
            if (hovered)
                tooltipBridge.tooltipRequested((row).Nri.tooltip, point.scenePosition)
            else
                tooltipBridge.tooltipRequested("", Qt.point(0, 0))
        }
    }

    // Click / double-click: selection and editor, the row's whole gesture
    // budget (a press below the click threshold is Qt's own click logic — no
    // drag lives here anymore). Gated on the delivered ``selectable`` flag.
    MouseArea {
        anchors.fill: parent
        enabled: !!(row.flags && row.flags.selectable)
        acceptedButtons: Qt.LeftButton
        onClicked: row.rowClicked()
        onDoubleClicked: row.rowDoubleClicked()
    }
}
