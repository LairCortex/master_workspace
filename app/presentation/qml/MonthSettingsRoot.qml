import QtQuick
import QtQuick.Layouts
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "monthSettingsRoot"

    readonly property Item defaultButton: saveButton

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor: Tokens.token(islandTokens, "color.bg.surface", "white")

    color: surfaceColor
    implicitWidth: 380
    implicitHeight: 520

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Tokens.px(root.islandTokens, "space.md", 16)
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        HintText {
            objectName: "monthHint"
            italic: true
            text: "Оставьте пустым для стандартного названия"
            Layout.fillWidth: true
        }

        Repeater {
            model: 12
            RowLayout {
                Layout.fillWidth: true
                TitleText {
                    text: (index + 1) + ". " + monthSettingsVm.placeholderAt(index) + ":"
                    Layout.preferredWidth: 140
                }
                ThemeField {
                    objectName: "monthField" + (index + 1)
                    Layout.fillWidth: true
                    placeholderText: monthSettingsVm.placeholderAt(index)
                    text: monthSettingsVm.names[index]
                    onTextChanged: monthSettingsVm.setName(index, text)
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            ThemeButton {
                objectName: "resetButton"
                text: "Сбросить"
                onClicked: monthSettingsVm.reset()
            }
            Item { Layout.fillWidth: true }
            ThemeButton {
                id: saveButton
                objectName: "saveButton"
                text: "Сохранить"
                accentBackground: true
                onClicked: root.saveRequested()
            }
            ThemeButton {
                objectName: "cancelButton"
                text: "Отмена"
                onClicked: root.cancelRequested()
            }
        }
    }

    signal saveRequested()
    signal cancelRequested()
}
