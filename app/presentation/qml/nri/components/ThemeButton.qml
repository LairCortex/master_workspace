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

    // Flat (ghost) set (NRI-0023 task 11.2, design Д12; owner rework on the
    // 2026-09-30 live audits; spec qml-components «Плоская (ghost) гарнитура
    // кнопки библиотеки»): a glyph action that sits ON a row wears NO own
    // face in ANY state — neither fill nor border, at rest, hovered or
    // pressed; the set is the glyph only. The first cut answered hover/press
    // with the compiler's derivations (color.accent.hover/pressed) — the
    // accent under an alpha printed a rounded chip over the hovered row's
    // wash and wherever the square overhangs a shorter band, the very defect
    // the set was born to cure; see the background's ghost branch. The
    // interaction story is the row's (its wash, its tooltip) plus the glyph
    // tint — ``accentBackground`` keeps flipping the glyph to
    // color.accent.fg over an accent-filled row. Ghost changes neither the
    // hit zone nor the accessibility (the stock Button contract is
    // untouched) and does not shift neighbours. Usage sites that do not ask
    // for it keep the previous face word-for-word.
    property bool ghost: false

    // Lucide icon of this button (user request 2026-09-30): a name of the
    // generated icons.js map, drawn by the library ThemeIcon before the
    // caption. It is paint only — the stock Button accessibility contract
    // is untouched (a word caption keeps naming the button; a glyph-only
    // button keeps its usage-site name annotation), the same rule the mute
    // text glyphs it replaces always followed. Empty (default) paints the
    // plain text button, so every pre-icon usage renders bit-for-bit as
    // before. Tint follows the face the text already uses: disabled → muted,
    // accent fill → accent.fg, plain → fg.primary.
    property string iconName: ""

    // The same glyph contract on the OTHER side of the caption (live fix
    // 2026-09-30 A1): the window chip's dropdown caret moves out of the text
    // into this trailing slot. Mirror of the leading block — the library
    // iconSize gauge, the shared iconGap, visible exactly when the name is
    // non-empty; empty (default) leaves the layout bit-for-bit as it was.
    property string trailingIconName: ""

    // The library glyph gauge for this button's icon; a usage that carries a
    // deliberately larger glyph (the ladder's disclosure chevron) overrides it.
    property int iconSize: 16

    // State angle of the glyphs in degrees (user request 2026-10-03, the
    // preview's pin): a stateful glyph toggle leans its glyph at rest and
    // turns it upright when the state engages. The seat is the library's
    // (the usage never reaches into the icon node); ThemeIcon spins around
    // the glyph's own centre. 0 (default) paints bit-for-bit as before.
    property real iconRotation: 0

    // Glyph in the accent colour while the button is ENABLED (same request):
    // the stateful toggles mark their engaged side by the accent, the way
    // ``accentBackground`` marks it over an accent fill. The face law stays
    // one chain — disabled mutes first, an accent-filled face keeps its own
    // foreground, and plain usages never set this flag, so every existing
    // button keeps the previous tint word-for-word.
    property bool iconAccentTint: false

    readonly property color iconTint: !enabled
        ? mutedColor
        : accentBackground ? accentFgColor
        : iconAccentTint ? accentColor : fgColor

    // Shared gap between the icon and the caption of an icon+text button.
    readonly property real iconGap: Tokens.px(islandTokens, "space.xs", 4)

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

    // Caption + optional Lucide glyph, kept centered as one group. The
    // geometry is manual (no Row): a positioner would refuse to squeeze the
    // caption below its implicit width, and chip-width buttons rely on the
    // caption eliding at the width floor (the old plain-Text contentItem
    // contract, reproduced here bit-for-bit when iconName is empty).
    contentItem: Item {
        id: contentBox

        readonly property real glyphW: control.iconName !== "" ? control.iconSize : 0
        readonly property real glyphGap:
            control.iconName !== "" && control.text !== "" ? control.iconGap : 0
        readonly property real trailingGlyphW:
            control.trailingIconName !== "" ? control.iconSize : 0
        readonly property real trailingGlyphGap:
            control.trailingIconName !== "" && control.text !== "" ? control.iconGap : 0
        readonly property real captionImplicit:
            control.text !== "" ? captionText.implicitWidth : 0
        readonly property real groupWidth: glyphW + glyphGap + Math.min(
            captionImplicit,
            Math.max(0, width - glyphW - glyphGap - trailingGlyphGap - trailingGlyphW))
            + trailingGlyphGap + trailingGlyphW

        implicitWidth: glyphW + glyphGap + captionImplicit
            + trailingGlyphGap + trailingGlyphW
        implicitHeight: Math.max(captionText.implicitHeight, control.iconSize)

        ThemeIcon {
            id: glyphIcon
            objectName: "themeButtonIcon"
            visible: control.iconName !== ""
            name: control.iconName
            size: control.iconSize
            tint: control.iconTint
            glyphRotation: control.iconRotation
            x: (contentBox.width - contentBox.groupWidth) / 2
            y: (contentBox.height - height) / 2
        }
        Text {
            id: captionText
            objectName: "themeButtonCaption"
            visible: control.text !== ""
            x: glyphIcon.x + contentBox.glyphW + contentBox.glyphGap
            width: contentBox.groupWidth - contentBox.glyphW - contentBox.glyphGap
                - contentBox.trailingGlyphGap - contentBox.trailingGlyphW
            y: (contentBox.height - height) / 2
            text: control.text
            font: control.font
            color: !control.enabled
                ? control.mutedColor
                : control.accentBackground ? control.accentFgColor : control.fgColor
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        // Trailing mirror of the leading glyph: same gauge, same tint, the
        // group stays centered with this glyph as its right-hand term.
        ThemeIcon {
            id: trailingGlyphIcon
            objectName: "themeButtonTrailingIcon"
            visible: control.trailingIconName !== ""
            name: control.trailingIconName
            size: control.iconSize
            tint: control.iconTint
            glyphRotation: control.iconRotation
            x: glyphIcon.x + contentBox.groupWidth - contentBox.trailingGlyphW
            y: (contentBox.height - height) / 2
        }
    }

    background: Rectangle {
        visible: control.skinned  // off-skin: bare Basic text button
        radius: Tokens.px(islandTokens, "radius.sm", 6)
        // A ghost wears no border ever (spec: «ни заливки, ни рамки»); the
        // non-ghost chrome below is the migrated pair, word-for-word.
        border.width: control.ghost ? 0 : (control.accentBackground ? 0 : 1)
        border.color: control.accentBackground ? "transparent" : control.borderColor
        color: {
            if (control.ghost)
                // Ghost face (Д12, owner rework on the 2026-09-30 live
                // audits): NO own face in ANY state — at rest, hovered or
                // pressed the flat set is the glyph only. The first cut
                // painted the compiler's derivations on hover/press; being
                // the accent under an alpha they read as a rounded chip
                // wherever they landed: over the hovered row's own wash, and
                // in the ring where the 32 px square overhangs a shorter
                // band. Interaction feedback belongs to the row (its wash,
                // its tooltip) and to the glyph tint — ``accentBackground``
                // still flips the glyph to accent.fg over the selection,
                // that flip is the whole state story there.
                return "transparent";
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
