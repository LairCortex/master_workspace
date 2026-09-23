// Unified five-sheet .xlsx import island (rework-xlsx-import, task 4.2).
//
// The state machine lives in `xlsxImportVm` (idle → analyzing → problems →
// importing → done); this file only renders it: hint block (text generated
// from the schema registry, never spelled out here), file row with the
// «Скачать шаблон» button, the pre-analysis problem list (sheet/row/reason),
// the progress bar while importing and the final report panel. Fatal analysis
// issues block the primary button through `canImport`.
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
    readonly property color fgColor: Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color mutedColor: Tokens.token(islandTokens, "color.fg.muted", "gray")

    color: surfaceColor
    implicitWidth: 620
    implicitHeight: 560

    function issuesShown() {
        return xlsxImportVm.state !== "done" && xlsxImportVm.analysisIssues.length > 0
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Tokens.px(root.islandTokens, "space.md", 16)
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        TitleText {
            objectName: "formatTitle"
            text: "Требования к файлу:"
        }

        ThemeTextArea {
            objectName: "formatArea"
            Layout.fillWidth: true
            Layout.preferredHeight: 150
            readOnly: true
            mono: true
            text: xlsxImportVm.formatText
            // nri-0012 task 3.4 (usage-site name, design map).
            Accessible.name: "Требования к формату файла"
        }

        RowLayout {
            Layout.fillWidth: true
            TitleText { text: "Файл:" }
            ThemeField {
                id: pathField
                objectName: "pathField"
                Layout.fillWidth: true
                placeholderText: "Выберите .xlsx файл…"
                // nri-0012 task 3.4: the typed path rides the value slot; the
                // name slot carries the field's purpose (the browse button is
                // named by its own text next to it).
                Accessible.name: "Путь к файлу .xlsx"
                text: xlsxImportVm.path
                onTextChanged: xlsxImportVm.path = text
            }
            ThemeButton {
                objectName: "browseButton"
                text: "Обзор…"
                onClicked: xlsxImportVm.requestBrowse()
            }
            ThemeButton {
                objectName: "downloadButton"
                text: "Скачать шаблон"
                // The save--as flow attaches to this signal in task 5.2 —
                // the island's side of the seam is done here.
                onClicked: xlsxImportVm.requestDownloadTemplate()
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

        // ── pre-analysis problem list (sheet / row / reason) ─────────────
        Rectangle {
            objectName: "issueFrame"
            visible: root.issuesShown()
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredHeight: 150
            radius: Tokens.px(root.islandTokens, "radius.sm", 6)
            color: root.canvasColor
            border.color: root.borderColor
            border.width: 1
            clip: true

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Tokens.px(root.islandTokens, "space.sm", 8)
                spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                TitleText {
                    objectName: "issuesTitle"
                    text: "Проблемы пред-анализа (импорт пропустит эти строки):"
                    visible: !xlsxImportVm.hasFatal
                }
                TitleText {
                    objectName: "fatalTitle"
                    text: "Фатальные ошибки файла — импорт невозможен:"
                    visible: xlsxImportVm.hasFatal
                }

                ListView {
                    id: issueList
                    objectName: "issueList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: xlsxImportVm.analysisIssues
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                    delegate: Rectangle {
                        id: issueRow
                        required property var modelData
                        objectName: "issueRow"
                        width: issueList.width
                        height: issueRowLayout.implicitHeight
                        color: "transparent"

                        RowLayout {
                            id: issueRowLayout
                            anchors.left: parent.left
                            anchors.right: parent.right
                            spacing: Tokens.px(root.islandTokens, "space.sm", 8)

                            HintText {
                                objectName: "issueSheetText"
                                text: issueRow.modelData.sheet === "" ? "файл"
                                                       : "лист «" + issueRow.modelData.sheet + "»"
                            }
                            HintText {
                                objectName: "issueRowNumberText"
                                text: issueRow.modelData.row > 0 ? "строка " + issueRow.modelData.row : "—"
                            }
                            Text {
                                objectName: "issueReasonText"
                                Layout.fillWidth: true
                                text: (issueRow.modelData.fatal ? "Фатально: " : "")
                                      + issueRow.modelData.reason
                                wrapMode: Text.WordWrap
                                font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                                color: issueRow.modelData.fatal ? root.accentColor : root.fgColor
                            }
                        }
                    }
                }
            }
        }

        // ── final report panel (created/updated/links/skipped/…) ──────────
        Flickable {
            objectName: "reportArea"
            // `report` arrives as QML `undefined` until the import finishes
            // (Python None has no strict-null identity across the bridge), so
            // every report read below goes through the plain truthiness test.
            visible: xlsxImportVm.state === "done" && !!xlsxImportVm.report
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredHeight: 150
            contentHeight: reportColumn.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            clip: true

            ColumnLayout {
                id: reportColumn
                width: parent.width
                spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                TitleText {
                    objectName: "reportTitle"
                    text: "Импорт завершён"
                }
                Text {
                    objectName: "reportCreatedText"
                    text: "Создано: " + (xlsxImportVm.report ? xlsxImportVm.report.created : 0)
                    font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                    color: root.fgColor
                }
                Text {
                    objectName: "reportUpdatedText"
                    text: "Обновлено: " + (xlsxImportVm.report ? xlsxImportVm.report.updated : 0)
                    font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                    color: root.fgColor
                }
                Text {
                    objectName: "reportLinksText"
                    text: "Связей: " + (xlsxImportVm.report ? xlsxImportVm.report.links : 0)
                    font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                    color: root.fgColor
                }
                Text {
                    objectName: "reportSkippedTitle"
                    text: "Пропущено строк: "
                          + (xlsxImportVm.report ? xlsxImportVm.report.skipped.length : 0)
                    font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                    color: root.fgColor
                    visible: !!xlsxImportVm.report && xlsxImportVm.report.skipped.length > 0
                }
                Repeater {
                    objectName: "reportSkippedRepeater"
                    model: xlsxImportVm.report ? xlsxImportVm.report.skipped : []
                    delegate: HintText {
                        required property var modelData
                        objectName: "reportSkippedRowText"
                        text: "лист «" + modelData.sheet + "», строка " + modelData.row
                              + ": " + modelData.reason
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                    }
                }
                // ── перенесённые в календаре игры даты (C3a): only shifted
                // dates get a row, so the section hides on a standard game ──
                Text {
                    objectName: "reportDateShiftTitle"
                    text: "Перенесённые даты: "
                          + (xlsxImportVm.report ? xlsxImportVm.report.dateShifts.length : 0)
                    font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                    color: root.fgColor
                    visible: !!xlsxImportVm.report && xlsxImportVm.report.dateShifts.length > 0
                }
                Repeater {
                    objectName: "reportDateShiftRepeater"
                    model: xlsxImportVm.report ? xlsxImportVm.report.dateShifts : []
                    delegate: HintText {
                        required property var modelData
                        objectName: "reportDateShiftText"
                        text: "лист «" + modelData.sheet + "», строка " + modelData.row
                              + ": «" + modelData.field + "» " + modelData.old
                              + " → " + modelData.new
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                    }
                }
                Repeater {
                    objectName: "reportDecisionRepeater"
                    model: xlsxImportVm.report ? xlsxImportVm.report.decisions : []
                    delegate: HintText {
                        required property var modelData
                        objectName: "reportDecisionText"
                        text: "Решение: " + modelData
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                    }
                }
                Repeater {
                    objectName: "reportWarningRepeater"
                    model: xlsxImportVm.report ? xlsxImportVm.report.warnings : []
                    delegate: HintText {
                        required property var modelData
                        objectName: "reportWarningText"
                        text: "Предупреждение: " + modelData
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            ThemeButton {
                id: importButton
                objectName: "importButton"
                text: xlsxImportVm.state === "done" ? "Закрыть"
                    : xlsxImportVm.state === "problems" ? "Импортировать"
                    : "Проверить…"
                accentBackground: true
                enabled: xlsxImportVm.state === "done" || xlsxImportVm.canImport
                onClicked: {
                    if (xlsxImportVm.state === "done")
                        root.cancelRequested()
                    else if (xlsxImportVm.state === "problems")
                        xlsxImportVm.requestConfirmImport()
                    else
                        xlsxImportVm.requestAnalyze()
                }
            }
            ThemeButton {
                objectName: "cancelButton"
                text: xlsxImportVm.state === "done" ? "Закрыть" : "Отмена"
                onClicked: root.cancelRequested()
            }
        }
    }

    signal cancelRequested()
}
