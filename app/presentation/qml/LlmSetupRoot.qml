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

    color: surfaceColor
    implicitWidth: 620
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
                        onTextChanged: llmSetupVm.endpoint = text
                    }

                    TitleText { text: "Модель:" }
                    ThemeField {
                        objectName: "modelField"
                        Layout.fillWidth: true
                        placeholderText: "Название модели, например gpt-4o-mini или llama3"
                        text: llmSetupVm.model
                        onTextChanged: llmSetupVm.model = text
                    }

                    TitleText { text: "Ключ API:" }
                    ThemeField {
                        objectName: "keyField"
                        Layout.fillWidth: true
                        echoPassword: true
                        placeholderText: "Ключ API — необязательно для локальных серверов"
                        text: llmSetupVm.apiKey
                        onTextChanged: llmSetupVm.apiKey = text
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

                    GridLayout {
                        columns: 2
                        columnSpacing: Tokens.px(root.islandTokens, "space.sm", 8)
                        rowSpacing: Tokens.px(root.islandTokens, "space.xs", 4)
                        Layout.fillWidth: true

                        Repeater {
                            model: fieldPage.pageData.fields

                            TitleText { text: modelData.label + ":" }
                        }

                        Repeater {
                            model: fieldPage.pageData.fields

                            ThemeField {
                                objectName: "fieldPrompt_" + fieldPage.pageData.entityType
                                    + "_" + modelData.name
                                Layout.fillWidth: true
                                placeholderText: modelData.placeholder
                                text: modelData.value
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
        }
    }
}
