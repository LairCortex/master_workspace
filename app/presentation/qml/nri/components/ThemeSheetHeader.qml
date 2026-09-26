// ThemeSheetHeader — the library's island-sheet title row (change
// nri-0014-window-contract-and-docs, task 4.1; design D3, defect E1).
//
// An island sheet has no native title bar, so the sheet names itself inside:
// one visible title line plus a close button. Everything visual is token
// chrome — the title is the library TitleText (fg.primary), the button is
// the library's square glyph button (NRI-0018 Д1: one gauge for every small
// action) — so the row repaints from the very same tokens as the sheet it
// crowns (spec qml-components «Одна тема с листом») and degrades like both
// controls off-skin (design D7).
//
// The component owns exactly one fact: what closing a sheet means in the
// tree. The close glyph is icon-like, so role/name/Press are component
// properties (design D3, mirror of RowItem/ThemeSwatch): the stock Button
// role comes with the control, «Закрыть» is the component's annotation of
// the mute glyph, and Press fires the same closeRequested() the mouse
// click() rides — one behaviour, two entry points, no second path. Which
// concrete cancel the signal performs (reject/Esc) is each owner island's
// existing route; the component never closes anything itself.
//
// NRI-0018 task 3.2 grew the row into a host: an optional default-property
// action slot sits between the title text and the close (fixed отступ from
// the title, centered on the title line), giving the order «заголовок →
// действие → … → закрытие» without touching the close contract.
import QtQuick
import "tokens.js" as Tokens

Item {
    id: header

    signal closeRequested()

    // The sheet's title text — threaded in by the usage site (the island
    // roots bind it to the dialog's windowTitle, task 4.2).
    property string title: ""

    // NRI-0018 task 3.2 (Д3, spec qml-components «Действие стоит за
    // заголовком»): the optional action slot. The usage site declares its
    // header action (the entity-generation ✨) right here; the default
    // property aliased to the slot host's data lands those children as the
    // host's VISUAL children, so the tree walk and the accessibility address
    // see them seated in the row. The header only hosts: like ✕, the slot's
    // behaviour belongs to the action's own owner, never to this component.
    default property alias actions: actionRow.data

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)

    implicitHeight: Math.max(
        titleText.implicitHeight, closeButton.implicitHeight, actionRow.implicitHeight)
        + 2 * Tokens.px(islandTokens, "space.sm", 8)

    TitleText {
        id: titleText
        objectName: "sheetHeaderTitle"
        anchors.left: parent.left
        anchors.leftMargin: Tokens.px(islandTokens, "space.md", 16)
        // NRI-0018: no right anchor any more — the title keeps its natural,
        // un-clipped width (spec «текст заголовка не обрезан»), the row's
        // slack moved behind the action slot.
        anchors.verticalCenter: parent.verticalCenter
        text: header.title
    }

    // The action slot host: hung off the title box with the fixed отступ and
    // centered on the title line, exactly like the two flanking controls
    // (task «центрирование по строке заголовка»). Pure anchors keep the order
    // «заголовок → действие → … → закрытие» in every theme and off-skin.
    Row {
        id: actionRow
        objectName: "sheetHeaderAction"
        anchors.left: titleText.right
        anchors.leftMargin: Tokens.px(islandTokens, "space.sm", 8)
        anchors.verticalCenter: parent.verticalCenter
        spacing: Tokens.px(islandTokens, "space.sm", 8)
    }

    ThemeIconButton {
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
