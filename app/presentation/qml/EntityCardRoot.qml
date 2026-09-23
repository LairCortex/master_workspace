import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "entityCardRoot"

    readonly property Item defaultButton: saveButton
    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor:
        Tokens.token(islandTokens, "color.bg.surface", "white")
    readonly property color canvasColor:
        Tokens.token(islandTokens, "color.bg.canvas", "white")
    readonly property color foregroundColor:
        Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color borderColor:
        Tokens.token(islandTokens, "color.border", "lightgray")
    readonly property color accentColor:
        Tokens.token(islandTokens, "color.accent", "black")

    color: surfaceColor
    // Natural content size (island_size.py mirrors it onto the window), so the
    // dialog opens big enough to show the related section and the action row
    // instead of pushing them under the scroll. The sizes the port pinned
    // (750/550 with an image, 550 without) stay as the floors; the content is
    // measured plus the scroll bar's track, which the scene never owns.
    readonly property real scrollbarReserve: 16
    implicitWidth: Math.max(
        entityCardVm.hasImage ? 750 : 550,
        cardColumn.implicitWidth + scrollbarReserve)
    implicitHeight: Math.max(
        550, cardColumn.implicitHeight + scrollbarReserve)

    ScrollView {
        id: scroll
        objectName: "entityCardScroll"
        anchors.fill: parent
        contentWidth: availableWidth

        ColumnLayout {
            id: cardColumn
            width: scroll.availableWidth
            spacing: Tokens.px(root.islandTokens, "space.sm", 8)

            RowLayout {
                Layout.fillWidth: true
                Layout.margins: Tokens.px(root.islandTokens, "space.md", 16)
                spacing: Tokens.px(root.islandTokens, "space.md", 16)

                ColumnLayout {
                    objectName: "entityImageColumn"
                    visible: entityCardVm.hasImage
                    Layout.alignment: Qt.AlignTop

                    CardPanel {
                        id: imageCard
                        objectName: "entityImageCard"
                        Layout.preferredWidth: 280
                        Layout.preferredHeight: 280

                        Image {
                            objectName: "entityImagePreview"
                            anchors.fill: parent
                            anchors.margins: 1
                            source: entityCardVm.imageSource
                            fillMode: Image.PreserveAspectFit
                            visible: entityCardVm.imageAvailable
                            cache: false
                        }
                        HintText {
                            objectName: "entityImagePlaceholder"
                            anchors.centerIn: parent
                            text: "Нет изображения"
                            visible: !entityCardVm.imageAvailable
                        }
                        MouseArea {
                            objectName: "entityImageOpenArea"
                            anchors.fill: parent
                            enabled: entityCardVm.imageAvailable
                            onClicked: entityCardVm.requestImageOpen()
                        }
                    }

                    RowLayout {
                        ThemeButton {
                            objectName: "entityImagePickButton"
                            text: "Выбрать файл"
                            onClicked: entityCardVm.requestImagePick()
                        }
                        ThemeButton {
                            objectName: "entityImageClearButton"
                            text: "Убрать"
                            enabled: entityCardVm.imageAvailable
                            onClicked: entityCardVm.requestImageClear()
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                    RowLayout {
                        Layout.fillWidth: true
                        Item { Layout.fillWidth: true }
                        ThemeAiButton {
                            objectName: "entityGenerateButton"
                            proxy: entityCardVm.entityAiProxy
                            // Task 2.4 (nri-0012): the wave button generates the
                            // entity as a whole — the label names that target in
                            // the tree (QML-side only: the wave itself is driven
                            // through the proxy, this label never reaches it).
                            fieldLabel: "Событие"
                            Accessible.name: "Сгенерировать: " + fieldLabel
                        }
                    }

                    GridLayout {
                        columns: 3
                        Layout.fillWidth: true
                        columnSpacing: Tokens.px(root.islandTokens, "space.sm", 8)
                        rowSpacing: Tokens.px(root.islandTokens, "space.xs", 4)

                        TitleText { text: "Название:" }
                        ThemeField {
                            objectName: "entityNameField"
                            Layout.fillWidth: true
                            text: entityCardVm.name
                            readOnly: entityCardVm.nameAiProxy.generating
                            // nri-0012 task 2.4 (usage-site name, design map):
                            // the typed value lives in the tree's value slot —
                            // the name slot carries the field's purpose.
                            Accessible.name: "Название"
                            onTextEdited: entityCardVm.name = text
                        }
                        ThemeAiButton {
                            objectName: "entityNameAiButton"
                            proxy: entityCardVm.nameAiProxy
                            entityType: entityCardVm.entityType
                            fieldName: "name"
                            fieldLabel: "Название"
                            Accessible.name: "Сгенерировать: " + fieldLabel
                        }

                        TitleText { text: "Рейтинг (1-20):" }
                        SpinBox {
                            id: ratingSpin
                            objectName: "entityRatingSpin"
                            Layout.fillWidth: true
                            from: 1
                            to: 20
                            value: entityCardVm.rating
                            editable: true
                            Accessible.name: "Рейтинг"
                            onValueModified: entityCardVm.setRating(value)
                            contentItem: TextInput {
                                text: ratingSpin.textFromValue(ratingSpin.value, ratingSpin.locale)
                                color: root.foregroundColor
                                selectionColor: root.accentColor
                                horizontalAlignment: Qt.AlignHCenter
                                verticalAlignment: Qt.AlignVCenter
                                readOnly: !ratingSpin.editable
                                validator: ratingSpin.validator
                                inputMethodHints: Qt.ImhFormattedNumbersOnly
                            }
                            background: Rectangle {
                                color: root.canvasColor
                                border.width: 1
                                border.color: ratingSpin.activeFocus
                                    ? root.accentColor : root.borderColor
                                radius: Tokens.px(root.islandTokens, "radius.sm", 6)
                            }
                        }
                        Item { implicitWidth: 24 }

                        TitleText { text: "Дата начала:" }
                        ThemeDateField {
                            id: startDate
                            objectName: "entityStartDateField"
                            Layout.fillWidth: true
                            isoDate: entityCardVm.startIso
                            display: entityCardVm.startDisplay
                            // nri-0012 task 2.4 (usage-site name, design map):
                            // the tap opens the calendar popup; the name slot
                            // carries the field's purpose (D5 description not
                            // needed — the name spells the action's target).
                            Accessible.name: "Дата начала"
                            onClicked: {
                                const point = startDate.mapToItem(root, 0, 0)
                                entityCardVm.requestDatePopup(
                                    "start", point.x, point.y,
                                    startDate.width, startDate.height)
                            }
                        }
                        Item { implicitWidth: 24 }

                        TitleText { text: "Дата конца:" }
                        RowLayout {
                            Layout.fillWidth: true
                            ThemeDateField {
                                id: endDate
                                objectName: "entityEndDateField"
                                Layout.fillWidth: true
                                visible: !entityCardVm.noEnd
                                isoDate: entityCardVm.endIso
                                display: entityCardVm.endDisplay
                                Accessible.name: "Дата конца"
                                onClicked: {
                                    const point = endDate.mapToItem(root, 0, 0)
                                    entityCardVm.requestDatePopup(
                                        "end", point.x, point.y,
                                        endDate.width, endDate.height)
                                }
                            }
                            ThemeCheckBox {
                                objectName: "entityNoEndCheck"
                                text: "Бессрочно"
                                checked: entityCardVm.noEnd
                                onToggled: entityCardVm.setNoEnd(checked)
                            }
                        }
                        Item { implicitWidth: 24 }

                        TitleText { text: "Характеристики:" }
                        MentionField {
                            objectName: "entityCharacteristicsField"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 72
                            host: entityCardVm.characteristicsHost
                            enabled: !entityCardVm.characteristicsAiProxy.generating
                            // nri-0012 task 2.4: the component brings the
                            // EditableText role (1.3); the island names it.
                            Accessible.name: "Характеристики"
                        }
                        ThemeAiButton {
                            objectName: "entityCharacteristicsAiButton"
                            proxy: entityCardVm.characteristicsAiProxy
                            // The «✨» glyph alone is mute in the tree; the
                            // name follows the field label (task 2.4). The
                            // fieldLabel property itself stays unset — it
                            // feeds the prompt, not the tree (behavior pin).
                            Accessible.name: "Сгенерировать: Характеристики"
                        }

                        TitleText { text: "Предыстория:" }
                        MentionField {
                            objectName: "entityBackstoryField"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 72
                            host: entityCardVm.backstoryHost
                            enabled: !entityCardVm.backstoryAiProxy.generating
                            Accessible.name: "Предыстория"
                        }
                        ThemeAiButton {
                            objectName: "entityBackstoryAiButton"
                            proxy: entityCardVm.backstoryAiProxy
                            Accessible.name: "Сгенерировать: Предыстория"
                        }

                        TitleText { text: "Музыка:" }
                        RowLayout {
                            Layout.fillWidth: true
                            ThemeField {
                                objectName: "entityMusicField"
                                Layout.fillWidth: true
                                visible: entityCardVm.musicEditing || !entityCardVm.musicUrl
                                text: entityCardVm.musicUrl
                                placeholderText: "Ссылка на музыку"
                                // nri-0012 task 2.4 (design map «Ссылка на
                                // музыку»): the placeholder is not a name.
                                Accessible.name: "Ссылка на музыку"
                                onTextEdited: entityCardVm.setMusicUrl(text)
                            }
                            ThemeButton {
                                objectName: "entityMusicOpenButton"
                                visible: !entityCardVm.musicEditing && !!entityCardVm.musicUrl
                                text: entityCardVm.musicUrl
                                // The text is the URL (data, not a label), so
                                // the usage-site name spells the action.
                                Accessible.name: "Открыть ссылку на музыку"
                                onClicked: entityCardVm.requestMusicOpen()
                            }
                        }
                        ThemeButton {
                            objectName: "entityMusicEditButton"
                            text: "✎"
                            onClicked: entityCardVm.toggleMusicEdit()
                        }
                    }

                    Repeater {
                        model: entityCardVm.extraFields
                        RowLayout {
                            objectName: "entityExtraRow_" + modelData.name
                            Layout.fillWidth: true
                            TitleText {
                                Layout.preferredWidth: 130
                                text: modelData.label + ":"
                            }
                            MentionField {
                                objectName: "entityExtraField_" + modelData.name
                                Layout.fillWidth: true
                                Layout.preferredHeight: 64
                                host: modelData.mentionHost
                                enabled: !modelData.aiProxy.generating
                                // nri-0012 task 2.4: extra fields are named by
                                // their model label (the same binding the
                                // TitleText paints).
                                Accessible.name: modelData.label
                            }
                            ThemeAiButton {
                                objectName: "entityExtraAiButton_" + modelData.name
                                proxy: modelData.aiProxy
                                Accessible.name: "Сгенерировать: " + modelData.label
                            }
                        }
                    }
                }
            }

            ColumnLayout {
                visible: entityCardVm.relatedSections.length > 0
                Layout.fillWidth: true
                Layout.preferredHeight: 230
                Layout.leftMargin: Tokens.px(root.islandTokens, "space.md", 16)
                Layout.rightMargin: Tokens.px(root.islandTokens, "space.md", 16)

                ThemeTabBar {
                    id: relatedTabs
                    objectName: "entityRelatedTabs"
                    Layout.fillWidth: true
                    Repeater {
                        model: entityCardVm.relatedSections
                        ThemeTabButton {
                            objectName: "entityRelatedTab_" + modelData.attr
                            text: modelData.label
                        }
                    }
                }
                StackLayout {
                    currentIndex: relatedTabs.currentIndex
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Repeater {
                        model: entityCardVm.relatedSections
                        RelatedSection {
                            objectName: "entityRelatedSection_" + modelData.attr
                            objectPrefix: "entityRelated_" + modelData.attr
                            section: modelData.section
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Tokens.px(root.islandTokens, "space.md", 16)
                Layout.rightMargin: Tokens.px(root.islandTokens, "space.md", 16)
                Layout.bottomMargin: Tokens.px(root.islandTokens, "space.md", 16)

                ThemeButton {
                    objectName: "entityOpenSheetButton"
                    visible: entityCardVm.characterSheetAvailable
                    text: "Открыть чар-лист"
                    onClicked: entityCardVm.requestCharacterSheet()
                }
                Item { Layout.fillWidth: true }
                ThemeButton {
                    id: saveButton
                    objectName: "entitySaveButton"
                    text: "Сохранить"
                    accentBackground: true
                    enabled: entityCardVm.saveEnabled
                    onClicked: entityCardVm.requestSave()
                }
                ThemeButton {
                    objectName: "entityCancelButton"
                    text: "Отмена"
                    enabled: !entityCardVm.saving
                    onClicked: entityCardVm.requestCancel()
                }
            }
        }
    }
}
