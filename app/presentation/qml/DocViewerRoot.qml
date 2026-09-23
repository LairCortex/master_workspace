import QtQuick
import QtQuick.Layouts
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

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Tokens.px(root.islandTokens, "space.sm", 8)

        ThemeTextArea {
            objectName: "docText"
            Layout.fillWidth: true
            Layout.fillHeight: true
            readOnly: true
            mono: true
            text: docViewerVm.text
            // nri-0012 task 3.4 (usage-site name, design map): the whole
            // island is this one viewer — the name states what it shows.
            Accessible.name: "Текст документа"
        }
    }
}
