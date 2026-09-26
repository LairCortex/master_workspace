import QtQuick

ThemeButton {
    id: control

    // NRI-0018 Д1: the AI action is one of the small glyph actions, so it
    // wears the library's square gauge (spec «AI-кнопка SHALL сохранить своё
    // оформление и состояния («✨»/«…»), приняв фиксированный квадрат»): the
    // side is set WITHIN the component — no usage site states a size — and
    // the same constant as ThemeIconButton.qml (drift trips the pin in
    // tests/presentation/test_theme_icon_button.py). Zero padding centers the
    // glyph in the whole square so wide emoji never clip. Styling, states and
    // the observable aiState contract below are untouched.
    readonly property int side: 32

    width: side
    height: side
    implicitWidth: side
    implicitHeight: side

    padding: 0

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
