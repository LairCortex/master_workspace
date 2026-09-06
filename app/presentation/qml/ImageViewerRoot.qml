import QtQuick
import QtQuick.Layouts
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "imageViewerRoot"

    readonly property Item defaultButton: closeButton

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool vmReady: typeof imageViewerVm !== "undefined" && imageViewerVm !== null
    readonly property color surfaceColor:
        Tokens.token(root.islandTokens, "color.bg.surface", "white")

    color: root.surfaceColor
    implicitWidth: 700
    implicitHeight: 600

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Tokens.px(root.islandTokens, "space.md", 16)
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        CardPanel {
            objectName: "unavailableText"
            visible: root.vmReady && imageViewerVm.unavailable
            Layout.fillWidth: true
            Layout.fillHeight: true
            TitleText {
                anchors.centerIn: parent
                text: "Изображение недоступно."
            }
        }

        Flickable {
            objectName: "viewerScroll"
            visible: root.vmReady && !imageViewerVm.unavailable
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: viewerImage.width
            contentHeight: viewerImage.height
            Image {
                id: viewerImage
                objectName: "viewerImage"
                source: root.vmReady ? imageViewerVm.source : ""
                cache: false
                asynchronous: false
            }
        }

        HintText {
            objectName: "fallbackNote"
            visible: root.vmReady && imageViewerVm.usedPreview && !imageViewerVm.unavailable
            text: "Оригинал недоступен — показан preview."
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
        }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            ThemeButton {
                id: closeButton
                objectName: "closeButton"
                text: "Закрыть"
                onClicked: root.closeRequested()
            }
        }
    }

    signal closeRequested()
}
