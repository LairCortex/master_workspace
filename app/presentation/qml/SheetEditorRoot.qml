// Sheet editor window island (change port-character-sheet-canvas-qml-q3b,
// task 3.1; designs D1/D9) — the whole content INCLUDING the «Правка» action
// row (nri-0017 task 3.1, finding B2): action row | palette | page rail |
// canvas | property panel | bottom row, replacing palette.py / page_rail.py /
// properties_panel.py 1:1. The commands left the QDialog's QMenuBar (which
// macOS projects nowhere) for this named row of buttons; the dialog keeps the
// hotkeys on the very handlers these signals are wired to.
//
// Context/injection contract (the QDialog facade wires exactly this):
//   * injection — ``vm`` (the design ViewModel) arrives as the root's
//     DECLARED property via QQuickWidget.setInitialProperties (two sheet
//     windows share the one process engine whose root context is global —
//     the Q3a lesson pinned in list_dialog.py); the canvas gets it passed
//     down as its declared property. The island only touches sync slots /
//     notify properties of the VM — the geometry/clamp/snap rules stay in
//     the VM (spec «Поля канваса идут из модели»);
//   * ``islandPalette`` / ``tooltipBridge`` — the token bridge and the
//     native tooltip shim (library/Q2.5a contracts; chrome reads tokens
//     only — the unthemed paper layer lives in SheetCanvas.qml, D8);
//   * signals out — every flow that touches the session or opens a NATIVE
//     popup (D1): ``saveRequested`` / ``exportPdfRequested`` /
//     ``imagePickRequested(fieldId)`` / ``pageRemoveRequested(index)``
//     (the delete-page confirm is a facade QMessageBox), plus the «Правка»
//     row ``undoRequested`` / ``redoRequested`` / ``copyRequested`` /
//     ``pasteActionRequested`` / ``duplicateRequested`` — the facade reruns
//     the same VM entrances its hotkey QActions call. The native QMenu
//     for a fill-mode dropdown is not this island's (design mode has no
//     dropdown menu); the canvas bridges are still relayed unchanged.
//   * Python → QML — ``pasteRequested(page)`` is EMITTED by the facade to
//     ask for the paste position: the handler parks the canvas'
//     ``visibleCenter(page)`` into ``pasteCenterOut`` right there (QML
//     functions are not Python-callable; the timeline's root-signal trick).
//   * Enter marker — ``defaultButton`` («Сохранить»); the wrapper clicks it
//     on Enter when the island has not consumed Enter (inline editing owns
//     the key, design D1).
//
// The tool catalog below mirrors the VM TOOL_* constants (the palette was
// always a UI catalog; the tool→type rule stays the VM's, the canvas asks
// ``vm.tool_field_type()``). Page names come from ``vm.page_names()``, the
// tape geometry from ``vm.pagesLayout`` — QML re-derives nothing.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "sheetEditorRoot"

    implicitWidth: 1280
    implicitHeight: 800

    // ── injected VM (see the header) ────────────────────────────────────────
    property var vm: null
    readonly property bool vmReady: vm !== null && vm !== undefined

    // The page/field structure and selection the rail/panel mirror.
    property var pageNames: vmReady ? vm.page_names() : []
    readonly property int pageCount:
        (vmReady && vm.pagesLayout && vm.pagesLayout.count) ? vm.pagesLayout.count : 0
    readonly property int currentPage: vmReady ? vm.currentPage : 0

    // Enter marker: the wrapper's Enter click target (design D1).
    readonly property Item defaultButton: saveButton

    // Paste-position bridge: the facade emits pasteRequested(page); the
    // canvas' own visibleCenter answers into pasteCenterOut (point).
    signal pasteRequested(int page)
    property point pasteCenterOut: Qt.point(-1, -1)
    onPasteRequested: (page) => { pasteCenterOut = sheetCanvas.visibleCenter(page) }

    // Native-popup / session flows owned by the facade (D1).
    signal saveRequested()
    signal exportPdfRequested()
    signal imagePickRequested(string fieldId)
    signal pageRemoveRequested(int index)
    // The «Правка» row (nri-0017 task 3.1, design F2): the facade wires each
    // of these to the SAME handler its hotkey QAction calls — asking, never
    // reimplementing (one command layer, the VM plus this window's bridge).
    signal undoRequested()
    signal redoRequested()
    signal copyRequested()
    signal pasteActionRequested()
    signal duplicateRequested()

    // ── tokens (chrome colors come from the bridge only) ────────────────────
    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor:
        Tokens.token(islandTokens, "color.bg.surface", "white")
    readonly property color canvasColor:
        Tokens.token(islandTokens, "color.bg.canvas", "white")
    readonly property color fgColor:
        Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color mutedColor:
        Tokens.token(islandTokens, "color.fg.muted", "gray")
    readonly property color borderColor:
        Tokens.token(islandTokens, "color.border", "lightgray")
    readonly property color accentColor:
        Tokens.token(islandTokens, "color.accent", "black")
    readonly property real gap: Tokens.px(islandTokens, "space.md")
    readonly property real gapSm: Tokens.px(islandTokens, "space.sm")

    color: surfaceColor

    onVmChanged: {
        refreshPages()
        refreshProps()
    }
    function refreshPages() {
        pageNames = vmReady ? vm.page_names() : []
    }

    // Re-read rails/panels after every structural VM moment.
    Connections {
        target: root.vmReady ? root.vm : null
        function onPages_changed() { root.refreshPages() }
        function onTemplate_changed() { root.refreshPages(); root.panelTick += 1 }
    }

    // ───────────────────────────── layout ───────────────────────────────────
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: root.gap
        spacing: root.gapSm

        // «Правка» as the window's top chrome row (nri-0017 F2, finding B2):
        // five named buttons reachable by mouse, keyboard AND the tree (the
        // text captions are their accessibility names — stock controls, no
        // re-annotation), the hotkeys of the facade staying the second entry
        // to the very same commands. Enabled states mirror the VM, exactly as
        // the retired menu greyed its items.
        RowLayout {
            id: editActionsRow
            objectName: "editActionsRow"
            Layout.fillWidth: true
            spacing: root.gapSm
            // the copy/duplicate gate (the selection rule of the retired menu)
            readonly property bool hasSelection:
                root.vmReady && root.vm.selectedIds.length > 0

            ThemeButton {
                objectName: "editUndoButton"
                text: "Отменить"
                enabled: root.vmReady && root.vm.canUndo
                onClicked: root.undoRequested()
            }
            ThemeButton {
                objectName: "editRedoButton"
                text: "Повторить"
                enabled: root.vmReady && root.vm.canRedo
                onClicked: root.redoRequested()
            }
            ThemeButton {
                objectName: "editCopyButton"
                text: "Копировать"
                enabled: editActionsRow.hasSelection
                onClicked: root.copyRequested()
            }
            ThemeButton {
                objectName: "editPasteButton"
                text: "Вставить"
                enabled: root.vmReady && root.vm.hasClipboard
                onClicked: root.pasteActionRequested()
            }
            ThemeButton {
                objectName: "editDuplicateButton"
                text: "Дублировать"
                enabled: editActionsRow.hasSelection
                onClicked: root.duplicateRequested()
            }
            Item { Layout.fillWidth: true }
        }

        // Top row — the migrated «Ориентация: [combo]» strip (A-playable D4:
        // one orientation per template, the combo mirrors the VM and pushes
        // switches; the clamp of out-of-fit fields happens in the VM).
        RowLayout {
            Layout.fillWidth: true
            spacing: root.gapSm
            Text {
                text: "Ориентация:"
                color: root.fgColor
                font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
            }
            ThemeComboBox {
                id: orientationCombo
                objectName: "orientationCombo"
                Layout.preferredWidth: 160
                model: ["Книжная", "Альбомная"]
                // nri-0012 task 3.3 (usage-site name, design map): the combo
                // shows data values only — the name slot carries the purpose.
                Accessible.name: "Ориентация страницы"
                // the template owns the orientation (D4); pagesLayout mirrors
                // it into the combo (the migrated _sync_orientation direction,
                // push only while the popup is not open)
                readonly property string vmOrientation:
                    (root.vmReady && root.pageCount !== 0
                     && vm.pagesLayout && vm.pagesLayout.orientation)
                        ? vm.pagesLayout.orientation : "portrait"
                Binding {
                    when: !orientationCombo.popup.visible
                    target: orientationCombo
                    property: "currentIndex"
                    value: orientationCombo.vmOrientation === "landscape" ? 1 : 0
                }
                onCurrentIndexChanged: {
                    // local reads only — a dependent bound property could
                    // still hold its pre-change value inside this handler
                    if (!root.vmReady || root.pageCount === 0)
                        return
                    var want = currentIndex === 1 ? "landscape" : "portrait"
                    var have = vm.pagesLayout && vm.pagesLayout.orientation
                               ? vm.pagesLayout.orientation : "portrait"
                    if (want !== have)
                        vm.set_orientation(want)
                }
            }
            Item { Layout.fillWidth: true }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: root.gapSm

            // ── palette (palette.py port, D7: pointer + 9 types) ────────────
            // A plain sized Rectangle owns the row-attached width: a *layout*
            // sibling with attached Layout.preferredWidth swallows the fill space
            // and the zero-implicit canvas would collapse to ~4px (QQuickLayouts
            // behaviour, found by the 3.3 dialog e2e).
            Rectangle {
                color: "transparent"
                Layout.preferredWidth: 120
                Layout.minimumWidth: 120
                Layout.fillHeight: true

                ColumnLayout {
                anchors.fill: parent
                spacing: root.gapSm

                Repeater {
                    model: [
                        {tool: "pointer", label: "Указатель", name: "paletteTool-pointer"},
                        {tool: "place_label", label: "Подпись", name: "paletteTool-label"},
                        {tool: "place_text", label: "Поле", name: "paletteTool-text"},
                        {tool: "place_textarea", label: "Область",
                         name: "paletteTool-textarea"},
                        {tool: "place_checkbox", label: "Чекбокс",
                         name: "paletteTool-checkbox"},
                        {tool: "place_number", label: "Число", name: "paletteTool-number"},
                        {tool: "place_dropdown", label: "Список",
                         name: "paletteTool-dropdown"},
                        {tool: "place_image", label: "Картинка", name: "paletteTool-image"},
                        {tool: "place_rect", label: "Рамка", name: "paletteTool-rect"},
                        {tool: "place_line", label: "Линия", name: "paletteTool-line"}
                    ]
                    delegate: ThemeButton {
                        id: toolButton
                        required property var modelData
                        objectName: modelData.name
                        Layout.fillWidth: true
                        Layout.minimumHeight: 32
                        text: modelData.label
                        checkable: true
                        // one-shot placement resets the tool to the pointer
                        // in the VM; the exclusive look mirrors vm.currentTool
                        checked: root.vmReady && root.vm.currentTool === modelData.tool
                        onClicked: root.vm.set_tool(modelData.tool)
                        Nri.tooltip: "Инструмент: " + modelData.label.toLowerCase()
                        HoverHandler {
                            onHoveredChanged: tooltipReported(
                                toolButton.Nri.tooltip, hovered)
                        }
                        // The active-tool bar (token color, library pattern):
                        // QToolButton's checked highlight ported to skin-only.
                        Rectangle {
                            visible: parent.checked
                            width: 3
                            height: parent.height
                            color: root.accentColor
                        }
                    }
                }

                Item { Layout.fillHeight: true }            // old addStretch
                }
            }

            // ── page rail (page_rail.py port, A-playable D7) ────────────────
            Rectangle {
                color: "transparent"
                Layout.preferredWidth: 160
                Layout.minimumWidth: 160
                Layout.fillHeight: true

                ColumnLayout {
                anchors.fill: parent
                spacing: root.gapSm

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

                        delegate: Item {
                            id: railDelegate
                            required property int index
                            required property var modelData
                            width: pageListView.width
                            height: railRow.visible ? railRow.height
                                                    : railRenameField.height
                            property bool editing: false
                            property string name: String(modelData)

                            RowItem {
                                id: railRow
                                objectName: "railPageRow"
                                visible: !railDelegate.editing
                                anchors.fill: parent
                                textObjectName: "railPageText"
                                text: railDelegate.name
                                selected: root.currentPage === index
                                onSelectedRequested: {
                                    if (railDelegate.editing)
                                        return                  // old _renaming guard
                                    root.vm.set_current_page(index)
                                    sheetCanvas.scrollToPage(index)
                                }
                                // double-click: inline rename (old
                                // DoubleClicked edit trigger)
                                onActivateRequested: {
                                    railDelegate.editing = true
                                    railRenameField.text = railDelegate.name
                                    railRenameField.forceActiveFocus()
                                    railRenameField.select(0, railDelegate.name.length)
                                }
                            }

                            ThemeField {
                                id: railRenameField
                                objectName: "railPageRenameField"
                                visible: railDelegate.editing
                                anchors.fill: parent
                                // nri-0012 task 3.3: the inline rename editor
                                // of a rail page (label-less by design).
                                Accessible.name: "Переименование страницы"
                                onAccepted: commit()
                                Keys.onEscapePressed: (event) => {
                                    // Esc reverts to the stored name (old
                                    // delegate revert)
                                    railDelegate.editing = false
                                    event.accepted = true
                                }
                                function commit() {
                                    if (!railDelegate.editing)
                                        return
                                    var text = railRenameField.text
                                    railDelegate.editing = false
                                    // last statement — a successful rename
                                    // rebuilds the ListView synchronously (the
                                    // VM's pages_changed re-feeds the model),
                                    // touching this delegate's context after it
                                    // would read a torn-down scope; the rebuilt
                                    // row re-reads the name from the model, a
                                    // refusal (empty name) keeps the stored one
                                    if (text !== railDelegate.name)
                                        root.vm.rename_page(railDelegate.index, text)
                                }
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.minimumHeight: 26
                    spacing: root.gapSm
                    // NRI-0018 task 1.3: the rail glyphs are library squares
                    // — no Layout size here (the component owns the gauge).
                    ThemeIconButton {
                        objectName: "railUpButton"
                        text: "↑"
                        // nri-0012 task 3.3: glyph-only button — the name is
                        // the tooltip's action word (design map).
                        Accessible.name: "Вверх"
                        enabled: root.pageCount > 1 && root.currentPage > 0
                        Nri.tooltip: "Вверх"
                        onClicked: root.vm.move_page(root.currentPage,
                                                     root.currentPage - 1)
                    }
                    ThemeIconButton {
                        objectName: "railDownButton"
                        text: "↓"
                        Accessible.name: "Вниз"
                        Nri.tooltip: "Вниз"
                        enabled: root.pageCount > 1
                                 && root.currentPage < root.pageCount - 1
                        onClicked: root.vm.move_page(root.currentPage,
                                                     root.currentPage + 1)
                    }
                    ThemeIconButton {
                        objectName: "railDeleteButton"
                        text: "−"
                        Accessible.name: "Удалить страницу"
                        Nri.tooltip: "Удалить страницу"
                        enabled: root.pageCount > 1
                        // the confirm (page has fields) is a native QMessageBox
                        // on the facade — the rail only asks (D1)
                        onClicked: root.pageRemoveRequested(root.currentPage)
                    }
                    ThemeIconButton {
                        objectName: "railAddButton"
                        text: "+"
                        Accessible.name: "Добавить страницу"
                        Nri.tooltip: "Добавить страницу после текущей"
                        enabled: root.pageCount > 0
                        onClicked: root.vm.add_page()
                    }
                }
                }
            }

            // ── the canvas island (group 2), design mode ────────────────────
            SheetCanvas {
                id: sheetCanvas
                objectName: "sheetEditorCanvas"
                Layout.fillWidth: true
                Layout.fillHeight: true
                vm: root.vm
                mode: "design"
                // picture double-click hands the file pick to the facade
                // (QFileDialog, ImageStore ingest — the old panel/canvas pair)
                onImageFileRequested: (fieldId) => root.imagePickRequested(fieldId)
            }

            // ── property panel (properties_panel.py port) ───────────────────
            Rectangle {
                Layout.preferredWidth: 260
                Layout.minimumWidth: 260
                Layout.fillHeight: true
                color: "transparent"

                ScrollView {
                    id: propertiesScroll
                    anchors.fill: parent
                    contentWidth: availableWidth
                    clip: true

                    ColumnLayout {
                        id: propertiesPanel
                        objectName: "propertiesPanel"
                        width: propertiesScroll.availableWidth
                        spacing: root.gapSm

                        // ── panel-wide edits ────────────────────────────────
                        ThemeCheckBox {
                            objectName: "snapCheck"
                            text: "Привязка к сетке"
                            enabled: root.vmReady
                            checked: root.vmReady && root.vm.snapOn
                            onToggled: root.vm.set_snap_enabled(checked)
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: root.gapSm
                            ThemeButton {
                                objectName: "bringFrontButton"
                                Layout.fillWidth: true
                                text: "На передний план"
                                enabled: root.panelSelected
                                onClicked: root.vm.bring_to_front()
                            }
                            ThemeButton {
                                objectName: "sendBackButton"
                                Layout.fillWidth: true
                                text: "На задний план"
                                enabled: root.panelSelected
                                onClicked: root.vm.send_to_back()
                            }
                        }

                        Text {
                            text: "Свойства:"
                            color: root.fgColor
                            font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                            font.bold: true
                        }

                        // The selected field's projection (D4 — the VM is the
                        // only buffer): refreshed on every VM moment.
                        Item {
                            id: fieldBox
                            objectName: "fieldPropertiesBox"
                            Layout.fillWidth: true
                            implicitHeight: dataColumn.implicitHeight
                            enabled: root.panelSelected
                            visible: root.panelRow !== null

                            ColumnLayout {
                                id: dataColumn
                                anchors.fill: parent
                                spacing: root.gapSm

                                // geometry grid X/Y/W/H + Кегль — the VM
                                // clamps into the (oriented) page (D4: the
                                // fields show the effective values again)
                                Grid {
                                    columns: 2
                                    columnSpacing: root.gapSm
                                    rowSpacing: root.gapSm
                                    Layout.fillWidth: true

                                    Repeater {
                                        model: [
                                            {label: "X", name: "xField",
                                             accName: "Позиция X"},
                                            {label: "Y", name: "yField",
                                             accName: "Позиция Y"},
                                            {label: "W", name: "wField",
                                             accName: "Ширина"},
                                            {label: "H", name: "hField",
                                             accName: "Высота"}
                                        ]
                                        delegate: ColumnLayout {
                                            required property var modelData
                                            required property int index
                                            spacing: 2
                                            Text {
                                                text: modelData.label
                                                color: root.fgColor
                                                font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                                            }
                                            ThemeField {
                                                id: geomField
                                                objectName: modelData.name
                                                Layout.fillWidth: true
                                                Layout.minimumWidth: 90
                                                validator: DoubleValidator {bottom: 0}
                                                // nri-0012 task 3.3 (design map):
                                                // the bare X/Y/W/H captions are
                                                // paint only — the tree names
                                                // the fields by purpose.
                                                Accessible.name: modelData.accName
                                                Binding {
                                                    when: !geomField.activeFocus
                                                    target: geomField
                                                    property: "text"
                                                    value: root.geomValue(index)
                                                }
                                                onEditingFinished:
                                                    root.applyGeometry(index, text)
                                            }
                                        }
                                    }

                                    Text {
                                        text: "Кегль"
                                        visible: root.fontEditVisible
                                        color: root.fgColor
                                        font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                                    }
                                    ThemeField {
                                        id: fontField
                                        objectName: "fontField"
                                        visible: root.fontEditVisible
                                        Layout.columnSpan: 2
                                        Layout.preferredWidth: 120
                                        validator: DoubleValidator {bottom: 4; top: 72}
                                        // nri-0012 task 3.3: same rule as X/Y/W/H.
                                        Accessible.name: "Кегль"
                                        Binding {
                                            when: !fontField.activeFocus
                                            target: fontField
                                            property: "text"
                                            value: root.panelRow ? root.panelRow.fontSize : ""
                                        }
                                        onEditingFinished: root.applyFontSize(text)
                                    }
                                }

                                // ── content branch (label/text/textarea) ────
                                // the panel and the inline canvas edit share
                                // ONE VM buffer; begin/end edit makes one
                                // typing session one undo step (review #11)
                                TextArea {
                                    id: contentField
                                    objectName: "contentField"
                                    visible: root.rowType === "label"
                                             || root.rowType === "text"
                                             || root.rowType === "textarea"
                                    Layout.fillWidth: true
                                    Layout.minimumHeight: 64
                                    placeholderText: "Текст поля"
                                    // nri-0012 task 3.3 (design map): the
                                    // placeholder is not the tree's name slot.
                                    Accessible.name: "Текст поля"
                                    color: root.fgColor
                                    background: Rectangle {
                                        color: root.canvasColor
                                        border.color: activeFocus ? root.accentColor
                                                                  : root.borderColor
                                        border.width: 1
                                    }
                                    Binding {
                                        when: !contentField.activeFocus
                                        target: contentField
                                        property: "text"
                                        value: root.panelRow ? root.panelRow.content : ""
                                    }
                                    onActiveFocusChanged: {
                                        if (!activeFocus)
                                            root.endPanelEdit()
                                    }
                                    onTextChanged: {
                                        if (!activeFocus || !root.panelSelected)
                                            return
                                        root.beginPanelEdit()
                                        root.vm.set_content(root.panelFid, text)
                                    }
                                }

                                // ── number branch ───────────────────────────
                                ThemeField {
                                    id: numberField
                                    objectName: "numberField"
                                    visible: root.rowType === "number"
                                    Layout.fillWidth: true
                                    placeholderText: "Число (запятая допустима)"
                                    // nri-0012 task 3.3: name = the map's short
                                    // purpose (the placeholder stays paint-only).
                                    Accessible.name: "Число"
                                    onEditingFinished: root.applyNumberDraft(text)
                                }
                                RowLayout {
                                    visible: root.rowType === "number"
                                    spacing: root.gapSm
                                    ThemeCheckBox {
                                        id: minCheck
                                        objectName: "minCheck"
                                        text: "min"
                                        checked: root.hasMin
                                        onToggled: root.applyBounds()
                                    }
                                    ThemeField {
                                        id: minField
                                        objectName: "minField"
                                        Layout.fillWidth: true
                                        enabled: minCheck.checked
                                        // nri-0012 task 3.3: «min» lives in the
                                        // checkbox text only — the field needs
                                        // the spelled-out name.
                                        Accessible.name: "Минимум"
                                        onEditingFinished: root.applyBounds()
                                    }
                                }
                                RowLayout {
                                    visible: root.rowType === "number"
                                    spacing: root.gapSm
                                    ThemeCheckBox {
                                        id: maxCheck
                                        objectName: "maxCheck"
                                        text: "max"
                                        checked: root.hasMax
                                        onToggled: root.applyBounds()
                                    }
                                    ThemeField {
                                        id: maxField
                                        objectName: "maxField"
                                        Layout.fillWidth: true
                                        enabled: maxCheck.checked
                                        Accessible.name: "Максимум"
                                        onEditingFinished: root.applyBounds()
                                    }
                                }

                                // ── checkbox branch ─────────────────────────
                                ThemeCheckBox {
                                    objectName: "checkboxDefaultCheck"
                                    visible: root.rowType === "checkbox"
                                    text: "Включение по умолчанию"
                                    checked: root.panelRow ? root.panelRow.content === "true"
                                                           : false
                                    onToggled: root.vm.toggle_checkbox(root.panelFid)
                                }

                                // ── dropdown branch ─────────────────────────
                                ColumnLayout {
                                    visible: root.rowType === "dropdown"
                                    spacing: root.gapSm

                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 110
                                        radius: Tokens.px(root.islandTokens, "radius.sm")
                                        color: root.canvasColor
                                        border.color: root.borderColor
                                        border.width: 1
                                        clip: true

                                        ListView {
                                            id: optionsList
                                            objectName: "optionsList"
                                            anchors.fill: parent
                                            anchors.margins: 1
                                            model: root.panelOptions
                                            clip: true
                                            spacing: 2
                                            delegate: RowItem {
                                                required property int index
                                                required property var modelData
                                                objectName: "optionRow"
                                                textObjectName: "optionRowText"
                                                width: optionsList.width
                                                height: implicitHeight
                                                text: String(modelData)
                                                selected: index === root.optionsCurrent
                                                onSelectedRequested:
                                                    root.optionsCurrent = index
                                            }
                                        }
                                    }

                                    RowLayout {
                                        spacing: root.gapSm
                                        ThemeField {
                                            id: optionInput
                                            objectName: "optionInput"
                                            Layout.fillWidth: true
                                            placeholderText: "Новая опция"
                                            // nri-0012 task 3.3 (design map).
                                            Accessible.name: "Новая опция"
                                            onAccepted: root.addOption()
                                        }
                                        ThemeButton {
                                            objectName: "optionAddButton"
                                            text: "Добавить"
                                            onClicked: root.addOption()
                                        }
                                    }
                                    RowLayout {
                                        spacing: root.gapSm
                                        ThemeButton {
                                            objectName: "optionRemoveButton"
                                            text: "Удалить"
                                            onClicked: root.removeOption()
                                        }
                                        ThemeIconButton {
                                            objectName: "optionUpButton"
                                            text: "↑"
                                            // nri-0012 task 3.3: glyph-only —
                                            // named by the action (design map).
                                            Accessible.name: "Поднять опцию"
                                            onClicked: root.moveOption(-1)
                                        }
                                        ThemeIconButton {
                                            objectName: "optionDownButton"
                                            text: "↓"
                                            Accessible.name: "Опустить опцию"
                                            onClicked: root.moveOption(1)
                                        }
                                        Item { Layout.fillWidth: true }
                                    }
                                    RowLayout {
                                        spacing: root.gapSm
                                        Text {
                                            text: "Default:"
                                            color: root.fgColor
                                            font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                                        }
                                        ThemeComboBox {
                                            id: defaultCombo
                                            objectName: "defaultCombo"
                                            Layout.fillWidth: true
                                            // nri-0012 task 3.3: the «Default:»
                                            // caption is paint; the tree name
                                            // spells the purpose once (map).
                                            Accessible.name: "Значение по умолчанию"
                                            // the migrated empty-default entry
                                            model: ["", ...root.panelOptions]
                                            Binding {
                                                when: !defaultCombo.popup.visible
                                                target: defaultCombo
                                                property: "currentIndex"
                                                value: Math.max(0, defaultCombo
                                                                .find(root.panelRow
                                                                     ? root.panelRow.content
                                                                     : ""))
                                            }
                                            onActivated: (index) =>
                                                root.vm.set_content(
                                                    root.panelFid, currentText)
                                        }
                                    }
                                }

                                // ── image branch ────────────────────────────
                                ColumnLayout {
                                    visible: root.rowType === "image"
                                    spacing: root.gapSm
                                    ThemeButton {
                                        objectName: "imagePickButton"
                                        Layout.fillWidth: true
                                        text: "Выбрать файл…"
                                        onClicked: root.imagePickRequested(root.panelFid)
                                    }
                                    ThemeButton {
                                        objectName: "imageClearButton"
                                        Layout.fillWidth: true
                                        text: "Очистить"
                                        onClicked: root.vm.set_image_id(root.panelFid, null)
                                    }
                                    Text {
                                        objectName: "imageLabel"
                                        Layout.fillWidth: true
                                        wrapMode: Text.WordWrap
                                        color: root.fgColor
                                        font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                                        text: root.panelRow && root.panelRow.imageKey !== ""
                                              ? "Изображение: id " + root.panelRow.imageKey
                                              : "Картинка не выбрана"
                                    }
                                }

                                // ── decorative branch (rect/line) ───────────
                                Text {
                                    objectName: "decorLabel"
                                    visible: root.rowType === "rect" || root.rowType === "line"
                                    Layout.fillWidth: true
                                    wrapMode: Text.WordWrap
                                    color: root.fgColor
                                    font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                                    text: "Декоративное поле: данных персонажа не хранит."
                                }
                            }
                        }
                    }
                }
            }
        }

        // Bottom actions (the old chrome): «Сохранить» is the Enter marker
        // (defaultButton above) — the wrapper clicks it when inline editing
        // did not consume Enter.
        RowLayout {
            Layout.fillWidth: true
            spacing: root.gapSm
            Item { Layout.fillWidth: true }
            ThemeButton {
                objectName: "exportPdfButton"
                text: "Экспорт в PDF…"
                onClicked: root.exportPdfRequested()
            }
            ThemeButton {
                id: saveButton
                objectName: "saveButton"
                text: "Сохранить"
                accentBackground: true
                onClicked: root.saveRequested()
            }
        }
    }

    // ── tooltip shim (Q2.5a D9): native QToolTip outside the island ────────
    function tooltipReported(text, hovered) {
        if (typeof tooltipBridge === "undefined" || tooltipBridge === null)
            return
        tooltipBridge.tooltipRequested(hovered ? text : "",
                                       Qt.point(0, 0))
    }

    // ── panel state (the selected field's projection) ───────────────────────
    // One recompute stamp bumped by every VM moment that can move the shown
    // values — the rows themselves come from the field model (get()), so no
    // second copy of any field exists here.
    property int panelTick: 0
    Connections {
        target: root.vmReady ? root.vm : null
        function onSelection_changed(_fid) { root.panelTick += 1; root.optionsCurrent = -1 }
        function onField_content_changed(_fid) { root.panelTick += 1 }
        function onField_geometry_changed(_fid) { root.panelTick += 1 }
        function onField_font_changed(_fid) { root.panelTick += 1 }
        function onField_props_changed(_fid) { root.panelTick += 1 }
        function onField_removed(_fid) { root.panelTick += 1; root.optionsCurrent = -1 }
        function onHistory_changed() { root.panelTick += 1 }
        function onTemplate_changed() { root.panelTick += 1; root.optionsCurrent = -1 }
        function onPages_changed() { root.panelTick += 1 }
    }
    Connections {
        target: sheetCanvas
        function onGeomTickChanged() { root.panelTick += 1 }
    }

    readonly property string panelFid:
        root.vmReady && vm.selectedIds && vm.selectedIds.length > 0
            ? String(vm.selectedIds[0]) : ""
    property var panelRow: computePanelRow()
    // direct VM reads — a bound projection of selectedIds could lag a change
    // inside the very signal handler that reacts to it (stale binding value)
    function liveFid() {
        if (!vmReady || !vm.selectedIds || vm.selectedIds.length === 0)
            return ""
        return String(vm.selectedIds[0])
    }
    function computePanelRow() {
        panelTick                                  // the recompute dependency
        var fid = liveFid()
        if (fid === "")
            return null
        return sheetCanvas.rowById(fid)
    }
    onPanelTickChanged: panelRow = computePanelRow()

    readonly property string rowType: panelRow ? panelRow.type : ""
    readonly property bool panelSelected: panelRow !== null
    readonly property bool fontEditVisible:
        rowType === "label" || rowType === "text" || rowType === "textarea"
        || rowType === "number" || rowType === "dropdown"

    property var panelProps: ({})
    function refreshProps() {
        var fid = liveFid()
        panelProps = (vmReady && fid !== "") ? vm.field_props(fid) : ({})
    }
    onPanelRowChanged: refreshProps()

    readonly property var panelOptions:
        panelProps.options ? panelProps.options : []
    readonly property bool hasMin: panelProps.min !== undefined
                                   && panelProps.min !== null
    readonly property bool hasMax: panelProps.max !== undefined
                                   && panelProps.max !== null
    property int optionsCurrent: -1

    function geomValue(index) {
        if (panelRow === null)
            return ""
        return [panelRow.x, panelRow.y, panelRow.w, panelRow.h][index]
    }

    // -- panel → VM: every edit lands on an existing sync entrance; the
    //    panel never clamps (the VM does, D4). begin/end mirror the old
    //    QDoubleSpinBox gesture wrapping (one undo step per session).
    function beginPanelEdit() { vm.begin_edit() }
    function endPanelEdit() { vm.end_edit() }

    function applyGeometry(index, value) {
        var row = computePanelRow()
        if (row === null)
            return
        var v = Number(value)
        if (!Number.isFinite(v))
            v = geomValue(index)               // old spin rejected garbage
        vm.begin_edit()
        switch (index) {
        case 0: vm.move(row.id, v, row.y); break
        case 1: vm.move(row.id, row.x, v); break
        case 2: vm.resize(row.id, row.x, row.y, v, row.h); break
        case 3: vm.resize(row.id, row.x, row.y, row.w, v); break
        }
        vm.end_edit()
    }
    function applyFontSize(value) {
        if (!panelSelected)
            return
        var v = Number(value)
        if (!Number.isFinite(v))
            return
        vm.begin_edit()
        vm.set_font_size(panelFid, v)
        vm.end_edit()
    }
    function applyNumberDraft(text) {
        if (!panelSelected)
            return
        // rejected (non-number or out of bounds): keep the stored value
        // visible (the old panel re-synced the line edit)
        if (!vm.apply_number(panelFid, text))
            numberDraftSync.stamp += 1
    }
    Item { id: numberDraftSync; property int stamp: 0 }
    Binding {
        when: numberDraftSync.stamp >= 0
        target: numberField
        property: "text"
        value: root.rowType === "number" && root.panelRow ? root.panelRow.content : ""
    }

    function applyBounds() {
        if (!panelSelected)
            return
        var newMin = minCheck.checked ? Number(minField.text) : null
        var newMax = maxCheck.checked ? Number(maxField.text) : null
        if (vm.set_min_value(panelFid, newMin)) {
            if (vm.set_max_value(panelFid, newMax))
                refreshProps()
            else
                vm.set_max_value(panelFid, panelProps.max ?? null)   // restore
        } else {
            vm.set_min_value(panelFid, panelProps.min ?? null)       // restore
        }
        refreshProps()
    }

    function addOption() {
        if (!panelSelected)
            return
        var text = optionInput.text
        optionInput.text = ""
        if (!vm.set_options(panelFid, [...panelOptions, text]))
            refreshProps()              // refused: re-read the VM list
    }
    function removeOption() {
        if (!panelSelected || optionsCurrent < 0 || optionsCurrent >= panelOptions.length)
            return
        var options = [...panelOptions]
        options.splice(optionsCurrent, 1)
        vm.set_options(panelFid, options)
        optionsCurrent = options.length ? Math.min(optionsCurrent, options.length - 1) : -1
    }
    function moveOption(delta) {
        if (!panelSelected)
            return
        var row = optionsCurrent
        var target = row + delta
        if (row < 0 || row >= panelOptions.length
                || target < 0 || target >= panelOptions.length)
            return
        var options = [...panelOptions]
        var tmp = options[row]
        options[row] = options[target]
        options[target] = tmp
        if (vm.set_options(panelFid, options))
            optionsCurrent = target
    }
}
