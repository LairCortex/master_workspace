// ThemeSwatch — checkable chart-token sample (R3 pack 2).
// colorIndex 1…8 maps to islandPalette color.chart.N. Off-skin: gray circle
// plus the index digit (named Qt globals only).
import QtQuick
import "tokens.js" as Tokens

Item {
    id: control
    objectName: "themeSwatch"

    property int colorIndex: 1
    property bool checked: false
    readonly property int effectiveColorIndex: Math.max(1, Math.min(8, colorIndex))

    // Accessibility name (task 1.2): defaults to the palette position and is
    // overridable at the usage site (an island names its swatch by purpose).
    property string accessibleName: "Цвет палитры №" + effectiveColorIndex

    signal clicked()

    // The mouse press and the accessibility Press run the same select
    // behaviour (design D2/D3): checked + clicked(), no new logic.
    function selectAndClick() {
        control.checked = true
        control.clicked()
    }

    // Accessibility contract (change nri-0012-qml-accessibility, task 1.2):
    // a colour choice is a radio button — role/state inside the component,
    // the Press action goes through the very select path the mouse uses.
    Accessible.role: Accessible.RadioButton
    Accessible.name: control.accessibleName
    Accessible.checked: control.checked
    Accessible.onPressAction: control.selectAndClick()

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""
    readonly property color chartColor: Tokens.token(
        islandTokens, "color.chart." + effectiveColorIndex, "gray")

    implicitWidth: 26
    implicitHeight: 26

    Rectangle {
        id: disc
        anchors.centerIn: parent
        width: 18
        height: 18
        radius: 9
        color: control.skinned ? control.chartColor : "gray"
        border.width: control.checked ? 2 : 1
        border.color: control.skinned ? Tokens.token(islandTokens, "color.accent", "black") : "black"
    }

    Text {
        anchors.centerIn: disc
        visible: !control.skinned
        text: String(control.effectiveColorIndex)
        color: "black"
        font.pixelSize: 10
    }

    MouseArea {
        anchors.fill: parent
        onClicked: control.selectAndClick()
    }
}
