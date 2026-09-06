import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "xlsxImportRoot"

    readonly property Item defaultButton: importButton

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor: Tokens.token(islandTokens, "color.bg.surface", "white")
    readonly property color accentColor: Tokens.token(islandTokens, "color.accent", "black")
    readonly property color canvasColor: Tokens.token(islandTokens, "color.bg.canvas", "white")
    readonly property color borderColor: Tokens.token(islandTokens, "color.border", "lightgray")

    color: surfaceColor
    implicitWidth: 580
    implicitHeight: 480

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Tokens.px(root.islandTokens, "space.md", 16)
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        TitleText {
            objectName: "formatTitle"
            text: "Требования к файлу:"
        }

        ThemeTextArea {
            id: formatArea
            objectName: "formatArea"
            Layout.fillWidth: true
            Layout.preferredHeight: 260
            readOnly: true
            mono: true
            text: xlsxImportVm.formatText
        }

        RowLayout {
            Layout.fillWidth: true
            TitleText { text: "Файл:" }
            ThemeField {
                id: pathField
                objectName: "pathField"
                Layout.fillWidth: true
                placeholderText: "Выберите .xlsx файл…"
                text: xlsxImportVm.path
                onTextChanged: xlsxImportVm.path = text
            }
            ThemeButton {
                objectName: "browseButton"
                text: "Обзор…"
                onClicked: xlsxImportVm.requestBrowse()
            }
        }

        ProgressBar {
            id: progressBar
            objectName: "progressBar"
            Layout.fillWidth: true
            visible: xlsxImportVm.progressVisible
            from: 0
            to: 100
            value: xlsxImportVm.progress
            background: Rectangle {
                implicitHeight: 8
                color: root.canvasColor
                border.color: root.borderColor
                border.width: 1
            }
            contentItem: Item {
                implicitHeight: 6
                Rectangle {
                    width: progressBar.visualPosition * parent.width
                    height: parent.height
                    color: root.accentColor
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            ThemeButton {
                id: importButton
                objectName: "importButton"
                text: "Проверить и импортировать"
                accentBackground: true
                enabled: xlsxImportVm.importEnabled
                onClicked: xlsxImportVm.requestImport()
            }
            ThemeButton {
                objectName: "cancelButton"
                text: "Отмена"
                onClicked: root.cancelRequested()
            }
        }
    }

    signal cancelRequested()
}
