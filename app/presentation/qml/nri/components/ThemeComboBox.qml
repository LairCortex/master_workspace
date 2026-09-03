// ThemeComboBox — the library's dropdown (change
// add-qml-component-library-q2a1, task 2.3; design D4: field + indicator
// by tokens, popup list themed as well).
//
// Skin/off-skin split by style-slot machinery:
//   * background / contentItem / arrow indicator: `skinned` swaps in themed
//     items or hands the slot back to Basic (null re-materializes the style
//     default — verified headless), so off-skin the combo box itself is the
//     plain Basic control;
//   * popup / delegate: assigned unconditionally instead. ComboBox exposes
//     `popup` as a plain property whose default lives in the style
//     template — there is no evidence the null hand-back regenerates it, and
//     silently losing the dropdown would break the off-skin interaction
//     contract. The themed popup therefore degrades to the pinned
//     named-Qt-global fallbacks off-skin: a functional white popup with a
//     token-border frame and readable rows — interactions and no exceptions
//     are what the off-skin scenario pins.
import QtQuick
import QtQuick.Controls
import "tokens.js" as Tokens

ComboBox {
    id: control

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""

    readonly property color canvasColor: Tokens.token(islandTokens, "color.bg.canvas", "white")
    readonly property color surfaceColor: Tokens.token(islandTokens, "color.bg.surface", "white")
    readonly property color fgColor: Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color mutedColor: Tokens.token(islandTokens, "color.fg.muted", "gray")
    readonly property color borderColor: Tokens.token(islandTokens, "color.border", "lightgray")
    readonly property color accentColor: Tokens.token(islandTokens, "color.accent", "black")
    readonly property color accentFgColor: Tokens.token(islandTokens, "color.accent.fg", "white")

    // Arrow edge: derived from the font token, not an invented constant.
    readonly property real arrowSize: Tokens.px(islandTokens, "font.size.md", 13)

    padding: Tokens.px(islandTokens, "space.sm", 8)
    font.pixelSize: Tokens.px(islandTokens, "font.size.md", 13)

    background: control.skinned ? comboBackground : null

    Rectangle {
        id: comboBackground
        visible: control.skinned  // floats invisible while off-skin
        radius: Tokens.px(islandTokens, "radius.sm", 6)
        color: control.canvasColor
        border.width: 1
        border.color: control.activeFocus || (control.popup && control.popup.visible)
            ? control.accentColor : control.borderColor
    }

    contentItem: control.skinned ? displayText : null

    Text {
        id: displayText
        visible: control.skinned  // floats invisible while off-skin
        text: control.displayText
        font: control.font
        color: control.enabled ? control.fgColor : control.mutedColor
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: control.skinned ? themedArrow : null

    // The arrow is a token-colored triangle: the Canvas paints by assigning
    // the bridge's fg value to the context (a value pass-through — the same
    // way every other slot binds color — never a computation).
    Canvas {
        id: themedArrow
        visible: control.skinned  // floats invisible while off-skin
        implicitWidth: control.arrowSize
        implicitHeight: control.arrowSize
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.fillStyle = String(control.fgColor)
            ctx.beginPath()
            ctx.moveTo(width * 0.15, height * 0.35)
            ctx.lineTo(width * 0.85, height * 0.35)
            ctx.lineTo(width * 0.5, height * 0.75)
            ctx.closePath()
            ctx.fill()
        }
        onVisibleChanged: if (visible) requestPaint()
    }
    onFgColorChanged: themedArrow.requestPaint()
    onFontChanged: themedArrow.requestPaint()

    popup: themedPopup

    Popup {
        id: themedPopup
        y: control.height
        width: control.width
        implicitHeight: popupList.implicitHeight + topPadding + bottomPadding
        padding: 1
        contentItem: ListView {
            id: popupList
            clip: true
            implicitHeight: contentHeight
            // combo.popup is null until the style materializes it — guard
            // the transient so creation-order binding errors never fire.
            model: control.popup && control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            boundsBehavior: Flickable.StopAtBounds
        }
        background: Rectangle {
            radius: Tokens.px(control.islandTokens, "radius.sm", 6)
            color: control.surfaceColor
            border.width: 1
            border.color: control.borderColor
        }
    }

    delegate: themedRow

    Component {
        id: themedRow
        ItemDelegate {
            id: rowDelegate
            width: control.width
            highlighted: control.highlightedIndex === index
            leftPadding: Tokens.px(control.islandTokens, "space.sm", 8)
            rightPadding: Tokens.px(control.islandTokens, "space.sm", 8)
            topPadding: Tokens.px(control.islandTokens, "space.xs", 4)
            bottomPadding: Tokens.px(control.islandTokens, "space.xs", 4)
            contentItem: Text {
                text: modelData
                font.pixelSize: Tokens.px(control.islandTokens, "font.size.md", 13)
                color: rowDelegate.highlighted
                    ? control.accentFgColor
                    : control.enabled ? control.fgColor : control.mutedColor
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
            background: Rectangle {
                color: rowDelegate.highlighted ? control.accentColor : control.canvasColor
            }
        }
    }
}
