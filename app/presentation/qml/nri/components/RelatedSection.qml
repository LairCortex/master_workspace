import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "tokens.js" as Tokens

ColumnLayout {
    id: control

    property var section: null
    property string objectPrefix: "related"

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""

    spacing: Tokens.px(control.islandTokens, "space.xs", 4)

    // The pane the migrated QTabWidget drew: a framed field that ties the rows
    // to the selected tab (the tab strip itself carries no chrome). Buttons
    // stay outside it, as they sat under the widget's group box.
    //
    // Off-skin (design D7) the frame collapses — "transparent" is a named Qt
    // global, so nothing is painted and no color is invented.
    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        radius: Tokens.px(control.islandTokens, "radius.sm", 6)
        color: Tokens.token(control.islandTokens, "color.bg.canvas", "transparent")
        border.width: control.skinned ? 1 : 0
        border.color: Tokens.token(control.islandTokens, "color.border", "transparent")
        clip: true

        ListView {
            id: relatedList
            objectName: control.objectPrefix + "List"
            anchors.fill: parent
            anchors.margins: 1  // keep rows off the 1px border
            clip: true
            model: control.section ? control.section.rows : []
            currentIndex: control.section ? control.section.selectedIndex : -1
            boundsBehavior: Flickable.StopAtBounds

            delegate: RowItem {
                objectName: control.objectPrefix + "Row"
                width: relatedList.width
                text: modelData.name
                selected: index === relatedList.currentIndex
                onSelectedRequested: {
                    relatedList.currentIndex = index
                    if (control.section)
                        control.section.select(index)
                }
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true

        ThemeButton {
            objectName: control.objectPrefix + "LinkButton"
            text: "Привязать существующего"
            onClicked: if (control.section) control.section.requestLink()
        }
        ThemeButton {
            objectName: control.objectPrefix + "CreateButton"
            text: "Создать нового"
            onClicked: if (control.section) control.section.requestCreate()
        }
        ThemeButton {
            objectName: control.objectPrefix + "UnlinkButton"
            text: "Отвязать"
            enabled: control.section && control.section.selectedIndex >= 0
            onClicked: if (control.section) control.section.unlinkSelected()
        }
    }
}
