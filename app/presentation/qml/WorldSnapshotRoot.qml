import QtQuick
import QtQuick.Layouts
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "worldSnapshotRoot"
    implicitWidth: 420
    implicitHeight: 420

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor:
        Tokens.token(islandTokens, "color.bg.surface", "white")
    readonly property color canvasColor:
        Tokens.token(islandTokens, "color.bg.canvas", "white")
    readonly property color foregroundColor:
        Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color mutedColor:
        Tokens.token(islandTokens, "color.fg.muted", "gray")
    readonly property color borderColor:
        Tokens.token(islandTokens, "color.border", "lightgray")

    color: surfaceColor

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Tokens.px(root.islandTokens, "space.xs", 4)
        spacing: Tokens.px(root.islandTokens, "space.xs", 4)

        TitleText {
            objectName: "snapshotTitle"
            text: "Обзор мира"
            Layout.fillWidth: true
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Tokens.px(root.islandTokens, "space.xs", 4)

            HintText { text: "Дата:" }

            ThemeDateField {
                id: dateField
                objectName: "snapshotDateField"
                isoDate: worldSnapshotVm.dateIso
                display: worldSnapshotVm.dateDisplay
                Layout.fillWidth: true
                onClicked: {
                    const point = dateField.mapToItem(root, 0, 0)
                    worldSnapshotVm.requestDatePopup(
                        point.x, point.y, dateField.width, dateField.height)
                }
            }

            ThemeButton {
                objectName: "snapshotShowButton"
                text: "Показать"
                accentBackground: true
                onClicked: worldSnapshotVm.requestShow()
            }
            ThemeButton {
                objectName: "snapshotResetButton"
                text: "Сброс"
                enabled: worldSnapshotVm.clearEnabled
                onClicked: worldSnapshotVm.clear()
            }
            ThemeButton {
                objectName: "snapshotShowAllButton"
                text: "Показать всё"
                onClicked: worldSnapshotVm.requestShowAll()
            }
        }

        CardPanel {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: root.canvasColor
            clip: true

            ListView {
                id: snapshotList
                objectName: "snapshotList"
                anchors.fill: parent
                anchors.margins: 1
                model: worldSnapshotVm.rowModel
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                delegate: Item {
                    id: snapshotRow
                    required property int index
                    required property string rowKind
                    required property string sectionKey
                    required property string type
                    required property string displayText
                    required property string ratingHex
                    required property bool fontBold
                    required property string tooltipHtml
                    required property string iconText
                    required property string iconPath
                    required property int iconSize
                    required property bool expanded
                    required property bool selectable
                    property string entityType: type
                    objectName: rowKind === "sectionHeader"
                        ? "snapshotSectionRow" : "snapshotEntityRow"
                    width: snapshotList.width
                    height: rowKind === "sectionHeader" ? 36 : 34
                    Nri.tooltip: tooltipHtml

                    ThemeRatingCard {
                        anchors.fill: parent
                        visible: rowKind === "entityRow"
                        tintColor: ratingHex
                    }

                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: rowKind === "sectionHeader" ? 4 : 24
                        anchors.rightMargin: 8
                        spacing: 6

                        Item {
                            width: iconSize
                            height: parent.height

                            Image {
                                anchors.centerIn: parent
                                width: iconSize
                                height: iconSize
                                source: iconPath
                                fillMode: Image.PreserveAspectFit
                                visible: iconPath !== ""
                            }
                            Text {
                                anchors.centerIn: parent
                                text: iconText
                                font.pixelSize: iconSize * 0.7
                                visible: iconPath === ""
                            }
                        }

                        Text {
                            width: parent.width - x
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            text: rowKind === "sectionHeader"
                                ? (expanded ? "▾  " : "▸  ") + displayText
                                : displayText
                            color: root.foregroundColor
                            font.bold: fontBold
                            font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: rowKind === "sectionHeader" || selectable
                            ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: {
                            if (rowKind === "sectionHeader")
                                worldSnapshotVm.toggleSection(index)
                            else
                                worldSnapshotVm.select(index)
                        }
                    }

                    HoverHandler {
                        onHoveredChanged: {
                            if (hovered && snapshotRow.Nri.tooltip !== "")
                                tooltipBridge.tooltipRequested(
                                    snapshotRow.Nri.tooltip, point.scenePosition)
                            else
                                tooltipBridge.tooltipRequested("", Qt.point(0, 0))
                        }
                    }
                }
            }

            HintText {
                anchors.centerIn: parent
                visible: snapshotList.count === 0
                text: worldSnapshotVm.emptyText
                italic: true
            }
        }

        HintText {
            objectName: "snapshotStats"
            text: worldSnapshotVm.statsText
            visible: text !== ""
            Layout.fillWidth: true
        }
    }
}
