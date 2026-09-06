import QtQuick
import "tokens.js" as Tokens

Rectangle {
    id: card

    property color tintColor: "transparent"

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""
    readonly property color surfaceColor:
        Tokens.token(islandTokens, "color.bg.surface", "transparent")
    readonly property color borderColor:
        Tokens.token(islandTokens, "color.border", "transparent")

    color: card.skinned ? card.surfaceColor : "transparent"
    radius: Tokens.px(islandTokens, "radius.sm", 6)
    border.width: card.skinned ? 1 : 0
    border.color: card.borderColor

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        visible: card.skinned
        color: card.tintColor
        radius: card.radius
    }
}
