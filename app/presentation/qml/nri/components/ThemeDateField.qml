// ThemeDateField — the library's read-only date chip (R4; the click routes
// to the island's Python date-popup bridge, the component itself does no
// calendar arithmetic).
//
// NRI-0017 task 1.1 (design F1, the FI-1/M2 fix): the live tree dropped the
// whole field because a usage-site ``Accessible.name`` on a role-less
// ``Control`` never projects through cocoa — so the BUTTON ROLE and the
// single-activation press now live INSIDE the component (the contract: role
// is the component's, the name stays on the usage site, AGENTS "role is the
// component's"). Press emits the very same ``clicked()`` the TapHandler
// emits, so accessibility opens the popup through the mouse's own path and
// no second open path exists.
//
// The width floor is also the component's (M2: the elide ate the year):
// ``worstCaseText`` carries the host formatter's worst-case caption of the
// active calendar («день самый-длинное-имя-месяца год до н.э.»); without a
// host hint the component measures a built-in fallback worst mask instead.
// ``implicitWidth`` and ``Layout.minimumWidth`` keep every layout from
// shrinking the caption below that worst form, so the elide stays what it
// always was — a last-resort fallback that never fires for a real caption.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "tokens.js" as Tokens

Control {
    id: control

    property string isoDate: ""
    property string display: ""
    // The active calendar's widest printable caption (VM/formatter-supplied,
    // nri-0017 F1); empty = the host has none and the fallback mask below
    // decides the field's minimum width.
    property string worstCaseText: ""
    // The same caption measured in this field's font — the host-facing read
    // of the width floor (pinned by tests, so the floor is never silent).
    readonly property real worstCaseWidth: worstCaseMetrics.width
    signal clicked()

    // Widest standard-calendar form: «Сентябрь» tops the default month names,
    // «0» is among the widest digits, and the era suffix is the widest tail
    // (the calendar can always print a BC date). A game calendar with longer
    // names gets its precise worst form via worstCaseText instead.
    readonly property string fallbackWorstCaseText: "00 Сентябрь 0000 г. до н.э."

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""
    readonly property color canvasColor:
        Tokens.token(islandTokens, "color.bg.canvas", "white")
    readonly property color foregroundColor:
        Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color borderColor:
        Tokens.token(islandTokens, "color.border", "lightgray")

    // Accessibility contract (nri-0017 F1, pattern of RowItem/ThemeSwatch):
    // role and press are the component's; the name is the usage site's.
    Accessible.role: Accessible.Button
    Accessible.onPressAction: control.clicked()

    TextMetrics {
        id: worstCaseMetrics
        text: control.worstCaseText !== ""
              ? control.worstCaseText : control.fallbackWorstCaseText
        font.pixelSize: Tokens.px(control.islandTokens, "font.size.md", 13)
    }

    leftPadding: Tokens.px(islandTokens, "space.sm", 8)
    rightPadding: Tokens.px(islandTokens, "space.sm", 8)
    topPadding: Tokens.px(islandTokens, "space.xs", 4)
    bottomPadding: Tokens.px(islandTokens, "space.xs", 4)

    // Never narrower than the worst caption (plus paddings), and never
    // narrower than the current display when the host passed a too-short
    // hint — the elide only ever sees deliberately oversized foreign text.
    implicitWidth: Math.max(
        worstCaseMetrics.width,
        contentItem ? contentItem.implicitWidth : 0) + leftPadding + rightPadding
    // Layouts default fillWidth items to a minimum of 0 (probed on Qt 6.10),
    // so the floor is stated explicitly; the attached object belongs to this
    // item and the parent Layout reads it from inside the component (F1:
    // usage sites change nothing for the width guarantee).
    Layout.minimumWidth: implicitWidth

    contentItem: Text {
        text: control.display
        color: control.foregroundColor
        font.pixelSize: Tokens.px(control.islandTokens, "font.size.md", 13)
        verticalAlignment: Text.AlignVCenter
        // Secondary fallback only (spec «elide остаётся запасным»): with the
        // minimumWidth floor in place a real caption never reaches it.
        elide: Text.ElideRight
    }

    background: control.skinned ? fieldBackground : null
    Rectangle {
        id: fieldBackground
        visible: control.skinned
        color: control.canvasColor
        radius: Tokens.px(control.islandTokens, "radius.sm", 6)
        border.width: 1
        border.color: control.borderColor
    }

    TapHandler {
        cursorShape: Qt.PointingHandCursor
        onTapped: control.clicked()
    }
}
