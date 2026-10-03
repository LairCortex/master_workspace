#!/usr/bin/env python3
"""Vendor the Lucide icon set and regenerate the QML path-data module.

Source of truth: https://github.com/lucide-icons/lucide (ISC license). The
raw SVG files are vendored verbatim under
``app/presentation/qml/nri/components/icons/`` (with the upstream LICENSE
next to them); ``icons.js`` next to the library components is GENERATED from
those files by this script and must never be edited by hand.

Why generated path data: Qt Quick renders the glyphs through
``Shape { ShapePath { PathSvg } }`` (the ``ThemeIcon`` component), and Qt's
``PathSvg`` understands only the ``M``/``L``/``C``/``Z`` commands — so the
SVG ``A``/``a`` arc commands and the ``circle``/``rect``/``line`` primitives
are expanded here into cubic Bézier segments at vendoring time (the
``QSvgRenderer``-free QML side then needs no SVG runtime at all).

Usage:

    python scripts/vendor_lucide.py           # regenerate icons.js from the vendored SVGs
    python scripts/vendor_lucide.py --fetch   # re-download the SVGs first (network)
"""
from __future__ import annotations

import math
import re
import sys
import urllib.request
from pathlib import Path

# The commit of lucide-icons/lucide (branch main) the vendored files came
# from — recorded so a re-fetch is reproducible and auditable.
UPSTREAM_COMMIT = "5a92b9ba262de5bf10e864219883267672c05db8"
UPSTREAM_URL = (
    "https://raw.githubusercontent.com/lucide-icons/lucide/"
    f"{UPSTREAM_COMMIT}/icons/{{name}}.svg"
)

# Every icon the app ships; ``ThemeIcon`` keys off these names.
ICON_NAMES = (
    "arrow-down",
    "arrow-up",
    "bring-to-front",
    "building",
    "calendar-clock",
    "calendar-days",
    "chevron-down",
    "chevron-left",
    "chevron-right",
    "circle-stop",
    "clipboard-paste",
    "copy",
    "copy-plus",
    "crosshair",
    "download",
    "eraser",
    "eye",
    "file-down",
    "file-plus",
    "folder-open",
    "folder-search",
    "hash",
    "image",
    "import",
    "link",
    "list",
    "map-pin",
    "minus",
    "mouse-pointer",
    "pencil",
    "pin",
    "play",
    "plug-zap",
    "plus",
    "redo-2",
    "refresh-ccw",
    "save",
    "scroll-text",
    "search",
    "search-check",
    "send-to-back",
    "sparkles",
    "square",
    "square-check",
    "sword",
    # Upstream retired the «text-select»/«align-left» names on this commit:
    # the text-field caret glyph ships as «text-cursor-input», the stacked
    # text lines as «text-align-start» — the same drawings, the live names.
    "text-align-start",
    "text-cursor-input",
    "trash",
    "type",
    "undo-2",
    "unlink",
    "user-minus",
    "user-plus",
    "user-round",
    "x",
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ICONS_DIR = REPO_ROOT / "app" / "presentation" / "qml" / "nri" / "components" / "icons"
ICONS_JS = ICONS_DIR.parent / "icons.js"

# The Lucide grid: every upstream icon draws on the 24×24 viewBox;
# ThemeIcon scales that grid. Circle-to-Bézier handle constant: 4/3·tan(π/8).
KAPPA = 0.5522847498307936

_NUM = r"-?\d*\.?\d+"
_COMMAND_RE = re.compile(r"([MmLlHhVvCcSsQqTtAaZz]|" + _NUM + r")")
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
_UNSUPPORTED_COMMANDS = frozenset("SsQqTt")


def _fmt(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _number_pairs(values: list[float]) -> list[tuple[float, float]]:
    return [(values[i], values[i + 1]) for i in range(0, len(values), 2)]


def _arc_to_cubics(
    x1: float,
    y1: float,
    rx: float,
    ry: float,
    phi_deg: float,
    large_arc: float,
    sweep: float,
    x2: float,
    y2: float,
) -> list[tuple[tuple[float, float], tuple[float, float], tuple[float, float]]]:
    """SVG F.6.5/F.6.6: endpoint parameterisation → cubic Bézier segments.

    Returns the ``(c1, c2, end)`` triples that, chained from ``(x1, y1)``,
    trace the arc; the arc commands the vendored icons carry are elliptical
    and small, but the conversion is the general one (including the radius
    correction and the 90° chunking)."""
    if (x1, y1) == (x2, y2):
        return []
    phi = math.radians(phi_deg)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p = cos_phi * dx + sin_phi * dy
    y1p = -sin_phi * dx + cos_phi * dy
    rx, ry = abs(rx), abs(ry)
    radius_check = (x1p / rx) ** 2 + (y1p / ry) ** 2
    if radius_check > 1.0:  # F.6.5.2: scale both radii so an arc exists
        scale = math.sqrt(radius_check)
        rx, ry = rx * scale, ry * scale
    num = max(
        0.0, rx**2 * ry**2 - rx**2 * y1p**2 - ry**2 * x1p**2
    )
    den = rx**2 * y1p**2 + ry**2 * x1p**2
    factor = (math.sqrt(num / den) if den else 0.0) * (1.0 if large_arc != sweep else -1.0)
    cxp = factor * (rx * y1p / ry)
    cyp = factor * (-(ry * x1p / rx))
    cx = cos_phi * cxp - sin_phi * cyp + (x1 + x2) / 2.0
    cy = sin_phi * cxp + cos_phi * cyp + (y1 + y2) / 2.0

    def _point(t: float) -> tuple[float, float]:
        ux, uy = rx * math.cos(t), ry * math.sin(t)
        return (cos_phi * ux - sin_phi * uy + cx, sin_phi * ux + cos_phi * uy + cy)

    def _angle(u: tuple[float, float], v: tuple[float, float]) -> float:
        sign = -1.0 if u[0] * v[1] - u[1] * v[0] < 0 else 1.0
        dot = u[0] * v[0] + u[1] * v[1]
        norms = math.sqrt(u[0] ** 2 + u[1] ** 2) * math.sqrt(v[0] ** 2 + v[1] ** 2)
        return sign * math.acos(max(-1.0, min(1.0, dot / norms if norms else 0.0)))

    theta1 = _angle((1.0, 0.0), ((x1p - cxp) / rx, (y1p - cyp) / ry))
    delta = _angle(
        ((x1p - cxp) / rx, (y1p - cyp) / ry), ((-x1p - cxp) / rx, (-y1p - cyp) / ry)
    )
    if sweep == 0 and delta > 0:
        delta -= 2.0 * math.pi
    elif sweep == 1 and delta < 0:
        delta += 2.0 * math.pi
    segments: list[tuple[tuple[float, float], tuple[float, float], tuple[float, float]]] = []
    remaining = delta
    t = theta1
    while abs(remaining) > 1e-9:
        chunk = remaining if abs(remaining) <= math.pi / 2 else math.copysign(math.pi / 2, remaining)
        alpha = 4.0 / 3.0 * math.tan(chunk / 4.0)
        p0, p3 = _point(t), _point(t + chunk)
        d0 = (-rx * math.sin(t), ry * math.cos(t))
        d3 = (-rx * math.sin(t + chunk), ry * math.cos(t + chunk))
        c1 = (p0[0] + alpha * d0[0], p0[1] + alpha * d0[1])
        c2 = (p3[0] - alpha * d3[0], p3[1] - alpha * d3[1])
        segments.append((c1, c2, p3))
        t += chunk
        remaining -= chunk
    return segments


def _circle_to_cubics(cx: float, cy: float, r: float) -> str:
    k = KAPPA * r
    parts = [f"M{_fmt(cx - r)} {_fmt(cy)}"]
    # Four counter-clockwise quarter-circle cubics starting at the left point.
    for start_x, start_y, c1x, c1y, c2x, c2y, end_x, end_y in (
        (cx - r, cy, cx - r, cy - k, cx - k, cy - r, cx, cy - r),
        (cx, cy - r, cx + k, cy - r, cx + r, cy - k, cx + r, cy),
        (cx + r, cy, cx + r, cy + k, cx + k, cy + r, cx, cy + r),
        (cx, cy + r, cx - k, cy + r, cx - r, cy + k, cx - r, cy),
    ):
        parts.append(
            f"C{_fmt(c1x)} {_fmt(c1y)} {_fmt(c2x)} {_fmt(c2y)} {_fmt(end_x)} {_fmt(end_y)}"
        )
    parts.append("Z")
    return "".join(parts)


def _rect_to_path(x: float, y: float, width: float, height: float, rx: float) -> str:
    if rx <= 0:
        return (
            f"M{_fmt(x)} {_fmt(y)}H{_fmt(x + width)}V{_fmt(y + height)}"
            f"H{_fmt(x)}Z"
        )
    rx = min(rx, width / 2.0, height / 2.0)
    k = KAPPA * rx
    f = _fmt
    return "".join((
        f"M{f(x + rx)} {f(y)}",
        f"H{f(x + width - rx)}",
        f"C{f(x + width - rx + k)} {f(y)} {f(x + width)} {f(y + rx - k)} {f(x + width)} {f(y + rx)}",
        f"V{f(y + height - rx)}",
        f"C{f(x + width)} {f(y + height - rx + k)} {f(x + width - rx + k)} {f(y + height)} {f(x + width - rx)} {f(y + height)}",
        f"H{f(x + rx)}",
        f"C{f(x + rx - k)} {f(y + height)} {f(x)} {f(y + height - rx + k)} {f(x)} {f(y + height - rx)}",
        f"V{f(y + rx)}",
        f"C{f(x)} {f(y + rx - k)} {f(x + rx - k)} {f(y)} {f(x + rx)} {f(y)}",
        "Z",
    ))


_SEG_RE = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])([^MmLlHhVvCcSsQqTtAaZz]*)")
_FLOAT_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_FLAG_RE = re.compile(r"[01]")


class _ArgReader:
    """Cursor over one command's argument string.

    Arcs need more than ``float()`` per token: the large-arc and sweep flags
    are single digits that SVG lets the following coordinate glue straight
    onto (``"a2 2 0 0021 5.172"`` — flags ``0``/``0``, endpoint ``(21, 5.172)``),
    so every parameter is consumed with its own rule."""

    def __init__(self, text: str) -> None:
        self._s = text
        self._i = 0

    def _skip_separators(self) -> None:
        while self._i < len(self._s) and self._s[self._i] in " ,\t\r\n":
            self._i += 1

    def at_end(self) -> bool:
        self._skip_separators()
        return self._i >= len(self._s)

    def number(self) -> float:
        self._skip_separators()
        match = _FLOAT_RE.match(self._s, self._i)
        if match is None:
            raise ValueError(f"expected a number at {self._s[self._i:self._i + 12]!r}")
        self._i = match.end()
        return float(match.group())

    def flag(self) -> float:
        self._skip_separators()
        match = _FLAG_RE.match(self._s, self._i)
        if match is None:
            raise ValueError(f"expected an arc flag at {self._s[self._i:self._i + 12]!r}")
        self._i = match.end()
        return float(match.group())


def _normalize_path(d: str) -> str:
    """Rewrite an SVG path as absolute ``M``/``L``/``C``/``Z`` commands."""
    out: list[str] = []
    cx = cy = 0.0  # current point
    sx = sy = 0.0  # subpath start
    for command, raw in _SEG_RE.findall(d):
        if command in _UNSUPPORTED_COMMANDS:
            raise ValueError(f"unsupported SVG path command {command!r} in {d!r}")
        args = _ArgReader(raw)
        if command == "M":
            first = True
            while not args.at_end():
                x, y = args.number(), args.number()
                out.append(("M" if first else "L") + f"{_fmt(x)} {_fmt(y)}")
                first = False
                cx, cy = x, y
            sx, sy = cx, cy
        elif command == "m":
            first = True
            while not args.at_end():
                cx, cy = cx + args.number(), cy + args.number()
                out.append(("M" if first else "L") + f"{_fmt(cx)} {_fmt(cy)}")
                first = False
            sx, sy = cx, cy
        elif command == "L":
            while not args.at_end():
                cx, cy = args.number(), args.number()
                out.append(f"L{_fmt(cx)} {_fmt(cy)}")
        elif command == "l":
            while not args.at_end():
                cx, cy = cx + args.number(), cy + args.number()
                out.append(f"L{_fmt(cx)} {_fmt(cy)}")
        elif command == "H":
            while not args.at_end():
                cx = args.number()
                out.append(f"L{_fmt(cx)} {_fmt(cy)}")
        elif command == "h":
            while not args.at_end():
                cx += args.number()
                out.append(f"L{_fmt(cx)} {_fmt(cy)}")
        elif command == "V":
            while not args.at_end():
                cy = args.number()
                out.append(f"L{_fmt(cx)} {_fmt(cy)}")
        elif command == "v":
            while not args.at_end():
                cy += args.number()
                out.append(f"L{_fmt(cx)} {_fmt(cy)}")
        elif command == "C":
            while not args.at_end():
                k1x, k1y, k2x, k2y, x, y = (args.number() for _ in range(6))
                out.append(
                    f"C{_fmt(k1x)} {_fmt(k1y)} {_fmt(k2x)} {_fmt(k2y)} {_fmt(x)} {_fmt(y)}"
                )
                cx, cy = x, y
        elif command == "c":
            while not args.at_end():
                k1x, k1y, k2x, k2y, dx, dy = (args.number() for _ in range(6))
                out.append(
                    "C"
                    + " ".join(
                        _fmt(v)
                        for v in (
                            cx + k1x, cy + k1y, cx + k2x, cy + k2y, cx + dx, cy + dy
                        )
                    )
                )
                cx, cy = cx + dx, cy + dy
        elif command in {"A", "a"}:
            while not args.at_end():
                rx, ry, rot = args.number(), args.number(), args.number()
                large, sweep = args.flag(), args.flag()
                x2, y2 = args.number(), args.number()
                if command == "a":
                    x2, y2 = cx + x2, cy + y2
                for c1, c2, end in _arc_to_cubics(
                    cx, cy, rx, ry, rot, large, sweep, x2, y2
                ):
                    out.append(
                        "C"
                        + " ".join(
                            _fmt(v)
                            for v in (c1[0], c1[1], c2[0], c2[1], end[0], end[1])
                        )
                    )
                cx, cy = x2, y2
        elif command in {"Z", "z"}:
            out.append("Z")
            cx, cy = sx, sy
        else:  # pragma: no cover — parser guards above already reject these
            raise ValueError(f"unhandled SVG path command {command!r} in {d!r}")
    return "".join(out)


def svg_to_path(svg_text: str) -> str:
    """A Lucide SVG document → one flat absolute M/L/C/Z path string."""
    body = svg_text.split(">", 1)[1] if "<svg" in svg_text else svg_text
    parts: list[str] = []
    consumed = 0
    for match in re.finditer(
        r"<(path|circle|rect|line|polyline|polygon)\b([^>]*?)/?>", body
    ):
        attrs = dict(_ATTR_RE.findall(match.group(2)))
        element = match.group(1)
        if element == "path":
            parts.append(_normalize_path(attrs["d"]))
        elif element == "circle":
            parts.append(
                _circle_to_cubics(
                    float(attrs["cx"]), float(attrs["cy"]), float(attrs["r"])
                )
            )
        elif element == "rect":
            parts.append(
                _rect_to_path(
                    float(attrs["x"]),
                    float(attrs["y"]),
                    float(attrs["width"]),
                    float(attrs["height"]),
                    float(attrs.get("rx", 0.0)),
                )
            )
        elif element == "line":
            parts.append(
                f"M{_fmt(float(attrs['x1']))} {_fmt(float(attrs['y1']))}"
                f"L{_fmt(float(attrs['x2']))} {_fmt(float(attrs['y2']))}"
            )
        elif element in {"polyline", "polygon"}:
            points = [float(v) for v in re.split(r"[,\s]+", attrs["points"].strip())]
            pairs = _number_pairs(points)
            path = "".join(
                ("M" if j == 0 else "L") + f"{_fmt(x)} {_fmt(y)}"
                for j, (x, y) in enumerate(pairs)
            )
            if element == "polygon":
                path += "Z"
            parts.append(path)
        consumed = match.end()
    leftover = re.sub(r"\s+", "", body[consumed:].split("</svg>")[0])
    if leftover:
        raise ValueError(f"unconverted SVG element content left: {leftover[:80]!r}")
    return "".join(parts)


def fetch_svg(name: str) -> str:
    with urllib.request.urlopen(UPSTREAM_URL.format(name=name), timeout=30) as reply:
        return reply.read().decode("utf-8")


JS_TEMPLATE = """/* GENERATED FILE — do not edit by hand.
 *
 * Lucide icon path data for the library ``ThemeIcon`` component. Regenerated
 * by ``scripts/vendor_lucide.py`` from the ISC-licensed upstream files vendored
 * under ``icons/`` (lucide-icons/lucide, commit {commit}). The upstream arc
 * commands and the circle/rect/line primitives are expanded to cubic Bézier
 * segments because Qt Quick's ``PathSvg`` understands only M/L/C/Z; every
 * string is the 24×24 Lucide grid stroked at width 2 with round caps — the
 * look ``ThemeIcon`` reproduces from the theme tokens.
 */

function iconPath(name) {{
    return PATHS[name] || "";
}}

var PATHS = {{
{entries}
}};
"""


def regenerate() -> None:
    entries = []
    for name in sorted(ICON_NAMES):
        svg = (ICONS_DIR / f"{name}.svg").read_text(encoding="utf-8")
        path = svg_to_path(svg)
        entries.append(f'    "{name}": "{path}",')
    ICONS_JS.write_text(
        JS_TEMPLATE.format(commit=UPSTREAM_COMMIT, entries="\n".join(entries)),
        encoding="utf-8",
    )
    print(f"wrote {ICONS_JS.relative_to(REPO_ROOT)} ({len(entries)} icons)")


def main(argv: list[str]) -> int:
    if "--fetch" in argv:
        LICENSE_URL = (
            "https://raw.githubusercontent.com/lucide-icons/lucide/"
            f"{UPSTREAM_COMMIT}/LICENSE"
        )
        ICONS_DIR.mkdir(parents=True, exist_ok=True)
        for name in ICON_NAMES:
            (ICONS_DIR / f"{name}.svg").write_text(fetch_svg(name), encoding="utf-8")
            print(f"fetched icons/{name}.svg")
        (ICONS_DIR / "LICENSE.txt").write_text(
            urllib.request.urlopen(LICENSE_URL, timeout=30).read().decode("utf-8"),
            encoding="utf-8",
        )
        print("fetched icons/LICENSE.txt")
    regenerate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
