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
    readonly property color fgColor: Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color accentColor: Tokens.token(islandTokens, "color.accent", "black")

    color: surfaceColor
    implicitWidth: 720
    implicitHeight: 560

    // Independent-audit addendum (spec document-viewer «Клавиатура
    // прокручивает»): the requirement names PageUp/PageDown next to the
    // movement keys. Pages are stepped here, one viewport height per
    // press, clamped to the content: the Keys handler runs as the focused
    // item's event filter BEFORE the selectable RichText sees the key, so
    // the page steps win over any cursor move the text would make. The
    // offset lives on the ScrollView's contentItem Flickable (ScrollView
    // itself exposes only the content metrics, not contentY).
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

        // The document renders formatted (md4c → HTML in the VM, the same
        // Qt rich-text engine): headings/lists/bold/code print as markup,
        // the colours ride the island tokens (the converter strips Qt's
        // hardcoded link colour so the accent paints the links). A plain
        // read-only mono field would show the raw asterisks and hashes.
        // Mouse selection is NOT available on this runtime: the PySide6
        // 6.10.3 wheel is built without the Qt textcontrol feature —
        // Text.selectable/selectByMouse/selectionColor are not types at all
        // there (probe: QML compile error), so a formatted label is read
        // and paged, never selected.
        Text {
            objectName: "docText"
            width: docScroll.availableWidth
            text: docViewerVm.html
            textFormat: Text.RichText
            wrapMode: Text.WordWrap
            color: root.fgColor
            linkColor: root.accentColor
            // The reader's carrier takes the scene focus on its own: with no
            // selection gesture left to earn focus (textcontrol is out of the
            // wheel), the page keys must still land after the open — this is
            // the focus the Keys handler below rides.
            focus: true
            // nri-0012 task 3.4 (usage-site name, design map): the whole
            // island is this one viewer — the name states what it shows.
            // The role is the stock Text item's static text (readable, not
            // editable) — the expected face of the formatted viewer.
            Accessible.name: "Текст документа"
            // The page keys land on the focused text (see pageScroll above):
            // one onPressed switch covers both (formal-parameter style of
            // SheetCanvas.qml).
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
