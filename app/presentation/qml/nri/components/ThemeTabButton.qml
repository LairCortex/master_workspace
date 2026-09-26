// ThemeTabButton — the library's tab, NRI-0019: an underline tab, not a
// member of the button family. Rounded borders around every caption read as
// buttons; a tab reads as a tab: no fill, the caption turns accent when the
// tab is current, the current tab sits on a 2 px accent underline, and every
// tab carries its share of the strip's 1 px baseline hairline (the tabs sit
// flush, so the hairlines join into one continuous line under the bar).
//
// The width contract is the component's too (spec qml-components «Вкладки
// делят ширину полосы»): `Layout.fillWidth` makes the ThemeTabBar row give
// each tab a share of the bar — stretched beyond the natural caption width
// while the column is roomy, shrunk proportionally below it when the column
// narrows, the caption eliding to «Организаци…».
//
// Off-skin (design D7): the style slots collapse to null so the Basic tab
// re-materializes untouched; the underline stays island chrome.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "tokens.js" as Tokens

TabButton {
    id: control

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""

    readonly property color fgColor: Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color mutedColor: Tokens.token(islandTokens, "color.fg.muted", "gray")
    readonly property color borderColor: Tokens.token(islandTokens, "color.border", "lightgray")
    readonly property color accentColor: Tokens.token(islandTokens, "color.accent", "black")

    function accentHover(base) { return Tokens.token(islandTokens, "color.accent.hover", base) }
    function accentPressed(base) { return Tokens.token(islandTokens, "color.accent.pressed", base) }

    // The label's inset: it also sets the strip's height (the tap target
    // stays a button-sized row even though nothing is outlined anymore).
    padding: Tokens.px(islandTokens, "space.sm", 8)
    leftPadding: padding
    rightPadding: padding
    font.pixelSize: Tokens.px(islandTokens, "font.size.md", 13)

    // NRI-0019: the tab shares the bar's width through the ThemeTabBar's
    // layout row (see the header comment); its natural width is the row's
    // share base, never a hard floor.
    Layout.fillWidth: true

    // NRI-0017 (B1, design F4): the stock press path is dead for this control
    // — the Qt6 accessibility bridge exposes NO action for an un-annotated
    // checkable AbstractButton (probe: offscreen; live B1: VoiceOver never
    // reached the tabs). The press machinery is the component's, per the
    // NRI-0012 D2 rule (a forgetful usage-site must not be able to break the
    // contract): a single accessibility Press clicks the tab exactly like a
    // mouse click — the same click state machine toggles the exclusive
    // checked state and drives the bar's currentIndex. Only the handler is
    // attached; role and name stay the stock face (the name is the caption,
    // never re-annotated — 4.2/4.1 guards stay green).
    Accessible.onPressAction: control.click()

    // The tab's natural (preferred) width is its text's implicit width plus
    // the horizontal padding — the caption floor never comes from a
    // hand-tuned pt constant; the layout row shrinks below it on demand.
    implicitWidth: implicitContentWidth + leftPadding + rightPadding

    contentItem: control.skinned ? themedLabel : null

    Text {
        id: themedLabel
        visible: control.skinned  // floats invisible while off-skin
        text: control.text
        font: control.font
        // Current = the accent caption; the rest is plain fg text answering
        // hover/press with the accent's interaction shades.
        color: !control.enabled
            ? control.mutedColor
            : control.checked ? control.accentColor
            : control.pressed ? control.accentPressed(control.fgColor)
            : control.hovered ? control.accentHover(control.fgColor)
            : control.fgColor
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    background: control.skinned ? themedBackground : null

    Rectangle {
        id: themedBackground
        visible: control.skinned  // floats invisible while off-skin
        color: "transparent"

        // The strip's baseline: every tab draws its own share, the flush
        // neighbours join it into one line across the bar.
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: control.borderColor
        }

        // The current tab's underline covers the baseline at its span.
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 2
            color: control.accentColor
            visible: control.checked
        }
    }
}
