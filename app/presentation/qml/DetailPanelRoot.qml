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
    // The selection pair of the skin (NRI-0022 task 3.1): the accent fills
    // the row wash exactly as the timeline's selection wash does, the
    // accent.fg text rank reads on top of it.
    readonly property color accentColor:
        Tokens.token(root.islandTokens, "color.accent", "black")
    readonly property color accentFgColor:
        Tokens.token(root.islandTokens, "color.accent.fg", "white")

    color: root.surfaceColor
    implicitWidth: 280
    implicitHeight: 400

    // Enter on the row in focus opens the editable card (NRI-0022 task 3.3,
    // design D3): the key event bubbles from the focused delegate up to the
    // list's Keys.onReturnPressed; the Window focus read is taken INLINE in
    // the handler (the attached property only resolves in the handler's own
    // scope, Qt 6.10 probe) and names the row to the shared rule below.
    // Anything else in focus (the list itself, no row) leaves the key alone.
    function openCardOnReturn(row, event) {
        if (row && row.entityType !== undefined) {
            event.accepted = true
            detailPanelVm.activate(row.entityType, row.entityId)
        }
    }

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
            property bool rowSelected: model.selected

            // Rows join the keyboard tab chain (NRI-0022 task 3.3): a real
            // user can focus one and press Enter for the card; the same flag
            // is what exposes the accessibility SetFocus action (Qt 6.10
            // probe: only focusable items carry it in the offscreen tree).
            activeFocusOnTab: true

            width: ListView.view.width
            height: Math.max(64, content.implicitHeight + 16)
            tintColor: ratingTint

            // Accessibility contract (change nri-0012-qml-accessibility,
            // task 2.2, design D2/D3; the action of the Press changed in
            // change nri-0022-entity-preview, task 3.1): a card row is a
            // list item named by the entity name; a single Press now runs
            // the single selection — the very step the single mouse click
            // drives — while the card itself opens on Enter (task 3.3) and
            // on the mouse double-click. The description follows the Press
            // (task 7.1): «Выбирает сущность» names what the activation
            // actually does now — the row left «Открывает карточку», which
            // the fixed map keeps only as vocabulary (spec qml-accessibility
            // «Скрытый смысл активации описан в дереве»).
            Accessible.role: Accessible.ListItem
            Accessible.name: rowCard.entityName
            Accessible.description: "Выбирает сущность"
            Accessible.onPressAction: detailPanelVm.select(
                rowCard.entityType, rowCard.entityId
            )

            // The selection wash (NRI-0022 task 3.1): the row's accent fill
            // with the same radius.sm rounding the timeline wash carries
            // (live fix 2026-09-26) — the VM delivers the state in the
            // ``selected`` role, this file only paints. Declared before the
            // content so it sits over the card's rating tint and under the
            // texts; a bare Rectangle never takes the mouse, the row
            // MouseArea at the bottom keeps receiving the clicks.
            Rectangle {
                objectName: "detailRowWash"
                anchors.fill: parent
                anchors.margins: 1  // inside the card's 1px border, like the tint
                visible: rowCard.rowSelected
                color: root.accentColor
                radius: Tokens.px(root.islandTokens, "radius.sm", 6)
            }

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
                        color: rowCard.rowSelected ? root.accentFgColor : root.primaryText
                        font.bold: true
                        font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                        elide: Text.ElideRight
                    }

                    Text {
                        objectName: "detailEntitySummary"
                        Layout.fillWidth: true
                        text: rowCard.summaryText
                        color: rowCard.rowSelected ? root.accentFgColor : root.secondaryText
                        textFormat: Text.RichText
                        wrapMode: Text.WordWrap
                        font.pixelSize: Tokens.px(root.islandTokens, "font.size.sm", 11)
                    }
                }
            }

            MouseArea {
                anchors.fill: parent
                z: -1
                // Single click selects (NRI-0022 task 3.1); the double-click
                // still opens the editable card. The picture's own MouseArea
                // sits above in the stacking order and accepts its clicks,
                // so a picture click stays the viewer gesture (design D3
                // risk row: the selection never douses it).
                onClicked: detailPanelVm.select(
                    rowCard.entityType, rowCard.entityId
                )
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
                // NRI-0022 task 3.2 (design D3): a tab switch hides the row
                // wash — screen state — while the VM keeps the remembered
                // selection and the preview behind its signal untouched.
                onCurrentIndexChanged: detailPanelVm.hideRowHighlight()

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
                    // NRI-0022 task 3.3: Enter on the row in focus opens the
                    // editable card (the pre-existing activate path); the
                    // focus read stays inline here — see root.openCardOnReturn.
                    Keys.onReturnPressed: function (event) {
                        root.openCardOnReturn(Window.activeFocusItem, event)
                    }
                }
                ListView {
                    objectName: "characterList"
                    model: detailPanelVm.characters
                    delegate: detailRowDelegate
                    clip: true
                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)
                    boundsBehavior: Flickable.StopAtBounds
                    // NRI-0022 task 3.3: Enter on the row in focus opens the
                    // editable card (the pre-existing activate path); the
                    // focus read stays inline here — see root.openCardOnReturn.
                    Keys.onReturnPressed: function (event) {
                        root.openCardOnReturn(Window.activeFocusItem, event)
                    }
                }
                ListView {
                    objectName: "itemList"
                    model: detailPanelVm.items
                    delegate: detailRowDelegate
                    clip: true
                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)
                    boundsBehavior: Flickable.StopAtBounds
                    // NRI-0022 task 3.3: Enter on the row in focus opens the
                    // editable card (the pre-existing activate path); the
                    // focus read stays inline here — see root.openCardOnReturn.
                    Keys.onReturnPressed: function (event) {
                        root.openCardOnReturn(Window.activeFocusItem, event)
                    }
                }
                ListView {
                    objectName: "locationList"
                    model: detailPanelVm.locations
                    delegate: detailRowDelegate
                    clip: true
                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)
                    boundsBehavior: Flickable.StopAtBounds
                    // NRI-0022 task 3.3: Enter on the row in focus opens the
                    // editable card (the pre-existing activate path); the
                    // focus read stays inline here — see root.openCardOnReturn.
                    Keys.onReturnPressed: function (event) {
                        root.openCardOnReturn(Window.activeFocusItem, event)
                    }
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
