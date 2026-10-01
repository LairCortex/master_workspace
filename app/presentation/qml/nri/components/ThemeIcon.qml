// ThemeIcon — the library's Lucide vector glyph (user request 2026-09-30:
// the islands' mute text glyphs retire in favour of the vendored Lucide set).
//
// One knowledge, one place (AGENTS coding principle 2): every icon the app
// can show is a name of the generated ``icons.js`` map (the ISC-licensed
// Lucide paths, vendored and expanded by scripts/vendor_lucide.py), and this
// component is the ONLY thing that draws them. The upstream arc commands and
// primitives arrive pre-expanded to cubic Béziers because Qt's PathSvg
// understands only M/L/C/Z; the 24×24 Lucide grid is scaled to ``size`` via
// the item transform, and with it the width-2 stroke and the round
// caps/joins — the same rendering law Lucide itself publishes.
//
// Color law (spec qml-components «Источник оформления — только палитра
// токенов»): the stroke reads the theme through the palette bridge — the
// caller passes ``tint`` (selection/accent faces), the untouched default is
// ``color.fg.primary``; off-skin the guarded lookup lands on the pinned
// "black" fallback, like every other library control's degradation (D7).
//
// Accessibility: an icon is paint, never a reader target — the component
// carries NO Accessible annotation (the forbidden list bars both
// ``Accessible.ignored`` and nameless role nodes, and an unannotated plain
// Item stays out of the tree). What an icon BUTTON means stays named at the
// usage site exactly as before (nri-0012 contract); ThemeIcon itself is the
// silent brush that draws it.
import QtQuick
import QtQuick.Shapes
import "tokens.js" as Tokens
import "icons.js" as Icons

Item {
    id: icon

    // The icon name (a key of the generated icons.js map); unknown or empty
    // names paint nothing rather than failing.
    property string name: ""

    // The square edge in logical pixels (the Lucide grid scales into it).
    property int size: 16

    // Stroke tint; the usage sites with their own face (selection wash,
    // accent fill, disabled) bind this, the default follows the theme text.
    property color tint: Tokens.token(islandTokens, "color.fg.primary", "black")

    // Shared library gauge for the glyph buttons' interior icon (the 32×32
    // hit square is ThemeIconButton's, this is the paint inside it).
    width: size
    height: size
    implicitWidth: size
    implicitHeight: size

    // D2 lookup with the typeof insurance — outside any island this degrades
    // to {} and the fallback color answers.
    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)

    // 24×24 upstream grid → `size` square; the stroke scales with it, as in
    // every Lucide render.
    transform: Scale {
        xScale: size / 24
        yScale: size / 24
    }

    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            fillColor: "transparent"
            strokeColor: icon.tint
            strokeWidth: 2
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: Icons.iconPath(icon.name) }
        }
    }
}
