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
                // nri-0012 task 3.5 (usage-site name, design map): the typed
                // name rides the value slot; the caption is paint.
                Accessible.name: "Название события"
                onTextEdited: eventDialogVm.name = text
            }
            ThemeAiButton {
                objectName: "eventNameAiButton"
                proxy: eventDialogVm.nameAiProxy
                entityType: "event"
                fieldName: "name"
                fieldLabel: "Название"
                // nri-0012 task 3.5: the «✨» glyph is mute in the tree; the
                // name follows the fieldLabel the proxy prompt already uses.
                Accessible.name: "Сгенерировать: " + fieldLabel
            }

            TitleText { text: "Дата начала *:" }
            ThemeDateField {
                id: startDate
                objectName: "eventStartDateField"
                Layout.fillWidth: true
                isoDate: eventDialogVm.startIso
                display: eventDialogVm.startDisplay
                // nri-0012 task 3.5: the tap opens the calendar popup; the
                // name slot carries the field's purpose (entity-card precedent).
                Accessible.name: "Дата начала"
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
                    Accessible.name: "Дата конца"
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
                    // nri-0012 task 3.5: the combo shows type names (data) —
                    // the tree name is the purpose (design map).
                    Accessible.name: "Тип события"
                    onActivated: eventDialogVm.selectType(index)
                }
                ThemeSwatch {
                    objectName: "eventTypeSwatch"
                    visible: eventDialogVm.selectedColorIndex > 0
                    colorIndex: Math.max(1, eventDialogVm.selectedColorIndex)
                    // nri-0012 task 3.5: the dialog override of the group-1
                    // swatch default («Цвет палитры №N» stays in the palette).
                    accessibleName: "Цвет типа события"
                }
            }
            Item { implicitWidth: 24 }

            TitleText { text: "Характеристики *:" }
            MentionField {
                objectName: "eventCharacteristicsField"
                Layout.fillWidth: true
                Layout.preferredHeight: 72
                host: eventDialogVm.characteristicsMentionHost
                // nri-0012 task 3.5: the component brings the EditableText
                // role (1.3); the island names it (entity-card precedent).
                Accessible.name: "Характеристики"
            }
            ThemeAiButton {
                objectName: "eventCharacteristicsAiButton"
                proxy: eventDialogVm.characteristicsAiProxy
                entityType: "event"
                fieldName: "characteristics"
                fieldLabel: "Характеристики"
                Accessible.name: "Сгенерировать: " + fieldLabel
            }

            TitleText { text: "Предыстория *:" }
            MentionField {
                objectName: "eventBackstoryField"
                Layout.fillWidth: true
                Layout.preferredHeight: 72
                host: eventDialogVm.backstoryMentionHost
                Accessible.name: "Предыстория"
            }
            ThemeAiButton {
                objectName: "eventBackstoryAiButton"
                proxy: eventDialogVm.backstoryAiProxy
                entityType: "event"
                fieldName: "backstory"
                fieldLabel: "Предыстория"
                Accessible.name: "Сгенерировать: " + fieldLabel
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            ThemeAiButton {
                objectName: "eventEntityAiButton"
                proxy: eventDialogVm.entityAiProxy
                // nri-0012 task 3.5: the wave generates the event as a whole
                // — the labelled target surfaces in the tree (the label is
                // QML-side only here: this button has no fieldName, the wave
                // rides the proxy unchanged).
                fieldLabel: "Событие"
                Accessible.name: "Сгенерировать: " + fieldLabel
            }
        }

        ThemeTabBar {
            id: tabs
            objectName: "eventRelatedTabs"
            Layout.fillWidth: true
            ThemeTabButton { text: "Организации" }
            ThemeTabButton { text: "Персонажи" }
            ThemeTabButton { text: "Предметы" }
            ThemeTabButton { text: "Локации" }
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
