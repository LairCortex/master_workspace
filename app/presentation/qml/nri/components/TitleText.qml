// TitleText — the library's section-title label (change
// add-qml-component-library-q2a1, task 2.4).
//
// Role equivalence (design D4): the QSS rule behind catalog.py's `title()`
// factory (compiler `[uiRole="title"]`) emits font.size.lg +
// font.weight.bold + color.fg.primary, growing to font.size.xl for the
// title(size="xl") modifier — this control reads the very same tokens, so a
// pixel test can demand one look from both sources.
//
// A text label has no style-item slot to hand back off-skin: the token
// lookups simply resolve to the pinned named-Qt-global fallbacks.
import QtQuick
import "tokens.js" as Tokens

Text {
    id: title

    // Mirrors catalog.py's title size modifiers: "md" is the base rule
    // (font.size.lg), "xl" grows to the xl token.
    property string roleSize: "md"

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""

    readonly property color fgColor: Tokens.token(islandTokens, "color.fg.primary", "black")

    font.pixelSize: roleSize === "xl"
        ? Tokens.px(islandTokens, "font.size.xl", 16)
        : Tokens.px(islandTokens, "font.size.lg", 14)
    font.weight: Tokens.px(islandTokens, "font.weight.bold", 400)
    color: title.fgColor
    elide: Text.ElideRight
}
