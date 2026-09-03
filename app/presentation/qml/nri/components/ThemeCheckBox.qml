// ThemeCheckBox — the library's toggle control (change
// add-qml-component-library-q2a1, task 2.3; design D4: indicator by
// tokens — canvas box with the token border, accent fill when checked).
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

    spacing: Tokens.px(islandTokens, "space.sm", 8)
    font.pixelSize: Tokens.px(islandTokens, "font.size.md", 13)

    indicator: control.skinned ? themedIndicator : null

    Rectangle {
        id: themedIndicator
        visible: control.skinned  // floats invisible while off-skin
        implicitWidth: control.boxSize
        implicitHeight: control.boxSize
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
        text: control.text
        font: control.font
        color: control.enabled ? control.fgColor : control.mutedColor
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
}
