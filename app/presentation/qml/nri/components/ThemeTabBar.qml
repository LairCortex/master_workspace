// ThemeTabBar — the strip holding ThemeTabButton tabs (NRI-0019: a tab
// strip, not a row of buttons — see ThemeTabButton for the underline face).
//
// The tabs share the bar's WHOLE WIDTH IN EQUAL SHARES, laid out by hand
// here (width = row width / tab count, x = index × share). No RowLayout is
// involved: a row distributes whatever it stretches or shrinks
// PROPORTIONALLY to the items' preferred widths, so a longer caption fattens
// its tab (2026-09-30 repro: «Шаблоны»/«Листы» in an 800 px bar measured
// 460/340 — masked off-skin, where every unskinned tab shares the same
// natural width). With room to spare every tab stretches beyond its natural
// caption width to the same width as its siblings, and in a narrow column
// the tabs shrink below those widths in equal shares too — the captions then
// elide instead of the strip leaking past the panel (spec qml-components
// «Вкладки делят ширину полосы»). The mechanism lives in the component, so
// no usage site can forget it (the retired per-usage `width: implicitWidth`
// tail of NRI-0015 M1 is gone with it).
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
import "tokens.js" as Tokens

TabBar {
    id: control

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""

    // Underline tabs sit flush against each other; the baseline they draw
    // reads as one continuous hairline only without gaps. The flush law also
    // owns the hand geometry below: shares are exact divisions, no gaps.
    spacing: 0

    // The implicit size stays the tabs' natural sum/height — accumulated tab
    // by tab through the Repeater (each tab's implicitSizeChanged signals
    // re-weigh it), never through Basic's Math.max(background, content)
    // implicit binding: while the tab delegates populate, the pane's
    // implicitContentWidth tracking channel re-triggers that binding at every
    // label-metrics resolution and the engine flags an implicitWidth binding
    // loop on creation (2026-09-26 repro: three loops per panel load). The
    // accumulator converges silently like the direct row read it replaces and
    // still hands the content-driven sheet sizes the tabs' natural sum —
    // plain sum, the flush law above means no gaps to add.
    // (JS cannot index `contentModel` on this Qt — a probe reads `undefined`
    // there at completion — so the Repeater is the tab carrier.)
    property real naturalWidth: 0
    property real naturalHeight: 0

    implicitWidth: naturalWidth

    function remeasureNatural() {
        let naturalW = 0
        let naturalH = 0
        for (let i = 0; i < tabsRepeater.count; ++i) {
            const tab = tabsRepeater.itemAt(i)
            if (tab !== null) {
                naturalW += tab.implicitWidth
                naturalH = Math.max(naturalH, tab.implicitHeight)
            }
        }
        control.naturalWidth = naturalW
        control.naturalHeight = naturalH
    }

    // The Repeater re-parents the usage-site tabs out of `contentData` into
    // the row; the row then positions them itself (library law: where a
    // standard layout would misapply its distribution rule, the component
    // lays out by hand).
    contentItem: Item {
        id: tabBarRow

        // The row's implicit height feeds Basic's implicit-height policy the
        // tallest tab, what the retired row layout reported the same way.
        implicitHeight: control.naturalHeight

        // One share per tab — the caption length buys no tab extra pixels.
        // Vertically the tabs keep their natural height and center in the
        // band, exactly what the retired RowLayout did with its default row
        // alignment (the band's height IS the tallest tab, so flush-on-zero
        // is the common case).
        function layoutTabs() {
            const n = tabsRepeater.count
            if (n <= 0)
                return
            const share = tabBarRow.width / n
            for (let i = 0; i < n; ++i) {
                const tab = tabsRepeater.itemAt(i)
                if (tab === null)
                    continue
                tab.x = i * share
                tab.y = (tabBarRow.height - tab.implicitHeight) / 2
                tab.width = share
                tab.height = tab.implicitHeight
            }
        }

        onWidthChanged: layoutTabs()
        onHeightChanged: layoutTabs()

        Repeater {
            id: tabsRepeater
            model: control.contentModel
            // Arrival/departure re-weighs the natural sum and re-shares the
            // row; a tab's own caption-metric changes (retheme, edited text)
            // re-weigh the sum without touching the shares (those read only
            // the row's live size).
            onItemAdded: (index, item) => {
                item.implicitWidthChanged.connect(control.remeasureNatural)
                item.implicitHeightChanged.connect(control.remeasureNatural)
                // The shares read only the row's live size, but the vertical
                // seat reads each tab's natural height — so a caption-metric
                // change re-weighs the sum AND re-seats the row.
                item.implicitHeightChanged.connect(tabBarRow.layoutTabs)
                control.remeasureNatural()
                tabBarRow.layoutTabs()
            }
            onItemRemoved: {
                control.remeasureNatural()
                tabBarRow.layoutTabs()
            }
        }
    }

    background: Rectangle {
        color: "transparent"
    }
}
