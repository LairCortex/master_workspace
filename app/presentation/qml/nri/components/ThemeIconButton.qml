// ThemeIconButton — the library's square small-action glyph button (change
// nri-0018-grid-alignment-and-card, task 1.2; design Д1).
//
// Spec qml-components «Квадратная мелкая кнопка действия библиотеки»: every
// mute glyph an island can press (sheet close, music-link edit, AI actions,
// scale add, the editor/event-type move rails) rides THIS component, so one
// gauge — the fixed 32×32 square below — answers for all of them. The side is
// a component constant, not a theme token (design Д1 + non-goal): the shape
// is the affordance's identity, not a knob the theme may turn, and keeping it
// here means no island can ever grow its own private glyph size again.
//
// Skin and interaction are inherited verbatim from ThemeButton (the token
// chrome, hover/pressed derivations, disabled face, off-skin Basic
// degradation) — the square only freezes the geometry. Accessibility stays on
// the nri-0012 contract: the stock Button role ships with the control, the
// NAME is the usage site's (icon glyphs are named by the action they perform;
// the close button inside ThemeSheetHeader is the one component-owned
// annotation), and single activation is the ordinary Button.clicked the
// accessibility Press also rides. Zero padding centers the glyph in the whole
// square (the contentItem keeps its own center alignment) — a 16 px inset
// band would clip wide emoji-size glyphs like «✨».
import QtQuick

ThemeButton {
    id: control

    // The single glyph gauge (spec: «фиксированный квадрат единого калибра
    // (32×32)»). ThemeAiButton wears the same value — the identical constant
    // in both component sources is pinned test-pinned in
    // tests/presentation/test_theme_icon_button.py.
    readonly property int side: 32

    width: side
    height: side
    implicitWidth: side
    implicitHeight: side

    padding: 0
}
