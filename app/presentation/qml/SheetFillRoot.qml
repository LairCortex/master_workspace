// Character-sheet fill window island (change port-character-sheet-canvas-qml-q3b,
// task 3.2; designs D1/D2/D9) — everything under the native «Правка» menu of
// the fill dialog: navigation rail | canvas (fill mode) | value panel |
// action row, replacing the widgets rail + FillPropertiesPanel 1:1.
//
// Context/injection contract (the QDialog facade wires exactly this):
//   * injection — ``vm`` (the fill ViewModel) arrives as the root's DECLARED
//     property via QQuickWidget.setInitialProperties (shared process engine,
//     global root context — the Q3a lesson); the canvas receives it as its
//     declared property. Rules (values, clamps, resolution) stay in the VM
//     (spec «Поля канваса идут из модели»);
//   * ``islandPalette`` / ``tooltipBridge`` — token bridge and native tooltip
//     shim (library/Q2.5a); the unthemed paper layer lives in SheetCanvas.qml;
//   * signals out — every session/popup flow the facade owns (D1):
//     ``saveRequested`` / ``bindRequested`` / ``unbindRequested`` (native
//     ``QInputDialog`` character picker stays on the facade) /
//     ``imagePickRequested(fieldId)`` (``QFileDialog`` + ImageStore ingest) /
//     ``dropdownRequested(fieldId, x, y)`` — the canvas' option-choice bridge
//     relayed unchanged: the facade shows the native ``QMenu`` in coordinates
//     mapped from the island and answers through ``vm.set_dropdown``;
//   * Enter marker — ``defaultButton`` («Сохранить»), clicked by the wrapper
//     when the island has not consumed Enter (inline editing owns the key).
//
// The value panel mirrors FillPropertiesPanel branch-for-branch: the current
// display value is the field model's content role (the domain resolve_display
// through the VM — no second resolution here); edits land on the same sync
// entrances the widgets panel used (set_text/set_number/set_dropdown/
// toggle_checkbox/clear_image), refuses re-read the VM. The navigation rail
// mirrors the widgets navigation_only mode: names, selection, scroll — no
// rename/add/remove chrome. Read-only (the master view) is the VM's single
// flag: the model's disabled role gates the canvas, ``readOnly`` gates this
// panel and the action buttons.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "sheetFillRoot"

    implicitWidth: 1100
    implicitHeight: 800

    // ── injected VM (see the header) ────────────────────────────────────────
    property var vm: null
    readonly property bool vmReady: vm !== null && vm !== undefined
    readonly property bool readOnly: vmReady && vm.readOnly

    property var pageNames: vmReady ? vm.page_names() : []
    readonly property int pageCount:
        (vmReady && vm.pagesLayout && vm.pagesLayout.count) ? vm.pagesLayout.count : 0
    readonly property int currentPage: vmReady ? vm.currentPage : 0

    // Enter marker: the wrapper's Enter click target (design D1).
    readonly property Item defaultButton: saveButton

    // The migrated _sync_bind_buttons channel (facade → QML): the bind state
    // has no VM notify, so the facade re-states it after every load/bind flow.
    property bool characterBound: false

    // Session/popup flows owned by the facade (D1).
    signal saveRequested()
    signal bindRequested()
    signal unbindRequested()
    signal imagePickRequested(string fieldId)
    // the canvas' native-QMenu bridge, relayed unchanged (scene coordinates —
    // the facade maps them through the QQuickWidget like the old globalPosition)
    signal dropdownRequested(string fieldId, real x, real y)

    // ── tokens (chrome colors come from the bridge only) ────────────────────
    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor:
        Tokens.token(islandTokens, "color.bg.surface", "white")
    readonly property color canvasColor:
        Tokens.token(islandTokens, "color.bg.canvas", "white")
    readonly property color fgColor:
        Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color borderColor:
        Tokens.token(islandTokens, "color.border", "lightgray")

    color: surfaceColor

    onVmChanged: refreshPages()
    function refreshPages() {
        pageNames = vmReady ? vm.page_names() : []
    }

    Connections {
        target: root.vmReady ? root.vm : null
        function onPages_changed() { root.refreshPages(); root.panelTick += 1 }
        function onTemplate_changed() { root.panelTick += 1 }
    }

    // ───────────────────────────── layout ───────────────────────────────────
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Tokens.px(root.islandTokens, "space.md")
        spacing: Tokens.px(root.islandTokens, "space.sm")

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Tokens.px(root.islandTokens, "space.sm")

            // ── navigation-only page rail (the widgets navigation_only mode) ──
            // Sized plain Rectangle as the row's fixed column: a layout object
            // with attached widths steals the fill space from the canvas
            // (QQuickLayouts, found by the 3.3 dialog e2e).
            Rectangle {
                color: "transparent"
                Layout.preferredWidth: 160
                Layout.minimumWidth: 160
                Layout.fillHeight: true

                ColumnLayout {
                anchors.fill: parent

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: Tokens.px(root.islandTokens, "radius.sm")
                    color: root.canvasColor
                    border.color: root.borderColor
                    border.width: 1
                    clip: true

                    ListView {
                        id: pageListView
                        objectName: "pageListView"
                        anchors.fill: parent
                        anchors.margins: 1
                        model: root.pageNames
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds

                        delegate: RowItem {
                            required property int index
                            required property var modelData
                            objectName: "railPageRow"
                            textObjectName: "railPageText"
                            width: pageListView.width
                            height: implicitHeight
                            text: String(modelData)
                            selected: root.currentPage === index
                            onSelectedRequested: {
                                root.vm.set_current_page(index)
                                sheetCanvas.scrollToPage(index)
                            }
                        }
                    }
                }
                }
            }

            // ── the canvas island (group 2), fill mode ───────────────────────
            SheetCanvas {
                id: sheetCanvas
                objectName: "sheetFillCanvas"
                Layout.fillWidth: true
                Layout.fillHeight: true
                vm: root.vm
                mode: "fill"
                // both native-bridge flows relay to the facade unchanged
                onImageFileRequested: (fieldId) => root.imagePickRequested(fieldId)
                onDropdownRequested: (fieldId, x, y) =>
                    root.dropdownRequested(fieldId, x, y)
            }

            // ── value panel (FillPropertiesPanel port, D9) ───────────────────
            Rectangle {
                Layout.preferredWidth: 260
                Layout.minimumWidth: 260
                Layout.fillHeight: true
                color: "transparent"
                enabled: !root.readOnly

                ColumnLayout {
                    id: fillPanel
                    objectName: "fillPropertiesPanel"
                    anchors.fill: parent
                    spacing: root.gapSm

                    Text {
                        text: "Значение"
                        color: root.fgColor
                        font.pixelSize:
                            Tokens.px(root.islandTokens, "font.size.md", 13)
                        font.bold: true
                    }
                    Text {
                        id: valueHint
                        objectName: "fillValueHint"
                        Layout.fillWidth: true
                        visible: root.panelRow === null
                        text: "Выберите поле"
                        color: root.fgColor
                        font.pixelSize:
                            Tokens.px(root.islandTokens, "font.size.md", 13)
                    }

                    // text / number — the widgets single line edit; commits on
                    // finishing, a VM refusal re-reads the stored display
                    ThemeField {
                        id: textInput
                        objectName: "fillTextInput"
                        visible: root.rowType === "text" || root.rowType === "number"
                        Layout.fillWidth: true
                        Binding {
                            when: !textInput.activeFocus
                            target: textInput
                            property: "text"
                            value: root.panelRow ? root.panelRow.content : ""
                        }
                        onEditingFinished: root.commitLine(text)
                    }

                    // multiline — committed on focus out (the old eventFilter)
                    TextArea {
                        id: textareaInput
                        objectName: "fillTextarea"
                        visible: root.rowType === "textarea"
                        Layout.fillWidth: true
                        Layout.minimumHeight: 80
                        color: root.fgColor
                        background: Rectangle {
                            color: root.canvasColor
                            border.color: activeFocus ? root.fgColor
                                                      : root.borderColor
                            border.width: 1
                        }
                        Binding {
                            when: !textareaInput.activeFocus
                            target: textareaInput
                            property: "text"
                            value: root.panelRow ? root.panelRow.content : ""
                        }
                        onActiveFocusChanged: {
                            if (!activeFocus && root.rowType === "textarea")
                                root.vm.set_text(root.panelFid, text)
                        }
                    }

                    // checkbox — the widgets QCheckBox; edits only differ from
                    // the stored display (the old _syncing guard's meaning)
                    ThemeCheckBox {
                        id: checkboxToggle
                        objectName: "fillCheckbox"
                        visible: root.rowType === "checkbox"
                        text: "Вкл."
                        checked: root.panelRow ? root.panelRow.content === "true"
                                               : false
                        onToggled: {
                            var current = root.panelRow
                                          && root.panelRow.content === "true"
                            if (current !== checked)
                                root.vm.toggle_checkbox(root.panelFid)
                        }
                    }

                    // dropdown — the widgets QComboBox (the canvas click-path
                    // stays a native QMenu on the facade; the panel editor may
                    // use the library combo, same as the design panel)
                    ThemeComboBox {
                        id: dropdownValue
                        objectName: "fillDropdown"
                        visible: root.rowType === "dropdown"
                        Layout.fillWidth: true
                        model: root.displayedOptions
                        // ComboBox.currentText is read-only — mirror by index
                        // (the migrated setCurrentText direction of travel)
                        Binding {
                            when: !dropdownValue.popup.visible
                            target: dropdownValue
                            property: "currentIndex"
                            value: {
                                root.reReadTick
                                var options = root.displayedOptions
                                var current = root.panelRow
                                              ? root.panelRow.content : ""
                                return Math.max(0, options.indexOf(current))
                            }
                        }
                        onActivated: (index) => {
                            if (!root.vm.set_dropdown(root.panelFid, currentText))
                                root.reReadTick += 1   // refused: reRead re-shows
                        }
                    }

                    // image — both buttons of the old panel; the pick goes to
                    // the facade (QFileDialog + ImageStore pipeline, D6)
                    RowLayout {
                        visible: root.rowType === "image"
                        spacing: root.gapSm
                        ThemeButton {
                            objectName: "fillImagePickButton"
                            Layout.fillWidth: true
                            text: "Выбрать…"
                            onClicked: root.imagePickRequested(root.panelFid)
                        }
                        ThemeButton {
                            objectName: "fillImageClearButton"
                            Layout.fillWidth: true
                            text: "Убрать"
                            onClicked: root.vm.clear_image(root.panelFid)
                        }
                    }

                    Item { Layout.fillHeight: true }   // old addStretch
                }
            }
        }

        // Bottom actions (the migrated chrome row).
        RowLayout {
            Layout.fillWidth: true
            spacing: Tokens.px(root.islandTokens, "space.sm")
            ThemeButton {
                objectName: "bindButton"
                text: "Привязать…"
                visible: !root.readOnly
                onClicked: root.bindRequested()
            }
            ThemeButton {
                objectName: "unbindButton"
                text: "Отвязать"
                visible: !root.readOnly
                // the migrated _sync_bind_buttons: the facade pushes the bind
                // state after load/bind/unbind (the VM fires no bind signal)
                enabled: root.characterBound
                onClicked: root.unbindRequested()
            }
            Item { Layout.fillWidth: true }
            ThemeButton {
                id: saveButton
                objectName: "saveButton"
                text: "Сохранить"
                visible: !root.readOnly
                accentBackground: true
                onClicked: root.saveRequested()
            }
        }
    }

    // ── panel state (the selected field's projection, D4) ───────────────────
    property int reReadTick: 0
    property int panelTick: 0
    Connections {
        target: root.vmReady ? root.vm : null
        function onSelection_changed(_fid) { root.panelTick += 1 }
        function onValues_changed() { root.panelTick += 1 }
        function onField_content_changed(_fid) { root.panelTick += 1 }
        function onField_props_changed(_fid) { root.panelTick += 1 }
        function onInline_changed(_fid) { root.panelTick += 1 }
        function onHistory_changed() { root.panelTick += 1 }
    }

    function liveFid() {
        if (!vmReady || !vm.selectedIds || vm.selectedIds.length === 0)
            return ""
        return String(vm.selectedIds[0])
    }
    readonly property string panelFid: liveFid()

    property var panelRow: computePanelRow()
    function computePanelRow() {
        panelTick                             // the recompute dependency
        reReadTick
        if (!vmReady)
            return null
        var fid = liveFid()
        if (fid === "")
            return null
        return sheetCanvas.rowById(fid)
    }
    onPanelTickChanged: panelRow = computePanelRow()
    onReReadTickChanged: panelRow = computePanelRow()

    readonly property string rowType: {
        var type = panelRow ? panelRow.type : ""
        // labels and decoration store no character value (old _refresh guard)
        if (type === "label" || type === "rect" || type === "line")
            return ""
        return type
    }

    // dropdown options with the current value prepended when it is outside
    // the list (the migrated QComboBox rebuild rules)
    readonly property var panelProps: {
        panelTick
        if (!vmReady || panelFid === "")
            return ({})
        return vm.field_props(panelFid)
    }
    readonly property var displayedOptions: {
        var options = panelProps.options ? panelProps.options : []
        var current = panelRow ? panelRow.content : ""
        if (current !== "" && options.indexOf(current) < 0)
            return [current].concat(options)
        var seen = []
        for (var i = 0; i < options.length; i += 1)
            if (seen.indexOf(options[i]) < 0)
                seen.push(options[i])
        return seen
    }

    // The line edit serves both migrated branches: NUMBER goes through
    // set_number (bounds-checked in the VM), TEXT through set_text; either
    // way a refusal re-reads the stored display value.
    function commitLine(text) {
        if (panelRow === null || rowType === "")
            return
        var accepted = rowType === "number" ? vm.set_number(panelFid, text)
                                            : vm.set_text(panelFid, text)
        if (accepted === false)
            reReadTick += 1
    }

    readonly property real gapSm: Tokens.px(islandTokens, "space.sm")
}
