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
    // NRI-0018 task 5.3 (spec ui-layout-grid «Отступ содержимого листов
    // задан единым токеном»): the shared sheet margin (space.md — the
    // content column below insets by it) must be part of the strip the
    // facade fixes to this implicit height, exactly like the card and the
    // event sheet keep the token on all their edges; with the bare content
    // height a taller token would push the row band off the window's bottom.
    readonly property real contentInset:
        Tokens.px(root.islandTokens, "space.md", 16)
    implicitHeight: content.implicitHeight + 2 * contentInset

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

    // NRI-0021 task 3.2 (design Д4): the game's «now» VM is the one extra
    // context name of this island (searchBarVm stays purely the search VM).
    // Unit-built islands may hold no game value yet — then the context value
    // is null and the widget row stays hidden behind these guards.
    readonly property var nowVm: nowDateVm

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: root.contentInset
        spacing: 0

        // NRI-0021 task 3.2 (spec «Виджет „Сейчас: <дата>“ в главном окне»):
        // the game-date row above the search field, centered through the
        // library ThemeDateField (role Button and press live inside the
        // component; the usage site carries the name — here the caption
        // itself, design Д4). Activation emits through the VM to the Python
        // widgets bridge; no QML Popup is involved (spec qml-shell).
        RowLayout {
            objectName: "nowDateRow"
            Layout.fillWidth: true
            Layout.bottomMargin: Tokens.px(root.islandTokens, "space.xs", 4)
            spacing: 0

            Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }

            ThemeDateField {
                id: nowDateField
                objectName: "nowDateField"
                visible: root.nowVm !== null
                display: root.nowVm !== null ? root.nowVm.caption : ""
                worstCaseText:
                    root.nowVm !== null ? root.nowVm.worstCaseDisplay : ""
                Accessible.name: root.nowVm !== null ? root.nowVm.caption : ""
                onClicked: {
                    if (!root.nowVm)
                        return
                    const point = nowDateField.mapToItem(root, 0, 0)
                    root.nowVm.requestDatePopup(
                        point.x, point.y, nowDateField.width, nowDateField.height)
                }
            }

            Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }
        }

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
