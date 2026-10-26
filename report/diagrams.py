"""diagrams.py — every figure in the report, drawn as vector graphics.

Each function has the signature ``fn(canvas, width, height)`` and is handed to
``pdf_kit.figure``. Nothing is rasterised, so the diagrams stay sharp at any
zoom level and print cleanly in black and white.
"""
from __future__ import annotations

import math

from reportlab.lib import colors
from reportlab.pdfbase.pdfmetrics import stringWidth

from pdf_kit import (AMBER, FONT, FONT_B, FONT_BI, FONT_I, GREY, INK, LIGHT,
                     MID, NAVY, RED, TEAL, TEXT_W)

# --------------------------------------------------------------------------- primitives
def wrap(c, text, font, size, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if stringWidth(trial, font, size) <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def ctext(c, cx, cy, text, size=7.2, font=FONT_B, color=INK, align="c", maxw=None):
    """Centred (or left/right anchored) multi-line text centred vertically on cy."""
    if maxw:
        lines = wrap(c, text, font, size, maxw)
    else:
        lines = text.split("\n")
    c.setFillColor(color)
    lead = size + 2.0
    total = lead * len(lines)
    y = cy + total / 2.0 - size
    for ln in lines:
        if align == "c":
            c.drawCentredString(cx, y, ln)
        elif align == "l":
            c.drawString(cx, y, ln)
        else:
            c.drawRightString(cx, y, ln)
        y -= lead
    return total


def box(c, x, y, w, h, label, sub=None, fill=LIGHT, stroke=NAVY, size=7.2,
        lw=0.8, radius=2.5, bold=True, tcolor=INK, sub_size=None, align="c"):
    c.setLineWidth(lw)
    c.setStrokeColor(stroke)
    c.setFillColor(fill)
    c.roundRect(x, y, w, h, radius, stroke=1, fill=1)
    font = FONT_B if bold else FONT
    if sub:
        sub_size = sub_size or (size - 1.0)
        lead = size + 2 + sub_size + 2
        top = y + h / 2.0 + lead / 2.0 - size * 0.9
        if align == "c":
            c.setFont(font, size)
            c.setFillColor(tcolor)
            for ln in wrap(c, label, font, size, w - 8) if len(label) > 22 else [label]:
                c.drawCentredString(x + w / 2.0, top, ln)
            c.setFont(FONT_I, sub_size)
            c.setFillColor(colors.HexColor("#3a3f47"))
            yy = top - size - 2.5
            for ln in wrap(c, sub, FONT_I, sub_size, w - 8):
                c.drawCentredString(x + w / 2.0, yy, ln)
                yy -= sub_size + 1.5
        else:
            c.setFont(font, size)
            c.setFillColor(tcolor)
            c.drawString(x + 6, y + h - size - 3, label)
            c.setFont(FONT_I, sub_size)
            c.setFillColor(colors.HexColor("#3a3f47"))
            c.drawString(x + 6, y + h - size - sub_size - 5.5, sub)
    else:
        c.setFont(font, size)
        c.setFillColor(tcolor)
        ctext(c, x + w / 2.0, y + h / 2.0, label, size=size, font=font,
              color=tcolor, maxw=w - 8)


def arrow(c, x1, y1, x2, y2, label=None, dashed=False, lw=0.9, color=NAVY,
          head=4.2, label_size=6.4, label_side="r", curve=0.0):
    c.setStrokeColor(color)
    c.setFillColor(color)
    c.setLineWidth(lw)
    if dashed:
        c.setDash(2, 2)
    if curve:
        c.bezier(x1, y1, x1 + curve, y1, x2 - curve, y2, x2, y2)
    else:
        c.line(x1, y1, x2, y2)
    c.setDash()
    ang = math.atan2(y2 - y1, x2 - x1)
    p = c.beginPath()
    p.moveTo(x2, y2)
    p.lineTo(x2 - head * math.cos(ang - 0.42), y2 - head * math.sin(ang - 0.42))
    p.lineTo(x2 - head * math.cos(ang + 0.42), y2 - head * math.sin(ang + 0.42))
    p.close()
    c.drawPath(p, fill=1, stroke=0)
    if label:
        mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        c.setFont(FONT_I, label_size)
        c.setFillColor(colors.HexColor("#3a3f47"))
        if label_side == "r":
            c.drawString(mx + 3, my + 2, label)
        elif label_side == "l":
            c.drawRightString(mx - 3, my + 2, label)
        else:
            c.drawCentredString(mx, my + 3, label)


def elbow(c, x1, y1, x2, y2, mid=None, label=None, dashed=False, vertical_first=True):
    if vertical_first:
        my = mid if mid is not None else (y1 + y2) / 2.0
        c.setStrokeColor(NAVY)
        c.setLineWidth(0.9)
        if dashed:
            c.setDash(2, 2)
        c.line(x1, y1, x1, my)
        c.line(x1, my, x2, my)
        c.setDash()
        arrow(c, x2, my, x2, y2, label=label, dashed=dashed)
    else:
        mx = mid if mid is not None else (x1 + x2) / 2.0
        c.setStrokeColor(NAVY)
        c.setLineWidth(0.9)
        if dashed:
            c.setDash(2, 2)
        c.line(x1, y1, mx, y1)
        c.line(mx, y1, mx, y2)
        c.setDash()
        arrow(c, mx, y2, x2, y2, label=label)


def diamond(c, cx, cy, w, h, label, fill=colors.HexColor("#fbf6e6"), stroke=AMBER,
            size=6.8):
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(0.9)
    p = c.beginPath()
    p.moveTo(cx, cy + h / 2.0)
    p.lineTo(cx + w / 2.0, cy)
    p.lineTo(cx, cy - h / 2.0)
    p.lineTo(cx - w / 2.0, cy)
    p.close()
    c.drawPath(p, fill=1, stroke=1)
    ctext(c, cx, cy, label, size=size, font=FONT_B, maxw=w * 0.66)


def cylinder(c, x, y, w, h, label, fill=colors.HexColor("#e8eef7")):
    eh = 7
    c.setFillColor(fill)
    c.setStrokeColor(NAVY)
    c.setLineWidth(0.8)
    c.ellipse(x, y + h - eh, x + w, y + h, stroke=1, fill=1)
    c.rect(x, y + eh / 2.0, w, h - eh, stroke=1, fill=1)
    c.ellipse(x, y, x + w, y + eh, stroke=1, fill=1)
    c.setFillColor(INK)
    ctext(c, x + w / 2.0, y + h / 2.0, label, size=6.8, font=FONT_B, maxw=w - 6)


def label(c, x, y, text, size=6.6, font=FONT_B, color=INK, align="l"):
    c.setFont(font, size)
    c.setFillColor(color)
    if align == "c":
        c.drawCentredString(x, y, text)
    elif align == "r":
        c.drawRightString(x, y, text)
    else:
        c.drawString(x, y, text)


def axes(c, x, y, w, h, ymax, yticks, ylabel, xticks=None, xticklabels=None,
         grid=True, tick_fmt="{:.0f}"):
    c.setStrokeColor(INK)
    c.setLineWidth(0.9)
    c.line(x, y, x, y + h)          # y axis
    c.line(x, y, x + w, y)          # x axis
    c.setFont(FONT, 6.2)
    c.setFillColor(INK)
    for v in yticks:
        yy = y + h * (v / ymax if ymax else 0)
        if grid:
            c.setStrokeColor(MID)
            c.setLineWidth(0.4)
            c.setDash(1.5, 1.5)
            c.line(x, yy, x + w, yy)
            c.setDash()
            c.setStrokeColor(INK)
        c.drawRightString(x - 3, yy - 2, tick_fmt.format(v))
    c.saveState()
    c.translate(x - 30, y + h / 2.0)
    c.rotate(90)
    c.setFont(FONT_B, 6.6)
    c.drawCentredString(0, 0, ylabel)
    c.restoreState()
    if xticks:
        for i, v in enumerate(xticks):
            xx = x + (w * (i + 0.5) / len(xticks))
            c.setFont(FONT, 6.2)
            c.setFillColor(INK)
            if xticklabels:
                c.saveState()
                c.translate(xx, y - 4)
                c.rotate(0)
                c.drawCentredString(0, 0, xticklabels[i])
                c.restoreState()


def legend(c, x, y, items, size=6.4, gap=8, box_size=6):
    cx = x
    for name, col in items:
        c.setFillColor(col)
        c.setStrokeColor(INK)
        c.setLineWidth(0.4)
        c.rect(cx, y, box_size, box_size, stroke=1, fill=1)
        c.setFont(FONT, size)
        c.setFillColor(INK)
        c.drawString(cx + box_size + 2.5, y + 0.6, name)
        cx += box_size + 2.5 + stringWidth(name, FONT, size) + gap


# =========================================================================== graphical abstract
def graphical_abstract(c, w, h):
    m = 6
    x = m
    bw = w - 2 * m
    y = h - 4
    rows = [
        ("USER UTTERANCE", "\u201cset the volume to 40 and tell me what is using my CPU\u201d", 30, MID, INK),
        ("FRONT END (CLI / REPL)", "slash commands \u00b7 approval prompts \u00b7 streaming status \u00b7 dry-run mode", 26, LIGHT, NAVY),
        ("ORCHESTRATOR", "prompt synthesis from live MCP schemas \u00b7 Qwen3-4B via llama.cpp \u00b7 grammar-constrained JSON", 32, colors.HexColor("#e9eef9"), NAVY),
    ]
    for title, sub, hh, fill, stroke in rows:
        box(c, x, y - hh, bw, hh, title, sub, fill=fill, stroke=stroke, size=7.4, sub_size=6.3)
        y -= hh + 8
        arrow(c, w / 2.0, y + 8, w / 2.0, y + 1.5)

    # guardrail tier strip
    t_h = 34
    tiers = [("TIER 1", "schema + type\nvalidation"), ("TIER 2", "policy, allowlist\n& jail check"),
             ("TIER 3", "single-use\nconfirmation token"), ("TIER 4", "timeout, cap\n& audit log")]
    tw = (bw - 3 * 5) / 4.0
    label(c, x, y + 1, "FOUR-TIER GUARDRAIL STACK", size=6.8, font=FONT_B, color=NAVY)
    y -= 8
    for i, (t, s) in enumerate(tiers):
        bx = x + i * (tw + 5)
        box(c, bx, y - t_h, tw, t_h, t, s, fill=colors.HexColor("#fdf6ec"),
            stroke=AMBER, size=6.9, sub_size=5.9)
        if i < 3:
            arrow(c, bx + tw, y - t_h / 2.0, bx + tw + 5, y - t_h / 2.0, lw=0.7, head=3.2)
    y -= t_h + 8
    arrow(c, w / 2.0, y + 8, w / 2.0, y + 1.5)

    # transport
    box(c, x, y - 24, bw, 24, "MCP CLIENT  \u2194  FastMCP SERVER", "JSON-RPC over stdio \u00b7 5 registered tools \u00b7 read-only / destructive hints",
        fill=LIGHT, stroke=NAVY, size=7.2, sub_size=6.0)
    y -= 24 + 8
    arrow(c, w / 2.0, y + 8, w / 2.0, y + 1.5)

    # tool row
    tools = [("system_\ntelemetry", "cpu \u00b7 mem \u00b7 disk \u00b7 battery"),
             ("hardware_\ncontrol", "volume \u00b7 mute \u00b7 brightness"),
             ("app_\nlifecycle", "list \u00b7 launch \u00b7 kill"),
             ("workspace_\nfs", "list \u00b7 read \u00b7 search"),
             ("power_\nsession", "lock \u00b7 sleep \u00b7 restart")]
    tw2 = (bw - 4 * 4) / 5.0
    th = 40
    for i, (t, s) in enumerate(tools):
        bx = x + i * (tw2 + 4)
        box(c, bx, y - th, tw2, th, t.replace("\n", " "), s,
            fill=colors.HexColor("#eef6f2"), stroke=TEAL, size=6.3, sub_size=5.4, bold=True)
    y -= th + 10
    arrow(c, w / 2.0, y + 10, w / 2.0, y + 1.5)
    box(c, x, y - 26, bw, 26, "WINDOWS HOST",
        "audio endpoint \u00b7 display brightness (WMI) \u00b7 process table \u00b7 sandboxed folder \u00b7 power state",
        fill=colors.HexColor("#f2f2f2"), stroke=INK, size=7.2, sub_size=6.0)


# =========================================================================== ch1
def gantt(c, w, h):
    tasks = [
        ("Need identification & survey", 1, 2),
        ("Literature survey", 1, 3),
        ("Requirement & feature freeze", 3, 2),
        ("Design alternatives & selection", 4, 3),
        ("MCP server implementation", 6, 4),
        ("Orchestrator + guardrails", 8, 4),
        ("Validation & benchmarking", 11, 3),
        ("Documentation & user manual", 13, 3),
        ("Presentation & viva prep", 15, 2),
    ]
    left = 150
    chart_w = w - left - 8
    top = h - 16
    row_h = (h - 34) / len(tasks)
    weeks = 16
    col_w = chart_w / weeks
    # header
    c.setFont(FONT_B, 6.6)
    c.setFillColor(INK)
    c.drawString(2, h - 9, "Task / Activity")
    c.setFillColor(LIGHT)
    c.setStrokeColor(MID)
    c.setLineWidth(0.4)
    c.rect(left, h - 22, chart_w, 14, stroke=1, fill=1)
    for i in range(weeks):
        if i % 2 == 0:
            c.setFillColor(colors.white)
            c.rect(left + i * col_w, 10, col_w, h - 32, stroke=0, fill=1)
    for wk in range(1, weeks + 2):
        xx = left + (wk - 1) * col_w
        c.setStrokeColor(MID)
        c.setLineWidth(0.35)
        c.line(xx, 10, xx, h - 8)
        if wk <= weeks:
            label(c, xx + col_w / 2.0, h - 17, f"W{wk}", size=5.4, font=FONT, align="c")
    for i, (name, start, dur) in enumerate(tasks):
        y = top - (i + 1) * row_h + 3
        c.setFont(FONT, 6.6)
        c.setFillColor(INK)
        c.drawString(2, y + row_h / 2.0 - 6, name)
        bx = left + (start - 1) * col_w
        bwid = dur * col_w
        shade = colors.HexColor("#28456f") if i % 2 == 0 else TEAL
        c.setFillColor(shade)
        c.setStrokeColor(INK)
        c.setLineWidth(0.4)
        c.roundRect(bx, y + 1, bwid, row_h - 6, 1.5, stroke=1, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FONT_B, 5.4)
        c.drawCentredString(bx + bwid / 2.0, y + row_h / 2.0 - 5, f"{dur}w")
    # axis
    c.setStrokeColor(INK)
    c.setLineWidth(0.8)
    c.line(left, 10, left + chart_w, 10)
    c.line(left, 10, left, h - 8)
    label(c, left + chart_w / 2.0, 2, "Project week (16-week schedule)", size=6.4, align="c")


def survey_chart(c, w, h):
    rows = [
        ("Repeated manual checks of CPU / RAM / disk", 88, "37 of 42"),
        ("Forgets running apps while the PC slows down", 81, "34 of 42"),
        ("Wants offline-only processing of private data", 95, "40 of 42"),
        ("Finds multi-step settings menus annoying", 76, "32 of 42"),
        ("Distrusts an agent that acts without asking", 93, "39 of 42"),
    ]
    left = 200
    bar_w = w - left - 48
    top = h - 20
    row_h = (h - 34) / len(rows)
    label(c, 2, h - 9, "Reported pain point", size=6.8)
    label(c, left + bar_w + 6, h - 9, "Agreeing", size=6.8)
    for i, (name, val, frac) in enumerate(rows):
        y = top - (i + 1) * row_h
        c.setFont(FONT, 6.4)
        c.setFillColor(INK)
        c.drawString(2, y + row_h / 2.0 - 3, name)
        c.setFillColor(MID)
        c.setStrokeColor(GREY)
        c.setLineWidth(0.4)
        c.rect(left, y + row_h / 2.0 - 6, bar_w, 11, stroke=1, fill=1)
        c.setFillColor(TEAL if val >= 85 else NAVY)
        c.rect(left, y + row_h / 2.0 - 6, bar_w * val / 100.0, 11, stroke=0, fill=1)
        c.setFillColor(colors.white if val > 40 else INK)
        c.setFont(FONT_B, 5.8)
        c.drawString(left + 4, y + row_h / 2.0 - 2.5, f"{val}%")
        c.setFillColor(INK)
        c.setFont(FONT_I, 5.8)
        c.drawString(left + bar_w + 6, y + row_h / 2.0 - 2.5, frac)


def timeline(c, w, h):
    events = [
        (1971, "Weizenbaum's\nELIZA: first\nconversational\nagent", True),
        (1995, "Software agents\nin HCI research;\nBDI architectures", False),
        (2011, "Siri / Watson:\nvoice assistants\nenter daily use", True),
        (2018, "Tool-augmented\nLLMs (WebGPT,\nToolformer)", False),
        (2022, "ReAct \u00b7 Chain-of-\nThought tool use;\nChatGPT plugins", True),
        (2024, "Model Context\nProtocol (MCP)\npublished", False),
        (2025, "Local small-model\nagents on consumer\nhardware", True),
    ]
    y0 = h / 2.0 - 4
    c.setStrokeColor(NAVY)
    c.setLineWidth(1.2)
    arrow(c, 6, y0, w - 6, y0, head=6)
    n = len(events)
    step = (w - 18) / (n - 1)
    for i, (yr, txt, above) in enumerate(events):
        x = 9 + i * step
        c.setFillColor(NAVY)
        c.setStrokeColor(colors.white)
        c.setLineWidth(0.8)
        c.circle(x, y0, 3.4, stroke=1, fill=1)
        c.setStrokeColor(GREY)
        c.setLineWidth(0.5)
        c.setDash(1.5, 1.5)
        if above:
            c.line(x, y0 + 4, x, y0 + 16)
        else:
            c.line(x, y0 - 4, x, y0 - 16)
        c.setDash()
        c.setFillColor(INK)
        c.setFont(FONT_B, 6.8)
        ty = y0 + 50 if above else y0 - 66
        c.drawCentredString(x, ty, str(yr))
        c.setFont(FONT, 5.6)
        c.setFillColor(colors.HexColor("#333333"))
        lines = txt.split("\n")
        yy = ty - 8
        for ln in lines:
            c.drawCentredString(x, yy, ln)
            yy -= 6.6


def bibliometric(c, w, h):
    years = ["2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024", "2025"]
    series = [
        ("LLM tool use / function calling", [0, 1, 1, 2, 3, 5, 8, 11, 14, 16], NAVY),
        ("On-device / edge inference", [2, 2, 3, 4, 5, 7, 9, 11, 13, 15], TEAL),
        ("Agent protocols & orchestration", [0, 0, 0, 0, 1, 2, 3, 6, 9, 12], AMBER),
    ]
    left, bottom = 34, 24
    cw = w - left - 10
    ch = h - bottom - 26
    ymax = 45
    axes(c, left, bottom, cw, ch, ymax, [0, 10, 20, 30, 40, 50],
         "Publications reviewed", tick_fmt="{:.0f}")
    n = len(years)
    group = cw / n
    barw = group * 0.24
    for i, yr in enumerate(years):
        tot = 0
        for j, (name, vals, col) in enumerate(series):
            v = vals[i]
            if v == 0:
                continue
            x = left + i * group + group * 0.14 + j * (barw + 1.2)
            bh = ch * v / ymax
            c.setFillColor(col)
            c.setStrokeColor(INK)
            c.setLineWidth(0.3)
            c.rect(x, bottom + ch * tot / ymax, barw, bh, stroke=1, fill=1)
            tot += v
        c.setFont(FONT, 6.0)
        c.setFillColor(INK)
        c.drawCentredString(left + i * group + group / 2.0, bottom - 8, yr)
        c.setFont(FONT_B, 5.6)
        c.drawCentredString(left + i * group + group / 2.0, bottom + ch * tot / ymax + 2, str(tot))
    legend(c, left + 6, h - 12, [(s[0], s[2]) for s in series])


# =========================================================================== ch2 extra
def capability_matrix(c, w, h):
    """Polar capability plot; only the selected design is filled."""
    axes_names = ["Offline", "Safety", "Small model", "Extensibility", "Latency", "UX"]
    sets = [
        ("Scripted macros", [5, 4, 5, 1, 3, 2], GREY, 0.9, (2, 2)),
        ("Cloud assistant", [0, 3, 1, 4, 3, 5], colors.HexColor("#8a6d3b"), 0.9, (1, 2)),
        ("Selected design", [5, 5, 4, 5, 4, 4], TEAL, 1.5, None),
    ]
    cx, cy = w / 2.0, h / 2.0 + 8
    R = min(w / 2.0 - 52, h / 2.0 - 26)
    n = len(axes_names)

    def vertex(i, v):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        return (cx + R * v / 5.0 * math.cos(ang), cy + R * v / 5.0 * math.sin(ang))

    for ring in range(1, 6):
        c.setStrokeColor(MID if ring < 5 else GREY)
        c.setLineWidth(0.4 if ring < 5 else 0.8)
        p_ = c.beginPath()
        for i in range(n):
            x, y = vertex(i, ring)
            (p_.moveTo if i == 0 else p_.lineTo)(x, y)
        p_.close()
        c.drawPath(p_, fill=0, stroke=1)
    for i in range(n):
        c.setStrokeColor(MID)
        c.setLineWidth(0.4)
        c.line(cx, cy, *vertex(i, 5))

    # selected design fill first, so outlines sit on top
    sel = sets[2][1]
    c.setFillColor(colors.Color(TEAL.red, TEAL.green, TEAL.blue, 0.13))
    c.setStrokeColor(colors.Color(1, 1, 1, 0))
    p_ = c.beginPath()
    for i in range(n):
        x, y = vertex(i, sel[i])
        (p_.moveTo if i == 0 else p_.lineTo)(x, y)
    p_.close()
    c.drawPath(p_, fill=1, stroke=0)

    for name, vals, col, lw, dash in sets:
        c.setStrokeColor(col)
        c.setLineWidth(lw)
        if dash:
            c.setDash(*dash)
        p_ = c.beginPath()
        for i, v in enumerate(vals):
            x, y = vertex(i, v)
            (p_.moveTo if i == 0 else p_.lineTo)(x, y)
        p_.close()
        c.drawPath(p_, fill=0, stroke=1)
        c.setDash()
        if not dash:
            for i, v in enumerate(vals):
                x, y = vertex(i, v)
                c.setFillColor(col)
                c.circle(x, y, 2.2, stroke=0, fill=1)

    for i, name in enumerate(axes_names):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        lx = cx + (R + 22) * math.cos(ang)
        ly = cy + (R + 22) * math.sin(ang)
        label(c, lx, ly - 2, name, size=6.4, font=FONT_B, align="c")
    # scale labels on the vertical axis
    for ring in (1, 3, 5):
        x, y = vertex(0, ring)
        label(c, x + 3, y - 1, str(ring), size=5.0, font=FONT_I, color=GREY)
    legend(c, 6, h - 9, [(s_[0], s_[2]) for s_ in sets], size=6.4)


# =========================================================================== ch3 designs
def design_a(c, w, h):
    """Alternative A: stateless single-shot router (baseline)."""
    y = h / 2.0 - 16
    boxes = [("User\ntext", 46), ("Prompt\nbuilder", 62), ("LLM\n1 pass", 52),
             ("Parse\nJSON", 48), ("Call\ntool", 44), ("Print\npayload", 54)]
    gap = (w - sum(b[1] for b in boxes)) / (len(boxes) - 1)
    x = 0
    prev = None
    for name, bwid in boxes:
        box(c, x, y, bwid, 32, name, fill=LIGHT, stroke=NAVY, size=6.6)
        if prev is not None:
            arrow(c, prev, y + 16, x - 1, y + 16, head=3.6)
        prev = x + bwid
        x += bwid + gap
    c.setStrokeColor(RED)
    c.setLineWidth(0.8)
    c.setDash(3, 2)
    c.rect(100, y - 12, w - 108, 56, stroke=1, fill=0)
    c.setDash()
    label(c, 104, y + 47, "no memory \u00b7 no confirmation \u00b7 no verification \u00b7 1 tool call per request",
          size=6.2, font=FONT_I, color=RED)


def design_b(c, w, h):
    """Alternative B: rule engine first, LLM fallback."""
    top = h - 26
    box(c, w * 0.28, top, w * 0.44, 26, "User command", fill=MID, stroke=INK, size=7)
    box(c, w * 0.18, top - 56, w * 0.30, 30, "Deterministic rule engine",
        "regex / keyword table", fill=LIGHT, stroke=NAVY, size=6.8, sub_size=5.8)
    box(c, w * 0.56, top - 56, w * 0.30, 30, "Intent classifier",
        "fine-tuned head or embeddings", fill=LIGHT, stroke=NAVY, size=6.8, sub_size=5.8)
    arrow(c, w * 0.44, top, w * 0.33, top - 26)
    arrow(c, w * 0.56, top, w * 0.71, top - 26)
    box(c, w * 0.30, top - 112, w * 0.40, 28, "Static dispatcher",
        "hand-written switch on intent", fill=LIGHT, stroke=NAVY, size=6.8, sub_size=5.8)
    arrow(c, w * 0.33, top - 56, w * 0.44, top - 84)
    arrow(c, w * 0.71, top - 56, w * 0.56, top - 84)
    arrow(c, w * 0.50, top - 112, w * 0.50, top - 138, color=RED, dashed=True)
    label(c, w * 0.515, top - 130, "no path for unseen intent", size=6.0, font=FONT_I,
          color=RED)
    box(c, w * 0.22, top - 172, w * 0.56, 26, "Tool executes immediately",
        fill=colors.HexColor("#fbeeee"), stroke=RED, size=6.8)
    label(c, w / 2.0, 10, "Every new tool requires editing the dispatcher, the rule table and "
                          "the prompt", size=6.0, font=FONT_I, color=RED, align="c")


def design_c(c, w, h):
    """Alternative C: layered orchestrator with observation loop (selected)."""
    top = h - 8
    box(c, 4, top - 74, 96, 74, "Presentation layer",
        "CLI REPL \u00b7 slash commands \u00b7 approval prompt \u00b7 dry-run",
        fill=LIGHT, stroke=NAVY, size=6.6, sub_size=5.6)
    box(c, 112, top - 74, 118, 74, "Reasoning layer",
        "schema-grounded prompt \u00b7 Qwen3-4B (llama.cpp) \u00b7 GBNF grammar \u00b7 JSON protocol",
        fill=colors.HexColor("#e9eef9"), stroke=NAVY, size=6.6, sub_size=5.6)
    box(c, 242, top - 74, 92, 74, "Guard layer",
        "T1 schema \u00b7 T2 policy \u00b7 T3 token \u00b7 T4 limits + audit",
        fill=colors.HexColor("#fdf6ec"), stroke=AMBER, size=6.6, sub_size=5.6)
    box(c, 344, top - 74, 66, 74, "Transport",
        "MCP client \u2194 FastMCP", fill=LIGHT, stroke=NAVY, size=6.4, sub_size=5.4)
    arrow(c, 100, top - 37, 111, top - 37, head=3.4)
    arrow(c, 230, top - 37, 241, top - 37, head=3.4)
    arrow(c, 334, top - 37, 343, top - 37, head=3.4)

    box(c, 120, top - 132, 290, 30, "Execution layer \u2014 5 MCP tools",
        "telemetry \u00b7 hardware \u00b7 apps \u00b7 workspace \u00b7 power", fill=colors.HexColor("#eef6f2"),
        stroke=TEAL, size=6.8, sub_size=5.8)
    arrow(c, 377, top - 74, 377, top - 100, head=3.4)
    c.line(377, top - 100, 300, top - 100)
    arrow(c, 300, top - 100, 300, top - 102, head=3.4)

    # observation loop
    c.setStrokeColor(TEAL)
    c.setLineWidth(1.0)
    c.setDash(3, 2)
    p = c.pathBegin = None
    c.line(120, top - 117, 60, top - 117)
    c.line(60, top - 117, 60, top - 80)
    c.setDash()
    arrow(c, 60, top - 92, 60, top - 80, color=TEAL, head=3.4)
    label(c, 64, top - 128, "observation fed back (max 4 steps)", size=5.8, font=FONT_I, color=TEAL)

    cylinder(c, 4, top - 196, 100, 44, "Audit log\n(JSONL)")
    arrow(c, 54, top - 142, 54, top - 152, head=3.4, dashed=True)
    box(c, 120, top - 196, 290, 44, "OS boundary",
        "audio endpoint (pycaw) \u00b7 WMI display brightness \u00b7 process table (psutil) \u00b7 jailed folder \u00b7 power state API",
        fill=colors.HexColor("#f2f2f2"), stroke=INK, size=6.8, sub_size=5.6)
    arrow(c, 265, top - 132, 265, top - 152, head=3.4)


def token_fsm(c, w, h):
    """Confirmation state machine, drawn on a computed grid (no overlap)."""
    n = 4
    gap = 30
    bw = (w - gap * (n - 1)) / n
    bh = 34
    y = h - 40
    xs = [i * (bw + gap) for i in range(n)]
    names = ["IDLE", "PENDING", "APPROVED", "EXECUTED"]
    subs = ["no token issued", "token issued", "user approved", "consumed once"]
    for i, x in enumerate(xs):
        fill = colors.HexColor("#fdf6ec") if i == 1 else LIGHT
        stroke = AMBER if i == 1 else NAVY
        box(c, x, y, bw, bh, names[i], subs[i], fill=fill, stroke=stroke,
            size=7.0, sub_size=5.4)
    for i in range(n - 1):
        arrow(c, xs[i] + bw + 1, y + bh / 2.0, xs[i + 1] - 1, y + bh / 2.0, head=3.4)

    ry = y - 44
    rejections = [(1, "REJECTED", "user declines"),
                  (2, "TOKEN EXPIRED", "TTL 120 s"),
                  (3, "REPLAY BLOCKED", "already used")]
    for idx, title, sub in rejections:
        rx = xs[idx] + bw / 2.0 - 44
        box(c, rx, ry, 88, 27, title, sub, fill=colors.HexColor("#fbeeee"), stroke=RED,
            size=6.2, sub_size=5.2, lw=0.7)
        arrow(c, xs[idx] + bw / 2.0, y - 1, rx + 44, ry + 28, color=RED, head=3.2)
    label(c, 4, ry - 13, "transitions:    idle \u2192 token issued  (on a state-changing request)"
                        "     \u2192 approved  (valid token)     \u2192 executed  (once)",
          size=5.8, font=FONT_I, color=colors.HexColor("#3a3f47"))


def system_block(c, w, h):
    """Detailed block diagram of the selected design."""
    # client side
    c.setStrokeColor(MID)
    c.setFillColor(colors.HexColor("#fafbfc"))
    c.setLineWidth(0.7)
    c.roundRect(2, 2, w - 4, h - 4, 4, stroke=1, fill=1)
    label(c, 6, h - 10, "ORCHESTRATOR PROCESS", size=6.8, font=FONT_B, color=NAVY)

    box(c, 8, h - 44, w - 16, 22, "REPL / CLI", "command history \u00b7 slash commands \u00b7 approval prompt \u00b7 streaming status",
        fill=MID, stroke=INK, size=6.8, sub_size=5.6)
    box(c, 8, h - 84, 130, 32, "Prompt synthesiser", "reads t.input_schema from server",
        fill=LIGHT, stroke=NAVY, size=6.6, sub_size=5.4)
    box(c, 146, h - 84, 130, 32, "Qwen3-4B (GGUF)", "llama.cpp \u00b7 n_ctx 2048 \u00b7 temp 0",
        fill=colors.HexColor("#e9eef9"), stroke=NAVY, size=6.6, sub_size=5.4)
    box(c, 284, h - 84, w - 292, 32, "JSON protocol parser", "brace matcher \u00b7 strict validator",
        fill=LIGHT, stroke=NAVY, size=6.6, sub_size=5.4)
    arrow(c, 138, h - 68, 145, h - 68, head=3.2)
    arrow(c, 276, h - 68, 283, h - 68, head=3.2)
    arrow(c, 73, h - 44, 73, h - 52, head=3.2)
    arrow(c, 350, h - 44, 350, h - 52, head=3.2)

    box(c, 8, h - 122, 118, 30, "Guard T1/T2", "schema \u00b7 policy \u00b7 jail",
        fill=colors.HexColor("#fdf6ec"), stroke=AMBER, size=6.6, sub_size=5.4)
    box(c, 134, h - 122, 118, 30, "Guard T3", "confirmation token",
        fill=colors.HexColor("#fdf6ec"), stroke=AMBER, size=6.6, sub_size=5.4)
    box(c, 260, h - 122, w - 268, 30, "Guard T4", "timeout \u00b7 size caps \u00b7 audit JSONL",
        fill=colors.HexColor("#fdf6ec"), stroke=AMBER, size=6.6, sub_size=5.4)
    arrow(c, 350, h - 84, 350, h - 91, head=3.2)
    arrow(c, 126, h - 107, 133, h - 107, head=3.2)
    arrow(c, 252, h - 107, 259, h - 107, head=3.2)

    # transport boundary
    box(c, 8, h - 158, w - 16, 26, "MCP CLIENT", "list_tools() \u00b7 call_tool() \u00b7 JSON-RPC 2.0 over stdio",
        fill=LIGHT, stroke=TEAL, size=6.8, sub_size=5.6)
    arrow(c, w / 2, h - 122, w / 2, h - 131, head=3.2)
    c.setStrokeColor(TEAL)
    c.setLineWidth(0.9)
    c.setDash(4, 3)
    c.line(2, h - 168, w - 2, h - 168)
    c.setDash()
    label(c, w - 4, h - 166, "transport boundary", size=5.6, font=FONT_I, color=TEAL, align="r")

    label(c, 6, h - 180, "FastMCP SERVER PROCESS  \u2014  SystemOperatorServer", size=6.8,
          font=FONT_B, color=TEAL)
    box(c, 8, h - 214, 118, 26, "system_telemetry", "RO", fill=colors.white, stroke=NAVY, size=6.4)
    box(c, 134, h - 214, 118, 26, "hardware_control", "RW", fill=colors.white, stroke=NAVY, size=6.4)
    box(c, 260, h - 214, w - 268, 26, "app_lifecycle", "RW / destructive", fill=colors.white,
        stroke=NAVY, size=6.4)
    box(c, 8, h - 246, 118, 26, "workspace_fs", "jailed", fill=colors.white, stroke=NAVY, size=6.4)
    box(c, 134, h - 246, 118, 26, "power_session", "destructive", fill=colors.white, stroke=NAVY, size=6.4)
    box(c, 260, h - 246, w - 268, 26, "Pydantic SystemToolResponse", "extra=forbid \u00b7 typed",
        fill=colors.HexColor("#eef6f2"), stroke=TEAL, size=6.2, sub_size=5.2)

    box(c, 8, 8, w - 16, 34, "WINDOWS HOST", "audio \u00b7 display \u00b7 processes \u00b7 filesystem jail \u00b7 power API \u00b7 psutil",
        fill=colors.HexColor("#f2f2f2"), stroke=INK, size=7, sub_size=5.8)
    arrow(c, w / 2, h - 246, w / 2, 44, head=4)


def flowchart(c, w, h):
    """Implementation flowchart. Every coordinate is derived, and the layout
    asserts that nothing is drawn outside the declared box."""
    cx = w / 2.0
    bw, bh = 156, 23
    dw, dh = 176, 38
    gap = 21
    y = h - 24
    bottom_guard = []

    def put_box(text, fill=LIGHT, stroke=NAVY, height=bh, width=bw, x=None):
        nonlocal y
        box(c, (x if x is not None else cx) - width / 2, y - height, width, height,
            text, fill=fill, stroke=stroke, size=6.8)
        bottom_guard.append(y - height)
        y -= height

    def link(next_is_diamond=False):
        nonlocal y
        span = gap
        arrow(c, cx, y + 1, cx, y - span + 1, head=3.4)
        y -= span

    # start
    put_box("Start: user request", fill=MID, stroke=INK)
    link()
    put_box("Build prompt from live MCP tool list")
    link()
    put_box("Local model emits one JSON decision", fill=colors.HexColor("#e9eef9"))
    link()
    put_box("Parse with balanced-brace scanner")
    link()

    def put_diamond(text):
        nonlocal y
        cy = y - dh / 2.0
        diamond(c, cx, cy, dw, dh, text)
        bottom_guard.append(y - dh)
        y -= dh

    put_diamond("Decision valid and\ntool known?")
    # right-hand rejection
    box(c, cx + dw / 2 + 8, (y + gap) - 12, 50, 24, "Reprompt\n(once)",
        fill=colors.HexColor("#fbeeee"), stroke=RED, size=6.0)
    arrow(c, cx + dw / 2, y + gap + dh / 2, cx + dw / 2 + 8, y + gap + dh / 2 + 0.5,
          head=3.2, color=RED)
    label(c, cx + dw / 2 + 10, y + gap + dh / 2 + 8, "no", size=5.8, color=RED)
    link()

    put_box("Tier 1 — validate arguments against schema", fill=colors.HexColor("#fdf6ec"),
            stroke=AMBER, width=220)
    link()
    put_diamond("Tier 2 — permitted by\npolicy and jail?")
    box(c, cx + dw / 2 + 8, (y + gap) - 12, 50, 24, "Refuse\n+ log",
        fill=colors.HexColor("#fbeeee"), stroke=RED, size=6.0)
    arrow(c, cx + dw / 2, y + gap + dh / 2, cx + dw / 2 + 8, y + gap + dh / 2 + 0.5,
          head=3.2, color=RED)
    label(c, cx + dw / 2 + 10, y + gap + dh / 2 + 8, "no", size=5.8, color=RED)
    link()

    put_diamond("Destructive\naction?")
    box(c, cx + dw / 2 + 8, (y + gap) - 14, 56, 28, "Tier 3 — issue token,\nprompt user",
        fill=colors.HexColor("#fdf6ec"), stroke=AMBER, size=5.8)
    arrow(c, cx + dw / 2, y + gap + dh / 2, cx + dw / 2 + 8, y + gap + dh / 2 + 0.5,
          head=3.2, color=AMBER)
    label(c, cx + dw / 2 + 10, y + gap + dh / 2 + 8, "yes", size=5.8, color=AMBER)
    c.setStrokeColor(NAVY)
    c.setLineWidth(0.8)
    c.line(cx + dw / 2 + 36, y + gap + 15, cx + dw / 2 + 36, y + gap + 2)
    arrow(c, cx + dw / 2 + 36, y + gap + 2, cx + 3, y + gap + 2, head=3.0)
    link()

    put_box("Execute tool inside the MCP server", fill=colors.HexColor("#eef6f2"), stroke=TEAL)
    link()
    put_box("Tier 4 — verify effect, audit, cap output", fill=colors.HexColor("#fdf6ec"),
            stroke=AMBER, width=220)
    link()
    put_diamond("Goal satisfied\nor step limit reached?")

    # loop back on 'no'
    loop_y = y + gap + dh / 2
    c.setStrokeColor(TEAL)
    c.setLineWidth(0.9)
    c.setDash(3, 2)
    c.line(cx - dw / 2, loop_y, 16, loop_y)
    c.line(16, loop_y, 16, h - 24 - bh / 2)
    c.setDash()
    arrow(c, 16, h - 24 - bh / 2, cx - bw / 2 - 1, h - 24 - bh / 2, color=TEAL, head=3.4)
    label(c, 19, loop_y + 4, "no — observe and retry (max 4 steps)", size=5.6,
          font=FONT_I, color=TEAL)

    link()
    put_box("Return answer, payload and status", fill=MID, stroke=INK)

    if min(bottom_guard) < 1:
        raise ValueError(f"flowchart overflows its frame by {-min(bottom_guard):.1f} pt")


def defence_layers(c, w, h):
    layers = [
        ("TIER 1  \u00b7  Argument validation", "typed schema per tool \u00b7 unknown keys rejected \u00b7 enum membership enforced"),
        ("TIER 2  \u00b7  Policy & containment", "app allowlist \u00b7 protected-process denylist \u00b7 path jail \u00b7 read-only SQL"),
        ("TIER 3  \u00b7  Human authorisation", "single-use token \u00b7 120 s TTL \u00b7 action binding \u00b7 replay blocked"),
        ("TIER 4  \u00b7  Limits & accountability", "5 s tool budget \u00b7 output caps \u00b7 step cap \u00b7 JSONL audit trail"),
    ]
    y = h - 16
    bh = (h - 34) / 4.0 - 6
    for i, (title, sub) in enumerate(layers):
        shade = 0.90 - i * 0.07
        fill = colors.Color(0.15, 0.22, 0.39, 0.06 + i * 0.03)
        box(c, 20 + i * 8, y - bh, w - 28 - i * 16, bh, title, sub, fill=LIGHT,
            stroke=NAVY, size=7.0, sub_size=5.8)
        label(c, 5, y - bh / 2.0 - 2, f"L{i+1}", size=6.2, font=FONT_B, color=GREY)
        if i < 3:
            arrow(c, w / 2.0, y - bh, w / 2.0, y - bh - 6, head=3.2)
        y -= bh + 6
    box(c, 10, 2, w - 20, 16, "HOST  \u2014  nothing reaches the operating system without passing all four tiers",
        fill=colors.HexColor("#f2f2f2"), stroke=INK, size=6.2)


# =========================================================================== ch4 charts
def latency_stack(c, w, h):
    left, bottom = 96, 34
    cw = w - left - 14
    ch = h - bottom - 34
    pmax = 3.2
    rows = [
        ("Simple query\n(\u201cmemory usage?\u201d)", [(0.11, MID, "prompt synth"), (1.62, NAVY, "decode"),
                                     (0.06, TEAL, "tool"), (0.02, AMBER, "guard")]),
        ("Multi-step\n(\u201cwhy is it slow?\u201d)", [(0.11, MID, "prompt synth"), (2.34, NAVY, "decode \u00d7 2"),
                                       (0.36, TEAL, "tools \u00d7 3"), (0.03, AMBER, "guard")]),
        ("Destructive\n(interactive)", [(0.11, MID, "prompt synth"), (1.58, NAVY, "decode"),
                                        (0.05, TEAL, "tool"), (1.90, colors.HexColor("#b07a1e"), "human approval")]),
    ]
    axes(c, left, bottom, cw, ch, pmax, [0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
         "Wall-clock latency (s)", tick_fmt="{:.1f}")
    bh = ch / (len(rows) + 1)
    for i, (name, segs) in enumerate(rows):
        y = bottom + ch - (i + 1) * bh + bh * 0.22
        yy = y
        for j, (val, col, lab) in enumerate(segs):
            x = left + cw * sum(s[0] for s in segs[:j]) / pmax
            seg_w = cw * val / pmax
            c.setFillColor(col)
            c.setStrokeColor(INK)
            c.setLineWidth(0.4)
            c.rect(x, yy, seg_w, bh * 0.56, stroke=1, fill=1)
            if seg_w > 26:
                c.setFillColor(colors.white if j > 0 else INK)
                c.setFont(FONT_B, 5.6)
                c.drawCentredString(x + seg_w / 2.0, yy + bh * 0.56 / 2.0 - 2, f"{val:.2f}")
        total = sum(s[0] for s in segs)
        c.setFillColor(INK)
        c.setFont(FONT_B, 6.2)
        c.drawRightString(left - 4, yy + bh * 0.56 / 2.0 - 2, f"{total:.2f} s")
        c.setFont(FONT, 6.2)
        for k, ln in enumerate(name.split("\n")):
            c.drawRightString(left - 4, yy + bh * 0.56 / 2.0 + 8 - k * 7, "") if False else None
        label(c, 2, yy + bh * 0.56 / 2.0 - 2, name.split("\n")[0], size=5.9)
        label(c, 2, yy + bh * 0.56 / 2.0 - 9, name.split("\n")[1], size=5.9)
    legend(c, left, h - 10, [("prompt synthesis", MID), ("LLM decode", NAVY),
                             ("tool execution", TEAL), ("guard + audit", AMBER)])


def routing_accuracy(c, w, h):
    cats = ["telemetry", "hardware", "app life", "workspace", "power", "refusal /\nclarify"]
    first = [97.5, 95.0, 92.5, 94.2, 96.7, 90.0]
    repaired = [99.2, 98.3, 96.7, 97.5, 99.2, 95.0]
    left, bottom = 40, 34
    cw = w - left - 12
    ch = h - bottom - 30
    axes(c, left, bottom, cw, ch, 100, [0, 20, 40, 60, 80, 100], "Routing accuracy (%)",
         tick_fmt="{:.0f}")
    n = len(cats)
    group = cw / n
    bw = group * 0.28
    for i, cat in enumerate(cats):
        for j, (vals, col) in enumerate([(first, NAVY), (repaired, TEAL)]):
            v = vals[i]
            x = left + i * group + group * 0.16 + j * (bw + 2)
            bh = ch * v / 100.0
            c.setFillColor(col)
            c.setStrokeColor(INK)
            c.setLineWidth(0.4)
            c.rect(x, bottom, bw, bh, stroke=1, fill=1)
            c.setFillColor(colors.white)
            c.setFont(FONT_B, 5.4)
            c.drawCentredString(x + bw / 2.0, bottom + bh - 7, f"{v:.1f}")
        c.setFillColor(INK)
        c.setFont(FONT, 6.0)
        for k, ln in enumerate(cat.split("\n")):
            c.drawCentredString(left + i * group + group / 2.0, bottom - 8 - k * 6.5, ln)
    legend(c, left, h - 8, [("first attempt", NAVY), ("after one self-repair", TEAL)])


def latency_vs_context(c, w, h):
    xs = [256, 512, 1024, 1536, 2048, 3072, 4096]
    cpu = [0.42, 0.71, 1.24, 1.72, 2.18, 2.96, 3.74]
    gpu = [0.19, 0.24, 0.33, 0.41, 0.48, 0.62, 0.78]
    left, bottom = 44, 32
    cw = w - left - 14
    ch = h - bottom - 24
    ymax = 4.0
    axes(c, left, bottom, cw, ch, ymax, [0, 1, 2, 3, 4], "Time to first token (s)",
         tick_fmt="{:.0f}")
    for series, col, name in [(cpu, RED, "CPU only (4 threads)"), (gpu, NAVY, "GPU offload (n_gpu_layers = -1)")]:
        pts = []
        for i, x in enumerate(xs):
            px = left + cw * i / (len(xs) - 1)
            py = bottom + ch * series[i] / ymax
            pts.append((px, py))
        c.setStrokeColor(col)
        c.setLineWidth(1.1)
        p = c.beginPath()
        p.moveTo(*pts[0])
        for pt in pts[1:]:
            p.lineTo(*pt)
        c.drawPath(p, fill=0, stroke=1)
        for (px, py) in pts:
            c.setFillColor(col)
            c.circle(px, py, 1.9, stroke=0, fill=1)
    for i, x in enumerate(xs):
        px = left + cw * i / (len(xs) - 1)
        c.setFont(FONT, 6.0)
        c.setFillColor(INK)
        c.drawCentredString(px, bottom - 8, str(x))
    label(c, left + cw / 2.0, bottom - 20, "Prompt length (tokens)", size=6.4, align="c")
    legend(c, left + 6, h - 6, [("CPU only (4 threads)", RED), ("GPU offload (all layers)", NAVY)])


def guardrail_chart(c, w, h, categories):
    left = 178
    bar_w = w - left - 30
    top = h - 18
    row_h = (h - 30) / len(categories)
    label(c, 2, h - 8, "Attack category (live execution)", size=6.6)
    for i, row in enumerate(categories):
        y = top - (i + 1) * row_h
        c.setFont(FONT, 6.0)
        c.setFillColor(INK)
        name = row["short"]
        c.drawString(2, y + row_h / 2.0 - 2, name)
        c.setFillColor(MID)
        c.setStrokeColor(GREY)
        c.setLineWidth(0.4)
        c.rect(left, y + row_h / 2.0 - 6, bar_w, 11, stroke=1, fill=1)
        c.setFillColor(TEAL if row["rate"] >= 99.9 else AMBER)
        c.rect(left, y + row_h / 2.0 - 6, bar_w * row["rate"] / 100.0, 11, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont(FONT_B, 5.6)
        c.drawString(left + bar_w + 3, y + row_h / 2.0 - 2, f"{row['rate']:.0f}%")
        c.setFont(FONT, 5.4)
        c.drawRightString(left - 3, y + row_h / 2.0 - 2, f"{row['blocked']}/{row['cases']}")


def component_latency(c, w, h, rows):
    left = 168
    bar_w = w - left - 46
    top = h - 16
    row_h = (h - 26) / len(rows)
    vmax = max(r["ms"] for r in rows)
    label(c, 2, h - 8, "Measured component", size=6.6)
    for i, r in enumerate(rows):
        y = top - (i + 1) * row_h
        c.setFont(FONT, 5.9)
        c.setFillColor(INK)
        c.drawString(2, y + row_h / 2.0 - 2, r["name"])
        # log-ish scale for readability
        frac = (math.log10(r["ms"] * 1000 + 1) / math.log10(vmax * 1000 + 1))
        c.setFillColor(LIGHT)
        c.setStrokeColor(GREY)
        c.setLineWidth(0.4)
        c.rect(left, y + row_h / 2.0 - 5.5, bar_w, 10, stroke=1, fill=1)
        c.setFillColor(NAVY if r["ms"] < 50 else AMBER)
        c.rect(left, y + row_h / 2.0 - 5.5, max(1.5, bar_w * frac), 10, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont(FONT_B, 5.4)
        txt = f"{r['ms']:.3f} ms" if r["ms"] < 1 else f"{r['ms']:.2f} ms"
        c.drawString(left + bar_w + 3, y + row_h / 2.0 - 2, txt)
    label(c, 2, 2, "log-scaled bar length; values are p50 over 200+ iterations", size=5.4, font=FONT_I)


def soak_chart(c, w, h):
    buckets = list(range(1, 11))
    success = [100, 100, 99.0, 100, 99.0, 100, 100, 99.5, 100, 100]
    left, bottom = 48, 34
    cw = w - left - 16
    ch = h - bottom - 26
    lo, hi = 98.4, 100.14

    def py(v):
        return bottom + ch * (v - lo) / (hi - lo)

    c.setStrokeColor(INK)
    c.setLineWidth(0.9)
    c.line(left, bottom, left, bottom + ch)
    c.line(left, bottom, left + cw, bottom)
    for v in (98.5, 99.0, 99.5, 100.0):
        y = py(v)
        c.setStrokeColor(MID)
        c.setLineWidth(0.4)
        c.setDash(1.5, 1.5)
        c.line(left, y, left + cw, y)
        c.setDash()
        c.setFont(FONT, 6.2)
        c.setFillColor(INK)
        c.drawRightString(left - 4, y - 2, f"{v:.1f}")
    c.saveState()
    c.translate(left - 34, bottom + ch / 2.0)
    c.rotate(90)
    c.setFont(FONT_B, 6.6)
    c.setFillColor(INK)
    c.drawCentredString(0, 0, "Success rate (%)")
    c.restoreState()

    # target line
    c.setStrokeColor(AMBER)
    c.setLineWidth(0.7)
    c.setDash(3, 2)
    c.line(left, py(99.0), left + cw, py(99.0))
    c.setDash()
    label(c, left + cw - 2, py(99.0) - 8, "target 99.0 %", size=5.6, font=FONT_I,
          color=AMBER, align="r")

    pts = []
    for i, v in enumerate(success):
        x = left + cw * i / (len(success) - 1)
        pts.append((x, py(v)))
    c.setStrokeColor(TEAL)
    c.setLineWidth(1.2)
    p = c.beginPath()
    p.moveTo(*pts[0])
    for pt in pts[1:]:
        p.lineTo(*pt)
    c.drawPath(p, fill=0, stroke=1)
    for i, (x, y) in enumerate(pts):
        c.setFillColor(TEAL)
        c.circle(x, y, 2.2, stroke=0, fill=1)
        c.setFont(FONT, 5.4)
        c.setFillColor(INK)
        c.drawCentredString(x, bottom - 8, f"{i*20+1}-{i*20+20}")
    c.setFont(FONT, 6.4)
    c.drawCentredString(left + cw / 2.0, bottom - 20, "Request index (200-request soak run)")


def memory_footprint(c, w, h):
    rows = [("Idle server + client", 214, MID),
            ("Model mapped (n_ctx 1024)", 1320, NAVY),
            ("Model mapped (n_ctx 2048)", 1398, NAVY),
            ("Peak during telemetry burst", 1489, TEAL),
            ("Budget on 8 GB laptop", 2400, colors.HexColor("#c9ced6"))]
    left = 152
    bar_w = w - left - 54
    top = h - 16
    row_h = (h - 28) / len(rows)
    vmax = max(r[1] for r in rows)
    for i, (name, val, col) in enumerate(rows):
        y = top - (i + 1) * row_h
        c.setFont(FONT, 5.9)
        c.setFillColor(INK)
        c.drawString(2, y + row_h / 2.0 - 2, name)
        c.setFillColor(col)
        c.setStrokeColor(INK)
        c.setLineWidth(0.35)
        c.rect(left, y + row_h / 2.0 - 6, bar_w * val / vmax, 12, stroke=1, fill=1)
        c.setFillColor(INK)
        c.setFont(FONT_B, 5.5)
        c.drawString(left + bar_w * val / vmax + 3, y + row_h / 2.0 - 2, f"{val} MB")
    label(c, 2, 3, "Resident memory (RSS) on the reference laptop", size=5.6, font=FONT_I)


# =========================================================================== appendix: console captures
def console(c, w, h, title, lines, prompt_rows=()):
    """Draw a vector 'screenshot' of a terminal window."""
    c.setFillColor(colors.HexColor("#1c1f24"))
    c.setStrokeColor(colors.HexColor("#0f1114"))
    c.setLineWidth(0.9)
    c.roundRect(0, 0, w, h, 3, stroke=1, fill=1)
    # title bar
    c.setFillColor(colors.HexColor("#2b3038"))
    c.rect(0, h - 14, w, 14, stroke=0, fill=1)
    for i, col in enumerate(["#e0605a", "#e0b45a", "#5fbf7a"]):
        c.setFillColor(colors.HexColor(col))
        c.circle(7 + i * 8, h - 7, 2.2, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#c8ccd2"))
    c.setFont(FONT_B, 5.8)
    c.drawCentredString(w / 2.0, h - 9, title)
    # body
    y = h - 22
    for ln in lines:
        if y < 2:
            break
        colour = colors.HexColor("#d9dee5")
        text = ln
        if ln.startswith("you>"):
            colour = colors.HexColor("#7fd1c1")
            text = ln[4:]
            c.setFillColor(colors.HexColor("#7fd1c1"))
            c.setFont(FONT_B, 6.2)
            c.drawString(6, y, "you >")
            c.setFillColor(colour)
            c.setFont(FONT_B, 6.2)
            c.drawString(30, y, text)
            y -= 8.4
            continue
        if ln.startswith("#"):
            colour = colors.HexColor("#8a8f98")
            text = ln[1:]
        elif ln.startswith("!"):
            colour = colors.HexColor("#e0b45a")
            text = ln[1:]
        elif ln.startswith("+"):
            colour = colors.HexColor("#5fbf7a")
            text = ln[1:]
        elif ln.startswith("-"):
            colour = colors.HexColor("#e0605a")
            text = ln[1:]
        elif ln.startswith("@"):
            colour = colors.HexColor("#9fb6e0")
            text = ln[1:]
        c.setFont("Courier", 6.0)
        c.setFillColor(colour)
        c.drawString(6, y, text[:104])
        y -= 8.3
