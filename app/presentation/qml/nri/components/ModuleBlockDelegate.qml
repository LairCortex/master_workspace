// ModuleBlockDelegate — one declarative module block of the kernel card
// scroll, painted with штатные Theme controls (dd-card-redesign task 4.2,
// design Д2: «ядро рисует их штатными Theme-контролами QML на объявленных
// позициях»).
//
// The block dict is the protocol's ModuleBlock.to_dict serialization — this
// component reads ONLY those fields and owns no module semantics: the write
// channel is one call, `vm.writeModuleBlock(block.id, field, value)`, relayed
// verbatim from the usage-site view model (the VM relays to the host, the
// host to the source's handler).
//
// Accessibility follows the island contract: every control whose caption
// lives outside the control (combo, number field) is named at THIS usage
// site by the block's label (the data-model controls are named by their
// purpose, the design-map convention); a switch rides onClicked (Д15: the
// accessibility activation of a stock CheckBox writes ``checked`` without a
// user gesture, so the write reads the model's value, never the half-flipped
// tick); a stock button carries its bound caption and no re-annotation.
//
// Kinds (the finite set of MODULE_BLOCK_KINDS; unknown kinds painted nothing
// — the protocol refuses them at construction anyway):
//   * combo   — caption + ThemeComboBox, the selected option written back;
//   * number  — caption + ThemeField with an IntValidator, committed on
//               editingFinished (never per keystroke — every write is one
//               module transaction);
//   * textline — caption + ThemeField without a validator (free text), the
//               placeholder from the block, committed on editingFinished;
//   * switch  — ThemeCheckBox, the tick is the frame's state (binding);
//   * text    — read-only caption/value line;
//   * buttons — a row of ThemeButtons, the pressed action id is the field;
//   * table   — caption, a column-caption row and rows of text/number/switch
//               cells; a cell writes as "<row id>.<field>".
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import nri.components
import "tokens.js" as Tokens

ColumnLayout {
    id: root

    // The serialized ModuleBlock and the island's view model (the two usage
    // sites run under different context names — entityCardVm/eventDialogVm —
    // so the vm arrives as a plain property, the component names no context).
    property var block: ({})
    property var vm: null

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color fgColor:
        Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property int mdPx: Tokens.px(islandTokens, "font.size.md", 13)
    // The caption street the kernel grid already uses for its own fields
    // (the extra mention rows print their labels at 130 px — the blocks
    // align with them).
    readonly property real labelWidth: 130
    // The table's first column (names), the rest share the remaining width.
    readonly property real firstColumnWidth: 180

    function write(field, value) {
        if (root.vm !== null)
            root.vm.writeModuleBlock(root.block.id, field, value)
    }

    readonly property var optionList:
        root.block.options === undefined || root.block.options === null
            ? [] : root.block.options
    readonly property var optionLabels: optionList.map(o => o.label)
    readonly property int optionIndex: {
        for (let i = 0; i < optionList.length; ++i)
            if (optionList[i].id === root.block.value)
                return i
        return -1
    }

    // ── combo ────────────────────────────────────────────────────────────────
    RowLayout {
        Layout.fillWidth: true
        visible: root.block.kind === "combo"
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        TitleText {
            objectName: "moduleBlockCaption_" + root.block.id
            Layout.preferredWidth: root.labelWidth
            visible: root.block.label !== ""
            text: root.block.label + ":"
        }
        ThemeComboBox {
            objectName: "moduleBlockCombo_" + root.block.id
            Layout.fillWidth: true
            enabled: root.block.enabled
            model: root.optionLabels
            currentIndex: root.optionIndex
            // The option captions are data; the tree name is the purpose
            // (the design map's combo convention, one usage-site name).
            Accessible.name: root.block.label
            onActivated: root.write("value", root.optionList[index].id)
        }
    }

    // ── number ───────────────────────────────────────────────────────────────
    RowLayout {
        Layout.fillWidth: true
        visible: root.block.kind === "number"
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        TitleText {
            objectName: "moduleBlockCaption_" + root.block.id
            Layout.preferredWidth: root.labelWidth
            visible: root.block.label !== ""
            text: root.block.label + ":"
        }
        ThemeField {
            objectName: "moduleBlockNumber_" + root.block.id
            Layout.fillWidth: true
            Layout.preferredWidth: 80
            enabled: root.block.enabled
            text: root.block.value
            placeholderText: "не задано"
            Accessible.name: root.block.label
            validator: IntValidator {
                bottom: root.block.minValue < 0 ? -2147483647 : root.block.minValue
                top: root.block.maxValue < 0 ? 2147483647 : root.block.maxValue
            }
            // One transaction per committed edit, never one per keystroke.
            onEditingFinished: root.write("value", text)
        }
    }

    // ── textline ─────────────────────────────────────────────────────────────
    // The editable one-line text (the LSS sheet id): no validator — free
    // text by contract — committed on editingFinished like the number, so
    // every edit is one module transaction, never one per keystroke.
    RowLayout {
        Layout.fillWidth: true
        visible: root.block.kind === "textline"
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        TitleText {
            objectName: "moduleBlockCaption_" + root.block.id
            Layout.preferredWidth: root.labelWidth
            visible: root.block.label !== ""
            text: root.block.label + ":"
        }
        ThemeField {
            objectName: "moduleBlockTextline_" + root.block.id
            Layout.fillWidth: true
            enabled: root.block.enabled
            text: root.block.value
            placeholderText: root.block.placeholder
            Accessible.name: root.block.label
            onEditingFinished: root.write("value", text)
        }
    }

    // ── switch ───────────────────────────────────────────────────────────────
    RowLayout {
        Layout.fillWidth: true
        visible: root.block.kind === "switch"
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        ThemeCheckBox {
            objectName: "moduleBlockSwitch_" + root.block.id
            text: root.block.label
            checked: root.block.checked
            enabled: root.block.enabled
            // Д15 posture: the activation requests the flipped MODEL value.
            onClicked: root.write("value", !root.block.checked)
        }
    }

    // ── text ─────────────────────────────────────────────────────────────────
    RowLayout {
        Layout.fillWidth: true
        visible: root.block.kind === "text"
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        TitleText {
            objectName: "moduleBlockCaption_" + root.block.id
            visible: root.block.label !== ""
            text: root.block.label
        }
        Text {
            objectName: "moduleBlockText_" + root.block.id
            Layout.fillWidth: true
            visible: root.block.value !== ""
            text: root.block.value
            color: root.fgColor
            font.pixelSize: root.mdPx
            elide: Text.ElideRight
        }
    }

    // ── buttons ──────────────────────────────────────────────────────────────
    RowLayout {
        Layout.fillWidth: true
        visible: root.block.kind === "buttons"
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        TitleText {
            objectName: "moduleBlockCaption_" + root.block.id
            visible: root.block.label !== ""
            text: root.block.label + ":"
        }
        Repeater {
            model: root.block.actions === undefined || root.block.actions === null
                ? [] : root.block.actions
            ThemeButton {
                objectName: "moduleBlockAction_" + root.block.id + "_" + modelData.id
                text: modelData.label
                enabled: modelData.enabled && root.block.enabled
                onClicked: root.write(modelData.id, true)
            }
        }
        Item { Layout.fillWidth: true }
    }

    // ── table ────────────────────────────────────────────────────────────────
    ColumnLayout {
        Layout.fillWidth: true
        visible: root.block.kind === "table"
        spacing: Tokens.px(root.islandTokens, "space.xs", 4)

        TitleText {
            objectName: "moduleBlockTableCaption_" + root.block.id
            visible: text !== ""
            text: root.block.label
        }

        // The column captions (the module names them; the first street is
        // the names column, the rest share the remaining width).
        RowLayout {
            Layout.fillWidth: true
            spacing: Tokens.px(root.islandTokens, "space.sm", 8)
            visible: root.block.columns !== undefined
                     && root.block.columns !== null && root.block.columns.length > 0
            Repeater {
                model: root.block.columns === undefined || root.block.columns === null
                    ? [] : root.block.columns
                TitleText {
                    objectName: "moduleBlockColumn_" + root.block.id + "_" + index
                    Layout.preferredWidth: index === 0 ? root.firstColumnWidth : 0
                    Layout.fillWidth: index !== 0
                    text: modelData
                }
            }
        }

        Repeater {
            model: root.block.rows === undefined || root.block.rows === null
                ? [] : root.block.rows
            RowLayout {
                id: blockRow
                objectName: "moduleBlockRow_" + root.block.id + "_" + modelData.id
                Layout.fillWidth: true
                spacing: Tokens.px(root.islandTokens, "space.sm", 8)
                readonly property string rowId: modelData.id

                Repeater {
                    model: modelData.cells === undefined || modelData.cells === null
                        ? [] : modelData.cells
                    ColumnLayout {
                        id: blockCell
                        readonly property var cell: modelData
                        Layout.preferredWidth: index === 0 ? root.firstColumnWidth : 0
                        Layout.fillWidth: index !== 0
                        spacing: 0

                        Text {
                            visible: blockCell.cell.kind === "text"
                            objectName: "moduleBlockCellText_" + root.block.id
                                          + "_" + blockRow.rowId + "_" + blockCell.cell.field
                            text: blockCell.cell.label !== ""
                                  ? blockCell.cell.label : blockCell.cell.value
                            color: root.fgColor
                            font.pixelSize: root.mdPx
                            elide: Text.ElideRight
                        }
                        ThemeField {
                            visible: blockCell.cell.kind === "number"
                            objectName: "moduleBlockCellNumber_" + root.block.id
                                        + "_" + blockRow.rowId + "_" + blockCell.cell.field
                            Layout.fillWidth: true
                            enabled: blockCell.cell.enabled
                            text: blockCell.cell.value
                            placeholderText: "не задано"
                            Accessible.name: blockCell.cell.name !== ""
                                             ? blockCell.cell.name : blockCell.cell.label
                            validator: IntValidator {
                                bottom: blockCell.cell.minValue < 0
                                        ? -2147483647 : blockCell.cell.minValue
                                top: blockCell.cell.maxValue < 0
                                     ? 2147483647 : blockCell.cell.maxValue
                            }
                            onEditingFinished: root.write(
                                blockRow.rowId + "." + blockCell.cell.field, text)
                        }
                        ThemeCheckBox {
                            visible: blockCell.cell.kind === "switch"
                            objectName: "moduleBlockCellSwitch_" + root.block.id
                                        + "_" + blockRow.rowId + "_" + blockCell.cell.field
                            text: blockCell.cell.label
                            checked: blockCell.cell.checked
                            enabled: blockCell.cell.enabled
                            Accessible.name: blockCell.cell.name !== ""
                                             ? blockCell.cell.name : blockCell.cell.label
                            onClicked: root.write(
                                blockRow.rowId + "." + blockCell.cell.field,
                                !blockCell.cell.checked)
                        }
                    }
                }
            }
        }
    }
}
