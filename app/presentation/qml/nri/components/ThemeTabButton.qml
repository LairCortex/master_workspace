// ThemeTabButton — the library's tab, NRI-0019: an underline tab, not a
// member of the button family. Rounded borders around every caption read as
// buttons; a tab reads as a tab: no fill, the caption turns accent when the
// tab is current, the current tab sits on a 2 px accent underline, and every
// tab carries its share of the strip's 1 px baseline hairline (the tabs sit
// flush, so the hairlines join into one continuous line under the bar).
//
// The width contract belongs to the ThemeTabBar (spec qml-components
// «Вкладки делят ширину полосы»): the bar hand-lays its row so every tab
// gets an EQUAL share of the strip — stretched beyond the natural caption
// width while the column is roomy, shrunk in equal shares below it when the
// column narrows (the caption length buys no tab extra pixels), the caption
// eliding to «Организаци…». The button itself only supplies the natural
// width the bar's implicit size is summed from, plus this elide mechanism.
//
// Off-skin (design D7): the style slots collapse to null so the Basic tab
// re-materializes untouched; the underline stays island chrome.
import QtQuick
import QtQuick.Controls
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

    // Lucide icon of this tab (Lucide pass 2026-09-30, the ThemeButton
    // contract mirrored): a name of the generated icons.js map, drawn by the
    // library ThemeIcon before the caption with the ThemeButton's shared
    // iconGap. Paint only — the caption, the stock name and the component-
    // owned role/press (NRI-0017 F4) are untouched; empty (default) keeps
    // the plain text tab bit-for-bit as it was.
    property string iconName: ""
    property int iconSize: 16
    readonly property real iconGap: Tokens.px(islandTokens, "space.xs", 4)

    // NRI-0019: the tab's width is handed out by the ThemeTabBar's manual
    // equal-share layout (see the header comment); its own natural width is
    // only the sum material for the bar's implicit size, never a hard floor.

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

    // The tab's natural (preferred) width is its content's implicit width
    // plus the horizontal padding — the caption floor never comes from a
    // hand-tuned pt constant; the bar's equal shares shrink below it on
    // demand and the caption below that elides (ThemedLabel, ElideRight).
    implicitWidth: implicitContentWidth + leftPadding + rightPadding

    contentItem: control.skinned ? themedContentBox : null

    // Caption + optional Lucide glyph, kept centered as one group — the
    // ThemeButton geometry law (no positioner, so the caption may still be
    // squeezed below its implicit width and elide at the bar's share).
    Item {
        id: themedContentBox
        visible: control.skinned  // floats invisible while off-skin

        readonly property real glyphW: control.iconName !== "" ? control.iconSize : 0
        readonly property real glyphGap:
            control.iconName !== "" && control.text !== "" ? control.iconGap : 0
        readonly property real captionImplicit:
            control.text !== "" ? themedLabel.implicitWidth : 0
        readonly property real groupWidth: glyphW + glyphGap + Math.min(
            captionImplicit, Math.max(0, width - glyphW - glyphGap))

        implicitWidth: glyphW + glyphGap + captionImplicit
        implicitHeight: Math.max(themedLabel.implicitHeight, control.iconSize)

        ThemeIcon {
            id: themedGlyph
            objectName: "themeTabIcon"
            visible: control.iconName !== ""
            name: control.iconName
            size: control.iconSize
            tint: themedLabel.color
            x: (themedContentBox.width - themedContentBox.groupWidth) / 2
            y: (themedContentBox.height - height) / 2
        }
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
            x: themedGlyph.x + themedContentBox.glyphW + themedContentBox.glyphGap
            width: themedContentBox.groupWidth
                - themedContentBox.glyphW - themedContentBox.glyphGap
            y: (themedContentBox.height - height) / 2
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
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
