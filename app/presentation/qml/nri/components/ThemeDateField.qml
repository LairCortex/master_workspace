import QtQuick
import QtQuick.Controls
import "tokens.js" as Tokens

Control {
    id: control

    property string isoDate: ""
    property string display: ""
    signal clicked()

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""
    readonly property color canvasColor:
        Tokens.token(islandTokens, "color.bg.canvas", "white")
    readonly property color foregroundColor:
        Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color borderColor:
        Tokens.token(islandTokens, "color.border", "lightgray")

    leftPadding: Tokens.px(islandTokens, "space.sm", 8)
    rightPadding: Tokens.px(islandTokens, "space.sm", 8)
    topPadding: Tokens.px(islandTokens, "space.xs", 4)
    bottomPadding: Tokens.px(islandTokens, "space.xs", 4)

    contentItem: Text {
        text: control.display
        color: control.foregroundColor
        font.pixelSize: Tokens.px(control.islandTokens, "font.size.md", 13)
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    background: control.skinned ? fieldBackground : null
    Rectangle {
        id: fieldBackground
        visible: control.skinned
        color: control.canvasColor
        radius: Tokens.px(control.islandTokens, "radius.sm", 6)
        border.width: 1
        border.color: control.borderColor
    }

    TapHandler {
        cursorShape: Qt.PointingHandCursor
        onTapped: control.clicked()
    }
}
