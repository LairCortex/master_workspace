// Two-layer mention editor. Python owns storage grammar and mapping; QML
// renders only display text plus chip rectangles derived from host spans.
import QtQuick
import QtQuick.Controls
import "tokens.js" as Tokens

Control {
    id: control
    objectName: "mentionField"

    property var host:
        typeof mentionFieldHost !== "undefined" ? mentionFieldHost : null
    property bool mono: false
    property bool syncing: false

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""
    readonly property color canvasColor:
        Tokens.token(islandTokens, "color.bg.canvas", "white")
    readonly property color fgColor:
        Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color borderColor:
        Tokens.token(islandTokens, "color.border", "lightgray")
    readonly property color accentColor:
        Tokens.token(islandTokens, "color.accent", "black")
    readonly property color accentFgColor:
        Tokens.token(islandTokens, "color.accent.fg", "white")

    leftPadding: Tokens.px(islandTokens, "space.sm", 8)
    rightPadding: Tokens.px(islandTokens, "space.sm", 8)
    topPadding: Tokens.px(islandTokens, "space.xs", 4)
    bottomPadding: Tokens.px(islandTokens, "space.xs", 4)
    implicitWidth: 260
    implicitHeight: 96

    // Accessibility contract (change nri-0012-qml-accessibility, task 1.3,
    // design D6): the field is editable text, so its interface offers the
    // SetFocus action; Qt's implementation focuses THIS item (the attached
    // type exposes no focus handler), and the delegation below forwards that
    // focus to the plain text layer, where keyboard input belongs. The
    // guard makes it stable: once plain holds the focus the root's own
    // activeFocus (which mirrors its child chain) changes no more.
    // Name/description stay a usage-site decision (design D2).
    onActiveFocusChanged: if (activeFocus && !plain.activeFocus)
        plain.forceActiveFocus()
    Accessible.role: Accessible.EditableText

    function syncFromHost() {
        if (!host || plain.text === host.display)
            return
        var oldCursor = plain.cursorPosition
        syncing = true
        plain.text = host.display
        plain.cursorPosition = Math.min(oldCursor, plain.length)
        syncing = false
        updateCaretRect()
    }

    function updateCaretRect() {
        if (!host)
            return
        var rect = plain.positionToRectangle(plain.cursorPosition)
        host.setCaretRect(
            rect.x - flick.contentX + control.leftPadding,
            rect.y - flick.contentY + control.topPadding,
            rect.height
        )
    }

    Component.onCompleted: syncFromHost()

    Connections {
        target: control.host
        function onDisplayChanged() { control.syncFromHost() }
    }

    background: control.skinned ? fieldBackground : null

    Rectangle {
        id: fieldBackground
        visible: control.skinned
        radius: Tokens.px(control.islandTokens, "radius.sm", 6)
        color: control.canvasColor
        border.width: 1
        border.color: plain.activeFocus ? control.accentColor : control.borderColor
    }

    contentItem: Flickable {
        id: flick
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentWidth: width
        contentHeight: Math.max(height, plain.contentHeight)

        TextEdit {
            id: plain
            objectName: "mentionPlain"
            width: flick.width
            height: Math.max(flick.height, contentHeight)
            textFormat: TextEdit.PlainText
            wrapMode: TextEdit.Wrap
            color: control.fgColor
            selectionColor: control.accentColor
            selectedTextColor: control.accentFgColor
            font.pixelSize: Tokens.px(control.islandTokens, "font.size.md", 13)
            font.family: control.mono
                ? ("" + Tokens.token(
                    control.islandTokens, "font.family.mono", "monospace"
                )).split(",")[0].trim()
                : Qt.application.font.family

            onTextChanged: {
                if (!control.host || control.syncing || inputMethodComposing)
                    return
                var safe = control.host.updateDisplay(
                    text, cursorPosition, false
                )
                control.syncFromHost()
                cursorPosition = Math.min(safe, length)
            }

            onCursorPositionChanged: {
                if (!control.host || control.syncing || inputMethodComposing)
                    return
                var safe = control.host.snapCursor(cursorPosition)
                if (safe !== cursorPosition)
                    cursorPosition = safe
                control.updateCaretRect()
            }

            onSelectionStartChanged: expandAtomicSelection()
            onSelectionEndChanged: expandAtomicSelection()

            function expandAtomicSelection() {
                if (!control.host || control.syncing
                        || selectionStart === selectionEnd)
                    return
                var expanded = control.host.expandSelection(
                    selectionStart, selectionEnd
                )
                if (expanded[0] !== selectionStart
                        || expanded[1] !== selectionEnd)
                    select(expanded[0], expanded[1])
            }

            onInputMethodComposingChanged: {
                if (!inputMethodComposing && control.host) {
                    var safe = control.host.updateDisplay(
                        text, cursorPosition, false
                    )
                    control.syncFromHost()
                    cursorPosition = Math.min(safe, length)
                }
            }

            Keys.onPressed: function(event) {
                if (!control.host)
                    return
                if (event.key === Qt.Key_Backspace
                        || event.key === Qt.Key_Delete) {
                    var start = selectionStart
                    var end = selectionEnd
                    if (start === end) {
                        if (event.key === Qt.Key_Backspace && start > 0)
                            start -= 1
                        else if (event.key === Qt.Key_Delete && end < length)
                            end += 1
                    }
                    var expanded = control.host.expandSelection(start, end)
                    if (expanded[0] !== expanded[1])
                        select(expanded[0], expanded[1])
                }
                if (control.host.popupVisible) {
                    if (event.key === Qt.Key_Down) {
                        control.host.popupDown()
                        event.accepted = true
                    } else if (event.key === Qt.Key_Up) {
                        control.host.popupUp()
                        event.accepted = true
                    } else if (event.key === Qt.Key_Return
                               || event.key === Qt.Key_Enter) {
                        control.host.confirmPopup()
                        event.accepted = true
                    } else if (event.key === Qt.Key_Escape) {
                        control.host.cancelMention()
                        event.accepted = true
                    }
                } else if (event.key === Qt.Key_Escape) {
                    control.host.cancelMention()
                    event.accepted = true
                }
            }
        }

        Repeater {
            model: control.host ? control.host.spans : []

            delegate: Rectangle {
                id: chip
                required property var modelData
                readonly property rect startRect:
                    plain.positionToRectangle(modelData.start)
                readonly property rect endRect:
                    plain.positionToRectangle(modelData.end)

                objectName:
                    "mentionChip_" + modelData.type + "_" + modelData.id
                // Accessibility contract (task 1.3): the chip opens the
                // mentioned entity — a link whose Press action reuses the
                // host entry point the MouseArea drives.
                Accessible.role: Accessible.Link
                Accessible.name: modelData.display
                Accessible.description: "Открывает упомянутую сущность"
                Accessible.onPressAction: control.host.activateMention(
                    modelData.type, modelData.id
                )
                x: startRect.x
                y: startRect.y
                width: Math.max(1, endRect.x - startRect.x)
                height: Math.max(startRect.height, 1)
                radius: Math.min(4, height / 3)
                color: control.accentColor
                z: 2

                Text {
                    anchors.fill: parent
                    text: chip.modelData.display
                    color: control.accentFgColor
                    font: plain.font
                    verticalAlignment: Text.AlignVCenter
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: control.host.activateMention(
                        chip.modelData.type, chip.modelData.id
                    )
                }
            }
        }

        Rectangle {
            id: mentionCaret
            objectName: "mentionCaret"
            readonly property rect caretRect:
                plain.positionToRectangle(plain.cursorPosition)
            x: caretRect.x
            y: caretRect.y
            width: 1
            height: Math.max(caretRect.height, 1)
            color: control.fgColor
            visible: plain.activeFocus
            z: 3
        }
    }
}
