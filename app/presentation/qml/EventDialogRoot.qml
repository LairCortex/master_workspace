import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import nri.components
import "nri/components/tokens.js" as Tokens

Rectangle {
    id: root
    objectName: "eventDialogRoot"

    readonly property Item defaultButton: saveButton
    readonly property string typeSelectorMode: "qml"
    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)
    readonly property color surfaceColor:
        Tokens.token(islandTokens, "color.bg.surface", "white")
    readonly property color accentColor:
        Tokens.token(islandTokens, "color.accent", "black")

    // NRI-0014 task 4.2 (E1): the sheet's visible title line. The dialog
    // threads its windowTitle in (the windowTitleChanged feed in
    // event_dialog.py is the only writer); the header itself rides the
    // library ThemeSheetHeader and cancels through the very view-model
    // request the «Отмена» button uses — no second close path.
    property string sheetTitle: ""

    // NRI-0014 task 4.3 (CR5): the stack depth. The stack owner (the wiring
    // that opened a child sheet over this one) threads the already-computed
    // dim alpha in; the island never sees layer counts, it only paints the
    // color.scrim overlay at this opacity on top. A top sheet stays at 0 and
    // the layer is not even painted — the wireframe pixel contract holds.
    property real sheetScrimAlpha: 0.0

    // dd-card-redesign task 3.2 (design Д1, spec «Ядро рисует карточки одним
    // экраном»): the kernel is the single-screen 0.19.1 event form — one
    // group, no strip. The mechanism sleeps: the strip shows and the
    // relations leave their seat for the stitched bottom band exactly when
    // an external source adds a tab (task 3.3, spec «Связи пришиты внизу
    // окна с табами»).
    readonly property bool hasExternalTabs:
        eventDialogVm.groups.length > eventDialogVm.kernelCount

    // The open relation section survives the Loader transfer between the
    // two seats (see EntityCardRoot's mirror of the same name).
    property int relatedTabMirror: 0

    color: surfaceColor
    implicitWidth: 720
    // The 620 the port pinned stays the CONTENT share; the header row is the
    // wireframe's own strip on top (the wireframe recomputed with the header,
    // task 4.2 — the pixel grab contract keeps the surface token at the edge).
    //
    // dd-card-redesign task 3.4 (spec «Размер окна с табами следует самому
    // высокому содержимому»): the single screen keeps the pinned 720×620
    // exactly; with guest tabs the ask grows to the tallest page plus the
    // stitched band and the buttons, never below the pinned floor (the band
    // share cap of half the rest keeps the «not more than a third of the
    // window» ceiling true at the opened size). The dialog facade refits
    // through island_size when the tabs join.
    readonly property real relationsNatural: 230
    readonly property real columnSpacings:
        Tokens.px(root.islandTokens, "space.sm", 8) * 3
    readonly property real stripShare: hasExternalTabs
        ? groupTabs.implicitHeight + Tokens.px(root.islandTokens, "space.sm", 8)
        : 0
    readonly property real contentShare:
        stripShare + eventBody.implicitHeight + actionsRow.implicitHeight
        + root.columnSpacings
    readonly property real bandShare: hasExternalTabs
        ? Math.min(root.relationsNatural, contentShare / 2)
        : 0
    implicitHeight: hasExternalTabs
        ? eventSheetHeader.implicitHeight + Math.max(620, contentShare + bandShare)
        : 620 + eventSheetHeader.implicitHeight

    ThemeSheetHeader {
        id: eventSheetHeader
        objectName: "eventSheetHeader"
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        title: root.sheetTitle
        onCloseRequested: eventDialogVm.requestCancel()

        // NRI-0018 task 3.3 (spec entity-generation «Кнопка стоит у
        // заголовка»): the wave that generates the event as a whole rides the
        // header's action slot, right after the dialog title — the same
        // seating the card got, one phrasing for both sheets. The objectName
        // and the proxy contract are untouched (the label is QML-side only:
        // this button has no fieldName, the wave rides the proxy unchanged).
        ThemeAiButton {
            objectName: "eventEntityAiButton"
            proxy: eventDialogVm.entityAiProxy
            fieldLabel: "Событие"
            Accessible.name: "Сгенерировать: " + fieldLabel
        }
    }

    ColumnLayout {
        anchors.top: eventSheetHeader.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: Tokens.px(root.islandTokens, "space.md", 16)
        spacing: Tokens.px(root.islandTokens, "space.sm", 8)

        // The grouping strip (dd-card-redesign Д1): it only wakes when an
        // external source brought tabs — the kernel alone is the single
        // screen. Under the header, never scrolled, caption-only tabs in
        // equal shares.
        ThemeTabBar {
            id: groupTabs
            objectName: "eventGroupTabs"
            Layout.fillWidth: true
            visible: root.hasExternalTabs
            currentIndex: eventDialogVm.activeGroup
            onCurrentIndexChanged: if (currentIndex !== eventDialogVm.activeGroup)
                eventDialogVm.selectGroup(currentIndex)
            Repeater {
                model: eventDialogVm.groups
                ThemeTabButton {
                    objectName: "eventGroupTab_" + modelData.key
                    text: modelData.title
                }
            }
        }
        // A tab tap writes currentIndex imperatively (breaking the binding),
        // so the reveal path (the VM opening the offended tab) re-seats the
        // strip through this channel — one value, two writers, no echo (the
        // guarded slot ignores an index the state already holds).
        Connections {
            target: eventDialogVm
            function onActiveGroupChanged() {
                groupTabs.currentIndex = eventDialogVm.activeGroup
            }
        }

        // The single screen and the body slot at once: the kernel grid wears
        // it whenever the active key is the kernel's, a guest tab's widget
        // (hosted by the dialog's CardTabHost) overlays the very same rect
        // otherwise. Without guests this is the plain 0.19.1 column child.
        Item {
            id: eventBody
            objectName: "eventGroupBody"
            Layout.fillWidth: true
            Layout.fillHeight: root.hasExternalTabs
            implicitHeight: eventKernelPage.implicitHeight

            // The body slot the module-tab overlay is placed over:
            // published in root coordinates on every geometry move; the
            // dialog maps it to window pixels.
            function publishBodyRect() {
                const point = mapToItem(root, 0, 0)
                eventDialogVm.reportBodyRect(point.x, point.y, width, height)
            }
            Component.onCompleted: publishBodyRect()
            onXChanged: publishBodyRect()
            onYChanged: publishBodyRect()
            onWidthChanged: publishBodyRect()
            onHeightChanged: publishBodyRect()

            GridLayout {
                id: eventKernelPage
                objectName: "eventKernelPage"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                columns: 3
                columnSpacing: Tokens.px(root.islandTokens, "space.sm", 8)
                rowSpacing: Tokens.px(root.islandTokens, "space.xs", 4)
                // Single screen: the key is the kernel's whenever no guest
                // tab is up, so the page is the whole form, exactly 0.19.1.
                visible: eventDialogVm.activeGroupKey === "overview"

                TitleText {
                    objectName: "eventNameLabel"
                    text: "Название: *"
                    // The reveal mark (spec «Ошибка указывает дорогу»): the
                    // field a refused save pointed at prints in the accent
                    // until the next attempt.
                    color: eventDialogVm.invalidatedField === "name"
                        ? root.accentColor : fgColor
                }
                ThemeField {
                    objectName: "eventNameField"
                    Layout.fillWidth: true
                    text: eventDialogVm.name
                    placeholderText: "Название события *"
                    // nri-0012 task 3.5 (usage-site name, design map): the typed
                    // name rides the value slot; the caption is paint.
                    Accessible.name: "Название события"
                    // PR-016: AX SetValue writes the text property without a
                    // user gesture, so the model follows every text change —
                    // the identity guard keeps the vm→text binding echo quiet.
                    onTextChanged: if (text !== eventDialogVm.name)
                        eventDialogVm.name = text
                }
                // NRI-0018 (spec entity-generation «Кнопка стоит у заголовка»):
                // only the name field's own ✨ stays in this cell — the whole-event
                // wave moved into the header's action slot above.
                ThemeAiButton {
                    objectName: "eventNameAiButton"
                    proxy: eventDialogVm.nameAiProxy
                    entityType: "event"
                    fieldName: "name"
                    fieldLabel: "Название"
                    // nri-0012 task 3.5: the «✨» glyph is mute in the tree; the
                    // name follows the fieldLabel the proxy prompt already uses.
                    Accessible.name: "Сгенерировать: " + fieldLabel
                }

                TitleText { text: "Дата начала: *" }
                ThemeDateField {
                    id: startDate
                    objectName: "eventStartDateField"
                    Layout.fillWidth: true
                    isoDate: eventDialogVm.startIso
                    display: eventDialogVm.startDisplay
                    // nri-0012 task 3.5: the tap opens the calendar popup; the
                    // name slot carries the field's purpose (entity-card
                    // precedent). nri-0017 1.1: role and press moved inside the
                    // component (FI-1) — the name stays right here, and the VM's
                    // worst-form caption becomes the field's width floor (M2).
                    Accessible.name: "Дата начала"
                    worstCaseText: eventDialogVm.worstCaseDisplay
                    onClicked: {
                        const point = startDate.mapToItem(root, 0, 0)
                        eventDialogVm.requestDatePopup(
                            "start", point.x, point.y, startDate.width, startDate.height)
                    }
                }
                Item { implicitWidth: 24 }

                // NRI-0023 task 7.2 (spec «Списки часов и минут в карточке
                // события»): the optional wall-clock start, right beside the start
                // date. The bounds come from the active calendar through the VM,
                // the empty «—» head means без времени and is never saved as
                // 00:00, and the minute list is enabled only while an hour is
                // chosen. The native popups sit outside the accessibility island
                // (limit ③); the triggers carry the design-Д8 usage-site names.
                TitleText { text: "Час:" }
                ThemeComboBox {
                    objectName: "eventStartHourCombo"
                    Layout.fillWidth: true
                    model: eventDialogVm.hourOptions
                    currentIndex: eventDialogVm.selectedHourIndex
                    Accessible.name: "Час начала"
                    onActivated: eventDialogVm.selectHour(index)
                }
                Item { implicitWidth: 24 }

                TitleText { text: "Минута:" }
                ThemeComboBox {
                    objectName: "eventStartMinuteCombo"
                    Layout.fillWidth: true
                    enabled: eventDialogVm.minuteEnabled
                    model: eventDialogVm.minuteOptions
                    currentIndex: eventDialogVm.selectedMinuteIndex
                    Accessible.name: "Минута начала"
                    onActivated: eventDialogVm.selectMinute(index)
                }
                Item { implicitWidth: 24 }

                TitleText { text: "Дата конца:" }
                RowLayout {
                    Layout.fillWidth: true
                    ThemeDateField {
                        id: endDate
                        objectName: "eventEndDateField"
                        Layout.fillWidth: true
                        visible: !eventDialogVm.noEnd
                        isoDate: eventDialogVm.endIso
                        display: eventDialogVm.endDisplay
                        Accessible.name: "Дата конца"
                        worstCaseText: eventDialogVm.worstCaseDisplay
                        onClicked: {
                            const point = endDate.mapToItem(root, 0, 0)
                            eventDialogVm.requestDatePopup(
                                "end", point.x, point.y, endDate.width, endDate.height)
                        }
                    }
                    ThemeCheckBox {
                        objectName: "eventNoEndCheck"
                        text: "Бессрочно"
                        checked: eventDialogVm.noEnd
                        // Д15 (NRI-0023 task 13.1, live audit 2026-09-29 OBS-2):
                        // the accessibility activation of a stock CheckBox writes
                        // ``checked`` WITHOUT a user gesture, so an onToggled
                        // wiring moved the tick but silently never reached the VM.
                        // The card's working convention (EntityCardRoot D1) rides:
                        // the tick is the VM's state (binding), every activation
                        // is a request read from the source of truth — never from
                        // the control's own half-flipped ``checked``.
                        onClicked: eventDialogVm.setNoEnd(!eventDialogVm.noEnd)
                    }
                }
                Item { implicitWidth: 24 }

                // NRI-0021 task 4.4 (spec «Read-only отображение производных
                // величин»): the read-only «С начала: <формула>» line under the
                // date fields — plain text, never an input and never part of the
                // save result; the VM owns the formula (eventText).  Without a
                // game «now» the answer is empty and the row leaves the grid.
                Text {
                    objectName: "eventSinceText"
                    visible: text !== ""
                    Layout.columnSpan: 3
                    Layout.fillWidth: true
                    text: eventDialogVm.eventText
                    color: Tokens.token(root.islandTokens, "color.fg.primary", "black")
                    font.pixelSize: Tokens.px(root.islandTokens, "font.size.md", 13)
                    elide: Text.ElideRight
                }

                TitleText { text: "Тип:" }
                RowLayout {
                    Layout.fillWidth: true
                    ThemeComboBox {
                        id: typeCombo
                        objectName: "eventTypeCombo"
                        Layout.fillWidth: true
                        model: eventDialogVm.typeNames
                        currentIndex: eventDialogVm.selectedTypeIndex
                        // nri-0012 task 3.5: the combo shows type names (data) —
                        // the tree name is the purpose (design map).
                        Accessible.name: "Тип события"
                        onActivated: eventDialogVm.selectType(index)
                    }
                    ThemeSwatch {
                        objectName: "eventTypeSwatch"
                        visible: eventDialogVm.selectedColorIndex > 0
                        colorIndex: Math.max(1, eventDialogVm.selectedColorIndex)
                        // nri-0012 task 3.5: the dialog override of the group-1
                        // swatch default («Цвет палитры №N» stays in the palette).
                        accessibleName: "Цвет типа события"
                    }
                }
                Item { implicitWidth: 24 }

                // NRI-0023 task 7.1 (spec «Поле „Родительское событие" в карточке
                // события»): a dropdown of «—» plus the game's main events (the
                // VM excludes sub-events and the edited one). Changing it is
                // applied at save; «—» lifts the event to main. The native popup
                // is outside the island (limit ③), the trigger carries the
                // design-Д8 usage-site name.
                TitleText { text: "Родительское событие:" }
                ThemeComboBox {
                    objectName: "eventParentCombo"
                    Layout.fillWidth: true
                    model: eventDialogVm.parentNames
                    currentIndex: eventDialogVm.selectedParentIndex
                    Accessible.name: "Родительское событие"
                    onActivated: eventDialogVm.selectParent(index)
                }
                Item { implicitWidth: 24 }

                // dd-card-redesign task 4.2 (design Д2): the «after short
                // fields» anchor — the same generic block channel as the
                // entity card, painted before the event texts. With an empty
                // channel nothing changes (events have no module owner in
                // this change — the channel exists so no dialog special
                // case is ever needed).
                Repeater {
                    model: eventDialogVm.moduleBlocks.filter(
                        b => b.anchor === "after_short_fields")
                    delegate: ModuleBlockDelegate {
                        objectName: "eventModuleBlock_" + modelData.id
                        Layout.columnSpan: 3
                        Layout.fillWidth: true
                        block: modelData
                        vm: eventDialogVm
                    }
                }

                TitleText {
                    objectName: "eventCharacteristicsLabel"
                    text: "Характеристики: *"
                    // The reveal mark: «both texts empty» points here.
                    color: eventDialogVm.invalidatedField === "characteristics"
                        ? root.accentColor : fgColor
                }
                MentionField {
                    objectName: "eventCharacteristicsField"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 72
                    host: eventDialogVm.characteristicsMentionHost
                    // nri-0012 task 3.5: the component brings the EditableText
                    // role (1.3); the island names it (entity-card precedent).
                    Accessible.name: "Характеристики"
                }
                ThemeAiButton {
                    objectName: "eventCharacteristicsAiButton"
                    proxy: eventDialogVm.characteristicsAiProxy
                    entityType: "event"
                    fieldName: "characteristics"
                    fieldLabel: "Характеристики"
                    Accessible.name: "Сгенерировать: " + fieldLabel
                }

                TitleText { text: "Предыстория: *" }
                MentionField {
                    objectName: "eventBackstoryField"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 72
                    host: eventDialogVm.backstoryMentionHost
                    Accessible.name: "Предыстория"
                }
                ThemeAiButton {
                    objectName: "eventBackstoryAiButton"
                    proxy: eventDialogVm.backstoryAiProxy
                    entityType: "event"
                    fieldName: "backstory"
                    fieldLabel: "Предыстория"
                    Accessible.name: "Сгенерировать: " + fieldLabel
                }

                // dd-card-redesign task 4.2 (design Д2): the «after music»
                // anchor for the event form — the event has no music field,
                // so the tail of the short-field grid stands in its place
                // (the anchor names the card layout, not a field per type).
                Repeater {
                    model: eventDialogVm.moduleBlocks.filter(
                        b => b.anchor === "after_music")
                    delegate: ModuleBlockDelegate {
                        objectName: "eventModuleBlockTail_" + modelData.id
                        Layout.columnSpan: 3
                        Layout.fillWidth: true
                        block: modelData
                        vm: eventDialogVm
                    }
                }
            }

            // The guest-tab placeholders: the kernel only reserves the body
            // slot — the module widget the dialog hosts is overlaid on it.
            // The external tail comes from the VM (everything past the
            // kernel head), so no usage site hardcodes the module keys.
            Repeater {
                model: eventDialogVm.moduleGroups
                Item {
                    objectName: "eventGroupPage_" + modelData.key
                    anchors.fill: parent
                    visible: eventDialogVm.activeGroupKey === modelData.key
                }
            }
        }

        // The stitched relations band (task 3.3, design Д4, spec «Связи
        // пришиты внизу окна с табами»): with guest tabs the strip leaves the
        // form for a bottom band that never disappears on a tab switch. Its
        // rows scroll inside the band (the RelatedSection list is the band's
        // own scroll), the band is capped at a third of the window, and the
        // action row sits below it.
        Loader {
            id: relationsBand
            objectName: "eventRelationsBand"
            active: root.hasExternalTabs
            // A sleeping seat is an invisible one: the inactive band kept
            // its preferred 230 px in the column while only the 0.19.1
            // form, the relations strip and the buttons fit inside the
            // pinned 620 — the strip collapsed to nothing and the action
            // row fell below the window edge (live audit 2026-10-13,
            // blocker 1: «Сохранить»/«Отмена» existed only for Enter).
            visible: active
            sourceComponent: relationsBlock
            Layout.fillWidth: true
            Layout.preferredHeight: root.relationsNatural
            Layout.maximumHeight: root.height / 3
            // A Loader sizes itself to the item, never the item to the
            // Loader — the seats fill it explicitly.
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

        // The 0.19.1 seat: the strip fills the rest of the column between the
        // form and the buttons (Loader of the same Component as the band, the
        // two seats are mutually exclusive — design Д4).
        Loader {
            id: relationsSingle
            objectName: "eventRelationsSingle"
            active: !root.hasExternalTabs
            // The same rule as the band above, the other way round: while
            // guest tabs are up this seat is empty, and as a visible
            // fillHeight item it would split the body's space with the
            // kernel page instead of leaving it all to the form.
            visible: active
            sourceComponent: relationsBlock
            Layout.fillWidth: true
            Layout.fillHeight: true
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
            Item { Layout.fillWidth: true }
            ThemeButton {
                id: saveButton
                objectName: "eventSaveButton"
                text: "Сохранить"
                // Lucide icon pass 2026-09-30: the save chip shared with the
                // entity-card and sheet save buttons.
                iconName: "save"
                accentBackground: true
                enabled: eventDialogVm.valid
                onClicked: eventDialogVm.requestSave()
            }
            ThemeButton {
                objectName: "eventCancelButton"
                text: "Отмена"
                enabled: !eventDialogVm.saving
                onClicked: eventDialogVm.requestCancel()
            }
        }
    }

    // The relations strip — ONE Component (design Д4), ridden by either seat
    // through its Loader: the four registry tabs with their glyphs and the
    // four sections, the objectNames the whole test surface addresses.
    Component {
        id: relationsBlock
        ColumnLayout {
            spacing: Tokens.px(root.islandTokens, "space.sm", 8)

            ThemeTabBar {
                id: tabs
                objectName: "eventRelatedTabs"
                Layout.fillWidth: true
                currentIndex: root.relatedTabMirror
                onCurrentIndexChanged: if (currentIndex !== root.relatedTabMirror)
                    root.relatedTabMirror = currentIndex
                // The registry-order glyphs of the four relation tabs (the same
                // captions order), from the one type→icon map (Lucide pass
                // 2026-09-30). The sheet sizes itself to its content, so the
                // bar never squeezes these captions below their iconed natural.
                ThemeTabButton { text: "Организации"; iconName: eventDialogVm.relatedTabIcons[0] }
                ThemeTabButton { text: "Персонажи"; iconName: eventDialogVm.relatedTabIcons[1] }
                ThemeTabButton { text: "Предметы"; iconName: eventDialogVm.relatedTabIcons[2] }
                ThemeTabButton { text: "Локации"; iconName: eventDialogVm.relatedTabIcons[3] }
            }

            StackLayout {
                currentIndex: tabs.currentIndex
                Layout.fillWidth: true
                Layout.fillHeight: true

                RelatedSection {
                    objectName: "organizationsRelatedSection"
                    objectPrefix: "organizationsRelated"
                    section: eventDialogVm.organizationsSection
                }
                RelatedSection {
                    objectName: "charactersRelatedSection"
                    objectPrefix: "charactersRelated"
                    section: eventDialogVm.charactersSection
                }
                RelatedSection {
                    objectName: "itemsRelatedSection"
                    objectPrefix: "itemsRelated"
                    section: eventDialogVm.itemsSection
                }
                RelatedSection {
                    objectName: "locationsRelatedSection"
                    objectPrefix: "locationsRelated"
                    section: eventDialogVm.locationsSection
                }
            }
        }
    }

    // Declared last so the dim paints over the whole sheet; a bare Item
    // accepts no mouse, so the scrim can never trap the sheet's own input.
    Rectangle {
        objectName: "sheetScrim"
        anchors.fill: parent
        color: Tokens.token(root.islandTokens, "color.scrim", "black")
        opacity: root.sheetScrimAlpha
        visible: root.sheetScrimAlpha > 0
    }
}
