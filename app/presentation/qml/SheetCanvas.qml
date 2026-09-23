// Character-sheet canvas island (change port-character-sheet-canvas-qml-q3b,
// tasks 2.1–2.5; designs D2/D3/D5/D6/D8) — the single QML surface behind all
// three sheet modes (design editor / fill / read-only master view), replacing
// the whole QGraphicsView paint+gesture layer of canvas.py 1:1 («поведение не
// меняется ни на пункт»).
//
// Island contract (the window facades of tasks 3.1–3.3 wire exactly this):
//   * vm             — ``property var vm`` (the design or fill ViewModel: rows
//                      arrive through ``vm.fieldModel`` (D4), page tape
//                      geometry through ``vm.pagesLayout`` — domain-computed
//                      page_origin/page_size/tape_height, never re-derived
//                      in QML; every interaction is a sync slot of the VM,
//                      never an async entry). It is a DECLARED property, not
//                      a context property: the process shares one QQmlEngine
//                      and its root context is global (Q3a pinned that in
//                      list_dialog.py), while editor and fill windows are two
//                      live VMs at once — the facade injects the VM through
//                      ``QQuickWidget.setInitialProperties({"vm": …})`` (a
//                      declared root-object property, applied before the
//                      object completes, so no binding ever sees ``null``);
//                      embedding roots pass it down: ``SheetCanvas {
//                      vm: root.vm }``.
//   * property WRITTEN by the owner — ``mode``: "design" (default) | "fill" |
//                      "readonly" (D2; the read-only master view is the same
//                      surface with input reduced to selection, and the
//                      fill VM's per-row ``disabled`` role — it re-emits on
//                      ``read_only_changed`` — gates fill input without a
//                      second copy of the flag);
//   * invokables     — ``scrollToPage(index)`` (rail → canvas scroll, the
//                      migrated ``scroll_to_page``), ``visibleCenter(index)``
//                      → canvas-space center of the viewport ∩ page (paste
//                      position, the migrated ``visible_page_center``) and
//                      the same-kind probes ``fitWidth()``/``handleCount()``;
//   * reports out    — every visible-page move lands in
//                      ``vm.set_current_page`` (the scroll channel of 1.2);
//                      ``imageFileRequested(fieldId)`` hands the picture-field
//                      file choice to the facade (native QFileDialog, D1),
//                      ``dropdownRequested(fieldId, x, y)`` asks the facade
//                      for the native QMenu at the scene (QQuickWidget)
//                      point of the click — mapped out of the canvas when it
//                      embeds into a composite root (system-menu rule: QML
//                      never owns a menu; the facade returns the pick through
//                      ``vm.set_dropdown``).
//   * objectNames    — ``sheetCanvas`` (root), ``sheetPage-<index>``,
//                      ``sheetField-<fieldId>``, plus ``sheetFlick``,
//                      ``sheetTape``, ``sheetGestures``, ``rubberBand``,
//                      ``sheetInlineLoader``/``sheetInlineEditor``.
//
// Geometry (D3): tape coordinates are page POINTS one-to-one, so the VM
// receives the very numbers the widgets canvas sent it; ``zoom`` scales the
// tape item and is the only view-space transform. Wheel: plain = scroll the
// tape, Ctrl = cursor-anchored zoom clamped 0.25–4.0 in 1.15 steps (the
// migrated MIN_ZOOM/MAX_ZOOM/ZOOM_STEP); the first presentation and every
// orientation change fit the first page's width (task 2.2), and the page
// with the largest visible area syncs to the rail through the VM.
//
// Gestures (D5) are thin dispatches onto the existing sync VM entrances:
// tool click → ``vm.place`` (Shift = one-shot snap override), single/Shift
// click → ``select``/``toggle_select``, rubber band → ``select_ids(ids,
// additive)``, set drag → ``drag_move``/``drag_move_selection`` +
// ``apply_drag``/``apply_drag_selection`` (the per-field clamp and the
// cross-gutter page change are counted by the VM), corner handles →
// ``resize`` inside a gesture, dblclick → inline/checkbox/image branches,
// Del/Backspace → ``remove_selection``, Esc → ``select(null)``.
// Inline editing (D6) reuses ONE editor on the inline field (the proxy
// precedent): live text → ``vm.set_content`` (the single buffer shared with
// the properties panel), Enter / Ctrl+Enter commit, Esc cancel; a number
// commits on Enter through ``vm.apply_number`` and a rejected value is
// re-shown by the editor instead of leaking into the field. Native QML
// editors — QGraphicsProxyWidget is gone.
//
// Colors are the unthemed paper layer: the fixed canvas.py constants ported
// 1:1 below (D8 — the single test_no_chrome_hex exception; chrome islands
// must not copy them).

import QtQuick
import QtQuick.Controls
import QtQuick.Shapes

Rectangle {
    id: canvas
    objectName: "sheetCanvas"
    // No implicit size on purpose: the owner (QQuickWidget in SizeRootObject
    // ToView mode or an anchors.fill embedding) is the only source of the
    // surface width, so the first fit never latches onto a made-up size.
    focus: true
    clip: true
    color: gutterColor      // the gutter/void wash behind the tape

    // ── island surface ──────────────────────────────────────────────────────
    property string mode: "design"        // "design" | "fill" | "readonly"
    // The only data input (D4: rows and tape geometry are the VM's). Declared
    // rather than context-provided so two live windows can share one engine —
    // see the island contract in the header.
    property var vm: null

    signal imageFileRequested(string fieldId)
    signal dropdownRequested(string fieldId, real x, real y)

    // QML signals are not addressable from the Python side (PySide6), so the
    // bridge requests are additionally recorded for the facades and tests.
    property string lastImageFieldId: ""
    property string lastDropdownFieldId: ""
    property real lastDropdownX: -1
    property real lastDropdownY: -1

    // ── the paper layer (canvas.py constants, 1:1 — D8 exception) ───────────
    readonly property color gutterColor: "#e2e2e2"               // GUTTER_BACKGROUND
    readonly property color pageFrameColor: "#5a5a5a"            // _PAGE_FRAME
    readonly property color frameColor: "#788cb4"                // _FRAME_COLOR
    readonly property color selectedColor: "#2f7de1"             // _SELECTED_COLOR
    readonly property color textColor: "#141414"                 // _TEXT_COLOR
    readonly property color lineColor: "#3c3c3c"                 // _LINE_COLOR
    readonly property color checkColor: "#1e6ebe"                // _CHECK_COLOR
    readonly property color imagePlaceholderColor: "#969696"     // _IMAGE_PLACEHOLDER
    readonly property color gridColor: "#d2dae4"                 // _GRID_COLOR
    readonly property real textInset: 2.0                        // _TEXT_INSET
    readonly property real handlePt: 8.0                         // _HANDLE_PT
    readonly property int rubberThresholdPx: 4                   // _RUBBER_THRESHOLD_PX
    // Zoom constants of the view (the migrated MIN/MAX/STEP knobs — D3:
    // view-space properties, never domain rules).
    readonly property real minZoom: 0.25
    readonly property real maxZoom: 4.0
    readonly property real zoomStep: 1.15
    readonly property string sheetFontFamily: "DejaVu Sans"      // register_sheet_font()

    property real zoom: 1.0

    // ── live VM surface (bindings on the pre-existing notify signals) ──────
    // All reads go through ``vmGuard``: the declared ``vm`` is null for the
    // single turn between object creation and the facade's injection, and a
    // TypeError in a binding would poison everything downstream of it.
    readonly property bool vmReady: vm !== null && vm !== undefined
    readonly property var pages: vmReady ? vm.pagesLayout : ({})
    readonly property var selectedList: vmReady ? vm.selectedIds : []
    readonly property string inlineId:
        (vmReady && vm.inlineFieldId !== null && vm.inlineFieldId !== undefined)
            ? String(vm.inlineFieldId) : ""
    readonly property bool designMode: mode === "design"
    // The short-circuit order is load-bearing: the fill VM has no snap
    // machinery, and in fill/readonly mode the right-hand side of && is
    // never evaluated.
    readonly property bool gridVisible: designMode && vmReady && vm.snapOn
    readonly property bool handleTargetsVisible:
        // ``(selectedList || [])`` also covers the fill VM, whose selection
        // channel never feeds a QStringList here
        designMode && (selectedList || []).length === 1 && inlineId === ""
    // Row-content change stamp: bumps the bindings that read roles directly
    // (the inline editor's geometry/font must follow a panel-driven resize
    // the way the old proxy resized with the field).
    property int geomTick: 0

    onGridVisibleChanged: pagesRepeater.itemAt(0)   // visible delegate repaints

    // ── transient gesture state (view-owned records — D5) ──────────────────
    property string dragFid: ""
    property real grabDx: 0
    property real grabDy: 0
    property var rubberOriginPx: null
    property bool rubberArmed: false
    property bool rubberAdditive: false
    property bool pendingClear: false
    property string resizeCorner: ""
    property var resizeStart: null              // [x, y, w, h] page-local,
                                                // the migrated _resize_start
    property bool fitDone: false
    property int lastVisiblePage: -1

    // ───────────────────────────── coordinate maths ─────────────────────────
    // pt = tape (page) units == the numbers the VM works with; px = viewport
    // pixels. The tape sits at content (0,0) with ``zoom`` applied (TopLeft
    // origin), so the four functions below are the whole transform.
    function toPageX(px) { return (px + sheetFlick.contentX) / zoom }
    function toPageY(py) { return (py + sheetFlick.contentY) / zoom }
    function toViewXP(x) { return x * zoom - sheetFlick.contentX }
    function toViewYP(y) { return y * zoom - sheetFlick.contentY }

    // Page geometry is the VM's layout map (domain page_origin/page_size/
    // tape_height — QML only indexes it, D4).
    function pageCount() { return (pages && pages.count) ? pages.count : 0 }
    function pageW() { return (pages && pages.width) ? pages.width : 0 }
    function pageH() { return (pages && pages.height) ? pages.height : 0 }
    function originX(page) {
        return (pages && pages.origins && pages.origins[page]) ? pages.origins[page][0] : 0
    }
    function originY(page) {
        return (pages && pages.origins && pages.origins[page]) ? pages.origins[page][1] : 0
    }

    // Row reads go through the model's get() seam (the timeline precedent):
    // the live template fields, the same role values the delegates bind to.
    function fieldCount() { return fieldsRepeater.count }
    function rowAt(i) { return vm.fieldModel.get(i) }
    function rowById(id) {
        if (id === "")
            return null
        for (var i = fieldCount() - 1; i >= 0; --i) {   // topmost wins
            var row = rowAt(i)
            if (row.id === id)
                return row
        }
        return null
    }
    function rowIndexById(id) {
        for (var i = 0; i < fieldCount(); ++i)
            if (rowAt(i).id === id)
                return i
        return -1
    }
    function sceneRect(row) {  // field rect in tape pt coordinates
        return {left: originX(row.page) + row.x, top: originY(row.page) + row.y,
                right: originX(row.page) + row.x + row.w,
                bottom: originY(row.page) + row.y + row.h}
    }

    // The migrated _field_at: selected fields win (drag-out of a standing
    // selection stays possible), otherwise the topmost row under the point;
    // both passes walk the flat model order backwards (z-order = row order).
    function fieldAt(x, y) {
        var sel = selectedList
        for (var i = fieldCount() - 1; i >= 0; --i) {
            var row = rowAt(i)
            if (sel && sel.indexOf(row.id) !== -1 && rectContains(sceneRect(row), x, y))
                return row.id
        }
        for (i = fieldCount() - 1; i >= 0; --i) {
            row = rowAt(i)
            if (rectContains(sceneRect(row), x, y))
                return row.id
        }
        return ""
    }
    function rectContains(r, x, y) {
        return x >= r.left && x <= r.right && y >= r.top && y <= r.bottom
    }
    function rectIntersects(a, b) {
        return !(a.left > b.right || a.right < b.left ||
                 a.top > b.bottom || a.bottom < b.top)
    }

    // The migrated _handle_at: only with exactly one selected field and no
    // open inline; the corner order (nw, ne, sw, se) matches the old dict.
    function handleAt(x, y) {
        if (!designMode || (selectedList || []).length !== 1 || inlineId !== "")
            return ""
        var row = rowById(selectedList[0])
        if (row === null)
            return ""
        var r = sceneRect(row)
        var half = handlePt / 2
        var pts = [
            ["nw", r.left, r.top], ["ne", r.right, r.top],
            ["sw", r.left, r.bottom], ["se", r.right, r.bottom]
        ]
        for (var i = 0; i < pts.length; ++i) {
            var c = pts[i]
            if (x >= c[1] - half && x <= c[1] + half &&
                    y >= c[2] - half && y <= c[2] + half)
                return c[0]
        }
        return ""
    }
    function handleCount() {   // the migrated handle_count probe
        if (!designMode || (selectedList || []).length !== 1 || inlineId !== ""
                || rowById(selectedList[0]) === null)
            return 0
        return 4
    }

    // ─────────────────────── zoom / scroll / visible page ───────────────────
    function fitWidth() {
        if (width <= 0 || pageCount() === 0 || pageW() <= 0)
            return
        zoom = Math.min(maxZoom, width / pageW())
        sheetFlick.contentX = 0
        sheetFlick.contentY = 0
        fitDone = true
        updateVisiblePage()
    }
    function maybeFit() { if (!fitDone) fitWidth() }

    function zoomAt(px, py, factor) {   // cursor-anchored (the migrated D2)
        var bx = toPageX(px), by = toPageY(py)
        var next = Math.min(maxZoom, Math.max(minZoom, zoom * factor))
        if (next === zoom)
            return
        zoom = next
        var maxX = Math.max(0, sheetFlick.contentWidth - sheetFlick.width)
        var maxY = Math.max(0, sheetFlick.contentHeight - sheetFlick.height)
        sheetFlick.contentX = Math.min(Math.max(0, bx * zoom - px), maxX)
        sheetFlick.contentY = Math.min(Math.max(0, by * zoom - py), maxY)
    }

    // The rail sync of the old _update_visible_page: the page with the
    // largest visible viewport area lands in the VM's scroll channel.
    function updateVisiblePage() {
        if (pageCount() === 0)
            return
        var top = toPageY(0), bottom = toPageY(height)
        var left = toPageX(0), right = toPageX(width)
        var best = lastVisiblePage, bestArea = -1
        for (var i = 0; i < pageCount(); ++i) {
            var y0 = originY(i)
            var oy0 = Math.max(top, y0), oy1 = Math.min(bottom, y0 + pageH())
            if (oy1 <= oy0)
                continue
            var ox0 = Math.max(left, 0), ox1 = Math.min(right, pageW())
            if (ox1 <= ox0)
                continue
            var area = (oy1 - oy0) * (ox1 - ox0)
            if (area > bestArea) {
                best = i
                bestArea = area
            }
        }
        if (best >= 0 && best !== lastVisiblePage) {
            lastVisiblePage = best
            vm.set_current_page(best)
        }
    }

    function scrollToPage(index) {   // the migrated scroll_to_page invokable
        if (index < 0 || index >= pageCount())
            return
        var maxY = Math.max(0, sheetFlick.contentHeight - sheetFlick.height)
        sheetFlick.contentY = Math.min(Math.max(0, originY(index) * zoom), maxY)
    }

    function visibleCenter(index) {  // the migrated visible_page_center
        if (pageCount() === 0)
            return Qt.point(0, 0)
        if (index < 0 || index >= pageCount())
            return Qt.point(pageW() / 2, pageH() / 2)
        var pageTop = originY(index)
        var x0 = Math.max(toPageX(0), 0), x1 = Math.min(toPageX(width), pageW())
        var y0 = Math.max(toPageY(0), pageTop)
        var y1 = Math.min(toPageY(height), pageTop + pageH())
        if (x1 <= x0 || y1 <= y0)
            return Qt.point(pageW() / 2, pageH() / 2)
        return Qt.point((x0 + x1) / 2, (y0 + y1) / 2 - pageTop)
    }

    // ───────────────────────── inline editing (D6) ──────────────────────────
    function inlineInitialText() {
        var row = rowById(inlineId)
        return (row === null || row.content === undefined) ? "" : String(row.content)
    }
    function inlineIsType(typeName) {
        var row = rowById(inlineId)
        return row !== null && row.type === typeName
    }

    function commitInlineClose() {
        // The migrated _commit_inline_close (click-away / other-field /
        // re-double-click): a number gets its Enter applied first (kept if
        // the VM rejects it), then the session commits.
        if (inlineId === "")
            return
        var ed = inlineLoader.item
        if (inlineIsType("number") && ed !== null)
            vm.apply_number(inlineId, ed.text)
        vm.apply_inline()
    }

    function inlineCommitEnter() {
        // Enter on the single-line editor: a number applies through the VM
        // (valid closes, a reject re-shows the stored text — the spec's
        // «отклонённое значение не принимается»); everything else closes
        // its already-live buffer.
        var ed = inlineLoader.item
        if (ed === null)
            return
        if (inlineIsType("number")) {
            if (vm.apply_number(inlineId, ed.text)) {
                vm.apply_inline()
                giveCanvasFocus()
            } else {
                inlineLoader.pushedText = inlineInitialText()
                ed.text = inlineLoader.pushedText
                ed.selectAll()
            }
        } else {
            vm.apply_inline()
            giveCanvasFocus()
        }
    }

    function inlineEscClose() {
        vm.cancel_inline()
        giveCanvasFocus()
    }

    onInlineIdChanged: {
        if (inlineId === "")
            return
        // Re-opened on another field while the editor survived the swap:
        // re-seed the reused buffer (the migrated initial-text contract).
        if (inlineLoader.item !== null) {
            inlineLoader.pushedText = inlineInitialText()
            inlineLoader.item.text = inlineLoader.pushedText
            inlineLoader.item.forceActiveFocus()
        }
    }
    function giveCanvasFocus() {
        if (inlineId === "")
            forceActiveFocus()
    }

    // ───────────────────────────── keyboard (D5) ────────────────────────────
    // Keys.onPressed (Qt 6 exposes no Keys.onKeyPressed) runs the migrated
    // keyPressEvent branches: while an inline editor is open the keys belong
    // to the editor (the chain consults it first); otherwise Del/Backspace
    // delete the design selection and Esc clears it (fill: Esc clears the
    // selection only, exactly like the old widget).
    Keys.onPressed: function (event) {
        if (inlineId !== "")
            return false
        var k = event.key
        if ((k === Qt.Key_Delete || k === Qt.Key_Backspace)
                && designMode
                && selectedList !== null && selectedList.length > 0) {
            vm.remove_selection()
            return true
        }
        if (k === Qt.Key_Escape) {
            vm.select(null)
            return true
        }
        return false
    }

    // ───────────────────────────── tap dispatcher ───────────────────────────
    function onPressDesign(x, y, modifiers) {
        var shift = (modifiers & Qt.ShiftModifier) !== 0
        var px = toPageX(x), py = toPageY(y)

        if (vm.currentTool !== "pointer") {
            var hit = vm.page_at(px, py)
            if (hit && hit.page !== undefined) {
                if (shift)
                    vm.set_snap_override(false)   // Shift = one-shot no-snap
                vm.place(vm.tool_field_type(), hit.x, hit.y, hit.page)
                vm.set_snap_override(null)
            }
            return true    // a gutter/void click with a place tool places
                           // nothing (scene_to_page answered {} — spec)
        }

        var fieldId = fieldAt(px, py)
        if (inlineId !== "") {
            if (fieldId === inlineId)
                return true      // the editor owns presses on its own field
            commitInlineClose()  // commit-away, then continue as a fresh press
        }
        var corner = handleAt(px, py)
        if (corner !== "") {
            var row = rowById(vm.selectedIds[0])
            if (row !== null) {
                resizeCorner = corner
                resizeStart = [row.x, row.y, row.w, row.h]
                vm.begin_gesture()
            }
            return true
        }
        var sel = selectedList
        if (fieldId !== "") {
            if (shift) {
                vm.toggle_select(fieldId)
            } else {
                if (sel === null || sel.indexOf(fieldId) === -1)
                    vm.select(fieldId)
                startDrag(fieldId, px, py)
            }
            return true
        }
        rubberOriginPx = Qt.point(x, y)
        rubberArmed = false
        rubberAdditive = shift
        pendingClear = true
        if (!shift)
            vm.select(null)
        return true
    }

    function startDrag(fieldId, px, py) {
        var row = rowById(fieldId)
        if (row === null)
            return
        dragFid = fieldId
        grabDx = px - row.x
        grabDy = py - (originY(row.page) + row.y)
    }

    function onDoubleClickDesign(x, y) {
        var px = toPageX(x), py = toPageY(y)
        var fieldId = fieldAt(px, py)
        if (fieldId === "")
            return
        var row = rowById(fieldId)
        if (row === null)
            return
        if (row.type === "checkbox") {
            if (inlineId !== "" && inlineId !== fieldId)
                commitInlineClose()
            vm.toggle_checkbox(fieldId)     // the default flips (migrated)
            return
        }
        if (row.type === "image") {
            lastImageFieldId = fieldId
            imageFileRequested(fieldId)  // file bridge to the facade
            return
        }
        if (row.type === "dropdown" || row.type === "rect" || row.type === "line") {
            vm.select(fieldId)
            return
        }
        // label / text / textarea / number: inline editing
        if (inlineId !== "" && inlineId !== fieldId)
            commitInlineClose()
        vm.open_inline(fieldId)
    }

    function onReleaseDesign(x, y) {
        var px = toPageX(x), py = toPageY(y)
        if (resizeCorner !== "") {
            vm.end_gesture()
            vm.set_snap_override(null)
        } else if (dragFid !== "") {
            var sel = selectedList
            if (sel !== null && sel.length > 1)
                vm.apply_drag_selection(px, py, grabDx, grabDy, dragFid)
            else
                vm.apply_drag(dragFid, px, py, grabDx, grabDy)
            vm.set_snap_override(null)
        } else if (rubberArmed) {
            var target = rubberRectPt()
            var ids = []
            for (var i = 0; i < fieldCount(); ++i) {
                var row = rowAt(i)
                if (rectIntersects(sceneRect(row), target))
                    ids.push(row.id)
            }
            vm.select_ids(ids, rubberAdditive)
        } else if (pendingClear) {
            vm.select(null)
        }
        dragFid = ""
        rubberArmed = false
        rubberOriginPx = null
        rubberAdditive = false
        pendingClear = false
        resizeCorner = ""
        resizeStart = null
        rubberBand.visible = false
    }

    function rubberRectPt() {
        var x0 = rubberBand.x, x1 = rubberBand.x + rubberBand.width
        var y0 = rubberBand.y, y1 = rubberBand.y + rubberBand.height
        return {left: toPageX(x0), right: toPageX(x1),
                top: toPageY(y0), bottom: toPageY(y1)}
    }

    // The migrated _apply_handle_resize, literal corner arithmetic in
    // page-local points (w/n drag the anchor with the cursor); the VM does
    // the clamp/snap of the result.
    function applyHandleResize(lx, ly) {
        if (resizeCorner === "" || resizeStart === null)
            return
        if (selectedList === null || selectedList.length !== 1)
            return
        var fid = selectedList[0]
        var row = rowById(fid)
        if (row === null)
            return
        var x = resizeStart[0], y = resizeStart[1]
        var w = resizeStart[2], h = resizeStart[3]
        var lxx = lx, lyy = ly - originY(row.page)
        if (resizeCorner.indexOf("e") !== -1) w = lxx - x
        if (resizeCorner.indexOf("s") !== -1) h = lyy - y
        if (resizeCorner.indexOf("w") !== -1) { w = x + w - lxx; x = lxx }
        if (resizeCorner.indexOf("n") !== -1) { h = y + h - lyy; y = lyy }
        vm.resize(fid, x, y, w, h)
    }

    // ── fill / read-only press (the migrated _fill_press, branch-for-branch) ─
    // Per-row ``disabled`` is the read-only gate: the modal master view
    // (mode "readonly") and live set_read_only flips share one channel
    // because the model's disabled role re-emits on read_only_changed (D4).
    function onFillPress(x, y, doubleClicked) {
        var px = toPageX(x), py = toPageY(y)
        var fieldId = fieldAt(px, py)
        var row = rowById(fieldId)
        if (mode === "readonly") {
            vm.select(fieldId === "" ? null : fieldId)
            return
        }
        if (row !== null && row.disabled) {
            vm.select(fieldId)
            return
        }
        if (inlineId !== "") {
            if (fieldId === inlineId)
                return
            commitInlineClose()
        }
        if (fieldId === "") {
            vm.select(null)
            return
        }
        vm.select(fieldId)
        if (row.type === "checkbox") {
            if (!doubleClicked)        // a dbl pair toggles once (old timer)
                vm.toggle_checkbox(fieldId)
        } else if (row.type === "text" || row.type === "textarea"
                || row.type === "number") {
            vm.open_inline(fieldId)
        } else if (row.type === "dropdown") {
            // The facade answers with a QMenu.popup at QQuickWidget
            // coordinates — the same space the widget-embedded canvas had as
            // view root. This island embeds into a composite root (the rail
            // sits beside the canvas), so localize through the scene: for a
            // bare canvas root mapToItem(null, …) is the identity, but an
            // embedded canvas reports the facade-correct widget coordinates.
            var menuPoint = canvas.mapToItem(null, x, y)
            lastDropdownFieldId = fieldId
            lastDropdownX = menuPoint.x
            lastDropdownY = menuPoint.y
            dropdownRequested(fieldId, menuPoint.x, menuPoint.y)
        } else if (row.type === "image") {
            if (!doubleClicked) {
                lastImageFieldId = fieldId
                imageFileRequested(fieldId)    // the file bridge
            }
        }
    }

    MouseArea {
        id: sheetGestures
        objectName: "sheetGestures"
        anchors.fill: parent
        z: 1
        acceptedButtons: Qt.LeftButton

        onPressed: (mouse) => {
            if (mouse.button !== Qt.LeftButton)
                return
            if (canvas.designMode) {
                if (canvas.onPressDesign(mouse.x, mouse.y, mouse.modifiers)) {
                    canvas.mousePressedAnywhere()
                    mouse.accepted = true
                }
                return
            }
            canvas.onFillPress(mouse.x, mouse.y, mouse.doubleClick)
            canvas.giveCanvasFocus()
            mouse.accepted = true
        }
        onPositionChanged: (mouse) => {
            if (!canvas.designMode || !(mouse.buttons & Qt.LeftButton))
                return
            var shift = (mouse.modifiers & Qt.ShiftModifier) !== 0
            var px = canvas.toPageX(mouse.x), py = canvas.toPageY(mouse.y)
            if (canvas.resizeCorner !== "") {
                vm.set_snap_override(shift ? false : null)
                canvas.applyHandleResize(px, py)
            } else if (canvas.dragFid !== "" && canvas.inlineId === "") {
                vm.set_snap_override(shift ? false : null)
                var sel = canvas.selectedList
                if (sel !== null && sel.length > 1)
                    vm.drag_move_selection(px, py, canvas.grabDx,
                                           canvas.grabDy, canvas.dragFid)
                else
                    vm.drag_move(canvas.dragFid, px, py,
                                 canvas.grabDx, canvas.grabDy)
            } else if (canvas.rubberOriginPx !== null && !canvas.rubberArmed) {
                var dist = Math.abs(mouse.x - canvas.rubberOriginPx.x)
                           + Math.abs(mouse.y - canvas.rubberOriginPx.y)
                if (dist <= canvas.rubberThresholdPx)
                    return
                canvas.rubberArmed = true    // past the threshold: pendingClear
                canvas.pendingClear = false  // dies (migrated branch)
                canvas.armRubber(mouse.x, mouse.y)
            }
            if (canvas.rubberArmed)
                canvas.stretchRubber(mouse.x, mouse.y)
        }
        onReleased: (mouse) => {
            if (canvas.designMode && mouse.button === Qt.LeftButton) {
                canvas.onReleaseDesign(mouse.x, mouse.y)
                canvas.giveCanvasFocus()
            }
            mouse.accepted = true
        }
        onDoubleClicked: (mouse) => {
            if (canvas.designMode)
                canvas.onDoubleClickDesign(mouse.x, mouse.y)
        }
        onWheel: (wheel) => {
            // The migrated wheelEvent: Ctrl = cursor-anchored zoom, plain
            // wheel scrolls the tape; nothing else reaches the Flickable.
            var angle = wheel.angleDelta.y
            if (!angle)
                return
            wheel.accepted = true
            if (wheel.modifiers & Qt.ControlModifier)
                canvas.zoomAt(wheel.x, wheel.y,
                              angle > 0 ? canvas.zoomStep : 1.0 / canvas.zoomStep)
            else {
                var maxY = Math.max(0, sheetFlick.contentHeight - sheetFlick.height)
                sheetFlick.contentY = Math.min(Math.max(0, sheetFlick.contentY - angle), maxY)
            }
        }
    }

    function mousePressedAnywhere() { giveCanvasFocus() }

    function armRubber(x, y) {
        rubberBand.visible = true
        stretchRubber(x, y)
    }
    function stretchRubber(x, y) {
        var o = rubberOriginPx
        rubberBand.x = Math.min(o.x, x)
        rubberBand.y = Math.min(o.y, y)
        rubberBand.width = Math.abs(x - o.x)
        rubberBand.height = Math.abs(y - o.y)
    }

    // ── fit/visible-page lifecycle (tasks 2.2): first presentation and every
    //    orientation switch fit the width of the first page; tape moves
    //    re-anchor the largest-visible-page report (the migrated settle).
    Connections {
        target: vm
        function onPages_changed() {
            canvas.maybeFit()
            canvas.updateVisiblePage()
        }
        function onTemplate_changed() {
            // the migrated _rebuild tail: first-fit while unfitted, then the
            // visible-page reread (a page move also arrives via pagesChanged
            // — both paths are idempotent).
            canvas.maybeFit()
            canvas.updateVisiblePage()
            canvas.giveCanvasFocus()
        }
    }
    Connections {
        // orientation exists on the design VM only (the fill template's
        // orientation is fixed at load) — the design-only target keeps the
        // fill canvas silent, the fit rule itself is unchanged (2.2)
        target: canvas.designMode && canvas.vmReady ? vm : null
        function onOrientation_changed() {
            canvas.fitWidth()      // refit on every orientation switch (2.2)
        }
    }
    onWidthChanged: maybeFit()
    onHeightChanged: maybeFit()
    onVisibleChanged: maybeFit()
    Component.onCompleted: maybeFit()

    // The migrated _on_field_data_changed/_on_geometry_changed: every VM-side
    // change of the row (the properties panel, undo, a remote value) bumps the
    // stamp the inline geometry/typography bindings watch, and pushes the new
    // content into the open editor — no second buffer (the editor's own live
    // write echo is recognized by the pushed-text guard). The granular VM
    // signals carry this (both VMs spell content/geometry/font/props the same;
    // the model is fed by the very same signals, so nothing arrives later).
    function syncInlineFromVm() {
        geomTick += 1
        if (inlineId === "" || inlineLoader.item === null)
            return
        let content = inlineInitialText()
        if (content !== inlineLoader.item.text && content !== inlineLoader.pushedText) {
            inlineLoader.pushedText = content
            inlineLoader.item.text = content
        }
    }
    Connections {
        target: vm
        function onField_content_changed(_fieldId) { canvas.syncInlineFromVm() }
        function onField_geometry_changed(_fieldId) { canvas.syncInlineFromVm() }
        function onField_font_changed(_fieldId) { canvas.syncInlineFromVm() }
        function onField_props_changed(_fieldId) { canvas.syncInlineFromVm() }
    }

    // ───────────────────────────── visual tree ──────────────────────────────
    Flickable {
        id: sheetFlick
        objectName: "sheetFlick"
        anchors.fill: parent
        interactive: false          // the MouseArea owns every gesture
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        onContentYChanged: canvas.updateVisiblePage()
        onContentXChanged: canvas.updateVisiblePage()
        onHeightChanged: canvas.updateVisiblePage()
        onWidthChanged: canvas.updateVisiblePage()

        contentWidth: contentTape.width * canvas.zoom
        contentHeight: contentTape.height * canvas.zoom

        Item {
            id: contentTape
            objectName: "sheetTape"
            // the zoom scale pins to the tape's top-left corner, which is also
            // the Flickable's content origin (D3 tape-unit contract)
            transformOrigin: Item.TopLeft
            width: canvas.pageW()
            height: (pages && pages.tapeHeight) ? pages.tapeHeight : 0
            scale: canvas.zoom      // TopLeft origin: pt↔px is one multiply

            // One page per Repeater row at its VM-output domain origin,
            // the gutter visible between them (task 2.1).
            Repeater {
                id: pagesRepeater
                model: canvas.pageCount()
                Rectangle {
                    id: pageFrame
                    objectName: "sheetPage-" + index
                    x: canvas.originX(index)
                    y: canvas.originY(index)
                    width: canvas.pageW()
                    height: canvas.pageH()
                    color: "white"
                    border.color: canvas.pageFrameColor
                    border.width: 1

                    // The design-layer snap grid (the old PageSheetItem
                    // branch): painted in page-POINT space so it scales with
                    // the tape exactly like the scene grid did; only shown
                    // while the VM's snap flag is on.
                    Canvas {
                        objectName: "pageGrid"
                        anchors.fill: parent
                        visible: canvas.gridVisible
                        onVisibleChanged: requestPaint()
                        property real gridStep: (pages && pages.gridStep) ? pages.gridStep : 4
                        onGridStepChanged: requestPaint()
                        onPaint: {
                            var ctx = getContext("2d")
                            ctx.clearRect(0, 0, width, height)
                            if (!visible || gridStep <= 0)
                                return
                            ctx.strokeStyle = canvas.gridColor
                            ctx.lineWidth = 1
                            ctx.beginPath()
                            for (var gx = 0; gx <= width + 0.01; gx += gridStep) {
                                ctx.moveTo(gx + 0.5, 0)
                                ctx.lineTo(gx + 0.5, height)
                            }
                            for (var gy = 0; gy <= height + 0.01; gy += gridStep) {
                                ctx.moveTo(0, gy + 0.5)
                                ctx.lineTo(width, gy + 0.5)
                            }
                            ctx.stroke()
                        }
                    }
                }
            }

            // One delegate per row of the whole model on the tape: the flat
            // Repeater order IS the z-order (page order first, then the
            // page's field order — the same semantics the old
            // ``setZValue(page*10000 + fieldIndex + 1)`` ladder had, task
            // 2.1). Geometry reads the row roles at binding time; hit-test
            // and rubber selection stay arithmetic on the VM's get() seam
            // (D5 — no second geometry source, no field copy).
            Repeater {
                id: fieldsRepeater
                model: canvas.vmReady ? canvas.vm.fieldModel : null

                delegate: Item {
                    id: fieldItem
                    objectName: "sheetField-" + model.id
                    x: model.x
                    y: canvas.originY(model.page) + model.y
                    width: model.w
                    height: model.h

                    readonly property bool isSel:
                        (canvas.selectedList || []).indexOf(model.id) !== -1
                    readonly property bool isInline: canvas.inlineId === model.id
                    readonly property bool wrapped:
                        model.type === "label" || model.type === "textarea"
                        || model.type === "dropdown"
                    readonly property bool hasText:
                        model.type === "label" || model.type === "text"
                        || model.type === "textarea" || model.type === "number"
                        || model.type === "dropdown"
                    readonly property bool isFrame:
                        model.type !== "image" && model.type !== "line"

                    // label/text/textarea/number/dropdown/rect/checkbox: one
                    // frame pass; image draws its own dashed frame, line is
                    // an axis fill (the migrated paint branches).
                    Rectangle {
                        objectName: "fieldFrame"
                        anchors.fill: parent
                        color: "transparent"
                        border.width: fieldItem.isSel ? 1.5 : 1.0
                        border.color: fieldItem.isSel ? canvas.selectedColor
                                                      : canvas.frameColor
                        visible: fieldItem.isFrame
                    }

                    // The text pass exists only for the text-bearing types —
                    // rect/line/image/checkbox never grow a fieldText child
                    // (the migrated paint had no text branch for them).
                    Loader {
                        objectName: "fieldTextLoader"
                        anchors.fill: parent
                        active: fieldItem.hasText
                        sourceComponent: Text {
                            objectName: "fieldText"
                            anchors.fill: parent
                            anchors.margins: canvas.textInset
                            visible: model.content !== ""
                            text: model.content
                            color: canvas.textColor
                            font.family: canvas.sheetFontFamily
                            font.pointSize: Math.max(1, Math.round(model.fontSize))
                            wrapMode: fieldItem.wrapped ? Text.WordWrap
                                                        : Text.NoWrap
                            verticalAlignment: Text.AlignVCenter
                            clip: true
                        }
                    }

                    // checkbox: the frame above plus a check mark when true
                    // (in fill the model already resolved the instance value
                    // through the domain's resolve_display — "true"/"false").
                    Shape {
                        objectName: "fieldCheck"
                        anchors.fill: parent
                        visible: model.type === "checkbox"
                                 && model.content === "true"
                        ShapePath {
                            strokeColor: canvas.checkColor
                            strokeWidth: 2
                            fillColor: "transparent"
                            startX: 0.2 * fieldItem.width
                            startY: 0.5 * fieldItem.height
                            PathLine { x: 0.42 * fieldItem.width; y: 0.75 * fieldItem.height }
                            PathLine { x: 0.8 * fieldItem.width; y: 0.25 * fieldItem.height }
                        }
                    }

                    // image: a dashed placeholder frame; the bytes arrive
                    // asynchronously through the shared id-provider (D7).
                    Canvas {
                        objectName: "fieldImageFrame"
                        anchors.fill: parent
                        visible: model.type === "image"
                        // a Connections scope has no Canvas requestPaint —
                        // watch the selection through a property instead
                        property bool selWatch: fieldItem.isSel
                        onSelWatchChanged: requestPaint()
                        onVisibleChanged: requestPaint()
                        onWidthChanged: requestPaint()
                        onHeightChanged: requestPaint()
                        onPaint: {
                            var ctx = getContext("2d")
                            ctx.clearRect(0, 0, width, height)
                            ctx.setLineDash([4, 3])
                            ctx.lineWidth = fieldItem.isSel ? 1.5 : 1.2
                            ctx.strokeStyle = fieldItem.isSel
                                    ? canvas.selectedColor
                                    : canvas.imagePlaceholderColor
                            var half = ctx.lineWidth / 2
                            ctx.strokeRect(half, half, width - ctx.lineWidth,
                                           height - ctx.lineWidth)
                        }
                        Image {
                            objectName: "fieldImage"
                            id: fieldImageView
                            anchors.fill: parent
                            anchors.margins: canvas.textInset
                            visible: model.imageKey !== ""
                            fillMode: Image.PreserveAspectFit
                            asynchronous: true
                            clip: true
                            // A QQuickWidget has no render thread: the cold
                            // request lands on the app loop, so the provider
                            // answers null and prefetches the store row
                            // asynchronously. ``resolved`` (image:// provider
                            // hub, D7) re-asks the same id once the path is
                            // warm — the reload suffix bypasses Qt's failed
                            // reply cache for the exact url.
                            property int reloadTick: 0
                            source: model.imageKey === ""
                                    ? "" : "image://sheet/" + model.imageKey
                                           + (reloadTick > 0 ? "?r=" + reloadTick : "")
                            Connections {
                                target: typeof sheetImages === "undefined"
                                        ? null : sheetImages
                                function onResolved(imageId) {
                                    if (String(imageId) === String(model.imageKey))
                                        fieldImageView.reloadTick += 1
                                }
                            }
                        }
                    }

                    // line: the smaller side is the thickness (D7), the
                    // axis direction follows the longer side; selected → the
                    // selection color (the old _paint_line brush branch).
                    Rectangle {
                        objectName: "fieldLine"
                        x: 0
                        y: 0
                        visible: model.type === "line"
                        width: model.w > model.h ? model.w : Math.max(model.w, 1)
                        height: model.w > model.h ? Math.max(model.h, 1) : model.h
                        color: fieldItem.isSel ? canvas.selectedColor
                                               : canvas.lineColor
                    }

                    // The design-layer resize handles (the migrated
                    // _paint_handles): four 8-pt squares at the corners,
                    // drawn by the selected field itself (same z-ladder the
                    // old paint produced). The gesture layer hit-tests them
                    // arithmetically, so the handles take no input here.
                    Repeater {
                        model: canvas.handleTargetsVisible && fieldItem.isSel ? 4 : 0
                        Rectangle {
                            objectName: "fieldHandle-" + index
                            width: canvas.handlePt
                            height: canvas.handlePt
                            color: canvas.selectedColor
                            border.color: "white"
                            border.width: 0.5
                            x: (index === 1 || index === 3)
                                    ? fieldItem.width - canvas.handlePt / 2
                                    : -canvas.handlePt / 2
                            y: (index >= 2)
                                    ? fieldItem.height - canvas.handlePt / 2
                                    : -canvas.handlePt / 2
                        }
                    }
                }
            }
        }
    }

    // ── rubber band (view-space px, the QRubberBand rectangle) and the one
    //    reused inline editor floating above the tape ────────────────────────
    Rectangle {
        id: rubberBand
        objectName: "rubberBand"
        visible: false
        z: 2
        color: canvas.selectedColor
        opacity: 0.2
        border.color: canvas.selectedColor
        border.width: 1
    }

    // One reused inline editor over the inline field (the proxy editor
    // precedent, D6): TextField for label/text/number, TextArea for
    // textarea (Enter inserts, Ctrl+Enter commits). Geometry and font follow
    // the zoomed field live through the bindings below (scroll, zoom, a
    // panel-driven resize — the geomTick re-reads model changes).
    Loader {
        id: inlineLoader
        objectName: "sheetInlineLoader"
        z: 3
        active: canvas.inlineId !== ""
        property string pushedText: ""

        readonly property int inlineRow:
            inlineRowNow()
        function inlineRowNow() {
            if (canvas.geomTick < 0)     // tick read keeps the binding live to
                return -1                // row-content/model changes
            return canvas.inlineId === "" ? -1
                                          : canvas.rowIndexById(canvas.inlineId)
        }
        readonly property var rowData:
            (inlineRow >= 0 && geomTick >= 0) ? vm.fieldModel.get(inlineRow) : null
        readonly property bool isNumber:
            inlineRow >= 0 ? rowData.type === "number" : false
        readonly property bool isTextarea:
            inlineRow >= 0 ? rowData.type === "textarea" : false
        readonly property real fieldFontSize:
            inlineRow >= 0 ? rowData.fontSize : 10

        visible: inlineRow >= 0
        x: (rowData !== null && canvas.geomTick >= 0)
                ? canvas.toViewXP(rowData.x) + canvas.zoom * 0.5 : 0
        y: (rowData !== null && canvas.geomTick >= 0)
                ? canvas.toViewYP(canvas.originY(rowData.page) + rowData.y)
                  + canvas.zoom * 0.5
                : 0
        width: (rowData !== null && canvas.geomTick >= 0)
                ? Math.max(16, (rowData.w - 2) * canvas.zoom) : 0
        height: (rowData !== null && canvas.geomTick >= 0)
                ? Math.max(10, (rowData.h - 2) * canvas.zoom) : 0

        sourceComponent: isTextarea ? inlineAreaComponent : inlineFieldComponent

        onLoaded: {
            pushedText = canvas.inlineInitialText()
            item.text = pushedText
            item.forceActiveFocus()
        }

        Component {
            id: inlineFieldComponent
            TextField {
                objectName: "sheetInlineEditor"
                leftPadding: 1
                rightPadding: 1
                topPadding: 0
                bottomPadding: 0
                font.family: canvas.sheetFontFamily
                font.pointSize: Math.max(1, Math.round(inlineLoader.fieldFontSize * canvas.zoom))
                selectByMouse: true
                // label/text write live; a number waits for Enter (invalid
                // drafts must not leak into the field — apply gates them).
                onTextChanged: {
                    if (inlineLoader.isNumber)
                        return
                    inlineLoader.pushedText = text
                    vm.set_content(canvas.inlineId, text)
                }
                onAccepted: canvas.inlineCommitEnter()
                Keys.onPressed: function (event) {
                    // Esc owns the cancel branch; Enter was eaten by the
                    // single-line text input into onAccepted.
                    if (event.key === Qt.Key_Escape) {
                        canvas.inlineEscClose()
                        return true
                    }
                    return false
                }
            }
        }

        Component {
            id: inlineAreaComponent
            TextArea {
                objectName: "sheetInlineEditor"
                wrapMode: TextArea.WordWrap
                font.family: canvas.sheetFontFamily
                font.pointSize: Math.max(1, Math.round(inlineLoader.fieldFontSize * canvas.zoom))
                selectByMouse: true
                onTextChanged: {
                    inlineLoader.pushedText = text
                    vm.set_content(canvas.inlineId, text)
                }
                Keys.onPressed: function (event) {
                    if (event.key === Qt.Key_Escape) {
                        canvas.inlineEscClose()
                        return true
                    }
                    // Ctrl(+Shift)+Enter commits through the VM; a plain
                    // Enter must reach the TextArea so it inserts the newline
                    // itself (the migrated plain-Enter-is-soft-break rule).
                    if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                            && (event.modifiers & Qt.ControlModifier))
                        return canvas.areaEnter(event)
                    return false
                }
            }
        }
    }

    function areaEnter(event) {
        // Plain Enter inserts a newline in the area; Ctrl(+Shift)+Enter
        // closes the session keeping the live text (the migrated filter).
        if (event.modifiers & Qt.ControlModifier) {
            vm.apply_inline()
            giveCanvasFocus()
            return true
        }
        return false
    }
}
