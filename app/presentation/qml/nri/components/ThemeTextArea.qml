// ThemeTextArea — library multiline field (change port-thin-dialogs-qml-r3).
// Field tokens match ThemeField: canvas fill, border, accent focus, fg text.
// Off-skin: background null → Basic TextArea; named-Qt-global fallbacks only.
import QtQuick
import QtQuick.Controls
import "tokens.js" as Tokens

TextArea {
    id: control

    property bool mono: false

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""

    readonly property color canvasColor: Tokens.token(islandTokens, "color.bg.canvas", "white")
    readonly property color fgColor: Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color borderColor: Tokens.token(islandTokens, "color.border", "lightgray")
    readonly property color accentColor: Tokens.token(islandTokens, "color.accent", "black")
    readonly property color accentFgColor: Tokens.token(islandTokens, "color.accent.fg", "white")

    leftPadding: Tokens.px(islandTokens, "space.sm", 8)
    rightPadding: Tokens.px(islandTokens, "space.sm", 8)
    topPadding: Tokens.px(islandTokens, "space.xs", 4)
    bottomPadding: Tokens.px(islandTokens, "space.xs", 4)
    font.pixelSize: Tokens.px(islandTokens, "font.size.md", 13)
    font.family: control.mono
        ? ("" + Tokens.token(islandTokens, "font.family.mono", "monospace")).split(",")[0].trim()
        : Qt.application.font.family

    color: control.fgColor
    selectionColor: control.accentColor
    selectedTextColor: control.accentFgColor
    wrapMode: TextEdit.Wrap

    background: control.skinned ? fieldBackground : null

    Rectangle {
        id: fieldBackground
        visible: control.skinned
        radius: Tokens.px(islandTokens, "radius.sm", 6)
        color: control.canvasColor
        border.width: 1
        border.color: control.activeFocus ? control.accentColor : control.borderColor
    }
}
