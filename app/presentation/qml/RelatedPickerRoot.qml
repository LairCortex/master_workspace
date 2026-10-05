// «Выберите <тип>» picker island (PR-020) — the QML half of the binding
// picker, replacing the widgets QListWidget whose virtual cells never reached
// the accessibility tree (live-аудит 2026-10-03: rows nameless, no action
// reached the selection — the same item-view hole PR-022 pinned for the desk).
//
// Context contract (the SheetFrame facade of related_picker_sheet.py):
//   * `relatedPickerVm` — RelatedPickerViewModel: the flat candidate rows
//     (roles `id`/`label`) bind through `relatedPickerVm.rows`, the
//     multi-selection through `relatedPickerVm.selectedIndex`; the sync slots
//     are `toggleRow` (the MultiSelection click moved to the VM) and
//     `selectRow` (the press selects before it activates). The commit is
//     facade-side (the section receives the candidates in order).
//   * `islandPalette` — the ONLY color/spacing source (library bridge, read
//     through tokens.js; off-skin the guarded seam degrades to named globals).
//
// Qt 6 Basic Buttons expose no «default» property — «ОК» is marked through
// `root.defaultButton`, the facade clicks it on Enter (the PR-029 bridge).
//
// Row contract (AGENTS accessibility tree contract): the role and the Press
// live inside RowItem; the usage site spells the name (the entity's visible
// name, modelData.label) and the hidden meaning of an activation here —
// «Выбирает сущность» (the fixed description map). A press selects the row
// and accepts the sheet (the migrated-OK idiom of SheetPresetRoot): the AT
// user reaches the section with the entity linked without any coordinate
// channel; the mouse keeps the retired list's semantics — a single click
// toggles only its own row, Enter/ОК commit the whole selection.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "relatedPickerRoot"

    implicitWidth: 360
    implicitHeight: 460

    // ── root contract to the facade (the migrated ОК/Отмена flows) ──────────
    signal okRequested()
    signal cancelRequested()

    // Enter-маркер (PR-029): the facade's Enter clicks this button.
    readonly property Item defaultButton: okButton

    // ── palette bridge (colors/spacing only ever come from here) ────────────
    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor: Tokens.token(root.islandTokens, "color.bg.surface", "white")
    readonly property color canvasColor: Tokens.token(root.islandTokens, "color.bg.canvas", "white")
    readonly property color borderColor: Tokens.token(root.islandTokens, "color.border", "lightgray")

    color: surfaceColor

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Tokens.px(root.islandTokens, "space.md", 16)
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        // The migrated multi-selection list: the unlinked candidates, every
        // row a library RowItem — ListItem role and Press inside the
        // component, the entity name the usage site's (design D4).
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: Tokens.px(root.islandTokens, "space.md", 16)
            radius: Tokens.px(root.islandTokens, "radius.sm", 6)
            color: root.canvasColor
            border.color: root.borderColor
            border.width: 1
            clip: true

            ListView {
                id: relatedPickerList
                objectName: "relatedPickerList"
                anchors.fill: parent
                anchors.margins: 1  // keep rows off the 1px border
                model: relatedPickerVm.rows
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                delegate: RowItem {
                    required property int index
                    required property var modelData
                    objectName: "relatedPickerRow"
                    width: relatedPickerList.width
                    height: implicitHeight
                    text: modelData.label
                    selected: relatedPickerVm.selectedIndex.includes(index)
                    accessibleDescription: "Выбирает сущность"
                    onSelectedRequested: relatedPickerVm.toggleRow(index)
                    onActivateRequested: {
                        relatedPickerVm.selectRow(index)
                        root.okRequested()
                    }
                }
            }
        }

        // Button row — the migrated QDialogButtonBox (ОК | Отмена); «ОК» rides
        // the accent fill and carries the Enter marker, «Отмена» cancels.
        RowLayout {
            Layout.fillWidth: true
            spacing: Tokens.px(root.islandTokens, "space.sm", 8)

            Item { Layout.fillWidth: true }

            ThemeButton {
                id: okButton
                objectName: "okButton"
                text: "ОК"
                accentBackground: true
                onClicked: root.okRequested()
            }
            ThemeButton {
                objectName: "cancelButton"
                text: "Отмена"
                onClicked: root.cancelRequested()
            }
        }
    }
}
