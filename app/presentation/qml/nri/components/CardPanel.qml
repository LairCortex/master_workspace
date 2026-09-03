// CardPanel — the library's raised content panel (change
// add-qml-component-library-q2a1, task 2.5; design D4: the catalog card
// role as a Rectangle — bg/border/radius are exactly the tokens
// compiler.py's `[uiRole="card"]` rule embeds: color.bg.surface,
// color.border, radius.sm).
//
// `padding` is the card rule's space.sm content padding exposed for the
// island to position children with (a Rectangle paints no content itself).
// Off-skin: the token lookups degrade to the pinned named-Qt-global
// fallbacks — a plain white panel with a light-gray hairline, no exceptions.
import QtQuick
import "tokens.js" as Tokens

Rectangle {
    id: card

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""

    readonly property color surfaceColor: Tokens.token(islandTokens, "color.bg.surface", "white")
    readonly property color borderColor: Tokens.token(islandTokens, "color.border", "lightgray")

    // Content inset for children (the QSS card rule's padding: space.sm).
    readonly property real padding: Tokens.px(islandTokens, "space.sm", 8)

    radius: Tokens.px(islandTokens, "radius.sm", 6)
    color: card.surfaceColor
    border.width: 1
    border.color: card.borderColor
}
