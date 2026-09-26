// ThemeCheckBox — the library's toggle control (change
// add-qml-component-library-q2a1, task 2.3; design D4: indicator by
// tokens — canvas box with the token border, accent fill when checked).
//
// Optical centering (change nri-0018-grid-alignment-and-card task 2.2,
// design Д2): the Basic style never repositions a user-supplied indicator,
// so the component itself places the box at the style's own centering
// formula plus the caption's optical correction — the indicator center
// meets the caption ink's center with the label metrics alone (FontMetrics
// descent+leading), and the top/bottom strip padding (space.sm) makes the
// control's implicit band equal the text buttons' row gauge. The correction
// ships capped at 1 px (owner resolution 2026-09-25) so the centering lands
// inside the ±1 px acceptance tolerance of the geometry pin.
//
// Off-skin (design D7): indicator and contentItem collapse to null so the
// Basic indicator box and CheckLabel re-materialize untouched; the checkmark
// lives inside the skinned indicator and never exists off-skin. Fallbacks
// are the pinned named-Qt-global set.
import QtQuick
import QtQuick.Controls
import "tokens.js" as Tokens

CheckBox {
    id: control

    // Indicator edge: geometry from the flat space scale (space.md token,
    // a 16px box with the shipped values), not an invented constant.
    readonly property real boxSize: Tokens.px(islandTokens, "space.md", 16)

    // The row band (design Д2): vertical padding out of the same space.sm
    // the text buttons pad with, so implicitHeight equals the buttons' strip
    // (line box + 2×8 at the shipped tokens) in every island action row.
    topPadding: Tokens.px(islandTokens, "space.sm", 8)
    bottomPadding: Tokens.px(islandTokens, "space.sm", 8)

    // Caption metrics drive the optical placement of the box (spec «Чекбокс
    // ставит индикатор и подпись на один оптический центр»): descent+leading
    // half is the ink hang below the geometric line center; the cap at 1 keeps
    // the correction inside the pinned ±1 px on fonts with a large descent.
    readonly property real opticalNudge:
        Math.min((labelMetrics.descent + labelMetrics.leading) / 2, 1)

    FontMetrics {
        id: labelMetrics
        font: control.font
    }

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""

    readonly property color canvasColor: Tokens.token(islandTokens, "color.bg.canvas", "white")
    readonly property color fgColor: Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color mutedColor: Tokens.token(islandTokens, "color.fg.muted", "gray")
    readonly property color borderColor: Tokens.token(islandTokens, "color.border", "lightgray")
    readonly property color accentColor: Tokens.token(islandTokens, "color.accent", "black")
    readonly property color accentFgColor: Tokens.token(islandTokens, "color.accent.fg", "white")

    // Grouping gap (owner design note 2026-09-26): the box and its caption
    // are ONE element, so the space between them is the tighter space.xs —
    // strictly smaller than the space.sm gap the surrounding row keeps
    // between neighbouring controls (the launcher's button row read the
    // box and «Светлая тема» as two row items at the old equal gap).
    spacing: Tokens.px(islandTokens, "space.xs", 4)

    // The same rule made measurable (offscreen probe 2026-09-26): the Basic
    // style still places a user-supplied contentItem at its own default 6 px
    // leftPadding while it NEVER repositions a user-supplied indicator (it
    // stays at x = 0 — the very quirk nri-0018 pinned for the y axis), so
    // that padding silently ADDS itself to the box↔caption gap (measured
    // 10 px against the row's 8). The control's own paddings stay untouched
    // (they are the off-skin bounds — D7); the skinned label below simply
    // subtracts the style inset, so the painted gap equals `spacing`.
    font.pixelSize: Tokens.px(islandTokens, "font.size.md", 13)

    indicator: control.skinned ? themedIndicator : null

    Rectangle {
        id: themedIndicator
        visible: control.skinned  // floats invisible while off-skin
        implicitWidth: control.boxSize
        implicitHeight: control.boxSize
        // The style's own centering formula (Basic CheckBox places its
        // indicator at topPadding + (availableHeight − height)/2) carries over
        // because Qt never positions a user-supplied indicator itself; the
        // optical nudge then walks the box down to the caption ink's center,
        // quantized to the raster the whole acceptance suite pins (Д2).
        y: Math.round(control.topPadding + (control.availableHeight - height) / 2
                      + control.opticalNudge)
        radius: Tokens.px(islandTokens, "radius.sm", 6)
        color: control.checked ? control.accentColor : control.canvasColor
        border.width: 1
        border.color: control.activeFocus ? control.accentColor : control.borderColor

        // Checkmark: accentFg over the checked accent fill, assembled as two
        // legs hanging off the indicator's centre point; rotation turns a
        // plain token-coloured bar into the tick (geometry only).
        Item {
            id: tickLegs
            anchors.centerIn: parent
            width: control.boxSize
            height: control.boxSize
            Rectangle {
                visible: control.checked
                x: tickLegs.width * 0.18
                y: tickLegs.height * 0.48
                width: tickLegs.width * 0.24
                height: 2  // tick leg thickness (geometry, not a token surface)
                color: control.accentFgColor
                rotation: 45
                transformOrigin: Item.TopLeft
            }
            Rectangle {
                visible: control.checked
                x: tickLegs.width * 0.34
                y: tickLegs.height * 0.52
                width: tickLegs.width * 0.44
                height: 2  // tick leg thickness (geometry, not a token surface)
                color: control.accentFgColor
                rotation: -45
                transformOrigin: Item.TopLeft
            }
        }
    }

    contentItem: control.skinned ? themedLabel : null

    Text {
        id: themedLabel
        visible: control.skinned  // floats invisible while off-skin
        // The control lays the contentItem over the whole padding rect, the
        // indicator included (Basic's own CheckLabel carries the same inset);
        // without it the label paints on top of the box. The item itself
        // starts at the style's leftPadding, so that inset is subtracted —
        // the ink then begins exactly `spacing` past the box (the gap note
        // above the font properties).
        leftPadding: control.indicator
            ? Math.max(control.indicator.width + control.spacing - control.leftPadding, 0)
            : 0
        text: control.text
        font: control.font
        color: control.enabled ? control.fgColor : control.mutedColor
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
}
