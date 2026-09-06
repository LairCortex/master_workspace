// Event-types island (change port-llm-event-types-qml-r3, tasks 4.1/4.2) —
// the QML half of «Типы событий», replacing the retired widgets list/rename
// field/swatch row 1:1.
//
// Context contract (design D1/D2): island-scoped names only — the shared
// process engine's root context is written by every island, so this surface
// binds through `eventTypesVm` (EventTypesViewModel: rows, selection, name
// text, action flags and the sync `request*` entrances) and `islandPalette`
// (the library's token bridge, read through tokens.js). No service, no HTTP
// client, no `_run` and no coroutine reaches here: the facade answers the
// VM's request signals and owns every write and reload (spec qml-shell
// «Контекст типов изолирован»).
//
// Write-through (design D6): the row tap only selects; rename on finished
// edit, swatch tap, add, remove and ↑/↓ each send their request immediately.
// There is no Save button, no dirty state and no confirmation — «Закрыть»
// just accepts the dialog.
//
// The palette is closed: the eight `ThemeSwatch` samples are built by a
// `Repeater` over `eventTypesVm.paletteSize`, so neither the set nor the
// chart tokens are re-declared here (design D5); off-skin the library
// component degrades to its numbered gray sample on its own.
import QtQuick
import QtQuick.Layouts
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "eventTypesRoot"

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor: Tokens.token(root.islandTokens, "color.bg.surface", "white")
    readonly property color canvasColor: Tokens.token(root.islandTokens, "color.bg.canvas", "white")
    readonly property color borderColor: Tokens.token(root.islandTokens, "color.border", "lightgray")

    color: surfaceColor
    implicitWidth: 460
    implicitHeight: 320

    // The name field and the swatch row are written IMPERATIVELY from the VM
    // (not bound): the user's own typing and the library swatch's checked
    // state are inputs of those same properties, and a plain binding would be
    // dropped by the first interaction — after which the field would stop
    // following the selection. Both syncs are idempotent no-ops when the
    // island already shows the VM's state.
    function syncNameField() {
        if (nameField.text !== eventTypesVm.nameText)
            nameField.text = eventTypesVm.nameText
    }

    function syncSwatches() {
        for (var i = 0; i < swatchRepeater.count; i++) {
            var swatch = swatchRepeater.itemAt(i)
            if (swatch !== null)
                swatch.checked = eventTypesVm.selectedColorIndex === i + 1
        }
    }

    Connections {
        target: eventTypesVm
        function onNameTextChanged() { root.syncNameField() }
        function onSelectionChanged() { root.syncSwatches() }
    }

    Component.onCompleted: {
        root.syncNameField()
        root.syncSwatches()
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Tokens.px(root.islandTokens, "space.md", 16)
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        HintText {
            objectName: "typeHint"
            italic: true
            text: "Цвет — готовый образец палитры; удаление лишь отвязывает тип от событий"
            Layout.fillWidth: true
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Tokens.px(root.islandTokens, "space.sm", 8)

            // List frame: surface-in-canvas with the token border (the island
            // pattern — the ListView itself stays chromeless).
            Rectangle {
                Layout.fillHeight: true
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                radius: Tokens.px(root.islandTokens, "radius.sm", 6)
                color: root.canvasColor
                border.color: root.borderColor
                border.width: 1
                clip: true

                ListView {
                    id: typeListView
                    objectName: "typeList"
                    anchors.fill: parent
                    anchors.margins: 1  // keep rows off the 1px border
                    model: eventTypesVm.rows
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                    delegate: RowItem {
                        required property int index
                        required property var modelData
                        objectName: "typeRow"
                        textObjectName: "typeRowText"
                        width: typeListView.width
                        height: implicitHeight
                        text: modelData.name
                        selected: eventTypesVm.selectedId === modelData.id
                        onSelectedRequested: eventTypesVm.select(index)
                    }
                }
            }

            ColumnLayout {
                Layout.fillHeight: true
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                spacing: Tokens.px(root.islandTokens, "space.sm", 8)

                // Rename: the finished edit is the request (write-through).
                ThemeField {
                    id: nameField
                    objectName: "typeNameField"
                    Layout.fillWidth: true
                    placeholderText: "Название типа"
                    onTextChanged: eventTypesVm.setNameText(text)
                    onEditingFinished: eventTypesVm.requestRename()
                }

                // The closed palette: eight samples, no free-color control.
                Flow {
                    Layout.fillWidth: true
                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                    Repeater {
                        id: swatchRepeater
                        model: eventTypesVm.paletteSize

                        ThemeSwatch {
                            required property int index
                            objectName: "typeColorSwatch" + (index + 1)
                            colorIndex: index + 1
                            enabled: eventTypesVm.hasSelection
                            onClicked: eventTypesVm.requestRecolor(index + 1)
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                    ThemeButton {
                        objectName: "typeAddButton"
                        text: "Добавить"
                        onClicked: eventTypesVm.requestAdd()
                    }
                    ThemeButton {
                        objectName: "typeRemoveButton"
                        text: "Удалить"
                        enabled: eventTypesVm.canRemove
                        onClicked: eventTypesVm.requestRemove()
                    }
                    Item { Layout.fillWidth: true }
                    ThemeButton {
                        objectName: "typeUpButton"
                        text: "↑"
                        enabled: eventTypesVm.canMoveUp
                        onClicked: eventTypesVm.requestMove(-1)
                    }
                    ThemeButton {
                        objectName: "typeDownButton"
                        text: "↓"
                        enabled: eventTypesVm.canMoveDown
                        onClicked: eventTypesVm.requestMove(1)
                    }
                }

                Item { Layout.fillHeight: true }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            ThemeButton {
                objectName: "typeCloseButton"
                text: "Закрыть"
                onClicked: eventTypesVm.requestClose()
            }
        }
    }
}
