// ThemeField — the library's text input (change
// add-qml-component-library-q2a1, task 2.2; design D4's field role: bg
// color.bg.canvas, border color.border, focus border color.accent — the
// task spells the field bg token explicitly).
//
// Off-skin (design D7): every overridden style item collapses to null, so
// the control falls back to its plain Basic look (verified headless: the
// default Basic background repaints) while text input still works; the
// remaining token-driven values degrade to the pinned named-Qt-global
// fallbacks. No hex, no OS palette, no color math — derivations come from
// the Python compiler through the bridge.
import QtQuick
import QtQuick.Controls
import "tokens.js" as Tokens

TextField {
    id: control

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""

    readonly property color canvasColor: Tokens.token(islandTokens, "color.bg.canvas", "white")
    readonly property color fgColor: Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color borderColor: Tokens.token(islandTokens, "color.border", "lightgray")
    readonly property color accentColor: Tokens.token(islandTokens, "color.accent", "black")
    readonly property color accentFgColor: Tokens.token(islandTokens, "color.accent.fg", "white")

    // Catalog field-role padding: vertical space.xs, horizontal space.sm.
    leftPadding: Tokens.px(islandTokens, "space.sm", 8)
    rightPadding: Tokens.px(islandTokens, "space.sm", 8)
    topPadding: Tokens.px(islandTokens, "space.xs", 4)
    bottomPadding: Tokens.px(islandTokens, "space.xs", 4)
    font.pixelSize: Tokens.px(islandTokens, "font.size.md", 13)

    color: control.fgColor
    // Catalog field-selection pair: selection-background-color accent,
    // selection-color accent.fg. (Qt 6 TextField dropped disabledTextColor;
    // Basic dims the text itself.)
    selectionColor: control.accentColor
    selectedTextColor: control.accentFgColor

    background: control.skinned ? fieldBackground : null

    Rectangle {
        id: fieldBackground
        // Invisible while floating unassigned: off-skin, `background: null`
        // re-materializes the Basic default and this child must not paint.
        visible: control.skinned
        radius: Tokens.px(islandTokens, "radius.sm", 6)
        color: control.canvasColor
        border.width: 1
        border.color: control.activeFocus ? control.accentColor : control.borderColor
    }
}
