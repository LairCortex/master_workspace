import QtQuick

ThemeButton {
    id: control

    property var proxy: null
    property string entityType: ""
    property string fieldName: ""
    property string fieldLabel: ""
    property string current_text: proxy ? proxy.currentText : ""
    property string aiState: proxy ? proxy.aiState : "disabled"
    property bool isGenerating: proxy ? proxy.generating : false

    signal generate_requested(
        string entityType,
        string fieldName,
        string fieldLabel,
        string currentText
    )

    text: isGenerating ? "…" : "✨"
    accentBackground: aiState === "active"
    enabled: proxy ? proxy.clickable : !isGenerating

    onClicked: {
        generate_requested(entityType, fieldName, fieldLabel, current_text)
        if (proxy)
            proxy.requestGenerate()
    }
}
