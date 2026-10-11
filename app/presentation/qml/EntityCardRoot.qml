import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "entityCardRoot"

    readonly property Item defaultButton: saveButton
    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor:
        Tokens.token(islandTokens, "color.bg.surface", "white")
    readonly property color canvasColor:
        Tokens.token(islandTokens, "color.bg.canvas", "white")
    readonly property color foregroundColor:
        Tokens.token(islandTokens, "color.fg.primary", "black")
    readonly property color borderColor:
        Tokens.token(islandTokens, "color.border", "lightgray")
    readonly property color accentColor:
        Tokens.token(islandTokens, "color.accent", "black")

    // NRI-0014 task 4.2 (E1): the card's visible title line, outside the
    // scroll — the title and the cross must stay reachable without scrolling.
    // The dialog threads its windowTitle («Карточка: <тип>») in; closing the
    // header runs the same view-model cancel as «Отмена» (guarded reject),
    // there is no second close path on this island.
    property string sheetTitle: ""

    // NRI-0014 task 4.3 (CR5): the stack depth. The stack owner (the wiring
    // that opened a child sheet over this one) threads the already-computed
    // dim alpha in; the island never sees layer counts, it only paints the
    // color.scrim overlay at this opacity on top. A top sheet stays at 0 and
    // the layer is not even painted — the wireframe pixel contract holds.
    property real sheetScrimAlpha: 0.0

    color: surfaceColor
    // Natural content size (island_size.py mirrors it onto the window), so the
    // dialog opens big enough to show the active group and the action row
    // instead of pushing them under the scroll. The sizes the port pinned
    // (760/550 with an image, 550 without; the 750 the audit saw was raised
    // onto the ui-layout-grid step by NRI-0018 Д6) stay as the floors; the
    // content is measured plus the scroll bar's track, which the scene never
    // owns, plus the header strip (task 4.2: the wireframe recomputed with
    // the header).
    //
    // add-dnd-game-face task 7.1: the content moved from one long scroll onto
    // grouping tabs, so the natural body size is the WIDEST/TALLEST page rather
    // than the one column that used to hold everything. A ScrollView measures
    // nothing from its content (its implicit size is not the content's), so
    // every page reports its content column's natural size through
    // reportBodySize; the sheet size then follows the max across pages — the
    // window is big enough for every tab, not just the opened one.
    readonly property real scrollbarReserve: 16
    property var bodySizes: ({})
    property real naturalBodyWidth: 0
    property real naturalBodyHeight: 0

    function reportBodySize(key, width, height) {
        var sizes = Object.assign({}, root.bodySizes)
        sizes[key] = [width, height]
        root.bodySizes = sizes
        let widest = 0
        let tallest = 0
        for (const page in sizes) {
            widest = Math.max(widest, sizes[page][0])
            tallest = Math.max(tallest, sizes[page][1])
        }
        root.naturalBodyWidth = widest
        root.naturalBodyHeight = tallest
    }

    readonly property real stripShare: groupTabs.visible
        ? groupTabs.implicitHeight + Tokens.px(root.islandTokens, "space.sm", 8)
        : 0
    implicitWidth: Math.max(
        entityCardVm.hasImage ? 760 : 550,
        naturalBodyWidth + scrollbarReserve)
    implicitHeight: Math.max(
        550,
        stripShare
        + naturalBodyHeight
        + actionsRow.implicitHeight
        + Tokens.px(root.islandTokens, "space.md", 16)
        + scrollbarReserve) + cardSheetHeader.implicitHeight

    // add-dnd-game-face task 7.1 (design Д10, spec entity-card-tabs): the
    // fields are laid out over grouping tabs — «Обзор» carries the picture,
    // the short fields, the age and the music row, «Тексты» the mention pair
    // and the extra text fields, «Связи» the whole relations strip as it was
    // (only for types that have sections — the rating card shows the pair).
    // The module placeholder pages (7.2) are the strip tail; the module
    // widget the dialog hosts is overlaid on the body slot.

    ThemeSheetHeader {
        id: cardSheetHeader
        objectName: "entitySheetHeader"
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        title: root.sheetTitle
        onCloseRequested: entityCardVm.requestCancel()

        // NRI-0018 task 3.3 (spec qml-shell «Шапка карточки … несёт полную
        // генерацию», entity-generation «Кнопка стоит у заголовка»): the
        // whole-entity wave rides the header's action slot, right after the
        // localized «Карточка: <тип>» — the objectName and the proxy contract
        // are untouched (e2e/wiring keep addressing them), only the parent
        // moved. The fieldLabel stays the card's own registry type (C1): a
        // character card reads «Сгенерировать: Персонаж», never «Событие».
        ThemeAiButton {
            objectName: "entityGenerateButton"
            proxy: entityCardVm.entityAiProxy
            fieldLabel: entityCardVm.entityLabel
            Accessible.name: "Сгенерировать: " + fieldLabel
        }
    }

    ColumnLayout {
        anchors.top: cardSheetHeader.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 0
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        // The grouping strip (design reference 2026-10-10): under the header,
        // never scrolled, caption-only tabs in equal shares — the icon stays
        // the relations strip's own identity. A single tab hides the strip
        // (the kernel strip is always ≥ 2, so in practice it is always up;
        // the rule is the design's).
        ThemeTabBar {
            id: groupTabs
            objectName: "entityGroupTabs"
            Layout.fillWidth: true
            Layout.leftMargin: Tokens.px(root.islandTokens, "space.md", 16)
            Layout.rightMargin: Tokens.px(root.islandTokens, "space.md", 16)
            Layout.topMargin: Tokens.px(root.islandTokens, "space.sm", 8)
            visible: entityCardVm.groups.length > 1
            currentIndex: entityCardVm.activeGroup
            onCurrentIndexChanged: if (currentIndex !== entityCardVm.activeGroup)
                entityCardVm.selectGroup(currentIndex)
            Repeater {
                model: entityCardVm.groups
                ThemeTabButton {
                    objectName: "entityGroupTab_" + modelData.key
                    text: modelData.title
                }
            }
        }
        // A tab tap writes currentIndex imperatively (breaking the binding),
        // so the reveal path (the VM opening the offended tab) re-seats the
        // strip through this channel — one value, two writers, no echo (the
        // guarded slot ignores an index the state already holds).
        Connections {
            target: entityCardVm
            function onActiveGroupChanged() {
                groupTabs.currentIndex = entityCardVm.activeGroup
            }
        }

        Item {
            id: bodyStack
            objectName: "entityGroupBody"
            Layout.fillWidth: true
            Layout.fillHeight: true

            // Pages bind on the active KEY (not a bare index): the kernel
            // pages are static children and the module tail comes and goes
            // with the external sources — a page that keyed itself to a
            // position would misalign the moment a module tab appears.
            readonly property string activeKey: entityCardVm.activeGroupKey

            // The body slot the module-tab overlay is placed over (task 7.2):
            // published in root coordinates on every geometry move; the card
            // facade maps it to window pixels.
            function publishBodyRect() {
                const point = mapToItem(root, 0, 0)
                entityCardVm.reportBodyRect(point.x, point.y, width, height)
            }
            Component.onCompleted: publishBodyRect()
            onXChanged: publishBodyRect()
            onYChanged: publishBodyRect()
            onWidthChanged: publishBodyRect()
            onHeightChanged: publishBodyRect()

            ScrollView {
                id: overviewScroll
                objectName: "entityCardScroll"
                anchors.fill: parent
                visible: bodyStack.activeKey === "overview"
                contentWidth: availableWidth

                ColumnLayout {
                    id: overviewCol
                    width: overviewScroll.availableWidth
                    spacing: Tokens.px(root.islandTokens, "space.sm", 8)

                    onImplicitWidthChanged: root.reportBodySize(
                        "overview", implicitWidth, implicitHeight)
                    onImplicitHeightChanged: root.reportBodySize(
                        "overview", implicitWidth, implicitHeight)
                    Component.onCompleted: root.reportBodySize(
                        "overview", implicitWidth, implicitHeight)

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.margins: Tokens.px(root.islandTokens, "space.md", 16)
                        spacing: Tokens.px(root.islandTokens, "space.md", 16)

                        ColumnLayout {
                            objectName: "entityImageColumn"
                            visible: entityCardVm.hasImage
                            Layout.alignment: Qt.AlignTop

                            CardPanel {
                                id: imageCard
                                objectName: "entityImageCard"
                                Layout.preferredWidth: 280
                                Layout.preferredHeight: 280

                                Image {
                                    objectName: "entityImagePreview"
                                    anchors.fill: parent
                                    anchors.margins: 1
                                    source: entityCardVm.imageSource
                                    fillMode: Image.PreserveAspectFit
                                    visible: entityCardVm.imageAvailable
                                    cache: false
                                    // PR-025: the card's picture joins the detail-panel
                                    // and preview slots as the named «open the image»
                                    // Button — the usage-site name is the entity's own
                                    // name (the card edits it live), «Изображение» when
                                    // unnamed, the fixed vocabulary description, and the
                                    // Press rides the VM's open request (a custom Item
                                    // presses only through onPressAction). The empty
                                    // slot stays unaddressable: the visible binding
                                    // hides the whole node (no broken press), and the
                                    // MouseArea below keeps driving the mouse path.
                                    Accessible.role: Accessible.Button
                                    Accessible.name: entityCardVm.name !== ""
                                        ? entityCardVm.name : "Изображение"
                                    Accessible.description: "Открыть изображение"
                                    Accessible.onPressAction: entityCardVm.requestImageOpen()
                                }
                                // The empty picture slot: the Lucide «image» glyph
                                // above the hint (user request 2026-09-30 — the mute
                                // text-only placeholder gets its icon affordance).
                                Column {
                                    anchors.centerIn: parent
                                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)
                                    visible: !entityCardVm.imageAvailable
                                    ThemeIcon {
                                        objectName: "entityImagePlaceholderIcon"
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        name: "image"
                                        size: 32
                                        tint: Tokens.token(root.islandTokens, "color.fg.muted", "gray")
                                    }
                                    HintText {
                                        objectName: "entityImagePlaceholder"
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: "Нет изображения"
                                    }
                                }
                                MouseArea {
                                    objectName: "entityImageOpenArea"
                                    anchors.fill: parent
                                    enabled: entityCardVm.imageAvailable
                                    onClicked: entityCardVm.requestImageOpen()
                                }
                            }

                            RowLayout {
                                ThemeButton {
                                    objectName: "entityImagePickButton"
                                    text: "Выбрать файл"
                                    // Lucide icon pass 2026-09-30: the file-picker
                                    // affordance rides in front of the caption.
                                    iconName: "folder-open"
                                    onClicked: entityCardVm.requestImagePick()
                                }
                                ThemeButton {
                                    objectName: "entityImageClearButton"
                                    text: "Убрать"
                                    iconName: "eraser"
                                    enabled: entityCardVm.imageAvailable
                                    onClicked: entityCardVm.requestImageClear()
                                }
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignTop
                            spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                            GridLayout {
                                columns: 3
                                Layout.fillWidth: true
                                columnSpacing: Tokens.px(root.islandTokens, "space.sm", 8)
                                rowSpacing: Tokens.px(root.islandTokens, "space.xs", 4)

                                TitleText {
                                    objectName: "entityNameLabel"
                                    text: "Название: *"
                                    // The reveal mark (task 7.1): the field a
                                    // refused save pointed at prints in the
                                    // accent until the next accepted attempt.
                                    color: entityCardVm.invalidatedField === "name"
                                        ? root.accentColor : fgColor
                                }
                                ThemeField {
                                    objectName: "entityNameField"
                                    Layout.fillWidth: true
                                    text: entityCardVm.name
                                    readOnly: entityCardVm.nameAiProxy.generating
                                    // nri-0012 task 2.4 (usage-site name, design map):
                                    // the typed value lives in the tree's value slot —
                                    // the name slot carries the field's purpose.
                                    Accessible.name: "Название"
                                    // PR-016: AX SetValue writes the text property
                                    // without a user gesture, so the model follows
                                    // every text change — the identity guard keeps
                                    // the vm→text binding echo from writing back.
                                    onTextChanged: if (text !== entityCardVm.name)
                                        entityCardVm.name = text
                                }
                                // NRI-0018 (spec qml-shell «Строка названия разгружена»):
                                // only the name field's own ✨ stays in this cell — the
                                // whole-entity wave moved into the header's action slot.
                                ThemeAiButton {
                                    objectName: "entityNameAiButton"
                                    proxy: entityCardVm.nameAiProxy
                                    entityType: entityCardVm.entityType
                                    fieldName: "name"
                                    fieldLabel: "Название"
                                    Accessible.name: "Сгенерировать: " + fieldLabel
                                }

                                TitleText { text: "Рейтинг (1-20):" }
                                SpinBox {
                                    id: ratingSpin
                                    objectName: "entityRatingSpin"
                                    Layout.fillWidth: true
                                    from: 1
                                    to: 20
                                    value: entityCardVm.rating
                                    editable: true
                                    Accessible.name: "Рейтинг"
                                    // PR-016: AX SetValue drives the value property
                                    // without a user gesture; the model follows every
                                    // change, the guard blocks the binding echo.
                                    onValueChanged: if (value !== entityCardVm.rating)
                                        entityCardVm.setRating(value)
                                    contentItem: TextInput {
                                        text: ratingSpin.textFromValue(ratingSpin.value, ratingSpin.locale)
                                        color: root.foregroundColor
                                        selectionColor: root.accentColor
                                        horizontalAlignment: Qt.AlignHCenter
                                        verticalAlignment: Qt.AlignVCenter
                                        readOnly: !ratingSpin.editable
                                        validator: ratingSpin.validator
                                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                                    }
                                    background: Rectangle {
                                        color: root.canvasColor
                                        border.width: 1
                                        border.color: ratingSpin.activeFocus
                                            ? root.accentColor : root.borderColor
                                        radius: Tokens.px(root.islandTokens, "radius.sm", 6)
                                    }
                                }
                                Item { implicitWidth: 24 }

                                TitleText { text: "Дата начала:" }
                                ThemeDateField {
                                    id: startDate
                                    objectName: "entityStartDateField"
                                    Layout.fillWidth: true
                                    isoDate: entityCardVm.startIso
                                    display: entityCardVm.startDisplay
                                    // nri-0012 task 2.4 (usage-site name, design map):
                                    // the tap opens the calendar popup; the name slot
                                    // carries the field's purpose (D5 description not
                                    // needed — the name spells the action's target).
                                    // nri-0017 1.1: role and press live inside the
                                    // component now (FI-1); the VM's worst-form
                                    // caption is the field's width floor (M2).
                                    Accessible.name: "Дата начала"
                                    worstCaseText: entityCardVm.worstCaseDisplay
                                    onClicked: {
                                        const point = startDate.mapToItem(root, 0, 0)
                                        entityCardVm.requestDatePopup(
                                            "start", point.x, point.y,
                                            startDate.width, startDate.height)
                                    }
                                }
                                Item { implicitWidth: 24 }

                                TitleText { text: "Дата конца:" }
                                RowLayout {
                                    Layout.fillWidth: true
                                    ThemeDateField {
                                        id: endDate
                                        objectName: "entityEndDateField"
                                        Layout.fillWidth: true
                                        visible: !entityCardVm.noEnd
                                        isoDate: entityCardVm.endIso
                                        display: entityCardVm.endDisplay
                                        Accessible.name: "Дата конца"
                                        worstCaseText: entityCardVm.worstCaseDisplay
                                        onClicked: {
                                            const point = endDate.mapToItem(root, 0, 0)
                                            entityCardVm.requestDatePopup(
                                                "end", point.x, point.y,
                                                endDate.width, endDate.height)
                                        }
                                    }
                                    ThemeCheckBox {
                                        objectName: "entityNoEndCheck"
                                        text: "Бессрочно"
                                        checked: entityCardVm.noEnd
                                        // D1 (live audit 2026-09-27): the accessibility
                                        // activation of a stock CheckBox announces the
                                        // CLICK, not the toggled signal (Qt 6.10 probe)
                                        // — on the old onToggled wiring an AT press
                                        // moved the tick but silently never reached the
                                        // VM. The launcher's working convention rides:
                                        // the tick is the VM's state (binding), every
                                        // activation is a request read from the source
                                        // of truth (never from the control's own half-
                                        // flipped `checked`).
                                        onClicked: entityCardVm.setNoEnd(!entityCardVm.noEnd)
                                    }
                                }
                                Item { implicitWidth: 24 }

                                // NRI-0021 task 4.3 (spec «Read-only отображение
                                // производных величин»): the age line under the date
                                // fields — plain read-only text, never an input and
                                // never part of the save result. The one age rule and
                                // the wording live in the VM (ageText); an invisible
                                // row leaves the grid, so location/organization cards
                                // show no age row at all (spec «Локация без возраста»).
                                Text {
                                    objectName: "entityAgeText"
                                    visible: text !== ""
                                    Layout.columnSpan: 3
                                    Layout.fillWidth: true
                                    text: entityCardVm.ageText
                                    color: root.foregroundColor
                                    font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                                    elide: Text.ElideRight
                                }

                                TitleText { text: "Музыка:" }
                                RowLayout {
                                    Layout.fillWidth: true
                                    ThemeField {
                                        objectName: "entityMusicField"
                                        Layout.fillWidth: true
                                        visible: entityCardVm.musicEditing || !entityCardVm.musicUrl
                                        text: entityCardVm.musicUrl
                                        placeholderText: "Ссылка на музыку"
                                        // nri-0012 task 2.4 (design map «Ссылка на
                                        // музыку»): the placeholder is not a name.
                                        Accessible.name: "Ссылка на музыку"
                                        // PR-016: same guarded-change channel as the
                                        // name field — AX SetValue reaches the model.
                                        onTextChanged: if (text !== entityCardVm.musicUrl)
                                            entityCardVm.setMusicUrl(text)
                                    }
                                    ThemeButton {
                                        objectName: "entityMusicOpenButton"
                                        visible: !entityCardVm.musicEditing && !!entityCardVm.musicUrl
                                        text: entityCardVm.musicUrl
                                        // The text is the URL (data, not a label), so
                                        // the usage-site name spells the action.
                                        Accessible.name: "Открыть ссылку на музыку"
                                        onClicked: entityCardVm.requestMusicOpen()
                                    }
                                }
                                ThemeIconButton {
                                    objectName: "entityMusicEditButton"
                                    iconName: "pencil"
                                    // NRI-0017 task 4.2 (FI-4=CR2): glyph text is no
                                    // caption to a reader, so this icon button is an
                                    // icon button — named by the action at the
                                    // usage-site (the 4.1 guard's glyph allowance).
                                    Accessible.name: "Изменить ссылку на музыку"
                                    onClicked: entityCardVm.toggleMusicEdit()
                                }
                            }
                        }
                    }
                }
            }

            ScrollView {
                id: textsScroll
                objectName: "entityTextsScroll"
                anchors.fill: parent
                visible: bodyStack.activeKey === "texts"
                contentWidth: availableWidth

                ColumnLayout {
                    id: textsCol
                    width: textsScroll.availableWidth
                    spacing: Tokens.px(root.islandTokens, "space.xs", 4)

                    onImplicitWidthChanged: root.reportBodySize(
                        "texts", implicitWidth, implicitHeight)
                    onImplicitHeightChanged: root.reportBodySize(
                        "texts", implicitWidth, implicitHeight)
                    Component.onCompleted: root.reportBodySize(
                        "texts", implicitWidth, implicitHeight)

                    GridLayout {
                        columns: 3
                        Layout.fillWidth: true
                        Layout.leftMargin: Tokens.px(root.islandTokens, "space.md", 16)
                        Layout.rightMargin: Tokens.px(root.islandTokens, "space.md", 16)
                        columnSpacing: Tokens.px(root.islandTokens, "space.sm", 8)
                        rowSpacing: Tokens.px(root.islandTokens, "space.xs", 4)

                        TitleText {
                            objectName: "entityCharacteristicsLabel"
                            text: "Характеристики: *"
                            // The reveal mark (task 7.1) rides the same channel
                            // as the name caption; the card's own gate is the
                            // name, so in practice this one waits for a future
                            // rule that would point here.
                            color: entityCardVm.invalidatedField === "characteristics"
                                ? root.accentColor : fgColor
                        }
                        MentionField {
                            objectName: "entityCharacteristicsField"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 72
                            host: entityCardVm.characteristicsHost
                            enabled: !entityCardVm.characteristicsAiProxy.generating
                            // nri-0012 task 2.4: the component brings the
                            // EditableText role (1.3); the island names it.
                            Accessible.name: "Характеристики"
                        }
                        ThemeAiButton {
                            objectName: "entityCharacteristicsAiButton"
                            proxy: entityCardVm.characteristicsAiProxy
                            // The «✨» glyph alone is mute in the tree; the
                            // name follows the field label (task 2.4). The
                            // fieldLabel property itself stays unset — it
                            // feeds the prompt, not the tree (behavior pin).
                            Accessible.name: "Сгенерировать: Характеристики"
                        }

                        TitleText { text: "Предыстория:" }
                        MentionField {
                            objectName: "entityBackstoryField"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 72
                            host: entityCardVm.backstoryHost
                            enabled: !entityCardVm.backstoryAiProxy.generating
                            Accessible.name: "Предыстория"
                        }
                        ThemeAiButton {
                            objectName: "entityBackstoryAiButton"
                            proxy: entityCardVm.backstoryAiProxy
                            Accessible.name: "Сгенерировать: Предыстория"
                        }
                    }

                    Repeater {
                        model: entityCardVm.extraFields
                        RowLayout {
                            objectName: "entityExtraRow_" + modelData.name
                            Layout.fillWidth: true
                            Layout.leftMargin: Tokens.px(root.islandTokens, "space.md", 16)
                            Layout.rightMargin: Tokens.px(root.islandTokens, "space.md", 16)
                            TitleText {
                                Layout.preferredWidth: 130
                                text: modelData.label + ":"
                            }
                            MentionField {
                                objectName: "entityExtraField_" + modelData.name
                                Layout.fillWidth: true
                                Layout.preferredHeight: 64
                                host: modelData.mentionHost
                                enabled: !modelData.aiProxy.generating
                                // nri-0012 task 2.4: extra fields are named by
                                // their model label (the same binding the
                                // TitleText paints).
                                Accessible.name: modelData.label
                            }
                            ThemeAiButton {
                                objectName: "entityExtraAiButton_" + modelData.name
                                proxy: modelData.aiProxy
                                Accessible.name: "Сгенерировать: " + modelData.label
                            }
                        }
                    }
                }
            }

            ColumnLayout {
                id: relationsCol
                objectName: "entityPageRelations"
                anchors.fill: parent
                anchors.leftMargin: Tokens.px(root.islandTokens, "space.md", 16)
                anchors.rightMargin: Tokens.px(root.islandTokens, "space.md", 16)
                visible: bodyStack.activeKey === "relations"
                spacing: Tokens.px(root.islandTokens, "space.sm", 8)

                onImplicitWidthChanged: root.reportBodySize(
                    "relations", implicitWidth + anchors.leftMargin * 2, implicitHeight)
                onImplicitHeightChanged: root.reportBodySize(
                    "relations", implicitWidth + anchors.leftMargin * 2, implicitHeight)
                Component.onCompleted: root.reportBodySize(
                    "relations", implicitWidth + anchors.leftMargin * 2, implicitHeight)

                // The relations strip moved onto its tab whole (task 7.1):
                // the tabs, the glyph per section type, the sections and
                // their objectNames are untouched — only the seat moved.
                ThemeTabBar {
                    id: relatedTabs
                    objectName: "entityRelatedTabs"
                    Layout.fillWidth: true
                    Repeater {
                        model: entityCardVm.relatedSections
                        ThemeTabButton {
                            objectName: "entityRelatedTab_" + modelData.attr
                            text: modelData.label
                            // The section type's glyph from the one map
                            // (Lucide pass 2026-09-30); the sheet sizes to
                            // its content, so the captions stay whole with
                            // the glyph (measured offscreen this pass).
                            iconName: modelData.iconName
                        }
                    }
                }
                StackLayout {
                    currentIndex: relatedTabs.currentIndex
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Repeater {
                        model: entityCardVm.relatedSections
                        RelatedSection {
                            objectName: "entityRelatedSection_" + modelData.attr
                            objectPrefix: "entityRelated_" + modelData.attr
                            section: modelData.section
                        }
                    }
                }
            }

            // The module-tab placeholders (task 7.2): the kernel only reserves
            // the body slot — the module widget the dialog hosts is overlaid
            // on it. The kernel keys are filtered out; anything else the VM
            // strip carries is a module tab.
            Repeater {
                model: entityCardVm.groups.filter(function (group) {
                    return group.key !== "overview"
                        && group.key !== "texts"
                        && group.key !== "relations"
                })
                Item {
                    objectName: "entityGroupPage_" + modelData.key
                    anchors.fill: parent
                    visible: bodyStack.activeKey === modelData.key
                }
            }
        }

        RowLayout {
            id: actionsRow
            Layout.fillWidth: true
            Layout.leftMargin: Tokens.px(root.islandTokens, "space.md", 16)
            Layout.rightMargin: Tokens.px(root.islandTokens, "space.md", 16)
            Layout.bottomMargin: Tokens.px(root.islandTokens, "space.md", 16)

            ThemeButton {
                objectName: "entityOpenSheetButton"
                visible: entityCardVm.characterSheetAvailable
                text: "Открыть чар-лист"
                // Lucide icon pass 2026-09-30: the sheet glyph (the same
                // paper the character-sheet islands open into).
                iconName: "scroll-text"
                onClicked: entityCardVm.requestCharacterSheet()
            }
            Item { Layout.fillWidth: true }
            ThemeButton {
                id: saveButton
                objectName: "entitySaveButton"
                text: "Сохранить"
                // Lucide icon pass 2026-09-30: the save chip matches the
                // editor/fill save buttons of the same island family.
                iconName: "save"
                accentBackground: true
                enabled: entityCardVm.saveEnabled
                onClicked: entityCardVm.requestSave()
            }
            ThemeButton {
                objectName: "entityCancelButton"
                text: "Отмена"
                enabled: !entityCardVm.saving
                onClicked: entityCardVm.requestCancel()
            }
        }
    }

    // Declared last so the dim paints over the whole sheet (header included);
    // a bare Item accepts no mouse, so the scrim can never trap the sheet's
    // own input.
    Rectangle {
        objectName: "sheetScrim"
        anchors.fill: parent
        color: Tokens.token(root.islandTokens, "color.scrim", "black")
        opacity: root.sheetScrimAlpha
        visible: root.sheetScrimAlpha > 0
    }
}
