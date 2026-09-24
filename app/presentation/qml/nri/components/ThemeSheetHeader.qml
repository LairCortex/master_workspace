// ThemeSheetHeader — the library's island-sheet title row (change
// nri-0014-window-contract-and-docs, task 4.1; design D3, defect E1).
//
// An island sheet has no native title bar, so the sheet names itself inside:
// one visible title line plus a close button. Everything visual is token
// chrome — the title is the library TitleText (fg.primary), the button is
// the library ThemeButton — so the row repaints from the very same tokens as
// the sheet it crowns (spec qml-components «Одна тема с листом») and
// degrades like both controls off-skin (design D7).
//
// The component owns exactly one fact: what closing a sheet means in the
// tree. The close glyph is icon-like, so role/name/Press are component
// properties (design D3, mirror of RowItem/ThemeSwatch): the stock Button
// role comes with the control, «Закрыть» is the component's annotation of
// the mute glyph, and Press fires the same closeRequested() the mouse
// click() rides — one behaviour, two entry points, no second path. Which
// concrete cancel the signal performs (reject/Esc) is each owner island's
// existing route; the component never closes anything itself.
import QtQuick
import "tokens.js" as Tokens

Item {
    id: header

    signal closeRequested()

    // The sheet's title text — threaded in by the usage site (the island
    // roots bind it to the dialog's windowTitle, task 4.2).
    property string title: ""

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)

    implicitHeight: Math.max(titleText.implicitHeight, closeButton.implicitHeight)
        + 2 * Tokens.px(islandTokens, "space.sm", 8)

    TitleText {
        id: titleText
        objectName: "sheetHeaderTitle"
        anchors.left: parent.left
        anchors.leftMargin: Tokens.px(islandTokens, "space.md", 16)
        anchors.right: closeButton.left
        anchors.rightMargin: Tokens.px(islandTokens, "space.sm", 8)
        anchors.verticalCenter: parent.verticalCenter
        text: header.title
    }

    ThemeButton {
        id: closeButton
        objectName: "sheetHeaderClose"
        anchors.right: parent.right
        anchors.rightMargin: Tokens.px(islandTokens, "space.md", 16)
        anchors.verticalCenter: parent.verticalCenter
        text: "✕"
        // Icon-like glyph: the tree names it by the action it performs
        // (design D3 — the annotation lives with the component).
        Accessible.name: "Закрыть"
        onClicked: header.closeRequested()
    }
}
