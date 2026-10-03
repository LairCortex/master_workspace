// Entity preview island — the readable right column (change
// nri-0022-entity-preview, tasks 4.1–4.5; multi-pane since NRI-0025 task 4.1).
//
// The column is a stack of up to four equal-height panes (design Д6, checkpoint
// docs/qa/2026-10-02-preview-pins-layout.md): the pinned cards in pin order
// and the live card last, each pane its own 32 px header band + CardPanel
// with its OWN Flickable — one pane = the whole column, so the zero-pins
// column paints the pre-NRI-0022 markup bit-for-bit. The header band lives
// OUTSIDE the flickable (checkpoint п.1: the scroll structurally cannot reach
// under the band, no sticky logic needed). Between panes the column breathes
// space.sm, inside a pane space.xs; the pane floor is the checkpoint's 88 px.
// The column's «Карточка» band is painted only at zero panes — from the first
// pane on, the first pane's own band holds the columns' header axis (same
// 32 px band, same space.xs inset, panelHeader.js law of 2026-09-26).
//
// Read-only for content by contract (spec entity-preview «Состав читаемого
// предпросмотра»): no TextField, no edit gesture anywhere — the interactive
// set is the picture (opens the viewer), the navigation channels (relation
// rows via the library RowItem, mention anchors in the rich-text sections)
// and since NRI-0025 the pane's pin button (the one new interactivity,
// design Д5 — its four name/tooltip formulations are pinned by the
// conventions guard). The VM answers every text already render-ready and
// authors the pin state word; this file only paints and forwards gestures.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import nri.components
import "nri/components/tokens.js" as Tokens
import "nri/components/panelHeader.js" as PanelHeader

Rectangle {
    id: root
    objectName: "entityPreviewRoot"
    implicitWidth: 420
    implicitHeight: 520

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor:
        Tokens.token(root.islandTokens, "color.bg.surface", "white")
    readonly property color canvasColor:
        Tokens.token(root.islandTokens, "color.bg.canvas", "white")
    readonly property color primaryText:
        Tokens.token(root.islandTokens, "color.fg.primary", "black")
    readonly property color secondaryText:
        Tokens.token(root.islandTokens, "color.fg.secondary", "gray")
    readonly property color mutedColor:
        Tokens.token(root.islandTokens, "color.fg.muted", "gray")
    readonly property color borderColor:
        Tokens.token(root.islandTokens, "color.border", "lightgray")
    // The mention anchors read as the skin's accent (compiler.mention_style's
    // island counterpart: the RichText label colours its links through the
    // Text.linkColor token, so a live retheme repaints without a re-render).
    readonly property color accentColor:
        Tokens.token(root.islandTokens, "color.accent", "black")
    // The readability step-up (the reader's request 2026-09-28): every
    // readable line of the card — the short fields, the section bodies, the
    // music link — rides two px above the skin's md text, so the preview
    // stays legible while the titles keep the shared library look.
    readonly property int bodyFontPixelSize:
        Tokens.px(root.islandTokens, "font.size.md", 13) + 2
    // The content inset (live bug 2026-09-30: the card texts glued themselves
    // to the borders). One token for the whole island — the same space.sm the
    // library card exposes as its own content padding (CardPanel.padding) and
    // the detail row uses inside its ThemeRatingCard — so the header line, the
    // identity band and the long sections all breathe the same distance from
    // every border. The band's TOP inset deliberately stays the shared
    // space.xs of the three column roots (panelHeader.js axis): the padding
    // moves the content off the edges, never the header off its line.
    readonly property int contentPadding:
        Tokens.px(root.islandTokens, "space.sm", 8)
    // The frame's shape for the layout half of the checkpoint: zero panes is
    // today's markup (band + card, one space.xs gap); with panes the column
    // separates the cards by space.sm (п.1 «рамка + воздух»).
    readonly property int panesCount: entityPreviewVm.panes.length
    // The self-explaining hint, one home for both empty faces (delta
    // entity-preview «Пустой предпросмотр объясняет себя»): the fully empty
    // column and the empty live area read the SAME sentence — and it no
    // longer points at the middle column (the entity arrives from relations,
    // search and the middle column alike).
    readonly property string emptyHintText:
        "Выберите сущность — здесь появится её карточка"
    // The scroll memory of the pinned slots (bug docs/qa/2026-10-03-preview-
    // scroll-reset.md): the Repeater's model is a plain list without identity,
    // so every contentChanged recreates ALL delegates and a fresh Flickable
    // starts at the top. Each destroyed pinned pane leaves its offset in this
    // JS map under its slotKey (the pair plus the half — the card VM's
    // identity), and the pane reborn under the same key sits back into it.
    // The rev check is the invalidation: only a genuinely rebuilt card (a
    // save refreshed its row, a pin transition, a limit word change) carries
    // a new rev, so exactly the card whose content really moved repaints from
    // the top while its neighbours keep reading. The live copy is never
    // stored: a new selection always opens from the top (QA 2026-10-03).
    property var slotScrollMemory: ({})

    color: root.surfaceColor

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Tokens.px(root.islandTokens, "space.xs", 4)
        spacing: root.panesCount === 0
            ? Tokens.px(root.islandTokens, "space.xs", 4)
            : Tokens.px(root.islandTokens, "space.sm", 8)

        // The column header rides the shared panel-header band (panelHeader.js)
        // and exists ONLY while the column shows no card at all (checkpoint
        // п.2): with the first pane its own band takes the axis, so a second
        // caption never stacks above the cards (delta «Заголовок
        // предпросмотра — единственная строка заголовка»: a fully empty column
        // is signed by the plain word «Карточка»).
        Item {
            objectName: "previewHeaderBand"
            visible: root.panesCount === 0
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            // The band keeps the shared 32 px height and the shared space.xs
            // top inset (its y stays the header axis of the three columns);
            // only its horizontal entry steps in by the content padding, so
            // the caption reads over the card's content, not on the border.
            Layout.leftMargin: root.contentPadding
            Layout.rightMargin: root.contentPadding
            implicitHeight: PanelHeader.band()
            Layout.preferredHeight: implicitHeight

            TitleText {
                objectName: "previewBandTitle"
                text: "Карточка"
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
            }
        }

        // The pinned panes in pin order, the live card last (VM contract,
        // design Д2): equal shares (Layout.fillHeight), the checkpoint's 88 px
        // floor, each pane its own Flickable — «visible cards divide the
        // column evenly, each scrolls independently» (spec preview-pins).
        Repeater {
            model: entityPreviewVm.panes

            ColumnLayout {
                id: previewPane
                required property var modelData
                objectName: "previewPane_" + modelData.slotIndex
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 88
                spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                // The memory's write side (2026-10-03 fix): the frame this
                // pane was born in is gone — hand its scroll position to the
                // pane reborn under the same slotKey, rev stamped so only the
                // identical construction may sit back into it. Live panes
                // keep no memory (a new selection opens from the top).
                Component.onDestruction: {
                    if (previewPane.modelData.pinned)
                        root.slotScrollMemory[previewPane.modelData.slotKey] = {
                            rev: previewPane.modelData.rev,
                            y: previewScroll.contentY,
                        }
                }

                // The card's own band — its ONLY headline line (delta
                // «Заголовок предпросмотра»): «Карточка: <тип из реестра> ·
                // <имя сущности>» from the VM (the reader's fix 2026-10-03
                // moved the name into the caption — with up to four cards in
                // the column the headline must say WHICH card it is; the
                // duplicate with the name field inside is the point).
                // It sits OUTSIDE the flickable — the header is fixed above
                // the scrolling content, its canvas staying the surface the
                // band has always worn.
                Item {
                    objectName: "previewPaneBand_" + previewPane.modelData.slotIndex
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.leftMargin: root.contentPadding
                    Layout.rightMargin: root.contentPadding
                    implicitHeight: PanelHeader.band()
                    Layout.preferredHeight: implicitHeight

                    TitleText {
                        objectName: "previewPaneTitle"
                        text: previewPane.modelData.title
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        // The pin square keeps the caption off its corner.
                        width: parent.width - pinButton.width
                            - Tokens.px(root.islandTokens, "space.xs", 4)
                    }

                    // The pin (NRI-0025 task 4.2, design Д5): the library
                    // square in its GHOST set — the штатный Button seat ships
                    // the role AND the accessibility Press (one Press is one
                    // real click, pinned in test_theme_icon_button), the NAME
                    // is this usage site's: the four fixed formulations that
                    // state the button's very state (the conventions guard
                    // pins the quartet; DESCRIPTION_VOCABULARY stays closed —
                    // the name already names the action, no description).
                    // Which of the four applies is the column VM's authorship
                    // (pinState) — the island never counts the cap here.
                    // The face carries the state too (user request 2026-10-03,
                    // «нет визуального подтверждения что карточка закреплена»):
                    // an un-pinned pin LEANS 45° right; a pinned card's pin
                    // stands upright and wears the accent colour — the pin's
                    // own look answers «закреплена?» without a press. The
                    // lean is read from the card's own pinned flag; the
                    // disabled duplicate/limit pins lean as well (they are
                    // not pinned either — the muted face still outranks the
                    // accent, the library's one tint chain).
                    ThemeIconButton {
                        id: pinButton
                        objectName: "previewPinButton_" + previewPane.modelData.slotIndex
                        ghost: true
                        iconName: "pin"
                        iconRotation: previewPane.modelData.pinned ? 0 : 45
                        iconAccentTint: previewPane.modelData.pinned
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        readonly property bool actionable:
                            previewPane.modelData.pinState !== "duplicate"
                            && previewPane.modelData.pinState !== "limit"
                        readonly property string pinLabel: previewPane.modelData.pinned
                            ? "Открепить карточку"
                            : previewPane.modelData.pinState === "duplicate"
                                ? "Уже закреплена"
                                : previewPane.modelData.pinState === "limit"
                                    ? "Можно закрепить только 3 карточки"
                                    : "Закрепить карточку"
                        enabled: actionable
                        Accessible.name: pinLabel
                        Nri.tooltip: pinLabel
                        HoverHandler {
                            // The shim's documented glue (design Д5): the hover
                            // reports the DECLARED text — and a disabled pin
                            // keeps answering hover (probed offscreen), so the
                            // capacity/duplicate wordings reach the reader.
                            onHoveredChanged: tooltipBridge.tooltipRequested(
                                hovered ? pinButton.Nri.tooltip : "",
                                point.scenePosition
                            )
                        }
                        onClicked: entityPreviewVm.requestPinToggle(
                            previewPane.modelData.entityType,
                            previewPane.modelData.entityId,
                            previewPane.modelData.pinned
                        )
                    }
                }

                // The card's canvas — exactly the pre-NRI-0025 composition
                // (checkpoint «содержимое карточки — текущая previewContent
                // 1-в-1»), just rebound to the pane's own dictionary.
                CardPanel {
                    objectName: "previewPaneCanvas"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: root.canvasColor
                    clip: true

                    // Long text scrolls per pane (the old column rule moved
                    // into every delegate): the whole composition is one
                    // column inside THIS flickable and the canvas clips it.
                    Flickable {
                        id: previewScroll
                        objectName: "previewScroll"
                        anchors.fill: parent
                        // The card's content inset: the 1px hairline plus the
                        // island's padding — the viewport itself (so the long
                        // sections, the music line and the last relation
                        // block too) never paints on the canvas border.
                        anchors.margins: 1 + root.contentPadding
                        contentWidth: width
                        contentHeight: previewContent.implicitHeight
                        boundsBehavior: Flickable.StopAtBounds
                        // The memory's read side (2026-10-03 fix, hardened
                        // the same day by the drift report): the pane reborn
                        // under a remembered slotKey of the SAME rev sits
                        // back into the old offset. A fresh delegate is laid
                        // out on transient geometry — measured: contentHeight
                        // sweeps 0 → partial → oversized → final while the
                        // pane height sweeps 0 → negative → settled — so the
                        // remembered offset must wait until it truly fits:
                        // an attempt that lands short of it (content shorter
                        // or taller-but-insufficient) reads as far as the
                        // content allows and stays ARMED, re-landing exactly
                        // when contentHeight or the viewport moves again. The
                        // first cut cleared the pending value after its very
                        // first attempt, so a card reborn mid-transient kept
                        // the clamped (or zero) position forever — the
                        // observed drift after a mention/relation transition.
                        // StopAtBounds never clamps a programmatic contentY
                        // by itself; a real user drag or flick retires the
                        // wait — the reader's own gesture outranks a memory
                        // that has not landed yet.
                        property real pendingRestoredY: 0.0
                        function applyPendingRestoredY() {
                            if (previewScroll.pendingRestoredY <= 0.0)
                                return
                            const capacity =
                                previewScroll.contentHeight - previewScroll.height
                            if (capacity >= previewScroll.pendingRestoredY) {
                                previewScroll.contentY = previewScroll.pendingRestoredY
                                previewScroll.pendingRestoredY = 0.0
                            } else if (capacity > 0.0) {
                                previewScroll.contentY = capacity
                            }
                        }
                        onContentHeightChanged: previewScroll.applyPendingRestoredY()
                        onHeightChanged: previewScroll.applyPendingRestoredY()
                        onDragStarted: previewScroll.pendingRestoredY = 0.0
                        onFlickStarted: previewScroll.pendingRestoredY = 0.0
                        Component.onCompleted: {
                            const saved = root.slotScrollMemory[previewPane.modelData.slotKey]
                            if (saved !== undefined && saved.rev === previewPane.modelData.rev)
                                previewScroll.pendingRestoredY = saved.y
                            previewScroll.applyPendingRestoredY()
                        }

                        ColumnLayout {
                            id: previewContent
                            objectName: "previewContent"
                            width: previewScroll.width
                            spacing: Tokens.px(root.islandTokens, "space.sm", 8)

                            // The identity band (live fix 2026-09-27, the
                            // reader's sketch): the picture seats top-left,
                            // the short lines (name, rating, dates, age) read
                            // to its right, and only below them do the long
                            // text sections, the music and the relation
                            // blocks run full width. The rule is the top-slice
                            // answer to short panes (checkpoint п.6): the
                            // name/rating/dates/age are what stays visible
                            // when 3–4 panes share the column.
                            RowLayout {
                                id: previewIdentityRow
                                objectName: "previewIdentityRow"
                                Layout.fillWidth: true
                                Layout.alignment: Qt.AlignTop
                                spacing: Tokens.px(root.islandTokens, "space.sm", 8)

                                // The picture slot (task 4.3): the preview copy
                                // through the shared image_utils pipeline; a
                                // null pixmap arrives here as an empty
                                // imageSource and the placeholder paints. It
                                // takes exactly half of the band and scales
                                // with the column (the reader's sketch, live
                                // fix 2026-09-28), the portrait 4:3 proportion
                                // keeping the tall look as the width grows.
                                Item {
                                    id: previewImageSlot
                                    objectName: "previewImageBlock"
                                    Layout.preferredWidth: Math.round(previewIdentityRow.width / 2)
                                    Layout.preferredHeight: Math.round(previewImageSlot.width * 4 / 3)
                                    Layout.alignment: Qt.AlignTop

                                    Image {
                                        id: previewImage
                                        objectName: "previewImage"
                                        anchors.fill: parent
                                        source: previewPane.modelData.imageSource
                                        fillMode: Image.PreserveAspectFit
                                        asynchronous: true
                                        visible: previewPane.modelData.imageSource !== ""
                                        // Accessibility: the same picture
                                        // contract as the detail row — the
                                        // named «open the image» button (the
                                        // detail-panel design map), the
                                        // MouseArea below stays the mouse
                                        // path. The gesture names its pane so
                                        // the facade builds the viewer from
                                        // THIS card (task 2.2).
                                        Accessible.role: Accessible.Button
                                        Accessible.name: previewPane.modelData.nameText !== ""
                                            ? previewPane.modelData.nameText : "Изображение"
                                        Accessible.description: "Открыть изображение"
                                        Accessible.onPressAction: entityPreviewVm.requestImageFor(
                                            previewPane.modelData.entityType,
                                            previewPane.modelData.entityId,
                                            previewPane.modelData.pinned
                                        )
                                    }

                                    // The empty slot gets the Lucide «image»
                                    // glyph above the hint (user request
                                    // 2026-09-30); the HintText keeps the
                                    // placeholder's objectName and its caption
                                    // — the icon is decoration.
                                    Column {
                                        anchors.centerIn: parent
                                        spacing: Tokens.px(root.islandTokens, "space.xs", 4)
                                        visible: previewPane.modelData.imageSource === ""
                                        ThemeIcon {
                                            objectName: "previewImagePlaceholderIcon"
                                            anchors.horizontalCenter: parent.horizontalCenter
                                            name: "image"
                                            size: 32
                                            tint: root.mutedColor
                                        }
                                        HintText {
                                            objectName: "previewImagePlaceholder"
                                            anchors.horizontalCenter: parent.horizontalCenter
                                            text: "Нет изображения"
                                            italic: true
                                        }
                                    }

                                    MouseArea {
                                        objectName: "previewImageMouseArea"
                                        anchors.fill: parent
                                        enabled: previewPane.modelData.imageSource !== ""
                                        visible: enabled
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: entityPreviewVm.requestImageFor(
                                            previewPane.modelData.entityType,
                                            previewPane.modelData.entityId,
                                            previewPane.modelData.pinned
                                        )
                                    }
                                }

                                // The short lines beside the picture: they wrap
                                // rather than elide, the narrow band must
                                // never hide a date. The one exception is the
                                // checkpoint's readability rule (п.6): on a
                                // pane whose canvas drops under 110 px the
                                // name caps at two elided lines, so long names
                                // cannot push the rating/dates/age past the
                                // top slice.
                                ColumnLayout {
                                    objectName: "previewFactsColumn"
                                    Layout.fillWidth: true
                                    Layout.alignment: Qt.AlignTop
                                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                                    TitleText {
                                        objectName: "previewName"
                                        Layout.fillWidth: true
                                        text: previewPane.modelData.nameText
                                        visible: text !== ""
                                        readonly property bool crampedCanvas:
                                            previewScroll.height < 110
                                        elide: crampedCanvas ? Text.ElideRight : Text.ElideNone
                                        maximumLineCount: crampedCanvas ? 2 : 0
                                        wrapMode: Text.WordWrap
                                    }

                                    Text {
                                        objectName: "previewRating"
                                        Layout.fillWidth: true
                                        text: previewPane.modelData.ratingText
                                        visible: text !== ""
                                        color: root.secondaryText
                                        font.pixelSize: root.bodyFontPixelSize
                                        wrapMode: Text.WordWrap
                                    }

                                    Text {
                                        objectName: "previewDates"
                                        Layout.fillWidth: true
                                        text: previewPane.modelData.dateText
                                        visible: text !== ""
                                        color: root.secondaryText
                                        font.pixelSize: root.bodyFontPixelSize
                                        wrapMode: Text.WordWrap
                                    }

                                    Text {
                                        objectName: "previewAge"
                                        Layout.fillWidth: true
                                        text: previewPane.modelData.ageText
                                        visible: text !== ""
                                        color: root.secondaryText
                                        font.pixelSize: root.bodyFontPixelSize
                                        wrapMode: Text.WordWrap
                                    }
                                }
                            }

                            // The text fields (Характеристики / Предыстория /
                            // Личность / Задачи) with clickable @mentions: the
                            // VM delivers each as the mention_html generator's
                            // anchors; a click hands the href to requestLink,
                            // which navigates generated anchors only (task
                            // 4.5). Since NRI-0025 the target lands in the
                            // live area from ANY pane (spec «Переход из
                            // закреплённой карточки»).
                            Repeater {
                                model: previewPane.modelData.sections

                                ColumnLayout {
                                    id: previewSection
                                    objectName: "previewSection_" + modelData.key
                                    required property var modelData
                                    Layout.fillWidth: true
                                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                                    TitleText {
                                        objectName: "previewSectionLabel"
                                        Layout.fillWidth: true
                                        text: previewSection.modelData.label + ":"
                                    }

                                    Text {
                                        objectName: "previewSectionText"
                                        Layout.fillWidth: true
                                        text: previewSection.modelData.html
                                        textFormat: Text.RichText
                                        wrapMode: Text.WordWrap
                                        color: root.primaryText
                                        linkColor: root.accentColor
                                        font.pixelSize: root.bodyFontPixelSize
                                        onLinkActivated: function (link) {
                                            entityPreviewVm.requestLink(link)
                                        }
                                    }
                                }
                            }

                            TitleText {
                                objectName: "previewMusicLabel"
                                Layout.fillWidth: true
                                text: "Музыка:"
                                visible: previewPane.modelData.musicUrl !== ""
                            }

                            Text {
                                objectName: "previewMusic"
                                Layout.fillWidth: true
                                text: previewPane.modelData.musicUrl
                                visible: text !== ""
                                color: root.secondaryText
                                wrapMode: Text.WrapAnywhere
                                font.pixelSize: root.bodyFontPixelSize
                            }

                            // Compact relation sections (task 4.4): one per
                            // registry relation the host actually has rows
                            // for — the VM drops the empty ones, so an empty
                            // block never reaches here.
                            Repeater {
                                model: previewPane.modelData.relatedSections

                                ColumnLayout {
                                    id: previewRelatedSection
                                    objectName: "previewRelatedSection_" + modelData.key
                                    required property var modelData
                                    Layout.fillWidth: true
                                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                                    TitleText {
                                        objectName: "previewRelatedLabel"
                                        Layout.fillWidth: true
                                        text: previewRelatedSection.modelData.label + ":"
                                    }

                                    Repeater {
                                        model: previewRelatedSection.modelData.rows

                                        RowItem {
                                            objectName: "previewRelatedRow"
                                            required property var modelData
                                            Layout.fillWidth: true
                                            text: modelData.name
                                            // Accessibility contract: the library
                                            // row owns the ListItem role, the
                                            // name is the visible content, the
                                            // usage-site spells the hidden
                                            // meaning of the activation — both
                                            // the mouse paths and the
                                            // component's single Press run the
                                            // same navigation.
                                            accessibleDescription: "Переходит к сущности"
                                            onSelectedRequested: entityPreviewVm.requestEntity(
                                                modelData.type, modelData.id
                                            )
                                            onActivateRequested: entityPreviewVm.requestEntity(
                                                modelData.type, modelData.id
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // The empty face, one panel two readings (checkpoint п.2/п.3): with
        // zero panes it is the fully empty column under the «Карточка» band,
        // bit-for-bit today's markup; with pins above it the SAME panel is the
        // empty LIVE area — no header band of its own (delta «Пустая живая
        // область без заголовка»), the same sentence, but wrapped (on a
        // 220 px-wide column the elided single line ate half the phrase), and
        // it shares the equal heights on the panes' own terms.
        CardPanel {
            objectName: "previewCanvas"
            visible: entityPreviewVm.liveEmpty
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 88
            color: root.canvasColor
            clip: true

            HintText {
                objectName: "previewEmptyHint"
                anchors.centerIn: parent
                visible: root.panesCount === 0
                text: root.emptyHintText
                italic: true
            }

            HintText {
                objectName: "previewLiveEmptyHint"
                anchors.centerIn: parent
                visible: root.panesCount > 0
                text: root.emptyHintText
                italic: true
                width: parent.width - 2 * root.contentPadding
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
            }
        }
    }
}
