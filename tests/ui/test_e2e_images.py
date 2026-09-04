"""E2E: image ingest/replace/remove through EntityCardDialog (design D4/D6,
tasks 5.2/6.1/6.2). Path: timeline context menu → card → pick file → save;
double-click to edit → replace/clear → save.
"""
from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage

from app.presentation.views.entity_card_dialog import EntityCardDialog
from tests.ui import helpers, timeline_probe
from tests.ui.conftest import query_db


def _write_png(path, color=Qt.GlobalColor.red) -> None:
    img = QImage(30, 20, QImage.Format.Format_RGB32)
    img.fill(color)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    path.write_bytes(bytes(data.data()))


def _visible_cards(window) -> list[EntityCardDialog]:
    return [d for d in window.findChildren(EntityCardDialog) if d.isVisible()]


async def test_pick_image_persists_and_shows_in_card(
    app, wait_for, menu_qmenu, modal_qdialog, file_dialogs, tmp_path,
):
    application, window = app
    db_path = application._db_path
    images_dir = application._image_store._image_dir
    name = "Орг С Картинкой"

    png = tmp_path / "art.png"
    _write_png(png)
    file_dialogs["open"] = str(png)

    from tests.ui.helpers import pick_menu_action, right_click

    pick_menu_action(menu_qmenu, "Новая организация")
    timeline_probe.click_object(
        window, "addButton", button=Qt.MouseButton.RightButton)
    await wait_for(lambda: _visible_cards(window))
    card = _visible_cards(window)[0]
    card.name_input.setText(name)

    card.pick_image_btn.click()
    await wait_for(lambda: card._image_id is not None)
    assert not card.image_label.pixmap().isNull()
    assert card.clear_image_btn.isEnabled()

    card.save_button.click()
    await wait_for(lambda: len(query_db(db_path, "SELECT id FROM organizations WHERE name = ?", (name,))) == 1)
    await helpers.wait_until_settled()

    rows = query_db(db_path, "SELECT image_id FROM organizations WHERE name = ?", (name,))
    image_id = rows[0][0]
    assert image_id is not None
    on_disk = query_db(db_path, "SELECT sha256, ext FROM images WHERE id = ?", (image_id,))
    assert len(on_disk) == 1
    sha, ext = on_disk[0]
    assert (images_dir / sha[:2] / f"{sha}.{ext}").exists()
    assert (images_dir / sha[:2] / f"{sha}.preview.webp").exists()


async def test_unreadable_file_warns_and_keeps_state(
    app, wait_for, menu_qmenu, modal_qdialog, file_dialogs, message_boxes, tmp_path,
):
    application, window = app
    from tests.ui.helpers import pick_menu_action, right_click

    bad = tmp_path / "bad.png"
    bad.write_text("not an image")
    file_dialogs["open"] = str(bad)

    pick_menu_action(menu_qmenu, "Новый персонаж")
    timeline_probe.click_object(
        window, "addButton", button=Qt.MouseButton.RightButton)
    await wait_for(lambda: _visible_cards(window))
    card = _visible_cards(window)[0]

    card.pick_image_btn.click()
    assert card._image_id is None
    assert not card.clear_image_btn.isEnabled()
    assert any(kind == "warning" for kind, _t, _txt in message_boxes)


async def test_replace_image_gcs_old_files_keeps_new(
    app, wait_for, menu_qmenu, modal_qdialog, file_dialogs, tmp_path,
):
    application, window = app
    db_path = application._db_path
    images_dir = application._image_store._image_dir
    name = "Орг Для Замены"

    png1 = tmp_path / "one.png"
    _write_png(png1, Qt.GlobalColor.red)
    file_dialogs["open"] = str(png1)

    from tests.ui.helpers import pick_menu_action, right_click

    pick_menu_action(menu_qmenu, "Новая организация")
    timeline_probe.click_object(
        window, "addButton", button=Qt.MouseButton.RightButton)
    await wait_for(lambda: _visible_cards(window))
    card = _visible_cards(window)[0]
    card.name_input.setText(name)
    card.pick_image_btn.click()
    await wait_for(lambda: card._image_id is not None)
    card.save_button.click()
    await wait_for(lambda: len(query_db(db_path, "SELECT id FROM organizations WHERE name = ?", (name,))) == 1)
    await helpers.wait_until_settled()

    old_image_id = query_db(db_path, "SELECT image_id FROM organizations WHERE name = ?", (name,))[0][0]
    old_sha, old_ext = query_db(db_path, "SELECT sha256, ext FROM images WHERE id = ?", (old_image_id,))[0]
    old_orig = images_dir / old_sha[:2] / f"{old_sha}.{old_ext}"
    assert old_orig.exists()

    # Edit: double-click via the org tab list isn't wired here; reopen via detail
    # panel is unnecessary — reuse the app's entity-click path directly.
    entity_id = query_db(db_path, "SELECT id FROM organizations WHERE name = ?", (name,))[0][0]
    window.detail_panel.entity_clicked.emit("organization", entity_id)
    await wait_for(lambda: [d for d in _visible_cards(window) if d.name_input.text() == name])
    edit_card = next(d for d in _visible_cards(window) if d.name_input.text() == name)

    png2 = tmp_path / "two.png"
    _write_png(png2, Qt.GlobalColor.blue)
    file_dialogs["open"] = str(png2)
    edit_card.pick_image_btn.click()
    await wait_for(lambda: edit_card._image_id is not None and edit_card._image_id != old_image_id)
    edit_card.save_button.click()
    await wait_for(
        lambda: query_db(db_path, "SELECT image_id FROM organizations WHERE name = ?", (name,))[0][0]
        != old_image_id
    )
    await helpers.wait_until_settled()

    assert not old_orig.exists()  # GC'd — no longer referenced
    assert query_db(db_path, "SELECT 1 FROM images WHERE id = ?", (old_image_id,)) == []


async def test_store_failure_warns_and_leaves_image_id_unset(
    app, wait_for, menu_qmenu, modal_qdialog, file_dialogs, message_boxes, tmp_path, monkeypatch,
):
    """A corrupt file that slips past the dialog's own check (edge case) is
    caught by the wiring's call into ImageStore.store() (design D4/6.1)."""
    application, window = app
    from app.infrastructure.images.store import ImageStore
    from tests.ui.helpers import pick_menu_action, right_click

    png = tmp_path / "art.png"
    _write_png(png)
    file_dialogs["open"] = str(png)

    def _boom(self, data):
        raise ValueError("corrupt")

    monkeypatch.setattr(ImageStore, "store", _boom)

    pick_menu_action(menu_qmenu, "Новая организация")
    timeline_probe.click_object(
        window, "addButton", button=Qt.MouseButton.RightButton)
    await wait_for(lambda: _visible_cards(window))
    card = _visible_cards(window)[0]
    card.pick_image_btn.click()
    await wait_for(lambda: any(kind == "warning" for kind, _t, _txt in message_boxes))
    assert card._image_id is None


async def test_no_image_store_configured_is_a_safe_noop(
    app, wait_for, menu_qmenu, modal_qdialog, file_dialogs, message_boxes, tmp_path,
):
    application, window = app
    from tests.ui.helpers import pick_menu_action, right_click

    png = tmp_path / "art.png"
    _write_png(png)
    file_dialogs["open"] = str(png)

    application._image_store = None
    try:
        pick_menu_action(menu_qmenu, "Новая организация")
        timeline_probe.click_object(
        window, "addButton", button=Qt.MouseButton.RightButton)
        await wait_for(lambda: _visible_cards(window))
        card = _visible_cards(window)[0]
        card.pick_image_btn.click()
        await helpers.wait_until_settled()
    finally:
        pass  # a fresh app fixture is torn down per test — no need to restore

    assert card._image_id is None
    assert not any(kind == "warning" for kind, _t, _txt in message_boxes)


async def test_clear_image_removes_file(app, wait_for, menu_qmenu, modal_qdialog, file_dialogs, tmp_path):
    application, window = app
    db_path = application._db_path
    images_dir = application._image_store._image_dir
    name = "Орг Убрать Картинку"

    png = tmp_path / "art.png"
    _write_png(png)
    file_dialogs["open"] = str(png)

    from tests.ui.helpers import pick_menu_action, right_click

    pick_menu_action(menu_qmenu, "Новая организация")
    timeline_probe.click_object(
        window, "addButton", button=Qt.MouseButton.RightButton)
    await wait_for(lambda: _visible_cards(window))
    card = _visible_cards(window)[0]
    card.name_input.setText(name)
    card.pick_image_btn.click()
    await wait_for(lambda: card._image_id is not None)
    card.save_button.click()
    await wait_for(lambda: len(query_db(db_path, "SELECT id FROM organizations WHERE name = ?", (name,))) == 1)
    await helpers.wait_until_settled()

    image_id = query_db(db_path, "SELECT image_id FROM organizations WHERE name = ?", (name,))[0][0]
    sha, ext = query_db(db_path, "SELECT sha256, ext FROM images WHERE id = ?", (image_id,))[0]
    orig = images_dir / sha[:2] / f"{sha}.{ext}"
    assert orig.exists()

    entity_id = query_db(db_path, "SELECT id FROM organizations WHERE name = ?", (name,))[0][0]
    window.detail_panel.entity_clicked.emit("organization", entity_id)
    await wait_for(lambda: [d for d in _visible_cards(window) if d.name_input.text() == name])
    edit_card = next(d for d in _visible_cards(window) if d.name_input.text() == name)

    edit_card.clear_image_btn.click()
    assert edit_card._image_id is None
    edit_card.save_button.click()
    await wait_for(
        lambda: query_db(db_path, "SELECT image_id FROM organizations WHERE name = ?", (name,))[0][0] is None
    )
    await helpers.wait_until_settled()

    assert not orig.exists()
    assert query_db(db_path, "SELECT 1 FROM images WHERE id = ?", (image_id,)) == []
