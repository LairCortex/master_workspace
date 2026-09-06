import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "tokens.js" as Tokens

ColumnLayout {
    id: control

    property var section: null
    property string objectPrefix: "related"

    spacing: Tokens.px(
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null),
        "space.xs",
        4
    )

    ListView {
        id: relatedList
        objectName: control.objectPrefix + "List"
        Layout.fillWidth: true
        Layout.fillHeight: true
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
