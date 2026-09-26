// ThemeTabBar — the strip holding ThemeTabButton tabs (NRI-0019: a tab
// strip, not a row of buttons — see ThemeTabButton for the underline face).
//
// The tabs share the bar's WHOLE WIDTH: the content row lays the tabs out
// with Layout.fillWidth, so with room to spare every tab stretches beyond
// its natural caption width, and in a narrow column the tabs shrink
// proportionally below those widths — the captions then elide instead of
// the strip leaking past the panel (spec qml-components «Вкладки делят
// ширину полосы»). The mechanism lives in the component, so no usage site
// can forget it (the retired per-usage `width: implicitWidth` tail of
// NRI-0015 M1 is gone with it).
//
// Basic paints the bar as an opaque toolbar-like band; the island's surface
// is the only background this chrome needs, so the bar itself stays
// transparent (the tabs draw the shared baseline hairline themselves).
//
// The background is assigned inline, not through the library's floating-item
// pattern: TabBar is a Container whose default property is `contentData`, so
// a floating child would be picked up as an extra tab. "transparent" is a
// named Qt global, so the off-skin run stays free of invented colors too.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "tokens.js" as Tokens

TabBar {
    id: control

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""

    // Underline tabs sit flush against each other; the baseline they draw
    // reads as one continuous hairline only without gaps.
    spacing: 0

    // The implicit width is read from the layout row directly, not through
    // Basic's Math.max(background, content) implicit binding: while the tab
    // delegates populate, the pane's implicitContentWidth tracking channel
    // re-triggers that binding at every label-metrics resolution and the
    // engine flags an implicitWidth binding loop on creation. The direct row
    // read converges silently (2026-09-26 repro: three loops per panel load)
    // and still hands the content-driven sheet sizes the tabs' natural sum.
    implicitWidth: tabBarRow.implicitWidth

    // The Repeater re-parents the usage-site tabs out of `contentData` into
    // the RowLayout, where the Layout attached properties take effect
    // (the documented Controls 2 recipe for a layout-driven bar).
    contentItem: RowLayout {
        id: tabBarRow
        spacing: control.spacing
        Repeater {
            model: control.contentModel
        }
    }

    background: Rectangle {
        color: "transparent"
    }
}
