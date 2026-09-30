// Delegate of one tree row (change simplify-event-timeline-flat-list,
// task 3.2, design D2/D5; NRI-0023 task 5.3, design Д6/Д8). One item per row
// of ``vm.rowModel``; the ListView recycles these by the equal-height-per-kind
// contract — a row without a description is the root's ``rowHeight`` of one
// caption line, a row with one is ``detailedRowHeight`` (the caption plus the
// bounded description glimpse).
//
// Roles delivered by TimelineRowModel: eventId / caption / detail / tokenKey /
// flags plus the NRI-0023 tree scalars kind ("event"/"stub") / depth (0/1) /
// hasChildren / expanded / isLastSibling (task 11.1).
// The caption and the detail arrive PRE-FORMATTED by
// Python (dates through the game calendar, open end shown as ``∞``, the
// description already collapsed and bounded, a stub's caption the bare parent
// name): this file never re-derives content, it only paints the delivered
// scalars — never a second rule engine. It only decides how many PAINTED
// lines the glimpse takes (two, then elided) and how the tree reads:
//
//   * a depth-1 child rides the row's own ``childIndent`` further right, with
//     a trunk line running along the parent row's left edge — x = 0, the same
//     street the parent's own wash/outline starts on (live fix 2026-09-30:
//     the line continues the parent card's left border, it no longer hides
//     under the parent's type mark) — and an elbow tick into its own mark
//     (the spec «связными линиями, соединяющими их со строкой родителя»); the
//     trunk runs to the bottom of the row only while another child follows —
//     on the group's LAST child (``isLastSibling``) it stops at the elbow
//     line, the «└» angle (task 11.1, design Д11), and an EXPANDED parent
//     draws the segment of the same line inside itself, from its own caption
//     line to the row's bottom edge, so the branch starts at the parent row's
//     left edge instead of out of the seam between rows (spec «Дерево
//     событий»: «от левого края родителя до локтя первого ребёнка линия
//     непрерывна»); a stub paints neither the trunk nor the type mark
//     and — its delivered flags already say ``selectable == false`` — takes no
//     selection or press at all («выбор и редактирование через неё
//     недоступны»);
//   * the selection/hover wash of a CHILD row starts at the child's indent
//     column (``childWashX``; task 11.3, design Д13 — the live fix
//     2026-09-30 moved the tree line to the row's left edge, so the band now
//     hangs on the indent instead of the line): the gutter between the line
//     and the band stays canvas, and the band's width itself reads as the
//     row's level (the parent's band stays full width); inside a selected
//     row the trunk, the elbow and the muted untyped mark flip to
//     ``color.accent.fg`` like the caption does — muted grey must not dirty
//     the accent (spec «Дерево событий»);
//   * an event row the core saw children for (``hasChildren``) wears the
//     disclosure chevron «▸/▾» — the library ThemeIconButton at the right
//     edge in its ghost (flat) set, glyph at the larger caption-step size,
//     vertically anchored to the SAME caption line as the mark and the elbow
//     (task 11.2, design Д12 — the live audit's «chip opposite to the wash»
//     is gone: transparent at rest, the compiler's derivations on hover, the
//     ``accent.fg`` glyph over the selection wash), the штатный Button role
//     with the usage-site name of the action it
//     performs and the fixed «Развернуть или свернуть раздел» description
//     (the nri-0022 map word, guard-pinned by tests/qml_a11y_scan.py); its
//     press — mouse click or accessibility action — is the row's OWN expand
//     channel, never the row's select/open gesture (design Д8).
//
// Visual truth (spec «Дерево событий» / «Оформление списка из
// токенов»): the caption line; the description line in the secondary token
// (``color.accent.fg`` over the selection wash); the type mark is the bare
// ``color.chart.N`` token square on the left (muted ``color.fg.muted`` for
// untyped, no outline, so it keeps its color over the selection wash), riding
// the caption line; the selection wash is the accent itself, hover the
// compiler's accent-derivation pair — a token COLOR plus a scalar alpha,
// because QML's color parser cannot read the sheet's rgba() form; off-skin the
// guarded lookups land on the same pinned named Qt globals the other controls
// degrade to. Colors come from ``islandPalette`` ONLY — no hex, no OS palette,
// no JS color math (the test_no_chrome_hex invariant). The connector lines are
// the row's own muted token — a text rank, not a new colour role.
//
// Interactions stay thin Qt wrappers: one MouseArea for click/double-click
// gated on the delivered ``selectable`` flag, one right-button TapHandler
// that requests the sub-event menu on main event rows only (NRI-0023 task
// 6.1), one HoverHandler reporting the dynamic tooltip (full name + range —
// the caption itself, readable even when the text elides) through the
// island's bridge. A miss past the rows is handled by the island root, not
// here.
import QtQuick
import nri.components
import "nri/components/tokens.js" as Tokens

Item {
    id: row

    // ── delivered roles (TimelineRowModel roleNames) ────────────────────────
    required property int index
    required property var eventId
    required property string caption
    required property string detail
    required property var tokenKey
    required property var flags
    // NRI-0023 (task 5.3): the tree scalars the core decided (build_rows) —
    // delivered, never re-derived here.
    required property string kind
    required property int depth
    required property bool hasChildren
    required property bool expanded
    // NRI-0023 (task 11.1, design Д11): the core's group-closing scalar — true
    // on the last child of the delivered group (a single child is its own
    // last), false on top-level rows and on stubs. The trunk angle is painted
    // from this flag; the delegate never re-derives the order (file contract).
    required property bool isLastSibling

    // ── island-owned state fed by the root's binding (D2) ───────────────────
    property bool selectedRow: false      // the washed row of selectedId

    // NRI-0021 task 5.1: the ONE row starting «today» (the core marked it in
    // the delivered flags — the rule lives in build_rows, this file paints).
    readonly property bool nowRow: !!(row.flags && row.flags.isNow)

    // NRI-0023 task 5.3 (spec «Дерево событий»): the row's face, read off
    // the delivered tree scalars.
    readonly property bool stubRow: kind === "stub"
    readonly property bool childRow: depth > 0 && !stubRow
    // NRI-0023 task 6.1: the ONLY row kind the sub-event menu belongs to —
    // an event row of the top level (a child never parents, a stub is not
    // an interaction target; the delivered scalars decide, nothing here
    // re-derives).
    readonly property bool mainEventRow: !stubRow && depth === 0
    // The chevron belongs to a real event row the core saw children for —
    // a stub never discloses («шеврон неактивен»), a childless parent has
    // nothing to open (spec «Пустой родитель без шеврона»).
    readonly property bool chevronRow: !stubRow && hasChildren
    // NRI-0023 task 11.1 (design Д11, spec «Дерево событий»: «от левого края
    // родителя до локтя первого ребёнка линия непрерывна»): the EXPANDED
    // parent carries the branch's first segment inside its own row, from the
    // height of its label to the row's bottom edge — the line starts at the
    // parent row's left edge instead of out of the seam between rows. A
    // collapsed parent shows no children, so it paints no segment either.
    readonly property bool parentBranchRow: !stubRow && depth === 0
                                            && hasChildren && expanded
    // The caption line's vertical center in row coordinates — the one height
    // the mark, the elbow, the chevron glyph and both connector ends share
    // (the live audit pinned the elbow↔mark coincidence; tasks 11.1/11.2).
    readonly property real captionLineY: textTopPad + rowText.height / 2

    // ── interaction channel to the root ─────────────────────────────────────
    signal rowClicked()
    signal rowDoubleClicked()
    // NRI-0023 (design Д8): the chevron's channel, deliberately separate
    // from the row's select/open gestures (a parent is selectable too).
    signal rowExpandRequested()
    // NRI-0023 task 6.1 (spec «Создание подсобытия правым кликом», design Д7):
    // the right-click request of a MAIN event row, in scene coordinates the
    // facade maps onto the native QMenu. A child and a stub never request a
    // menu — the handler below is disabled on them, so the signal cannot
    // fire there at all («По подсобытию и заглушке меню не создаётся вовсе»).
    signal rowContextMenuRequested(real x, real y)

    // The delegate contract for the acceptance harness: event rows and the
    // window-only parent stub are distinct kinds (NRI-0023 task 5.1).
    objectName: row.stubRow ? "stubRow" : "eventRow"

    // Accessibility contract (change nri-0012-qml-accessibility, task 2.1,
    // design D2/D3; NRI-0023 task 5.3 for the stub gate): the row is a list
    // item, its name is the delivered caption, and a single Press takes the
    // DOUBLE-click path — the event open (accessibility has no double press;
    // the review opens with one activation). A stub explains its orphans and
    // never interacts: the description slot stays unset («» — the contract's
    // empty) and its Press opens nothing. The mouse paths below stay
    // untouched (single = select).
    Accessible.role: Accessible.ListItem
    Accessible.name: row.caption
    Accessible.description: row.stubRow ? "" : "Открывает событие"
    Accessible.onPressAction: {
        if (!row.stubRow)
            row.rowDoubleClicked()
    }

    // Row geometry: mark at TEXT_LEFT_PAD, mark side MARK_SIZE, text at
    // TEXT_INDENT = 8 + 8 + 4, right bleed TEXT_LEFT_PAD (the migrated
    // ladder row's rhythm, kept identical so the mark/text pair reads the
    // same as every earlier scale). The block hugs the row's top so the
    // caption line — and the mark riding it — sits at the same height in a
    // one-line and a two-line row. NRI-0023 shifts the whole content block
    // right by depth × CHILD_INDENT (the spec's «горизонтальным отступом»)
    // and reserves the chevron square for parent rows.
    readonly property int textLeftPad: 8
    readonly property int markSize: 8
    readonly property int textIndent: 20
    readonly property int textTopPad: 4
    readonly property int lineGap: 1
    readonly property int childIndent: 20
    readonly property int contentShift: depth * childIndent
    // The connector trunk runs along the row's left edge (live fix
    // 2026-09-30): x = 0 is the exact street of the parent's own wash and
    // outline, so the vertical line reads as the continuation of the parent
    // card's left border — NOT a hairline under the parent's type mark — and
    // turns into the child's own mark at the elbow.
    readonly property int trunkX: 0
    // The child's selection/hover band keeps the level step (task 11.3,
    // design Д13): with the tree line at the row's left edge there is no
    // room left of it, so the band hangs on the child's indent column — the
    // gutter between the line and the band stays canvas (spec «Выделение
    // подсобытия не захватывает гуттер дерева»).
    readonly property int childWashX: childIndent

    readonly property var islandTokens:
        Tokens.resolveTokens(typeof islandPalette !== "undefined" ? islandPalette : null)

    readonly property color fgColor: Tokens.token(islandTokens, "color.fg.primary", "black")
    // The secondary text rank of the skin: the same muted token the emptiness
    // hint and the untyped type mark use — the description line is the row's
    // second-rank text, so it takes the row's ONE muted colour (no second
    // colour role invented). The connector lines ride the same rank.
    readonly property color mutedColor: Tokens.token(islandTokens, "color.fg.muted", "gray")
    readonly property color accentColor: Tokens.token(islandTokens, "color.accent", "black")
    readonly property color accentFgColor: Tokens.token(islandTokens, "color.accent.fg", "white")
    // Hover wash = the accent itself under the compiler's row-wash alpha
    // (the pair the Python palette derives; see the comment above). Off-skin
    // it falls back to the same named global the muted captions use, at the
    // migrated 0.25 wash alpha.
    readonly property color rowWashColor: Tokens.token(islandTokens, "color.accent.rowHover", "gray")
    readonly property real rowWashAlpha: Tokens.px(islandTokens, "opacity.accent.rowHover", 0.25)

    // The dynamic row tooltip (spec «Подсказка с названием и датами»): the
    // caption carries the full name and the real range, shown even when the
    // text itself elides. Declared with the library shim, shown by the
    // island's bridge on hover.
    Nri.tooltip: row.caption

    // Selection / hover washes, full row width exactly like fillRect(rect).
    // The selection is the accent itself (alpha 1); the hover wash is the
    // same accent under the migrated 0.25 wash alpha, never under the
    // selection — and only on selectable rows (the stub's flag is false by
    // delivery, so a stub stays inert under the cursor).
    //
    // The wash is rounded on ``radius.sm`` (live fix 2026-09-26): every other
    // list item in the skin wears the card rounding (the snapshot and detail
    // rows ride the rounded `ThemeRatingCard`, fields/buttons/checkboxes all
    // take `radius.sm`), only the timeline row was a square accent block —
    // the same token the content field's corners use, so the row reads as a
    // rounded item inside the field.
    //
    // NRI-0023 task 11.3 (design Д13, spec «Дерево событий» / scenario
    // «Выделение подсобытия не захватывает гуттер дерева»; live fix
    // 2026-09-30 moved the trunk to the row's left edge): the CHILD row's
    // band hangs on the child's indent — its left edge stands at
    // ``childWashX``, the gutter between the tree line at x = 0 and the band
    // stays canvas and the band's width itself reads as the row's level (only
    // the parent keeps the full band). The rounding opens the corner where the
    // band starts, far from the trunk (the audit's A6 «зазубренный ритм» is
    // gone with it).
    Rectangle {
        objectName: "rowWash"
        x: row.childRow ? row.childWashX : 0
        y: 0
        width: row.width - x
        height: row.height
        visible: row.selectedRow
            || (row.hoveredRow && !!(row.flags && row.flags.selectable))
        color: row.selectedRow ? row.accentColor : row.rowWashColor
        opacity: row.selectedRow ? 1.0 : row.rowWashAlpha
        radius: Tokens.px(row.islandTokens, "radius.sm", 6)
    }

    // NRI-0021 task 5.1 (spec «Обводка события, начинающегося „сегодня“»,
    // design Д6): the today-row wears an OUTLINE, never a fill — border
    // against the selection's fill is the mandated visual difference, so a
    // now-row and a selected row can never be confused. The border color is
    // the compiler's accent DERIVATION (``color.accent.hover`` — the accent
    // at the button-wash alpha, the same token family the hover wash pair
    // comes from), not ``color.accent`` itself that fills the selection; the
    // rounding repeats the card rule of the wash above. The flag arrives via
    // the model (re-delivered without a reset on a «now» edit — design Д6),
    // here it is only painted.
    //
    // NRI-0023 task 11.4 (A2, spec scenario «Обводка видна на выбранной
    // строке»): over the selection's solid accent the same-family derivation
    // is orange-on-orange — invisible exactly when the user looks. Only the
    // line COLOR flips (the outline stays an outline): the contrast family
    // of the wash, ``color.accent.fg`` — the same switch the caption rides.
    Rectangle {
        objectName: "rowNowOutline"
        anchors.fill: parent
        visible: row.nowRow
        color: "transparent"
        border.width: 1
        border.color: row.selectedRow
            ? row.accentFgColor
            : Tokens.token(row.islandTokens, "color.accent.hover", "black")
        radius: Tokens.px(row.islandTokens, "radius.sm", 6)
    }

    // NRI-0023 task 5.3 (spec «Подсобытия под родителем с отступом»): the
    // child's connector. The trunk runs along the parent row's left edge
    // (live fix 2026-09-30: the line continues the parent card's border
    // instead of hiding under its type mark), the elbow tick turns from it
    // into the child's own mark at the caption line. Painted on child rows
    // only — a stub and a top-level row carry no connector paint. NRI-0023
    // task 11.1 (design Д11, spec
    // scenario «Последний ребёнок завершает ветку»): the trunk runs to the
    // row's bottom edge ONLY while another child follows («├»); on the
    // group's LAST delivered child (``isLastSibling``) it stops at the elbow
    // line — the «└» angle — so the branch never promises a child that does
    // not exist. Task 11.3 (design Д13, spec «Дерево не грязнит акцент на
    // залировке»): the connector of a selected row is service rank — it
    // flips to ``color.accent.fg`` with the caption, muted grey never
    // dirtying the accent.
    Rectangle {
        objectName: "rowConnectorTrunk"
        visible: row.childRow
        x: row.trunkX
        y: 0
        width: 1
        height: row.isLastSibling ? row.captionLineY : row.height
        color: row.selectedRow ? row.accentFgColor : row.mutedColor
    }
    Rectangle {
        objectName: "rowConnectorElbow"
        visible: row.childRow
        x: row.trunkX
        width: row.textLeftPad + row.contentShift - row.trunkX + 2
        height: 1
        // The mark itself rides rowText's vertical center (below) — the
        // elbow centers on the SAME line, so it lands on the mark's height
        // without a second anchor hop through an id-less object.
        anchors.verticalCenter: rowText.verticalCenter
        color: row.selectedRow ? row.accentFgColor : row.mutedColor
    }
    // The branch's first segment (task 11.1, design Д11, A4): drawn inside
    // the EXPANDED parent's own row, from its caption line down to the row's
    // bottom edge — the seam between delegates then carries a line that
    // began at the parent row's left edge, not «из пустоты». Same trunk
    // column, same service rank and its flip.
    Rectangle {
        objectName: "rowParentSegment"
        visible: row.parentBranchRow
        x: row.trunkX
        y: row.captionLineY
        width: 1
        height: row.height - row.captionLineY
        color: row.selectedRow ? row.accentFgColor : row.mutedColor
    }

    // The type mark: the bare ``color.chart.N`` token square (untyped rows
    // land on the muted fallback). No outline over the wash. It rides the
    // CAPTION line (a sibling anchor), so a two-line row keeps the mark on the
    // same height as a one-line row. A stub paints no mark (spec «Окно
    // фильтрации и пустое состояние»: the stub explains with a name alone).
    // Task 11.3 (design Д13, spec «Дерево не грязнит акцент на залировке»):
    // only the MUTED untyped fallback flips to ``color.accent.fg`` over the
    // selection — a typed mark keeps its chart color (pinned since the flat
    // list: «the mark keeps its color over the wash»).
    Rectangle {
        objectName: "eventTypeMark"
        visible: !row.stubRow
        x: row.textLeftPad + row.contentShift
        width: row.markSize
        height: row.markSize
        anchors.verticalCenter: rowText.verticalCenter
        // tokenKey is the delivered "color.chart.N" key (None/undefined for
        // the untyped row — token() then answers the muted fallback).
        color: row.selectedRow && !row.tokenKey
            ? row.accentFgColor
            : Tokens.token(row.islandTokens,
                           row.tokenKey ? String(row.tokenKey) : "", row.mutedColor)
    }

    // The caption line. Selected rows flip to accent.fg while washed. Parent
    // rows reserve the chevron square so no caption ever hides under it.
    Text {
        id: rowText
        objectName: "rowText"
        x: row.textIndent + row.contentShift
        width: Math.max(row.width - row.textIndent - row.contentShift
                        - row.textLeftPad - (row.chevronRow ? 34 : 0), 0)
        anchors.top: parent.top
        anchors.topMargin: row.textTopPad
        text: row.caption
        elide: Text.ElideRight
        font.pixelSize: Tokens.px(row.islandTokens, "font.size.md", 13)
        color: row.selectedRow ? row.accentFgColor : row.fgColor
    }

    // The description glimpse (spec «Плоский список событий»): the delivered
    // one-line text wrapped over AT MOST two painted lines, the rest elided —
    // Python bounded the text, this file only decides how much of it shows.
    // An event with nothing to say paints nothing here (the row drops back to
    // its single-line height); a stub's delivered detail is empty anyway and
    // the gate keeps the no-description rule explicit.
    Text {
        id: rowDetail
        objectName: "rowDetail"
        x: row.textIndent + row.contentShift
        width: Math.max(row.width - row.textIndent - row.contentShift
                        - row.textLeftPad - (row.chevronRow ? 34 : 0), 0)
        anchors.top: rowText.bottom
        anchors.topMargin: row.lineGap
        text: row.detail
        visible: !row.stubRow && text !== ""
        wrapMode: Text.WordWrap
        elide: Text.ElideRight
        maximumLineCount: 2
        font.pixelSize: Tokens.px(row.islandTokens, "font.size.sm", 11)
        color: row.selectedRow ? row.accentFgColor : row.mutedColor
    }

    // NRI-0023 task 5.3 (spec «Шеврон раскрытия дерева», design Д8) restyled
    // by task 11.2 (design Д12, spec qml-components «Плоская (ghost) гарнитура
    // кнопки библиотеки»): the disclosure glyph of a parent row is the library
    // square in its GHOST set — transparent at rest (no canvas chip, no frame;
    // the audit's «квадратик с точкой» and the hole it burned into the accent
    // wash are both gone), the compiler's derivations answering hover/press,
    // the glyph at the larger caption step of the skin (``font.size.lg``) and
    // riding the SAME caption line as the mark and the elbow (the audit's A1
    // vertical drift is gone). Over the selection wash ``accentBackground``
    // hands the glyph to ``color.accent.fg`` while the background stays
    // transparent — the ghost branch of ThemeButton reads it before the accent
    // fill, so the chip never returns. The hit gauge stays the library's
    // 32×32; Accessibility (nri-0012 contract, nri-0022 description map): the
    // stock Button role ships with the control, the NAME is this usage site's
    // and names the action («Развернуть подсобытия»/«Свернуть подсобытия» — a
    // glyph-only button cannot name itself), the DESCRIPTION carries the
    // hidden meaning of the activation («Развернуть или свернуть раздел» — the
    // fixed map word), and the Press runs the same expand channel as the mouse
    // click, never the row's own gesture. Offscreen-pinned through
    // actionInterface().doAction("Press") in test_timeline_accessibility.py.
    ThemeIconButton {
        id: rowChevron
        objectName: "rowChevron"
        visible: row.chevronRow
        text: row.expanded ? "▾" : "▸"
        ghost: true
        font.pixelSize: Tokens.px(row.islandTokens, "font.size.lg", 14)
        anchors.right: parent.right
        anchors.rightMargin: 2
        anchors.verticalCenter: rowText.verticalCenter
        accentBackground: row.selectedRow
        z: 2
        // No Nri.tooltip here on purpose: the row's own hover bridge reports
        // the ROW's attached tooltip over the whole delegate (spec «в
        // подсказке строки по-прежнему полное имя и диапазон дат»), a second
        // attached would shadow it; the meaning rides the a11y name below.
        Accessible.name: row.expanded ? "Свернуть подсобытия" : "Развернуть подсобытия"
        Accessible.description: "Развернуть или свернуть раздел"
        Accessible.onPressAction: row.rowExpandRequested()
        onClicked: row.rowExpandRequested()
    }

    // Hover: the wash under the cursor + the bridge's tooltip report.
    readonly property bool hoveredRow: rowHover.hovered
    HoverHandler {
        id: rowHover
        onHoveredChanged: {
            if (typeof tooltipBridge === "undefined" || tooltipBridge === null)
                return
            if (hovered)
                tooltipBridge.tooltipRequested((row).Nri.tooltip, point.scenePosition)
            else
                tooltipBridge.tooltipRequested("", Qt.point(0, 0))
        }
    }

    // Click / double-click: selection and editor, the row's whole gesture
    // budget (a press below the click threshold is Qt's own click logic — no
    // drag lives here anymore). Gated on the delivered ``selectable`` flag —
    // the stub's false keeps the whole row inert (spec: «клики по ней ничего
    // не выбирают»).
    MouseArea {
        anchors.fill: parent
        enabled: !!(row.flags && row.flags.selectable)
        acceptedButtons: Qt.LeftButton
        onClicked: row.rowClicked()
        onDoubleClicked: row.rowDoubleClicked()
    }

    // NRI-0023 task 6.1 (spec «Создание подсобытия правым кликом», design Д7):
    // the right-click opener of the sub-event menu, enabled ONLY on a main
    // event row. The штатный TapHandler takes the right button (the left
    // MouseArea above leaves it), so a child or a stub row — where this is
    // disabled — accepts nothing: no menu, and the click is neither a
    // selection nor a miss (those are left-only channels). The reported point
    // is the scene position the facade maps to global for the native QMenu.
    TapHandler {
        objectName: "rowContextMenuTap"
        enabled: row.mainEventRow
        acceptedButtons: Qt.RightButton
        onTapped: {
            const p = point.scenePosition
            row.rowContextMenuRequested(p.x, p.y)
        }
    }
}
