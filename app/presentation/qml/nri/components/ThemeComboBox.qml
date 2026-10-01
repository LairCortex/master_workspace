// ThemeComboBox — the library's dropdown (change
// add-qml-component-library-q2a1, task 2.3; design D4: field + indicator
// by tokens, popup list themed as well).
//
// Skin/off-skin split by style-slot machinery:
//   * background / contentItem / arrow indicator: `skinned` swaps in themed
//     items or hands the slot back to Basic (null re-materializes the style
//     default — verified headless), so off-skin the combo box itself is the
//     plain Basic control;
//   * popup / delegate: assigned unconditionally instead. ComboBox exposes
//     `popup` as a plain property whose default lives in the style
//     template — there is no evidence the null hand-back regenerates it, and
//     silently losing the dropdown would break the off-skin interaction
//     contract. The themed popup therefore degrades to the pinned
//     named-Qt-global fallbacks off-skin: a functional white popup with a
//     token-border frame and readable rows — interactions and no exceptions
//     are what the off-skin scenario pins.
//
// NRI-0023 group 12 (design Д14, live audit docs/qa/2026-09-29-now-hour-chip
// -design.md) — the geometry and the list are the component's contract now:
//   * Д14.1 (A1 blocker): the popup height is EXPLICIT —
//     min(count, maxRows) × rowHeight, never the lazy ListView's contentHeight
//     (that binding made the list exactly as tall as the two delegates it had
//     realized: rows 1…23 were unreachable by mouse). The remaining rows stay
//     reachable by wheel/keyboard, and the popup opens scrolled to the
//     highlighted row so the current value is visible without scrolling;
//     the popup is never narrower than the control nor than its widest row.
//   * Д14.2 (A4): the indicator gets its own right pocket — the control's
//     rightPadding is arrowSize + space.xs and the arrow paints inside that
//     pocket, so the value area and the arrow can no longer intersect.
//   * Д14.3 (H2): vertical paddings are space.xs, the same token the date
//     chip uses, so neighbours in one row share one height; `worstCaseText`
//     (VM-supplied, ThemeDateField's convention) fixes the control width to
//     the widest printable option, killing the per-selection jitter.
//   * Д14.4 (A2/A3/A6/A8): an open combo flips the arrow (180°) on top of the
//     accent frame, hover paints the compiler's `color.accent.hover` wash,
//     focus without opening keeps the arrow down; the rows carry a hairline
//     `color.border` divider so they stop merging into one blob.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "tokens.js" as Tokens

ComboBox {
    id: control

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""

    readonly property color canvasColor: Tokens.token(islandTokens, "color.bg.canvas", "white")
    readonly property color surfaceColor: Tokens.token(islandTokens, "color.bg.surface", "white")
    readonly property color fgColor: Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color mutedColor: Tokens.token(islandTokens, "color.fg.muted", "gray")
    readonly property color borderColor: Tokens.token(islandTokens, "color.border", "lightgray")
    readonly property color accentColor: Tokens.token(islandTokens, "color.accent", "black")
    readonly property color accentFgColor: Tokens.token(islandTokens, "color.accent.fg", "white")
    // The hover wash is the compiler's own derivation token (same source the
    // ThemeButton wash reads — never a computed color here).
    readonly property color accentHoverColor:
        Tokens.token(islandTokens, "color.accent.hover", "lightgray")

    // Д14.2 (A7): an empty value («—», «без часа») is a placeholder, not a
    // reading — the usage site flags it and the value prints at the muted
    // rank; a real value keeps fg.primary. The list rows are unaffected.
    property bool valueIsPlaceholder: false
    // Д14.3 (A5/H2): the active host's widest printable option (VM-supplied,
    // ThemeDateField's worstCaseText convention); empty = no host hint and
    // the control sizes to its content exactly as before.
    property string worstCaseText: ""

    // Д14.1 host half (re-audit 2026-09-29, A1): a host that fixes its own
    // height (the search-island facade mirrors the island's implicit height
    // with setFixedHeight) can never show this pop-up — a QQuickPopup paints
    // inside its host window, so the list there is cut to the widget's
    // bottom. Such a usage site sets externalPopup and answers
    // popupOpenRequested by opening the picker itself as a top-level window
    // (the date chip of the same row — the widgets bridge is the precedent).
    // The face, geometry, role, name and the activated(index) channel stay
    // the component's; only the pop-up OPEN REQUEST is redirected — and on
    // every path (mouse tap, key, accessibility Press), because each of them
    // funnels through Popup.open(). Hosts that keep the default get exactly
    // the Д14.1 pop-up above, unchanged.
    property bool externalPopup: false

    /// The host asked for our open — it shows the list outside itself.
    signal popupOpenRequested()

    // Arrow edge: derived from the font token, not an invented constant.
    readonly property real arrowSize: Tokens.px(islandTokens, "font.size.md", 13)

    // Floor measures — hidden Text items, the same item type and font the
    // value itself paints with (see implicitWidth: the same-engine measure is
    // what makes the floor a floor). They are template strangers: nothing
    // resizes them from the control's geometry, so no resize-notify loop.
    Text {
        id: worstCaseMeasure
        text: control.worstCaseText
        font: control.font
        visible: false
    }

    Text {
        id: displayMeasure
        text: control.displayText
        font: control.font
        visible: false
    }

    padding: Tokens.px(islandTokens, "space.xs", 4)
    // The indicator pocket (Д14.2): leftPadding stays the field's text inset,
    // rightPadding reserves the arrow plus a hair of gap so the value area
    // physically ends where the arrow band starts.
    leftPadding: Tokens.px(islandTokens, "space.sm", 8)
    rightPadding: control.arrowSize + Tokens.px(islandTokens, "space.xs", 4)
    font.pixelSize: Tokens.px(islandTokens, "font.size.md", 13)

    // Width floor (Д14.3): the worst option plus the paddings — selecting a
    // narrower value can no longer shrink the control; Layout.minimumWidth
    // states the floor to parent layouts (ThemeDateField's F1 pattern).
    // The measure items are hidden Texts with displayText's own font, NOT
    // TextMetrics: live 2026-09-29 caught the floor eliding its own worst
    // value («Час: …» for 23) because TextMetrics' horizontalAdvance measures
    // a hair narrower than the laid-out Text of the same string (46.27 vs
    // 47.86 here, the same shortfall the live selector died on) — the floor
    // has to be measured by the very engine that paints the value. The extra
    // point is the floor's rounding band: geometry lands on device pixels and
    // must never squeeze a value whose width equals the floor exactly
    // (truncated stays False — pinned in
    // tests/presentation/test_theme_combobox_popup.py).
    implicitWidth: Math.max(
        worstCaseMeasure.implicitWidth,
        displayMeasure.implicitWidth) + leftPadding + rightPadding + 1
    Layout.minimumWidth: implicitWidth

    // Д14.4: hover reads the pointer directly (the stock ComboBox exposes no
    // hover face for a hand-assigned background slot).
    HoverHandler { id: pointerHover }

    background: control.skinned ? comboBackground : null

    Rectangle {
        id: comboBackground
        objectName: "themeComboBackground"
        visible: control.skinned  // floats invisible while off-skin
        radius: Tokens.px(islandTokens, "radius.sm", 6)
        color: pointerHover.hovered && control.enabled
            ? control.accentHoverColor : control.canvasColor
        border.width: 1
        // Д14.4: the frame colour is one readable property — the state machine
        // (focus ≠ open) is the component's contract, while the border pen
        // itself is not addressable from the offscreen harness.
        readonly property color frameColor: control.activeFocus
            || (control.popup && control.popup.visible)
            ? control.accentColor : control.borderColor
        border.color: frameColor
    }

    contentItem: control.skinned ? displayText : null

    Text {
        id: displayText
        objectName: "themeComboDisplay"
        visible: control.skinned  // floats invisible while off-skin
        text: control.displayText
        font: control.font
        color: control.enabled && !control.valueIsPlaceholder
            ? control.fgColor : control.mutedColor
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: control.skinned ? themedArrow : null

    // Lucide icon pass 2026-09-30: the indicator is the library chevron-down
    // glyph (the hand-drawn Canvas triangle retires; the chevron is the same
    // down-pointing affordance, token-tinted through ThemeIcon — the bridge
    // value pass-through rule is untouched).
    //
    // Positioning is the component's own job (nri-0015, E4=B5; pocket since
    // NRI-0023 Д14.2): the glyph sits inside the reserved right band, one
    // space.xs from the frame — the value area (which ends at rightPadding)
    // and the arrow never share pixels. Д14.4: while the popup is open the
    // arrow flips (rotation is an Item transform, no repaint); a mere focus
    // keeps it down — «открыт» and «в фокусе» become distinguishable.
    ThemeIcon {
        id: themedArrow
        objectName: "themeComboArrow"
        visible: control.skinned  // floats invisible while off-skin
        x: control.width - width - Tokens.px(control.islandTokens, "space.xs", 4)
        y: control.topPadding + (control.availableHeight - height) / 2
        name: "chevron-down"
        // ThemeIcon's width/height follow its size — the pocket gauge stays
        // the component's arrowSize, same square the Canvas occupied.
        size: control.arrowSize
        tint: control.fgColor
        rotation: control.popup && control.popup.visible ? 180 : 0
        transformOrigin: Item.Center
    }

    // Д14.1 (A1): the widest printable value is measured from the MODEL, never
    // from the realized rows (a lazy list's contentWidth only ever knows the
    // rows it happened to materialize — offscreen it reads -1 forever, live it
    // was the 41 pt list of the audit). TextMetrics objects, not Items: the
    // measurement costs nothing and never paints.
    Instantiator {
        id: rowWidths
        model: control.model
        delegate: TextMetrics {
            text: modelData
            font.pixelSize: Tokens.px(control.islandTokens, "font.size.md", 13)
        }
    }

    popup: themedPopup

    // Д14.1 (A1): every geometry of the list is explicit —
    //   * height: min(count, maxRows) rows of a fixed rowHeight, never the
    //     lazy ListView's own implicitHeight (that is how the live audit got
    //     a two-row popup out of a 25-value model);
    //   * width: never narrower than the control, never narrower than the
    //     widest value of the model, measured from the model itself (a lazy
    //     list knows only the rows it happened to realize — offscreen its
    //     contentWidth is -1 forever, live it was the 41 pt list);
    //   * the wheel scrolls the list through this component (see WheelHandler
    //     below), the stock wheel path being an animation the island runtime
    //     never advances — the audit's «колесо не прокручивает вообще»;
    //   * on open the list positions the highlighted row into view, so the
    //     current value is visible without manual scrolling (A2).
    Popup {
        id: themedPopup
        objectName: "themeComboPopup"
        y: control.height
        padding: 1

        // The widest value of the MODEL, not of the realized rows: the row
        // metrics are TextMetrics objects (no Items, nothing painted), and
        // the font token is an explicit dependency so a theme recompile
        // re-measures.
        readonly property real widestRowTextWidth: {
            var fontPx = control.font.pixelSize
            var widest = 0
            for (var i = 0; i < rowWidths.count; ++i) {
                var rowMetrics = rowWidths.objectAt(i)
                if (rowMetrics && rowMetrics.width > widest)
                    widest = rowMetrics.width
            }
            return widest
        }
        // One row's horizontal inset is the delegate's left+right padding; the
        // popup grows by exactly that plus its own frame.
        readonly property real rowInset:
            2 * Tokens.px(control.islandTokens, "space.sm", 8)
        width: Math.max(control.width,
                        widestRowTextWidth + rowInset + leftPadding + rightPadding)

        // One row: one text line plus the space.xs band top and bottom —
        // measured from tokens, so the delegate and the height math below
        // can never disagree.
        readonly property real rowHeight: rowTextMetrics.height
            + 2 * Tokens.px(control.islandTokens, "space.xs", 4)
        // «несколько строк» (spec qml-components): eight rows cap the popup
        // so a long list still floats over its own field, not over the
        // window.
        readonly property int maxRows: 8

        implicitHeight: Math.min(popupList.count, themedPopup.maxRows) * rowHeight
            + topPadding + bottomPadding

        TextMetrics {
            id: rowTextMetrics
            // A sample glyph: an empty TextMetrics measures a zero-height
            // bounding box offscreen, and the row height must not depend on
            // realized delegates (the very A1 trap).
            text: "0"
            font.pixelSize: Tokens.px(control.islandTokens, "font.size.md", 13)
        }

        // The delegate model rides the visible transition, so the rows exist
        // one beat after `opened` — scroll in the next callLater pass.
        function scrollToHighlighted() {
            if (popupList.currentIndex >= 0)
                popupList.positionViewAtIndex(popupList.currentIndex, ListView.Beginning)
        }
        onOpened: Qt.callLater(scrollToHighlighted)
        // Д14.1 host half: an externalPopup usage site cancels our show here
        // — no frame has painted yet (offscreen-pinned: visible never becomes
        // true, repeated opens stay sane) — and takes the list into its own
        // top-level window through the signal.
        onAboutToShow: if (control.externalPopup) {
            close()
            control.popupOpenRequested()
        }

        contentItem: ListView {
            id: popupList
            objectName: "themeComboPopupList"
            clip: true
            // Explicit height: rows × one rowHeight (contentHeight of an
            // unbounded lazy list is the exact trap A1 fell into).
            implicitHeight: count * themedPopup.rowHeight
            // combo.popup is null until the style materializes it — guard
            // the transient so creation-order binding errors never fire.
            model: control.popup && control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            boundsBehavior: Flickable.StopAtBounds
            // Keyboard navigation moves the highlight with no gesture of its
            // own — an off-screen highlight would be the keyboard twin of A1,
            // so every move drags the row into view.
            onCurrentIndexChanged: if (currentIndex >= 0 && control.popup
                                       && control.popup.visible)
                positionViewAtIndex(currentIndex, ListView.Visible)

            // The wheel is the component's own (the island precedent is
            // SheetCanvas's onWheel): the stock wheel path only kicks the
            // Flickable into a momentum flick, and a flick is a frame-driven
            // animation — inside a QQuickWidget island (live AND offscreen)
            // no frame clock advances it, which is exactly why the audit
            // measured zero changed pixels per wheel notch. Setting contentY
            // is an immediate stop-at-bounds scroll, so the same code path
            // serves the real mouse wheel and the pinned one.
            WheelHandler {
                objectName: "themeComboPopupWheel"
                target: popupList
                onWheel: function (wheel) {
                    var travel = wheel.pixelDelta.y !== 0
                        ? wheel.pixelDelta.y : wheel.angleDelta.y
                    if (travel === 0)
                        return
                    wheel.accepted = true
                    popupList.contentY = Math.max(
                        0, Math.min(popupList.contentY - travel,
                                    Math.max(0, popupList.contentHeight
                                             - popupList.height)))
                }
            }
        }
        background: Rectangle {
            radius: Tokens.px(control.islandTokens, "radius.sm", 6)
            color: control.surfaceColor
            border.width: 1
            border.color: control.borderColor
        }
    }

    delegate: themedRow

    Component {
        id: themedRow
        ItemDelegate {
            id: rowDelegate
            objectName: "themeComboPopupRow"
            // The row fills the list; a row wider than the list drags the
            // popup contentWidth (and so the popup width) after it — the
            // popup never clips a value horizontally.
            width: Math.max(popupList.width, implicitWidth)
            height: themedPopup.rowHeight
            highlighted: control.highlightedIndex === index
            leftPadding: Tokens.px(control.islandTokens, "space.sm", 8)
            rightPadding: Tokens.px(control.islandTokens, "space.sm", 8)
            topPadding: Tokens.px(control.islandTokens, "space.xs", 4)
            bottomPadding: Tokens.px(control.islandTokens, "space.xs", 4)
            contentItem: Text {
                text: modelData
                font.pixelSize: Tokens.px(control.islandTokens, "font.size.md", 13)
                color: rowDelegate.highlighted
                    ? control.accentFgColor
                    : control.enabled ? control.fgColor : control.mutedColor
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
            background: Rectangle {
                color: rowDelegate.highlighted ? control.accentColor : control.canvasColor
                // A8: a hairline separates consecutive rows — the canvas
                // fill over the surface background was too weak to guide the
                // eye; the last row needs no divider under it.
                Rectangle {
                    objectName: "themeComboPopupDivider"
                    anchors.bottom: parent.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 1
                    color: control.borderColor
                    visible: index < control.count - 1
                }
            }
        }
    }
}
