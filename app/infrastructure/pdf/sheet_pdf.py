"""Character sheet → fillable A4 PDF (AcroForm) generator.

Pure synchronous function, no Qt (design D4): coordinates are converted
from the editor's top-left origin to PDF's bottom-left origin per page,
static elements are drawn with embedded DejaVu Sans (Cyrillic), and
fillable fields are legacy ``reportlab.pdfbase.pdfform`` patterns
(customized with ``/AA`` numeric validation and ``/TU`` hint per spike D4).
Field names are the stable field ids (spec «Стабильные имена полей формы»).
"""
from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib.colors import black, white
from reportlab.pdfbase import pdfmetrics, ttfonts
from reportlab.pdfbase.pdfdoc import PDFArray, PDFDictionary, PDFName, PDFString
from reportlab.pdfbase.pdfpattern import PDFPattern
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.pdfform import ButtonStream, getForm
from reportlab.pdfgen.canvas import Canvas

from app.domain.entities.character_sheet import SheetField, SheetTemplate
from app.domain.enums.field_type import INTERACTIVE_FIELDS, FieldType
from app.domain.enums.sheet_orientation import a4_size

#: candidate locations for the bundled TTFs, in priority order (frozen only);
#: mirrors the docs-dir convention in main_window._docs_dir — PyInstaller puts
#: ``datas`` under _MEIPASS (``_internal/`` on Win/Linux, ``Contents/Resources``
#: in the macOS .app), while the module file itself may be anywhere in the PYZ
def _fonts_dir() -> Path:
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent / "fonts"
    exe = Path(sys.executable).resolve()
    rel = Path("app") / "infrastructure" / "pdf" / "fonts"
    for base in (exe.parent.parent / "Resources", exe.parent.parent / "Frameworks",
                 exe.parent / "_internal", exe.parent):
        candidate = base / rel
        if candidate.is_dir():
            return candidate
    return exe.parent / "_internal" / rel  # fallback


REGULAR_TTF = _fonts_dir() / "DejaVuSans.ttf"
BOLD_TTF = _fonts_dir() / "DejaVuSans-Bold.ttf"
_REGULAR = "DejaVuSans"
_BOLD = "DejaVuSans-Bold"

#: gap between a field's label baseline and the top edge of its box, pt
_LABEL_GAP = 3.0
#: placeholder hint written as /TU for date fields
DATE_HINT = "ДД.ММ.ГГГГ"
#: default max length for text fields
_TEXT_MAX_LEN = 10000


def _register_fonts() -> None:
    """Embed DejaVu Sans (Regular + Bold) for the Cyrillic static text (D4.3)."""
    if _REGULAR not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(ttfonts.TTFont(_REGULAR, str(REGULAR_TTF)))
    if _BOLD not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(ttfonts.TTFont(_BOLD, str(BOLD_TTF)))


# ── page geometry ──────────────────────────────────────────────────────────


def _rect_in_pdf(f: SheetField, page_height: float) -> tuple[float, float, float, float]:
    """Editor rect (top-left origin) → PDF (bottom-left): x, y, w, h."""
    return f.x, page_height - f.y - f.h, f.w, f.h


# ── form-field patterns ────────────────────────────────────────────────────
# The stock pdfform patterns hard-code /F 4 /FT /Tx and carry no /AA, /TU or
# empty-/V variants (spike D4.2); these thin customizations are used instead.

_TEXT_PATTERN_BODY = [
    ' /DA (', ["fontname"], ' ', ["fontsize"], ' Tf 0 0 0 rg)\r\n'
    ' /DV ', ["value"], '\r\n'
    ' /F 4 /FT /Tx\r\n'
    '/MK << /BC [ 0 0 0 ] >>\r\n'
    ' /MaxLen ', ["maxlen"], '\r\n'
    ' /P ', ["page"], '\r\n'
    ' /Rect [', ["xmin"], " ", ["ymin"], " ", ["xmax"], " ", ["ymax"], '] \r\n'
    '/Subtype /Widget\r\n'
    ' /T ', ["title"], '\r\n'
    ' /Type /Annot\r\n',
]
_TEXT_PATTERN_TAIL = [
    ' /V ', ["value"], '\r\n'
    ' /Ff ', ["Flags"], '\r\n'
    '>>',
]


def _number_validation_js(min_value: int, max_value: int) -> str:
    return (
        "var v=event.target.valueAsString; "
        "if(v.trim()!==''){var n=parseFloat(v); "
        f"if(isNaN(n)||n<{min_value}||n>{max_value}){{event.validate=false;}}"
    )


def _validate_action(code: str) -> PDFDictionary:
    action = PDFDictionary()
    action["S"] = "/JavaScript"
    action["JS"] = PDFString(code)
    return action


def _text_field(
    canvas,
    form,
    *,
    name: str,
    value: str,
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
    page,
    font_size: float,
    multiline: bool = False,
    max_len: int = _TEXT_MAX_LEN,
    validate_js: str | None = None,
    hint: str | None = None,
) -> None:
    # optional keys must sit inside the field dictionary, i.e. after `<<`
    pattern = ['<<']
    if validate_js is not None:
        pattern += [' /AA << /V ', ["aa"], ' >>\r\n']
    if hint is not None:
        pattern += [' /TU ', ["tu"], '\r\n']
    pattern += _TEXT_PATTERN_BODY
    pattern += _TEXT_PATTERN_TAIL

    flags = (1 << 12) if multiline else 0  # AcroForm multiline bit (D4.2)
    kwargs = dict(
        value=PDFString(value),
        maxlen=max_len,
        page=page,
        title=PDFString(name),
        xmin=xmin,
        ymin=ymin,
        xmax=xmax,
        ymax=ymax,
        fontname=PDFName("Helv"),  # standard 14, resolved by the viewer (D4.3)
        fontsize=font_size,
        Flags=flags,
    )
    if validate_js is not None:
        kwargs["aa"] = _validate_action(validate_js)
    if hint is not None:
        kwargs["tu"] = PDFString(hint)
    field = PDFPattern(pattern, **kwargs)
    form.fields.append(field)
    canvas._addAnnotation(field)


_SELECT_PATTERN_BASE = [
    '<< '
    ' /DA (', ["fontname"], ' ', ["fontsize"], ' Tf 0 0 0 rg)\r\n',
    ' /F 4\r\n'
    ' /FT /Ch\r\n'
    ' /MK << /BC [ 0 0 0 ] /BG [ 1 1 1 ] >>\r\n'
    ' /Opt ', ["Options"], '\r\n'
    ' /P ', ["Page"], '\r\n',
    '/Rect [', ["xmin"], " ", ["ymin"], " ", ["xmax"], " ", ["ymax"], '] \r\n',
    '/Subtype /Widget\r\n'
    ' /T ', ["Name"], '\r\n'
    ' /Type /Annot\r\n',
]
_SELECT_PATTERN_WITH_VALUE = [
    ' /DV ', ["Selected"], '\r\n'
    ' /V ', ["Selected"], '\r\n'
    '>>',
]
_SELECT_PATTERN_EMPTY_VALUE = ['>>']


def _select_field(
    canvas,
    form,
    *,
    name: str,
    value: str,
    options: list[str],
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
    page,
    font_size: float,
) -> None:
    # /DV+/V are written only for a non-empty initial value: an empty value
    # is not one of the /Opt entries, so both keys are omitted in that case
    pattern = list(_SELECT_PATTERN_BASE)
    if value:
        pattern += _SELECT_PATTERN_WITH_VALUE
    else:
        pattern += _SELECT_PATTERN_EMPTY_VALUE

    kwargs = dict(
        Options=PDFArray([PDFString(o) for o in options]),
        Page=page,
        Name=PDFString(name),
        xmin=xmin,
        ymin=ymin,
        xmax=xmax,
        ymax=ymax,
        fontname=PDFName("Helv"),
        fontsize=font_size,
    )
    if value:
        kwargs["Selected"] = PDFString(value)
    field = PDFPattern(pattern, **kwargs)
    form.fields.append(field)
    canvas._addAnnotation(field)


_CHECK_STREAMS = {
    "APDOff": "0.749 g 0 0 %(w)s %(h)s re f\r\n",
    "APDYes": (
        "0.749 g 0 0 %(w)s %(h)s re f q 1 1 %(w)s %(h)s re W n "
        "BT /ZaDb %(fs)s Tf 0 g 1 0 0 1 %(dx)s %(dy)s Tm (4) Tj ET\r\n"
    ),
    "APNYes": (
        "q 1 1 %(w)s %(h)s re W n BT /ZaDb %(fs)s Tf 0 g "
        "1 0 0 1 %(dx)s %(dy)s Tm (4) Tj ET Q\r\n"
    ),
}


def _check_metrics(width: float, height: float) -> dict:
    # proportions ported from reportlab's ZapfDingbats "4" (checkmark) layout
    return {
        "w": width,
        "h": height,
        "fs": (11.3086 / 14.907) * height,
        "dx": (3.6017 / 16.7704) * width,
        "dy": (3.3881 / 14.907) * height,
    }


def _button_field(
    canvas,
    form,
    *,
    name: str,
    checked: bool,
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
    page,
) -> None:
    """Checkbox built directly (the stock ButtonField sets ymax from the
    width — reportlab bug bypassed per spike D4.4)."""
    width = xmax - xmin
    height = ymax - ymin
    m = _check_metrics(width, height)
    field = PDFPattern(
        [
            '<< '
            '/AP << /D << /Off ', ["APDOff"], '\r\n'
            '/Yes ', ["APDYes"], '\r\n'
            '>> /N << /Yes ', ["APNYes"], '\r\n'
            '>> >>\r\n'
            ' /AS ', ["Value"], '\r\n'
            ' /DA (/ZaDb 0 Tf 0 g)\r\n'
            '/DV ', ["Value"], '\r\n'
            '/F 4 '
            '/FT /Btn '
            '/H /T '
            '/MK << /AC (\\376\\377) /CA (4) /RC (\\376\\377) >> \r\n'
            '/P ', ["Page"], '\r\n'
            '/Rect [', ["xmin"], " ", ["ymin"], " ", ["xmax"], " ", ["ymax"], '] \r\n'
            '/Subtype /Widget '
            '/T ', ["Name"], '\r\n'
            '/Type /Annot '
            '/V ', ["Value"], '\r\n'
            ' >>',
        ],
        Name=PDFString(name),
        Value=PDFName("Yes" if checked else "Off"),
        Page=page,
        xmin=xmin,
        ymin=ymin,
        xmax=xmax,
        ymax=ymax,
        APDOff=ButtonStream(_CHECK_STREAMS["APDOff"] % m, width=width, height=height),
        APDYes=ButtonStream(_CHECK_STREAMS["APDYes"] % m, width=width, height=height),
        APNYes=ButtonStream(_CHECK_STREAMS["APNYes"] % m, width=width, height=height),
    )
    form.fields.append(field)
    canvas._addAnnotation(field)


# ── static rendering ───────────────────────────────────────────────────────


def _draw_text_block(
    canvas,
    text: str,
    x: float,
    top_y: float,
    font_size: float,
    font: str,
    lines: bool = False,
) -> None:
    """Draw text with its first baseline at ``top_y - font_size`` (PDF y up).

    ``lines`` splits on line breaks; otherwise the text is drawn as-is.
    """
    canvas.setFont(font, font_size)
    leading = font_size * 1.2
    for i, line in enumerate(text.split("\n") if lines else [text]):
        canvas.drawString(x, top_y - font_size - i * leading, line)


def _draw_portrait(canvas, x: float, bottom_y: float, w: float, h: float) -> None:
    label = "Портрет"
    canvas.setFont(_REGULAR, 12.0)
    text_w = stringWidth(label, _REGULAR, 12.0)
    canvas.drawString(x + (w - text_w) / 2, bottom_y + h / 2 - 6, label)


def _draw_field(canvas, f: SheetField, page_height: float) -> None:
    """Static appearance of one field (boxes, labels, static text).

    Text drawn outside the MediaBox is clipped at render time, so fields at
    or beyond the page edge never break the export.
    """
    x, bottom_y, w, h = _rect_in_pdf(f, page_height)
    top_y = page_height - f.y

    if f.type in INTERACTIVE_FIELDS:
        canvas.setStrokeColor(black)
        canvas.setFillColor(white)
        canvas.rect(x, bottom_y, w, h, fill=1, stroke=1)
        if f.label:
            # label sits directly above the box (spec «Геометрия, подписи и шрифт»)
            _draw_text_block(canvas, f.label, x, top_y - _LABEL_GAP, f.font_size, _REGULAR)
    elif f.type is FieldType.PORTRAIT:
        canvas.setStrokeColor(black)
        canvas.setFillColor(white)
        canvas.rect(x, bottom_y, w, h, fill=1, stroke=1)
        _draw_portrait(canvas, x, bottom_y, w, h)
    else:  # HEADING, STATIC_TEXT
        font = _BOLD if f.type is FieldType.HEADING else _REGULAR
        _draw_text_block(canvas, f.label, x, top_y, f.font_size, font, lines=True)


# ── public API ─────────────────────────────────────────────────────────────


def generate_sheet_pdf(template: SheetTemplate, path: Path | str) -> Path:
    """Render ``template`` into a fillable A4 PDF at ``path`` (returns it).

    Content leaving a page boundary is clipped, never an error (spec
    «Обрезка за пределами страницы»).
    """
    path = Path(path)
    _register_fonts()

    canvas = Canvas(str(path))
    canvas.setTitle(template.name)  # metadata title = template name
    page_w, page_h = a4_size(template.orientation)
    form = getForm(canvas)
    form.needAppearances = "true"  # let viewers rebuild field appearances

    for page in template.pages:
        canvas.setPageSize((page_w, page_h))
        # start the page (a full-page white rect is invisible but forces
        # the page object to exist so form annotations can attach to it)
        canvas.setFillColor(white)
        canvas.rect(0, 0, page_w, page_h, fill=1, stroke=0)

        for f in page.fields:
            _draw_field(canvas, f, page_h)

        if page.fields:
            page_ref = canvas._doc.thisPageRef()
            for f in page.fields:
                _add_form_field(canvas, form, f, page_h, page_ref)

        canvas.showPage()
    canvas.save()
    return path


def _add_form_field(canvas, form, f: SheetField, page_height: float, page_ref) -> None:
    x, bottom_y, w, h = _rect_in_pdf(f, page_height)
    rect = dict(xmin=x, ymin=bottom_y, xmax=x + w, ymax=bottom_y + h, page=page_ref)

    if f.type is FieldType.NUMBER:
        _text_field(
            canvas, form, name=f.id, value=f.default_value, font_size=f.font_size,
            validate_js=_number_validation_js(f.min_value, f.max_value), **rect,
        )
    elif f.type in (FieldType.SHORT_TEXT, FieldType.LONG_TEXT, FieldType.DATE):
        _text_field(
            canvas, form, name=f.id, value=f.default_value, font_size=f.font_size,
            multiline=f.type is FieldType.LONG_TEXT,
            hint=DATE_HINT if f.type is FieldType.DATE else None, **rect,
        )
    elif f.type is FieldType.DROPDOWN:
        _select_field(
            canvas, form, name=f.id, value=f.default_value,
            options=list(f.options), font_size=f.font_size, **rect,
        )
    elif f.type is FieldType.CHECKBOX:
        _button_field(
            canvas, form, name=f.id, checked=f.initial_checked, **rect,
        )
