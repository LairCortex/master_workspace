// ThemeTabBar — the strip holding ThemeTabButton tabs (design D4's button
// family). Basic paints the bar as an opaque toolbar-like band with its own
// separator; the island's surface is the only background this chrome needs,
// so the bar itself is transparent and only spaces its tabs.
//
// The background is assigned inline, not through the library's floating-item
// pattern: TabBar is a Container whose default property is `contentData`, so
// a floating child would be picked up as an extra tab. "transparent" is a
// named Qt global, so the off-skin run stays free of invented colors too.
import QtQuick
import QtQuick.Controls
import "tokens.js" as Tokens

TabBar {
    id: control

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""

    spacing: Tokens.px(islandTokens, "space.xs", 4)

    background: Rectangle {
        color: "transparent"
    }
}
