"""pdf_kit.py — document machinery for the UG project report.

Implements the Chandigarh University UG report typographic specification:
  * A4, left 1.5", right 1", top 1", bottom 1"
  * body: Times New Roman 12 pt, 1.5 line spacing, justified
  * chapter name: Times 16 pt bold, centred
  * heading: Times 14 pt bold, left
  * sub-heading: Times 12 pt bold, left
  * figure caption: Times 10 pt bold, below the figure
  * table caption: Times 10 pt bold, above the table

Also provides: dual (roman / arabic) page numbering, a manually rendered
table of contents with dot leaders and real page numbers, automatic figure and
table registers, and a two-pass build so every cross-reference is correct.
"""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, FrameBreak,
                                KeepTogether, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

# --------------------------------------------------------------------------- geometry
PAGE_W, PAGE_H = A4
ML, MR, MT, MB = 1.5 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch
TEXT_W = PAGE_W - ML - MR          # ~415 pt

# --------------------------------------------------------------------------- palette
INK = colors.HexColor("#111111")
NAVY = colors.HexColor("#1f3864")
TEAL = colors.HexColor("#2e6f6b")
GREY = colors.HexColor("#8a8f98")
LIGHT = colors.HexColor("#eef1f5")
MID = colors.HexColor("#d7dce3")
AMBER = colors.HexColor("#b07a1e")
RED = colors.HexColor("#8c2f2f")

FONT = "Times-Roman"
FONT_B = "Times-Bold"
FONT_I = "Times-Italic"
FONT_BI = "Times-BoldItalic"

# --------------------------------------------------------------------------- styles
def _s(name, **kw):
    base = dict(fontName=FONT, fontSize=12, leading=18, alignment=TA_JUSTIFY,
                spaceAfter=6, textColor=INK)
    base.update(kw)
    return ParagraphStyle(name, **base)


S = {
    "body": _s("body"),
    "body_c": _s("body_c", alignment=TA_CENTER),
    "body_nj": _s("body_nj", alignment=TA_LEFT),
    "chapter_no": _s("chapter_no", fontName=FONT_B, fontSize=16, leading=22,
                     alignment=TA_CENTER, spaceBefore=0, spaceAfter=2),
    "chapter": _s("chapter", fontName=FONT_B, fontSize=16, leading=22,
                  alignment=TA_CENTER, spaceAfter=20),
    "h1": _s("h1", fontName=FONT_B, fontSize=14, leading=20, alignment=TA_LEFT,
             spaceBefore=12, spaceAfter=6),
    "h2": _s("h2", fontName=FONT_B, fontSize=12, leading=17, alignment=TA_LEFT,
             spaceBefore=10, spaceAfter=4),
    "h3": _s("h3", fontName=FONT_BI, fontSize=12, leading=17, alignment=TA_LEFT,
             spaceBefore=8, spaceAfter=3),
    "fig_cap": _s("fig_cap", fontName=FONT_B, fontSize=10, leading=13,
                  alignment=TA_CENTER, spaceBefore=6, spaceAfter=14),
    "tab_cap": _s("tab_cap", fontName=FONT_B, fontSize=10, leading=13,
                  alignment=TA_CENTER, spaceBefore=12, spaceAfter=5),
    "cell": _s("cell", fontSize=10, leading=12.5, alignment=TA_LEFT, spaceAfter=0),
    "cell_c": _s("cell_c", fontSize=10, leading=12.5, alignment=TA_CENTER, spaceAfter=0),
    "cell_b": _s("cell_b", fontName=FONT_B, fontSize=10, leading=12.5, spaceAfter=0),
    "cell_h": _s("cell_h", fontName=FONT_B, fontSize=10, leading=12.5,
                 alignment=TA_LEFT, spaceAfter=0, textColor=colors.white),
    "front_head": _s("front_head", fontName=FONT_B, fontSize=16, leading=22,
                     alignment=TA_CENTER, spaceAfter=18),
    "title_big": _s("title_big", fontName=FONT_B, fontSize=18, leading=25,
                    alignment=TA_CENTER, spaceAfter=0),
    "bullet": _s("bullet", leftIndent=20, bulletIndent=6, spaceAfter=4),
    "small": _s("small", fontSize=10, leading=14),
    "ref": _s("ref", fontSize=11, leading=15, alignment=TA_LEFT, spaceAfter=6,
              leftIndent=22, firstLineIndent=-22),
    "code": _s("code", fontName="Courier", fontSize=9, leading=12, alignment=TA_LEFT,
               backColor=colors.HexColor("#f4f5f7"), borderPadding=(5, 6, 5, 6),
               spaceBefore=4, spaceAfter=10),
    "fig_note": _s("fig_note", fontSize=9, leading=12, alignment=TA_CENTER,
                   textColor=colors.HexColor("#444444"), spaceAfter=8),
}


def P(text, style="body"):
    return Paragraph(text, S[style])


def B(items, style="body"):
    """Bulleted list."""
    out = []
    for it in items:
        st = ParagraphStyle("b_", parent=S[style], leftIndent=22, bulletIndent=6,
                            spaceAfter=4)
        out.append(Paragraph(it, st, bulletText="\u2022"))
    return out


def NUM(items, style="body"):
    out = []
    for i, it in enumerate(items, 1):
        st = ParagraphStyle("n_", parent=S[style], leftIndent=24, bulletIndent=4,
                            spaceAfter=4)
        out.append(Paragraph(it, st, bulletText=f"{i}."))
    return out


# --------------------------------------------------------------------------- markers
class Marker(Flowable):
    """Zero-height flowable that records the physical page it lands on."""

    REG: dict[str, int] = {}
    CURRENT: list = []          # stack of registries (one per pass)

    def __init__(self, key: str):
        super().__init__()
        self.key = key
        self.width = 0
        self.height = 0

    def wrap(self, aw, ah):
        return (0, 0)

    def draw(self):
        if Marker.CURRENT:
            Marker.CURRENT[-1][self.key] = self.canv.getPageNumber()


def key(k: str) -> Marker:
    return Marker(k)


# --------------------------------------------------------------------------- figures / tables
FIG_REG: list[dict] = []
TAB_REG: list[dict] = []

CHAPTER_STATE = {"current": 1}


class Fig(Flowable):
    """A vector diagram drawn by ``fn(canvas, width, height)`` + caption below."""

    def __init__(self, num, caption, draw_fn, height, width=TEXT_W, note=None):
        super().__init__()
        self.num = str(num)
        self.caption = caption
        self.fn = draw_fn
        self.width = width
        self.height = height
        self.note = note

    def wrap(self, aw, ah):
        return (min(self.width, aw), self.height)

    def draw(self):
        self.canv.saveState()
        self.fn(self.canv, self.width, self.height)
        self.canv.restoreState()


def figure(num, caption, draw_fn, height, note=None, width=TEXT_W):
    """Return a KeepTogether block: diagram + caption (+ optional note)."""
    FIG_REG.append({"num": str(num), "caption": caption, "key": f"fig:{num}"})
    parts = [Marker(f"fig:{num}"), Spacer(1, 6),
             Fig(num, caption, draw_fn, height, width),
             Paragraph(f"Figure {num}: {caption}", S["fig_cap"])]
    if note:
        parts.append(Paragraph(note, S["fig_note"]))
    parts.append(Spacer(1, 4))
    return KeepTogether(parts)


def table(num, caption, data, col_widths, align="LEFT", header=True,
          font_size=10, zebra=True, span_rows=None, extra_style=None,
          valign="MIDDLE", keep=True, pad=3.4, header_size=None):
    """Return a KeepTogether block: caption above + ruled table."""
    TAB_REG.append({"num": str(num), "caption": caption, "key": f"tab:{num}"})

    hstyle = S["cell_h"] if header_size is None else ParagraphStyle(
        "cell_h2", parent=S["cell_h"], fontSize=header_size, leading=header_size + 1.6)
    rows = []
    for r_i, row in enumerate(data):
        cells = []
        for c_i, cell in enumerate(row):
            if isinstance(cell, str):
                if header and r_i == 0:
                    st = hstyle
                elif c_i == 0 and align == "CENTER":
                    st = S["cell_c"]
                else:
                    st = S["cell"] if align == "LEFT" else S["cell_c"]
                cells.append(Paragraph(cell, st))
            else:
                cells.append(cell)
        rows.append(cells)

    t = Table(rows, colWidths=col_widths, repeatRows=1 if header else 0,
              hAlign="CENTER")
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), valign),
        ("GRID", (0, 0), (-1, -1), 0.4, GREY),
        ("LINEBELOW", (0, 0), (-1, 0), 0.9, INK),
        ("LINEABOVE", (0, 0), (-1, 0), 0.9, INK),
        ("TOPPADDING", (0, 0), (-1, -1), pad),
        ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        cmds += [("BACKGROUND", (0, 0), (-1, 0), NAVY),
                 ("LINEBELOW", (0, 0), (-1, 0), 0.9, INK)]
    if zebra:
        for i in range(1, len(data)):
            if i % 2 == 0:
                cmds.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    if span_rows:
        for (r, c1, c2) in span_rows:
            cmds.append(("SPAN", (c1, r), (c2, r)))
    if extra_style:
        cmds += extra_style
    t.setStyle(TableStyle(cmds))
    block = [Marker(f"tab:{num}"),
             Paragraph(f"Table {num}: {caption}", S["tab_cap"]),
             t, Spacer(1, 10)]
    # a long table cannot be kept on one page without stranding the page before
    # it, so only short tables are pinned; long ones split and repeat the header
    # always returns a list so callers can use story.extend(...)
    if keep and len(data) <= 6:
        return [KeepTogether(block)]
    return block


# --------------------------------------------------------------------------- heading helpers
CHAPTERS: list[dict] = []


def chapter(number: str, title: str, page_break=True):
    CHAPTERS.append({"level": 1, "label": f"Chapter {number}.",
                     "title": title.upper(), "key": f"ch{number}"})
    out = []
    if page_break:
        out.append(PageBreakLite())
    out.append(Spacer(1, 6))
    out.append(Marker(f"ch{number}"))
    out.append(P(f"CHAPTER {number}", "chapter_no"))
    out.append(P(title.upper(), "chapter"))
    return out


def h1(number: str, text: str):
    CHAPTERS.append({"level": 2, "label": number, "title": text, "key": f"h{number}"})
    return [Marker(f"h{number}"), P(f"{number}. {text}", "h1")]


def h2(number: str, text: str, numbered=True):
    CHAPTERS.append({"level": 3, "label": number, "title": text, "key": f"h{number}"})
    label = f"{number}." if numbered else number
    return [Marker(f"h{number}"), P(f"{label} {text}", "h2")]


def front_entry(label: str, key_name: str, level: int = 2):
    CHAPTERS.append({"level": level, "label": "", "title": label, "key": key_name})


def PageBreakLite():
    from reportlab.platypus import PageBreak
    return PageBreak()


# --------------------------------------------------------------------------- page decoration
class PageState:
    front_pages = 12       # physical pages before Chapter 1 (updated after pass 1)


def to_roman(n: int) -> str:
    vals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"),
            (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"),
            (5, "v"), (4, "iv"), (1, "i")]
    out = ""
    for v, sym in vals:
        while n >= v:
            out += sym
            n -= v
    return out


def page_label(physical: int) -> str:
    if physical <= PageState.front_pages:
        return to_roman(physical)
    return str(physical - PageState.front_pages)


def _on_page(canvas, doc):
    canvas.saveState()
    n = canvas.getPageNumber()
    if n <= 2:                      # title page + bonafide certificate: no number
        canvas.restoreState()
        return
    canvas.setFont(FONT, 10)
    canvas.setFillColor(INK)
    canvas.drawCentredString(PAGE_W / 2.0, 0.62 * inch, page_label(n))
    # thin rule under the text block
    canvas.setStrokeColor(MID)
    canvas.setLineWidth(0.4)
    canvas.line(ML, 0.85 * inch, PAGE_W - MR, 0.85 * inch)
    canvas.restoreState()


# --------------------------------------------------------------------------- TOC renderer
class TocBlock(Flowable):
    """Manually rendered contents list with dot leaders and page labels."""

    def __init__(self, entries, page_map, width=TEXT_W, indent=0, start=0, end=None):
        super().__init__()
        self.entries = entries        # list of dicts: level, label, title, key
        self.page_map = page_map
        self.width = width
        self.line_h = 16.4
        self.indent = indent
        self.start = start
        self.end = len(entries) if end is None else end

    def _visible(self):
        return self.entries[self.start:self.end]

    def wrap(self, aw, ah):
        self.width = min(self.width, aw)
        self.height = self.line_h * len(self._visible())
        return (self.width, self.height)

    def split(self, availWidth, availHeight):
        n_fit = int(availHeight // self.line_h)
        total = self.end - self.start
        if n_fit < 1 or n_fit >= total:
            return []
        cut = self.start + n_fit
        head = TocBlock(self.entries, self.page_map, self.width, self.indent,
                        self.start, cut)
        tail = TocBlock(self.entries, self.page_map, self.width, self.indent,
                        cut, self.end)
        return [head, tail]

    def draw(self):
        c = self.canv
        y = self.height
        for e in self._visible():
            y -= self.line_h
            lvl = e["level"]
            font = FONT_B if lvl <= 2 else FONT
            size = 11 if lvl <= 2 else 10.5
            left = {1: 0, 2: 14, 3: 30}.get(lvl, 14)
            text = (e["label"] + "  " if e["label"] else "") + e["title"]
            if lvl == 1:
                text = text.upper() if e["title"].isupper() is False else text
            phys = self.page_map.get(e["key"])
            page = page_label(phys) if phys else ""
            c.setFont(font, size)
            c.setFillColor(INK)
            baseline = y + 4.5
            pw = stringWidth(page, font, size)
            # trim the label if it would collide with the page number
            limit = self.width - pw - 14
            tw = stringWidth(text, font, size)
            if left + tw > limit:
                trimmed = text
                while trimmed and stringWidth(trimmed + "\u2026", font, size) > limit - left:
                    trimmed = trimmed[:-1]
                text = trimmed.rstrip() + "\u2026"
                tw = stringWidth(text, font, size)
            c.drawString(left, baseline, text)
            dot_start = left + tw + 5
            dot_end = self.width - pw - 6
            if dot_end > dot_start:
                c.setFont(FONT, size)
                c.setFillColor(GREY)
                x = dot_start
                while x < dot_end:
                    c.drawString(x, baseline, ".")
                    x += 3.0
            c.setFont(font, size)
            c.setFillColor(INK)
            c.drawRightString(self.width, baseline, page)


def toc_block(entries, page_map):
    return TocBlock(entries, page_map)


def lof_block(page_map):
    ents = [{"level": 2, "label": "", "title": f"Figure {f['num']}: {f['caption']}",
             "key": f["key"]} for f in FIG_REG]
    return TocBlock(ents, page_map, indent=0)


def lot_block(page_map):
    ents = [{"level": 2, "label": "", "title": f"Table {t['num']}: {t['caption']}",
             "key": t["key"]} for t in TAB_REG]
    return TocBlock(ents, page_map, indent=0)


# --------------------------------------------------------------------------- document
class ReportDoc(BaseDocTemplate):
    def __init__(self, filename, **kw):
        super().__init__(filename, pagesize=A4,
                         leftMargin=ML, rightMargin=MR,
                         topMargin=MT, bottomMargin=MB,
                         title="Multi-Orchestration with MCP Server - Project Report",
                         author="Project Report", **kw)
        frame = Frame(ML, MB, TEXT_W, PAGE_H - MT - MB, id="main",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=_on_page)])
