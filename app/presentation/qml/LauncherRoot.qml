// Launcher island (spec game-launcher «Поверхность лаунчера — QML-островок»).
//
// Since change add-qml-component-library-q2a1 every themed control here comes
// from the nri.components library (`import nri.components`): the row delegate
// is `RowItem`, the action buttons are `ThemeButton`, and the token/px
// helpers live in the module's stateless `tokens.js` (design D2/D3 — zero
// chrome styling stays inline in this file).
//
// Context contract (design D6, replicated by the QDialog wrapper in group 6):
//   * `vm`            — LauncherViewModel: bound read-only (games/
//                       selectedIndex/selectedPath); buttons emit its
//                       *Requested signals and call sync set_selected()
//                       only — never an async entry (spec qml-shell
//                       «Контракт биндингов»).
//   * `islandPalette` — QmlPalette: the ONLY color/spacing source, read
//                       through tokens.js by the island and through the
//                       creation-context lookup chain by the library
//                       components (design D2). The name deliberately differs
//                       from the engine-level "palette": Qt Quick Controls
//                       shadow the bare «palette» identifier in any scope, so
//                       the island context must carry the bridge under this
//                       name. No hex literals, no OS palette here; off-skin
//                       (empty `tokens`, design D7) bindings degrade to named
//                       Qt globals through the library, controls stay on
//                       their plain Basic look and nothing throws.
//
// Embedding contract for the wrapper (group 6):
//   * `currentTheme` — set to the runtime theme name ("dark"/"light") and
//     re-synced on every theme change; it only labels the toggle with the
//     theme it would switch *to*.
//   * `themeToggleRequested()` — connect and call ThemeRuntime.toggle().
//   * Qt 6's Basic Button exposes no «default» style property — the island
//     marks the default action through `root.defaultButton`; the dialog
//     wrapper wires Enter to its `click()` (spec: «Открыть» on Enter).
import QtQuick
import QtQuick.Layouts
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "launcherRoot"

    implicitWidth: 480
    implicitHeight: 400

    property string currentTheme: "dark"

    signal themeToggleRequested()

    // «Открыть» is the default action (spec game-launcher). Qt 6 Basic's
    // Button exposes no bindable «default» property, so the marker is this
    // typed contract on the root: the wrapper wires Enter to its click().
    readonly property Item defaultButton: openButton

    // ---- palette bridge (colors/spacing only ever come from here) ----
    //
    // Same guarded resolveTokens seam as smoke.qml and every library
    // component (design D2): a context without the bridge — or with an empty
    // token dictionary — degrades to the named-global fallbacks, no throws.
    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)

    readonly property color surfaceColor: Tokens.token(root.islandTokens, "color.bg.surface", "white")
    readonly property color canvasColor: Tokens.token(root.islandTokens, "color.bg.canvas", "white")
    readonly property color fgColor: Tokens.token(root.islandTokens, "color.fg.primary", "black")
    readonly property color borderColor: Tokens.token(root.islandTokens, "color.border", "lightgray")

    function openGame(path) {
        // Spec: «Открыть» without a selected row is a no-op. The signal is
        // the VM's own (the island emits it; the controller answers).
        if (path) vm.openRequested(path)
    }

    color: surfaceColor

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Tokens.px(root.islandTokens, "space.md", 16)
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        Text {
            text: "Выберите игру или создайте новую"
            font.pixelSize: Tokens.px(root.islandTokens, "font.size.xl", 16)
            font.weight: Tokens.px(root.islandTokens, "font.weight.bold", 400)
            color: root.fgColor
            Layout.fillWidth: true
        }

        // List frame: surface-in-canvas with the token border.
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: Tokens.px(root.islandTokens, "radius.sm", 6)
            color: root.canvasColor
            border.color: root.borderColor
            border.width: 1
            clip: true

            ListView {
                id: gameList
                objectName: "gameList"
                anchors.fill: parent
                anchors.margins: 1  // keep rows off the 1px border
                model: vm.games
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                // The row's look and tap/double-tap MouseArea are the
                // library's (RowItem): selected → accent + accent.fg, height
                // text + 2 * space.xs, insets space.sm — the island owns the
                // model semantics and answers the row's two signals. The
                // objectName contract (tests) travels via `textObjectName`.
                delegate: RowItem {
                    required property int index
                    required property var modelData
                    objectName: "gameRow"
                    width: gameList.width
                    height: implicitHeight
                    textObjectName: "gameRowText"
                    // Spec row format: «имя (дата_изменения)» — roles from the VM.
                    text: modelData.name + " (" + modelData.modifiedLabel + ")"
                    selected: vm.selectedIndex === index

                    onSelectedRequested: {
                        gameList.currentIndex = index
                        vm.set_selected(index)
                    }
                    onActivateRequested: root.openGame(modelData.path)
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Tokens.px(root.islandTokens, "space.sm", 8)

            ThemeButton {
                objectName: "newButton"
                text: "Новая игра"
                onClicked: vm.createRequested("")
            }
            ThemeButton {
                objectName: "importButton"
                text: "Импорт"
                onClicked: vm.importRequested("")
            }
            ThemeButton {
                objectName: "themeToggleButton"
                // Label names the theme the toggle would switch TO.
                text: root.currentTheme === "light" ? "Тёмная тема" : "Светлая тема"
                onClicked: root.themeToggleRequested()
            }

            Item { Layout.fillWidth: true }

            ThemeButton {
                objectName: "deleteButton"
                text: "Удалить"
                // Spec: without a selected row the button is a no-op.
                onClicked: if (vm.selectedIndex >= 0) vm.deleteRequested(vm.selectedIndex)
            }
            ThemeButton {
                id: openButton
                objectName: "openButton"
                text: "Открыть"
                accentBackground: true
                onClicked: root.openGame(vm.selectedPath)
            }
        }
    }
}
