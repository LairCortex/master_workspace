// Smoke probe of the nri.components module (change
// add-qml-component-library-q2a1, tasks 1.1–1.2; loaded by
// tests/presentation/test_qml_components.py, not a public component).
//
// It proves the two skeleton contracts:
//   1.1 — `import nri.components` resolves through the engine's one import
//         path (spec qml-shell «Модуль библиотеки резолвится из import-пути»)
//         and loads with a clean error list even while the qmldir-listed
//         component files only arrive with group 2 (type entries resolve
//         lazily; the smoke deliberately uses none of them).
//   1.2 — the shared `token()`/`px()` helpers live in tokens.js. The bridge
//         lookup keeps the `typeof islandPalette` insurance (design D2): a
//         context WITHOUT the bridge must degrade to pure fallbacks, and a
//         context with it must read the real token values through tokens.js.
import QtQuick
import nri.components
import "tokens.js" as Tokens

Item {
    id: smoke
    objectName: "componentsSmoke"

    implicitWidth: 120
    implicitHeight: 60

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)

    // Probe values addressed by the tests: with a palette these must equal
    // the palette's own entries; without one — exactly the fallbacks below.
    property string accentProbe: Tokens.token(islandTokens, "color.accent", "skeleton-fallback")
    property real spaceProbe: Tokens.px(islandTokens, "space.md", -1)
}
