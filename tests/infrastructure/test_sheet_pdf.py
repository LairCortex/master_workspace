"""Tests for generate_sheet_pdf: static rendering, AcroForm fields, metadata,
clipping (tasks 4.1–4.3). PDF assertions go through pypdf."""
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.domain.entities.character_sheet import SheetField, SheetPage, SheetTemplate
from app.domain.enums.field_type import FieldType
from app.domain.enums.sheet_orientation import SheetOrientation
from app.infrastructure.pdf.sheet_pdf import generate_sheet_pdf

LANDSCAPE_MEDIABOX = (0.0, 0.0, 841.89, 595.28)
PORTRAIT_MEDIABOX = (0.0, 0.0, 595.28, 841.89)


# ── helpers ────────────────────────────────────────────────────────────────


def make_field(field_id: str, field_type: FieldType, **overrides) -> SheetField:
    params = dict(
        id=field_id,
        type=field_type,
        x=50.0,
        y=100.0,
        w=200.0,
        h=24.0,
        label="Поле",
        default_value="",
        font_size=12.0,
    )
    params.update(overrides)
    return SheetField(**params)


def make_template(
    orientation: SheetOrientation = SheetOrientation.LANDSCAPE,
    **pages_fields,
) -> SheetTemplate:
    """pages_fields: page_name -> list[SheetField]."""
    return SheetTemplate(
        name="Лист персонажа",
        orientation=orientation,
        pages=[SheetPage(name=n, fields=list(f)) for n, f in pages_fields.items()],
    )


def generate(tmp_path: Path, template: SheetTemplate) -> Path:
    out = tmp_path / f"{template.name}.pdf"
    generate_sheet_pdf(template, out)
    return out


def read(path: Path) -> PdfReader:
    return PdfReader(str(path))


def fields_by_id(reader: PdfReader) -> dict[str, dict]:
    fields = reader.get_fields() or {}
    return {name: f for name, f in fields.items()}


def field_raw(reader: PdfReader, field_id: str) -> dict:
    for page in reader.pages:
        for annot in page.get("/Annots") or []:
            annot = annot.get_object()
            if str(annot.get("/T")) == field_id:
                return annot
    raise AssertionError(f"form field {field_id!r} not found in the PDF")


# ── 4.1 pages and static rendering ─────────────────────────────────────────


class TestPagesAndStatic:
    def test_page_count_order_and_size(self, tmp_path):
        t = make_template(
            orientation=SheetOrientation.PORTRAIT,
            page_one=[],
            page_two=[make_field("a" * 32, FieldType.HEADING, label="ОСН")],
            page_three=[],
        )
        reader = read(generate(tmp_path, t))
        assert len(reader.pages) == 3
        for page in reader.pages:
            box = (page.mediabox.left, page.mediabox.bottom,
                   page.mediabox.right, page.mediabox.top)
            assert tuple(round(v, 2) for v in box) == PORTRAIT_MEDIABOX

    def test_landscape_page_size(self, tmp_path):
        t = make_template(orientation=SheetOrientation.LANDSCAPE, page=[])
        reader = read(generate(tmp_path, t))
        box = (reader.pages[0].mediabox.left, reader.pages[0].mediabox.bottom,
               reader.pages[0].mediabox.right, reader.pages[0].mediabox.top)
        assert tuple(round(v, 2) for v in box) == LANDSCAPE_MEDIABOX

    def test_static_text_is_extracted(self, tmp_path):
        t = make_template(
            page=[
                make_field("h" * 32, FieldType.HEADING, label="ПЕРСОНАЖ", font_size=18.0),
                make_field("s" * 32, FieldType.STATIC_TEXT, label="Статус: активен", font_size=11.0),
                make_field("l" * 32, FieldType.SHORT_TEXT, label="Имя", x=60.0, y=300.0),
                make_field("p" * 32, FieldType.PORTRAIT, x=480.0, y=100.0, w=120.0, h=150.0, label=""),
            ],
        )
        reader = read(generate(tmp_path, t))
        text = reader.pages[0].extract_text()
        assert "ПЕРСОНАЖ" in text
        assert "Статус: активен" in text
        assert "Имя" in text          # label above the fillable box
        assert "Портрет" in text      # portrait placeholder

    def test_no_form_fields_for_static_page(self, tmp_path):
        t = make_template(
            page=[
                make_field("h" * 32, FieldType.HEADING, label="Заголовок"),
                make_field("p" * 32, FieldType.PORTRAIT, x=480.0, y=100.0, w=120.0, h=150.0, label=""),
            ]
        )
        reader = read(generate(tmp_path, t))
        assert fields_by_id(reader) == {}


# ── 4.2 AcroForm fields ────────────────────────────────────────────────────


class TestFormFields:
    def test_short_text_field(self, tmp_path):
        fid = "1" * 32
        t = make_template(page=[make_field(fid, FieldType.SHORT_TEXT, default_value="Герой")])
        reader = read(generate(tmp_path, t))
        field = fields_by_id(reader)[fid]
        assert field["/FT"] == "/Tx"
        assert str(field["/V"]) == "Герой"

    def test_long_text_field_is_multiline(self, tmp_path):
        fid = "2" * 32
        t = make_template(page=[make_field(fid, FieldType.LONG_TEXT, h=80.0)])
        reader = read(generate(tmp_path, t))
        field = fields_by_id(reader)[fid]
        assert field["/FT"] == "/Tx"
        assert int(field["/Ff"]) & (1 << 12)  # multiline bit, set natively (D4.2)

    def test_number_field_has_js_validation(self, tmp_path):
        fid = "3" * 32
        t = make_template(page=[
            make_field(fid, FieldType.NUMBER, default_value="10", min_value=1, max_value=20)
        ])
        reader = read(generate(tmp_path, t))
        field = fields_by_id(reader)[fid]
        assert field["/FT"] == "/Tx"
        assert str(field["/V"]) == "10"
        action = field_raw(reader, fid)["/AA"]["/V"].get_object()
        assert action["/S"] == "/JavaScript"
        js = str(action["/JS"])
        assert "n<1" in js and "n>20" in js

    def test_date_field_has_format_hint(self, tmp_path):
        fid = "4" * 32
        t = make_template(page=[make_field(fid, FieldType.DATE)])
        reader = read(generate(tmp_path, t))
        assert str(field_raw(reader, fid)["/TU"]) == "ДД.ММ.ГГГГ"

    @pytest.mark.parametrize("checked", [True, False])
    def test_checkbox_initial_state(self, tmp_path, checked):
        fid = "c" * 32
        t = make_template(page=[
            make_field(fid, FieldType.CHECKBOX, w=20.0, h=20.0, initial_checked=checked)
        ])
        reader = read(generate(tmp_path, t))
        field = fields_by_id(reader)[fid]
        assert field["/FT"] == "/Btn"
        assert str(field["/V"]) == ("/Yes" if checked else "/Off")

    def test_dropdown_options_and_default(self, tmp_path):
        fid = "d" * 32
        t = make_template(page=[
            make_field(fid, FieldType.DROPDOWN, default_value="Маг",
                       options=["Воин", "Маг", "Разбойник"])
        ])
        reader = read(generate(tmp_path, t))
        field = fields_by_id(reader)[fid]
        assert field["/FT"] == "/Ch"
        assert list(field["/Opt"]) == ["Воин", "Маг", "Разбойник"]
        assert str(field["/V"]) == "Маг"

    def test_dropdown_without_default_has_no_value(self, tmp_path):
        fid = "e" * 32
        t = make_template(page=[
            make_field(fid, FieldType.DROPDOWN, options=["А", "Б"])
        ])
        reader = read(generate(tmp_path, t))
        raw = field_raw(reader, fid)
        assert "/V" not in raw
        assert "/DV" not in raw
        assert list(fields_by_id(reader)[fid]["/Opt"]) == ["А", "Б"]

    def test_field_names_are_stable_ids(self, tmp_path):
        ids = ["f" * 32, "0a" * 16]
        t = make_template(page=[
            make_field(ids[0], FieldType.SHORT_TEXT, label="Первое"),
            make_field(ids[1], FieldType.LONG_TEXT, label="Второе"),
        ])
        reader = read(generate(tmp_path, t))
        assert set(fields_by_id(reader)) == set(ids)


    def test_form_field_rect_matches_editor_geometry(self, tmp_path):
        fid = "r" * 32
        t = make_template(
            page=[make_field(fid, FieldType.SHORT_TEXT, x=100.5, y=200.25, w=250.0, h=30.0)]
        )
        page_h = LANDSCAPE_MEDIABOX[3]
        reader = read(generate(tmp_path, t))
        rect = [round(float(v), 2) for v in field_raw(reader, fid)["/Rect"]]
        # y flipped: y_pdf = page_h - y - h (design D4)
        assert rect == [100.5, round(page_h - 200.25 - 30.0, 2),
                        350.5, round(page_h - 200.25, 2)]


# ── 4.3 metadata, clipping, structure ──────────────────────────────────────


class TestMetadataAndClipping:
    def test_title_metadata_equals_template_name(self, tmp_path):
        t = make_template(page=[])
        t.name = "Мой лист"
        reader = read(generate(tmp_path, t))
        assert reader.metadata.title == "Мой лист"

    def test_written_file_is_a_pdf(self, tmp_path):
        t = make_template(page=[])
        out = generate(tmp_path, t)
        assert out.name == "Лист персонажа.pdf"
        assert out.read_bytes().startswith(b"%PDF")
        assert len(read(out).pages) == 1

    @pytest.mark.parametrize(
        "overrides",
        [
            dict(x=-250.0, y=-300.0, w=300.0, h=40.0),   # fully off-page
            dict(x=700.0, y=500.0, w=300.0, h=100.0),    # crosses two edges
            dict(x=0.0, y=0.0, w=842.0, h=596.0),        # slightly over each edge
        ],
        ids=["off-page", "crosses-edges", "over-edges"],
    )
    def test_out_of_bounds_content_is_clipped_not_an_error(self, tmp_path, overrides):
        t = make_template(
            page=[
                make_field("k" * 32, FieldType.SHORT_TEXT, label="За краем", **overrides),
                make_field("h" * 32, FieldType.HEADING, label="На месте", x=50.0, y=50.0),
            ]
        )
        reader = read(generate(tmp_path, t))
        assert len(reader.pages) == 1
        assert "На месте" in reader.pages[0].extract_text()

    def test_acroform_tree_structure(self, tmp_path):
        """Golden check on the AcroForm document tree (design risk D4)."""
        ids = ["g" * 32, "7" * 32, "9" * 32]
        t = make_template(page=[
            make_field(ids[0], FieldType.SHORT_TEXT, default_value="А"),
            make_field(ids[1], FieldType.CHECKBOX, w=20.0, h=20.0, initial_checked=True, label="Б"),
            make_field(ids[2], FieldType.NUMBER, label="В", min_value=0, max_value=99),
        ])
        reader = read(generate(tmp_path, t))
        catalog = reader.trailer["/Root"].get_object()
        acroform = catalog["/AcroForm"].get_object()
        assert bool(acroform.get("/NeedAppearances"))
        names = [str(f.get("/T")) for f in acroform["/Fields"]]
        assert set(names) == set(ids)
        # exactly the interactive fields appear in the form, one widget each
        assert len(names) == 3
        for f in acroform["/Fields"]:
            f = f.get_object()
            assert f["/FT"] in ("/Tx", "/Ch", "/Btn")
            assert f["/Type"] == "/Annot"
            assert f["/Subtype"] == "/Widget"
