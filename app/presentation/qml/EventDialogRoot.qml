import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "eventDialogRoot"

    readonly property Item defaultButton: saveButton
    readonly property string typeSelectorMode: "qml"
    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor:
        Tokens.token(islandTokens, "color.bg.surface", "white")

    color: surfaceColor
    implicitWidth: 700
    implicitHeight: 620

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Tokens.px(root.islandTokens, "space.md", 16)
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        GridLayout {
            columns: 3
            columnSpacing: Tokens.px(root.islandTokens, "space.sm", 8)
            rowSpacing: Tokens.px(root.islandTokens, "space.xs", 4)
            Layout.fillWidth: true

            TitleText { text: "Название *:" }
            ThemeField {
                objectName: "eventNameField"
                Layout.fillWidth: true
                text: eventDialogVm.name
                placeholderText: "Название события *"
                onTextEdited: eventDialogVm.name = text
            }
            ThemeAiButton {
                objectName: "eventNameAiButton"
                proxy: eventDialogVm.nameAiProxy
                entityType: "event"
                fieldName: "name"
                fieldLabel: "Название"
            }

            TitleText { text: "Дата начала *:" }
            ThemeDateField {
                id: startDate
                objectName: "eventStartDateField"
                Layout.fillWidth: true
                isoDate: eventDialogVm.startIso
                display: eventDialogVm.startDisplay
                onClicked: {
                    const point = startDate.mapToItem(root, 0, 0)
                    eventDialogVm.requestDatePopup(
                        "start", point.x, point.y, startDate.width, startDate.height)
                }
            }
            Item { implicitWidth: 24 }

            TitleText { text: "Дата конца:" }
            RowLayout {
                Layout.fillWidth: true
                ThemeDateField {
                    id: endDate
                    objectName: "eventEndDateField"
                    Layout.fillWidth: true
                    visible: !eventDialogVm.noEnd
                    isoDate: eventDialogVm.endIso
                    display: eventDialogVm.endDisplay
                    onClicked: {
                        const point = endDate.mapToItem(root, 0, 0)
                        eventDialogVm.requestDatePopup(
                            "end", point.x, point.y, endDate.width, endDate.height)
                    }
                }
                ThemeCheckBox {
                    objectName: "eventNoEndCheck"
                    text: "Бессрочно"
                    checked: eventDialogVm.noEnd
                    onToggled: eventDialogVm.setNoEnd(checked)
                }
            }
            Item { implicitWidth: 24 }

            TitleText { text: "Тип:" }
            RowLayout {
                Layout.fillWidth: true
                ThemeComboBox {
                    id: typeCombo
                    objectName: "eventTypeCombo"
                    Layout.fillWidth: true
                    model: eventDialogVm.typeNames
                    currentIndex: eventDialogVm.selectedTypeIndex
                    onActivated: eventDialogVm.selectType(index)
                }
                ThemeSwatch {
                    objectName: "eventTypeSwatch"
                    visible: eventDialogVm.selectedColorIndex > 0
                    colorIndex: Math.max(1, eventDialogVm.selectedColorIndex)
                }
            }
            Item { implicitWidth: 24 }

            TitleText { text: "Характеристики *:" }
            MentionField {
                objectName: "eventCharacteristicsField"
                Layout.fillWidth: true
                Layout.preferredHeight: 72
                host: eventDialogVm.characteristicsMentionHost
            }
            ThemeAiButton {
                objectName: "eventCharacteristicsAiButton"
                proxy: eventDialogVm.characteristicsAiProxy
                entityType: "event"
                fieldName: "characteristics"
                fieldLabel: "Характеристики"
            }

            TitleText { text: "Предыстория *:" }
            MentionField {
                objectName: "eventBackstoryField"
                Layout.fillWidth: true
                Layout.preferredHeight: 72
                host: eventDialogVm.backstoryMentionHost
            }
            ThemeAiButton {
                objectName: "eventBackstoryAiButton"
                proxy: eventDialogVm.backstoryAiProxy
                entityType: "event"
                fieldName: "backstory"
                fieldLabel: "Предыстория"
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            ThemeAiButton {
                objectName: "eventEntityAiButton"
                proxy: eventDialogVm.entityAiProxy
            }
        }

        TabBar {
            id: tabs
            objectName: "eventRelatedTabs"
            Layout.fillWidth: true
            TabButton { text: "Организации" }
            TabButton { text: "Персонажи" }
            TabButton { text: "Предметы" }
            TabButton { text: "Локации" }
        }

        StackLayout {
            currentIndex: tabs.currentIndex
            Layout.fillWidth: true
            Layout.fillHeight: true

            RelatedSection {
                objectName: "organizationsRelatedSection"
                objectPrefix: "organizationsRelated"
                section: eventDialogVm.organizationsSection
            }
            RelatedSection {
                objectName: "charactersRelatedSection"
                objectPrefix: "charactersRelated"
                section: eventDialogVm.charactersSection
            }
            RelatedSection {
                objectName: "itemsRelatedSection"
                objectPrefix: "itemsRelated"
                section: eventDialogVm.itemsSection
            }
            RelatedSection {
                objectName: "locationsRelatedSection"
                objectPrefix: "locationsRelated"
                section: eventDialogVm.locationsSection
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            ThemeButton {
                id: saveButton
                objectName: "eventSaveButton"
                text: "Сохранить"
                accentBackground: true
                enabled: eventDialogVm.valid
                onClicked: eventDialogVm.requestSave()
            }
            ThemeButton {
                objectName: "eventCancelButton"
                text: "Отмена"
                enabled: !eventDialogVm.saving
                onClicked: eventDialogVm.requestCancel()
            }
        }
    }
}
