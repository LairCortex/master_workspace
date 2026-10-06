"""Markdown documents as render-ready HTML (doc-viewer rendering pass).

The documentation and the Changelog used to show their raw markup; this is
the single converter turning a Markdown source into the HTML a RichText
``Text`` shows. The engine is Qt's own Markdown stack (md4c, already shipped
inside PySide6): ``QTextDocument.setMarkdown`` parses, ``toHtml`` prints —
no third-party dependency, and the generator and the reading surface (QML's
``Text.RichText`` runs on the same rich-text engine) can never disagree on
the supported subset.

The print keeps everything the engine produced — the heading hierarchy rides
relative font sizes, bold rides ``font-weight``, code rides the monospace
family — except one token: Qt embeds its hardcoded link colour
(``color:#0000ff``) into every anchor, and an embedded colour would mute the
island's themed ``linkColor`` (blue on the dark surface reads as nothing).
Colour is presentation, so the converter strips it and lets the surface
paint it; family and sizes are the document's own typography and stay.
"""
from __future__ import annotations

import re

from PySide6.QtGui import QTextDocument

#: The one style token the converter overrides — Qt's fixed anchor colour,
#: emitted verbatim by ``QTextDocument.toHtml`` into every link's span.
_QT_LINK_COLOR = re.compile(r"\s*color:#0000ff;", re.IGNORECASE)


def build_doc_html(markdown_text: str) -> str:
    """Markdown source -> rich-text HTML (Qt md4c, zero new dependencies).

    The result is a full HTML document string (Qt's print format, the
    ``qrichtext`` meta included) — the shape ``Text.RichText`` consumes
    natively. Raw HTML typed into the source stays literal text: the
    Markdown importer escapes it, so a document cannot smuggle markup."""
    document = QTextDocument()
    document.setMarkdown(markdown_text)
    return _QT_LINK_COLOR.sub("", document.toHtml())
