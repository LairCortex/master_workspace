// ThemeTabButton — the library's tab, styled as the button family is: token
// padding around the label, the rounded button corner and the accent fill on
// the selected tab (Basic's own tab is a tall square strip that reads as a
// foreign control between token-skinned chrome).
//
// Off-skin (design D7): both style slots collapse to null so the Basic tab
// re-materializes untouched; the fallbacks are the pinned named-Qt-global
// set.
import QtQuick
import QtQuick.Controls
import "tokens.js" as Tokens

TabButton {
    id: control

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""

    readonly property color canvasColor: Tokens.token(islandTokens, "color.bg.canvas", "white")
    readonly property color fgColor: Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color mutedColor: Tokens.token(islandTokens, "color.fg.muted", "gray")
    readonly property color borderColor: Tokens.token(islandTokens, "color.border", "lightgray")
    readonly property color accentColor: Tokens.token(islandTokens, "color.accent", "black")
    readonly property color accentFgColor: Tokens.token(islandTokens, "color.accent.fg", "white")

    function accentHover(base) { return Tokens.token(islandTokens, "color.accent.hover", base) }
    function accentPressed(base) { return Tokens.token(islandTokens, "color.accent.pressed", base) }

    // The button family's inset: space.sm on every side of the label.
    padding: Tokens.px(islandTokens, "space.sm", 8)
    leftPadding: padding
    rightPadding: padding
    font.pixelSize: Tokens.px(islandTokens, "font.size.md", 13)

    // NRI-0015 (task 1.1): the button's natural minimum width is its text's
    // implicit width plus the button's own horizontal padding — the caption
    // floor never comes from a hand-tuned pt constant.
    implicitWidth: implicitContentWidth + leftPadding + rightPadding

    contentItem: control.skinned ? themedLabel : null

    Text {
        id: themedLabel
        visible: control.skinned  // floats invisible while off-skin
        text: control.text
        font: control.font
        color: !control.enabled
            ? control.mutedColor
            : control.checked ? control.accentFgColor : control.fgColor
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    background: control.skinned ? themedBackground : null

    Rectangle {
        id: themedBackground
        visible: control.skinned  // floats invisible while off-skin
        radius: Tokens.px(islandTokens, "radius.sm", 6)
        // Selected tab = the accent action; the rest carries the flat
        // button's canvas fill and token border.
        border.width: control.checked ? 0 : 1
        border.color: control.checked ? "transparent" : control.borderColor
        color: {
            if (control.checked)
                return control.pressed ? control.accentPressed(control.accentColor)
                     : control.hovered ? control.accentHover(control.accentColor)
                     : control.accentColor
            return control.pressed ? control.accentPressed(control.canvasColor)
                 : control.hovered ? control.accentHover(control.canvasColor)
                 : control.canvasColor
        }
    }
}
