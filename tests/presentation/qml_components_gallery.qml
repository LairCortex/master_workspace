// Gallery island for the nri.components acceptance suite (change
// add-qml-component-library-q2a1, task 4.1; design D6). Not a product file —
// loaded by tests/presentation/test_qml_components.py through the shared
// shell engine, exactly like a real island (the `import nri.components`
// resolves through the engine's production import path, proving the module
// seam one more time on the acceptance surface).
//
// Every library component appears once under a stable objectName so the
// acceptance tests can address it by the same walk/findBy-objectName pattern
// as the launcher island. Geometry is flat and integer-pixel: pixel
// acceptance (task 4.2) samples known surfaces — token-driven padding only,
// no magic layout numbers — and text checks scan the text item's own scene
// bounds for an exact token pixel (no golden images, per spec).
//
// The page background is a guarded direct read of color.danger (the same
// bridge the components resolve through, design D2): the acceptance page is
// painted with a token NO component surface uses, so every themed surface —
// surface, canvas, border, accent, fg, muted text — is pixel-distinguishable
// from its surround in both themes (a page sharing any of those tokens would
// let that check pass on the surround alone). Off-skin (no / empty bridge —
// tasks 4.4) the guarded read degrades to the same "lightgray" named global
// the components themselves fall back to, without engine errors.
import QtQuick
import nri.components

Item {
    id: gallery
    objectName: "componentsGallery"
    implicitWidth: 420
    implicitHeight: 330

    // Guarded bridge lookup (the components all repeat this; the page uses
    // the same insurance, so the whole gallery degrades together).
    readonly property var islandTokens:
        (typeof islandPalette !== "undefined" && islandPalette !== null
            && islandPalette.tokens) ? islandPalette.tokens : ({})

    // Interaction counters the acceptance tests read back — the gallery-side
    // counterparts of what islands wire to their view models.
    property int buttonClicks: 0
    property int rowTaps: 0
    property int rowActivations: 0

    // Aggregate skin flag: every themed component answers with its own
    // `skinned` (off-skin flips this to false without any exception).
    readonly property bool allSkinned: btnAccent.skinned && btnPlain.skinned
        && fld.skinned && chk.skinned && cbo.skinned && ttl.skinned && hnt.skinned
        && card.skinned && rw.skinned

    // Off-skin escape detector: the AND above alone would let a SINGLE
    // component stuck on `skinned: true` (design D7 violation) pass every
    // off-skin run unnoticed — the OR aggregate pins the per-component
    // contract "no component considers itself skinned without the bridge"
    // (spec «Поведение компонентов вне валидной темы»).
    readonly property bool anySkinned: btnAccent.skinned || btnPlain.skinned
        || fld.skinned || chk.skinned || cbo.skinned || ttl.skinned || hnt.skinned
        || card.skinned || rw.skinned

    // Page surface — color.danger (see header). Declared first so every
    // component sits above it in the sibling paint order.
    Rectangle {
        anchors.fill: parent
        color: gallery.islandTokens["color.danger"] || "lightgray"
    }

    ThemeButton {
        id: btnAccent
        objectName: "galleryButtonAccent"
        accentBackground: true
        text: "MMM"
        x: 10; y: 10; width: 120; height: 36
        onClicked: gallery.buttonClicks += 1
    }
    ThemeButton {
        id: btnPlain
        objectName: "galleryButtonPlain"
        text: "MMM"
        x: 150; y: 10; width: 120; height: 36
    }
    ThemeField {
        id: fld
        objectName: "galleryField"
        x: 10; y: 60; width: 200; height: 32
    }
    ThemeCheckBox {
        id: chk
        objectName: "galleryCheckBox"
        text: "WWW"
        x: 10; y: 106
    }
    ThemeComboBox {
        id: cbo
        objectName: "galleryCombo"
        model: ["MMM", "WWW"]
        x: 240; y: 106; width: 150; height: 30
    }
    TitleText {
        id: ttl
        objectName: "galleryTitle"
        text: "WMW"
        x: 10; y: 136
    }
    HintText {
        id: hnt
        objectName: "galleryHint"
        text: "WMW"
        x: 10; y: 160
    }
    CardPanel {
        id: card
        objectName: "galleryCard"
        x: 240; y: 146; width: 150; height: 50
    }
    RowItem {
        id: rw
        objectName: "galleryRow"
        text: "WWW"
        textObjectName: "galleryRowText"
        x: 10; y: 192; width: 220
        height: implicitHeight
        onSelectedRequested: gallery.rowTaps += 1
        onActivateRequested: gallery.rowActivations += 1
    }

    // Headless stand-in for the combo popup (group 2's verified acceptance
    // route): clone the themed delegate template into a local list. The
    // template, bindings and delegate-materialization errors are identical
    // to the real popup's; only the windowless showing is left out.
    ListView {
        id: comboRows
        objectName: "galleryComboRows"
        x: 240; y: 210; width: 150; height: 72
        // Same fixed glyph set as the combo's own model — the exact-pixel
        // text check (task 4.2) scans these rows too.
        model: ["MMM", "WWW"]
        delegate: cbo.delegate
    }
}
