"""Fillable PDF export from a sheet template (add-character-sheet-p)."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.domain.entities.character_sheet import (
    ORIENTATION_LANDSCAPE,
    PAGE_HEIGHT_PT,
    PAGE_WIDTH_PT,
    SheetField,
    SheetPage,
    SheetTemplate,
)
from app.domain.enums.field_type import FieldType

_1PX_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def _field(
    field_id: str,
    ftype: FieldType,
    *,
    x: float = 20.0,
    y: float = 20.0,
    w: float = 80.0,
    h: float = 20.0,
    content: str = "",
    **extra,
) -> SheetField:
    return SheetField(
        id=field_id,
        type=ftype,
        x=x,
        y=y,
        w=w,
        h=h,
        content=content,
        **extra,
    )


def _write(tmp_path: Path, template: SheetTemplate, images=None) -> Path:
    from app.domain.character_sheet_pdf import write_sheet_pdf

    dest = tmp_path / "sheet.pdf"
    write_sheet_pdf(template, dest, images or {})
    return dest


def _field_value(fields: dict, name: str):
    f = fields[name]
    return f.get("/V")


def test_two_pages_a4_order(tmp_path):
    template = SheetTemplate(
        name="Две",
        pages=[
            SheetPage(name="1", fields=[_field("t1", FieldType.TEXT, content="a")]),
            SheetPage(name="2", fields=[_field("t2", FieldType.TEXT, y=40.0, content="b")]),
        ],
    )
    dest = _write(tmp_path, template)
    reader = PdfReader(dest)
    assert len(reader.pages) == 2
    box = reader.pages[0].mediabox
    assert pytest.approx(float(box.width), abs=0.1) == PAGE_WIDTH_PT
    assert pytest.approx(float(box.height), abs=0.1) == PAGE_HEIGHT_PT
    fields = reader.get_fields()
    assert set(fields) == {"t1", "t2"}
    assert _field_value(fields, "t1") == "a"
    assert _field_value(fields, "t2") == "b"


def test_landscape_mediabox(tmp_path):
    template = SheetTemplate(
        name="Альбом",
        orientation=ORIENTATION_LANDSCAPE,
        pages=[SheetPage()],
    )
    dest = _write(tmp_path, template)
    box = PdfReader(dest).pages[0].mediabox
    assert pytest.approx(float(box.width), abs=0.1) == PAGE_HEIGHT_PT
    assert pytest.approx(float(box.height), abs=0.1) == PAGE_WIDTH_PT


def test_widgets_by_id_and_value(tmp_path):
    template = SheetTemplate(
        name="Виджеты",
        pages=[
            SheetPage(
                fields=[
                    _field("tx", FieldType.TEXT, content="Имя"),
                    _field("ta", FieldType.TEXTAREA, y=50.0, h=54.0, content="Предыстория"),
                    _field("cb", FieldType.CHECKBOX, y=120.0, w=18.0, h=18.0, content="true"),
                    _field(
                        "nm",
                        FieldType.NUMBER,
                        y=150.0,
                        content="3.5",
                        min_value=0.0,
                        max_value=10.0,
                    ),
                    _field(
                        "dd",
                        FieldType.DROPDOWN,
                        y=180.0,
                        content="Б",
                        options=["А", "Б"],
                    ),
                ]
            )
        ],
    )
    dest = _write(tmp_path, template)
    data = dest.read_bytes()
    assert b"/JavaScript" not in data
    reader = PdfReader(dest)
    fields = reader.get_fields()
    assert _field_value(fields, "tx") == "Имя"
    assert _field_value(fields, "ta") == "Предыстория"
    assert str(_field_value(fields, "cb")) in ("/Yes", "Yes")
    assert _field_value(fields, "nm") == "3.5"
    assert _field_value(fields, "dd") == "Б"
    opts = fields["dd"].get("/Opt")
    assert opts is not None
    assert [str(o) for o in opts] == ["А", "Б"]


def test_drawing_not_in_get_fields_cyrillic_label(tmp_path):
    template = SheetTemplate(
        name="Рисунок",
        pages=[
            SheetPage(
                fields=[
                    _field("lb", FieldType.LABEL, content="Сила"),
                    _field("rc", FieldType.RECT, y=50.0, w=100.0, h=40.0),
                    _field("ln", FieldType.LINE, y=100.0, w=80.0, h=2.0),
                    _field("im", FieldType.IMAGE, y=120.0, w=40.0, h=40.0, image_id=1),
                    _field("tx", FieldType.TEXT, y=180.0, content="ok"),
                ]
            )
        ],
    )
    dest = _write(tmp_path, template, images={1: _1PX_PNG})
    fields = PdfReader(dest).get_fields()
    assert set(fields) == {"tx"}
    text = PdfReader(dest).pages[0].extract_text() or ""
    assert "Сила" in text


def test_broken_image_still_writes_text(tmp_path):
    template = SheetTemplate(
        name="Битая",
        pages=[
            SheetPage(
                fields=[
                    _field("im", FieldType.IMAGE, image_id=99, w=40.0, h=40.0),
                    _field("tx", FieldType.TEXT, y=80.0, content="жив"),
                ]
            )
        ],
    )
    dest = _write(tmp_path, template, images={})
    assert dest.is_file() and dest.stat().st_size > 0
    fields = PdfReader(dest).get_fields()
    assert "im" not in fields
    assert _field_value(fields, "tx") == "жив"


def test_need_appearances(tmp_path):
    template = SheetTemplate(
        name="NA",
        pages=[SheetPage(fields=[_field("tx", FieldType.TEXT, content="x")])],
    )
    dest = _write(tmp_path, template)
    assert b"/NeedAppearances" in dest.read_bytes()


def test_checkbox_off_and_dropdown_unknown(tmp_path):
    template = SheetTemplate(
        name="Края",
        pages=[
            SheetPage(
                fields=[
                    _field("cb", FieldType.CHECKBOX, content="false"),
                    _field("dd", FieldType.DROPDOWN, y=40.0, content="нет", options=["А"]),
                    _field("lv", FieldType.LINE, y=80.0, w=2.0, h=40.0),
                ]
            )
        ],
    )
    dest = _write(tmp_path, template)
    fields = PdfReader(dest).get_fields()
    assert str(_field_value(fields, "cb")) in ("/Off", "Off")
    val = _field_value(fields, "dd")
    assert val in (None, "", [])


def test_binaryio_and_bad_image_bytes(tmp_path):
    from app.domain.character_sheet_pdf import write_sheet_pdf

    template = SheetTemplate(
        name="IO",
        pages=[
            SheetPage(
                fields=[
                    _field("im", FieldType.IMAGE, image_id=1, w=30.0, h=30.0),
                    _field("tx", FieldType.TEXT, y=50.0, content="ok"),
                ]
            )
        ],
    )
    buf = BytesIO()
    write_sheet_pdf(template, buf, {1: b"not-an-image"})
    buf.seek(0)
    fields = PdfReader(buf).get_fields()
    assert _field_value(fields, "tx") == "ok"


def test_write_oserror_leaves_no_dest(tmp_path, monkeypatch):
    from reportlab.pdfgen.canvas import Canvas

    from app.domain import character_sheet_pdf as pdf_mod

    template = SheetTemplate(name="X", pages=[SheetPage()])
    dest = tmp_path / "out.pdf"

    def boom(self):
        raise OSError("диск полный")

    monkeypatch.setattr(Canvas, "save", boom)
    with pytest.raises(OSError):
        pdf_mod.write_sheet_pdf(template, dest, {})
    assert not dest.exists()
    leftovers = list(tmp_path.glob("*"))
    assert leftovers == []


def test_tmp_unlink_oserror_still_raises(tmp_path, monkeypatch):
    from reportlab.pdfgen.canvas import Canvas

    from app.domain import character_sheet_pdf as pdf_mod

    hits = {"n": 0}
    orig_unlink = Path.unlink

    def flaky(self, missing_ok=False):
        hits["n"] += 1
        if hits["n"] == 1:
            raise OSError("busy")
        return orig_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Canvas, "save", lambda self: (_ for _ in ()).throw(OSError("диск полный")))
    monkeypatch.setattr(Path, "unlink", flaky)
    dest = tmp_path / "out.pdf"
    with pytest.raises(OSError, match="диск"):
        pdf_mod.write_sheet_pdf(SheetTemplate(name="X", pages=[SheetPage()]), dest, {})
    assert not dest.exists()


def test_image_without_id_is_not_a_widget(tmp_path):
    template = SheetTemplate(
        name="Пусто",
        pages=[SheetPage(fields=[_field("im", FieldType.IMAGE, w=30.0, h=30.0)])],
    )
    dest = _write(tmp_path, template)
    fields = PdfReader(dest).get_fields() or {}
    assert "im" not in fields


def test_dropdown_without_options_is_still_a_widget(tmp_path):
    """Every dropdown is an AcroForm field; with no options it offers a blank."""
    template = SheetTemplate(
        name="Пустой список",
        pages=[SheetPage(fields=[_field("dd", FieldType.DROPDOWN, options=[])])],
    )
    dest = _write(tmp_path, template)
    fields = PdfReader(dest).get_fields() or {}
    assert "dd" in fields
    assert str(fields["dd"].get("/FT")) == "/Ch"
    assert _field_value(fields, "dd") in (None, "", [])


def test_label_wraps_and_clips_by_height(tmp_path):
    """The label is drawn as the canvas draws it: wrapped by width, cut by height."""
    words = ["АЛЬФА", "БЕТА", "ГАММА", "ДЕЛЬТА", "ЭПСИЛОН", "ДЗЕТА"]
    template = SheetTemplate(
        name="Перенос",
        pages=[
            SheetPage(
                fields=[
                    _field(
                        "lb",
                        FieldType.LABEL,
                        w=60.0,
                        h=28.0,
                        content=" ".join(words),
                    )
                ]
            )
        ],
    )
    dest = _write(tmp_path, template)
    text = PdfReader(dest).pages[0].extract_text() or ""
    assert words[0] in text          # the first line is on the page…
    assert words[-1] not in text     # …and what the frame cannot hold is not
    assert text.count("\n") >= 1     # more than one line was emitted


def test_wrap_text_breaks_an_overlong_word(tmp_path):
    from app.domain.character_sheet_pdf import _ensure_font, wrap_text

    _ensure_font()
    lines = wrap_text("АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ", 10.0, 40.0)
    assert len(lines) > 1
    assert "".join(lines) == "АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
    assert wrap_text("что угодно", 10.0, 0.0) == []

