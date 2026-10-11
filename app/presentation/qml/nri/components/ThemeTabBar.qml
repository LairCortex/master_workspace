// ThemeTabBar — the strip holding ThemeTabButton tabs (NRI-0019: a tab
// strip, not a row of buttons — see ThemeTabButton for the underline face).
//
// The tabs share the bar's WHOLE WIDTH IN EQUAL SHARES through the
// container's own positioning channel. No RowLayout is involved: a row
// distributes whatever it stretches or shrinks PROPORTIONALLY to the
// items' preferred widths, so a longer caption fattens its tab (2026-09-30
// repro: «Шаблоны»/«Листы» in an 800 px bar measured 460/340 — masked
// off-skin, where every unskinned tab shares the same natural width). With
// room to spare every tab stretches beyond its natural caption width to the
// same width as its siblings, and in a narrow column the tabs shrink below
// those widths in equal shares too — the captions then elide instead of the
// strip leaking past the panel (spec qml-components «Вкладки делят ширину
// полосы»). The mechanism lives in the component, so no usage site can
// forget it (the retired per-usage `width: implicitWidth` tail of NRI-0015
// M1 is gone with it).
//
// The carrier is Basic's own horizontal ListView — the stock TabBar's. The
// first cut (through 2026-10-10) was a hand-laid Item row fed by a Repeater
// over `contentModel`; DND-LIVE-1 buried it: the moment ANY rendered tab
// was destroyed under a live TabBar — the module tab joining replaces the
// usage Repeater's model, one removal is enough — the bar's whole render
// subtree stranded outside the scene graph. Every tab stayed skinned,
// visible, laid out and named, and printed no pixels; the offscreen grab
// measures the band empty from the FIRST frame (the join rides populate,
// before the window ever paints), and no post-hoc poke revives it (layout
// pokes, row/tab/bar visibility flicks, contentItem re-assignment — all
// measured dead 2026-10-10). The stock view-item recycling is the shipping
// path of this very control, and it survives exactly those churns (pin:
// replace/join/dejoin keep the strip rendering).
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
    // matches the equal shares the container hands out: exact divisions,
    // spacing 0.
    spacing: 0

    // The implicit size stays the tabs' natural sum/height — accumulated tab
    // by tab (each tab's implicitSizeChanged signals re-weigh it), never
    // through Basic's Math.max(background, content) implicit binding: while
    // the tab delegates populate, the pane's implicitContentWidth tracking
    // channel re-triggers that binding at every label-metrics resolution and
    // the engine flags an implicitWidth binding loop on creation (2026-09-26
    // repro: three loops per panel load). The accumulator converges silently
    // like the direct row read it replaces and still hands the content-driven
    // sheet sizes the tabs' natural sum — plain sum, the flush law above
    // means no gaps to add.
    property real naturalWidth: 0
    property real naturalHeight: 0
    property var __hookedTabs: []

    implicitWidth: naturalWidth

    function remeasureNatural() {
        let naturalW = 0
        let naturalH = 0
        for (let i = 0; i < tabsRow.count; ++i) {
            const tab = tabsRow.itemAtIndex(i)
            if (tab !== null) {
                naturalW += tab.implicitWidth
                naturalH = Math.max(naturalH, tab.implicitHeight)
                // Arrival re-weighs the natural sum; a tab's own caption-
                // metric changes (retheme, edited text) re-weigh it too.
                // The hooked-list guard keeps a count bump from stacking
                // the same connection (QML cannot hang a marker property
                // on a foreign item, and the engine hands the same JS
                // wrapper for the same QObject, so identity compare works).
                const hooked = control.__hookedTabs
                let seen = false
                for (let j = 0; j < hooked.length; ++j) {
                    if (hooked[j] === tab) {
                        seen = true
                        break
                    }
                }
                if (!seen) {
                    hooked.push(tab)
                    tab.implicitWidthChanged.connect(control.remeasureNatural)
                    tab.implicitHeightChanged.connect(control.remeasureNatural)
                }
            }
        }
        control.naturalWidth = naturalW
        control.naturalHeight = naturalH
    }

    contentItem: ListView {
        id: tabsRow
        // The stock carrier: the contentModel's tabs ride the view as its
        // own items — equal shares (bar width / count) and the churn-safe
        // add/remove lifecycle are the container machinery's, not ours.
        model: control.contentModel
        currentIndex: control.currentIndex
        spacing: control.spacing
        orientation: ListView.Horizontal
        // FlickStop is Flickable's default boundsBehavior — the enum member
        // reads back as undefined on this Qt build's QML side, so the line
        // stays unwritten rather than assigned.
        // Equal shares make the content exactly as wide as the viewport,
        // so there is never anything to scroll or flick.
        interactive: false
        implicitHeight: control.naturalHeight

        onCountChanged: control.remeasureNatural()
    }

    background: Rectangle {
        color: "transparent"
    }
}
