// Launcher island (spec game-launcher «Поверхность лаунчера — QML-островок»).
//
// Context contract (design D6, replicated by the QDialog wrapper in group 6):
//   * `vm`            — LauncherViewModel: bound read-only (games/
//                       selectedIndex/selectedPath); buttons emit its
//                       *Requested signals and call sync set_selected()
//                       only — never an async entry (spec qml-shell
//                       «Контракт биндингов»).
//   * `islandPalette` — QmlPalette: the ONLY color/spacing source. The name
//                       deliberately differs from the engine-level
//                       "palette": Qt Quick Controls shadow the bare
//                       «palette» identifier in any scope, so the island
//                       context must carry the bridge under this name.
//                       No hex literals, no OS palette here; off-skin
//                       (empty `tokens`, design D7) bindings fall back to
//                       named Qt globals, controls stay on their plain
//                       Basic look and nothing throws.
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
import QtQuick.Controls
import QtQuick.Layouts

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

    // ---- palette bridge helpers (colors/spacing only ever come from here) ----

    readonly property var tokens: islandPalette.tokens

    function token(name, fallback) {
        var value = root.tokens[name]
        return value === undefined ? fallback : value
    }

    // Token values are CSS strings ("8px", "13px"); the numeric part drives
    // geometry. Not a color derivation — a unit read of the very same token.
    function px(name, fallback) {
        var value = Number.parseFloat(root.token(name, ""))
        return Number.isNaN(value) ? fallback : value
    }

    readonly property color surfaceColor: token("color.bg.surface", "white")
    readonly property color canvasColor: token("color.bg.canvas", "white")
    readonly property color fgColor: token("color.fg.primary", "black")
    readonly property color mutedColor: token("color.fg.muted", "gray")
    readonly property color borderColor: token("color.border", "lightgray")
    readonly property color accentColor: token("color.accent", "black")
    readonly property color accentFgColor: token("color.accent.fg", "white")

    function accentHover(base) { return token("color.accent.hover", base) }
    function accentPressed(base) { return token("color.accent.pressed", base) }

    function openGame(path) {
        // Spec: «Открыть» without a selected row is a no-op. The signal is
        // the VM's own (the island emits it; the controller answers).
        if (path) vm.openRequested(path)
    }

    color: surfaceColor

    // Inline themed button for every action in the row (no hex; off-skin
    // degrades to the plain Basic text button: background stays hidden).
    component ThemedButton: Button {
        id: control
        property bool accentBackground: false
        readonly property bool skinned: root.tokens["color.bg.surface"] !== undefined

        padding: root.px("space.sm", 8)
        leftPadding: padding
        rightPadding: padding
        font.pixelSize: root.px("font.size.md", 13)

        contentItem: Text {
            text: control.text
            font: control.font
            color: !control.enabled
                ? root.mutedColor
                : control.accentBackground ? root.accentFgColor : root.fgColor
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }

        background: Rectangle {
            visible: control.skinned  // off-skin: bare Basic text button
            radius: root.px("radius.sm", 6)
            border.width: control.accentBackground ? 0 : 1
            border.color: control.accentBackground ? "transparent" : root.borderColor
            color: {
                if (!control.enabled)
                    return root.canvasColor
                if (control.accentBackground)
                    return control.pressed ? root.accentPressed(root.accentColor)
                         : control.hovered ? root.accentHover(root.accentColor)
                         : root.accentColor
                return control.pressed ? root.accentPressed(root.canvasColor)
                     : control.hovered ? root.accentHover(root.canvasColor)
                     : root.canvasColor
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: root.px("space.md", 16)
        spacing: root.px("space.sm", 8)

        Text {
            text: "Выберите игру или создайте новую"
            font.pixelSize: root.px("font.size.xl", 16)
            font.weight: root.px("font.weight.bold", 400)
            color: root.fgColor
            Layout.fillWidth: true
        }

        // List frame: surface-in-canvas with the token border.
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: root.px("radius.sm", 6)
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
                spacing: root.px("space.xs", 4)

                delegate: Rectangle {
                    id: gameRow
                    required property int index
                    required property var modelData
                    objectName: "gameRow"
                    readonly property bool selected: vm.selectedIndex === index

                    width: gameList.width
                    height: gameRowText.implicitHeight + 2 * root.px("space.xs", 4)
                    color: gameRow.selected ? root.accentColor : "transparent"

                    Text {
                        id: gameRowText
                        objectName: "gameRowText"
                        anchors.left: parent.left
                        anchors.leftMargin: root.px("space.sm", 8)
                        anchors.right: parent.right
                        anchors.rightMargin: root.px("space.sm", 8)
                        anchors.verticalCenter: parent.verticalCenter
                        // Spec row format: «имя (дата_изменения)» — roles from the VM.
                        text: modelData.name + " (" + modelData.modifiedLabel + ")"
                        color: gameRow.selected ? root.accentFgColor : root.fgColor
                        font.pixelSize: root.px("font.size.md", 13)
                        elide: Text.ElideRight
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            gameList.currentIndex = gameRow.index
                            vm.set_selected(gameRow.index)
                        }
                        onDoubleClicked: root.openGame(gameRow.modelData.path)
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: root.px("space.sm", 8)

            ThemedButton {
                objectName: "newButton"
                text: "Новая игра"
                onClicked: vm.createRequested("")
            }
            ThemedButton {
                objectName: "importButton"
                text: "Импорт"
                onClicked: vm.importRequested("")
            }
            ThemedButton {
                objectName: "themeToggleButton"
                // Label names the theme the toggle would switch TO.
                text: root.currentTheme === "light" ? "Тёмная тема" : "Светлая тема"
                onClicked: root.themeToggleRequested()
            }

            Item { Layout.fillWidth: true }

            ThemedButton {
                objectName: "deleteButton"
                text: "Удалить"
                // Spec: without a selected row the button is a no-op.
                onClicked: if (vm.selectedIndex >= 0) vm.deleteRequested(vm.selectedIndex)
            }
            ThemedButton {
                id: openButton
                objectName: "openButton"
                text: "Открыть"
                accentBackground: true
                onClicked: root.openGame(vm.selectedPath)
            }
        }
    }
}
