// LlmSetupRoot — the LLM setup wizard island (change
// port-llm-event-types-qml-r3, design D3/D4).
//
// The island only displays `llmSetupVm` and emits synchronous requests: the
// HTTP client, the provider and `check_connection` stay on the QDialog
// facade. Entity/field prompt pages are built by a Repeater over the VM's
// model, which the Python side derives from FIELD_CONFIG — no second list of
// field names lives here (spec llm-configuration «Поля выводятся из
// единственного источника»).
import QtQuick
import QtQuick.Layouts
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "llmSetupRoot"

    readonly property Item defaultButton: saveButton

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor: Tokens.token(islandTokens, "color.bg.surface", "white")
    readonly property color mutedColor: Tokens.token(islandTokens, "color.fg.muted", "gray")
    readonly property color okColor: Tokens.token(islandTokens, "color.status.ok", "black")
    readonly property color errorColor: Tokens.token(islandTokens, "color.danger", "black")

    // nri-0016 LS4: the field's accessibility caption is a root constant.
    // Live cocoa fact (DEFECT-LS4 re-diagnosis, QA 2026-09-25): Qt zeroes
    // Accessible.name of a password field the moment an AT attaches (and a
    // helper text put into Accessible.description is overwritten by the
    // placeholder), while the placeholder itself is maintained by Qt into
    // the slot assistive tools fall back to. So the placeholder IS the
    // caption — «Ключ API» is what every reader path shows; the explanatory
    // hint lives in its own HintText next to the field.
    readonly property string apiKeyFieldName: "Ключ API"

    color: surfaceColor
    implicitWidth: 640
    implicitHeight: 480

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Tokens.px(root.islandTokens, "space.md", 16)
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        StackLayout {
            objectName: "pageStack"
            currentIndex: llmSetupVm.currentPage
            Layout.fillWidth: true
            Layout.fillHeight: true

            ColumnLayout {
                objectName: "connectionPage"
                spacing: Tokens.px(root.islandTokens, "space.sm", 8)

                TitleText { text: "Шаг 1: Подключение к LLM" }

                HintText {
                    objectName: "endpointHint"
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    elide: Text.ElideNone
                    text: "Поддерживаются любые OpenAI-совместимые серверы:\n"
                        + "• OpenAI: https://api.openai.com/v1\n"
                        + "• Ollama: http://localhost:11434/v1\n"
                        + "• vLLM: http://host:8000/v1\n"
                        + "• LM Studio: http://localhost:1234/v1"
                }

                GridLayout {
                    columns: 2
                    columnSpacing: Tokens.px(root.islandTokens, "space.sm", 8)
                    rowSpacing: Tokens.px(root.islandTokens, "space.xs", 4)
                    Layout.fillWidth: true

                    TitleText { text: "Endpoint:" }
                    ThemeField {
                        objectName: "endpointField"
                        Layout.fillWidth: true
                        placeholderText: "Базовый URL до /v1, например https://api.openai.com/v1"
                            + " или http://localhost:11434/v1 (Ollama)"
                        text: llmSetupVm.endpoint
                        // nri-0012 task 3.2 (usage-site name, design map): the
                        // typed URL lives in the value slot; the name slot
                        // carries the field's purpose.
                        Accessible.name: "Endpoint"
                        onTextChanged: llmSetupVm.endpoint = text
                    }

                    TitleText { text: "Модель:" }
                    ThemeField {
                        objectName: "modelField"
                        Layout.fillWidth: true
                        placeholderText: "Название модели, например gpt-4o-mini или llama3"
                        text: llmSetupVm.model
                        Accessible.name: "Модель"
                        onTextChanged: llmSetupVm.model = text
                    }

                    TitleText { text: "Ключ API:" }
                    ThemeField {
                        objectName: "keyField"
                        Layout.fillWidth: true
                        echoPassword: true
                        placeholderText: root.apiKeyFieldName
                        text: llmSetupVm.apiKey
                        // LS4: the name slot takes the root's stable caption,
                        // never a hint (see the apiKeyFieldName comment for
                        // why the placeholder carries the same caption).
                        Accessible.name: root.apiKeyFieldName
                        onTextChanged: llmSetupVm.apiKey = text
                    }
                    // The explanation the placeholder used to carry lives in
                    // plain text now (LS4 re-diagnosis: the placeholder IS the
                    // accessible caption for this field).
                    HintText {
                        objectName: "apiKeyHint"
                        Layout.columnSpan: 2
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        elide: Text.ElideNone
                        text: "Необязательно для локальных серверов."
                    }
                }

                ThemeButton {
                    objectName: "checkButton"
                    Layout.fillWidth: true
                    Layout.minimumHeight: 36
                    text: "Проверить соединение"
                    enabled: llmSetupVm.checkEnabled
                    onClicked: llmSetupVm.requestCheck()
                }

                Text {
                    objectName: "checkStatusText"
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                    text: llmSetupVm.checkText
                    color: llmSetupVm.checkStatus === "ok"
                        ? root.okColor
                        : llmSetupVm.checkStatus === "error" ? root.errorColor : root.mutedColor
                }

                Item { Layout.fillHeight: true }
            }

            ColumnLayout {
                objectName: "worldPage"
                spacing: Tokens.px(root.islandTokens, "space.sm", 8)

                TitleText { text: "Шаг 2: Описание мира" }

                HintText {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    elide: Text.ElideNone
                    text: "Опишите мир, в котором вы водите: сеттинг, эпоха, стиль, ключевые"
                        + " особенности.\nЭтот текст будет основным контекстом для всех"
                        + " AI-генераций."
                }

                ThemeTextArea {
                    objectName: "worldPromptArea"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    placeholderText: "Опишите ваш мир: сеттинг, эпоха, стиль, ключевые особенности..."
                    text: llmSetupVm.worldPrompt
                    // nri-0012 task 3.2: the world-description zone of the map.
                    Accessible.name: "Описание мира"
                    onTextChanged: llmSetupVm.worldPrompt = text
                }
            }

            Repeater {
                model: llmSetupVm.fieldPages

                ColumnLayout {
                    id: fieldPage
                    objectName: "fieldPromptsPage_" + fieldPage.pageData.entityType
                    spacing: Tokens.px(root.islandTokens, "space.sm", 8)

                    readonly property var pageData: modelData
                    readonly property int pageIndex: index

                    TitleText { text: fieldPage.pageData.title }

                    HintText {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        elide: Text.ElideNone
                        text: "Для каждого поля можно задать инструкцию для AI."
                            + " Пустое поле — используется только название поля."
                    }

                    // NRI-0016 LS1 (spec «Подпись стоит у своего поля», design
                    // V5): ONE Repeater whose row delegate paints the label and
                    // its own field side by side (row objectName
                    // «fieldPromptRow_<etype>_<field>» is the test seam). The
                    // two Repeaters before put ALL labels into the left column
                    // and ALL fields into the right one, so with a few rows a
                    // label visually faced another setting's field on every
                    // field page.
                    Repeater {
                        model: fieldPage.pageData.fields

                        RowLayout {
                            objectName: "fieldPromptRow_" + fieldPage.pageData.entityType
                                + "_" + modelData.name
                            Layout.fillWidth: true
                            spacing: Tokens.px(root.islandTokens, "space.sm", 8)

                            // Test-seam pair of the row: the label and the
                            // field share the «_<etype>_<field>» suffix, so a
                            // tree walk can read the alternation and compare
                            // the painted caption with the field's name slot.
                            TitleText {
                                objectName: "fieldPromptLabel_" + fieldPage.pageData.entityType
                                    + "_" + modelData.name
                                text: modelData.label + ":"
                            }

                            ThemeField {
                                objectName: "fieldPrompt_" + fieldPage.pageData.entityType
                                    + "_" + modelData.name
                                Layout.fillWidth: true
                                placeholderText: modelData.placeholder
                                text: modelData.value
                                // nri-0012 task 3.2: the row binds the field's
                                // name to the very model label its own
                                // TitleText paints (D4: label is a binding).
                                Accessible.name: modelData.label
                                onTextChanged: llmSetupVm.setFieldValue(
                                    fieldPage.pageIndex, index, text)
                            }
                        }
                    }

                    Item { Layout.fillHeight: true }
                }
            }

            ColumnLayout {
                objectName: "warningsPage"
                spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                TitleText { text: "Информация" }

                Repeater {
                    model: [
                        "• LLM будет редактировать и дополнять ваш текст на основе описания мира.",
                        "• Генерация выполняется по одному полю за раз. Если запущено несколько —"
                            + " они встанут в очередь и будут обработаны последовательно.",
                        "• Во время генерации поле будет заблокировано, а окно нельзя будет закрыть.",
                        "• Ключ API хранится в локальном файле ~/.nri_manager/llm_config.json"
                            + " (права 0600, только текущий пользователь).",
                    ]

                    HintText {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        elide: Text.ElideNone
                        text: modelData
                    }
                }

                Item { Layout.fillHeight: true }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Tokens.px(root.islandTokens, "space.sm", 8)

            ThemeButton {
                objectName: "backButton"
                text: "Назад"
                enabled: llmSetupVm.backEnabled
                onClicked: llmSetupVm.goBack()
            }
            Item { Layout.fillWidth: true }
            // NRI-0016 LS2 (spec «Оконный формат wizard с постоянным выходом
            // и счётчиком»): the page index and the exit live OUTSIDE the
            // StackLayout, so every page — including the field-prompt pages —
            // shows «N из M» and «Закрыть»; the buttons inside the pages only
            // navigate or explicitly save.
            Text {
                objectName: "pageCounterLabel"
                font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                color: root.mutedColor
                text: (llmSetupVm.currentPage + 1) + " из " + llmSetupVm.pageCount
            }
            ThemeButton {
                objectName: "nextButton"
                text: "Далее"
                visible: llmSetupVm.nextVisible
                onClicked: llmSetupVm.goNext()
            }
            ThemeButton {
                id: saveButton
                objectName: "saveButton"
                text: "Сохранить и закрыть"
                accentBackground: true
                visible: llmSetupVm.saveVisible
                enabled: llmSetupVm.saveEnabled
                onClicked: llmSetupVm.requestSave()
            }
            ThemeButton {
                objectName: "setupCloseButton"
                text: "Закрыть"
                // D4's running-save rule stays: while the async save is in
                // flight the window cannot leave (the same gate Esc and the
                // native close meet) — no silently inert button.
                enabled: !llmSetupVm.saving
                onClicked: llmSetupVm.requestClose()
            }
        }
    }
}
