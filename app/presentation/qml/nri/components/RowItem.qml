// RowItem — the library's list-row style (change
// add-qml-component-library-q2a1, task 2.5; design D4: the row extracted
// from the launcher delegate — selection colors mirror the catalog list
// role's ::item:selected pair, accent background + accent.fg text;
// geometry matches LauncherRoot's delegate exactly: text height + 2 *
// space.xs, insets space.sm).
//
// Composition, not a global ListView style: the list itself stays the
// island's (rows are placed by its delegate), so islands keep W3b-level
// delegate latitude (the design rejected global Controls styles).
// Selection is INPUT (`selected`) — the island owns the model semantics and
// answers the two signals; MouseArea behaviour is identical off-skin.
import QtQuick
import "tokens.js" as Tokens

Rectangle {
    id: row

    // Row affordances the island answers: single tap requests selection,
    // double click activates the row's entry (launcher: «Открыть»).
    signal selectedRequested()
    signal activateRequested()

    property alias text: rowText.text
    property bool selected: false

    // Escape hatch for the island's objectName contracts (the launcher's
    // tests address the cell text by name): `textObjectName: "gameRowText"`.
    property alias textObjectName: rowText.objectName

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""

    readonly property color fgColor: Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color accentColor: Tokens.token(islandTokens, "color.accent", "black")
    readonly property color accentFgColor: Tokens.token(islandTokens, "color.accent.fg", "white")

    implicitHeight: rowText.implicitHeight + 2 * Tokens.px(islandTokens, "space.xs", 4)
    color: row.selected ? row.accentColor : "transparent"

    Text {
        id: rowText
        anchors.left: parent.left
        anchors.leftMargin: Tokens.px(islandTokens, "space.sm", 8)
        anchors.right: parent.right
        anchors.rightMargin: Tokens.px(islandTokens, "space.sm", 8)
        anchors.verticalCenter: parent.verticalCenter
        font.pixelSize: Tokens.px(islandTokens, "font.size.md", 13)
        elide: Text.ElideRight
        color: row.selected ? row.accentFgColor : row.fgColor
    }

    MouseArea {
        anchors.fill: parent
        onClicked: row.selectedRequested()
        onDoubleClicked: row.activateRequested()
    }
}
