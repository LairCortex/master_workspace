// Char-sheet list island (change port-sheet-list-preset-dialogs-qml-q3a,
// task 2.1; designs D2/D4/D5) — the QML half of the «Чар-листы» dialog,
// replacing the migrated QTabWidget/QListWidget chrome 1:1.
//
// Context contract (the QDialog facade replicates the launcher's seam,
// design D1). The VM name is island-scoped: QQuickWidget.rootContext() on
// the shared process engine writes into the ENGINE-wide root context (docs:
// «changes propagate to instances sharing the engine»), the launcher/timeline
// islands own the plain `vm` name, and this dialog coexists with them —
// re-using it there would blind those islands' bindings.
//   * `sheetListVm`     — SheetListViewModel: the two row models (roles
//                         `id`/`label`) bind read-only through
//                         `sheetListVm.templateList` /
//                         `sheetListVm.instanceList`; the island only calls
//                         the sync slots `setCurrentTab`/`selectTemplate`/
//                         `selectInstance` and reads
//                         `sheetListVm.currentTab`/`canOpen`/`canRename`/
//                         `canDelete`/`presetButtonVisible` — never an async
//                         entry (spec qml-shell «Контракт биндингов»). All
//                         coroutines (create/open/rename/delete/refresh under
//                         `run_locked`, the native QInputDialog/QMessageBox)
//                         live on the facade, fed by the `*Requested` signals
//                         below.
//   * `islandPalette` — the ONLY color/spacing source: the library bridge
//                       name, pushed by this dialog's facade from its own
//                       dialog-owned QmlPalette (the launcher/timeline
//                       contract — the name resolves engine-wide because
//                       widgets on one engine share its root context). Read
//                       through the library's tokens.js; bare «palette» is
//                       shadowed by Controls in any scope (LauncherRoot.qml
//                       header).
//                       Off-skin (empty tokens, design D7) the guarded
//                       resolveTokens seam degrades to the named Qt globals
//                       — no hex, no OS palette, no color math here.
//
// The «лист — шаблон» labels are composed Python-side (design D2 — one rule
// implementation), so the delegates only display `modelData.label`.
// Qt 6 Basic Buttons expose no «default» property — «Открыть» is marked
// through `root.defaultButton`, the dialog wrapper clicks it on Enter (D5).
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "sheetListRoot"

    // Natural content size (island_size.py mirrors it onto the window): the
    // button row declares the width the six actions need, so the dialog opens
    // wide enough instead of squeezing their texts off the window. The old
    // 420x520 stays as the floor.
    readonly property real contentMargin:
        Tokens.px(islandTokens, "space.md", 16)
    implicitWidth: Math.max(
        420, sheetListColumn.implicitWidth + 2 * contentMargin)
    implicitHeight: Math.max(
        520, sheetListColumn.implicitHeight + 2 * contentMargin)

    // ── root contract to the facade (the migrated button flows) ─────────────
    // Argument-free: the facade reads the tab + per-tab selection back from
    // the VM, exactly like the old `_on_instances_tab`/`_selected_id` helpers.
    signal createRequested()
    signal presetRequested()
    signal openRequested()
    signal renameRequested()
    signal deleteRequested()
    signal closeRequested()

    // Enter marker (design D5): the wrapper's Enter key clicks this button.
    readonly property Item defaultButton: openButton

    // ── palette bridge (colors/spacing only ever come from here) ────────────
    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor: Tokens.token(root.islandTokens, "color.bg.surface", "white")
    readonly property color canvasColor: Tokens.token(root.islandTokens, "color.bg.canvas", "white")
    readonly property color fgColor: Tokens.token(root.islandTokens, "color.fg.primary", "black")
    readonly property color borderColor: Tokens.token(root.islandTokens, "color.border", "lightgray")

    color: surfaceColor

    ColumnLayout {
        id: sheetListColumn
        anchors.fill: parent
        anchors.margins: root.contentMargin
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        // The migrated «Чар-листы текущей игры» hint caption (hint role).
        HintText {
            objectName: "sheetListHint"
            text: "Чар-листы текущей игры"
            Layout.fillWidth: true
        }

        // Tabs — the migrated QTabWidget («Шаблоны»/«Листы»). The bar mirrors
        // `sheetListVm.currentTab` and pushes taps back through the sync slot; the VM
        // ignores repeat/out-of-range indices, so the round trip is idempotent.
        ThemeTabBar {
            id: tabBar
            Layout.fillWidth: true
            currentIndex: sheetListVm.currentTab
            onCurrentIndexChanged: sheetListVm.setCurrentTab(currentIndex)

            ThemeTabButton {
                objectName: "tabTemplates"
                text: "Шаблоны"
            }
            ThemeTabButton {
                objectName: "tabInstances"
                text: "Листы"
            }
        }

        StackLayout {
            id: pages
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: tabBar.currentIndex

            // ── «Шаблоны» tab: the migrated list_widget ───────────────────
            // List frame: surface-in-canvas with the token border (launcher
            // pattern — the ListView itself stays chromeless).
            Rectangle {
                radius: Tokens.px(root.islandTokens, "radius.sm", 6)
                color: root.canvasColor
                border.color: root.borderColor
                border.width: 1
                clip: true

                ListView {
                    id: templateListView
                    objectName: "templateList"
                    anchors.fill: parent
                    anchors.margins: 1  // keep rows off the 1px border
                    model: sheetListVm.templateList
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                    // RowItem (library): selection colors mirror the catalog
                    // list role, the look/tap machinery is the library's.
                    // Double-click stays unwired — the migrated dialog had no
                    // activate-on-double-click flow («поведение не меняется»).
                    delegate: RowItem {
                        required property int index
                        required property var modelData
                        objectName: "templateRow"
                        textObjectName: "templateRowText"
                        width: templateListView.width
                        height: implicitHeight
                        text: modelData.label
                        selected: sheetListVm.selectedTemplateId === modelData.id
                        onSelectedRequested: sheetListVm.selectTemplate(index)
                    }
                }

                // NRI-0015 (B6, design T2): the empty tab explains itself with
                // the same muted hint face the timeline uses; it disappears
                // with the first row.
                HintText {
                    objectName: "templatesListHint"
                    anchors.centerIn: parent
                    visible: templateListView.count === 0
                    text: "Шаблонов ещё нет — создайте или возьмите пресет"
                }
            }

            // ── «Листы» tab: the migrated instance_list ────────────────────
            Rectangle {
                radius: Tokens.px(root.islandTokens, "radius.sm", 6)
                color: root.canvasColor
                border.color: root.borderColor
                border.width: 1
                clip: true

                ListView {
                    id: instanceListView
                    objectName: "instanceList"
                    anchors.fill: parent
                    anchors.margins: 1
                    model: sheetListVm.instanceList
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                    // `modelData.label` is the Python-composed
                    // «лист — шаблон» label (design D2) — never concatenated
                    // here.
                    delegate: RowItem {
                        required property int index
                        required property var modelData
                        objectName: "instanceRow"
                        textObjectName: "instanceRowText"
                        width: instanceListView.width
                        height: implicitHeight
                        text: modelData.label
                        selected: sheetListVm.selectedInstanceId === modelData.id
                        onSelectedRequested: sheetListVm.selectInstance(index)
                    }
                }
            }
        }

        // Button row — the migrated QHBoxLayout + «Закрыть» on the right.
        // create/close carry no availability rules in the old dialog; open/
        // rename/delete ride the VM's per-tab flags; «Создать из пресета…» is
        // an action of the templates tab only (`presetButtonVisible`).
        RowLayout {
            Layout.fillWidth: true
            spacing: Tokens.px(root.islandTokens, "space.sm", 8)

            ThemeButton {
                objectName: "createButton"
                text: "Создать"
                onClicked: root.createRequested()
            }
            ThemeButton {
                objectName: "presetButton"
                text: "Создать из пресета…"
                visible: sheetListVm.presetButtonVisible
                onClicked: root.presetRequested()
            }
            ThemeButton {
                id: openButton
                objectName: "openButton"
                text: "Открыть"
                accentBackground: true
                enabled: sheetListVm.canOpen
                onClicked: root.openRequested()
            }
            ThemeButton {
                objectName: "renameButton"
                text: "Переименовать"
                enabled: sheetListVm.canRename
                onClicked: root.renameRequested()
            }
            ThemeButton {
                objectName: "deleteButton"
                text: "Удалить"
                enabled: sheetListVm.canDelete
                onClicked: root.deleteRequested()
            }

            Item { Layout.fillWidth: true }

            ThemeButton {
                objectName: "closeButton"
                text: "Закрыть"
                onClicked: root.closeRequested()
            }
        }
    }
}
