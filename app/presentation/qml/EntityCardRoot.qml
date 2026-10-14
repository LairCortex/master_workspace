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

    // dd-card-redesign task 3.1 (design Д1, spec «Ядро рисует карточки одним
    // экраном»): the kernel is the single-screen 0.19.1 card — one group, no
    // strip. The tab mechanism below sleeps: the strip shows and the
    // relations leave the scroll for the stitched bottom band exactly when an
    // external source adds a tab (spec «Связи пришиты внизу окна с табами»).
    readonly property bool hasExternalTabs:
        entityCardVm.groups.length > entityCardVm.kernelCount

    // Which of the relation sections the reader left open. The block rides
    // two seats (scroll end / stitched band) through mutual-exclusive
    // Loaders (design Д4), and a Loader rebuilds its item — the mirror keeps
    // the chosen section across the transfer (the rows themselves are the
    // VM's state, the band's row scroll is the ListView's own).
    property int relatedTabMirror: 0

    color: surfaceColor
    // Natural content size (island_size.py mirrors it onto the window), so the
    // dialog opens big enough to show the whole screen and the action row
    // instead of pushing them under the scroll. The sizes the port pinned
    // (760/550 with an image, 550 without; the 750 the audit saw was raised
    // onto the ui-layout-grid step by NRI-0018 Д6) stay as the floors; the
    // content is measured plus the scroll bar's track, which the scene never
    // owns, plus the header strip (task 4.2: the wireframe recomputed with
    // the header).
    //
    // dd-card-redesign task 3.4 (spec «Размер окна с табами следует самому
    // высокому содержимому»): with guest tabs the ask grows by the strip and
    // the stitched band share; the band share is capped at half of the rest
    // so the resulting height always honours the «not more than a third of
    // the window» ceiling (band = H/3 exactly at the cap).
    readonly property real scrollbarReserve: 16
    readonly property real relationsNatural: 230
    readonly property real stripShare: hasExternalTabs
        ? groupTabs.implicitHeight + Tokens.px(root.islandTokens, "space.sm", 8)
        : 0
    readonly property real bandShare: hasExternalTabs
            && entityCardVm.relatedSections.length > 0
        ? Math.min(relationsNatural,
                   (stripShare + cardColumn.implicitHeight
                    + actionsRow.implicitHeight
                    + Tokens.px(root.islandTokens, "space.md", 16)) / 2)
        : 0
    implicitWidth: Math.max(
        entityCardVm.hasImage ? 760 : 550,
        cardColumn.implicitWidth + scrollbarReserve)
    implicitHeight: Math.max(
        550,
        stripShare
        + cardColumn.implicitHeight
        + bandShare
        + actionsRow.implicitHeight
        + Tokens.px(root.islandTokens, "space.md", 16)
        + scrollbarReserve) + cardSheetHeader.implicitHeight

    // The single screen (the 0.19.1 column): the short fields with the
    // mention pair in ONE grid, the type's extra mention rows, and the
    // relations strip at the scroll end. The module placeholder pages are
    // the strip tail (their widgets are overlaid on the body slot by the
    // card facade's CardTabHost).

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

        // The grouping strip (dd-card-redesign Д1): it only wakes when an
        // external source brought tabs — the kernel alone is the single
        // screen. Under the header, never scrolled, caption-only tabs in
        // equal shares.
        ThemeTabBar {
            id: groupTabs
            objectName: "entityGroupTabs"
            Layout.fillWidth: true
            Layout.leftMargin: Tokens.px(root.islandTokens, "space.md", 16)
            Layout.rightMargin: Tokens.px(root.islandTokens, "space.md", 16)
            Layout.topMargin: Tokens.px(root.islandTokens, "space.sm", 8)
            visible: root.hasExternalTabs
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
            // page is static and the module tail comes and goes with the
            // external sources — a page that keyed itself to a position
            // would misalign the moment a module tab appears.
            readonly property string activeKey: entityCardVm.activeGroupKey

            // The body slot the module-tab overlay is placed over:
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

            // The single screen. The active key is «overview» whenever no
            // module tab is up, so with the strip asleep this scroll is the
            // whole card, exactly the 0.19.1 posture.
            ScrollView {
                id: overviewScroll
                objectName: "entityCardScroll"
                anchors.fill: parent
                visible: bodyStack.activeKey === "overview"
                contentWidth: availableWidth

                ColumnLayout {
                    id: cardColumn
                    width: overviewScroll.availableWidth
                    spacing: Tokens.px(root.islandTokens, "space.sm", 8)

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
                                    // The reveal mark (dd-card-redesign, spec
                                    // «Ошибка указывает дорогу»): the field a
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

                                // dd-card-redesign task 4.2 (design Д2, spec
                                // «Позиции модульных блоков зафиксированы»): the
                                // «after short fields» anchor — between the last
                                // short kernel row and the derived age line. With
                                // an empty channel the Repeater paints nothing and
                                // the kernel renders bit-for-bit as before; the
                                // D&D character's lists, level and ability table
                                // land here for a module-attached card.
                                Repeater {
                                    model: entityCardVm.moduleBlocks.filter(
                                        b => b.anchor === "after_short_fields")
                                    delegate: ModuleBlockDelegate {
                                        objectName: "entityModuleBlock_" + modelData.id
                                        Layout.columnSpan: 3
                                        Layout.fillWidth: true
                                        block: modelData
                                        vm: entityCardVm
                                    }
                                }

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

                                // dd-card-redesign task 4.2 (design Д2, spec
                                // «Модуль заменяет текстовые поля ядра»): a module
                                // owning a kernel text field hides the whole row —
                                // caption, editor and the field's AI button. The
                                // channel is generic: an empty hiddenFields (every
                                // non-D&D card, every kernel game) leaves the rows
                                // visible exactly as before.
                                TitleText {
                                    objectName: "entityCharacteristicsLabel"
                                    visible: !entityCardVm.hiddenFields.includes("characteristics")
                                    text: "Характеристики: *"
                                    // The reveal mark rides the same channel as
                                    // the name caption; the card's own gate is the
                                    // name, so in practice this one waits for a
                                    // future rule that would point here.
                                    color: entityCardVm.invalidatedField === "characteristics"
                                        ? root.accentColor : fgColor
                                }
                                MentionField {
                                    objectName: "entityCharacteristicsField"
                                    visible: !entityCardVm.hiddenFields.includes("characteristics")
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
                                    visible: !entityCardVm.hiddenFields.includes("characteristics")
                                    proxy: entityCardVm.characteristicsAiProxy
                                    // The «✨» glyph alone is mute in the tree; the
                                    // name follows the field label (task 2.4). The
                                    // fieldLabel property itself stays unset — it
                                    // feeds the prompt, not the tree (behavior pin).
                                    Accessible.name: "Сгенерировать: Характеристики"
                                }

                                TitleText {
                                    text: "Предыстория:"
                                    visible: !entityCardVm.hiddenFields.includes("backstory")
                                }
                                MentionField {
                                    objectName: "entityBackstoryField"
                                    visible: !entityCardVm.hiddenFields.includes("backstory")
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 72
                                    host: entityCardVm.backstoryHost
                                    enabled: !entityCardVm.backstoryAiProxy.generating
                                    Accessible.name: "Предыстория"
                                }
                                ThemeAiButton {
                                    objectName: "entityBackstoryAiButton"
                                    visible: !entityCardVm.hiddenFields.includes("backstory")
                                    proxy: entityCardVm.backstoryAiProxy
                                    Accessible.name: "Сгенерировать: Предыстория"
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

                            Repeater {
                                model: entityCardVm.extraFields
                                RowLayout {
                                    objectName: "entityExtraRow_" + modelData.name
                                    Layout.fillWidth: true
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

                            // dd-card-redesign task 4.2 (design Д2): the
                            // «after music» anchor — the tail of the core
                            // content, after the optional extra mention rows
                            // (all of them hidden for a module-attached
                            // character). The D&D character's LSS-source door
                            // row and «Дозаполнить ИИ» land here; with an
                            // empty channel the scroll ends exactly as in
                            // 0.19.1.
                            Repeater {
                                model: entityCardVm.moduleBlocks.filter(
                                    b => b.anchor === "after_music")
                                delegate: ModuleBlockDelegate {
                                    objectName: "entityModuleBlockTail_" + modelData.id
                                    Layout.fillWidth: true
                                    block: modelData
                                    vm: entityCardVm
                                }
                            }
                        }
                    }

                    // The 0.19.1 seat of the relations strip: the LAST block
                    // of the scroll (design Д4, spec «В одноэкранном виде ядра
                    // связи SHALL оставаться в конце прокрутки»). Loader rather
                    // than a static child so the very same Component can ride
                    // the stitched band once guest tabs arrive — the Loaders are
                    // mutually exclusive, the item exists once at a time.
                    Loader {
                        id: relationsInScroll
                        objectName: "entityRelationsInScroll"
                        active: !root.hasExternalTabs
                            && entityCardVm.relatedSections.length > 0
                        // A seat only exists for the layout while it is the
                        // live one (the dd-card-redesign live audit of
                        // 2026-10-13): an inactive Loader stays a VISIBLE
                        // 0-size item, and its Layout.preferredHeight kept
                        // reserving 230 px of scroll even with no item —
                        // types without sections scrolled over a phantom
                        // gap. QQuickLayout skips invisible children.
                        visible: active
                        sourceComponent: relationsBlock
                        Layout.fillWidth: true
                        // A loaded Loader reports the block's implicit width
                        // as its width floor, which is the four-glyph tab
                        // row's natural (measured 794 offscreen) — wider
                        // than the card itself. Without the cap the layout
                        // honours that floor and the block hangs past the
                        // window; 0.19.1's direct-child seat had no such
                        // floor, so the cap restores the old geometry.
                        Layout.maximumWidth: overviewScroll.availableWidth
                            - Tokens.px(root.islandTokens, "space.md", 16) * 2
                        Layout.preferredHeight: root.relationsNatural
                        Layout.leftMargin: Tokens.px(root.islandTokens, "space.md", 16)
                        Layout.rightMargin: Tokens.px(root.islandTokens, "space.md", 16)
                        // A Loader sizes itself to the item, never the item to
                        // the Loader — the seats fill it explicitly (the layout
                        // decides the box, the block wears it).
                        function fitItem() {
                            if (item) {
                                item.width = width
                                item.height = height
                            }
                        }
                        onLoaded: fitItem()
                        onWidthChanged: fitItem()
                        onHeightChanged: fitItem()
                    }
                }
            }

            // The module-tab placeholders: the kernel only reserves the body
            // slot — the module widget the dialog hosts is overlaid on it.
            // The external tail comes from the VM (everything past the kernel
            // head), so no usage site hardcodes the module keys.
            Repeater {
                model: entityCardVm.moduleGroups
                Item {
                    objectName: "entityGroupPage_" + modelData.key
                    anchors.fill: parent
                    visible: bodyStack.activeKey === modelData.key
                }
            }
        }

        // The stitched relations band (dd-card-redesign task 3.3, design Д4,
        // spec «Связи пришиты внизу окна с табами»): with guest tabs the strip
        // leaves the scroll for a bottom band that never disappears on a tab
        // switch. Its rows scroll inside the band (the RelatedSection list is
        // the band's own scroll), the band itself is capped at a third of the
        // window, and the action row sits below it.
        Loader {
            id: relationsBand
            objectName: "entityRelationsBand"
            active: root.hasExternalTabs && entityCardVm.relatedSections.length > 0
            // The sleeping band must leave the column entirely: its
            // preferred 230 px sat in the layout while inactive, ate a
            // fifth of the card's scroll viewport and pushed the relations
            // end below the fold (live audit 2026-10-13, blocker 2).
            visible: active
            sourceComponent: relationsBlock
            Layout.fillWidth: true
            Layout.leftMargin: Tokens.px(root.islandTokens, "space.md", 16)
            Layout.rightMargin: Tokens.px(root.islandTokens, "space.md", 16)
            Layout.preferredHeight: root.relationsNatural
            Layout.maximumHeight: root.height / 3
            function fitItem() {
                if (item) {
                    item.width = width
                    item.height = height
                }
            }
            onLoaded: fitItem()
            onWidthChanged: fitItem()
            onHeightChanged: fitItem()
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

    // The relations strip — ONE Component (design Д4), ridden by either seat
    // through its Loader. The tabs, the glyph per section type, the sections
    // and their objectNames are the strip the kernel always drew.
    Component {
        id: relationsBlock
        ColumnLayout {
            spacing: Tokens.px(root.islandTokens, "space.sm", 8)

            ThemeTabBar {
                id: relatedTabs
                objectName: "entityRelatedTabs"
                Layout.fillWidth: true
                currentIndex: root.relatedTabMirror
                onCurrentIndexChanged: if (currentIndex !== root.relatedTabMirror)
                    root.relatedTabMirror = currentIndex
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
