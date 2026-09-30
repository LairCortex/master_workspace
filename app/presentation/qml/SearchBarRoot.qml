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

    // The result row's two gestures (NRI-0022 task 6.2, spec «Клик по
    // результату ведёт к цели и закрывает список»): the single left click
    // runs the full path to the hit, the double click asks for editing —
    // both emit through the VM, which collapses the list with the gesture.
    //
    // A real double click releases its FIRST click as a single click before
    // the double-click event arrives, so the jump waits out the platform's
    // double-click interval in ``singleClickHold``: an ``activateRequested``
    // during the hold cancels the jump and takes the row to the editor
    // instead. RowItem's accessibility Press emits activateRequested too
    // (the library's «press mirrors the double-click path» rule), so the
    // keyboard route opens the editor as well. The right button reaches no
    // handler at all (RowItem's MouseArea accepts the left button only).
    property int pendingJumpIndex: -1

    Timer {
        id: singleClickHold
        interval: searchBarVm.doubleClickIntervalMs
        onTriggered: {
            const index = root.pendingJumpIndex
            root.pendingJumpIndex = -1
            if (index >= 0)
                root.jumpToRow(index)
        }
    }

    function jumpToRow(index) {
        searchResultsList.currentIndex = index
        searchBarVm.select(index)
    }

    function holdJump(index) {
        root.pendingJumpIndex = index
        singleClickHold.restart()
    }

    function editRow(index) {
        root.pendingJumpIndex = -1
        singleClickHold.stop()
        searchResultsList.currentIndex = index
        searchBarVm.activate(index)
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
        // the game-date row above the search field, built on the library
        // ThemeDateField (role Button and press live inside the component;
        // the usage site carries the name — here the caption itself, design
        // Д4). Activation emits through the VM to the Python widgets bridge;
        // no QML Popup is involved (spec qml-shell).
        //
        // NRI-0023 group 12 (design Д14.5; the audit-A9 left alignment is
        // retired by the user request of 2026-09-30): the chip and the hour
        // selector stay ONE pair (the combo's space.xs left margin is the gap
        // between them) and the pair is horizontally CENTERED in the panel —
        // the two invisible fillWidth spacers keep the pair's middle on the
        // island's middle. Setting an hour grows the chip inside its worstCase
        // floor, which widens the pair symmetrically: the middle never moves.
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

            // NRI-0023 task 9.1 (spec «Виджет „Сейчас: <дата>“»): the optional
            // hour list beside the chip — «—» plus 0 … day_hours−1 of the
            // active calendar (the bounds and the index mapping live in the
            // VM, design Д4: no consumer hardcodes 24). A pick only asks the
            // VM; the wiring's service transaction decides, and the caption
            // grows the «…, HH:00» tail while every derived surface stays on
            // the day it was computed from (spec «Час меняет только
            // подпись»). ThemeComboBox carries its role inside the component,
            // the usage site names the trigger; the native drop-down window
            // is the documented tree limit ③ (never an island node).
            //
            // Group 12 (design Д14.2/Д14.3, audit H1/H2/A5/A7): the closed
            // control prints the VM's labelled display text («Час: —» — the
            // list rows stay bare numbers), keeps the chip's height (the
            // component's space.xs vertical padding) and a fixed width taken
            // from the calendar's worst label («Час: 23»), and the empty
            // value paints at the muted rank.
            ThemeComboBox {
                id: nowHourCombo
                objectName: "nowHourCombo"
                visible: root.nowVm !== null
                Layout.leftMargin: Tokens.px(root.islandTokens, "space.xs", 4)
                model: root.nowVm !== null ? root.nowVm.hourOptions : []
                currentIndex: root.nowVm !== null ? root.nowVm.selectedHourIndex : 0
                displayText: root.nowVm !== null ? root.nowVm.hourDisplay : ""
                worstCaseText:
                    root.nowVm !== null ? root.nowVm.worstCaseHourOption : ""
                valueIsPlaceholder:
                    root.nowVm !== null && root.nowVm.selectedHourIndex === 0
                Accessible.name: "Час сейчас"
                // Task 12.6 (A1 host half of design Д14.1): this island's
                // facade fixes the widget to the island's implicit height, so
                // the component's own pop-up could never grow to its full
                // list here — the hour rows leave for the widgets-bridge
                // window through the VM, the very route the date chip beside
                // this row already takes. Taller hosts (the event sheet) keep
                // the in-component pop-up untouched.
                externalPopup: true
                onPopupOpenRequested: {
                    if (!root.nowVm)
                        return
                    const point = nowHourCombo.mapToItem(root, 0, 0)
                    root.nowVm.requestHourPopup(
                        point.x, point.y, nowHourCombo.width, nowHourCombo.height)
                }
                onActivated: {
                    if (root.nowVm)
                        root.nowVm.requestHour(index)
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
                        onSelectedRequested: root.holdJump(parent.rowIndex)
                        onActivateRequested: root.editRow(parent.rowIndex)
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
