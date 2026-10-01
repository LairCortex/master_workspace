import QtQuick
import QtQuick.Layouts
import nri.components
import "nri/components/tokens.js" as Tokens
import "nri/components/panelHeader.js" as PanelHeader

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

        // The title rides the shared panel-header band (panelHeader.js, live
        // fix 2026-09-26): the same 32 px band and the same 4 px top margin
        // as the timeline header and the detail tab strip, with the caption
        // seated on the band's vertical center — before this the bare text
        // line hugged the top margin and read 7 px above the timeline title.
        // Anchors, not a nested layout, so a long caption elides at the
        // panel edge exactly like the timeline title does.
        Item {
            objectName: "snapshotHeaderBand"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            implicitHeight: PanelHeader.band()
            Layout.preferredHeight: implicitHeight

            TitleText {
                objectName: "snapshotTitle"
                text: "Обзор мира"
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
            }
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
                // nri-0017 1.1 (FI-1/M2): role+press came inside the library
                // component, so the usage-site name finally projects — the
                // field's purpose is the row label's word; the VM's
                // worst-form caption is the field's width floor.
                Accessible.name: "Дата"
                worstCaseText: worldSnapshotVm.worstCaseDisplay
                onClicked: {
                    const point = dateField.mapToItem(root, 0, 0)
                    worldSnapshotVm.requestDatePopup(
                        point.x, point.y, dateField.width, dateField.height)
                }
            }

            // No Lucide glyphs on this header's buttons (icon pass
            // 2026-09-30, measured offscreen at the root's real widths): the
            // date field's worst-case floor leaves «Показать всё» — the
            // OBS-1 clipper (docs/qa/2026-09-25-accessibility-audit.md) —
            // exactly zero slack. Offscreen probe: at the 520 px first-open
            // frame the row's right edge ends at 502/520 without glyphs and
            // at 522/542 (past the panel edge) once «Показать» and «Сброс»
            // take their 20 px each; at the audit's saved 1028 px frame the
            // pre-pass row already ends at 1024/1028, matching the observed
            // live clip. eye/refresh-ccw/list would each regress OBS-1, so
            // the whole row stays text-only — the same probe rule that kept
            // bring-to-front/send-to-back bare in SheetEditorRoot.qml.
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
                    required property string iconName
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

                    // Accessibility contract (change nri-0012-qml-accessibility,
                    // task 2.3, design map «WorldSnapshot строка»): the entity
                    // row is a list item whose Press runs the selection jump
                    // (vm.select(index) — the mouse's single-click channel);
                    // the section header is the expand/collapse button. Both
                    // names are the delivered displayText (the ▸/▾ glyph is
                    // paint, not the name). The MouseArea below stays the
                    // mouse path.
                    Accessible.role: rowKind === "sectionHeader"
                        ? Accessible.Button : Accessible.ListItem
                    Accessible.name: displayText
                    Accessible.description: rowKind === "sectionHeader"
                        ? "Развернуть или свернуть раздел" : "Переходит к сущности"
                    Accessible.onPressAction: {
                        if (rowKind === "sectionHeader")
                            worldSnapshotVm.toggleSection(index)
                        else
                            worldSnapshotVm.select(index)
                    }

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

                        // Disclosure glyph of the section header (Lucide pass
                        // 2026-09-30): the «▸/▾» that used to be typed into
                        // the caption — paint outside the name — is now the
                        // library ThemeIcon beside the section icon. Entity
                        // rows carry no chevron (always-visible leaves).
                        ThemeIcon {
                            visible: rowKind === "sectionHeader"
                            anchors.verticalCenter: parent.verticalCenter
                            name: expanded ? "chevron-down" : "chevron-right"
                            size: 14
                            tint: root.foregroundColor
                        }

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
                            // No photo — the section's Lucide glyph stands in
                            // (the old emoji Text fallback retired with it).
                            ThemeIcon {
                                anchors.centerIn: parent
                                visible: iconPath === ""
                                name: iconName
                                size: iconSize
                                tint: root.foregroundColor
                            }
                        }

                        Text {
                            width: parent.width - x
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            text: displayText
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
