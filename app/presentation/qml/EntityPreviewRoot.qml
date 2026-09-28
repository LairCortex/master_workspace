// Entity preview island — the readable right column (change
// nri-0022-entity-preview, tasks 4.1–4.5).
//
// Read-only by contract (spec entity-preview «Состав читаемого предпросмотра»):
// no TextField, no Button, no edit gesture anywhere — the only interactive
// elements are the picture (opens the viewer, the detail-row contract) and
// the navigation channels: relation rows (the library RowItem) and the
// mention anchors inside the rich-text sections (onLinkActivated → the same
// selection bus). The VM answers every text already render-ready; this file
// only paints and forwards the two activation gestures.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import nri.components
import "nri/components/tokens.js" as Tokens
import "nri/components/panelHeader.js" as PanelHeader

Rectangle {
    id: root
    objectName: "entityPreviewRoot"
    implicitWidth: 420
    implicitHeight: 520

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor:
        Tokens.token(root.islandTokens, "color.bg.surface", "white")
    readonly property color canvasColor:
        Tokens.token(root.islandTokens, "color.bg.canvas", "white")
    readonly property color primaryText:
        Tokens.token(root.islandTokens, "color.fg.primary", "black")
    readonly property color secondaryText:
        Tokens.token(root.islandTokens, "color.fg.secondary", "gray")
    readonly property color mutedColor:
        Tokens.token(root.islandTokens, "color.fg.muted", "gray")
    readonly property color borderColor:
        Tokens.token(root.islandTokens, "color.border", "lightgray")
    // The mention anchors read as the skin's accent (compiler.mention_style's
    // island counterpart: the RichText label colours its links through the
    // Text.linkColor token, so a live retheme repaints without a re-render).
    readonly property color accentColor:
        Tokens.token(root.islandTokens, "color.accent", "black")
    // The readability step-up (the reader's request 2026-09-28): every
    // readable line of the card — the short fields, the section bodies, the
    // music link — rides two px above the skin's md text, so the preview
    // stays legible while the titles keep the shared library look.
    readonly property int bodyFontPixelSize:
        Tokens.px(root.islandTokens, "font.size.md", 13) + 2

    color: root.surfaceColor

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Tokens.px(root.islandTokens, "space.xs", 4)
        spacing: Tokens.px(root.islandTokens, "space.xs", 4)

        // The column header rides the shared panel-header band (panelHeader.js):
        // the preview is the main window's right column now, its caption
        // seats on the same axis as the timeline title and the detail tab
        // strip (live fix 2026-09-26 rule). The band is the card's ONLY
        // headline (the reader's fix 2026-09-28): «Карточка» while the column
        // is empty, «Карточка: <русское имя типа из реестра>» while one is
        // shown — the VM answers both halves, no second «Карточка…» line
        // lives inside, the entity's own name stays a field of the card.
        Item {
            objectName: "previewHeaderBand"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            implicitHeight: PanelHeader.band()
            Layout.preferredHeight: implicitHeight

            TitleText {
                objectName: "previewBandTitle"
                text: entityPreviewVm.title
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
            }
        }

        CardPanel {
            objectName: "previewCanvas"
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: root.canvasColor
            clip: true

            // Long text scrolls (task 4.2 «прокрутка длинного текста»): the
            // whole composition is one column inside this flickable; the
            // canvas clips it.
            Flickable {
                id: previewScroll
                objectName: "previewScroll"
                anchors.fill: parent
                anchors.margins: 1  // keep content off the 1px border
                contentWidth: width
                contentHeight: previewContent.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                visible: entityPreviewVm.hasEntity

                ColumnLayout {
                    id: previewContent
                    objectName: "previewContent"
                    width: previewScroll.width
                    spacing: Tokens.px(root.islandTokens, "space.sm", 8)

                    // The identity band (live fix 2026-09-27, the reader's
                    // sketch): the picture seats top-left, the short lines
                    // (name, rating, dates, age) read to its right, and only
                    // below them do the long text sections, the music and the
                    // relation blocks run full width.
                    RowLayout {
                        id: previewIdentityRow
                        objectName: "previewIdentityRow"
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

                        // The picture slot (task 4.3): the preview copy through
                        // the shared image_utils pipeline; a null pixmap arrives
                        // here as an empty imageSource and the placeholder paints.
                        // It takes exactly half of the band and scales with the
                        // column (the reader's sketch, live fix 2026-09-28), the
                        // portrait 4:3 proportion keeping the tall look as the
                        // width grows; the QML Image paints the ≤512-px preview
                        // file scaled, so the growth stays smooth.
                        Item {
                            id: previewImageSlot
                            objectName: "previewImageBlock"
                            Layout.preferredWidth: Math.round(previewIdentityRow.width / 2)
                            Layout.preferredHeight: Math.round(previewImageSlot.width * 4 / 3)
                            Layout.alignment: Qt.AlignTop
                            // The block belongs to the shown entity: while a card
                            // is up its picture slot always paints — the preview
                            // copy, or the «Нет изображения» placeholder inside.
                            visible: entityPreviewVm.hasEntity

                            Image {
                                id: previewImage
                                objectName: "previewImage"
                                anchors.fill: parent
                                source: entityPreviewVm.imageSource
                                fillMode: Image.PreserveAspectFit
                                asynchronous: true
                                visible: entityPreviewVm.imageSource !== ""
                                // Accessibility: the same picture contract as the
                                // detail row — the named «open the image» button
                                // (the detail-panel design map), the MouseArea
                                // below stays the mouse path.
                                Accessible.role: Accessible.Button
                                Accessible.name: entityPreviewVm.nameText !== ""
                                    ? entityPreviewVm.nameText : "Изображение"
                                Accessible.description: "Открыть изображение"
                                Accessible.onPressAction: entityPreviewVm.requestImage()
                            }

                            HintText {
                                objectName: "previewImagePlaceholder"
                                anchors.centerIn: parent
                                text: "Нет изображения"
                                italic: true
                                visible: entityPreviewVm.imageSource === ""
                            }

                            MouseArea {
                                objectName: "previewImageMouseArea"
                                anchors.fill: parent
                                enabled: entityPreviewVm.imageSource !== ""
                                visible: enabled
                                cursorShape: Qt.PointingHandCursor
                                onClicked: entityPreviewVm.requestImage()
                            }
                        }

                        // The short lines beside the picture: they wrap rather
                        // than elide, the narrow band must never hide a date.
                        ColumnLayout {
                            objectName: "previewFactsColumn"
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignTop
                            spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                            TitleText {
                                objectName: "previewName"
                                Layout.fillWidth: true
                                text: entityPreviewVm.nameText
                                visible: text !== ""
                                elide: Text.ElideNone
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                objectName: "previewRating"
                                Layout.fillWidth: true
                                text: entityPreviewVm.ratingText
                                visible: text !== ""
                                color: root.secondaryText
                                font.pixelSize: root.bodyFontPixelSize
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                objectName: "previewDates"
                                Layout.fillWidth: true
                                text: entityPreviewVm.dateText
                                visible: text !== ""
                                color: root.secondaryText
                                font.pixelSize: root.bodyFontPixelSize
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                objectName: "previewAge"
                                Layout.fillWidth: true
                                text: entityPreviewVm.ageText
                                visible: text !== ""
                                color: root.secondaryText
                                font.pixelSize: root.bodyFontPixelSize
                                wrapMode: Text.WordWrap
                            }
                        }
                    }

                    // The text fields (Характеристики / Предыстория /
                    // Личность / Задачи) with clickable @mentions: the VM
                    // delivers each as the mention_html generator's anchors;
                    // a click hands the href to requestLink, which navigates
                    // generated anchors only (task 4.5).
                    Repeater {
                        model: entityPreviewVm.sections

                        ColumnLayout {
                            id: previewSection
                            objectName: "previewSection_" + modelData.key
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                            TitleText {
                                objectName: "previewSectionLabel"
                                Layout.fillWidth: true
                                text: previewSection.modelData.label + ":"
                            }

                            Text {
                                objectName: "previewSectionText"
                                Layout.fillWidth: true
                                text: previewSection.modelData.html
                                textFormat: Text.RichText
                                wrapMode: Text.WordWrap
                                color: root.primaryText
                                linkColor: root.accentColor
                                font.pixelSize: root.bodyFontPixelSize
                                onLinkActivated: function (link) {
                                    entityPreviewVm.requestLink(link)
                                }
                            }
                        }
                    }

                    TitleText {
                        objectName: "previewMusicLabel"
                        Layout.fillWidth: true
                        text: "Музыка:"
                        visible: entityPreviewVm.musicUrl !== ""
                    }

                    Text {
                        objectName: "previewMusic"
                        Layout.fillWidth: true
                        text: entityPreviewVm.musicUrl
                        visible: text !== ""
                        color: root.secondaryText
                        wrapMode: Text.WrapAnywhere
                        font.pixelSize: root.bodyFontPixelSize
                    }

                    // Compact relation sections (task 4.4): one per registry
                    // relation the host actually has rows for — the VM drops
                    // the empty ones, so an empty block never reaches here.
                    Repeater {
                        model: entityPreviewVm.relatedSections

                        ColumnLayout {
                            id: previewRelatedSection
                            objectName: "previewRelatedSection_" + modelData.key
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                            TitleText {
                                objectName: "previewRelatedLabel"
                                Layout.fillWidth: true
                                text: previewRelatedSection.modelData.label + ":"
                            }

                            Repeater {
                                model: previewRelatedSection.modelData.rows

                                RowItem {
                                    objectName: "previewRelatedRow"
                                    required property var modelData
                                    Layout.fillWidth: true
                                    text: modelData.name
                                    // Accessibility contract: the library row
                                    // owns the ListItem role, the name is the
                                    // visible content, the usage-site spells
                                    // the hidden meaning of the activation —
                                    // both the mouse paths and the component's
                                    // single Press run the same navigation.
                                    accessibleDescription: "Переходит к сущности"
                                    onSelectedRequested: entityPreviewVm.requestEntity(
                                        modelData.type, modelData.id
                                    )
                                    onActivateRequested: entityPreviewVm.requestEntity(
                                        modelData.type, modelData.id
                                    )
                                }
                            }
                        }
                    }
                }
            }

            // The empty state explains itself (task 4.1, spec «Пустой
            // предпросмотр объясняет себя»): the muted hint names the action,
            // the column keeps its place (the splitter floor + non-collapsible
            // children are the Python half of the same rule).
            HintText {
                objectName: "previewEmptyHint"
                anchors.centerIn: parent
                visible: !entityPreviewVm.hasEntity
                text: "Выберите сущность в среднем столбце — здесь появится её карточка"
                italic: true
            }
        }
    }
}
