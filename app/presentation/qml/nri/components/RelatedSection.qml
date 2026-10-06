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
            // Lucide icon pass 2026-09-30: link/create/unlink are the same
            // gestures as the fill island's bind/unbind pair. «user-plus»
            // was NOT used for the character sections: the section model
            // (RelatedSectionState) carries no entity type — the type lives
            // only in the entity-card's outer row dict, so no one-line
            // condition inside this component could reach it.
            iconName: "link"
            onClicked: if (control.section) control.section.requestLink()
        }
        ThemeButton {
            objectName: control.objectPrefix + "CreateButton"
            text: "Создать нового"
            // The component owns the view (design claim 2026-10-06): the
            // related-create popup builds its sections with canCreate false
            // — the nested «Создать нового» signal has no receiver at depth
            // 1, and a button that silently does nothing must not be shown.
            // A section without state (gallery probe) keeps the entry.
            visible: !control.section || control.section.canCreate
            iconName: "plus"
            onClicked: if (control.section) control.section.requestCreate()
        }
        ThemeButton {
            objectName: control.objectPrefix + "UnlinkButton"
            text: "Отвязать"
            iconName: "unlink"
            enabled: control.section && control.section.selectedIndex >= 0
            onClicked: if (control.section) control.section.unlinkSelected()
        }
    }
}
