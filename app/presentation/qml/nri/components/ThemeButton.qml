// ThemeButton — the library's accented/flat action button (change
// add-qml-component-library-q2a1, task 2.1; design D3: extracted one-to-one
// from LauncherRoot's inline ThemedButton — same properties, same
// hover/pressed derivations, same off-skin degradation).
//
// Styling contract (spec qml-components «Источник оформления — только
// палитра токенов»): every color/geometry comes from the bridge
// (islandPalette.tokens via tokens.js); hover/pressed washes are Python
// compiler derivations (color.accent.hover/pressed), never computed here.
// Off-skin (empty/missing bridge, design D7): the background hides and the
// control degrades to the plain Basic text button; the fallback literals are
// exactly the named Qt globals LauncherRoot.qml pins.
import QtQuick
import QtQuick.Controls
import "tokens.js" as Tokens

Button {
    id: control

    // Accent fill (true) vs canvas fill with border (false) — the launcher's
    // «Открыть» vs every other action.
    property bool accentBackground: false

    // Design D2: creation-context lookup of the bridge with the typeof
    // insurance; outside any island the lookup degrades to {} (off-skin).
    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property bool skinned:
        Tokens.token(islandTokens, "color.bg.surface", "") !== ""

    // The launcher root's derived-color block, replicated verbatim so the
    // 1:1 extraction cannot drift (fallbacks: the pinned off-skin globals).
    readonly property color surfaceColor: Tokens.token(islandTokens, "color.bg.surface", "white")
    readonly property color canvasColor: Tokens.token(islandTokens, "color.bg.canvas", "white")
    readonly property color fgColor: Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color mutedColor: Tokens.token(islandTokens, "color.fg.muted", "gray")
    readonly property color borderColor: Tokens.token(islandTokens, "color.border", "lightgray")
    readonly property color accentColor: Tokens.token(islandTokens, "color.accent", "black")
    readonly property color accentFgColor: Tokens.token(islandTokens, "color.accent.fg", "white")

    function accentHover(base) { return Tokens.token(islandTokens, "color.accent.hover", base) }
    function accentPressed(base) { return Tokens.token(islandTokens, "color.accent.pressed", base) }

    padding: Tokens.px(islandTokens, "space.sm", 8)
    leftPadding: padding
    rightPadding: padding
    font.pixelSize: Tokens.px(islandTokens, "font.size.md", 13)

    contentItem: Text {
        text: control.text
        font: control.font
        color: !control.enabled
            ? control.mutedColor
            : control.accentBackground ? control.accentFgColor : control.fgColor
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    background: Rectangle {
        visible: control.skinned  // off-skin: bare Basic text button
        radius: Tokens.px(islandTokens, "radius.sm", 6)
        border.width: control.accentBackground ? 0 : 1
        border.color: control.accentBackground ? "transparent" : control.borderColor
        color: {
            if (!control.enabled)
                return control.canvasColor
            if (control.accentBackground)
                return control.pressed ? control.accentPressed(control.accentColor)
                     : control.hovered ? control.accentHover(control.accentColor)
                     : control.accentColor
            return control.pressed ? control.accentPressed(control.canvasColor)
                 : control.hovered ? control.accentHover(control.canvasColor)
                 : control.canvasColor
        }
    }
}
