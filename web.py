#!/usr/bin/env python
"""
Medical Expert System - Web Application
A local web-based interface for the medical diagnosis expert system.
Run this file and access the application at http://localhost:5000
"""

import os
import json
import html
import webbrowser
import re
import textwrap
from pathlib import Path
from html.parser import HTMLParser
from flask import Flask, render_template_string, request, jsonify, abort, url_for, send_file
import threading
import time
import uuid
from io import BytesIO
from expert import DiagnosisFlow, diagnose_from_answers

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent

# Store diagnosis sessions
sessions = {}


def get_markdown_path_for_disease(disease):
    if not disease:
        return None
    path = BASE_DIR / "Treatment" / "markdown" / f"{disease}.md"
    return path if path.exists() else None


def get_treatment_html_path(filename):
    treatment_dir = BASE_DIR / "Treatment" / "html"
    file_path = (treatment_dir / filename).resolve()
    try:
        file_path.relative_to(treatment_dir.resolve())
    except ValueError:
        return None
    if not file_path.exists() or not file_path.is_file():
        return None
    return file_path


def extract_treatment_body(html_content):
    match = re.search(r"<body[^>]*>(.*)</body>", html_content, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return html_content


def markdown_to_html_content(raw_text):
    lines = raw_text.splitlines()
    html_parts = []
    in_list = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            continue

        if stripped.startswith("# "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<h1>{html.escape(stripped[2:])}</h1>")
            continue

        if stripped.startswith("## "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<h2>{html.escape(stripped[3:])}</h2>")
            continue

        if stripped.startswith("### "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<h3>{html.escape(stripped[4:])}</h3>")
            continue

        if stripped[:2].isdigit() and stripped[1] == ".":
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f"<li>{html.escape(stripped[2:].strip())}</li>")
            continue

        if stripped.startswith(("- ", "* ")):
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f"<li>{html.escape(stripped[2:].strip())}</li>")
            continue

        if in_list:
            html_parts.append("</ul>")
            in_list = False

        cleaned = stripped.replace("**", "").replace("_", "")
        html_parts.append(f"<p>{html.escape(cleaned)}</p>")

    if in_list:
        html_parts.append("</ul>")

    return "".join(html_parts)


def get_disease_content(disease):
    html_path = get_treatment_html_path(f"{disease}.html")
    if html_path:
        return extract_treatment_body(html_path.read_text(encoding="utf-8", errors="ignore"))

    md_path = get_markdown_path_for_disease(disease)
    if md_path:
        return markdown_to_html_content(md_path.read_text(encoding="utf-8", errors="ignore"))

    return None


def _pdf_escape(value):
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


# ============================================================
# PDF RENDERING
# ============================================================

PAGE_W, PAGE_H = 595.28, 841.89
MARGIN_L = MARGIN_R = 56.0
MARGIN_B = 56.0
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R

PDF_INK = (0.063, 0.125, 0.200)
PDF_MUTED = (0.318, 0.384, 0.467)
PDF_ACCENT = (0.059, 0.463, 0.431)
PDF_ACCENT_DARK = (0.043, 0.369, 0.341)
PDF_RULE = (0.847, 0.898, 0.945)
PDF_BOX = (0.957, 0.984, 0.976)
PDF_WARN_BG = (0.996, 0.949, 0.949)
PDF_WARN_INK = (0.498, 0.114, 0.114)
PDF_WHITE = (1.0, 1.0, 1.0)

# Helvetica / Helvetica-Bold advance widths for WinAnsi codes 32-126.
_W_REGULAR = (278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278,
              333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556,
              278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611,
              778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667,
              611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333,
              556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833,
              556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500,
              334, 260, 334, 584)
_W_BOLD = (278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278,
           333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556,
           333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611,
           778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667,
           611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333,
           556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889,
           611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500,
           389, 280, 389, 584)
_W_HIGH = {0x85: 1000, 0x91: 222, 0x92: 222, 0x93: 333, 0x94: 333, 0x95: 350,
           0x96: 556, 0x97: 1000, 0xA0: 278, 0xB0: 400}
_W_HIGH_BOLD = {0x85: 1000, 0x91: 278, 0x92: 278, 0x93: 500, 0x94: 500,
                0x95: 350, 0x96: 556, 0x97: 1000, 0xA0: 278, 0xB0: 400}

_TYPOGRAPHIC = {
    "—": "\x97", "–": "\x96", "‘": "\x91", "’": "\x92",
    "“": "\x93", "”": "\x94", "•": "\x95", "…": "\x85",
    " ": " ", "→": "->", "≥": ">=", "≤": "<=",
}


def _to_winansi(text):
    """Map typographic characters onto WinAnsi, dropping glyphs Helvetica lacks."""
    out = []
    for char in text:
        if char in _TYPOGRAPHIC:
            out.append(_TYPOGRAPHIC[char])
            continue
        try:
            char.encode("latin-1")
        except UnicodeEncodeError:
            continue
        out.append(char)
    return "".join(out)


def _char_width(code, bold):
    if 32 <= code <= 126:
        return (_W_BOLD if bold else _W_REGULAR)[code - 32]
    return (_W_HIGH_BOLD if bold else _W_HIGH).get(code, 556)


def _text_width(text, size, bold=False):
    return sum(_char_width(ord(c), bold) for c in text) * size / 1000.0


class TreatmentDocument(HTMLParser):
    """Flattens treatment HTML into styled blocks the PDF writer can lay out."""

    _SKIP = {"style", "script", "svg"}
    _BLOCKS = {"h1": "h1", "h2": "h2", "h3": "h3", "h4": "h3", "p": "p", "li": "li"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.badge = ""
        self.facts = []
        self.blocks = []
        self._skip = 0
        self._bold = 0
        self._italic = 0
        self._header = 0
        self._footer = 0
        self._block = None
        self._runs = []
        self._fact_key = None

    def _flush(self):
        block, runs = self._block, self._runs
        self._block, self._runs = None, []
        if not block:
            return
        kind = block[0]
        runs = [(t, b, i) for t, b, i in runs if t.strip()]
        if not runs:
            return
        text = " ".join(t.strip() for t, _, _ in runs).strip()
        if kind == "badge":
            self.badge = self.badge or text
        elif kind == "factk":
            self._fact_key = text
        elif kind == "factv":
            self.facts.append((self._fact_key or "", text))
            self._fact_key = None
        elif kind == "h1" and self._header and not self.title:
            self.title = text
        elif self._header:
            self.blocks.append({"kind": "lead", "runs": runs})
        elif self._footer:
            self.blocks.append({"kind": "note", "runs": runs})
        else:
            self.blocks.append({"kind": kind, "runs": runs})

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        classes = dict(attrs).get("class", "").split()
        if tag == "header":
            self._header += 1
        elif tag == "footer":
            self._footer += 1
        if tag in ("strong", "b"):
            self._bold += 1
            return
        if tag in ("em", "i"):
            self._italic += 1
            return
        if tag == "br":
            self._runs.append((" ", False, False))
            return

        kind = self._BLOCKS.get(tag)
        if kind is None and tag == "div":
            if "callout" in classes:
                kind = "callout-warn" if "warn" in classes else "callout-info"
            elif "k" in classes:
                kind = "factk"
            elif "v" in classes:
                kind = "factv"
        elif kind is None and tag == "span" and "badge" in classes:
            kind = "badge"
        if kind:
            self._flush()
            self._block = (kind, tag)

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag in ("strong", "b"):
            self._bold = max(0, self._bold - 1)
            return
        if tag in ("em", "i"):
            self._italic = max(0, self._italic - 1)
            return
        if self._block and self._block[1] == tag:
            self._flush()
        if tag == "header":
            self._header = max(0, self._header - 1)
        elif tag == "footer":
            self._footer = max(0, self._footer - 1)

    def handle_data(self, data):
        if self._skip or not self._block or not data.strip():
            return
        self._runs.append((data, self._bold > 0, self._italic > 0))

    def close(self):
        super().close()
        self._flush()


class _PdfCanvas:
    """Collects drawing operators, one operator list per page."""

    def __init__(self):
        self.pages = []
        self.ops = []
        self.y = 0.0
        self.new_page()

    def new_page(self):
        self.ops = []
        self.pages.append(self.ops)
        self.y = PAGE_H - 64.0

    def need(self, height):
        if self.y - height < MARGIN_B:
            self.new_page()

    def rect(self, x, y, w, h, color):
        r, g, b = color
        self.ops.append(
            f"q {r:.3f} {g:.3f} {b:.3f} rg {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f Q")

    def text(self, x, y, value, font, size, color):
        value = _pdf_escape(_to_winansi(value))
        if not value:
            return
        r, g, b = color
        self.ops.append(
            f"BT /{font} {size:.2f} Tf {r:.3f} {g:.3f} {b:.3f} rg "
            f"{x:.2f} {y:.2f} Td ({value}) Tj ET")


def _tokens(runs):
    """Split runs into words, remembering where the source actually had a space
    so punctuation after an inline tag stays glued to the preceding word."""
    out, separated = [], False
    for text, bold, italic in runs:
        converted = _to_winansi(text)
        if not converted.strip():
            separated = separated or bool(converted)
            continue
        if converted[:1].isspace():
            separated = True
        for index, word in enumerate(converted.split()):
            out.append((word, bold, italic, separated if index == 0 else True))
            separated = True
        separated = converted[-1:].isspace()
    return out


def _wrap(tokens, size, max_width):
    lines, current, width = [], [], 0.0
    for token in tokens:
        word_w = _text_width(token[0], size, token[1])
        step = word_w
        if current and token[3]:
            step += _text_width(" ", size, token[1])
        if current and width + step > max_width:
            lines.append(current)
            current, width = [token], word_w
        else:
            current.append(token)
            width += step
    if current:
        lines.append(current)
    return lines


def _draw_line(canvas, x, y, line, size, color):
    for index, (word, bold, italic, separated) in enumerate(line):
        if index and separated:
            x += _text_width(" ", size, bold)
        font = "F2" if bold else ("F3" if italic else "F1")
        canvas.text(x, y, word, font, size, color)
        x += _text_width(word, size, bold)


def _embolden(runs):
    return [(text, True, italic) for text, _, italic in runs]


def _paragraph(canvas, runs, size, leading, color, gap=7.0, indent=0.0):
    for line in _wrap(_tokens(runs), size, CONTENT_W - indent):
        canvas.need(leading)
        canvas.y -= leading
        _draw_line(canvas, MARGIN_L + indent, canvas.y, line, size, color)
    canvas.y -= gap


def _heading(canvas, runs, size, color, space_above, space_below, rule=False):
    # reserve room for a couple of body lines too, so a heading never sits alone
    # at the foot of a page
    canvas.need(size + space_above + space_below + 42)
    canvas.y -= space_above
    for line in _wrap(_tokens(_embolden(runs)), size, CONTENT_W):
        canvas.y -= size + 2
        _draw_line(canvas, MARGIN_L, canvas.y, line, size, color)
    if rule:
        canvas.y -= 7
        canvas.rect(MARGIN_L, canvas.y, CONTENT_W, 0.7, PDF_RULE)
    canvas.y -= space_below


def _bullet(canvas, runs, size=10.0, leading=13.5):
    indent = 17.0
    for index, line in enumerate(_wrap(_tokens(runs), size, CONTENT_W - indent)):
        canvas.need(leading)
        canvas.y -= leading
        if index == 0:
            canvas.rect(MARGIN_L + 4, canvas.y + 3, 3, 3, PDF_ACCENT)
        _draw_line(canvas, MARGIN_L + indent, canvas.y, line, size, PDF_INK)
    canvas.y -= 3


def _callout(canvas, runs, warn):
    size, leading, pad = 9.5, 13.0, 11.0
    inner = CONTENT_W - 2 * pad - 6
    body = list(runs)
    # a leading <strong> is styled display:block on the page, so give it its own line
    lead = [body.pop(0)] if body and body[0][1] else []
    lines = _wrap(_tokens(lead), size, inner) if lead else []
    lines += _wrap(_tokens(body), size, inner) if body else []
    height = len(lines) * leading + 2 * pad
    canvas.need(height + 10)
    background = PDF_WARN_BG if warn else PDF_BOX
    ink = PDF_WARN_INK if warn else PDF_ACCENT_DARK
    top = canvas.y - 4
    canvas.rect(MARGIN_L, top - height, CONTENT_W, height, background)
    canvas.rect(MARGIN_L, top - height, 3.0, height, ink)
    y = top - pad - size + 2
    for line in lines:
        _draw_line(canvas, MARGIN_L + pad + 6, y, line, size, ink)
        y -= leading
    canvas.y = top - height - 10


def _facts_box(canvas, facts):
    if not facts:
        return
    row, pad = 17.0, 11.0
    height = len(facts) * row + 2 * pad - 4
    canvas.need(height + 12)
    top = canvas.y
    canvas.rect(MARGIN_L, top - height, CONTENT_W, height, PDF_BOX)
    y = top - pad - 8
    for key, value in facts:
        canvas.text(MARGIN_L + pad, y, key.upper(), "F1", 8.0, PDF_MUTED)
        _draw_line(canvas, MARGIN_L + pad + 150, y,
                   _tokens([(value, True, False)]), 9.5, PDF_INK)
        y -= row
    canvas.y = top - height - 14


def _summary_box(canvas, blocks):
    pad, size, leading = 12.0, 10.0, 14.0
    inner = CONTENT_W - 2 * pad
    items = []
    for block in blocks:
        kind, runs = block["kind"], block.get("runs", [])
        if kind in ("h1", "h2", "h3"):
            items.append(("head", _wrap(_tokens(_embolden(runs)), 12.0, inner), 16.0, 12.0))
        elif kind == "li":
            items.append(("li", _wrap(_tokens(runs), size, inner - 15), leading, size))
        else:
            items.append(("p", _wrap(_tokens(runs), size, inner), leading, size))
    height = 2 * pad + sum(len(lines) * step for _, lines, step, _ in items)
    canvas.need(height + 16)
    top = canvas.y
    canvas.rect(MARGIN_L, top - height, CONTENT_W, height, PDF_BOX)
    canvas.rect(MARGIN_L, top - height, 3.5, height, PDF_ACCENT)
    y = top - pad
    for kind, lines, step, size_ in items:
        for line in lines:
            y -= step
            if kind == "li":
                canvas.rect(MARGIN_L + pad + 4, y + 3, 2.5, 2.5, PDF_ACCENT)
                _draw_line(canvas, MARGIN_L + pad + 15, y, line, size_, PDF_INK)
            else:
                colour = PDF_ACCENT_DARK if kind == "head" else PDF_INK
                _draw_line(canvas, MARGIN_L + pad, y, line, size_, colour)
    canvas.y = top - height - 16


def _title_bar(canvas, title, badge):
    bar = 104.0
    canvas.rect(0, PAGE_H - bar, PAGE_W, bar, PDF_ACCENT)
    if badge:
        canvas.text(MARGIN_L, PAGE_H - 40, badge.upper(), "F1", 8.0, PDF_WHITE)
    size = 22.0
    while size > 13.0 and _text_width(title, size, True) > CONTENT_W:
        size -= 0.5
    canvas.text(MARGIN_L, PAGE_H - 70, title, "F2", size, PDF_WHITE)
    canvas.text(MARGIN_L, PAGE_H - 88, "Medical Expert System — condition reference",
                "F1", 9.0, PDF_WHITE)
    canvas.y = PAGE_H - bar - 26


def _page_footers(pages):
    total = len(pages)
    for index, ops in enumerate(pages, start=1):
        label = f"{index} of {total}"
        width = _text_width(label, 8.0)
        ops.append(f"q 0.847 0.898 0.945 rg {MARGIN_L:.2f} 40.00 "
                   f"{CONTENT_W:.2f} 0.7 re f Q")
        ops.append(
            f"BT /F1 8.00 Tf 0.318 0.384 0.467 rg "
            f"{(PAGE_W - width) / 2:.2f} 27.00 Td ({label}) Tj ET")


def _emit_pdf(pages):
    objects = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"),
        (4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            b"/Encoding /WinAnsiEncoding >>"),
        (5, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique "
            b"/Encoding /WinAnsiEncoding >>"),
    ]
    resources = "<< /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >>"
    kids, next_id = [], 6
    for ops in pages:
        content_id, page_id = next_id, next_id + 1
        next_id += 2
        stream = "\n".join(ops).encode("latin-1", errors="replace")
        objects.append((content_id,
                        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\n"
                        b"stream\n" + stream + b"\nendstream"))
        objects.append((page_id, (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W:.2f} {PAGE_H:.2f}] "
            f"/Resources {resources} /Contents {content_id} 0 R >>").encode("ascii")))
        kids.append(f"{page_id} 0 R")
    objects.append((2, (f"<< /Type /Pages /Kids [{' '.join(kids)}] "
                        f"/Count {len(kids)} >>").encode("ascii")))
    objects.sort(key=lambda item: item[0])

    output = BytesIO()
    output.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for obj_id, body in objects:
        offsets.append(output.tell())
        output.write(f"{obj_id} 0 obj\n".encode("ascii"))
        output.write(body)
        output.write(b"\nendobj\n")
    xref_start = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.write(b"0000000000 65535 f \n")
    for offset in offsets:
        output.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.write((f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
                  f"startxref\n{xref_start}\n%%EOF\n").encode("ascii"))
    output.seek(0)
    return output


def build_treatment_pdf(title, html_content, summary_html=""):
    """Render a treatment guide to a laid-out PDF using only the standard library."""
    document = TreatmentDocument()
    document.feed(html_content)
    document.close()

    summary_blocks = []
    if summary_html:
        summary = TreatmentDocument()
        summary.feed(summary_html)
        summary.close()
        summary_blocks = summary.blocks

    canvas = _PdfCanvas()
    _title_bar(canvas, document.title or title, document.badge)
    if summary_blocks:
        _summary_box(canvas, summary_blocks)
    _facts_box(canvas, document.facts)

    for block in document.blocks:
        kind, runs = block["kind"], block.get("runs", [])
        if kind == "lead":
            _paragraph(canvas, runs, 11.0, 15.0, PDF_MUTED, gap=12.0)
        elif kind == "h1":
            _heading(canvas, runs, 16.0, PDF_ACCENT_DARK, 16.0, 7.0, rule=True)
        elif kind == "h2":
            _heading(canvas, runs, 13.5, PDF_ACCENT_DARK, 18.0, 6.0, rule=True)
        elif kind == "h3":
            _heading(canvas, runs, 11.0, PDF_INK, 11.0, 3.0)
        elif kind == "li":
            _bullet(canvas, runs)
        elif kind.startswith("callout"):
            _callout(canvas, runs, kind.endswith("warn"))
        elif kind == "note":
            canvas.need(30)
            canvas.y -= 14
            canvas.rect(MARGIN_L, canvas.y, CONTENT_W, 0.7, PDF_RULE)
            canvas.y -= 6
            _paragraph(canvas, [(t, False, True) for t, _, _ in runs],
                       8.5, 12.0, PDF_MUTED)
        else:
            _paragraph(canvas, runs, 10.0, 14.0, PDF_INK)

    _page_footers(canvas.pages)
    return _emit_pdf(canvas.pages)


MAIN_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MediExpert &middot; Symptom Checker</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #eef4f2;
            --surface: #ffffff;
            --ink: #0e1a18;
            --muted: #5a6b68;
            --line: #e5ede9;
            --brand: #0f766e;
            --brand-2: #0d9488;
            --brand-3: #14b8a6;
            --brand-ink: #0b5e57;
            --mint: #ecfbf5;
            --mint-line: #cdeee2;
            --shadow: 0 1px 2px rgba(16,24,40,0.04), 0 14px 30px rgba(15,118,110,0.08);
            --shadow-lg: 0 1px 3px rgba(16,24,40,0.05), 0 30px 64px rgba(6,60,55,0.16);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html { scroll-behavior: smooth; }
        body {
            font-family: "Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
            color: var(--ink);
            background: var(--bg);
            min-height: 100vh;
            overflow-x: hidden;
            -webkit-font-smoothing: antialiased;
        }
        .nav {
            max-width: 1160px;
            margin: 0 auto;
            padding: 22px 28px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: relative;
            z-index: 3;
        }
        .logo {
            display: flex; align-items: center; gap: 10px;
            font-weight: 800; font-size: 1.14rem;
            letter-spacing: -0.02em; color: var(--ink);
        }
        .logo-mark {
            width: 36px; height: 36px; border-radius: 11px;
            background: linear-gradient(135deg, var(--brand) 0%, var(--brand-3) 100%);
            display: grid; place-items: center;
            box-shadow: 0 8px 18px rgba(15,118,110,0.32);
        }
        .logo-mark svg { width: 21px; height: 21px; }
        .nav-links { display: flex; align-items: center; gap: 26px; }
        .nav-links a {
            font-size: 0.92rem; font-weight: 600; color: var(--muted);
            text-decoration: none; transition: color 0.18s;
        }
        .nav-links a:hover { color: var(--brand); }
        .nav-cta {
            font-size: 0.9rem; font-weight: 700; color: var(--brand-ink) !important;
            background: var(--mint); border: 1px solid var(--mint-line);
            padding: 9px 16px; border-radius: 999px;
        }

        /* ---------- HERO ---------- */
        .hero-wrap { max-width: 1160px; margin: 0 auto; padding: 8px 28px 0; }
        .hero {
            position: relative;
            border-radius: 32px;
            overflow: hidden;
            background:
                radial-gradient(120% 120% at 100% 0%, rgba(20,184,166,0.55) 0%, transparent 45%),
                radial-gradient(90% 90% at -5% 110%, rgba(6,78,71,0.65) 0%, transparent 50%),
                linear-gradient(135deg, #0b5e57 0%, #0f766e 52%, #0d9488 100%);
            box-shadow: var(--shadow-lg);
            padding: 58px 56px;
            display: grid;
            grid-template-columns: 1.02fr 0.98fr;
            gap: 30px;
            align-items: center;
            isolation: isolate;
        }
        .hero::before, .hero::after {
            content: ""; position: absolute; border-radius: 50%;
            filter: blur(6px); z-index: -1; pointer-events: none;
        }
        .hero::before {
            width: 320px; height: 320px; top: -120px; right: -60px;
            background: radial-gradient(circle, rgba(153,246,228,0.35), transparent 70%);
            animation: floaty 9s ease-in-out infinite;
        }
        .hero::after {
            width: 260px; height: 260px; bottom: -110px; left: 20%;
            background: radial-gradient(circle, rgba(45,212,191,0.28), transparent 70%);
            animation: floaty 11s ease-in-out infinite reverse;
        }
        .hero-copy { color: #fff; animation: fadeUp 0.7s cubic-bezier(.2,.7,.2,1) both; }
        .eyebrow {
            display: inline-flex; align-items: center; gap: 8px;
            font-size: 0.76rem; font-weight: 700; letter-spacing: 0.05em;
            text-transform: uppercase; color: #d7fbef;
            background: rgba(255,255,255,0.12);
            border: 1px solid rgba(255,255,255,0.22);
            padding: 8px 14px; border-radius: 999px; margin-bottom: 24px;
            backdrop-filter: blur(4px);
        }
        .eyebrow .dot {
            width: 7px; height: 7px; border-radius: 50%; background: #6ee7b7;
            box-shadow: 0 0 0 4px rgba(110,231,183,0.28);
            animation: pulseDot 2s ease-in-out infinite;
        }
        h1.title {
            font-size: clamp(2.3rem, 4.6vw, 3.5rem);
            line-height: 1.04; letter-spacing: -0.035em;
            font-weight: 800; margin-bottom: 20px; color: #fff;
        }
        h1.title .accent {
            background: linear-gradient(120deg, #a7f3d0 0%, #6ee7b7 100%);
            -webkit-background-clip: text; background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .lede {
            font-size: 1.09rem; line-height: 1.62;
            color: rgba(233,250,245,0.9); max-width: 470px; margin-bottom: 32px;
        }
        .cta-row { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }
        .start-btn {
            border: none; border-radius: 15px; padding: 17px 30px;
            font-family: inherit; font-size: 1.04rem; font-weight: 700;
            color: var(--brand-ink); background: #ffffff; cursor: pointer;
            display: inline-flex; align-items: center; gap: 10px;
            box-shadow: 0 14px 30px rgba(3,40,36,0.35);
            transition: transform 0.18s ease, box-shadow 0.18s ease;
        }
        .start-btn:hover { transform: translateY(-3px); box-shadow: 0 20px 40px rgba(3,40,36,0.45); }
        .start-btn svg { width: 18px; height: 18px; transition: transform 0.18s; }
        .start-btn:hover svg { transform: translateX(4px); }
        .cta-note { font-size: 0.9rem; color: rgba(233,250,245,0.85); }
        .cta-note strong { color: #fff; font-weight: 700; }

        /* ---------- HERO PREVIEW ---------- */
        .preview { position: relative; height: 100%; min-height: 380px; animation: fadeUp 0.8s cubic-bezier(.2,.7,.2,1) 0.12s both; }
        .app-card {
            position: absolute; inset: 14% 6% 14% 6%;
            background: #fff; border-radius: 22px;
            box-shadow: 0 30px 60px rgba(3,40,36,0.4);
            padding: 22px; display: flex; flex-direction: column; gap: 16px;
            animation: floaty 7s ease-in-out infinite;
        }
        .app-top { display: flex; align-items: center; gap: 7px; }
        .app-top i { width: 10px; height: 10px; border-radius: 50%; background: #e2e8e6; display: block; }
        .app-top i:first-child { background: #34d399; }
        .app-top span { margin-left: auto; font-size: 0.72rem; font-weight: 700; color: var(--brand-ink); background: var(--mint); padding: 4px 10px; border-radius: 999px; }
        .app-prog { height: 7px; border-radius: 999px; background: #eef2f0; overflow: hidden; }
        .app-prog b { display: block; height: 100%; width: 62%; border-radius: 999px; background: linear-gradient(90deg, var(--brand), var(--brand-3)); animation: grow 2.4s ease-in-out infinite alternate; }
        .app-q { font-size: 1.06rem; font-weight: 700; letter-spacing: -0.01em; color: var(--ink); line-height: 1.35; }
        .app-opts { display: grid; gap: 9px; }
        .app-opt { padding: 12px 14px; border-radius: 12px; border: 1px solid var(--line); font-size: 0.9rem; font-weight: 600; color: var(--muted); display: flex; align-items: center; justify-content: space-between; }
        .app-opt.on { background: linear-gradient(135deg, var(--brand), var(--brand-2)); border-color: transparent; color: #fff; box-shadow: 0 10px 20px rgba(15,118,110,0.28); }
        .app-opt.on svg { width: 16px; height: 16px; }

        .float-badge {
            position: absolute; top: 4%; right: -2%;
            background: #fff; border-radius: 15px; padding: 12px 15px;
            box-shadow: 0 18px 38px rgba(3,40,36,0.28);
            display: flex; align-items: center; gap: 11px;
            animation: floaty 6s ease-in-out 0.4s infinite;
        }
        .float-badge .fb-ico { width: 34px; height: 34px; border-radius: 10px; background: #dcfce7; color: #059669; display: grid; place-items: center; }
        .float-badge .fb-ico svg { width: 19px; height: 19px; }
        .float-badge small { display: block; font-size: 0.68rem; font-weight: 600; color: var(--muted); }
        .float-badge strong { display: block; font-size: 0.92rem; font-weight: 800; color: var(--ink); }

        .float-vitals {
            position: absolute; bottom: 3%; left: -4%;
            background: #fff; border-radius: 15px; padding: 13px 16px;
            box-shadow: 0 18px 38px rgba(3,40,36,0.28);
            animation: floaty 8s ease-in-out 0.7s infinite;
        }
        .float-vitals .fv-top { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
        .float-vitals .fv-top svg { width: 15px; height: 15px; color: #f43f5e; }
        .float-vitals .fv-top span { font-size: 0.7rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
        .float-vitals .fv-val { font-size: 1.15rem; font-weight: 800; color: var(--ink); }
        .float-vitals .fv-val em { font-size: 0.7rem; font-weight: 600; color: var(--muted); font-style: normal; }
        .ecg { display: block; width: 92px; height: 26px; margin-top: 2px; }
        .ecg path { stroke: #f43f5e; stroke-width: 2; fill: none; stroke-linecap: round; stroke-linejoin: round; stroke-dasharray: 160; animation: ecg 2.2s linear infinite; }

        /* ---------- FEATURES ---------- */
        .section { max-width: 1160px; margin: 0 auto; padding: 76px 28px 0; }
        .sec-head { text-align: center; max-width: 620px; margin: 0 auto 42px; }
        .sec-head .kicker { font-size: 0.78rem; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; color: var(--brand-2); }
        .sec-head h2 { font-size: clamp(1.7rem, 3.4vw, 2.4rem); font-weight: 800; letter-spacing: -0.03em; margin: 10px 0 12px; }
        .sec-head p { color: var(--muted); font-size: 1.02rem; line-height: 1.6; }
        .features { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
        .feature {
            position: relative; background: var(--surface); border: 1px solid var(--line);
            border-radius: 22px; padding: 28px; box-shadow: var(--shadow);
            transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
            overflow: hidden;
        }
        .feature::after {
            content: ""; position: absolute; inset: 0 0 auto 0; height: 3px;
            background: linear-gradient(90deg, var(--brand), var(--brand-3));
            transform: scaleX(0); transform-origin: left; transition: transform 0.28s ease;
        }
        .feature:hover { transform: translateY(-6px); box-shadow: 0 24px 48px rgba(6,60,55,0.14); border-color: var(--mint-line); }
        .feature:hover::after { transform: scaleX(1); }
        .feature .ico {
            width: 50px; height: 50px; border-radius: 14px;
            background: linear-gradient(135deg, var(--mint), #d6f5ea);
            color: var(--brand); display: grid; place-items: center; margin-bottom: 18px;
            box-shadow: inset 0 0 0 1px var(--mint-line);
        }
        .feature .ico svg { width: 25px; height: 25px; }
        .feature h3 { font-size: 1.14rem; font-weight: 700; margin-bottom: 8px; letter-spacing: -0.01em; }
        .feature p { font-size: 0.93rem; color: var(--muted); line-height: 1.6; }

        /* ---------- STEPS BAND ---------- */
        .steps-band {
            margin-top: 26px; background: var(--surface); border: 1px solid var(--line);
            border-radius: 26px; padding: 40px; box-shadow: var(--shadow);
            display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; position: relative;
        }
        .stepx { display: flex; gap: 16px; align-items: flex-start; }
        .stepx .num {
            flex: none; width: 42px; height: 42px; border-radius: 13px;
            background: linear-gradient(135deg, var(--brand), var(--brand-2)); color: #fff;
            font-weight: 800; font-size: 1.05rem; display: grid; place-items: center;
            box-shadow: 0 8px 18px rgba(15,118,110,0.28);
        }
        .stepx h4 { font-size: 1.02rem; font-weight: 700; margin-bottom: 4px; }
        .stepx p { font-size: 0.9rem; color: var(--muted); line-height: 1.5; }

        /* ---------- CTA BAND ---------- */
        .cta-band {
            max-width: 1160px; margin: 76px auto 0; padding: 0 28px;
        }
        .cta-inner {
            background: linear-gradient(135deg, #0b5e57, #0f766e 60%, #0d9488);
            border-radius: 28px; padding: 48px; text-align: center; color: #fff;
            box-shadow: var(--shadow-lg); position: relative; overflow: hidden;
        }
        .cta-inner h2 { font-size: clamp(1.6rem, 3.2vw, 2.2rem); font-weight: 800; letter-spacing: -0.02em; margin-bottom: 12px; }
        .cta-inner p { color: rgba(233,250,245,0.9); font-size: 1.02rem; margin-bottom: 26px; }

        /* ---------- FOOTER ---------- */
        .footer { max-width: 1160px; margin: 0 auto; padding: 40px 28px 48px; }
        .disclaimer {
            display: flex; gap: 12px; align-items: flex-start;
            border: 1px solid var(--line); background: var(--surface);
            border-radius: 16px; padding: 16px 18px;
            font-size: 0.9rem; color: var(--muted); line-height: 1.55;
        }
        .disclaimer svg { width: 20px; height: 20px; flex: none; color: var(--brand); margin-top: 1px; }
        .disclaimer strong { color: var(--ink); }
        .foot-meta { text-align: center; margin-top: 22px; font-size: 0.85rem; color: var(--muted); }

        @keyframes fadeUp { from { opacity: 0; transform: translateY(22px); } to { opacity: 1; transform: none; } }
        @keyframes floaty { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-12px); } }
        @keyframes grow { from { width: 42%; } to { width: 74%; } }
        @keyframes pulseDot { 0%,100% { box-shadow: 0 0 0 4px rgba(110,231,183,0.28); } 50% { box-shadow: 0 0 0 8px rgba(110,231,183,0.05); } }
        @keyframes ecg { from { stroke-dashoffset: 320; } to { stroke-dashoffset: 0; } }

        @media (max-width: 940px) {
            .hero { grid-template-columns: 1fr; padding: 44px 34px; }
            .preview { min-height: 330px; margin-top: 20px; }
            .features, .steps-band { grid-template-columns: 1fr; }
            .nav-links a:not(.nav-cta) { display: none; }
        }
        @media (max-width: 560px) {
            .nav, .hero-wrap, .section, .cta-band, .footer { padding-left: 16px; padding-right: 16px; }
            .hero { padding: 34px 22px; border-radius: 24px; }
            .cta-inner, .steps-band { padding: 30px 22px; }
            .float-vitals { left: 0; }
            .float-badge { right: 0; }
        }
        @media (prefers-reduced-motion: reduce) {
            * { animation: none !important; scroll-behavior: auto; }
        }
    </style>
</head>
<body>
    <nav class="nav">
        <div class="logo">
            <span class="logo-mark">
                <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h4l2 5 4-12 2 7h6"/></svg>
            </span>
            MediExpert
        </div>
        <div class="nav-links">
            <a href="#features">Features</a>
            <a href="#how">How it works</a>
            <a href="#" class="nav-cta" onclick="startDiagnosis(); return false;">Start check</a>
        </div>
    </nav>

    <div class="hero-wrap">
        <section class="hero">
            <div class="hero-copy">
                <span class="eyebrow"><span class="dot"></span> AI-guided symptom checker</span>
                <h1 class="title">Understand your symptoms, <span class="accent">clearly.</span></h1>
                <p class="lede">A rule-based medical expert system that asks structured questions about your symptoms and history, then suggests a likely condition with treatment guidance.</p>
                <div class="cta-row">
                    <button class="start-btn" onclick="startDiagnosis()">
                        Start diagnosis
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
                    </button>
                    <span class="cta-note"><strong>Free</strong> &middot; No sign-up needed</span>
                </div>
            </div>

            <div class="preview">
                <div class="app-card">
                    <div class="app-top">
                        <i></i><i></i><i></i>
                        <span>Question 5 of 8</span>
                    </div>
                    <div class="app-prog"><b></b></div>
                    <div class="app-q">Do you have a high fever with body aches?</div>
                    <div class="app-opts">
                        <div class="app-opt on">Yes
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
                        </div>
                        <div class="app-opt">No</div>
                    </div>
                </div>
                <div class="float-badge">
                    <span class="fb-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span>
                    <div><small>Likely condition</small><strong>Dengue</strong></div>
                </div>
                <div class="float-vitals">
                    <div class="fv-top">
                        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 21s-7.5-4.9-10-9.3C.6 8.8 1.9 5 5.3 5c2 0 3.2 1.1 4.2 2.4C10.5 6.1 11.7 5 13.7 5c3.4 0 4.7 3.8 3.3 6.7C19.5 16.1 12 21 12 21z"/></svg>
                        <span>Heart rate</span>
                    </div>
                    <div class="fv-val">82 <em>bpm</em></div>
                    <svg class="ecg" viewBox="0 0 92 26" preserveAspectRatio="none"><path d="M0 13 H22 L27 4 L33 22 L39 13 H56 L61 7 L67 19 L72 13 H92"/></svg>
                </div>
            </div>
        </section>
    </div>

    <section class="section" id="features">
        <div class="sec-head">
            <span class="kicker">Why MediExpert</span>
            <h2>Smart triage, made simple</h2>
            <p>Everything you need to check symptoms and understand the next step &mdash; in a clean, guided flow.</p>
        </div>
        <div class="features">
            <div class="feature">
                <div class="ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.29 1.51 4.04 3 5.5l7 7Z"/></svg></div>
                <h3>31 conditions</h3>
                <p>A curated knowledge base of common diseases, modelled with expert medical rules.</p>
            </div>
            <div class="feature">
                <div class="ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v1a3 3 0 0 0-3 3 3 3 0 0 0 0 6 3 3 0 0 0 3 3v1a3 3 0 0 0 6 0v-1a3 3 0 0 0 3-3 3 3 0 0 0 0-6 3 3 0 0 0-3-3V5a3 3 0 0 0-3-3Z"/></svg></div>
                <h3>Rule-based AI</h3>
                <p>A transparent expert-system engine reasons over your answers &mdash; no black box.</p>
            </div>
            <div class="feature">
                <div class="ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M9 15l2 2 4-4"/></svg></div>
                <h3>Treatment &amp; PDF</h3>
                <p>Get practical cure and prevention details, ready to read or download as a PDF.</p>
            </div>
        </div>
    </section>

    <section class="section" id="how">
        <div class="sec-head">
            <span class="kicker">How it works</span>
            <h2>Three simple steps</h2>
            <p>From first symptom to a clear next action in just a few minutes.</p>
        </div>
        <div class="steps-band">
            <div class="stepx">
                <span class="num">1</span>
                <div><h4>Answer questions</h4><p>Respond honestly to guided questions about your symptoms.</p></div>
            </div>
            <div class="stepx">
                <span class="num">2</span>
                <div><h4>Share your history</h4><p>Add relevant medical background and risk factors.</p></div>
            </div>
            <div class="stepx">
                <span class="num">3</span>
                <div><h4>Get your result</h4><p>Review the likely condition plus treatment and prevention info.</p></div>
            </div>
        </div>
    </section>

    <div class="cta-band">
        <div class="cta-inner">
            <h2>Ready to check your symptoms?</h2>
            <p>It only takes a few minutes &mdash; no account required.</p>
            <button class="start-btn" onclick="startDiagnosis()">
                Start diagnosis
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
            </button>
        </div>
    </div>

    <footer class="footer">
        <div class="disclaimer">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
            <div><strong>Medical disclaimer:</strong> This tool is for educational use only and does not replace professional medical advice, diagnosis, or treatment.</div>
        </div>
        <div class="foot-meta">&copy; MediExpert &middot; Rule-based medical expert system</div>
    </footer>

    <script>
        function startDiagnosis() {
            window.location.href = '/diagnosis';
        }
    </script>
</body>
</html>
"""

DIAGNOSIS_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Diagnosis &middot; MediExpert</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #f3f8f6;
            --card: #ffffff;
            --ink: #0f1c1a;
            --muted: #5a6b68;
            --line: #e5ede9;
            --primary: #0f766e;
            --primary-2: #0d9488;
            --brand-ink: #0b5e57;
            --mint: #ecfbf5;
            --mint-line: #cdeee2;
            --danger: #be123c;
            --shadow-lg: 0 1px 3px rgba(16,24,40,0.05), 0 24px 50px rgba(15,118,110,0.12);
            --shadow-sm: 0 1px 2px rgba(16,24,40,0.04), 0 12px 26px rgba(15,118,110,0.10);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: "Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
            color: var(--ink);
            background:
                radial-gradient(circle at 90% -6%, rgba(16,185,129,0.09), transparent 42%),
                radial-gradient(circle at 4% 106%, rgba(13,148,136,0.07), transparent 40%),
                var(--bg);
            min-height: 100vh;
            padding: 22px 14px 40px;
            -webkit-font-smoothing: antialiased;
        }
        /* ---------- BACKGROUND WATERMARK ---------- */
        .med-bg {
            position: fixed;
            inset: 0;
            z-index: 0;
            pointer-events: none;
            color: var(--primary);
            opacity: 0.08;
        }
        .med-bg svg {
            display: block;
            width: 100%;
            height: 100%;
        }
        .shell {
            position: relative;
            z-index: 1;
            width: 100%;
            max-width: 780px;
            margin: 0 auto;
            display: block;
        }
        .side { display: none; }
        .brandbar {
            display: flex;
            align-items: center;
            gap: 10px;
            font-weight: 800;
            letter-spacing: -0.02em;
            font-size: 1.02rem;
            margin: 0 auto 18px;
            max-width: 780px;
            color: var(--ink);
        }
        .brandbar .logo-mark {
            width: 30px; height: 30px;
            border-radius: 9px;
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-2) 100%);
            display: grid; place-items: center;
            box-shadow: 0 5px 14px rgba(15,118,110,0.28);
        }
        .brandbar .logo-mark svg { width: 18px; height: 18px; }
        .container {
            width: 100%;
            background: var(--card);
            border: 1px solid var(--line);
            border-radius: 24px;
            box-shadow: var(--shadow-lg);
            overflow: hidden;
            min-height: 0;
        }
        .header {
            background: var(--card);
            color: var(--ink);
            padding: 22px 26px 18px;
            display: grid;
            gap: 12px;
            position: sticky;
            top: 0;
            z-index: 5;
            border-bottom: 1px solid var(--line);
        }
        .header-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
        }
        .header h2 {
            font-size: 1.12rem;
            font-weight: 700;
            letter-spacing: -0.01em;
        }
        .progress-label {
            font-size: 0.8rem;
            font-weight: 700;
            padding: 6px 12px;
            border-radius: 999px;
            background: var(--mint);
            color: var(--brand-ink);
            white-space: nowrap;
        }
        .progress-track {
            width: 100%;
            height: 8px;
            border-radius: 999px;
            background: #eef2f0;
            overflow: hidden;
        }
        .progress-fill {
            width: 6%;
            height: 100%;
            border-radius: 999px;
            background: linear-gradient(90deg, var(--primary) 0%, var(--primary-2) 100%);
            transition: width 0.3s ease;
        }
        .content {
            padding: 24px 26px 28px;
            min-height: 0;
            overflow: visible;
        }
        .prediction-banner {
            display: none;
            margin-bottom: 18px;
            padding: 18px 20px;
            border: 1px solid var(--mint-line);
            border-radius: 18px;
            background: linear-gradient(135deg, #f0fbf6 0%, #eafaf4 100%);
            box-shadow: 0 12px 26px rgba(15, 118, 110, 0.10);
        }
        .prediction-banner.show {
            display: block;
        }
        .prediction-banner.final {
            border-color: var(--mint-line);
            background: linear-gradient(135deg, #eefaf5 0%, #e6f7f0 100%);
        }
        .prediction-banner h3 {
            font-size: 1.06rem;
            font-weight: 700;
            color: var(--brand-ink);
            margin-bottom: 8px;
        }
        .prediction-banner p {
            color: var(--muted);
            font-size: 0.94rem;
            line-height: 1.55;
        }
        .prediction-actions {
            display: flex;
            gap: 10px;
            margin-top: 16px;
        }
        .secondary-btn {
            padding: 12px 16px;
            border: 1px solid var(--line);
            border-radius: 12px;
            font-family: inherit;
            font-size: 0.94rem;
            font-weight: 700;
            cursor: pointer;
            color: var(--ink);
            background: #fff;
            transition: transform 0.18s, box-shadow 0.18s, border-color 0.18s;
        }
        .secondary-btn:hover {
            transform: translateY(-1px);
            box-shadow: var(--shadow-sm);
            border-color: var(--mint-line);
        }
        .question-stream {
            display: block;
            position: relative;
            min-height: 220px;
        }
        .loading-note {
            color: var(--muted);
            font-size: 0.95rem;
            text-align: left;
            padding: 14px 10px;
        }
        #content > * {
            width: 100%;
            max-width: 100%;
        }
        .question-card {
            width: 100%;
            position: relative;
            transition: opacity 0.3s ease, transform 0.32s cubic-bezier(.2,.7,.2,1);
        }
        .question-card.entering {
            opacity: 0;
            transform: translateY(26px) scale(0.97);
        }
        .question-card.leaving {
            opacity: 0;
            transform: translateY(-24px) scale(0.97);
        }
        @media (prefers-reduced-motion: reduce) {
            .question-card { transition: none; }
            .question-card.entering, .question-card.leaving { opacity: 1; transform: none; }
        }
        .question-meta {
            font-size: 0.74rem;
            font-weight: 700;
            color: var(--brand-ink);
            margin: 0 0 8px 4px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .question-section {
            background: #ffffff;
            border: 1px solid var(--line);
            border-radius: 20px;
            padding: 22px;
            transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
        }
        .question-section.active {
            border-color: var(--mint-line);
            box-shadow: 0 16px 34px rgba(15, 118, 110, 0.10);
        }
        .question-section.answered {
            background: #fbfefd;
            border-color: var(--line);
        }
        .answer-preview {
            margin-top: 14px;
            color: var(--brand-ink);
            font-weight: 600;
            font-size: 0.9rem;
            line-height: 1.45;
            border-top: 1px solid var(--line);
            padding-top: 12px;
        }
        .card-actions {
            display: flex;
            gap: 10px;
            margin-top: 14px;
            flex-wrap: wrap;
        }
        .edit-btn {
            padding: 9px 15px;
            border: 1px solid var(--line);
            border-radius: 999px;
            background: #fff;
            color: var(--brand-ink);
            font-family: inherit;
            font-size: 0.86rem;
            font-weight: 700;
            cursor: pointer;
            transition: border-color 0.18s, background 0.18s;
        }
        .edit-btn:hover {
            border-color: var(--mint-line);
            background: var(--mint);
        }
        .question-section.editing {
            border-color: var(--primary-2);
            box-shadow: 0 16px 34px rgba(15, 118, 110, 0.10);
        }
        .selected-answer {
            background: var(--mint);
            border-color: var(--primary-2);
        }
        .question {
            font-size: 1.16rem;
            color: var(--ink);
            margin-bottom: 18px;
            line-height: 1.45;
            font-weight: 700;
            letter-spacing: -0.01em;
        }
        .yes-no-buttons {
            display: flex;
            gap: 10px;
        }
        .yes-btn, .no-btn {
            flex: 1;
            padding: 14px 18px;
            border: 1px solid var(--line);
            border-radius: 13px;
            font-family: inherit;
            font-size: 0.98rem;
            font-weight: 700;
            cursor: pointer;
            color: var(--ink);
            background: #fff;
            transition: transform 0.18s, box-shadow 0.18s, border-color 0.18s, background 0.18s;
        }
        .yes-btn:hover { border-color: var(--primary-2); background: var(--mint); color: var(--brand-ink); transform: translateY(-1px); box-shadow: var(--shadow-sm); }
        .no-btn:hover { border-color: #f3c6d1; background: #fdf2f5; color: var(--danger); transform: translateY(-1px); box-shadow: var(--shadow-sm); }
        .yes-btn.selected-answer { background: linear-gradient(135deg, var(--primary), var(--primary-2)); border-color: transparent; color: #fff; }
        .no-btn.selected-answer { background: linear-gradient(135deg, var(--danger), #e11d48); border-color: transparent; color: #fff; }
        .option-btn {
            width: 100%;
            padding: 14px 16px;
            margin-bottom: 10px;
            border-radius: 13px;
            border: 1px solid var(--line);
            background: #fff;
            color: var(--ink);
            text-align: left;
            font-family: inherit;
            font-size: 0.96rem;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.18s, border-color 0.18s, transform 0.18s;
        }
        .option-btn:hover {
            background: var(--mint);
            border-color: var(--mint-line);
            transform: translateX(3px);
        }
        .option-btn.selected-answer {
            background: var(--mint);
            border-color: var(--primary-2);
            color: var(--brand-ink);
            font-weight: 700;
        }
        .text-input {
            width: 100%;
            padding: 14px 16px;
            border: 1px solid var(--line);
            border-radius: 13px;
            font-size: 0.98rem;
            margin-bottom: 12px;
            font-family: inherit;
            background: #fbfefd;
        }
        .text-input:focus {
            outline: none;
            border-color: var(--primary-2);
            background: #fff;
            box-shadow: 0 0 0 4px rgba(13,148,136,0.14);
        }
        .submit-btn {
            width: 100%;
            padding: 14px;
            border: none;
            border-radius: 13px;
            font-family: inherit;
            font-size: 0.98rem;
            font-weight: 700;
            color: #fff;
            cursor: pointer;
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-2) 100%);
            box-shadow: 0 8px 20px rgba(15,118,110,0.24);
            transition: transform 0.18s, box-shadow 0.18s, filter 0.18s;
        }
        .submit-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 14px 28px rgba(15,118,110,0.30);
            filter: brightness(1.03);
        }
        .checkbox-group {
            display: grid;
            gap: 10px;
            margin-bottom: 14px;
        }
        .checkbox-label {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 13px 14px;
            border: 1px solid var(--line);
            border-radius: 12px;
            background: #fff;
            transition: background 0.18s, border-color 0.18s;
            cursor: pointer;
            font-size: 0.95rem;
        }
        .checkbox-label:hover { border-color: var(--mint-line); background: #fbfefd; }
        .checkbox-label.checked {
            background: var(--mint);
            border-color: var(--primary-2);
            font-weight: 600;
        }
        .checkbox-label input {
            width: 19px;
            height: 19px;
            accent-color: var(--primary);
        }
        @media (max-width: 640px) {
            body { padding: 16px 10px 30px; }
            .header { padding: 18px 16px 14px; }
            .content { padding: 20px 16px; }
            .question-stream { padding-left: 20px; }
            .question-card::before { left: -18px; }
            .question { font-size: 1.05rem; }
            .yes-no-buttons { flex-direction: column; }
            .prediction-actions { flex-direction: column; }
        }
    </style>
</head>
<body>
    <div class="med-bg" aria-hidden="true">
        <svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%">
            <defs>
                <g id="eq-stetho" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="14" cy="7" r="2.2"/>
                    <circle cx="32" cy="7" r="2.2"/>
                    <path d="M14 9v7c0 8 18 8 18 0V9"/>
                    <path d="M23 22c0 6 3 9 8 10"/>
                    <circle cx="33" cy="34" r="3.8"/>
                    <circle cx="33" cy="34" r="1.4"/>
                </g>
                <g id="eq-syringe" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="15" y="19" width="19" height="10" rx="1.5"/>
                    <path d="M34 24h9"/>
                    <path d="M34 20.5v7"/>
                    <path d="M15 24H9"/>
                    <path d="M9 20v8"/>
                    <path d="M20 19v3.5M24 19v3.5M28 19v3.5"/>
                </g>
                <g id="eq-thermo" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="20.5" y="6" width="7" height="24" rx="3.5"/>
                    <circle cx="24" cy="34" r="5.5"/>
                    <path d="M28.5 12h4M28.5 17h4M28.5 22h4"/>
                </g>
                <g id="eq-heart" fill="none" stroke="currentColor" stroke-width="0.6" stroke-linecap="round" stroke-linejoin="round">
                    <g transform="translate(0,5) scale(2)">
                        <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.29 1.51 4.04 3 5.5l7 7Z"/>
                        <path d="M4.5 11h3l1.5-3 2 6 1.5-3h5"/>
                    </g>
                </g>
                <g id="eq-capsule" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
                    <g transform="rotate(-35 24 24)">
                        <rect x="8" y="18" width="32" height="12" rx="6"/>
                        <path d="M24 18v12"/>
                    </g>
                </g>
                <g id="eq-iv" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 5c0-2 6-2 6 0"/>
                    <path d="M24 5v3"/>
                    <rect x="16" y="8" width="16" height="18" rx="3"/>
                    <path d="M19.5 13h9"/>
                    <path d="M24 26v3"/>
                    <rect x="21" y="29" width="6" height="7" rx="2"/>
                    <path d="M24 36v3c0 3 5 2 5 5"/>
                </g>
                <g id="eq-clip" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="11" y="9" width="26" height="31" rx="3"/>
                    <rect x="18" y="5" width="12" height="8" rx="2.5"/>
                    <path d="M24 20v13M17.5 26.5h13"/>
                </g>
                <g id="eq-monitor" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="7" y="10" width="34" height="23" rx="3"/>
                    <path d="M12 22h5l3-6 4 12 3-6h9"/>
                    <path d="M24 33v5"/>
                    <path d="M17 39h14"/>
                </g>
                <pattern id="medEquipTile" x="0" y="0" width="480" height="480" patternUnits="userSpaceOnUse">
                    <use href="#eq-stetho"  transform="translate(28,26) scale(1.75) rotate(-8 24 24)"/>
                    <use href="#eq-syringe" transform="translate(250,48) scale(1.7) rotate(12 24 24)"/>
                    <use href="#eq-clip"    transform="translate(382,18) scale(1.5) rotate(7 24 24)"/>
                    <use href="#eq-heart"   transform="translate(146,176) scale(1.7) rotate(4 24 24)"/>
                    <use href="#eq-monitor" transform="translate(348,192) scale(1.6) rotate(-6 24 24)"/>
                    <use href="#eq-thermo"  transform="translate(44,292) scale(1.7) rotate(11 24 24)"/>
                    <use href="#eq-iv"      transform="translate(188,338) scale(1.6) rotate(-5 24 24)"/>
                    <use href="#eq-capsule" transform="translate(300,330) scale(1.6)"/>
                </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#medEquipTile)"/>
        </svg>
    </div>
    <div class="shell">
        <div class="brandbar">
            <span class="logo-mark">
                <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h4l2 5 4-12 2 7h6"/></svg>
            </span>
            MediExpert
        </div>
        <div class="container">
            <div class="header">
                <div class="header-top">
                    <h2>Symptom check</h2>
                    <span class="progress-label">Question <span id="q-num">1</span></span>
                </div>
                <div class="progress-track">
                    <div class="progress-fill" id="q-fill"></div>
                </div>
            </div>
            <div class="content" id="content">
                <div class="prediction-banner" id="prediction-banner">
                    <h3 id="prediction-title"></h3>
                    <p id="prediction-text"></p>
                    <div class="prediction-actions">
                        <button class="submit-btn" type="button" onclick="continueAfterPrediction()">Continue questions</button>
                        <button class="secondary-btn" type="button" onclick="goToResult()">See result</button>
                    </div>
                </div>
                <div class="question-stream" id="question-stream">
                    <p class="loading-note" id="loading-note">Loading questions...</p>
                </div>
            </div>
        </div>
    </div>
    <script>
        let sessionId = '{{ session_id }}';
        let selectedOptions = [];
        let currentQuestion = null;
        let isSubmitting = false;
        let answersOrder = [];
        let answersByKey = {};
        const LEAVE_MS = 240;

        function escapeHtml(value) {
            return String(value)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        function getStream() {
            return document.getElementById('question-stream');
        }

        function setVisualProgress(step) {
            const fill = document.getElementById('q-fill');
            const percent = Math.min(100, Math.max(6, step * 7));
            fill.style.width = percent + '%';
        }

        function recordAnswer(question, answer) {
            const item = { key: question.key, question: question.question, answer: answer, type: question.type };
            if (Object.prototype.hasOwnProperty.call(answersByKey, question.key)) {
                answersOrder[answersByKey[question.key]] = item;
            } else {
                answersByKey[question.key] = answersOrder.length;
                answersOrder.push(item);
            }
        }

        function persistAnswers() {
            try { sessionStorage.setItem('mediexpert_answers', JSON.stringify(answersOrder)); } catch (e) {}
        }

        function hidePredictionBanner() {
            const banner = document.getElementById('prediction-banner');
            banner.classList.remove('show');
            banner.classList.remove('final');
        }

        function renderControls(q) {
            if (q.type === 'text') {
                return `
                    <input type="text" class="text-input" placeholder="Type your answer..." autofocus onkeydown="handleTextKeydown(event)">
                    <button class="submit-btn" type="button" onclick="submitText()">Continue</button>
                `;
            }
            if (q.type === 'yesno') {
                return `
                    <div class="yes-no-buttons">
                        <button class="yes-btn" type="button" onclick="pickAndSubmit(this, 'yes')">Yes</button>
                        <button class="no-btn" type="button" onclick="pickAndSubmit(this, 'no')">No</button>
                    </div>
                `;
            }
            if (q.type === 'select') {
                return `
                    <div class="options">
                        ${q.options.map(opt => `<button class="option-btn" type="button" onclick='pickAndSubmit(this, ${JSON.stringify(opt)})'>${escapeHtml(opt)}</button>`).join('')}
                    </div>
                `;
            }
            if (q.type === 'multi') {
                return `
                    <div class="checkbox-group">
                        ${q.options.map(opt => `
                            <label class="checkbox-label">
                                <input type="checkbox" onchange='toggleCheckbox(${JSON.stringify(opt)}, this)'>
                                <span>${escapeHtml(opt)}</span>
                            </label>
                        `).join('')}
                    </div>
                    <button class="submit-btn" type="button" onclick="submitMultiSelect()">Continue</button>
                `;
            }
            return '';
        }

        function renderCard(data) {
            const q = data.question;
            q.step = data.step;
            currentQuestion = q;
            selectedOptions = [];

            const stream = getStream();
            const loading = document.getElementById('loading-note');
            if (loading) loading.remove();

            const card = document.createElement('div');
            card.className = 'question-card entering';
            card.innerHTML = `
                <div class="question-meta">Question ${q.step}</div>
                <div class="question-section active">
                    <div class="question">${escapeHtml(q.question)}</div>
                    ${renderControls(q)}
                </div>
            `;
            stream.appendChild(card);
            requestAnimationFrame(() => card.classList.remove('entering'));
            const input = card.querySelector('.text-input');
            if (input) { try { input.focus(); } catch (e) {} }
        }

        function loadQuestion() {
            fetch('/api/question?session_id=' + sessionId)
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'complete') {
                        goToResult();
                        return;
                    }
                    if (data.status === 'error') {
                        getStream().innerHTML = '<p class="loading-note" style="color:#be123c;">Error: ' + data.message + '</p>';
                        return;
                    }
                    document.getElementById('q-num').textContent = data.step;
                    setVisualProgress(data.step);
                    renderCard(data);
                    isSubmitting = false;
                })
                .catch(() => {
                    getStream().innerHTML = '<p class="loading-note" style="color:#be123c;">Error loading question. Please refresh.</p>';
                    isSubmitting = false;
                });
        }

        function goToResult() {
            persistAnswers();
            window.location.href = '/result?session_id=' + sessionId;
        }

        function showPrediction(prediction) {
            const banner = document.getElementById('prediction-banner');
            banner.classList.remove('final');
            document.getElementById('prediction-title').textContent = 'This may be: ' + prediction.disease;
            document.getElementById('prediction-text').textContent = 'Keep answering for a more thorough check, or see your result now.';
            document.querySelector('.prediction-actions').innerHTML = `
                <button class="submit-btn" type="button" onclick="continueAfterPrediction()">Continue questions</button>
                <button class="secondary-btn" type="button" onclick="goToResult()">See result</button>
            `;
            banner.classList.add('show');
            banner.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }

        function continueAfterPrediction() {
            hidePredictionBanner();
            loadQuestion();
        }

        function leaveCurrentCard(callback) {
            const card = getStream().querySelector('.question-card');
            if (card) {
                card.classList.add('leaving');
                setTimeout(() => { if (card.parentNode) card.remove(); callback(); }, LEAVE_MS);
            } else {
                callback();
            }
        }

        function submitAnswer(answer) {
            if (isSubmitting || !currentQuestion) return;
            isSubmitting = true;
            hidePredictionBanner();
            const finalAnswer = Array.isArray(answer) ? [...answer] : answer;
            const question = currentQuestion;
            recordAnswer(question, finalAnswer);
            persistAnswers();

            const request = fetch('/api/answer', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ session_id: sessionId, key: question.key, answer: finalAnswer })
            }).then(r => r.json()).catch(() => ({ status: 'ok' }));

            leaveCurrentCard(() => {
                request.then(data => {
                    isSubmitting = false;
                    if (data && data.status === 'predicted') {
                        showPrediction(data.prediction);
                    } else {
                        loadQuestion();
                    }
                });
            });
        }

        function pickAndSubmit(el, answer) {
            if (isSubmitting) return;
            el.classList.add('selected-answer');
            const siblings = el.parentElement ? el.parentElement.querySelectorAll('button') : [];
            siblings.forEach(b => { if (b !== el) b.disabled = true; });
            submitAnswer(answer);
        }

        function submitText() {
            const card = getStream().querySelector('.question-card');
            const input = card ? card.querySelector('.text-input') : null;
            if (input && input.value.trim()) {
                submitAnswer(input.value.trim());
            } else {
                alert('Please enter an answer');
            }
        }

        function handleTextKeydown(event) {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            submitText();
        }

        function toggleCheckbox(option, checkbox) {
            const label = checkbox.parentElement;
            if (checkbox.checked) {
                label.classList.add('checked');
                if (!selectedOptions.includes(option)) selectedOptions.push(option);
            } else {
                label.classList.remove('checked');
                selectedOptions = selectedOptions.filter(o => o !== option);
            }
        }

        function submitMultiSelect() {
            if (selectedOptions.length === 0) {
                alert('Please select at least one option');
                return;
            }
            submitAnswer([...selectedOptions]);
        }

        loadQuestion();
    </script>
</body>
</html>
"""

RESULT_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Result &middot; MediExpert</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #f3f8f6;
            --card: #ffffff;
            --ink: #0f1c1a;
            --muted: #5a6b68;
            --line: #e5ede9;
            --primary: #0f766e;
            --primary-2: #0d9488;
            --brand-ink: #0b5e57;
            --mint: #ecfbf5;
            --mint-line: #cdeee2;
            --shadow: 0 1px 2px rgba(16,24,40,0.04), 0 14px 30px rgba(15,118,110,0.08);
            --shadow-lg: 0 1px 3px rgba(16,24,40,0.05), 0 28px 58px rgba(15,118,110,0.13);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: "Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
            color: var(--ink);
            background:
                radial-gradient(circle at 88% -8%, rgba(16,185,129,0.10), transparent 42%),
                radial-gradient(circle at 6% 108%, rgba(13,148,136,0.08), transparent 40%),
                var(--bg);
            min-height: 100vh;
            padding: 22px 16px 44px;
            -webkit-font-smoothing: antialiased;
        }
        .brandbar {
            display: flex;
            align-items: center;
            gap: 10px;
            font-weight: 800;
            letter-spacing: -0.02em;
            font-size: 1.02rem;
            margin: 0 auto 18px;
            max-width: 820px;
            color: var(--ink);
        }
        .brandbar .logo-mark {
            width: 30px; height: 30px;
            border-radius: 9px;
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-2) 100%);
            display: grid; place-items: center;
            box-shadow: 0 5px 14px rgba(15,118,110,0.28);
        }
        .brandbar .logo-mark svg { width: 18px; height: 18px; }
        .container {
            width: 100%;
            max-width: 820px;
            margin: 0 auto;
            background: var(--card);
            border: 1px solid var(--line);
            border-radius: 24px;
            box-shadow: var(--shadow-lg);
            overflow: hidden;
            animation: resultIn 0.5s cubic-bezier(.2,.7,.2,1) both;
        }
        @keyframes resultIn { from { opacity: 0; transform: translateY(20px) scale(0.99); } to { opacity: 1; transform: none; } }
        @media (prefers-reduced-motion: reduce) { .container { animation: none; } }
        .header {
            padding: 30px 30px 26px;
            border-bottom: 1px solid var(--line);
            text-align: center;
        }
        .result-badge {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-size: 0.76rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            color: var(--brand-ink);
            background: var(--mint);
            border: 1px solid var(--mint-line);
            padding: 7px 14px;
            border-radius: 999px;
            margin-bottom: 16px;
        }
        .result-badge svg { width: 15px; height: 15px; }
        .header .likely-label {
            font-size: 0.9rem;
            color: var(--muted);
            font-weight: 600;
            margin-bottom: 6px;
        }
        .diagnosis-title {
            font-size: clamp(1.9rem, 4vw, 2.6rem);
            color: var(--ink);
            font-weight: 800;
            letter-spacing: -0.03em;
            line-height: 1.1;
        }
        .content {
            padding: 26px 30px 32px;
            display: grid;
            gap: 20px;
        }
        .symptoms-list {
            background: #fbfefd;
            border: 1px solid var(--line);
            border-radius: 18px;
            padding: 22px;
        }
        .symptoms-list h4 {
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            margin-bottom: 14px;
            color: var(--brand-ink);
            font-weight: 700;
        }
        .symptoms-list ul {
            list-style: none;
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
        }
        .symptoms-list li {
            position: relative;
            padding-left: 26px;
            color: var(--ink);
            line-height: 1.4;
            font-size: 0.94rem;
            font-weight: 500;
        }
        .symptoms-list li:before {
            content: "";
            position: absolute;
            left: 0;
            top: 1px;
            width: 17px;
            height: 17px;
            border-radius: 50%;
            background: var(--mint);
            border: 1px solid var(--mint-line);
        }
        .symptoms-list li:after {
            content: "";
            position: absolute;
            left: 5px;
            top: 6px;
            width: 6px;
            height: 3px;
            border-left: 2px solid var(--primary);
            border-bottom: 2px solid var(--primary);
            transform: rotate(-45deg);
        }
        .answers-review {
            background: #fbfefd;
            border: 1px solid var(--line);
            border-radius: 18px;
            padding: 22px;
        }
        .answers-review h4 {
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            margin-bottom: 14px;
            color: var(--brand-ink);
            font-weight: 700;
        }
        .ans-list { display: grid; gap: 10px; }
        .ans-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            padding: 12px 14px;
            border: 1px solid var(--line);
            border-radius: 12px;
            background: #fff;
        }
        .ans-q { font-size: 0.92rem; color: var(--muted); font-weight: 500; line-height: 1.4; }
        .ans-a {
            flex: none;
            font-size: 0.86rem;
            font-weight: 700;
            color: var(--brand-ink);
            background: var(--mint);
            border: 1px solid var(--mint-line);
            padding: 6px 12px;
            border-radius: 999px;
            max-width: 48%;
            text-align: right;
            word-break: break-word;
        }
        .actions {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
        }
        .action-btn {
            padding: 15px 16px;
            border: 1px solid var(--line);
            border-radius: 14px;
            font-size: 0.94rem;
            font-weight: 700;
            text-decoration: none;
            text-align: center;
            color: var(--ink);
            background: #fff;
            transition: transform 0.18s, box-shadow 0.18s, border-color 0.18s, background 0.18s;
        }
        .action-btn:hover {
            transform: translateY(-2px);
            box-shadow: var(--shadow);
            border-color: var(--mint-line);
            background: #fbfefd;
        }
        .treatment-btn {
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-2) 100%);
            color: #fff;
            border-color: transparent;
            box-shadow: 0 8px 20px rgba(15,118,110,0.24);
        }
        .treatment-btn:hover {
            color: #fff;
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-2) 100%);
            box-shadow: 0 14px 28px rgba(15,118,110,0.30);
            filter: brightness(1.04);
        }
        .disclaimer {
            display: flex;
            gap: 12px;
            align-items: flex-start;
            background: #fbfefd;
            border: 1px solid var(--line);
            border-radius: 14px;
            padding: 15px 17px;
            color: var(--muted);
            font-size: 0.88rem;
            line-height: 1.55;
        }
        .disclaimer svg { width: 19px; height: 19px; flex: none; color: var(--primary); margin-top: 1px; }
        .disclaimer strong { color: var(--ink); }
        .no-match {
            text-align: center;
            padding: 20px 10px;
        }
        .no-match .nm-ico {
            width: 60px; height: 60px;
            border-radius: 16px;
            background: var(--mint);
            color: var(--primary);
            display: grid; place-items: center;
            margin: 0 auto 18px;
        }
        .no-match .nm-ico svg { width: 30px; height: 30px; }
        .no-match h3 {
            color: var(--ink);
            font-size: 1.4rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            margin-bottom: 10px;
        }
        .no-match p {
            color: var(--muted);
            line-height: 1.55;
            max-width: 420px;
            margin: 0 auto;
        }
        .no-match .try-btn {
            display: inline-block;
            margin-top: 22px;
            padding: 15px 32px;
            border-radius: 14px;
            text-decoration: none;
            font-weight: 700;
            color: #fff;
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-2) 100%);
            box-shadow: 0 8px 20px rgba(15,118,110,0.24);
            transition: transform 0.18s, box-shadow 0.18s;
        }
        .no-match .try-btn:hover { transform: translateY(-2px); box-shadow: 0 14px 28px rgba(15,118,110,0.30); }
        @media (max-width: 640px) {
            body { padding: 16px 12px 34px; }
            .header { padding: 24px 18px 20px; }
            .content { padding: 20px 18px; }
            .actions { grid-template-columns: 1fr; }
            .symptoms-list ul { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="brandbar">
        <span class="logo-mark">
            <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h4l2 5 4-12 2 7h6"/></svg>
        </span>
        MediExpert
    </div>
    <div class="container">
        {% if result and result.disease %}
        <div class="header">
            <span class="result-badge">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
                Diagnosis complete
            </span>
            <div class="likely-label">Most likely condition</div>
            <div class="diagnosis-title">{{ result.disease }}</div>
        </div>

        <div class="content">
            <div class="symptoms-list">
                <h4>Matched symptoms</h4>
                <ul>
                    {% for symptom in result.symptoms %}
                    <li>{{ symptom }}</li>
                    {% endfor %}
                </ul>
            </div>

            <div class="answers-review" id="answers-review" style="display:none">
                <h4>Your answers</h4>
                <div class="ans-list" id="ans-list"></div>
            </div>

            <div class="actions">
                <a href="{{ treatment_url }}" target="_blank" class="action-btn treatment-btn">View treatment</a>
                <a href="{{ pdf_url }}" class="action-btn">Download PDF</a>
                <a href="/" class="action-btn">New diagnosis</a>
            </div>

            <div class="disclaimer">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
                <div><strong>Medical disclaimer:</strong> This expert system is for educational purposes only. It is not a substitute for professional medical advice.</div>
            </div>
        </div>
        {% else %}
        <div class="content">
            <div class="no-match">
                <div class="nm-ico">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
                </div>
                <h3>No clear match</h3>
                <p>The symptoms you provided did not match a disease in the current knowledge base. Try again with different answers.</p>
                <a href="/" class="try-btn">Try again</a>
            </div>

            <div class="answers-review" id="answers-review" style="display:none">
                <h4>Your answers</h4>
                <div class="ans-list" id="ans-list"></div>
            </div>

            <div class="disclaimer">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
                <div><strong>Medical disclaimer:</strong> This expert system is for educational purposes only. It is not a substitute for professional medical advice.</div>
            </div>
        </div>
        {% endif %}
    </div>
    <script>
        (function () {
            var raw;
            try { raw = sessionStorage.getItem('mediexpert_answers'); } catch (e) { raw = null; }
            if (!raw) return;
            var items;
            try { items = JSON.parse(raw); } catch (e) { return; }
            if (!items || !items.length) return;
            var list = document.getElementById('ans-list');
            var review = document.getElementById('answers-review');
            if (!list || !review) return;
            function fmt(a) {
                if (Array.isArray(a)) return a.join(', ');
                var s = String(a == null ? '' : a);
                if (s === 'yes') return 'Yes';
                if (s === 'no') return 'No';
                return s;
            }
            items.forEach(function (it) {
                if (!it || !it.question) return;
                var row = document.createElement('div');
                row.className = 'ans-row';
                var q = document.createElement('div');
                q.className = 'ans-q';
                q.textContent = it.question;
                var a = document.createElement('div');
                a.className = 'ans-a';
                a.textContent = fmt(it.answer);
                row.appendChild(q);
                row.appendChild(a);
                list.appendChild(row);
            });
            review.style.display = 'block';
        })();
    </script>
</body>
</html>
"""

TREATMENT_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ disease }} - Treatment Reference</title>
    <style>
        :root {
            --bg-1: #edf7ff;
            --bg-2: #f8fcff;
            --card: #ffffff;
            --ink: #102033;
            --muted: #516277;
            --line: #d8e5f1;
            --primary: #13578f;
            --primary-2: #2a79bf;
            --accent: #0f766e;
            --shadow-lg: 0 24px 54px rgba(19, 87, 143, 0.14);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
            color: var(--ink);
            background:
                radial-gradient(circle at 10% 5%, rgba(42,121,191,0.14), transparent 38%),
                radial-gradient(circle at 90% 95%, rgba(15,118,110,0.12), transparent 40%),
                linear-gradient(165deg, var(--bg-1) 0%, var(--bg-2) 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1040px;
            margin: 0 auto;
            background: var(--card);
            border: 1px solid var(--line);
            border-radius: 20px;
            box-shadow: var(--shadow-lg);
            overflow: hidden;
        }
        .topbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            padding: 18px 22px;
            background: linear-gradient(130deg, var(--primary) 0%, var(--primary-2) 62%, var(--accent) 100%);
            color: white;
        }
        .topbar h1 {
            font-size: clamp(1.35rem, 2.6vw, 1.9rem);
            line-height: 1.2;
        }
        .topbar p {
            font-size: 0.93rem;
            opacity: 0.94;
            margin-top: 4px;
        }
        .actions {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .action-btn {
            padding: 11px 14px;
            border-radius: 11px;
            text-decoration: none;
            color: white;
            font-weight: 700;
            font-size: 0.93rem;
            border: 1px solid rgba(255,255,255,0.2);
            background: rgba(255,255,255,0.18);
        }
        .action-btn.secondary {
            background: rgba(10, 29, 53, 0.2);
        }
        .content {
            padding: 24px;
        }
        .article {
            background: #fff;
            border: 1px solid #e2edf8;
            border-radius: 16px;
            padding: 22px;
            line-height: 1.7;
            color: #1b2a3b;
        }
        .article h1, .article h2, .article h3 {
            color: var(--primary);
            margin: 18px 0 10px;
        }
        .article p, .article ul, .article ol {
            margin: 0 0 14px;
        }
        @media (max-width: 700px) {
            body { padding: 12px; }
            .topbar { align-items: flex-start; flex-direction: column; }
            .content { padding: 16px; }
            .article { padding: 16px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="topbar">
            <div>
                <h1>{{ disease }}</h1>
                <p>Know more about diagnosis, treatment options, and prevention.</p>
            </div>
            <div class="actions">
                <a href="{{ pdf_url }}" class="action-btn">Download PDF</a>
                <a href="/" class="action-btn secondary">Back Home</a>
            </div>
        </div>
        <div class="content">
            <div class="article">{{ content|safe }}</div>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(MAIN_PAGE)

@app.route('/diagnosis')
def diagnosis():
    session_id = str(uuid.uuid4())
    sessions[session_id] = DiagnosisFlow()
    return render_template_string(DIAGNOSIS_PAGE, session_id=session_id)

@app.route('/api/question')
def get_question():
    session_id = request.args.get('session_id')

    if not session_id or session_id not in sessions:
        return jsonify({'status': 'error', 'message': 'Invalid session'})

    flow = sessions[session_id]
    question = flow.get_current_question()

    if not question:
        # Run diagnosis
        disease, symptoms = flow.run_diagnosis()
        sessions[session_id].result = {'disease': disease, 'symptoms': symptoms}
        return jsonify({
            'status': 'complete',
            'result': {
                'disease': disease,
                'symptoms': symptoms
            }
        })

    # Generate HTML for the question
    question_html = ''

    if question['type'] == 'text':
        question_html = f'''
        <div class="question-section">
            <div class="question">{question["question"]}</div>
            <input type="text" class="text-input" id="text-answer" placeholder="Type your answer..." autofocus>
            <button class="submit-btn" onclick="submitText()">Continue</button>
        </div>
        '''

    elif question['type'] == 'yesno':
        question_html = f'''
        <div class="question-section">
            <div class="question">{question["question"]}</div>
            <div class="yes-no-buttons">
                <button class="yes-btn" onclick="submitAnswer('yes')">Yes</button>
                <button class="no-btn" onclick="submitAnswer('no')">No</button>
            </div>
        </div>
        '''

    elif question['type'] == 'select':
        options_html = ''.join([
            f'<button class="option-btn" onclick=\'submitAnswer({json.dumps(opt)})\'>{html.escape(opt)}</button>'
            for opt in question['options']
        ])
        question_html = f'''
        <div class="question-section">
            <div class="question">{question["question"]}</div>
            <div class="options">
                {options_html}
            </div>
        </div>
        '''

    elif question['type'] == 'multi':
        options_html = ''.join([
            f'''
            <label class="checkbox-label">
                <input type="checkbox" onchange='toggleCheckbox({json.dumps(opt)}, this)'>
                <span>{html.escape(opt)}</span>
            </label>
            '''
            for opt in question['options']
        ])
        question_html = f'''
        <div class="question-section">
            <div class="question">{question["question"]}</div>
            <div class="checkbox-group">
                {options_html}
            </div>
            <button class="submit-btn" onclick="submitMultiSelect()">Continue</button>
        </div>
        '''

    return jsonify({
        'status': 'question',
        'step': len(flow.answers) + 1,
        'html': question_html,
        'key': question.get('key', ''),
        'question': question
    })

@app.route('/api/answer', methods=['POST'])
def submit_answer():
    data = request.json
    session_id = data.get('session_id')
    key = data.get('key')
    answer = data.get('answer')

    if session_id in sessions:
        flow = sessions[session_id]
        if key:
            flow.submit_answer(key, answer)
            disease, symptoms = diagnose_from_answers(flow.answers)
            if disease and flow.prediction_prompted != disease:
                flow.prediction_prompted = disease
                return jsonify({
                    'status': 'predicted',
                    'prediction': {
                        'disease': disease,
                        'symptoms': symptoms
                    }
                })
            flow.prediction_prompted = disease

    return jsonify({'status': 'ok'})

@app.route('/api/edit-start', methods=['POST'])
def edit_start():
    data = request.json
    session_id = data.get('session_id')
    key = data.get('key')

    if session_id in sessions and key:
        sessions[session_id].start_edit(key)
        return jsonify({'status': 'ok'})

    return jsonify({'status': 'error', 'message': 'Invalid session or key'}), 400

@app.route('/api/revise-answer', methods=['POST'])
def revise_answer():
    data = request.json
    session_id = data.get('session_id')
    key = data.get('key')
    answer = data.get('answer')

    if session_id in sessions and key:
        flow = sessions[session_id]
        flow.revise_answer(key, answer)
        disease, symptoms = diagnose_from_answers(flow.answers)
        if disease and flow.prediction_prompted != disease:
            flow.prediction_prompted = disease
            return jsonify({
                'status': 'predicted',
                'prediction': {
                    'disease': disease,
                    'symptoms': symptoms
                }
            })
        flow.prediction_prompted = disease
        return jsonify({'status': 'ok'})

    return jsonify({'status': 'error', 'message': 'Invalid session or key'}), 400

@app.route('/result')
def result():
    session_id = request.args.get('session_id')

    if session_id in sessions:
        flow = sessions[session_id]
        result_data = flow.result

        treatment_url = ''
        if result_data and result_data.get('disease'):
            disease = result_data['disease']
            if get_disease_content(disease):
                treatment_url = url_for('treatment_info', disease=disease, session_id=session_id)
            pdf_url = url_for('download_disease_pdf', disease=disease, session_id=session_id)
        else:
            pdf_url = ''

        return render_template_string(RESULT_PAGE,
            result=result_data,
            treatment_url=treatment_url,
            pdf_url=pdf_url
        )

    return render_template_string(RESULT_PAGE, result=None, pdf_url='', treatment_url='')

@app.route('/treatment-info/<path:disease>')
def treatment_info(disease):
    content = get_disease_content(disease)
    if not content:
        abort(404)
    session_id = request.args.get('session_id', '')
    return render_template_string(
        TREATMENT_PAGE,
        disease=disease,
        pdf_url=url_for('download_disease_pdf', disease=disease, session_id=session_id) if session_id else url_for('download_disease_pdf', disease=disease),
        content=content
    )

@app.route('/treatment/<path:filename>')
def treatment_file(filename):
    file_path = get_treatment_html_path(filename)
    if not file_path:
        abort(404)
    disease = Path(filename).stem
    content = extract_treatment_body(file_path.read_text(encoding='utf-8', errors='ignore'))
    session_id = request.args.get('session_id', '')
    return render_template_string(
        TREATMENT_PAGE,
        disease=disease,
        pdf_url=url_for('download_disease_pdf', disease=disease, session_id=session_id) if session_id else url_for('download_disease_pdf', disease=disease),
        content=content
    )


@app.route('/download-pdf/<path:disease>')
def download_disease_pdf(disease):
    content = get_disease_content(disease)
    if not content:
        abort(404)
    session_id = request.args.get('session_id', '')
    summary_html = ''

    if session_id and session_id in sessions:
        flow = sessions[session_id]
        patient_name = flow.answers.get('name', '').strip()
        symptoms = []
        if flow.result and flow.result.get('symptoms'):
            symptoms = flow.result.get('symptoms', [])

        summary_parts = ['<h2>Patient Summary</h2>']
        if patient_name:
            summary_parts.append(f'<p><strong>Patient name:</strong> {html.escape(patient_name)}</p>')
        summary_parts.append(f'<p><strong>Predicted disease:</strong> {html.escape(disease)}</p>')
        if symptoms:
            summary_parts.append('<p><strong>Matching symptoms:</strong></p>')
            summary_parts.append('<ul>')
            summary_parts.extend(f'<li>{html.escape(symptom)}</li>' for symptom in symptoms)
            summary_parts.append('</ul>')
        summary_html = ''.join(summary_parts)

    pdf_buffer = build_treatment_pdf(disease, content, summary_html=summary_html)
    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f"{disease}.pdf",
        mimetype="application/pdf"
    )

# ============================================================
# MAIN
# ============================================================

def open_browser():
    """Open browser after server starts"""
    time.sleep(2)
    webbrowser.open('http://localhost:5000')

if __name__ == '__main__':
    print("=" * 60)
    print("MEDICAL EXPERT SYSTEM - WEB VERSION")
    print("=" * 60)
    print()
    print("Starting local web server...")
    print()
    print("The application will open in your default browser.")
    print()
    print("If it doesn't open automatically, go to:")
    print("http://localhost:5000")
    print()
    print("Press Ctrl+C to stop the server.")
    print("=" * 60)

    threading.Thread(target=open_browser, daemon=True).start()
    app.run(debug=False, port=5000)
