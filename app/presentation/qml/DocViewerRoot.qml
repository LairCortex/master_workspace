import QtQuick
import QtQuick.Controls
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "docViewerRoot"

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor: Tokens.token(islandTokens, "color.bg.surface", "white")

    color: surfaceColor
    implicitWidth: 720
    implicitHeight: 560

    // Independent-audit addendum (spec document-viewer «Клавиатура
    // прокручивает»): the requirement names PageUp/PageDown next to the
    // movement keys. Arrow keys reach the Flickable on their own (the
    // readOnly text edit ignores them and they bubble), but a readOnly
    // TextArea ACCEPTS the page keys without moving anything and the
    // ScrollView owns no key handler — so pages are stepped here, one
    // viewport height per press, clamped to the content. The offset lives
    // on the ScrollView's contentItem Flickable (ScrollView itself exposes
    // only the content metrics, not contentY).
    function pageScroll(direction) {
        var flick = docScroll.contentItem
        var page = docScroll.availableHeight
        var maxY = Math.max(0, flick.contentHeight - page)
        flick.contentY = Math.max(0, Math.min(flick.contentY + direction * page, maxY))
    }

    // NRI-0014 task 2.1 (defect AB1): the document is wrapped in a stock
    // ScrollView — the same pattern as SheetPresetRoot.qml:134-147 — so every
    // line is reachable by wheel/scrollbar/keys, not only the fragment that
    // happened to fit at open time. contentWidth is pinned to the viewport so
    // only the vertical axis scrolls (the text wraps, never runs sideways).
    ScrollView {
        id: docScroll
        objectName: "docScroll"
        anchors.fill: parent
        // NRI-0018 task 5.3 (spec ui-layout-grid «Отступ содержимого листов
        // задан единым токеном»): the 8 px exception was pulled up to the
        // shared sheet token.
        anchors.margins: Tokens.px(root.islandTokens, "space.md", 16)
        clip: true
        contentWidth: availableWidth

        ThemeTextArea {
            objectName: "docText"
            width: docScroll.availableWidth
            readOnly: true
            mono: true
            text: docViewerVm.text
            // nri-0012 task 3.4 (usage-site name, design map): the whole
            // island is this one viewer — the name states what it shows.
            Accessible.name: "Текст документа"
            // The page keys land on the focused text (see pageScroll above):
            // accepted here, the readOnly field would eat them motionless.
            // Keys has no per-key PageUp/PageDown signal — one onPressed
            // switch covers both (formal-parameter style of SheetCanvas.qml).
            Keys.onPressed: function (event) {
                if (event.key === Qt.Key_PageDown) {
                    root.pageScroll(1)
                    event.accepted = true
                } else if (event.key === Qt.Key_PageUp) {
                    root.pageScroll(-1)
                    event.accepted = true
                }
            }
        }
    }
}
