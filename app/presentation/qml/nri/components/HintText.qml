// HintText — the library's muted hint label (change
// add-qml-component-library-q2a1, task 2.4).
//
// Role equivalence (design D4): catalog.py's `hint()` factory stamps the QSS
// rule `[uiRole="hint"]` = color.fg.muted (font size stays the chrome base,
// font.size.md) with the optional italic modifier — the same tokens drive
// this label, and the italic flag mirrors the factory's keyword argument.
//
// Text has no style-item slot off-skin: token lookups resolve to the pinned
// named-Qt-global fallbacks (color.fg.muted's off-skin stand-in is "gray").
import QtQuick
import "tokens.js" as Tokens

Text {
    id: hint

    // catalog.py's hint(italic=True) modifier counterpart.
    property bool italic: false

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""

    readonly property color mutedColor: Tokens.token(islandTokens, "color.fg.muted", "gray")

    font.pixelSize: Tokens.px(islandTokens, "font.size.md", 13)
    font.italic: hint.italic
    color: hint.mutedColor
    elide: Text.ElideRight
}
