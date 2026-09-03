// Token-lookup helpers for the nri.components library (change
// add-qml-component-library-q2a1, design D2). Same resolution semantics the
// launcher island carried inline in LauncherRoot.qml — `token` returns the
// caller's fallback for an unknown name, `px` parses the numeric part of a
// CSS-sized token and returns the fallback on NaN — now shared and stateless.
//
// A `.pragma library` script has no QML context of its own: neither ids nor
// context properties (islandPalette included) are nameable inside it, so the
// bridge is always passed IN by the island. `resolveTokens` keeps the
// `typeof islandPalette` insurance on that seam: an island whose context has
// no bridge, or a bridge whose dictionary is empty (off-skin, design D7),
// degrades to an empty lookup — every helper then yields its fallback and
// nothing throws. No colors are computed here; the Python theme compiler
// stays the only color engine.

.pragma library

// The island's flat token dictionary, or an empty one when the context has
// no `islandPalette` bridge (undefined) or carries a null stand-in for it.
function resolveTokens(islandPalette) {
    if (typeof islandPalette === "undefined" || islandPalette === null) {
        return {}
    }
    var tokens = islandPalette.tokens
    return typeof tokens === "undefined" || tokens === null ? {} : tokens
}

// tokens: the dictionary from resolveTokens; name: dotted token key.
function token(tokens, name, fallback) {
    var value = tokens[name]
    return value === undefined ? fallback : value
}

// Token values are CSS strings ("8px", "13px"); the numeric part drives
// geometry. Not a color derivation — a unit read of the very same token.
function px(tokens, name, fallback) {
    var value = Number.parseFloat(token(tokens, name, ""))
    return Number.isNaN(value) ? fallback : value
}
