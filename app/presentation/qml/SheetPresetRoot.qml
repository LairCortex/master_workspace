// «Создать из пресета…» island (change port-sheet-list-preset-dialogs-qml-q3a,
// task 2.2; designs D3/D4/D5) — the QML half of the preset dialog, replacing
// the migrated QListWidget/QPlainTextEdit/QLineEdit chrome 1:1.
//
// Context contract (the QDialog facade of group 3 replicates the launcher's
// seam, design D1):
//   * `sheetPresetVm` — SheetPresetViewModel: the flat preset rows (roles
//                       `id`/`label`) bind through `sheetPresetVm.presetList`, the
//                       selection through `sheetPresetVm.selectedIndex`, the full license
//                       through `sheetPresetVm.licenseText`; the ONLY in-call is the sync
//                       slot `selectPreset(index)` (the migrated
//                       currentRowChanged seam), plus `setNameText` keeping
//                       the name field two-way — never an async entry (spec
//                       qml-shell «Контракт биндингов»). The D5 name-
//                       substitution rule is Python-side (design D3): QML
//                       never re-implements it, it just mirrors `sheetPresetVm.nameText`.
//                       The create flow (empty-name warning, create_from_preset
//                       under `run_locked`, `created(int)`, conflict) lives on
//                       the facade, fed by `createRequested`/
//                       `cancelRequested` below.
//   * `islandPalette` — the ONLY color/spacing source: the library bridge
//                       name, pushed by this dialog's facade from its own
//                       dialog-owned QmlPalette (the launcher/timeline
//                       contract — the name resolves engine-wide because
//                       widgets on one engine share its root context). Read
//                       through the library's tokens.js; off-skin the guarded
//                       resolveTokens seam degrades to the named Qt globals.
//
// Qt 6 Basic Buttons expose no «default» property — «Создать» is marked
// through `root.defaultButton`, the dialog wrapper clicks it on Enter (D5).
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "sheetPresetRoot"

    implicitWidth: 540
    implicitHeight: 500

    // ── root contract to the facade (the migrated OK/Cancel flows) ──────────
    signal createRequested()
    signal cancelRequested()

    // Enter-маркер (design D5): the wrapper's Enter key clicks this button.
    readonly property Item defaultButton: okButton

    // ── palette bridge (colors/spacing only ever come from here) ────────────
    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor: Tokens.token(root.islandTokens, "color.bg.surface", "white")
    readonly property color canvasColor: Tokens.token(root.islandTokens, "color.bg.canvas", "white")
    readonly property color fgColor: Tokens.token(root.islandTokens, "color.fg.primary", "black")
    readonly property color borderColor: Tokens.token(root.islandTokens, "color.border", "lightgray")

    color: surfaceColor

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Tokens.px(root.islandTokens, "space.md", 16)
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        // Captions — the migrated QLabels («Пресет:», «Лицензия:», «Имя:»),
        // chrome base font on the primary token.
        Text {
            text: "Пресет:"
            font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
            color: root.fgColor
            Layout.fillWidth: true
        }

        // The migrated preset_list: rows carry the preset titles exactly as
        // PresetCatalog().list() spells them (Python-side model, QML displays).
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
                id: presetListView
                objectName: "presetList"
                anchors.fill: parent
                anchors.margins: 1  // keep rows off the 1px border
                model: sheetPresetVm.presetList
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                // Selection change = the migrated currentRowChanged: one sync
                // `selectPreset` call, the VM then re-drives license + name
                // (D5 rule, Python-side).
                delegate: RowItem {
                    required property int index
                    required property var modelData
                    objectName: "presetRow"
                    textObjectName: "presetRowText"
                    width: presetListView.width
                    height: implicitHeight
                    text: modelData.label
                    selected: sheetPresetVm.selectedIndex === index
                    onSelectedRequested: sheetPresetVm.selectPreset(index)
                }
            }
        }

        Text {
            text: "Лицензия:"
            font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
            color: root.fgColor
            Layout.fillWidth: true
        }

        // The migrated read-only QPlainTextEdit (setFixedHeight(140)): the
        // FULL license text, selectable (selectByMouse = textCursorEnabled),
        // scrolled by the frame's ScrollView — the spec's «read-only
        // прокручиваемая лицензия».
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 140  // the migrated fixed height
            radius: Tokens.px(root.islandTokens, "radius.sm", 6)
            color: root.canvasColor
            border.color: root.borderColor
            border.width: 1
            clip: true

            ScrollView {
                anchors.fill: parent
                anchors.margins: 1
                clip: true
                contentWidth: availableWidth

                TextEdit {
                    id: licenseView
                    objectName: "licenseView"
                    width: parent.availableWidth
                    readOnly: true
                    selectByMouse: true
                    wrapMode: Text.WordWrap
                    text: sheetPresetVm.licenseText
                    color: root.fgColor
                    // The migrated dialog showed the license at the dialog's
                    // font size — never smaller than the captions (spec).
                    font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                }
            }
        }

        Text {
            text: "Имя:"
            font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
            color: root.fgColor
            Layout.fillWidth: true
        }

        // The migrated name_edit, two-way against `sheetPresetVm.nameText`: the binding
        // mirrors the VM's D5 substitutions into the field, `setNameText`
        // pushes the typed text back (the VM's same-text guard keeps the
        // round trip silent).
        ThemeField {
            id: nameField
            objectName: "nameField"
            Layout.fillWidth: true
            text: sheetPresetVm.nameText
            onTextChanged: sheetPresetVm.setNameText(text)
        }

        // Button row — the migrated QHBoxLayout (stretch, Создать, Отмена);
        // «Создать» rides the accent fill and carries the Enter marker.
        RowLayout {
            Layout.fillWidth: true
            spacing: Tokens.px(root.islandTokens, "space.sm", 8)

            Item { Layout.fillWidth: true }

            ThemeButton {
                id: okButton
                objectName: "okButton"
                text: "Создать"
                accentBackground: true
                onClicked: root.createRequested()
            }
            ThemeButton {
                objectName: "cancelButton"
                text: "Отмена"
                onClicked: root.cancelRequested()
            }
        }
    }
}
