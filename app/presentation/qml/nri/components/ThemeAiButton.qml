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
    property bool isCancelling: proxy ? proxy.isCancelling : false

    signal generate_requested(
        string entityType,
        string fieldName,
        string fieldLabel,
        string currentText
    )

    // The ✨ face is the Lucide «sparkles» glyph (user request 2026-09-30);
    // the busy state keeps its «…» caption exactly as the spec pins it — an
    // ellipsis is text, not an icon. While a batch wave runs the press stops
    // it, and the button prints the Lucide «circle-stop» glyph in place of
    // the retired mute «⏹» text (A4, live fix 2026-09-30).
    iconName: isCancelling ? "circle-stop" : (isGenerating ? "" : "sparkles")
    text: isCancelling ? "" : (isGenerating ? "…" : "")
    accentBackground: aiState === "active"
    enabled: proxy ? proxy.clickable : !isGenerating

    onClicked: {
        generate_requested(entityType, fieldName, fieldLabel, current_text)
        if (proxy)
            proxy.requestGenerate()
    }
}
