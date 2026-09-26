import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import nri.components
import "nri/components/tokens.js" as Tokens
import "nri/components/panelHeader.js" as PanelHeader

Rectangle {
    id: root
    objectName: "detailPanelRoot"

    property alias currentTab: tabBar.currentIndex
    property alias organizationContentY: organizationList.contentY

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor:
        Tokens.token(root.islandTokens, "color.bg.surface", "white")
    readonly property color canvasColor:
        Tokens.token(root.islandTokens, "color.bg.canvas", "white")
    readonly property color borderColor:
        Tokens.token(root.islandTokens, "color.border", "lightgray")
    readonly property color primaryText:
        Tokens.token(root.islandTokens, "color.fg.primary", "black")
    readonly property color secondaryText:
        Tokens.token(root.islandTokens, "color.fg.secondary", "gray")

    color: root.surfaceColor
    implicitWidth: 280
    implicitHeight: 400

    Component {
        id: detailRowDelegate

        ThemeRatingCard {
            id: rowCard
            objectName: "detailEntityRow"
            property string entityName: model.name
            property string summaryText: model.summary
            property string entityType: model.entityType
            property int entityId: model.entityId
            property string imageSource: model.imageSource
            property color ratingTint: model.ratingTint

            width: ListView.view.width
            height: Math.max(64, content.implicitHeight + 16)
            tintColor: ratingTint

            // Accessibility contract (change nri-0012-qml-accessibility,
            // task 2.2, design D2/D3): a card row is a list item named by the
            // entity name; a single Press takes the double-click path — the
            // card open through the VM (accessibility has no double press).
            // The mouse MouseArea below stays untouched.
            Accessible.role: Accessible.ListItem
            Accessible.name: rowCard.entityName
            Accessible.description: "Открывает карточку"
            Accessible.onPressAction: detailPanelVm.activate(
                rowCard.entityType, rowCard.entityId
            )

            RowLayout {
                id: content
                anchors.fill: parent
                anchors.margins: Tokens.px(root.islandTokens, "space.sm", 8)
                spacing: Tokens.px(root.islandTokens, "space.sm", 8)

                Item {
                    visible: rowCard.imageSource !== ""
                    Layout.preferredWidth: visible ? 100 : 0
                    Layout.preferredHeight: visible ? 100 : 0

                    Image {
                        id: entityImage
                        objectName: "detailEntityImage"
                        anchors.fill: parent
                        source: rowCard.imageSource
                        fillMode: Image.PreserveAspectFit
                        asynchronous: true
                        // Accessibility (task 2.2): the picture is the
                        // «open the image» button; without an entity name the
                        // generic «Изображение» names it. The MouseArea beside
                        // it keeps driving the same VM call for the mouse.
                        Accessible.role: Accessible.Button
                        Accessible.name: rowCard.entityName !== ""
                            ? rowCard.entityName : "Изображение"
                        Accessible.description: "Открыть изображение"
                        Accessible.onPressAction: detailPanelVm.requestImage(
                            rowCard.entityType, rowCard.entityId
                        )
                    }

                    MouseArea {
                        objectName: "detailImageMouseArea"
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: detailPanelVm.requestImage(
                            rowCard.entityType, rowCard.entityId
                        )
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                    Text {
                        objectName: "detailEntityName"
                        Layout.fillWidth: true
                        text: rowCard.entityName
                        color: root.primaryText
                        font.bold: true
                        font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                        elide: Text.ElideRight
                    }

                    Text {
                        objectName: "detailEntitySummary"
                        Layout.fillWidth: true
                        text: rowCard.summaryText
                        color: root.secondaryText
                        textFormat: Text.RichText
                        wrapMode: Text.WordWrap
                        font.pixelSize: Tokens.px(root.islandTokens, "font.size.sm", 11)
                    }
                }
            }

            MouseArea {
                anchors.fill: parent
                z: -1
                onDoubleClicked: detailPanelVm.activate(
                    rowCard.entityType, rowCard.entityId
                )
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Tokens.px(root.islandTokens, "space.xs", 4)
        spacing: Tokens.px(root.islandTokens, "space.xs", 4)

        // The event-meta rows belong to a selected event: while nothing is
        // selected they stay empty, and an empty row still occupied its line
        // height + spacing, dropping the tab strip 41 px below the other two
        // column headers (live fix 2026-09-26). The VM already answers the
        // question — eventSelected — so the rows simply leave the layout
        // (invisible children are skipped by ColumnLayout) and never push
        // the strip down; a selected event grows the header block downward
        // above the strip, exactly like before.
        TitleText {
            objectName: "detailTitle"
            Layout.fillWidth: true
            visible: detailPanelVm.eventSelected
            text: detailPanelVm.title
        }

        Text {
            objectName: "detailDate"
            Layout.fillWidth: true
            visible: detailPanelVm.eventSelected
            text: detailPanelVm.dateText
            color: root.secondaryText
            font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
        }

        // The tab strip rides the shared panel-header band (panelHeader.js,
        // live fix 2026-09-26): the same 32 px band, the same 4 px top margin
        // and the band's vertical center as the timeline title and the
        // snapshot title, so all three column headers sit on one horizontal
        // line whether or not an event is selected. Anchors, not Layout
        // attributes — the strip keeps the whole width (the tabs share it)
        // and its own implicit height, centered in the band.
        Item {
            objectName: "detailTabBand"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            implicitHeight: PanelHeader.band()
            Layout.preferredHeight: implicitHeight

            ThemeTabBar {
                id: tabBar
                objectName: "detailTabBar"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                currentIndex: 0

                // NRI-0018 (Д5): the retired short captions — every tab wears the
                // registry's full plural again, as text, accessibility name AND
                // tooltip at once (spec main-window scenario «Подпись и имя
                // доступности одно»). The name stays annotated because the text-
                // derived name is the live-platform half only (AGENTS F4); the
                // bound-text control keeps the 4.1 convention guard silent.
                // NRI-0019: the retired width: implicitWidth (NRI-0015 M1 tail) —
                // the bar's row now shares its width between the tabs (ThemeTabBar),
                // so the whole column is used and a narrow column shortens the
                // captions with the ellipsis instead of clipping the strip.
                Repeater {
                    model: detailPanelVm.tabTitles
                    ThemeTabButton {
                        id: detailTab
                        objectName: "detailTab"
                        required property string modelData
                        required property int index
                        text: modelData
                        Accessible.name: detailPanelVm.tabTitles[index]
                        HoverHandler {
                            onHoveredChanged: tooltipBridge.tooltipRequested(
                                hovered ? detailPanelVm.tabTitles[index] : "",
                                point.scenePosition
                            )
                        }
                    }
                }
            }
        }

        // Tab pane: the frame that ties the list to the selected tab (the
        // widget QTabWidget drew it, the token tab strip does not).
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: Tokens.px(root.islandTokens, "radius.sm", 6)
            color: root.canvasColor
            border.color: root.borderColor
            border.width: 1
            clip: true

            StackLayout {
                id: stack
                objectName: "detailStack"
                anchors.fill: parent
                anchors.margins: 1  // keep rows off the 1px border
                currentIndex: tabBar.currentIndex

                ListView {
                    id: organizationList
                    objectName: "organizationList"
                    model: detailPanelVm.organizations
                    delegate: detailRowDelegate
                    clip: true
                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)
                    boundsBehavior: Flickable.StopAtBounds
                }
                ListView {
                    objectName: "characterList"
                    model: detailPanelVm.characters
                    delegate: detailRowDelegate
                    clip: true
                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)
                    boundsBehavior: Flickable.StopAtBounds
                }
                ListView {
                    objectName: "itemList"
                    model: detailPanelVm.items
                    delegate: detailRowDelegate
                    clip: true
                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)
                    boundsBehavior: Flickable.StopAtBounds
                }
                ListView {
                    objectName: "locationList"
                    model: detailPanelVm.locations
                    delegate: detailRowDelegate
                    clip: true
                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)
                    boundsBehavior: Flickable.StopAtBounds
                }
            }

            // NRI-0015 (M4, design T2): the emptiness explains itself with the
            // same muted hint face the timeline uses («Событий ещё нет»).
            HintText {
                objectName: "detailEmptyHint"
                anchors.centerIn: parent
                text: "Выберите строку — тут появятся детали"
                visible: !detailPanelVm.eventSelected
            }
        }
    }
}
