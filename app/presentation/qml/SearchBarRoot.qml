// Global-search QML island (R4 tasks 2.3/2.4).
//
// Context is intentionally limited to the existing SearchViewModel adapter
// and this island's palette. Search/services stay on the Python side.
import QtQuick
import QtQuick.Layouts
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "searchBarRoot"

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor:
        Tokens.token(root.islandTokens, "color.bg.surface", "white")
    readonly property color canvasColor:
        Tokens.token(root.islandTokens, "color.bg.canvas", "white")
    readonly property color borderColor:
        Tokens.token(root.islandTokens, "color.border", "lightgray")
    readonly property color primaryColor:
        Tokens.token(root.islandTokens, "color.fg.primary", "black")

    color: surfaceColor
    implicitWidth: 500
    implicitHeight: content.implicitHeight

    function syncQuery() {
        if (searchInput.text !== searchBarVm.query)
            searchInput.text = searchBarVm.query
    }

    // The result row's single action: jump to the hit (the VM emits
    // resultSelected and collapses the list). NRI-0017 task 2.2 (B3 sweep):
    // both row paths run through it — the single-click jump is the migrated
    // behavior, and the RowItem press path emits activateRequested, which
    // without a listener here was a silent no-op in the accessibility tree.
    function jumpToRow(index) {
        searchResultsList.currentIndex = index
        searchBarVm.select(index)
    }

    Connections {
        target: searchBarVm
        function onQueryChanged() { root.syncQuery() }
    }

    Component.onCompleted: root.syncQuery()

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Tokens.px(root.islandTokens, "space.xs", 4)
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            spacing: Tokens.px(root.islandTokens, "space.xs", 4)

            ThemeField {
                id: searchInput
                objectName: "searchInput"
                Layout.fillWidth: true
                placeholderText: "Поиск по всем сущностям (от 2 символов)..."
                // nri-0012 task 3.1 (usage-site name, design map): the typed
                // query lives in the tree's value slot — the name slot carries
                // the field's purpose.
                Accessible.name: "Поиск по всем сущностям"
                onTextChanged: searchBarVm.setQuery(text)
                onAccepted: searchBarVm.requestSearch()
            }

            ThemeButton {
                objectName: "searchButton"
                text: "Найти"
                onClicked: searchBarVm.requestSearch()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: searchResultsList.visible
                ? Math.min(searchResultsList.contentHeight + 2, 300)
                : 0
            color: root.canvasColor
            border.color: root.borderColor
            border.width: 1
            radius: Tokens.px(root.islandTokens, "radius.sm", 6)
            clip: true

            ListView {
                id: searchResultsList
                objectName: "searchResultsList"
                anchors.fill: parent
                anchors.margins: 1
                visible: searchBarVm.listVisible
                model: searchBarVm.rows
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                delegate: Loader {
                    id: rowLoader
                    required property int index
                    required property var modelData
                    width: searchResultsList.width
                    sourceComponent: modelData.kind === "sectionHeader"
                        ? sectionHeaderComponent
                        : modelData.kind === "result"
                            ? resultComponent
                            : noMatchComponent

                    property var rowData: modelData
                    property int rowIndex: index
                }

                Component {
                    id: sectionHeaderComponent
                    Rectangle {
                        objectName: "searchSectionHeader"
                        width: searchResultsList.width
                        height: headerText.implicitHeight
                            + 2 * Tokens.px(root.islandTokens, "space.xs", 4)
                        color: root.borderColor
                        enabled: false

                        Text {
                            id: headerText
                            objectName: "searchSectionHeaderText"
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.leftMargin: Tokens.px(root.islandTokens, "space.sm", 8)
                            anchors.rightMargin: anchors.leftMargin
                            anchors.verticalCenter: parent.verticalCenter
                            text: parent.parent.rowData.text
                            color: root.primaryColor
                            font.bold: true
                            font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                            elide: Text.ElideRight
                        }
                    }
                }

                Component {
                    id: resultComponent
                    RowItem {
                        objectName: "searchResultRow"
                        textObjectName: "searchResultText"
                        width: searchResultsList.width
                        text: parent.rowData.text
                        selected: searchResultsList.currentIndex === parent.rowIndex
                        onSelectedRequested: root.jumpToRow(parent.rowIndex)
                        onActivateRequested: root.jumpToRow(parent.rowIndex)
                    }
                }

                Component {
                    id: noMatchComponent
                    Rectangle {
                        objectName: "searchNoMatchRow"
                        width: searchResultsList.width
                        height: noMatchText.implicitHeight
                            + 2 * Tokens.px(root.islandTokens, "space.xs", 4)
                        color: "transparent"
                        enabled: false

                        HintText {
                            id: noMatchText
                            objectName: "searchNoMatchText"
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.leftMargin: Tokens.px(root.islandTokens, "space.sm", 8)
                            anchors.rightMargin: anchors.leftMargin
                            anchors.verticalCenter: parent.verticalCenter
                            text: parent.parent.rowData.text
                        }
                    }
                }
            }
        }
    }
}
