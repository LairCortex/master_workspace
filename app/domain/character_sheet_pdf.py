"""Write a fillable PDF from a character-sheet template (no Qt)."""
from __future__ import annotations

import os
import tempfile
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Mapping

from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import acroform as rl_acroform
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.acroform import PDFFromString
from reportlab.pdfbase.pdfdoc import PDFString
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from app.domain.entities.character_sheet import SheetField, SheetTemplate
from app.domain.enums.field_type import FieldType

_DEJAVU = (
    Path(__file__).resolve().parents[1]
    / "presentation"
    / "views"
    / "character_sheet"
    / "fonts"
    / "DejaVuSans.ttf"
)
_FONT = "DejaVuSans"
_WIDGET_MAXLEN = 4096
# The canvas insets label text by 2 pt and wraps it inside the frame; the PDF
# mirrors both so an exported label breaks in the same places it does in Design.
_TEXT_INSET = 2.0
_LINE_SPACING = 1.2
_DRAWING = frozenset(
    {FieldType.LABEL, FieldType.RECT, FieldType.LINE, FieldType.IMAGE}
)
_WIDGETS = frozenset(
    {
        FieldType.TEXT,
        FieldType.TEXTAREA,
        FieldType.CHECKBOX,
        FieldType.NUMBER,
        FieldType.DROPDOWN,
    }
)


def _ensure_font() -> None:
    if _FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_FONT, str(_DEJAVU)))


def _y_pdf(page_h: float, field: SheetField) -> float:
    return page_h - field.y - field.h


def _wrap_line(text: str, font_size: float, width: float) -> list[str]:
    """Greedy word wrap with a character-level break for an over-long word."""
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        candidate = f"{current} {word}" if current else word
        if pdfmetrics.stringWidth(candidate, _FONT, font_size) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        while pdfmetrics.stringWidth(word, _FONT, font_size) > width and len(word) > 1:
            cut = len(word)
            while (
                cut > 1
                and pdfmetrics.stringWidth(word[:cut], _FONT, font_size) > width
            ):
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    lines.append(current)
    return lines


def wrap_text(text: str, font_size: float, width: float) -> list[str]:
    """Label text broken into the lines the frame width allows."""
    if width <= 0:
        return []
    lines: list[str] = []
    for paragraph in text.split("\n"):
        lines.extend(_wrap_line(paragraph, font_size, width))
    return lines


def _draw_label(canvas: Canvas, field: SheetField, x: float, y: float) -> None:
    size = field.font_size
    step = size * _LINE_SPACING
    bottom = y + _TEXT_INSET
    baseline = y + field.h - _TEXT_INSET - size
    canvas.setFont(_FONT, size)
    for line in wrap_text(field.content or "", size, field.w - 2 * _TEXT_INSET):
        if baseline < bottom - 0.01:
            break  # the frame is full: the rest is clipped, as on the canvas
        canvas.drawString(x + _TEXT_INSET, baseline, line)
        baseline -= step


def _draw_drawing(
    canvas: Canvas,
    field: SheetField,
    page_h: float,
    images: Mapping[int, bytes],
) -> None:
    x, y, w, h = field.x, _y_pdf(page_h, field), field.w, field.h
    if field.type is FieldType.LABEL:
        canvas.saveState()
        path = canvas.beginPath()
        path.rect(x, y, w, h)
        canvas.clipPath(path, stroke=0, fill=0)
        _draw_label(canvas, field, x, y)
        canvas.restoreState()
        return
    if field.type is FieldType.RECT:
        canvas.rect(x, y, w, h, stroke=1, fill=0)
        return
    if field.type is FieldType.LINE:
        if w > h:
            mid = y + h / 2.0
            canvas.line(x, mid, x + w, mid)
        else:
            mid = x + w / 2.0
            canvas.line(mid, y, mid, y + h)
        return
    data = images.get(field.image_id) if field.image_id is not None else None
    if data:
        try:
            canvas.drawImage(
                ImageReader(BytesIO(data)),
                x,
                y,
                width=w,
                height=h,
                mask="auto",
            )
            return
        except Exception:
            pass
    canvas.rect(x, y, w, h, stroke=1, fill=0)


def _latin1_escPDF(s):
    if isinstance(s, str):
        s = s.encode("latin-1", "replace").decode("latin-1")
    return _ORIG_ESCPDF(s)


_ORIG_ESCPDF = rl_acroform.escPDF


def _last_annot(canvas: Canvas):
    return canvas._doc.idToObject[f"Annot.NUMBER{canvas._annotationCount}"]


def _set_string_value(canvas: Canvas, value: str) -> None:
    annot = _last_annot(canvas)
    stored = PDFString(value)
    annot.dict["V"] = stored
    annot.dict["DV"] = stored


def _draw_widget(canvas: Canvas, field: SheetField, page_h: float) -> None:
    x, y, w, h = field.x, _y_pdf(page_h, field), field.w, field.h
    form = canvas.acroForm
    fs = field.font_size
    if field.type in (FieldType.TEXT, FieldType.NUMBER, FieldType.TEXTAREA):
        flags = "multiline" if field.type is FieldType.TEXTAREA else ""
        form.textfield(
            name=field.id,
            value=field.content or "",
            x=x,
            y=y,
            width=w,
            height=h,
            maxlen=_WIDGET_MAXLEN,
            fontSize=fs,
            fieldFlags=flags,
        )
        _set_string_value(canvas, field.content or "")
        return
    if field.type is FieldType.CHECKBOX:
        form.checkbox(
            name=field.id,
            checked=(field.content == "true"),
            x=x,
            y=y,
            size=min(w, h),
            fieldFlags="",
        )
        return
    options = list(field.options)
    selected = field.content if field.content in options else ""
    # A dropdown without options is still a form field (spec «Виджеты AcroForm»),
    # offering the single blank entry. reportlab 5.0.1 raises on a falsy scalar
    # ``value``, so the blank case is passed as a one-element list.
    if options:
        choice_options = options
        choice_value = selected or options[0]
    else:
        choice_options = [""]
        choice_value = [""]
    form.choice(
        name=field.id,
        options=choice_options,
        value=choice_value,
        x=x,
        y=y,
        width=w,
        height=h,
        fontSize=fs,
        fieldFlags="combo",
    )
    if not selected:
        annot = _last_annot(canvas)
        annot.dict["V"] = PDFString("")
        annot.dict["DV"] = PDFString("")
        annot.dict.pop("I", None)
    else:
        _set_string_value(canvas, selected)


def _render(template: SheetTemplate, dest: BinaryIO, images: Mapping[int, bytes]) -> None:
    _ensure_font()
    page_w, page_h = template.page_size
    canvas = Canvas(dest, pagesize=(page_w, page_h))
    rl_acroform.escPDF = _latin1_escPDF
    try:
        for page in template.pages:
            for field in page.fields:
                if field.type in _DRAWING:
                    _draw_drawing(canvas, field, page_h, images)
            for field in page.fields:
                if field.type in _WIDGETS:
                    _draw_widget(canvas, field, page_h)
            canvas.showPage()
        if getattr(canvas, "AcroForm", None) is not None:
            canvas.AcroForm.extras["NeedAppearances"] = PDFFromString("true")
        canvas.save()
    finally:
        rl_acroform.escPDF = _ORIG_ESCPDF


def write_sheet_pdf(
    template: SheetTemplate,
    dest: Path | BinaryIO,
    images: Mapping[int, bytes],
) -> None:
    """Write one A4 PDF page per template page; widgets are AcroForm fields."""
    if not isinstance(dest, Path):
        _render(template, dest, images)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(suffix=".pdf", dir=str(dest.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            _render(template, handle, images)
        tmp_path.replace(dest)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
