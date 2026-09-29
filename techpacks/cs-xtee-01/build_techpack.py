#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_techpack.py

Cultsiders CS-XTEE-01 (working code): factory tech pack, v0.1 DRAFT.
Builds 8 A4-landscape SVG pages, renders them with cairosvg to one PDF
(merged with pypdf) plus one PNG preview per page (1600 px wide, rendered from the final PDF with pdfium).
CJK text uses a TrueType-outline copy of Noto Sans CJK SC built into fonts/ (see build_cjk_fonts); every
character of both PDFs is checked for a real glyph and visible ink after the build (verify_pdf).
Also builds the 1:1 X template (PROPOSAL): a 2-page PDF (A3: 200 mm X,
A4: 150 mm X) and two plain ASCII R12 DXF files (layers STITCH, BASE, CUT_JAG,
PATCH, GUIDE (tooling sheet with asymmetric CF notch), ORIENT (engraved arrow + FACE UP / NECK),
CHECK (50 x 50 mm square), CENTRE, NOTES, plus STITCH_FOLLOW on the 150 mm file; units mm;
origin = X centre; face view) with R2000 copies (*-R2000.dxf, via ezdxf); all four are read back and audited.
Checks that fail the build: CUT_JAG combined tooth depth <= 40% of the arm, visible brown >= BROWN_MIN,
cut >= 3 mm from the stitch, GUIDE notch orientation-proof, glyph ink in both PDFs, and no ink within
8 mm of any page edge (edge_check).

Run:  python3 build_techpack.py
Out:  CS-XTEE-TechPack-v0.1-DRAFT.pdf, page-01.png ... page-08.png, svg/page-NN.svg,
      CS-XTEE-01-X-template-1to1-PROPOSAL.pdf, CS-XTEE-01-X-template-200mm.dxf,
      CS-XTEE-01-X-template-150mm.dxf, *-R2000.dxf copies, template-p1.png, template-p2.png
"""
import base64
import bisect
import html
import io
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# CJK text is embedded from a TrueType-outline copy of Noto Sans CJK SC (built below, private
# fontconfig dir). cairo's CFF subsetter produced broken charstrings for some glyphs (e.g. 如) in
# the CID-keyed OTF, so the PDF must never embed the CFF original. Set before cairo loads fonts.
FONT_DIR = os.path.join(HERE, "fonts")
os.environ["FONTCONFIG_FILE"] = os.path.join(FONT_DIR, "fonts.conf")

import cairosvg  # noqa: E402
import numpy as np  # noqa: E402
import pypdfium2 as pdfium  # noqa: E402
from PIL import Image, ImageFont  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402
from shapely.geometry import LinearRing, LineString, Point, Polygon  # noqa: E402

VERSION = "v0.1"
OUT_PDF = os.path.join(HERE, f"CS-XTEE-TechPack-{VERSION}-DRAFT.pdf")
SVG_DIR = os.path.join(HERE, "svg")
WORDMARK = "/home/user/cultsiders/assets/wordmark.png"

PW, PH = 297.0, 210.0          # A4 landscape, user units = mm
N_PAGES = 8
DATE = "2026-09-29"
DATE_V0 = "2026-09-28"
STYLE = "CS-XTEE-01"
TPL_PDF_NAME = f"{STYLE}-X-template-1to1-PROPOSAL.pdf"
DXF200_NAME = f"{STYLE}-X-template-200mm.dxf"
DXF150_NAME = f"{STYLE}-X-template-150mm.dxf"
DXF200_R2K_NAME = f"{STYLE}-X-template-200mm-R2000.dxf"
DXF150_R2K_NAME = f"{STYLE}-X-template-150mm-R2000.dxf"
CHECK_SQ = 50.0               # DXF layer CHECK: 50 x 50 mm square to confirm import scale
BASE = "XH25-IM1222-M"

# ------------------------------------------------------------------ colours
INK = "#161616"
GREY = "#5c5c5c"
MID = "#8a8a8a"
LIGHT = "#c9c9c9"
FAINT = "#efefef"
ZHC = "#3b3b3b"
CREAM = "#F3EDDC"
CREAM_D = "#E1D7BF"
INSIDE = "#DCD2BA"
BROWN = "#5A3826"
BROWN_BACK = "#7A5A46"
BROWN_BK = "#2B211C"
TBD_FILL = "#FFE94D"
TBD_LINE = "#A8820A"
WHITE = "#FFFFFF"

FAM_EN = "Liberation Sans"
FAM_ZH = "Noto Sans SC TT"      # TrueType-outline copy of Noto Sans CJK SC, see build_cjk_fonts()
ZH_SRC = {False: "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
          True: "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"}

# default text sizes (mm)
SE = 2.3     # English body
SZ = 2.0     # Chinese body (smaller, second)

WARN = []

# ------------------------------------------------------------------ fonts
_F = {}


def _font(zh, bold):
    key = (zh, bold)
    if key not in _F:
        if zh:
            _F[key] = ImageFont.truetype(ZH_SRC[bold], 200, index=2)  # index 2 = SC
        else:
            path = ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
                    else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf")
            _F[key] = ImageFont.truetype(path, 200)
    return _F[key]


def tw(s, size, zh=False, bold=False):
    """Text width in mm."""
    return _font(zh, bold).getlength(s) * size / 200.0


def esc(s):
    return html.escape(s, quote=True)


# ------------------------------------------------------------------ primitives
def f2(v):
    return f"{v:.2f}"


def text(x, y, s, size=SE, zh=False, bold=False, anchor="start", fill=INK, rot=None):
    if not zh and any(ord(ch) >= 0x2E80 for ch in s):
        WARN.append(f"CJK in EN text: {s[:60]}")
    fam = FAM_ZH if zh else FAM_EN
    wt = "bold" if bold else "normal"
    tr = f' transform="rotate({f2(rot)} {f2(x)} {f2(y)})"' if rot else ""
    return (f'<text x="{f2(x)}" y="{f2(y)}" font-family="{fam}" font-size="{f2(size)}" '
            f'font-weight="{wt}" fill="{fill}" text-anchor="{anchor}"{tr}>{esc(s)}</text>')


def rect(x, y, w, h, fill="none", stroke=None, sw=0.2, rx=0, dash=None, opacity=None):
    st = f' stroke="{stroke}" stroke-width="{f2(sw)}"' if stroke else ""
    da = f' stroke-dasharray="{dash}"' if dash else ""
    op = f' fill-opacity="{opacity}"' if opacity is not None else ""
    r = f' rx="{f2(rx)}"' if rx else ""
    return f'<rect x="{f2(x)}" y="{f2(y)}" width="{f2(w)}" height="{f2(h)}" fill="{fill}"{op}{st}{da}{r}/>'


def line(x1, y1, x2, y2, stroke=INK, sw=0.2, dash=None, cap="butt"):
    da = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{f2(x1)}" y1="{f2(y1)}" x2="{f2(x2)}" y2="{f2(y2)}" stroke="{stroke}" '
            f'stroke-width="{f2(sw)}" stroke-linecap="{cap}"{da}/>')


def poly(pts, fill="none", stroke=INK, sw=0.25, closed=True, dash=None, join="round", opacity=None):
    if not pts:
        return ""
    d = "M " + " L ".join(f"{f2(x)} {f2(y)}" for x, y in pts) + (" Z" if closed else "")
    st = f' stroke="{stroke}" stroke-width="{f2(sw)}" stroke-linejoin="{join}"' if stroke else ""
    da = f' stroke-dasharray="{dash}"' if dash else ""
    op = f' fill-opacity="{opacity}"' if opacity is not None else ""
    return f'<path d="{d}" fill="{fill}"{op}{st}{da}/>'


def circle(x, y, r, fill="none", stroke=INK, sw=0.25):
    st = f' stroke="{stroke}" stroke-width="{f2(sw)}"' if stroke else ""
    return f'<circle cx="{f2(x)}" cy="{f2(y)}" r="{f2(r)}" fill="{fill}"{st}/>'


# ------------------------------------------------------------------ vectors
def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def mul(a, k):
    return (a[0] * k, a[1] * k)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def unit(v):
    l = math.hypot(v[0], v[1])
    return (v[0] / l, v[1] / l)


def line_x(p, r, q, s):
    """Intersection of p + t r and q + u s."""
    rxs = r[0] * s[1] - r[1] * s[0]
    t = ((q[0] - p[0]) * s[1] - (q[1] - p[1]) * s[0]) / rxs
    return add(p, mul(r, t))


def clip_half(pts, p0, nrm):
    """Keep the part of convex polygon pts where dot(p - p0, nrm) <= 0."""
    out = []
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        da, db = dot(sub(a, p0), nrm), dot(sub(b, p0), nrm)
        if da <= 0:
            out.append(a)
        if (da < 0 < db) or (db < 0 < da):
            t = da / (da - db)
            out.append(add(a, mul(sub(b, a), t)))
    return out


# ------------------------------------------------------------------ text layout
ZH_NO_START = set("，。；：、）》」』！？,.;:)%")


def _tokens(s, zh):
    if not zh:
        out = []
        for i, w in enumerate(s.split(" ")):
            if i:
                out.append(" ")
            if w:
                out.append(w)
        return out
    toks, buf = [], ""
    for ch in s:
        if ord(ch) < 0x2E80 and ch not in "，。；：、（）":
            if ch == " ":
                if buf:
                    toks.append(buf)
                    buf = ""
                toks.append(" ")
            else:
                buf += ch
        else:
            if buf:
                toks.append(buf)
                buf = ""
            if ch in ZH_NO_START and toks:
                toks[-1] += ch
            else:
                toks.append(ch)
    if buf:
        toks.append(buf)
    # an opening bracket never ends a line: bind it to the next token
    out, i = [], 0
    while i < len(toks):
        t = toks[i]
        while t and t[-1] in "（《「『" and i + 1 < len(toks):
            i += 1
            t += toks[i]
        out.append(t)
        i += 1
    return out


def wrap(s, size, width, zh=False, bold=False, first_indent=0.0):
    width = width * 0.965          # raster hinting safety margin
    lines = []
    for par in s.split("\n"):
        toks = _tokens(par, zh)
        cur = ""
        avail = width - (first_indent if not lines else 0)
        for tk in toks:
            if tk == " " and not cur:
                continue
            trial = cur + tk
            if tw(trial.rstrip(), size, zh, bold) <= avail or not cur.strip():
                cur = trial
            else:
                lines.append(cur.rstrip())
                avail = width
                cur = "" if tk == " " else tk
        lines.append(cur.rstrip())
    for i, l in enumerate(lines):
        lim = width - (first_indent if i == 0 else 0)
        if tw(l, size, zh, bold) > lim + 0.3:
            WARN.append(f"overflow {tw(l, size, zh, bold):.1f}>{lim:.1f}: {l[:50]}")
    return lines


def para(x, y, s, width, size=SE, zh=False, bold=False, lh=None, fill=None, align="left",
         first_indent=0.0):
    """Wrapped paragraph; y = top. Returns (svg, height)."""
    if not s:
        return "", 0.0
    if lh is None:
        lh = 1.36 if zh else 1.26
    if fill is None:
        fill = ZHC if zh else INK
    lines = wrap(s, size, width, zh, bold, first_indent)
    out = []
    for i, l in enumerate(lines):
        by = y + size * 0.84 + i * size * lh
        if align == "center":
            out.append(text(x + width / 2, by, l, size, zh, bold, "middle", fill))
        elif align == "right":
            out.append(text(x + width, by, l, size, zh, bold, "end", fill))
        else:
            out.append(text(x + (first_indent if i == 0 else 0), by, l, size, zh, bold, "start", fill))
    return "".join(out), len(lines) * size * lh


def bi(x, y, en, zh, width, se=SE, sz=SZ, bold=False, gap=0.25, first_indent=0.0, align="left",
       fill=INK, lh_en=None):
    # a TBD badge sits in the first-line indent: open the EN leading so line 2 clears the badge
    if lh_en is None and first_indent > 0:
        lh_en = 1.45
    s1, h1 = para(x, y, en, width, se, bold=bold, first_indent=first_indent, align=align, fill=fill,
                  lh=lh_en)
    if zh:
        s2, h2 = para(x, y + h1 + gap, zh, width, sz, zh=True, bold=False, align=align)
        return s1 + s2, h1 + gap + h2
    return s1, h1


def tbd_badge(x, y, size=1.9, label="TBD"):
    """Yellow TBD badge; (x, y) = top-left. Returns (svg, width, height)."""
    w = tw(label, size, bold=True) + 1.4
    h = size * 1.3
    s = rect(x, y, w, h, TBD_FILL, TBD_LINE, 0.25, rx=0.5)
    s += text(x + w / 2, y + h * 0.76, label, size, bold=True, anchor="middle", fill=INK)
    return s, w, h


def tbd_box(x, y, w, en, zh=None, se=2.1, sz=1.85, pad=1.0):
    """Highlighted TBD box with text. Returns (svg, height)."""
    b, bw, bh = tbd_badge(x + pad, y + pad - 0.25)
    s, h = bi(x + pad, y + pad, en, zh, w - 2 * pad, se, sz, first_indent=bw + 1.0)
    hh = max(h, bh) + 2 * pad
    return rect(x, y, w, hh, TBD_FILL, TBD_LINE, 0.3, rx=0.8) + b + s, hh


def heading(x, y, en, zh=None, size=3.0, width=None, rule=True):
    """Section heading with rule underneath. y = top. Returns (svg, height)."""
    s = text(x, y + size * 0.84, en, size, bold=True)
    wx = tw(en, size, bold=True)
    if zh:
        s += text(x + wx + 2.0, y + size * 0.84, zh, size * 0.8, zh=True, bold=True, fill=ZHC)
    h = size * 1.15
    if rule and width:
        s += line(x, y + h + 0.3, x + width, y + h + 0.3, INK, 0.3)
    return s, h + 1.4


# ------------------------------------------------------------------ table
def norm_cell(c):
    if c is None:
        return {"en": ""}
    if isinstance(c, str):
        return {"en": c}
    if isinstance(c, tuple):
        d = {"en": c[0]}
        if len(c) > 1:
            d["zh"] = c[1]
        return d
    return dict(c)


def C(en="", zh=None, **kw):
    d = {"en": en}
    if zh:
        d["zh"] = zh
    d.update(kw)
    return d


def cell_render(x, y, w, c, se, sz, header=False):
    parts = []
    h = 0.0
    align = c.get("align", "left")
    ind = 0.0
    color = WHITE if header else c.get("color", INK)
    zcolor = "#DADADA" if header else ZHC
    se_ = c.get("se", se)
    sz_ = c.get("sz", sz)
    if c.get("tbd"):
        if align == "center":
            bwid = tw("TBD", 1.8, bold=True) + 1.4
            b, bw, bh = tbd_badge(x + w / 2 - bwid / 2, y, 1.8)
            parts.append(b)
            h = bh + 0.5
        else:
            b, bw, bh = tbd_badge(x, y, 1.8)
            parts.append(b)
            ind = bw + 0.9
    if c.get("en"):
        s, hh = para(x, y + h, c["en"], w, se_, bold=c.get("bold", header), fill=color, align=align,
                     first_indent=ind, lh=1.42 if ind > 0 else None)
        parts.append(s)
        if c.get("inline_zh"):
            parts.append(text(x + tw(c["en"], se_, bold=c.get("bold", header)) + 1.6, y + h + se_ * 0.84,
                              c["inline_zh"], sz_, zh=True, bold=c.get("bold", header), fill=zcolor))
        h += hh
        ind = 0.0
    if c.get("sub"):
        s, hh = para(x, y + h + 0.1, c["sub"], w, se_ * 0.88, fill=GREY if not header else "#DADADA",
                     align=align, first_indent=ind)
        parts.append(s)
        h += hh + 0.1
    if c.get("zh"):
        s, hh = para(x, y + h + 0.2, c["zh"], w, sz_, zh=True, fill=zcolor, align=align,
                     first_indent=ind)
        parts.append(s)
        h += hh + 0.2
    if c.get("tbd") and h < 2.4:
        h = 2.4
    return "".join(parts), h


def table(x, y, widths, rows, header=None, se=2.05, sz=1.8, pad=0.9, head_fill=INK,
          border=LIGHT, min_h=0.0, zebra=False):
    """rows: list of lists of cells; a row may be ('SPAN', cell) for a full-width band.
    Returns (svg, height)."""
    bg, fg = [], []
    cy = y
    total_w = sum(widths)
    seq = []
    if header:
        seq.append(("H", header))
    for r in rows:
        seq.append(("R", r))
    for idx, (kind, r) in enumerate(seq):
        if isinstance(r, tuple) and r and r[0] == "SPAN":
            c = norm_cell(r[1])
            s, hh = cell_render(x + pad, cy + pad, total_w - 2 * pad, c, se, sz)
            rh = hh + 2 * pad
            bg.append(rect(x, cy, total_w, rh, c.get("fill", FAINT)))
            fg.append(s)
            bg.append(line(x, cy + rh, x + total_w, cy + rh, border, 0.2))
            cy += rh
            continue
        cells = [norm_cell(c) for c in r]
        rendered = []
        cx = x
        rh = min_h
        for w, c in zip(widths, cells):
            s, hh = cell_render(cx + pad, cy + pad, w - 2 * pad, c, se, sz, header=(kind == "H"))
            rendered.append((cx, w, c, s))
            rh = max(rh, hh + 2 * pad)
            cx += w
        if kind == "H":
            bg.append(rect(x, cy, total_w, rh, head_fill))
        elif zebra and idx % 2 == 0:
            bg.append(rect(x, cy, total_w, rh, "#F7F7F7"))
        for cx, w, c, s in rendered:
            if c.get("tbd") and kind != "H":
                bg.append(rect(cx, cy, w, rh, TBD_FILL))
                bg.append(rect(cx + 0.15, cy + 0.15, w - 0.3, rh - 0.3, "none", TBD_LINE, 0.25))
            elif c.get("fill") and kind != "H":
                bg.append(rect(cx, cy, w, rh, c["fill"]))
            fg.append(s)
        # borders
        cx = x
        for w in widths[:-1]:
            cx += w
            fg.append(line(cx, cy, cx, cy + rh, border if kind != "H" else "#555555", 0.2))
        fg.append(line(x, cy + rh, x + total_w, cy + rh, border, 0.2))
        cy += rh
    frame = rect(x, y, total_w, cy - y, "none", GREY, 0.3)
    return "".join(bg) + "".join(fg) + frame, cy - y


# ------------------------------------------------------------------ dimensioning
def arrowhead(tip, direction, L=1.5, W=0.95, fill=INK):
    d = unit(direction)
    n = (-d[1], d[0])
    base = sub(tip, mul(d, L))
    return poly([tip, add(base, mul(n, W / 2)), sub(base, mul(n, W / 2))], fill=fill, stroke=None)


def label_box(mx, my, angle, s, size=2.0, tbd=False, bg=WHITE, zh=False, bold=False):
    """Centered label at baseline point (mx, my), rotated by angle (deg)."""
    w = tw(s, size, zh=zh, bold=bold)
    extra = 0.0
    if tbd:
        extra = tw("TBD", size * 0.85, bold=True) + 1.6
    tot = w + extra
    x0 = mx - tot / 2
    g = []
    if tbd:
        g.append(rect(x0 - 0.8, my - size * 0.95, tot + 1.6, size * 1.3, TBD_FILL, TBD_LINE, 0.25, rx=0.4))
    elif bg:
        g.append(rect(x0 - 0.5, my - size * 0.9, tot + 1.0, size * 1.2, bg))
    g.append(text(x0, my, s, size, zh=zh, bold=bold, anchor="start"))
    if tbd:
        g.append(text(x0 + w + 1.2, my - size * 0.05, "TBD", size * 0.85, bold=True, anchor="start"))
    inner = "".join(g)
    if angle:
        return f'<g transform="rotate({f2(angle)} {f2(mx)} {f2(my)})">{inner}</g>'
    return inner


def dim(p1, p2, off, lab, size=2.0, tbd=False, color=INK, sw=0.18, gap=0.7, tside=1,
        ext=True, lab_shift=0.0):
    """Aligned dimension between page points p1, p2, offset 'off' along left normal."""
    d = unit(sub(p2, p1))
    n = (-d[1], d[0])
    q1 = add(p1, mul(n, off))
    q2 = add(p2, mul(n, off))
    out = []
    if ext and abs(off) > 0.01:
        sgn = 1 if off > 0 else -1
        for p, q in ((p1, q1), (p2, q2)):
            out.append(line(*add(p, mul(n, gap * sgn)), *add(q, mul(n, 1.0 * sgn)), color, 0.15))
    out.append(line(*q1, *q2, color, sw))
    out.append(arrowhead(q1, mul(d, -1), fill=color))
    out.append(arrowhead(q2, d, fill=color))
    ang = math.degrees(math.atan2(d[1], d[0]))
    if ang > 89.99:
        ang -= 180
    if ang <= -90.01:
        ang += 180
    up = (math.sin(math.radians(ang)), -math.cos(math.radians(ang)))
    mid = mul(add(q1, q2), 0.5)
    mid = add(mid, mul(d, lab_shift))
    lp = add(mid, mul(up, 0.9 * tside if tside > 0 else -(size + 0.2)))
    if lab:
        out.append(label_box(lp[0], lp[1], ang, lab, size, tbd))
    return "".join(out)


def num(x, y, n, r=2.0, fill=INK, fg=WHITE, size=None):
    size = size or r * 1.15
    return circle(x, y, r, fill, None) + text(x, y + size * 0.36, str(n), size, bold=True,
                                              anchor="middle", fill=fg)


def leader(p, q, color=INK, sw=0.18, dot_end=True):
    s = line(*p, *q, color, sw)
    if dot_end:
        s += circle(q[0], q[1], 0.45, color, None)
    return s


# ------------------------------------------------------------------ X geometry (mm, y down)
class XGeo:
    """X window spec. W x H = bounding box of the base cut line; HC / HT = half width along the arm / at the tip."""

    def __init__(self, name, W, H, HC, HT):
        self.name, self.W, self.H, self.HC, self.HT = name, W, H, HC, HT


G200 = XGeo("200", 200.0, 210.0, 12.5, 5.5)      # Proto A: 25 mm arm at BASE, 11 mm round tips
G150 = XGeo("150", 150.0, 157.5, 9.375, 5.0)     # Proto B: based on the 200 mm X, tips kept at 10 mm (not a x0.75 scale)
R_CUT = 7.0                   # inner-corner radius of the base cut line (cut r >= 7)
STITCH_OFF = 4.0              # base cut line to stitch (stitch inner corner r = 7 - 4 = 3)
PATCH_OFF = 10.0              # under-patch cut line = stitch + 10 mm
R_PATCH = 3.0                 # inner-corner radius of the patch line
JAG_A = 3.0                   # variant A: jag 0-3 mm into the window
TRIM_OFF = 7.0                # optional trim to stitch + 7 (only if a flap flips on the proto)
TOOTH_SP = (5.0, 15.0)        # variant B: tooth spacing (mm)
TOOTH_D = (3.0, 8.0)          # variant B: tooth depth (mm), less where the arm narrows
COMB_MAX = 0.40               # variant B: both sides together <= 40% of the local arm width at any cross-section
BROWN_MIN = {"200": 12.0, "150": 10.0}   # minimum visible brown across an arm (mm); never less than the tip
TIP_FREE = {"200": 18.0, "150": 16.0}    # no teeth in the last N mm before each tip cap
TOOTH_START = 14.0            # first tooth starts this far (along the arm) past the sharp inner corner
TAPER_START = 0.5             # fraction of half-arm length where the taper starts


def x_axes(g=G200):
    th = math.atan2(g.H / 2 - g.HT, g.W / 2 - g.HT)
    T = math.hypot(g.W / 2 - g.HT, g.H / 2 - g.HT)
    phis = [th, math.pi - th, math.pi + th, 2 * math.pi - th]
    return th, T, phis


def _hprof(t, T, hc, ht):
    t1 = TAPER_START * T
    if t <= t1:
        return hc
    u = min(1.0, (t - t1) / (T - t1))
    sm = u * u * (3 - 2 * u)
    return hc + (ht - hc) * sm


def x_outline(off=0.0, r=R_CUT, n_arc=16, n_side=40, g=G200):
    """Closed outline of the X window offset outward by 'off' mm. r = inner-corner radius of the
    base line; the offset line gets r - off (concave corners shrink when offset outward)."""
    th, T, phis = x_axes(g)
    hc, ht = g.HC + off, g.HT + off
    rr = r - off if r > 0 else 0.0
    arms = [((math.cos(p), math.sin(p)), (-math.sin(p), math.cos(p)), p) for p in phis]
    corners = []
    for k in range(4):
        d0, m0, _ = arms[k]
        d1, m1, _ = arms[(k + 1) % 4]
        X = line_x(mul(m0, hc), d0, mul(m1, -hc), d1)
        a, b = d0, d1
        if rr > 0.05:
            gamma = math.acos(max(-1, min(1, dot(a, b))))
            dist = rr / math.tan(gamma / 2)
            Ta, Tb = add(X, mul(a, dist)), add(X, mul(b, dist))
            cc = add(X, mul(unit(add(a, b)), rr / math.sin(gamma / 2)))
            a0 = math.atan2(Ta[1] - cc[1], Ta[0] - cc[0])
            a1 = math.atan2(Tb[1] - cc[1], Tb[0] - cc[0])
            da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
            arc = [add(cc, (rr * math.cos(a0 + da * i / n_arc), rr * math.sin(a0 + da * i / n_arc)))
                   for i in range(n_arc + 1)]
            ta, tb = dot(Ta, a), dot(Tb, b)
        else:
            arc = [X]
            ta, tb = dot(X, a), dot(X, b)
        corners.append((arc, ta, tb))
    pts = []
    for k in range(4):
        d, m, phi = arms[k]
        t_start = corners[k - 1][2]
        for i in range(1, n_side):
            t = t_start + (T - t_start) * i / n_side
            pts.append(add(mul(d, t), mul(m, -_hprof(t, T, hc, ht))))
        cc = mul(d, T)
        for i in range(n_arc * 2 + 1):
            ang = phi - math.pi / 2 + math.pi * i / (n_arc * 2)
            pts.append(add(cc, (ht * math.cos(ang), ht * math.sin(ang))))
        t_end = corners[k][1]
        for i in range(1, n_side):
            t = T - (T - t_end) * i / n_side
            pts.append(add(mul(d, t), mul(m, _hprof(t, T, hc, ht))))
        pts.extend(corners[k][0])
    return pts


def base_outline(g=G200, **kw):
    return x_outline(0.0, R_CUT, g=g, **kw)


def stitch_outline(g=G200, **kw):
    return x_outline(STITCH_OFF, R_CUT, g=g, **kw)


def patch_outline(g=G200, **kw):
    o = STITCH_OFF + PATCH_OFF
    return x_outline(o, o + R_PATCH, g=g, **kw)


def x_corner_points(g=G200, off=0.0):
    """Sharp (unrounded) inner-corner points of the outline offset by 'off'."""
    th, T, phis = x_axes(g)
    arms = [((math.cos(p), math.sin(p)), (-math.sin(p), math.cos(p))) for p in phis]
    out = []
    for k in range(4):
        d0, m0 = arms[k]
        d1, m1 = arms[(k + 1) % 4]
        out.append(line_x(mul(m0, g.HC + off), d0, mul(m1, -(g.HC + off)), d1))
    return out


def resample(pts, step):
    out = []
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        k = max(1, int(L / step))
        for j in range(k):
            out.append(add(a, mul(sub(b, a), j / k)))
    return out


def signed_area(pts):
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return s / 2


def smooth01(u):
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def _arclen(pts):
    sl = [0.0]
    for i in range(1, len(pts)):
        sl.append(sl[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
    total = sl[-1] + math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1])
    return sl, total


def interp_keys(keys, s, total, ks=None):
    """Linear interpolation in a closed (wrapping) list of (s, value) keys sorted by s."""
    if ks is None:
        ks = [k[0] for k in keys]
    i = bisect.bisect_right(ks, s) - 1
    if i < 0:
        a, b = (keys[-1][0] - total, keys[-1][1]), keys[0]
    elif i >= len(keys) - 1:
        a, b = keys[-1], (keys[0][0] + total, keys[0][1])
    else:
        a, b = keys[i], keys[i + 1]
    t = (s - a[0]) / max(1e-9, b[0] - a[0])
    return a[1] + (b[1] - a[1]) * t


def _inward_normals(base):
    A = signed_area(base)
    n = len(base)
    out = []
    for i in range(n):
        a, b = base[i - 1], base[(i + 1) % n]
        t = unit(sub(b, a))
        out.append((-t[1], t[0]) if A > 0 else (t[1], -t[0]))
    return out


def jag_profile(n_len, rng):
    """Variant A: slow undulation + small irregular teeth. Returns (big, small) key lists (fractions)."""
    big, small = [], []
    s = 0.0
    while s < n_len:
        big.append((s, rng.uniform(0.0, 0.5)))
        s += rng.uniform(7.0, 15.0)
    s = 0.0
    while s < n_len:
        pitch = rng.uniform(2.0, 5.5)
        pk = rng.uniform(0.3, 0.7) * pitch
        small.append((s, rng.uniform(0.0, 0.08)))
        small.append((s + pk, rng.uniform(0.12, 0.45) if rng.random() > 0.22 else rng.uniform(0.5, 0.75)))
        s += pitch
    return big, small


_CUT_CACHE = {}


def x_cut_A(g=G200, seed=11):
    """Variant A (v0 drawing): base line pushed INTO the window by 0..3 mm; 0-1 mm at tips and corners."""
    key = ("A", g.name, seed)
    if key in _CUT_CACHE:
        return _CUT_CACHE[key]
    base = resample(base_outline(g, n_arc=24, n_side=80), 0.3)
    th, T, phis = x_axes(g)
    tips = [(T * math.cos(p), T * math.sin(p)) for p in phis]
    crn = x_corner_points(g)
    sl, total = _arclen(base)
    rng = random.Random(seed)
    big, small = jag_profile(total, rng)
    kb, ksm = [k[0] for k in big], [k[0] for k in small]
    nins = _inward_normals(base)
    out = []
    for i, p in enumerate(base):
        dt = min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in tips)
        dc = min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in crn)
        amp = JAG_A
        if dt < 30:
            amp = 0.8 + (JAG_A - 0.8) * max(0.0, (dt - 12) / 18)
        if dc < 14:
            amp = min(amp, 0.8 + (JAG_A - 0.8) * max(0.0, (dc - 8) / 6))
        fr = min(1.0, interp_keys(big, sl[i], total, kb) + interp_keys(small, sl[i], total, ksm))
        out.append(add(p, mul(nins[i], fr * amp)))
    _CUT_CACHE[key] = out
    return out


def tooth_keys(total, rng, local=None):
    """Variant B tooth profile along a straight strip (page 3 edge detail): valleys 0-0.6 mm, teeth TOOTH_D deep at
    TOOTH_SP spacing. local(s) -> (envelope 0..1, local width mm) optionally limits the teeth."""
    keys = []
    s = 0.0
    while s < total - 1e-6:
        sp = rng.uniform(*TOOTH_SP)
        if total - (s + sp) < TOOTH_SP[0]:
            sp = total - s
        f = rng.uniform(0.3, 0.7)
        e, w = local(s + f * sp) if local else (1.0, 1e9)
        dep = min(rng.uniform(*TOOTH_D), 0.9 * sp, 0.3 * w) * e
        ev = local(s)[0] if local else 1.0
        v = rng.uniform(0.0, 0.6) * ev
        j1, j2 = rng.uniform(-0.5, 0.5) * e, rng.uniform(-0.5, 0.5) * e
        keys.append((s, v))
        keys.append((s + f * sp * 0.5, max(0.0, (v + dep) * 0.5 + j1)))
        keys.append((s + f * sp, dep))
        keys.append((s + f * sp + (1 - f) * sp * 0.5, max(0.0, dep * 0.5 + j2)))
        s += sp
    return keys


def _arm_frames(g):
    th, T, phis = x_axes(g)
    return T, [((math.cos(p), math.sin(p)), (-math.sin(p), math.cos(p))) for p in phis]


def _side_corner_t(g):
    """Axial position t of the sharp inner corner that ends each (arm, side); side = sign of the m-coordinate."""
    T, fr = _arm_frames(g)
    out = {}
    for k, (d, m) in enumerate(fr):
        for X in x_corner_points(g):
            mm = dot(X, m)
            if abs(abs(mm) - g.HC) < 1e-6 and dot(X, d) > 0:
                out[(k, 1 if mm > 0 else -1)] = dot(X, d)
    if len(out) != 8:
        raise SystemExit(f"X {g.name}: inner-corner lookup failed")
    return out


def arm_width(g, t):
    """Local width of the BASE line across the arm at axial position t (mm)."""
    th, T, phis = x_axes(g)
    return 2 * _hprof(max(0.0, t), T, g.HC, g.HT)


def _teeth_keys(teeth):
    """(t, depth) keys of one side of one arm; each tooth: valley, mid-rise, peak, mid-fall (irregular flanks)."""
    keys = []
    for i, tt in enumerate(teeth):
        d = tt["d"]
        if d <= 0:
            keys.append((tt["t0"], 0.0))
            continue
        js = min(1.0, d / 5.0)
        v0 = tt["v"] if i == 0 or teeth[i - 1]["d"] > 0 else 0.0
        v0 = min(v0, 0.1 * d)
        keys.append((tt["t0"], v0))
        keys.append((tt["t0"] + (tt["tp"] - tt["t0"]) * 0.5, max(0.0, (v0 + d) * 0.5 + tt["j1"] * js)))
        keys.append((tt["tp"], d))
        keys.append((tt["tp"] + (tt["t1"] - tt["tp"]) * 0.5, max(0.0, d * 0.5 + tt["j2"] * js)))
    if teeth:
        keys.append((teeth[-1]["t1"], 0.0))
    return keys


def _depth_at(keys, t):
    if not keys or t <= keys[0][0] or t >= keys[-1][0]:
        return 0.0
    i = bisect.bisect_right([k[0] for k in keys], t) - 1
    a, b = keys[i], keys[i + 1]
    return a[1] + (b[1] - a[1]) * (t - a[0]) / max(1e-9, b[0] - a[0])


def _tooth_line(g, tt, s):
    """One tooth's cut line in arm-local coordinates (t along the arm, y across; side s = +1 / -1)."""
    ks = _teeth_keys([tt])
    n = max(2, int((tt["t1"] - tt["t0"]) / 0.1))
    ts = [tt["t0"] + (tt["t1"] - tt["t0"]) * i / n for i in range(n + 1)]
    return LineString([(t, s * (arm_width(g, t) / 2 - _depth_at(ks, t))) for t in ts])


def _plan_arm(g, rng, t_lo, t_hi, t_c):
    """Teeth for both sides of one arm. Rules: 3-8 mm deep at 5-15 mm spacing; the two sides are staggered so that
    the combined depth at any cross-section is <= COMB_MAX of the local arm width and the brown between opposite
    teeth stays >= BROWN_MIN; less depth where the arm narrows; first tooth ramps in after the inner corner."""
    wmin = BROWN_MIN[g.name]
    sides = {}
    for s, off in ((1, rng.uniform(0.0, 2.0)), (-1, rng.uniform(3.0, 7.0))):
        teeth = []
        pos = t_lo[s] + off
        while True:
            sp = rng.uniform(*TOOTH_SP)
            if pos + sp > t_hi:
                break
            f = rng.uniform(0.3, 0.7)
            teeth.append({"t0": pos, "t1": pos + sp, "tp": pos + f * sp, "d": rng.uniform(*TOOTH_D),
                          "v": rng.uniform(0.0, 0.4), "j1": rng.uniform(-0.5, 0.5), "j2": rng.uniform(-0.5, 0.5)})
            pos += sp
        for tt in teeth:
            ts = [tt["t0"] + (tt["t1"] - tt["t0"]) * i / 10 for i in range(11)]
            cap = min(min(COMB_MAX * arm_width(g, t), arm_width(g, t) - wmin) for t in ts) - 0.4
            cap = min(cap, 2.5 + 0.5 * (tt["tp"] - t_c[s] - TOOTH_START))
            tt["floor"] = TOOTH_D[0] if cap >= TOOTH_D[0] else 1.5
            tt["d"] = min(tt["d"], cap)
            if tt["d"] < 1.5:
                tt["d"] = 0.0
        sides[s] = teeth
    for _ in range(3000):
        worst = None
        for a in sides[1]:
            if a["d"] <= 0:
                continue
            la = _tooth_line(g, a, 1)
            for b in sides[-1]:
                if b["d"] <= 0 or b["t0"] > a["t1"] + 16 or b["t1"] < a["t0"] - 16:
                    continue
                gap = la.distance(_tooth_line(g, b, -1))
                lo, hi = max(a["t0"], b["t0"]), min(a["t1"], b["t1"])
                c1 = -1.0
                if hi > lo:
                    ka, kb = _teeth_keys([a]), _teeth_keys([b])
                    for i in range(61):
                        t = lo + (hi - lo) * i / 60
                        c1 = max(c1, _depth_at(ka, t) + _depth_at(kb, t) - COMB_MAX * arm_width(g, t))
                sev = max(wmin + 0.3 - gap, c1 + 0.12)
                if sev > 0 and (worst is None or sev > worst[0]):
                    worst = (sev, a, b)
        if worst is None:
            return sides
        _, a, b = worst
        cand = [x for x in (a, b) if x["d"] > x["floor"] + 1e-6]
        if cand:
            x = max(cand, key=lambda z: z["d"])
            x["d"] = max(x["floor"], x["d"] - 0.25)
        else:                                   # both at 3 mm: the arm is narrowing, the tip-side tooth gives way
            x = min((a, b), key=lambda z: arm_width(g, z["tp"]))
            x["floor"] = 1.5
            x["d"] -= 0.25
            if x["d"] < 1.5:
                x["d"] = 0.0
    raise SystemExit(f"X {g.name}: tooth planning did not converge")


def x_cut_B(g=G200, seed=5):
    """Variant B (template): irregular teeth pointing INTO the window, 3-8 mm deep (less where the arm narrows) at
    5-15 mm spacing, planned per arm and side (see _plan_arm). Valleys sit on the base line (4 mm from the stitch).
    No teeth on inner-corner arcs (teeth start TOOTH_START mm past the sharp corner) or in the last TIP_FREE mm
    before each tip cap."""
    key = ("B", g.name, seed)
    if key in _CUT_CACHE:
        return _CUT_CACHE[key]
    base = resample(base_outline(g, n_arc=24, n_side=80), 0.25)
    T, fr = _arm_frames(g)
    tcs = _side_corner_t(g)
    rng = random.Random(seed)
    t_hi = T - TIP_FREE[g.name]
    plans = {}
    for k in range(4):
        tc = {s: tcs[(k, s)] for s in (1, -1)}
        sides = _plan_arm(g, rng, {s: tc[s] + TOOTH_START for s in (1, -1)}, t_hi, tc)
        for s in (1, -1):
            plans[(k, s)] = _teeth_keys(sides[s])
    nins = _inward_normals(base)
    out = []
    for i, p in enumerate(base):
        k = max(range(4), key=lambda j: dot(p, fr[j][0]))
        d, m = fr[k]
        t = dot(p, d)
        dep = _depth_at(plans[(k, 1 if dot(p, m) > 0 else -1)], t) if t < T else 0.0
        out.append(add(p, mul(nins[i], dep)))
    _CUT_CACHE[key] = out
    _CUT_CACHE[("plan", g.name, seed)] = plans
    return out


def x_cut_plan(g, seed=5):
    x_cut_B(g, seed)
    return _CUT_CACHE[("plan", g.name, seed)]


def brown_bottleneck(poly_pts, a, b):
    """Widest disc (diameter, mm) that can travel inside the window polygon from point a to point b."""
    P = Polygon(poly_pts).buffer(0)

    def ok(r):
        E = P.buffer(-r, quad_segs=16)
        for gg in (list(E.geoms) if hasattr(E, "geoms") else [E]):
            if not gg.is_empty and gg.distance(Point(a)) < 1e-6:
                return gg.distance(Point(b)) < 1e-6
        return False
    lo, hi = 0.0, 20.0
    for _ in range(26):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return 2 * lo


def cut_stats(g):
    """Checks for the CUT_JAG layer: combined tooth depth / arm width (max), narrowest brown from the X centre to
    the end of the toothed zone and to each tip centre, tooth depths."""
    T, fr = _arm_frames(g)
    plans = x_cut_plan(g)
    comb = 0.0
    for k in range(4):
        for i in range(int(T * 10)):
            t = i * 0.1
            comb = max(comb, (_depth_at(plans[(k, 1)], t) + _depth_at(plans[(k, -1)], t)) / arm_width(g, t))
    cut = x_cut_B(g)
    t_hi = T - TIP_FREE[g.name]
    arm_min = min(brown_bottleneck(cut, (0, 0), (t_hi * d[0], t_hi * d[1])) for d, m in fr)
    tip_min = min(brown_bottleneck(cut, (0, 0), (T * d[0], T * d[1])) for d, m in fr)
    deps = [kk[1] for keys in plans.values() for i, kk in enumerate(keys) if i % 4 == 2 and i < len(keys) - 1]
    shallow_w = [arm_width(g, kk[0]) for keys in plans.values() for i, kk in enumerate(keys)
                 if i % 4 == 2 and i < len(keys) - 1 and kk[1] < TOOTH_D[0]]
    return {"comb": comb, "arm_min": arm_min, "tip_min": tip_min, "n": len(deps), "dmin": min(deps),
            "dmax": max(deps), "n_shallow": len(shallow_w), "shallow_wmax": max(shallow_w) if shallow_w else 0.0}


x_cut_line = x_cut_B


def stitch_follow(g=G150):
    """Proto B option: stitch that follows the jag at >= 4 mm. Outward 4 mm offset of the window,
    then closed with a 3 mm disc so every concave turn has r >= 3 mm (machine-friendly)."""
    key = ("F", g.name)
    if key in _CUT_CACHE:
        return _CUT_CACHE[key]
    win = Polygon(x_cut_B(g)).buffer(0)
    sf = win.buffer(STITCH_OFF + 3.0, quad_segs=24).buffer(-3.0, quad_segs=24)
    pts = list(sf.exterior.coords)[:-1]
    _CUT_CACHE[key] = pts
    return pts


def top_corner_depth(g=G200):
    """Distance from X centre up to the top inner-corner point of the STITCH line (on CF)."""
    st = stitch_outline(g, n_arc=32, n_side=60)
    cand = [-y for (x, y) in st if abs(x) < 0.05 and y < 0]
    if not cand:
        cand = [-y for (x, y) in st if abs(x) < 0.6 and y < 0]
    return min(cand)


def stitch_length(pts):
    return LinearRing(pts).length


def bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def tx(pts, ox, oy, k):
    return [(ox + x * k, oy + y * k) for x, y in pts]


# ------------------------------------------------------------------ garment geometry (cm)
NECK_HW = 6.75 * 2.54 / 2       # collar width / 2 (M)
SP = (20 * 2.54 / 2, 2.5)       # shoulder point, 2.5 cm shoulder drop (drawing assumption)
SLV_A = math.radians(16)
SLV_L = 11 * 2.54
CUFF = 8.5 * 2.54
BODY_HW = 25.75 * 2.54 / 2
UA = (BODY_HW, 27.0)            # armhole depth: drawing only
LEN = 26 * 2.54
FND = 10.0                      # front neck drop: drawing only (TBD)
BND = 2.0                       # back neck drop: drawing only (TBD)
RIB = 2.54
X_CENTER_Y = 27.0               # proposal, M
HEM_W = 2.2                     # hem height drawing only (as base)


def E(a, b, t0=0.0, t1=math.pi, n=48):
    return [(a * math.cos(t0 + (t1 - t0) * i / n), b * math.sin(t0 + (t1 - t0) * i / n)) for i in range(n + 1)]


def tee_points():
    HPS = (NECK_HW, 0.0)
    CT = add(SP, mul((math.cos(SLV_A), math.sin(SLV_A)), SLV_L))
    CB = add(CT, mul((-math.sin(SLV_A), math.cos(SLV_A)), CUFF))
    HEM = (BODY_HW, LEN)
    return HPS, CT, CB, HEM


def checker_band(A, B, nrm, depth_rows, q, phase, clip_p0, clip_n, border=0.0, line_at=None,
                 sw=0.12):
    """Draw checker squares along A->B (page coords). depth_rows: list of (v0, v1, row_idx).
    Squares of size q along the band, alternating colours; clipped by half-plane."""
    u = unit(sub(B, A))
    L = math.hypot(B[0] - A[0], B[1] - A[1]) + 3 * q
    out = []
    n_sq = int(L / q) + 1
    for (v0, v1, row) in depth_rows:
        for i in range(n_sq):
            u0, u1 = i * q, (i + 1) * q
            pts = [add(add(A, mul(u, u0)), mul(nrm, v0)), add(add(A, mul(u, u1)), mul(nrm, v0)),
                   add(add(A, mul(u, u1)), mul(nrm, v1)), add(add(A, mul(u, u0)), mul(nrm, v1))]
            pts = clip_half(pts, clip_p0, clip_n)
            if len(pts) < 3:
                continue
            col = CREAM if (i + row + phase) % 2 == 0 else BROWN_BK
            out.append(poly(pts, fill=col, stroke=None))
    return "".join(out)


def draw_tee(cx, hy, s, view="front", show_x=True, detail=True, lw=0.3):
    """Flat sketch of the M tee. cx = CF page x, hy = HPS-line page y, s = page mm per cm.
    Returns (svg, P) where P maps garment cm -> page mm."""
    def P(x, y):
        return (cx + x * s, hy + y * s)

    HPS, CT, CBt, HEM = tee_points()
    right = [HPS, SP, CT, CBt, UA, HEM]
    left = [(-x, y) for (x, y) in reversed(right)]
    if view == "front":
        top = [(x, y) for (x, y) in reversed(E(NECK_HW, BND))]
    else:
        top = [(x, y) for (x, y) in reversed(E(NECK_HW, -0.45))]
    sil = right + left + top[1:-1]
    out = [poly([P(*p) for p in sil], fill=CREAM, stroke=INK, sw=lw)]
    dsh = f"{f2(0.55 * s)} {f2(0.4 * s)}"
    thin = lw * 0.7
    # armhole seams
    for sg in (1, -1):
        out.append(line(*P(sg * SP[0], SP[1]), *P(sg * UA[0], UA[1]), INK, thin))
    # hem coverstitch (2 rows, drawing only)
    for yy in (LEN - HEM_W, LEN - HEM_W + 0.64):
        out.append(line(*P(-BODY_HW + 0.3, yy), *P(BODY_HW - 0.3, yy), GREY, thin * 0.8, dash=dsh))
    # sleeve hems
    ax = (math.cos(SLV_A), math.sin(SLV_A))
    for sg in (1, -1):
        for dd in (HEM_W, HEM_W - 0.64):
            a = sub(CT, mul(ax, dd))
            b = sub(CBt, mul(ax, dd))
            out.append(line(*P(sg * a[0], a[1]), *P(sg * b[0], b[1]), GREY, thin * 0.8, dash=dsh))
    # neck
    if view == "front":
        front_seam = E(NECK_HW, FND)
        open_front = E(NECK_HW - 1.9, FND - RIB)
        open_back = E(NECK_HW - 1.9, BND + 2.3)
        opening = open_front + list(reversed(open_back))
        out.append(poly([P(*p) for p in opening], fill=INSIDE, stroke=INK, sw=thin))
        out.append(poly([P(*p) for p in front_seam], stroke=INK, sw=thin, closed=False))
        # neck coverstitch
        cs = E(NECK_HW + 0.55, FND + 0.6)
        out.append(poly([P(*p) for p in cs], stroke=GREY, sw=thin * 0.8, closed=False, dash=dsh))
        if detail:
            # labels inside CB neck
            out.append(rect(*P(-1.3, BND + 2.35), 2.6 * s, 1.5 * s, WHITE, INK, 0.15))
            out.append(rect(*P(-0.8, BND + 2.35 + 1.5), 1.6 * s, 0.9 * s, WHITE, INK, 0.15))
    else:
        back_seam = E(NECK_HW, BND)
        out.append(poly([P(*p) for p in back_seam], stroke=INK, sw=thin, closed=False))
        # back neck tape stitch lines (outside view) and hidden tape
        for aa, bb in ((0.15, 0.2), (0.45, 1.15)):
            cs = E(NECK_HW + aa, BND + bb)
            out.append(poly([P(*p) for p in cs], stroke=GREY, sw=thin * 0.8, closed=False, dash=dsh))
        if detail:
            # hidden labels at CB neck (inside)
            out.append(rect(*P(-1.3, BND + 0.25), 2.6 * s, 1.5 * s, "none", MID, 0.15,
                            dash=f"{f2(0.3 * s)} {f2(0.25 * s)}"))
    # shoulder tape (half width visible in each view: 1 row of squares + border)
    for sg in (1, -1):
        A = P(sg * HPS[0], HPS[1])
        B = P(sg * SP[0], SP[1])
        u = unit(sub(B, A))
        nrm = (-u[1], u[0]) if sg == 1 else (u[1], -u[0])
        if nrm[1] < 0:
            nrm = mul(nrm, -1)
        # clip by armhole line (keep the side of the body containing HPS)
        a_dir = unit(sub(P(sg * UA[0], UA[1]), B))
        cn = (-a_dir[1], a_dir[0])
        if dot(sub(A, B), cn) > 0:
            cn = mul(cn, -1)
        q = 0.75 * s
        phase = 0 if view == "front" else 1
        out.append(checker_band(A, B, nrm, [(0, q, 0)], q, phase, B, cn))
        # border strip and thin line
        b0 = [add(A, mul(nrm, q)), add(B, mul(nrm, q)), add(B, mul(nrm, 1.0 * s)), add(A, mul(nrm, 1.0 * s))]
        b0 = clip_half(b0, B, cn)
        out.append(poly(b0, fill=CREAM, stroke=None))
        l0 = [add(A, mul(nrm, 0.87 * s)), add(add(B, mul(nrm, 0.87 * s)), mul(u, 3 * s))]
        lc = clip_half([l0[0], l0[1], add(l0[1], mul(nrm, 0.05 * s)), add(l0[0], mul(nrm, 0.05 * s))], B, cn)
        out.append(poly(lc, fill=BROWN_BK, stroke=None))
        edge = clip_half([A, add(B, mul(u, 3 * s)), add(add(B, mul(u, 3 * s)), mul(nrm, 1.0 * s)),
                          add(A, mul(nrm, 1.0 * s))], B, cn)
        out.append(poly(edge, fill="none", stroke=INK, sw=0.12))
    # re-stroke shoulder silhouette on top of tape
    out.append(poly([P(*HPS), P(*SP)], stroke=INK, sw=lw, closed=False))
    out.append(poly([P(-HPS[0], HPS[1]), P(-SP[0], SP[1])], stroke=INK, sw=lw, closed=False))
    # X
    if view == "front" and show_x:
        k = s / 10.0
        ox, oy = P(0, X_CENTER_Y)
        cut = tx(x_cut_B(G200), ox, oy, k)
        st = tx(stitch_outline(G200, n_arc=10, n_side=24), ox, oy, k)
        out.append(poly(cut, fill=BROWN, stroke=INK, sw=0.1))
        out.append(poly(st, stroke=INK, sw=0.12, dash=f"{f2(0.25 * s)} {f2(0.18 * s)}"))
    if view == "front" and detail:
        # care label hidden in wearer's left side seam (viewer right)
        out.append(rect(*P(BODY_HW - 2.4, LEN - 13.0), 2.4 * s, 3.4 * s, "none", MID, 0.15,
                        dash=f"{f2(0.3 * s)} {f2(0.25 * s)}"))
    return "".join(out), P


# ------------------------------------------------------------------ page frame
def wordmark_img(x, y, h):
    b = base64.b64encode(open(WORDMARK, "rb").read()).decode()
    w = h * 1730 / 516
    return f'<image x="{f2(x)}" y="{f2(y)}" width="{f2(w)}" height="{f2(h)}" xlink:href="data:image/png;base64,{b}"/>', w


EDGE_MIN = 8.0                  # nothing printed within 8 mm of any page edge (printer unprintable margin)
FOOT_RULE = 198.4               # footer rule; page content must end above CONTENT_BOTTOM
CONTENT_BOTTOM = 197.6


def header(n, t_en, t_zh):
    out = []
    img, w = wordmark_img(10, 8.4, 5.8)
    out.append(img)
    x = 10 + w + 3.5
    out.append(text(x, 11.9, STYLE, 3.2, bold=True))
    x2 = x + tw(STYLE, 3.2, bold=True) + 1.2
    out.append(text(x2, 11.9, "(working code)", 2.0, fill=GREY))
    out.append(text(x, 15.8, f"Base block: {BASE}", 1.9, fill=GREY))
    out.append(text(x + tw(f"Base block: {BASE}", 1.9) + 1.2, 15.8, "原版款号", 1.7, zh=True, fill=GREY))
    tx0 = 112
    out.append(text(tx0, 12.5, t_en, 4.1, bold=True))
    out.append(text(tx0, 16.6, t_zh, 2.45, zh=True, bold=True, fill=ZHC))
    # draft badge
    bx = 244
    out.append(rect(bx, 8.4, 43, 5.8, INK))
    out.append(text(bx + 2.2, 12.4, f"DRAFT {VERSION}", 3.1, bold=True, fill=WHITE))
    out.append(text(bx + 2.2 + tw(f"DRAFT {VERSION}", 3.1, bold=True) + 1.6, 12.4, "草稿 待确认", 2.3, zh=True,
                    bold=True, fill=WHITE))
    out.append(text(287, 16.9, f"{DATE}    Page {n} / {N_PAGES}", 2.0, anchor="end", fill=GREY))
    out.append(line(10, 18.2, 287, 18.2, INK, 0.45))
    return "".join(out)


def footer(n):
    fy = FOOT_RULE + 2.9
    out = [line(10, FOOT_RULE, 287, FOOT_RULE, GREY, 0.2)]
    s1 = (f"CULTSIDERS  |  {STYLE} (working code)  |  Tech pack {VERSION} DRAFT {DATE}  |  Not approved for "
          "sampling or bulk until released as v1.")
    out.append(text(10, fy, s1, 1.85, fill=GREY))
    out.append(text(10 + tw(s1, 1.85) * 0.978 + 0.8, fy, "v1发出前不得打样或开货。", 1.7, zh=True, fill=GREY))
    b, bw, bh = tbd_badge(196.0, fy - 2.4, 1.7)
    out.append(b)
    out.append(text(196.0 + bw + 1.2, fy, "= open point, decide before sampling.", 1.85, fill=GREY))
    out.append(text(287, fy, "待定项：打样前须由客户确认", 1.7, zh=True, fill=GREY, anchor="end"))
    return "".join(out)


def page_svg(n, t_en, t_zh, body):
    return ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{PW}mm" height="{PH}mm" viewBox="0 0 {PW} {PH}">'
            f'<rect x="0" y="0" width="{PW}" height="{PH}" fill="#FFFFFF"/>'
            + header(n, t_en, t_zh) + body + footer(n) + "</svg>")


# ================================================================== PAGE 1: COVER
def check_bar(x, y, scale_txt, vertical=False, L=50.0, size=1.7):
    """50 mm print-check bar with 10 mm black / white segments. (x, y) = start of the bar.
    Horizontal: text to the right. Vertical: text below. Returns svg."""
    o = []
    for i in range(5):
        col = INK if i % 2 == 0 else WHITE
        if vertical:
            o.append(rect(x, y + i * 10, 1.4, 10, col, INK, 0.15))
        else:
            o.append(rect(x + i * 10, y, 10, 1.4, col, INK, 0.15))
    if vertical:
        o.append(line(x - 1.0, y, x + 2.4, y, INK, 0.2))
        o.append(line(x - 1.0, y + L, x + 2.4, y + L, INK, 0.2))
        o.append(text(x + 3.0, y + L / 2 + 0.7, "50 mm", size, bold=True))
        ty = y + L + 3.2
        o.append(text(x - 1.0, ty, f"{scale_txt}: print at 100%", size, bold=True))
        o.append(text(x - 1.0, ty + size * 1.45, "实际大小打印，勿缩放", size * 0.92, zh=True, fill=ZHC))
        o.append(text(x - 1.0, ty + size * 2.9, "measure: bar = 50 mm", size * 0.92, fill=GREY))
    else:
        o.append(line(x, y - 1.0, x, y + 2.4, INK, 0.2))
        o.append(line(x + L, y - 1.0, x + L, y + 2.4, INK, 0.2))
        tx_ = x + L + 2.5
        s1 = f"50 mm check bar  |  {scale_txt}: print at 100%"
        o.append(text(tx_, y + 1.2, s1, size, bold=True))
        o.append(text(tx_ + tw(s1, size, bold=True) + 1.4, y + 1.2, "实际大小打印，勿缩放", size * 0.92, zh=True,
                      fill=ZHC))
    return "".join(o)


def page1():
    o = []
    # --- left: style block
    o.append(text(10, 30, STYLE, 8.0, bold=True))
    o.append(text(10 + tw(STYLE, 8.0, bold=True) + 2.5, 30, "working code", 2.6, fill=GREY))
    o.append(text(10 + tw(STYLE, 8.0, bold=True) + 2.5 + tw("working code", 2.6) + 1.2, 30, "暂定款号", 2.3,
                  zh=True, fill=GREY))
    s, h = bi(10, 33, "Oversized boxy tee: reverse-appliqué X + checker shoulder tape",
              "宽松落肩短袖T恤：前胸反面贴布绣X + 肩缝棋盘格织带", 140, se=3.4, sz=2.6, bold=True)
    o.append(s)
    y = 33 + h + 2.5
    rows = [
        [C("Description", "款式描述", bold=True),
         C("Oversized drop-shoulder tee. Front: X made by reverse appliqué: the cream top layer is cut away "
           "inside the stitch line to show a chocolate-brown jersey under-patch; raw cut edges. Shoulders: "
           "woven checker tape centred over both shoulder seams.",
           "宽松落肩短袖T恤。前胸X为反面贴布绣：车线内剪开米白面布，露出咖啡色汗布底布，剪口毛边。"
           "两边肩缝居中压棋盘格提花织带。")],
        [C("Factory", "工厂", bold=True), C("Dongguan Xinhui Garments Co., Ltd, Humen, Dongguan, Guangdong, China")],
        [C("Factory style no.", "工厂款号", bold=True), C("Factory to assign; reference base below.", "请工厂编号", tbd=True)],
        [C("Base block", "原版", bold=True),
         C(f"{BASE} (DROP 001). Use the same pattern, grading, neck rib, stitch types and label position. "
           "Body fabric per the rule on page 7. Change ONLY the items in this tech pack.",
           f"沿用{BASE}原版纸样、放码、领罗纹、做工及唛位；大身面料按第7页规定。仅修改本工艺单列明项目。")],
        [C("Sizes", "尺码", bold=True), C("S / M / L / XL. Sample size: M", "基码：M")],
        [C("Quantity", "数量", bold=True), C("Bulk quantity and size split (DROP 001 was 100 + 10 extra).",
                                             "大货数量及尺码配比待定", tbd=True)],
        [C("Price", "价格", bold=True), C("Factory to quote; X operation, under-patch fabric and tape attach as "
                                          "separate lines, with and without garment wash.",
                                          "请报价：X工艺、底布、织带及上织带工序分开报价；含水洗与不含水洗分别报价",
                                          tbd=True)],
        [C("Status", "状态", bold=True), C(f"{VERSION} DRAFT for Cultsiders review. v1 goes to the factory for the "
                                           "technique swatch + proto (2 pcs).",
                                           f"{VERSION}草稿供客户审阅；v1发工厂打工艺小样及头办（2件）。")],
        [C("Contacts", "联系人", bold=True), C("Cultsiders: Ivan Montenegro, email / WeChat to be added. "
                                              "Factory merchandiser: name to be added.",
                                              "双方联系人及微信待补充", tbd=True)],
    ]
    s, h = table(10, y, [30, 112], rows, se=2.0, sz=1.76, pad=0.85)
    o.append(s)
    yl = y + h + 2.0
    s, h = bi(10, yl, "Pages: 1 Cover  2 Flats  3 X geometry + template  4 X construction  5 Shoulder tape  "
              "6 Measurements  7 BOM  8 Labels, QC, samples.  Files: " + TPL_PDF_NAME + ", " + DXF200_NAME + ", "
              + DXF150_NAME + " (+ R2000 copies).",
              "页码：1 封面 2 款式图 3 X尺寸及模板 4 X工艺 5 肩部织带 6 尺寸表 7 物料表 8 唛头、验货、样衣。"
              "附件：1:1模板PDF及DXF文件（R12及R2000）。", 142, se=1.8, sz=1.62, gap=0.15)
    o.append(s)
    if yl + h > 127.0:
        WARN.append(f"page1 left block overflow {yl + h:.1f}")

    # --- right: thumbnails
    rx = 160
    o.append(text(rx, 25.5, "FRONT", 2.2, bold=True, fill=GREY))
    o.append(text(rx + 67, 25.5, "BACK", 2.2, bold=True, fill=GREY))
    sv, _ = draw_tee(rx + 30, 31, 0.55, "front", detail=False, lw=0.22)
    o.append(sv)
    sv, _ = draw_tee(rx + 97, 31, 0.55, "back", detail=False, lw=0.22)
    o.append(sv)

    # --- colourway
    cy0 = 72
    s, hh = heading(rx, cy0, "COLOURWAY", "配色", 2.7, width=127)
    o.append(s)
    cy = cy0 + hh + 0.8
    sw_rows = [
        ("Body", "大身", [CREAM], "Cream = DROP 001 bulk shade (approved standard). Body colour itself is still open; "
         "cream proposed.", "米白，以DROP 001大货布为标准；大身颜色待定（建议米白）", True),
        ("Under-patch", "底布", [BROWN], "Chocolate brown jersey, Pantone TCX code open; lab dip required.",
         "咖啡色汗布，潘通TCX色号待定，须打色样", True),
        ("Checker tape", "织带", [CREAM, BROWN_BK], "Cream + brown-black. Founder's physical roll is the standard.",
         "米白 + 深棕黑，以客供实物为准", False),
        ("X thread", "X车线", [CREAM, BROWN_BK], "Proto A: cream (tonal). Proto B: brown-black (contrast). Choose one "
         "for bulk after the protos.", "头办A件米白同色线，B件深棕黑撞色线；看头办后大货二选一", True),
    ]
    for name, zh, cols, en_d, zh_d, tb in sw_rows:
        bx = rx
        for i, col in enumerate(cols):
            o.append(rect(bx + i * 5.5, cy + 0.5, 5.5 if len(cols) > 1 else 11, 7, col, INK, 0.2))
        o.append(text(rx + 13.5, cy + 2.6, name, 2.2, bold=True))
        o.append(text(rx + 13.5, cy + 5.5, zh, 1.9, zh=True, fill=ZHC))
        dx = rx + 34
        if tb:
            b, bw, bh = tbd_badge(dx, cy + 0.4, 1.7)
            o.append(b)
            s, h = bi(dx, cy + 0.4, en_d, zh_d, 93, se=1.95, sz=1.7, first_indent=bw + 0.8)
        else:
            s, h = bi(dx, cy + 0.4, en_d, zh_d, 93, se=1.95, sz=1.7)
        o.append(s)
        cy += max(8.6, h + 1.6)

    # --- bottom: changes vs base
    by = 128
    s, hh = heading(10, by, "CHANGES VS BASE " + BASE, "相对原版的修改", 2.7, width=142)
    o.append(s)
    rows = [
        ["1", C("Front", "前片"), C("DROP 001 printed X removed. New reverse-appliqué X (1:1 template files).",
                                    "取消DROP 001印花X，改为反面贴布绣X（附1:1模板）"), "3, 4"],
        ["2", C("Shoulders", "肩部"), C("Add checker tape over both shoulder seams.", "两边肩缝加棋盘格织带"), "5"],
        ["3", C("Labels", "唛头"), C("Add size + origin label at CB neck and care / content label in side seam.",
                                     "后中领加尺码及产地唛，侧骨加洗水成分唛"), "7, 8"],
        ["4", C("Size spec", "尺寸"), C("Per-POM tolerances; half bottom and XL half cuff to confirm.",
                                        "逐项公差；下摆及XL袖口待确认", tbd=True), "6"],
        ["5", C("Back", "后片"), C("Back: none (recommended), or a new Cultsiders graphic with no straw hat, "
                                   "character or series reference.",
                                   "后片：无图案（建议），或新图案（不得有草帽、人物、作品元素）", tbd=True), "2"],
    ]
    s, h = table(10, by + hh + 0.5, [7, 25, 98, 12], rows,
                 header=[C("#"), C("Area", "部位"), C("Change", "修改内容"), C("Page", "页")], se=1.95, sz=1.72,
                 pad=0.8)
    o.append(s)
    if by + hh + 0.5 + h > 176.0:
        WARN.append(f"page1 changes table overflow {by + hh + 0.5 + h:.1f}")

    # --- revision log
    s, hh = heading(160, by, "REVISION LOG", "修改记录", 2.7, width=127)
    o.append(s)
    rows = [
        ["v0", DATE_V0, C("First draft from technique research. Open points marked TBD.", "初稿，待定项已标黄"),
         "Cultsiders"],
        [VERSION, DATE, C("Review fixes: protos A/B, edge variants, staggered teeth + min. brown, X orientation "
                          "marks, tape stitch, neck-end cover, stitch-crack fallback, corner radii, back artwork, "
                          "fabric rule, US import documents.",
                          "审核修改：头办A/B、边缘方案、锯齿错开及最小咖啡色宽度、X方向标记、织带车线、领口端覆盖、断线对策、"
                          "内角半径、后片图案、面料规定、美国进口文件"), "Cultsiders"],
        ["v1", C("", tbd=True, align="center"), C("TBDs answered; release to factory for swatch + proto.",
                                                  "确认待定项后发工厂打小样及头办"), "Cultsiders"],
    ]
    s, h = table(160, by + hh + 0.5, [10, 19, 83, 15], rows,
                 header=[C("Rev"), C("Date", "日期"), C("Change", "内容"), C("By", "修改人")], se=1.9, sz=1.68,
                 pad=0.8)
    o.append(s)
    yy = by + hh + 0.5 + h + 2.6
    s, h = bi(160, yy, "Brand rule: no character artwork, character names or third-party logos on the garment, "
              "labels, packaging or files. The X is a plain graphic.",
              "品牌规定：服装、唛头、包装及文件上不得出现动漫人物、角色名称或他人商标。X为普通图形。", 125, se=1.9,
              sz=1.68, bold=False)
    o.append(rect(159.0, yy - 1.1, 128.0, h + 2.2, "none", INK, 0.3))
    o.append(s)
    if yy + h + 1.1 > 176.5:
        WARN.append(f"page1 right block overflow {yy + h + 1.1:.1f}")

    # --- critical points strip
    cy = 179.0
    s, hh = heading(10, cy, "CRITICAL QUALITY POINTS", "重点品质要求", 2.6, width=277)
    o.append(s)
    pts = [
        ("Brown must not stain the cream: colourfastness tests and a whole-garment wash test before bulk.",
         "咖啡色不得沾染米白：大货前须做色牢度测试及成衣洗水测试。"),
        ("Body and under-patch in the same fabric article, both pre-shrunk; otherwise the X puckers.",
         "大身与底布用同款面料并预缩，否则X起皱。"),
        ("Never cut the brown. Cut-to-stitch nominal 4-7 mm (B: at the valleys); accept ≥ 3 mm; reject < 3 mm "
         "or any cut stitch.", "不可剪到底布。剪口距车线标准4-7mm（B方案按齿谷）；≥3mm可接受；<3mm或剪断车线为次品。"),
        ("Tape pre-shrunk, sewn flat without stretching, ends covered at the neck, same phase both shoulders.",
         "织带预缩，平车不拉伸，领口端盖好，两肩花位一致。"),
    ]
    for i, (en, zh) in enumerate(pts):
        x = 10 + i * 69.5
        o.append(num(x + 1.7, cy + hh + 2.3, i + 1, 1.6))
        s, h = bi(x + 4.8, cy + hh + 0.6, en, zh, 63, se=1.85, sz=1.64, gap=0.1)
        o.append(s)
        if cy + hh + 0.6 + h > CONTENT_BOTTOM:
            WARN.append(f"page1 critical point {i + 1} overflow {cy + hh + 0.6 + h:.1f}")
    return page_svg(1, "TECH PACK: COVER", "工艺单：封面", "".join(o))


# ================================================================== PAGE 2: FLATS
def page2():
    o = []
    s = 1.2
    fx, bxc, hy = 76.0, 219.0, 38.5
    o.append(text(fx - 55, 26.5, "FRONT VIEW", 2.8, bold=True))
    o.append(text(fx - 55 + tw("FRONT VIEW", 2.8, bold=True) + 2, 26.5, "正面", 2.3, zh=True, bold=True, fill=ZHC))
    o.append(text(bxc - 55, 26.5, "BACK VIEW", 2.8, bold=True))
    o.append(text(bxc - 55 + tw("BACK VIEW", 2.8, bold=True) + 2, 26.5, "背面", 2.3, zh=True, bold=True, fill=ZHC))
    o.append(text(287, 26.5, "Size M, approx. 1:9", 2.0, anchor="end", fill=GREY))
    sv, P = draw_tee(fx, hy, s, "front")
    o.append(sv)
    sv, Q = draw_tee(bxc, hy, s, "back")
    o.append(sv)
    # CF line + HPS line (front)
    o.append(line(*P(0, -3.0), *P(0, LEN + 2.5), GREY, 0.15, dash="3 0.8 0.6 0.8"))
    o.append(text(*add(P(0, LEN + 2.5), (0, 2.6)), "CF", 1.9, anchor="middle", fill=GREY))
    o.append(line(*Q(0, -3.0), *Q(0, LEN + 2.5), GREY, 0.15, dash="3 0.8 0.6 0.8"))
    o.append(text(*add(Q(0, LEN + 2.5), (0, 2.6)), "CB", 1.9, anchor="middle", fill=GREY))
    o.append(line(*P(-NECK_HW - 10, 0), *P(NECK_HW, 0), GREY, 0.15, dash="0.8 0.6"))
    o.append(text(*add(P(-NECK_HW - 10, 0), (0, -0.8)), "HPS", 1.8, fill=GREY))
    # X placement dims
    xc = X_CENTER_Y
    o.append(line(*P(-16.5, xc), *P(0, xc), GREY, 0.15, dash="0.8 0.6"))
    o.append(dim(P(-15.5, 0), P(-15.5, xc), 0, "27 cm (M)", 1.9, tbd=True))
    o.append(dim(P(-10, xc + 10.5), P(10, xc + 10.5), 3.2, "20 cm", 1.9, tbd=True, tside=-1))
    o.append(dim(P(10.5, xc - 10.5), P(10.5, xc + 10.5), -3.5, "21 cm", 1.9, tbd=True))
    # back artwork TBD
    x0, y0 = Q(-15, 9)
    x1, y1 = Q(15, 36)
    o.append(rect(x0, y0, x1 - x0, y1 - y0, CREAM, MID, 0.25, dash="1.2 0.8"))
    bcx = (x0 + x1) / 2
    b, bw, bh = tbd_badge(bcx - 4.5, y0 + 4.0, 2.0)
    o.append(b)
    o.append(text(bcx, y0 + 10.0, "BACK ARTWORK", 2.1, bold=True, anchor="middle"))
    s_, h_ = bi(x0 + 2.0, y0 + 11.6, "None (recommended), or a new Cultsiders graphic: no straw hat, character or "
                "series reference. If printed: print the flat back panel before the tape is attached; no heat press "
                "on the tape.",
                "后片：无图案（建议），或新图案（不得有草帽、人物、作品元素）；如印花须在上织带前于后片裁片完成，织带不可烫压。",
                (x1 - x0) - 4.0, se=1.7, sz=1.55, align="center", fill=GREY, gap=0.4)
    o.append(s_)
    if y0 + 11.6 + h_ > y1 - 0.5:
        WARN.append(f"page2 back artwork text overflow {y0 + 11.6 + h_:.1f} > {y1:.1f}")

    # callouts: (n, anchor page point, badge page point)
    HPS, CT, CBt, HEM = tee_points()
    th, T, phis = x_axes()
    arm_pt = P(0.1 * T * 0.62 * math.cos(phis[0]), xc + 0.1 * T * 0.62 * math.sin(phis[0]))
    calls = [
        (1, arm_pt, P(17.5, 46.5)),
        (2, P((HPS[0] + SP[0]) / 2 + 3, 1.2), add(P(SP[0] + 4, -6), (0, 0))),
        (3, P(-NECK_HW + 1.0, FND - 3.2), add(P(-NECK_HW - 9, -6.5), (0, 0))),
        (4, P(0, BND + 3.1), add(P(-4.0, -6.8), (0, 0))),
        (5, P(-(CT[0] + CBt[0]) / 2 + 1.5, (CT[1] + CBt[1]) / 2 + 0.2), add(P(-CT[0], 36), (-2, 0))),
        (6, P(-20, LEN - HEM_W + 0.3), add(P(-BODY_HW, LEN + 4.5), (-4, 0))),
        (7, P(BODY_HW - 1.2, LEN - 11.3), add(P(BODY_HW, LEN + 4.5), (5, 0))),
        (8, Q(-(HPS[0] + SP[0]) / 2 - 2, 1.4), add(Q(-SP[0] - 4, -6), (0, 0))),
        (9, Q(3.5, BND + 1.0), add(Q(9, -6.8), (0, 0))),
        (10, Q(0, BND + 1.0), add(Q(-3.0, -6.8), (0, 0))),
        (11, Q(-26.9, 7.5), Q(-43, -3.5)),
    ]
    for n, a, b in calls:
        o.append(leader(b, a))
        o.append(num(b[0], b[1], n, 1.9))

    # legend
    ly = 128.5
    s_, hh = heading(10, ly, "CALLOUTS", "说明", 2.7, width=277)
    o.append(s_)
    items = [
        (1, "Reverse-appliqué X: cream top layer cut away to show brown under-patch. 1:1 template files; see pages "
            "3 and 4.", "反面贴布绣X：剪开米白面布露出咖啡色底布；附1:1模板文件，见第3、4页。", False),
        (2, "Checker tape centred on shoulder seam, neck seam to sleeve seam. Each view shows half the tape "
            "width. See page 5.", "棋盘格织带居中压肩缝，由领骨至袖窿骨；每个视图只见一半宽度。见第5页。", False),
        (3, "Neck rib 1\" (2.5 cm) finished, as base.", "领罗纹成品高2.5cm，同原版。", False),
        (4, "Inside CB neck: CS main label, artwork TBD (page 7) + NEW size / origin label (page 8).",
         "后中领内：主唛稿待定（见第7页）+ 新增尺码及产地唛（第8页）。", True),
        (5, "Sleeve hem coverstitch, as base.", "袖口冚车，同原版。", False),
        (6, "Body hem coverstitch, as base.", "下摆冚车，同原版。", False),
        (7, "NEW care / content label in wearer's left side seam, inside; height above hem open.",
         "新增洗水成分唛，车于穿着者左侧骨内，离下摆高度待定。", True),
        (8, "Tape back half. Neck end caught in the neck seam and covered by the back neck tape; sleeve end caught "
            "in the armhole seam.", "织带后半部分；领口端夹入领骨并由后领贴盖住，袖窿端夹入上袖骨。", False),
        (9, "Back neck tape inside, as base, but extended 2 cm past each shoulder seam onto the front neckline to "
            "fully cover the checker tape ends (page 5).",
         "后领贴同原版，但两端各过肩缝2cm至前领，完全盖住织带端口（第5页）。", False),
        (10, "Labels at CB neck, inside (hidden line).", "后中领内唛头（虚线）。", False),
        (11, "Armhole seam as base; tape end enclosed.", "上袖骨同原版，织带端藏入缝内。", False),
    ]
    colw = 134
    yA = ly + hh + 1.0
    yB = yA
    for i, (n, en, zh, tb) in enumerate(items):
        col = 0 if i < 6 else 1
        x = 10 + col * (colw + 9)
        yy = yA if col == 0 else yB
        o.append(num(x + 2, yy + 1.9, n, 1.7))
        ind = 0
        if tb:
            b, bw, bh = tbd_badge(x + 5.5, yy + 0.2, 1.7)
            o.append(b)
            ind = bw + 0.8
        s_, h = bi(x + 5.5, yy + 0.2, en, zh, colw - 6, se=2.1, sz=1.84, first_indent=ind)
        o.append(s_)
        if col == 0:
            yA += max(h, 4) + 1.7
        else:
            yB += max(h, 4) + 1.7
    # drawing note
    s_, h = tbd_box(10 + colw + 9, yB + 0.6, colw,
                    "Drawing only: armhole, neck drops and hem heights are drawn as assumptions; values come from the "
                    "factory's DROP 001 pattern (page 6, POM I / P / Q). X size and position shown are proposals (Proto A 200 mm; "
                    "Proto B 150 mm, same X centre).",
                    "仅为示意：袖窿、前后领深、下摆高按假设绘制，数值以工厂DROP 001纸样为准（第6页I/P/Q）。X尺寸及位置为建议值"
                    "（头办A件200mm；B件150mm，X中心相同）。")
    o.append(s_)
    if yB + 0.6 + h > CONTENT_BOTTOM or yA > CONTENT_BOTTOM:
        WARN.append(f"page2 callouts overflow {max(yA, yB + 0.6 + h):.1f}")
    return page_svg(2, "FLAT SKETCHES", "款式图（正面 / 背面）", "".join(o))


# ================================================================== PAGE 3: X GEOMETRY
def strip_profile_B(Lu, seed=23):
    """Straight-strip version of the variant B tooth profile (for the edge detail)."""
    keys = tooth_keys(Lu + 20, random.Random(seed))
    ks = [k[0] for k in keys]
    us = [i * 0.1 for i in range(int(Lu / 0.1) + 1)]
    return [(u, interp_keys(keys, u + 3.0, Lu + 20, ks)) for u in us], keys


def page3():
    o = []
    g = G200
    k = 0.5                       # 1:2
    ox, oy = 78.0, 119.0
    o.append(text(10, 25.5, "OUTSIDE VIEW (FACE), SCALE 1:2", 2.6, bold=True))
    o.append(text(10 + tw("OUTSIDE VIEW (FACE), SCALE 1:2", 2.6, bold=True) + 2, 25.5, "正面视图 1:2", 2.2, zh=True,
                  bold=True, fill=ZHC))
    s_, h = bi(10, 27.4, f"1:1 template (PROPOSAL): {TPL_PDF_NAME} (page 1, A3: 200 mm X; page 2, A4: 150 mm X) "
               f"and {DXF200_NAME} / {DXF150_NAME} (R12; R2000 copies *-R2000.dxf). Layers STITCH, BASE, CUT_JAG, PATCH, "
               "CHECK, GUIDE, ORIENT (150 mm file also STITCH_FOLLOW). Units mm, origin = X centre. CHECK = 50 x 50 mm "
               "square: measure it after import. Face view: never mirror or rotate the template, guide or program.",
               "1:1模板（建议稿）：PDF第1页A3为200mm X，第2页A4为150mm X；DXF为R12格式（另附R2000副本）。图层：车线STITCH、"
               "基准线BASE、剪口CUT_JAG、底布PATCH、校准CHECK、GUIDE、ORIENT（150mm另有STITCH_FOLLOW）。单位mm，原点为X中心；"
               "CHECK为50 x 50mm方块，导入后先量。正面视图：模板、剪口模板及绣花程序不可翻转或旋转。", 146, se=1.75, sz=1.58,
               gap=0.15)
    o.append(s_)
    patch = tx(patch_outline(g), ox, oy, k)
    stitch = tx(stitch_outline(g), ox, oy, k)
    cut = tx(x_cut_B(g), ox, oy, k)
    base = tx(base_outline(g), ox, oy, k)
    bb = bbox(patch)
    o.append(rect(bb[0] - 6, bb[1] - 4, bb[2] - bb[0] + 12, bb[3] - bb[1] + 8, CREAM, None))
    o.append(poly(patch, stroke=GREY, sw=0.25, dash="2.2 1.0"))
    o.append(poly(cut, fill=BROWN, stroke=INK, sw=0.18))
    o.append(poly(stitch, stroke=INK, sw=0.28, dash="1.1 0.7"))
    # centre lines
    o.append(line(ox, bb[1] - 7, ox, bb[3] + 5, GREY, 0.15, dash="3 0.8 0.6 0.8"))
    o.append(line(bb[0] - 8, oy, bb[2] + 5, oy, GREY, 0.15, dash="3 0.8 0.6 0.8"))
    o.append(text(ox + 1.0, bb[1] - 5.4, "CF", 1.9, fill=GREY))
    o.append(text(bb[0] - 7.5, oy - 1.0, "X centre", 1.8, fill=GREY))
    # dims
    wb = bbox(base)
    o.append(dim((wb[0], wb[1]), (wb[2], wb[1]), -(wb[1] - bb[1]) - 7.5, "200 mm window width", 2.0, tbd=True,
                 gap=0.5))
    o.append(dim((wb[0], wb[3]), (wb[0], wb[1]), -(wb[0] - bb[0]) - 8.5, "210 mm window height", 2.0, tbd=True,
                 gap=0.5))
    th, T, phis = x_axes(g)
    # arm opening at mid-arm (arm 0 = down-right)
    d0 = (math.cos(phis[0]), math.sin(phis[0]))
    m0 = (-math.sin(phis[0]), math.cos(phis[0]))
    tm = 0.42 * T
    pA = add(mul(d0, tm), mul(m0, -g.HC))
    pB = add(mul(d0, tm), mul(m0, g.HC))
    pA, pB = (ox + pA[0] * k, oy + pA[1] * k), (ox + pB[0] * k, oy + pB[1] * k)
    o.append(dim(pB, pA, 0, "", 1.8, ext=False))
    lab_p = add(pA, (10.0, -3.5))                 # clear of the PATCH line (7 mm outside BASE at 1:2)
    o.append(leader(add(pA, (0.8, -0.6)), lab_p, dot_end=False))
    lab1 = "25 mm arm at BASE"
    tot1 = tw(lab1, 1.9) + tw("TBD", 1.9 * 0.85, bold=True) + 1.6
    o.append(label_box(lab_p[0] + 1.3 + tot1 / 2, lab_p[1] - 0.4, 0, lab1, 1.9, tbd=True))
    o.append(text(lab_p[0] + 0.5, lab_p[1] - 3.4, f"visible brown ≥ {BROWN_MIN['200']:g} mm (teeth staggered)", 1.7))
    # tip width
    d1 = (math.cos(phis[3]), math.sin(phis[3]))
    tipc = (ox + d1[0] * T * k, oy + d1[1] * T * k)
    lab_t = add(tipc, (11.0, 3.6))                # clear of the PATCH cap (r = 9.75 mm at 1:2)
    o.append(leader(add(tipc, (1.6, 0.4)), lab_t, dot_end=False))
    lab2 = "tip 11 mm (10-12)"
    tot2 = tw(lab2, 1.9) + tw("TBD", 1.9 * 0.85, bold=True) + 1.6
    o.append(label_box(lab_t[0] + 1.3 + tot2 / 2, lab_t[1] + 0.6, 0, lab2, 1.9, tbd=True))
    # angle
    r_ = 26
    arc = [(ox + r_ * math.cos(-a), oy + r_ * math.sin(-a)) for a in [th * i / 20 for i in range(21)]]
    o.append(poly(arc, stroke=INK, sw=0.18, closed=False))
    o.append(label_box(ox + r_ + 5.5, oy - 3.4, 0, f"{math.degrees(th):.0f}°", 1.9))
    # inner corner note (top corner, stitch line)
    dtop = top_corner_depth(g)
    cp = (ox, oy - dtop * k)
    l2 = "stitch r ≥ 3, cut r ≥ 7, patch r ≥ 3"
    ly2 = cp[1] - 32.0
    while wedge_halfwidth(g, (ly2 + 0.5 - oy) / k) * k < 1.8 + tw(l2, 1.75) + 1.5:
        ly2 -= 0.5
    o.append(text(ox + 1.8, ly2 - 2.4, "inner corners:", 1.75))
    o.append(text(ox + 1.8, ly2, l2, 1.75))
    o.append(line(ox + 1.4, ly2 + 0.9, cp[0] + 0.15, cp[1] - 0.6, INK, 0.18))
    o.append(circle(cp[0], cp[1], 0.45, INK, None))
    # line keys on the drawing (upper-left arm)
    d2 = (math.cos(phis[2]), math.sin(phis[2]))
    m2 = (-math.sin(phis[2]), math.cos(phis[2]))
    tq = 0.80 * T
    hq = _hprof(tq, T, g.HC, g.HT)
    # labels sit in the cream area to the RIGHT of the 210 mm dimension line (x = bb[0] - 8.5), left-aligned
    lab_x = bb[0] - 5.0
    if lab_x < bb[0] - 8.5 + 1.5:
        WARN.append("page3 line-key labels too close to the 210 mm dimension line")
    for off, lab, dy in ((0.0, "CUT_JAG", 0.0), (STITCH_OFF, "STITCH", 3.2),
                         (STITCH_OFF + PATCH_OFF, "PATCH", 6.4)):
        q = add(mul(d2, tq), mul(m2, -(hq + off)))
        qp = (ox + q[0] * k, oy + q[1] * k)
        yl = bb[1] + 30.6 + dy
        o.append(rect(lab_x - 0.4, yl - 1.45, tw(lab, 1.6) + 0.8, 1.95, CREAM, None))
        o.append(text(lab_x, yl, lab, 1.6, fill=GREY))
        o.append(leader((lab_x + tw(lab, 1.6) + 0.7, yl - 0.55), qp, sw=0.14))
    o.append(check_bar(10.0, 190.5, "1:2"))

    # ---------------- right: edge variants 1.5:1
    rx = 163
    s_, hh = heading(rx, 22, "EDGE VARIANTS, SCALE 1.5:1", "边缘方案 1.5:1（小样对比）", 2.6, width=124)
    o.append(s_)
    kk = 1.5
    pw_ = 59.0
    Lu = pw_ / kk
    top_u, bot_u = -16.5, 11.5
    py0 = 22 + hh + 5.2
    keysA = [(0, 0.1), (2.2, 0.45), (3.4, 0.2), (5.8, 0.75), (7.0, 0.3), (8.6, 0.55), (11.0, 0.0), (13.1, 0.35),
             (14.5, 0.12), (17.2, 0.9), (18.6, 0.4), (20.0, 0.62), (22.4, 0.08), (24.5, 0.3), (26.0, 0.05),
             (29.0, 1.0), (30.6, 0.35), (32.8, 0.6), (35.0, 0.15), (37.0, 0.5), (39.0, 0.2), (42.0, 0.4)]
    profA = [(u * Lu / 42.0, fr * JAG_A) for u, fr in keysA]
    profB, kB = strip_profile_B(Lu)
    titles = [("A", "freehand jag 0-3 mm inside BASE"), ("B", "teeth 3-8 mm deep (less on narrow arms), 5-15 apart")]
    for idx, (prof, (tag, ttl)) in enumerate(zip((profA, profB), titles)):
        px = rx + idx * (pw_ + 6.0)

        def Y(u):
            return py0 + (u - top_u) * kk
        o.append(text(px, py0 - 1.3, tag, 2.3, bold=True))
        o.append(text(px + 3.2, py0 - 1.3, ttl, 1.75, fill=GREY))
        o.append(rect(px, Y(top_u), pw_, (bot_u - top_u) * kk, CREAM, None))
        cutp = [(px + u * kk, Y(dd)) for u, dd in prof]
        o.append(poly(cutp + [(px + pw_, Y(bot_u)), (px, Y(bot_u))], fill=BROWN, stroke=None))
        o.append(poly(cutp, stroke=INK, sw=0.25, closed=False))
        o.append(line(px, Y(-STITCH_OFF), px + pw_, Y(-STITCH_OFF), INK, 0.32, dash="2.0 1.1"))
        o.append(line(px, Y(-STITCH_OFF - PATCH_OFF), px + pw_, Y(-STITCH_OFF - PATCH_OFF), GREY, 0.25,
                      dash="2.2 1.0"))
        o.append(line(px, Y(0), px + pw_, Y(0), MID, 0.12, dash="0.3 0.5"))
        o.append(rect(px, Y(top_u), pw_, (bot_u - top_u) * kk, "none", GREY, 0.2))
        o.append(text(px + 1.2, Y(bot_u) - 1.3, "brown window", 1.55, fill=WHITE))
        o.append(text(px + 1.2, Y(top_u) + 2.4, "cream, outside", 1.55, fill=GREY))
        # patch dim (right edge)
        xr_ = px + pw_ - 3.0
        o.append(dim((xr_, Y(-STITCH_OFF)), (xr_, Y(-STITCH_OFF - PATCH_OFF)), 0, "", 1.6, ext=False))
        o.append(label_box(xr_ - 3.4, (Y(-STITCH_OFF) + Y(-14)) / 2 + 0.6, 0, "10", 1.6))
        if tag == "A":
            uv = 11.0 * Lu / 42.0
            up = 29.0 * Lu / 42.0
            xv, xp = px + uv * kk, px + up * kk
            o.append(dim((xv, Y(-STITCH_OFF)), (xv, Y(0)), 0, "", 1.6, ext=False))
            o.append(label_box(xv + 5.0, Y(-2.0) + 0.6, 0, "4 min", 1.6))
            o.append(dim((xp, Y(-STITCH_OFF)), (xp, Y(JAG_A)), 0, "", 1.6, ext=False))
            o.append(label_box(xp + 5.0, Y(-0.6) + 0.6, 0, "7 max", 1.6))
        else:
            # deepest tooth in view and the valleys around it
            vals = [kk_[0] - 3.0 for i, kk_ in enumerate(kB) if i % 4 == 0]
            cands = []
            for i, kk_ in enumerate(kB):
                if i % 4 != 2:
                    continue
                up_ = kk_[0] - 3.0
                lo = [v for v in vals if v < up_]
                hi = [v for v in vals if v > up_]
                if lo and hi and lo[-1] > 4.0 and hi[0] < Lu - 6.0:
                    cands.append((kk_[1], up_, lo[-1], hi[0]))
            dep, up, v0, v1 = max(cands)
            xp = px + up * kk
            o.append(dim((xp, Y(0)), (xp, Y(dep)), 0, "", 1.6, ext=False))
            o.append(label_box(xp + 4.6, Y(dep * 0.55) + 0.6, 0, "3-8", 1.6))
            xv = px + v0 * kk
            o.append(dim((xv, Y(-STITCH_OFF)), (xv, Y(0)), 0, "", 1.6, ext=False))
            o.append(label_box(xv - 3.0, Y(-2.0) + 0.6, 0, "4", 1.6))
            yd = Y(bot_u) - 5.5
            o.append(dim((xv, yd), (px + v1 * kk, yd), 0, "", 1.5, ext=False))
            o.append(line(xv, Y(0), xv, yd + 1.0, WHITE, 0.12, dash="0.4 0.4"))
            o.append(line(px + v1 * kk, Y(0), px + v1 * kk, yd + 1.0, WHITE, 0.12, dash="0.4 0.4"))
            o.append(label_box((xv + px + v1 * kk) / 2, yd - 0.8, 0, "5-15", 1.5))
    ly = py0 + (bot_u - top_u) * kk + 2.0
    s_, h = bi(rx, ly, "C = B + hand-brushed or sanded raw edge. Make A, B and C on the technique swatch, "
               "photograph all three after 3 washes, then choose. In B the stitch stays smooth and at least "
               "3 mm from the deepest valley (drawn at 4 mm). All dimensions in mm.",
               "C = B + 手工磨毛边。工艺小样上A、B、C三种都做，洗3次后拍照再定。B方案车线平顺，距最深齿谷≥3mm"
               "（图示4mm）。单位mm。", 124, se=1.85, sz=1.64)
    o.append(s_)
    ly += h + 1.6
    legend = [
        ("cut", "CUT_JAG: cut the CREAM layer only; the cream inside is removed.",
         "剪口线：只剪米白面布，线内面布剪掉。"),
        ("stitch", "STITCH: through both layers, 4 mm outside the base line (solid line on the 1:1 template).",
         "车线：穿过两层，距剪口基准线4mm（1:1模板上为实线）。"),
        ("patch", "PATCH: cut the under-patch on this line = stitch + 10 mm. No trimming after sewing.",
         "底布裁剪线：车线外10mm，车后不再修剪。"),
        ("base", "BASE line (DXF layer BASE; fine dotted on the 1:1 template): STITCH offset 4 mm inward, inner "
                 "corners r ≥ 7 mm. A: cut freehand 0-3 mm inside it. B: the valleys of the jag sit on it.",
         "剪口基准线BASE（DXF图层BASE，1:1模板上为细点线）：车线向内4mm，内角半径≥7mm。A方案：在此线内0-3mm徒手剪；"
         "B方案：锯齿谷底在此线上。"),
    ]
    for kind, en, zh in legend:
        x0 = rx + 1
        yy = ly + 1.3
        if kind == "cut":
            o.append(poly([(x0, yy), (x0 + 2, yy + 0.9), (x0 + 3.5, yy - 0.2), (x0 + 5.5, yy + 0.8), (x0 + 8, yy)],
                          stroke=INK, sw=0.3, closed=False))
        elif kind == "stitch":
            o.append(line(x0, yy, x0 + 8, yy, INK, 0.35, dash="1.1 0.7"))
        elif kind == "patch":
            o.append(line(x0, yy, x0 + 8, yy, GREY, 0.3, dash="2.2 1.0"))
        else:
            o.append(line(x0, yy, x0 + 8, yy, MID, 0.15, dash="0.3 0.5"))
        s_, h = bi(x0 + 10, ly, en, zh, 113, se=1.85, sz=1.64, gap=0.1)
        o.append(s_)
        ly += h + 0.7

    # key values table
    ty = ly + 0.8
    rows = [
        [C("X size (window)", "X尺寸（开口外框）"),
         C("Proto A: 200 x 210 mm, all sizes the same. Proto B: approx. 150 mm (150 x 157.5), all sizes the same.",
           "200 x 210 mm，全码相同；另一方案：X约150mm（全码相同），用于对比打样。", tbd=True)],
        [C("Arm / tip", "臂宽 / 尖端"),
         C(f"Proto A (200 mm): arm 25 mm at BASE (range 22-28); after the teeth at least {BROWN_MIN['200']:g} mm of "
           f"brown shows; tapering to 10-12 mm round tips (drawn 11). Proto B (150 mm): arm 19 mm, brown ≥ "
           f"{BROWN_MIN['150']:g} mm, tips 10 mm. Never narrower than the tip. Approve the tip after 3 washes.",
           f"A件：BASE处臂宽25mm（22-28），锯齿后可见咖啡色≥{BROWN_MIN['200']:g}mm，尖端10-12mm圆头（图示11mm）；"
           f"B件：臂宽19mm，咖啡色≥{BROWN_MIN['150']:g}mm，尖端10mm。任何位置不窄于尖端。洗3次后确认。", tbd=True)],
        [C("Teeth (edge B)", "锯齿（B边）"),
         C(f"3-8 mm deep, less where the arm narrows; 5-15 mm apart. Opposite sides staggered: together ≤ 40% of the "
           f"local arm width. None on corner arcs or in the last 15-20 mm before each tip cap "
           f"({TIP_FREE['200']:g} / {TIP_FREE['150']:g} mm).",
           f"齿深3-8mm，臂变窄处更浅；齿距5-15mm。两侧锯齿错开：同一截面合计≤该处臂宽40%。内角圆弧及尖端前15-20mm"
           f"（{TIP_FREE['200']:g}/{TIP_FREE['150']:g}mm）不做锯齿。")],
        [C("Inner corners", "内角"),
         C("STITCH r ≥ 3 mm; CUT line r ≥ 7 mm; PATCH r ≥ 3 mm.", "车线半径≥3mm；剪口≥7mm；底布≥3mm。")],
        [C("Cut to stitch", "剪口至车线"),
         C("Nominal 4-7 mm (B: at the valleys). Accept ≥ 3 mm. Reject < 3 mm or any cut stitch.",
           "标准4-7mm（B方案按齿谷）；≥3mm可接受；<3mm或剪断车线为次品。")],
        [C("Placement", "位置"),
         C("X centre on CF, 26 / 27 / 28 / 29 cm below HPS (S / M / L / XL). Same centre for Proto B.",
           "X中心在前中，距高肩点26/27/28/29cm；B件中心相同。", tbd=True)],
        [C("Edge style", "边缘效果"),
         C("Swatch: A / B / C side by side; the bulk edge is chosen after 3 washes. Both protos: edge B, cut on "
           "CUT_JAG. Stitch smooth on STITCH (Proto A) or following the jag at 4 mm (Proto B, layer STITCH_FOLLOW).",
           "小样：A/B/C并排，洗3次后定大货边。两件头办均用B边，按CUT_JAG剪。车线：A件沿STITCH平顺；B件沿锯齿4mm"
           "（STITCH_FOLLOW图层）。", tbd=True)],
        [C("Template", "模板"),
         C("Factory digitises the STITCH layer (Proto B: STITCH_FOLLOW; digitising fee quoted separately) and makes "
           "the cut guide, placement template and stitch-marking stencil (page 7, TOOLING). Face view: never mirror "
           "or rotate; CF notch, arrow and FACE UP / NECK on all tooling.",
           "工厂按STITCH图层制版（B件用STITCH_FOLLOW；制版费另报），并制作剪口模板、定位板及车线画线板（第7页）。"
           "正面视图，不可翻转或旋转；所有工装均开前中缺口并刻箭头及FACE UP / NECK。")],
    ]
    s_, h = table(rx, ty, [27, 97], rows, header=[C("Item", "项目"), C("Proposed for swatch / proto", "打样建议值")],
                  se=1.8, sz=1.6, pad=0.7)
    o.append(s_)
    if ty + h > CONTENT_BOTTOM:
        WARN.append(f"page3 right overflow {ty + h:.1f}")
    return page_svg(3, "X DETAIL: GEOMETRY AND TEMPLATE", "X细节：尺寸、剪口及模板", "".join(o))


# ================================================================== PAGE 4: X CONSTRUCTION
HOODIE_EDGE = os.path.join(os.path.dirname(HERE), "z1.png")


def embed_png(path, x, y, w, h):
    im = Image.open(path).convert("RGB")
    # centre-crop to the box aspect
    ar = w / h
    iw, ih = im.size
    if iw / ih > ar:
        nw = int(ih * ar)
        im = im.crop(((iw - nw) // 2, 0, (iw - nw) // 2 + nw, ih))
    else:
        nh = int(iw / ar)
        im = im.crop((0, (ih - nh) // 2, iw, (ih - nh) // 2 + nh))
    im = im.resize((int(w * 12), int(h * 12)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    b = base64.b64encode(buf.getvalue()).decode()
    return (f'<image x="{f2(x)}" y="{f2(y)}" width="{f2(w)}" height="{f2(h)}" preserveAspectRatio="none" '
            f'xlink:href="data:image/jpeg;base64,{b}"/>')


def page4():
    o = []
    # ---------- cross-section
    s_, hh = heading(10, 22, "CROSS-SECTION THROUGH ONE ARM", "X臂横截面（示意，厚度放大）", 2.7, width=150)
    o.append(s_)
    kx = 1.7
    xc = 60.0
    yc = 41.0          # top of cream layer
    th = 3.0
    gap = 0.6
    half_w = 12.5 * kx
    st_d = 5.0 * kx
    pa_d = PATCH_OFF * kx
    xl, xr_ = 10.5, 112.0
    yb_top = yc + th + gap
    ybot = yb_top + th
    o.append(rect(xl, yc, (xc - half_w) - xl, th, CREAM, INK, 0.25))
    o.append(rect(xc + half_w, yc, xr_ - (xc + half_w), th, CREAM, INK, 0.25))
    for sg in (-1, 1):
        ex = xc + sg * half_w
        o.append(poly([(ex, yc), (ex - sg * 0.25, yc - 1.5), (ex - sg * 1.8, yc - 2.0)], stroke=GREY, sw=0.22,
                      closed=False))
    bl, br = xc - half_w - st_d - pa_d, xc + half_w + st_d + pa_d
    o.append(rect(bl, yb_top, br - bl, th, BROWN, INK, 0.25))
    for sg in (-1, 1):
        sx = xc + sg * (half_w + st_d)
        o.append(line(sx, yc - 1.4, sx, ybot + 1.4, INK, 0.5, dash="1.0 0.5"))
        o.append(circle(sx, yc - 1.7, 0.5, INK, None))
        o.append(circle(sx, ybot + 1.7, 0.5, INK, None))
    for ex in (xl, xr_):
        o.append(poly([(ex, yc - 1.2), (ex - 0.9, yc + 0.8), (ex + 0.9, yc + 2.0), (ex, yc + th + 1.2)],
                      stroke=GREY, sw=0.22, closed=False))
    o.append(text(xl, yc - 12.3, "OUTSIDE (face)", 2.0, bold=True))
    o.append(text(xl + tw("OUTSIDE (face)", 2.0, bold=True) + 1.2, yc - 12.3, "外面（正面）", 1.8, zh=True, fill=ZHC))
    o.append(text(xl, ybot + 14.5, "INSIDE (skin side)", 2.0, bold=True))
    o.append(text(xl + tw("INSIDE (skin side)", 2.0, bold=True) + 1.2, ybot + 14.5, "里面（贴身面）", 1.8, zh=True,
                  fill=ZHC))
    o.append(dim((xc - half_w, yc), (xc + half_w, yc), -5.0, "25 mm at BASE (valleys)", 1.8))
    o.append(dim((xc + half_w, ybot), (xc + half_w + st_d, ybot), 5.0, "4-7", 1.7, tside=-1))
    o.append(dim((xc + half_w + st_d, ybot), (br, ybot), 5.0, "10", 1.7, tside=-1))
    notes = [
        (1, (xl + 8, yc + 1.5), (xl + 6, yc - 6.0)),
        (3, (xc - half_w - st_d, yc - 1.7), (xc - half_w - st_d - 2.5, yc - 8.0)),
        (4, (xc + half_w - 0.4, yc - 1.2), (xc + half_w + 6, yc - 7.5)),
        (2, (bl + 5, yb_top + th / 2), (bl + 5, ybot + 8.5)),
        (5, (xc - 8, yb_top + 0.8), (xc - 8, ybot + 8.5)),
        (6, (br - 0.4, yb_top + th / 2), (br + 3.5, ybot + 6.0)),
    ]
    for n, a, b in notes:
        o.append(leader(b, a))
        o.append(num(b[0], b[1], n, 1.5))
    # inside view 1:8 (inset)
    k = 1 / 8.0
    ox, oy = 138.5, 47.0
    patch = tx(patch_outline(G200), ox, oy, k)
    stitch = tx(stitch_outline(G200), ox, oy, k)
    bb = bbox(patch)
    o.append(text(118.0, 29.6, "INSIDE VIEW 1:8", 1.9, bold=True))
    o.append(text(118.0 + tw("INSIDE VIEW 1:8", 1.9, bold=True) + 1.0, 29.6, "反面 1:8", 1.7, zh=True, fill=ZHC))
    o.append(rect(bb[0] - 2, bb[1] - 1.5, bb[2] - bb[0] + 4, bb[3] - bb[1] + 3, CREAM_D, None))
    o.append(poly(patch, fill=BROWN_BACK, stroke=INK, sw=0.18))
    o.append(poly(stitch, stroke=CREAM, sw=0.22, dash="0.7 0.45"))
    ny = 67.5
    leg = [
        (1, "Cream body jersey (top layer), front panel.", "米白大身汗布（面层），前片。"),
        (2, "Brown under-patch on the wrong side; brown FACE side toward the outside.", "咖啡色底布放前片反面，正面朝外。"),
        (3, "Stitch through both layers on the STITCH line (ISO 301 or embroidery run).",
         "沿STITCH线穿两层车线（301平车或电脑绣花跑针）。"),
        (4, "Raw cut edge of cream, 4-7 mm from stitch. It rolls into a soft lip after washing; it does not fuzz "
            "like fleece.", "米白剪口毛边，距车线4-7mm；洗后卷成软边，不会像卫衣布起毛。"),
        (5, "Window: brown face visible from outside.", "开口：从外面看见咖啡色正面。"),
        (6, "Under-patch cut at stitch + 10 mm (PATCH layer), raw, not overlocked, no trimming.",
         "底布按PATCH图层裁至车线外10mm，毛边不拷边，不修剪。"),
        (0, "Inside view: back of the under-patch with the bobbin line. Thread tails 3-5 mm; no knots against "
            "the skin.", "反面：底布反面可见底线；线头剪至3-5mm，内侧不得有线结。"),
    ]
    for i, (n, en, zh) in enumerate(leg):
        col = i % 2
        x = 10 + col * 76
        yy = ny + (i // 2) * 8.4
        if n:
            o.append(num(x + 1.5, yy + 1.7, n, 1.4))
        else:
            o.append(circle(x + 1.5, yy + 1.4, 0.55, INK, None))
        s_, h = bi(x + 4.2, yy, en, zh, 71, se=1.8, sz=1.6, gap=0.1)
        o.append(s_)
        if h > 8.2:
            WARN.append(f"page4 legend item {n} too tall {h:.1f}")

    # ---------- stitch table
    ty = ny + 4 * 8.4 + 0.6
    s_, hh = heading(10, ty, "STITCH SPECIFICATION", "针步规格", 2.6, width=150)
    o.append(s_)
    rows = [
        [C("X outline, flatbed", "X轮廓（平车）"),
         C("ISO 301 lockstitch on the STITCH line (Proto B: STITCH_FOLLOW), marked on the face with the "
           "stitch-marking stencil + air-erasable pen",
           "单针平车301，沿STITCH线（B件：STITCH_FOLLOW）；用车线画线板及气消笔在正面画线"),
         C("10-12 SPI (2.1-2.5 mm)", "每英寸10-12针"),
         C("402 spun poly, needle + bobbin. A: cream, B: brown-black", "402涤纶线，A件米白、B件深棕黑", tbd=True),
         C("Ballpoint Nm 75-80", "圆头针75-80号")],
        [C("X outline, embroidery", "X轮廓（电脑绣花）"),
         C("Running stitch, panel hooped; factory digitises from the DXF STITCH layer (fee quoted)",
           "跑针，上绷；工厂按DXF制版并报制版费"),
         C("2.5 mm run", "跑针2.5mm"), C("120D/2 polyester embroidery thread (40 wt)", "120D/2涤纶绣花线"),
         C("DBxK5 SES 75/11 ballpoint", "DBxK5圆头75/11针")],
        ("SPAN", C("Start / stop on a straight section mid-arm, overlap 3 stitches (embroidery: tie-in / tie-off); "
                   "no back-tack pile at corners. Inner corners: one 10 mm repeat pass only; bartack only if the "
                   "proto shows splitting.",
                   "起止针在臂中直线段，重叠3针，不在内角回针；内角只重复车10mm一次，头办有裂开才加打枣。",
                   fill=WHITE)),
        ("SPAN", C("If stitch cracks: (1) balance / reduce needle tension, keep 10-12 SPI (do not lengthen the stitch); (2) textured / "
                   "wooly poly bobbin; (3) narrow 304 zigzag, 1.5 mm throw, 12 SPI. Triple / bean stitch only for "
                   "coverage, not for stretch.",
                   "断线时：先调松面线张力，针距保持每英寸10-12针（不可加长针距）；底线改弹力线；仍断则改窄人字车1.5mm。"
                   "三重跑针只增加覆盖，不增加弹性。", fill=WHITE)),
        [C("All other seams", "其他缝位"), C("As base " + BASE, "同原版"), C("as base", "同原版"), C("as base", "同原版"),
         C("as base", "同原版")],
    ]
    s_, h = table(10, ty + hh + 0.4, [23, 51, 22, 30, 24], rows,
                  header=[C("Operation", "工序"), C("Stitch", "线迹"), C("SPI", "针距"), C("Thread", "用线"),
                          C("Needle", "机针")], se=1.85, sz=1.64, pad=0.75)
    o.append(s_)
    ry = ty + hh + 0.4 + h + 2.0
    s_, h = tbd_box(10, ry, 150,
                    "Method to confirm on swatch / proto: stitch-then-cut (drawn) or cut-then-stitch; embroidery "
                    "machine or flatbed; X done in-house or by a Humen embroidery subcontractor.",
                    "小样或头办确认做法：先车后剪（图示）或先剪后车；电脑绣花或平车；厂内或外发虎门绣花厂。",
                    se=1.8, sz=1.6)
    o.append(s_)
    ry += h + 2.8
    o.append(check_bar(10.0, ry, "inside view 1:8"))
    if ry + 2 > CONTENT_BOTTOM:
        WARN.append(f"page4 left overflow {ry + 2:.1f}")

    # ---------- look reference (right, top)
    sx = 168
    s_, hh = heading(sx, 22, "LOOK REFERENCE", "效果参考", 2.6, width=119)
    o.append(s_)
    iy = 22 + hh + 0.8
    iw, ih = 27.6, 27.0
    slots = [("Mock-up close-up 1", "after 3 washes"), ("Mock-up close-up 2", "inner corner"),
             ("Mock-up close-up 3", "tip")]
    for i, (a, b_) in enumerate(slots):
        x = sx + i * (iw + 2.2)
        o.append(rect(x, iy, iw, ih, "#F4F4F4", MID, 0.25, dash="1.0 0.7"))
        bdg, bw, bh = tbd_badge(x + iw / 2 - 3.8, iy + 4.5, 1.6)
        o.append(bdg)
        o.append(text(x + iw / 2, iy + 12.0, a, 1.7, bold=True, anchor="middle"))
        o.append(text(x + iw / 2, iy + 15.0, b_, 1.65, anchor="middle", fill=GREY))
        o.append(text(x + iw / 2, iy + 19.5, "founder adds photo", 1.6, anchor="middle", fill=GREY))
        o.append(text(x + iw / 2, iy + 22.3, "客户补充照片", 1.5, zh=True, anchor="middle", fill=ZHC))
    x = sx + 3 * (iw + 2.2)
    o.append(embed_png(HOODIE_EDGE, x, iy, iw, ih))
    o.append(rect(x, iy, iw, ih, "none", INK, 0.25))
    cy_ = iy + ih + 1.0
    s_, h1 = bi(sx, cy_, "Target edge after wash: founder's home mock-up (cream tee + brown tee scrap, stitched, cut, "
                "washed 3 times).", "洗后目标效果：客户手工样（米白T恤+咖啡色T恤布，车线剪开后洗3次）。",
                3 * (iw + 2.2) - 2.2, se=1.75, sz=1.58, gap=0.1)
    o.append(s_)
    s_, h2 = bi(x, cy_, "Other garment (fleece), edge scale only: stitch approx. 3-5 mm inside the raw edge. Not the "
                "design.", "其他款卫衣，仅参考毛边与车线距离，非本款图案。", iw, se=1.55, sz=1.45, gap=0.1)
    o.append(s_)
    py_ = cy_ + max(h1, h2) + 1.2
    s_, h = bi(sx, py_, "Physical items shipped with v1: (1) tape roll or 1 m swatch; (2) the approved DROP 001 piece "
               "as counter sample; (3) Pantone TCX brown swatch; (4) the mock-up.",
               "v1随附实物：（1）织带整卷或1米样；（2）DROP 001确认样作封样；（3）潘通TCX咖啡色卡；（4）手工样。",
               117.4, se=1.85, sz=1.64, gap=0.12)
    o.append(rect(sx - 0.8, py_ - 0.8, 119.8, h + 1.6, "none", INK, 0.25))
    o.append(s_)

    # ---------- steps
    st_y = py_ + h + 3.0
    s_, hh = heading(sx, st_y, "SEQUENCE ON THE FLAT FRONT PANEL", "前片裁片工序", 2.6, width=119)
    o.append(s_)
    steps = [
        ("Pre-test: shrinkage (length and width) of cream and brown; colourfastness of brown (page 8).",
         "预测：米白及咖啡色布缩水率（长宽）；咖啡色布色牢度（第8页）。"),
        ("Cut front panel as base. Mark CF and the X centre with the placement template (air-erasable pen only). "
         "Flatbed route: also mark the stitch path on the face with the stitch-marking stencil (STITCH layer; "
         "Proto B: STITCH_FOLLOW).",
         "按原版裁前片；用定位板标前中及X中心（只用气消笔）。平车做法：再用车线画线板在正面画车线（STITCH图层；"
         "B件：STITCH_FOLLOW）。"),
        ("Cut the under-patch X-shaped on the PATCH layer (stitch + 10 mm), same grain as body. Place it on the "
         "WRONG side of the front with the placement template, brown face toward the panel. Backing: (a) none, two "
         "layers hooped + light spray adhesive (test first), or (b) 1.5 oz fusible no-show mesh left in. Compare a "
         "and b on the swatch; no tear-away or wash-away unless the factory shows it on the swatch.",
         "按PATCH图层裁X形底布（车线外10mm），布纹同大身；用定位板放前片反面，正面贴前片。衬：（a）不加衬，两层上绷"
         "+少量喷胶（先测试）；（b）1.5oz热熔网衬保留。小样对比a与b；除非工厂小样证明可行，不用撕纸或水溶纸。"),
        ("Stitch the STITCH line (Proto B: STITCH_FOLLOW) through both layers (embroidery machine, panel hooped, "
         "preferred). Start / stop "
         "mid-arm, overlap 3 stitches, no back-tacks at corners; inner corners one 10 mm repeat pass. Arms run near "
         "45 degrees: do not stretch the bias edges. Embroidery program in face view, arrow to the neck, the same "
         "orientation as the template (never mirrored).",
         "沿STITCH线（B件：STITCH_FOLLOW）穿两层车线（首选电脑绣花上绷）。起止针在臂中，重叠3针，内角不回针，只重复车10mm一次。"
         "X臂接近45°斜向，不可拉扯。绣花程序按正面视图，箭头指领口，与模板方向一致（不可镜像）。"),
        ("Both protos: edge B. Lay the cut guide (acrylic or cardboard, CUT_JAG layer) FACE UP, arrow to the neck, "
         "notch on CF, on the stitch line; never flipped or rotated. Proto B: before tracing, check that each tooth "
         "on the guide sits where the stitch steps in. Trace CUT_JAG onto the cream with an air-erasable pen. Cut "
         "the CREAM only, on the traced line, with duck-bill appliqué scissors. Any nick in the brown = reject. No "
         "laser or die cut unless approved. If tracing is not practical, cut freehand to the approved swatch: A = "
         "inside the 4-7 mm band from the stitch (0-3 mm inside BASE), 3-6 irregular teeth per 5 cm; B = teeth "
         f"3-8 mm deep (less where the arm narrows), 5-15 mm apart, staggered side to side, brown ≥ "
         f"{BROWN_MIN['200']:g} mm (Proto B ≥ {BROWN_MIN['150']:g} mm), valleys never closer than 3 mm to the stitch.",
         "两件头办均用B边。剪口模板（亚克力或硬纸板，按CUT_JAG图层）正面朝上、箭头指领口、缺口对前中，对准车线放好，"
         "不可翻转或旋转。B件：描线前核对模板上每个齿正对车线内折处。用气消笔画剪口线；用鸭嘴剪只剪米白面布。"
         "底布有剪口即次品。未经批准不可激光或刀模切割。如画线不可行，按确认小样徒手剪：A方案在距车线4-7mm范围内"
         "（BASE线内0-3mm），每5cm不规则齿3-6个；B方案齿深3-8mm（臂变窄处更浅），齿距5-15mm，两侧错开，可见咖啡色"
         f"≥{BROWN_MIN['200']:g}mm（B件≥{BROWN_MIN['150']:g}mm），齿谷距车线不小于3mm。"),
        ("No under-patch trimming (cut to size in step 3); trim to stitch + 7 mm only if the proto shows a flap "
         "flipping. Raw edges: no overlock, binding, satin, zigzag, glue, heat-seal or folding. Variant C only: "
         "brush the raw edge by hand.",
         "底布已按尺寸裁好，车后不修剪；仅当头办底布边外翻时修至车线外7mm。毛边外露：不锁边、不包边、不要缎面或"
         "人字包边、不上胶、不热封、不折边。仅C方案：手工磨毛边。"),
        ("Then assemble as base: shoulders, tape (page 5), neck rib, sleeves, side seams, hems, labels. Garment "
         "wash open (protos unwashed). No garment dyeing.",
         "之后按原版组合：合肩、上织带（第5页）、上领、上袖、埋夹、冚脚、上唛。成衣水洗待定（头办不洗），不可成衣染色。"),
    ]
    yy = st_y + hh + 0.6
    for i, (en, zh) in enumerate(steps):
        o.append(num(sx + 1.6, yy + 1.7, i + 1, 1.5))
        s_, h = bi(sx + 4.6, yy, en, zh, 114.4, se=1.9, sz=1.68, gap=0.15)
        o.append(s_)
        yy += h + 1.3
    if yy > CONTENT_BOTTOM:
        WARN.append(f"page4 steps overflow y={yy:.1f}")
    return page_svg(4, "X DETAIL: CONSTRUCTION", "X细节：工艺及工序", "".join(o))


# ================================================================== PAGE 5: SHOULDER TAPE
TAPE_LINE_C = 1.9      # proposal: centre of the thin lengthwise line, mm from the tape edge
TAPE_LINE_W = 0.4


def draw_tape(x, y, length_mm, k, width_mm=20.0, q=7.5, border=2.5, phase=0, hatch=True, lines=True,
              line_c=TAPE_LINE_C, line_w=TAPE_LINE_W):
    out = []
    out.append(rect(x, y, length_mm * k, width_mm * k, CREAM, None))
    n = int(math.ceil(length_mm / q))
    for row in range(2):
        for i in range(n):
            u0 = i * q
            u1 = min(length_mm, (i + 1) * q)
            if u0 >= length_mm:
                continue
            col = CREAM if (i + row + phase) % 2 == 0 else BROWN_BK
            x0 = x + u0 * k
            y0 = y + (border + row * q) * k
            w = (u1 - u0) * k
            h = q * k
            out.append(rect(x0, y0, w, h, col, None))
            if hatch:
                hc = "#D6CCB4" if col == CREAM else "#4A3C34"
                step = 0.9 * k
                j = -h
                while j < w:
                    p0x, p0y, p1x, p1y = x0 + j, y0 + h, x0 + j + h, y0
                    if p0x < x0:
                        p0y -= (x0 - p0x)
                        p0x = x0
                    if p1x > x0 + w:
                        p1y += (p1x - (x0 + w))
                        p1x = x0 + w
                    if p0x < p1x:
                        out.append(line(p0x, p0y, p1x, p1y, hc, 0.12 * k / 2.8))
                    j += step
    if lines:
        for yy in (line_c, width_mm - line_c):
            out.append(rect(x, y + (yy - line_w / 2) * k, length_mm * k, line_w * k, BROWN_BK, None))
    out.append(rect(x, y, length_mm * k, width_mm * k, "none", INK, 0.25))
    return "".join(out)


def edge_detail(x, y, k, L, border, line_c, stitch_c, thread, label):
    """Plan view of one tape edge at scale k: jersey above, tape edge, border, thin line, squares; edge-stitch."""
    o = []
    depth = 5.0
    above = 2.0
    o.append(rect(x, y, L * k, above * k, CREAM_D, None))
    ty = y + above * k
    o.append(rect(x, ty, L * k, depth * k, CREAM, None))
    q = 7.5
    i = 0
    u = -2.5
    while u < L:
        u0, u1 = max(0.0, u), min(L, u + q)
        if u1 > u0:
            col = CREAM if i % 2 == 0 else BROWN_BK
            o.append(rect(x + u0 * k, ty + border * k, (u1 - u0) * k, (depth - border) * k, col, None))
        u += q
        i += 1
    o.append(rect(x, ty + (line_c - TAPE_LINE_W / 2) * k, L * k, TAPE_LINE_W * k, BROWN_BK, None))
    o.append(line(x, ty, x + L * k, ty, INK, 0.3))
    # stitch: short strokes (needle holes at 2.3 mm)
    sy = ty + stitch_c * k
    u = 0.6
    scol = CREAM if thread == "cream" else BROWN_BK
    while u + 1.6 < L:
        o.append(line(x + u * k, sy, x + (u + 1.6) * k, sy, INK, 0.95, cap="round"))
        o.append(line(x + u * k, sy, x + (u + 1.6) * k, sy, scol, 0.6, cap="round"))
        u += 2.3
    o.append(rect(x, y, L * k, (above + depth) * k, "none", GREY, 0.2))
    o.append(text(x + 1.0, y + above * k - 1.0, "jersey", 1.5, fill=GREY))
    # dims on the right: edge to stitch, edge to border end
    xr = x + L * k
    o.append(dim((xr, ty), (xr, sy), -2.2, "", 1.5, ext=True))
    o.append(text(xr + 3.2, ty - 1.3, label, 1.5))
    o.append(dim((xr, ty), (xr, ty + border * k), -8.5, "", 1.5, ext=True))
    o.append(text(xr + 9.7, ty + border * k / 2 + 0.55, f"border {border:g}", 1.5))
    return "".join(o), (above + depth) * k


def page5():
    o = []
    s_, hh = heading(10, 22, "TAPE ARTWORK, SCALE 2.5:1", "织带图稿 2.5:1", 2.7, width=140)
    o.append(s_)
    k = 2.5
    tx0, ty0 = 22.0, 34.0
    L = 37.5
    o.append(draw_tape(tx0, ty0, L, k, phase=0))
    o.append(dim((tx0, ty0), (tx0 + 7.5 * k, ty0), -3.5, "7.5", 1.8))
    o.append(dim((tx0 + 7.5 * k, ty0), (tx0 + 22.5 * k, ty0), -3.5, "15.0 repeat", 1.8))
    o.append(dim((tx0, ty0 + 20 * k), (tx0, ty0), -5.0, "20 mm width", 1.8, tbd=True))
    xr = tx0 + L * k
    o.append(dim((xr, ty0), (xr, ty0 + 2.5 * k), -3.5, "2.5", 1.6))
    o.append(dim((xr, ty0 + 2.5 * k), (xr, ty0 + 10.0 * k), -3.5, "7.5", 1.7))
    o.append(dim((xr, ty0 + 10 * k), (xr, ty0 + 17.5 * k), -3.5, "7.5", 1.7))
    o.append(dim((xr, ty0 + 17.5 * k), (xr, ty0 + 20 * k), -3.5, "2.5", 1.6))
    o.append(check_bar(133.0, ty0, "2.5:1", vertical=True, size=1.55))
    ny = ty0 + 20 * k + 2.2
    s_, h = bi(10, ny, "Drawn as a 20 mm proposal: 2 rows of 7.5 mm squares; each 2.5 mm border carries a thin "
               f"lengthwise line about {TAPE_LINE_C:g} mm from the edge. The founder's roll is the approved standard for "
               "weave, colours, border width and line position: measure it before choosing the edge-stitch below.",
               "按20mm建议绘制：两排7.5mm方格，两边2.5mm边内各一条细线（距边约1.9mm）。织法、颜色、边宽及细线位置以"
               "客供实物为准；先量织带，再按下图选边线位置。", 120, se=1.8, sz=1.6)
    o.append(s_)

    # ---------- edge-stitch position 6:1
    ey = ny + h + 2.4
    s_, hh = heading(10, ey, "EDGE-STITCH POSITION, SCALE 5:1", "织带边线位置 5:1", 2.4, width=140)
    o.append(s_)
    ey += hh + 0.8
    ke = 5.0
    sa, ha = edge_detail(10.0, ey, ke, 10.0, 2.5, TAPE_LINE_C, 1.0, "cream", "stitch 1.0 from edge")
    o.append(sa)
    sb, hb = edge_detail(80.0, ey, ke, 10.0, 1.8, 0.9, 0.9, "brown", "stitch ON the line")
    o.append(sb)
    cy_ = ey + max(ha, hb) + 1.2
    s_, h1 = bi(10.0, cy_, "(a) Border 2.5 mm or more: edge-stitch 1 mm from the edge, in the plain cream border, "
                "never on the thin line; thread cream.", "（a）边宽≥2.5mm：压0.1cm边线，车在米白边内，不可压到细线；"
                "线色米白。", 68, se=1.65, sz=1.5, gap=0.1)
    o.append(s_)
    s_, h2 = bi(80.0, cy_, "(b) Border under 2.5 mm: stitch ON the thin line; thread brown-black like the line.",
                "（b）边宽<2.5mm：车在细线上，线色同细线（深棕黑）。", 66, se=1.65, sz=1.5, gap=0.1)
    o.append(s_)

    # ---------- shoulder top-down diagram 1:2
    dy = cy_ + max(h1, h2) + 2.2
    s_, hh = heading(10, dy, "ON THE SHOULDER (TOP VIEW), SCALE 1:2", "肩部位置（俯视）1:2", 2.4, width=140)
    o.append(s_)
    ks = 0.5
    seam_len = (20 - 6.75) / 2 * 25.4     # mm, M
    x0 = 34.0
    x1 = x0 + seam_len * ks
    yseam = dy + hh + 13.0
    o.append(rect(x0 - 10, yseam - 12, (x1 - x0) + 26, 24, CREAM, None))
    o.append(rect(x0 - 10, yseam - 12, 10, 24, CREAM_D, INK, 0.2))
    o.append(text(x0 - 9, yseam + 0.8, "neck rib", 1.6, fill=GREY))
    o.append(text(x0 + 4.5, yseam - 9.6, "BACK", 1.7, bold=True, fill=GREY))
    o.append(text(x0 + 7.2, yseam + 11.0, "FRONT", 1.7, bold=True, fill=GREY))
    o.append(line(x0, yseam - 12, x0, yseam + 12, INK, 0.3))
    o.append(line(x1, yseam - 12, x1, yseam + 12, INK, 0.3))
    o.append(text(x1 + 2, yseam + 0.8, "sleeve", 1.6, fill=GREY))
    tw_ = 20 * ks
    o.append(draw_tape(x0, yseam - tw_ / 2, seam_len, ks, hatch=False, phase=1))
    o.append(line(x0, yseam, x1, yseam, WHITE, 0.25, dash="0.6 0.5"))
    for yy in (yseam - tw_ / 2 + 0.5, yseam + tw_ / 2 - 0.5):
        o.append(line(x0, yy, x1, yy, "#9A9A9A", 0.22, dash="0.8 0.45"))
    # back neck tape inside (hidden line, no fill): along the neck seam, 2 cm past the shoulder seam onto the front
    o.append(rect(x0, yseam - 12, 3.5, 12 + 10.0, "none", INK, 0.3, dash="0.9 0.5"))
    o.append(dim((x0 + 3.5, yseam), (x0 + 3.5, yseam + 10.0), -1.6, "", 1.4, ext=False))
    o.append(text(x0 + 6.6, yseam + 7.3, "2 cm", 1.5, bold=True))
    # below the view: clear of the FRONT label and callout 5
    o.append(dim((x0, yseam + tw_ / 2), (x1, yseam + tw_ / 2), 9.3, "shoulder seam, approx. 16.8 cm (M)", 1.7,
                 tside=-1))
    for n, a, b in [(1, (x0 + 40, yseam), (x0 + 40, yseam - 9.5)),
                    (2, (x0 + 58, yseam - tw_ / 2 + 0.5), (x0 + 58, yseam - 9.5)),
                    (3, (x0 + 1.8, yseam - 3), (x0 + 14, yseam - 9.5)),
                    (4, (x1 - 0.3, yseam - 3), (x1 - 6, yseam - 9.5)),
                    (5, (x0 + 7.5 * ks / 2, yseam + 7.5 * ks / 2), (x0 - 5.0, yseam + 7.6))]:
        o.append(leader(b, a))
        o.append(num(b[0], b[1], n, 1.4))

    # ---------- section (shoulder seam)
    sy = yseam + 21.0
    o.append(text(10, sy, "SECTION", 1.9, bold=True))
    o.append(text(10, sy + 2.8, "肩缝截面", 1.7, zh=True, fill=ZHC))
    cx_ = 82.0
    base_y = sy + 1.0
    o.append(rect(cx_ - 50, base_y, 50, 1.3, CREAM, INK, 0.2))
    o.append(rect(cx_, base_y, 50, 1.3, CREAM, INK, 0.2))
    o.append(rect(cx_ - 7, base_y + 1.5, 7, 1.8, CREAM_D, INK, 0.2))
    o.append(text(cx_ - 49, base_y + 4.6, "back", 1.6, fill=GREY))
    o.append(text(cx_ + 49, base_y + 4.6, "front", 1.6, fill=GREY, anchor="end"))
    tl = cx_ - 10
    for i in range(4):
        o.append(rect(tl + i * 5, base_y - 1.4, 5, 1.2, CREAM if i % 2 else BROWN_BK, None))
    o.append(rect(tl, base_y - 1.4, 20, 1.2, "none", INK, 0.2))
    for xx in (tl + 0.5, tl + 20 - 0.5):
        o.append(line(xx, base_y - 2.2, xx, base_y + 1.9, INK, 0.35, dash="0.6 0.3"))
    o.append(leader((cx_ + 14, base_y - 3.8), (cx_ + 9.5, base_y - 1.0)))
    o.append(text(cx_ + 14.5, base_y - 3.4, "tape centred on seam; edge-stitch per (a) or (b)", 1.6))
    o.append(leader((cx_ - 14, base_y + 5.0), (cx_ - 4, base_y + 2.6)))
    o.append(text(cx_ - 14.5, base_y + 5.5, "514 overlock, allowance to back", 1.6, anchor="end"))
    if sy + 7 > CONTENT_BOTTOM:
        WARN.append(f"page5 left overflow {sy + 7:.1f}")

    # ---------- right column: spec table
    rx = 158
    s_, hh = heading(rx, 22, "TAPE SPECIFICATION", "织带规格", 2.7, width=129)
    o.append(s_)
    rows = [
        [C("Type", "类型"), C("Woven checker tape (ichimatsu), garment ribbon weight. Founder's roll = approved trim "
                              "standard; physical swatch sent.", "棋盘格提花织带（市松格），服装用薄织带；以客供实物为准（寄样）")],
        [C("Width", "宽度"), C("Measure founder's roll. If new: 20 mm.", "量客供织带；如新做建议20mm", tbd=True)],
        [C("Border / line", "边 / 细线"), C("Measure border width and thin-line position on the roll; they decide "
                                           "edge-stitch option (a) or (b).", "量边宽及细线位置，决定边线做法（a）或（b）",
                                           tbd=True)],
        [C("Fibre", "成分"), C("Confirm from roll or supplier (likely polyester).", "待确认（可能为涤纶）", tbd=True)],
        [C("Colours", "颜色"), C("Cream + brown-black; match body cream and X brown by physical swatch.",
                                "米白 + 深棕黑，按实物对色")],
        [C("Shrinkage", "缩水率"), C("1% max, heat-set. Body width shrinkage ≤ 3% (page 7): at 5% vs 1% a 17 cm "
                                    "shoulder differs by about 7 mm and ripples. Washed with the body on Proto B; tape "
                                    "pucker is pass / fail in the wash photos.",
                                    "不超过1%，定型。大身横向缩水≤3%（第7页）：若大身5%、织带1%，17cm肩缝相差约7mm，"
                                    "会起波浪。B件与大身同洗，洗后照片中织带起皱为合格判定项。")],
        [C("Colourfastness", "色牢度"), C("Washing staining grade 4 or better; wet rubbing 3 or better.", "水洗沾色4级以上，湿摩3级以上")],
        [C("Thickness / ends", "厚度 / 端口"), C("0.8 mm max (garment ribbon, not bag webbing). Hot-cut if polyester; "
                                               "ends always hidden inside seams.", "不超过0.8mm（非箱包织带）；涤纶热切，端口藏入缝内")],
        [C("Source", "来源"), C("Customer-supplied, or factory finds the same stock tape in Humen. Add 10-15% spare.",
                               "客供或工厂在虎门找同款现货，另加10-15%", tbd=True)],
    ]
    s_, h = table(rx, 22 + hh + 0.4, [24, 105], rows, se=1.8, sz=1.58, pad=0.6)
    o.append(s_)
    yy = 22 + hh + 0.4 + h + 2.0
    s_, hh = heading(rx, yy, "ATTACHING (numbers = top view)", "上织带做法", 2.3, width=129)
    o.append(s_)
    yy += hh + 0.4
    rules = [
        (1, "Join shoulders ISO 514 4-thread overlock, allowance to back. Tape centred on seam (+/-1.5 mm), outside.",
         "四线包缝合肩，缝份倒向后片；织带居中压肩缝（±1.5mm）。", False),
        (2, "Edge-stitch both edges ISO 301, 10-12 SPI. Measure the roll first: (a) border 2.5 mm or more: 1 mm from "
            "the edge in the plain cream border, never on the thin line, thread cream; (b) border under 2.5 mm: "
            "stitch ON the thin line, thread brown-black.",
         "两边压单针明线，每英寸10-12针。先量织带：（a）边宽≥2.5mm：压0.1cm边线，车在米白边内，不可压到细线，线色"
         "米白；（b）边宽<2.5mm：车在细线上，线色同细线。", False),
        (3, "Back neck tape extends 2 cm past each shoulder seam onto the front neckline, fully covering the checker "
            "tape end. Trim the checker tape end to 5 mm inside the neck seam allowance before attaching the rib. "
            "Tape never runs over the rib.",
         "后领贴两端各过肩缝2cm至前领，完全盖住织带端口；上领前织带端修剪至缝份内5mm。织带不可压在罗纹上。", False),
        (4, "Sleeve end caught in armhole seam.", "袖窿端夹入上袖骨。", False),
        (5, "Phase: at the FINISHED neck seam the first visible front-row square is cream and shows at least 5 mm; "
            "cut to pattern so both shoulders match.",
         "花位：成品领骨处前排第一格为米白，外露≥5mm；对花裁剪，两肩一致。", True),
    ]
    for n, en, zh, tb in rules:
        o.append(num(rx + 1.5, yy + 1.6, n, 1.4))
        ind = 0
        if tb:
            b, bw, bh = tbd_badge(rx + 4.3, yy, 1.6)
            o.append(b)
            ind = bw + 0.8
        s_, h = bi(rx + 4.3, yy, en, zh, 124.7, se=1.78, sz=1.58, first_indent=ind, gap=0.12)
        o.append(s_)
        yy += h + 0.8
    s_, h = bi(rx, yy + 0.2, "Sew flat; do not stretch tape or jersey (puller or walking foot). No extra clear "
               "elastic in the shoulder seam: the tape stabilises it (factory to confirm base). Check: no lump or "
               "flare at HPS; tape ends not felt from inside.",
               "平车时不拉伸织带及面料（用拖轮或同步送布）。肩缝不另加透明橡筋，由织带起牵条作用（请工厂确认原版做法）。"
               "检查：高肩点无鼓包、不外翻；内侧摸不到织带端口。", 129, se=1.75, sz=1.56)
    o.append(s_)
    yy += h + 2.2

    # ---------- tape length table
    s_, hh = heading(rx, yy, "TAPE LENGTH", "织带用量", 2.3, width=129)
    o.append(s_)
    yy += hh + 0.3
    sizes = [("S", 19, 6.5, 23), ("M", 20, 6.75, 33), ("L", 21, 7.0, 32), ("XL", 22, 7.25, 22)]
    rows = []
    tot = 0.0
    for sz_, sh, col, q in sizes:
        seam = (sh - col) / 2 * 2.54
        cut = round(seam + 2.0)
        per = 2 * cut
        m = per * q / 100
        tot += m
        rows.append([C(sz_, bold=True, align="center"), C(f"{seam:.1f}", align="center"), C(f"{cut}", align="center"),
                     C(f"{per}", align="center"), C(f"{q}", align="center"), C(f"{m:.1f}", align="center")])
    rows.append([C("Total", bold=True, align="center"), C(""), C(""), C(""), C("110", align="center", tbd=True),
                 C(f"{tot:.1f} net", align="center", bold=True)])
    s_, h = table(rx, yy, [14, 25, 22, 22, 20, 26], rows,
                  header=[C("Size"), C("Seam/side cm", "肩缝长/边"), C("Cut/side cm", "裁长/边"),
                          C("Per tee cm", "每件"), C("Qty", "件数"), C("Metres", "米数")],
                  se=1.75, sz=1.52, pad=0.45)
    o.append(s_)
    yy += h + 1.3
    s_, h = bi(rx, yy, f"Seam per side = (shoulder width - collar width) / 2 from the chart; factory to confirm from "
               f"the pattern. Qty = DROP 001 split. Net {tot:.0f} m + 10% waste + pattern matching + samples = "
               f"approx. 55 m; a 100 yd roll covers it.",
               "肩缝长按尺寸表（肩宽-领宽）/2计算，以纸样为准；件数按DROP 001配比。含损耗、对花及样衣约55米，一卷100码足够。",
               129, se=1.7, sz=1.52)
    o.append(s_)
    if yy + h > CONTENT_BOTTOM:
        WARN.append(f"page5 right overflow {yy + h:.1f}")
    return page_svg(5, "SHOULDER TAPE", "肩部棋盘格织带", "".join(o))


# ================================================================== PAGE 6: MEASUREMENTS
def page6():
    o = []
    s = 0.75
    cx, hy = 47.5, 42.0
    sv, P = draw_tee(cx, hy, s, "front", detail=False, lw=0.22)
    o.append(sv)
    o.append(text(10, 25.5, "POINTS OF MEASURE", 2.6, bold=True))
    o.append(text(10 + tw("POINTS OF MEASURE", 2.6, bold=True) + 2, 25.5, "量度部位", 2.2, zh=True, bold=True, fill=ZHC))
    HPS, CT, CBt, HEM = tee_points()

    def mark(p, letter):
        return num(p[0], p[1], letter, 1.55, fill=WHITE, fg=INK) + circle(p[0], p[1], 1.55, "none", INK, 0.25)

    col = "#1F4E9E"
    # A body length from HPS
    o.append(dim(P(NECK_HW, 0), P(NECK_HW, LEN), 0, "", 1.6, color=col, ext=False))
    o.append(mark(add(P(NECK_HW, LEN * 0.8), (2.2, 0)), "A"))
    # B chest
    o.append(dim(P(-BODY_HW, UA[1] + 2.54), P(BODY_HW, UA[1] + 2.54), 0, "", 1.6, color=col, ext=False))
    o.append(mark(add(P(-BODY_HW * 0.55, UA[1] + 2.54), (0, -2.0)), "B"))
    # C shoulder
    o.append(dim(P(-SP[0], SP[1]), P(SP[0], SP[1]), 7.5 * s, "", 1.6, color=col))
    o.append(mark(add(P(-14, SP[1] - 7.5), (0, 0)), "C"))
    # D sleeve length
    o.append(dim(P(SP[0], SP[1]), P(CT[0], CT[1]), 4.0, "", 1.6, color=col))
    dm = P((SP[0] + CT[0]) / 2, (SP[1] + CT[1]) / 2)
    o.append(mark(add(dm, (-0.5, -6.5)), "D"))
    # E collar width
    o.append(dim(P(-NECK_HW, 0), P(NECK_HW, 0), 2.6, "", 1.6, color=col))
    o.append(mark(add(P(0, 0), (0, -5.2)), "E"))
    # F rib (label only)
    o.append(mark(add(P(-NECK_HW + 0.5, FND - 0.6), (-2.0, 2.2)), "F"))
    # G cuff
    o.append(dim(P(CT[0], CT[1]), P(CBt[0], CBt[1]), -3.0, "", 1.6, color=col))
    o.append(mark(add(P(CBt[0], CBt[1]), (1.0, 4.2)), "G"))
    # H bottom
    o.append(dim(P(-BODY_HW, LEN), P(BODY_HW, LEN), -3.2, "", 1.6, color=col))
    o.append(mark(add(P(-BODY_HW * 0.5, LEN), (0, 5.4)), "H"))
    # HPS line across the neck (reference for I and K)
    o.append(line(*P(-NECK_HW - 1.0, 0), *P(NECK_HW + 1.0, 0), col, 0.15, dash="0.6 0.4"))
    # I front neck drop (drawn just right of CF so K can run on CF; extension line from the seam at CF)
    xi = 1.8
    o.append(dim(P(xi, 0), P(xi, FND), 0, "", 1.4, color=col, ext=False))
    o.append(line(*P(0.2, FND), *P(xi + 0.6, FND), col, 0.15))
    o.append(mark(add(P(xi, FND), (2.4, 2.2)), "I"))
    # K X placement: on CF, from the HPS line down to the top inner-corner STITCH point of the X (arrow tip on it)
    ky = X_CENTER_Y - top_corner_depth(G200) / 10.0
    o.append(dim(P(0, 0), P(0, ky), 0, "", 1.4, color=col, ext=False))
    o.append(mark(add(P(0, (FND + ky) / 2), (-2.6, 0)), "K"))
    o.append(mark(add(P(-10.5, X_CENTER_Y + 11.5), (-1.8, 1.8)), "M"))

    # general notes under the diagram
    gy = 110.0
    s_, h = bi(10, gy, "Measure the finished garment flat on a table, smoothed, not stretched. Half measurements. "
               "If the garment is washed, measure after washing.",
               "成衣平放量度，抚平，不拉伸。半围尺寸。如有水洗，以洗后尺寸为准。", 80, se=1.9, sz=1.7)
    o.append(s_)
    gy += h + 2.0
    s_, h = bi(10, gy, "Inches shown as decimals with cm below. Chart = DROP 001 chart with half chest reduced 1\".",
               "英寸以小数表示，下行为厘米。尺寸表为DROP 001尺寸，胸围已减1英寸。", 80, se=1.9, sz=1.7)
    o.append(s_)
    gy += h + 2.0
    s_, h = tbd_box(10, gy, 80, "Tolerances are proposals per POM. The proforma says +/-0.5\" for everything; please "
                    "confirm or propose your own.",
                    "公差为逐项建议值；形式发票为统一±0.5英寸，请工厂确认或提出意见。", se=1.85, sz=1.65)
    o.append(s_)
    gy += h + 2.0
    s_, h = tbd_box(10, gy, 80, "Half bottom: the chest was reduced 1\" but the hem was not. Keep hem as charted "
                    "(1\" wider than chest, slight flare) or reduce by 1\" too?",
                    "胸围已减1英寸，下摆未改：下摆保持原数（比胸围宽1英寸）还是同样减1英寸？", se=1.85, sz=1.65)
    o.append(s_)

    # table
    def cm(v):
        return f"{v * 2.54:.1f}"

    data = [
        ("A", "Body length", "衣长", "HPS straight down to hem edge (front). Confirm the factory uses the same basis.",
         "由高肩点垂直量至下摆边（前片），请确认量法同原版。", (0.5, 1.3), [25, 26, 27, 28], "+1", False),
        ("B", "1/2 chest", "1/2胸围", "1\" (2.5 cm) below armhole, edge to edge.", "夹下1寸平量，边至边。",
         (0.5, 1.3), [24.75, 25.75, 26.75, 27.75], "+1", False),
        ("C", "Shoulder width", "肩宽", "Armhole seam to armhole seam, straight across.", "左右袖窿骨（肩点）之间直量。",
         (0.375, 1.0), [19, 20, 21, 22], "+1", False),
        ("D", "Sleeve length", "袖长", "Shoulder point along top fold to sleeve hem edge.", "由肩点沿袖中线量至袖口边。",
         (0.375, 1.0), [10.625, 11, 11.375, 11.75], "+0.375", False),
        ("E", "Collar width", "领宽", "HPS to HPS straight across. Seam to seam or inside edge? Confirm.",
         "高肩点间直量；骨至骨或边至边，请确认。", (0.25, 0.6), [6.5, 6.75, 7, 7.25], "+0.25", False),
        ("F", "Collar rib height", "领高", "Seam to edge, at CB.", "后中量，骨至边。", (0.125, 0.3), [1, 1, 1, 1], "0",
         False),
        ("G", "1/2 cuff", "1/2袖口", "Sleeve opening straight across, edge to edge.", "袖口平量，边至边。",
         (0.25, 0.6), [8.125, 8.5, 8.875, 9], "+0.375", False),
        ("H", "1/2 bottom", "1/2下摆", "Bottom edge straight across, edge to edge.", "下摆平量，边至边。",
         (0.5, 1.3), [25.75, 26.75, 27.75, 28.75], "+1", True),
    ]
    head = [C("POM"), C("Point of measure", "部位"), C("How to measure", "量法"), C("Tol +/-", "公差"),
            C("S", align="center"), C("M", align="center"), C("L", align="center"), C("XL", align="center"),
            C("Grade", "跳码")]
    rows = []
    for code, en, zh, how, howzh, tol, vals, grade, tb in data:
        r = [C(code, bold=True, align="center"), C(en, zh, bold=True), C(how, howzh),
             C(f'{tol[0]:g}"', sub=f"{tol[1]} cm", align="center")]
        for i, v in enumerate(vals):
            c = C(f"{v:.3f}".rstrip("0").rstrip(".") if v != int(v) else f"{v:.0f}", sub=cm(v), align="center")
            if code == "G" and i == 3:
                c["tbd"] = True
                c["sub"] = cm(v) + " (9.25?)"
            if tb:
                c["tbd"] = True
            r.append(c)
        r.append(C(grade, align="center"))
        rows.append(r)
    # new POMs
    rows.append(("SPAN", C("NEW POINTS FOR THIS STYLE (proposals; I, P, Q values from the factory)",
                           inline_zh="本款新增量度（建议值；I、P、Q由工厂提供）", bold=True)))
    rows.append([C("I", bold=True, align="center"), C("Front neck drop", "前领深", bold=True),
                 C("HPS line straight down to front neck seam at CF.", "高肩点连线垂直量至前中领骨。"),
                 C('0.25"', sub="0.6 cm", align="center"),
                 C("as base", align="center", tbd=True), C("as base", align="center", tbd=True),
                 C("as base", align="center", tbd=True), C("as base", align="center", tbd=True), C("-", align="center")])
    dA, dB = top_corner_depth(G200), top_corner_depth(G150)
    kcells = []
    for i, cen in enumerate((26.0, 27.0, 28.0, 29.0)):
        v = cen - dA / 10.0
        kcells.append(C(f"{v / 2.54:.2f}", sub=f"{v:.1f}", align="center", tbd=True))
    kB = 27.0 - dB / 10.0
    rows.append([C("K", bold=True, align="center"), C("HPS to X top", "高肩点至X上内角", bold=True),
                 C(f"HPS line straight down to the top inner-corner stitch point of the X; X centred on CF (+/-0.3 cm). "
                   f"Proto B (150 mm X, same centre): M = {kB:.1f} cm.",
                   f"高肩点垂直量至X上内角车线点；X居前中（±0.3cm）。B件（150mm）M码{kB:.1f}cm。"),
                 C('0.2"', sub="0.5 cm", align="center")] + kcells + [C("+0.39", align="center")])
    sa = bbox(stitch_outline(G200))
    sw_, sh_ = sa[2] - sa[0], sa[3] - sa[1]
    sb_ = bbox(stitch_outline(G150))
    mcell = f"{sw_ / 25.4:.2f} x {sh_ / 25.4:.2f}"
    msub = f"{sw_ / 10:.1f} x {sh_ / 10:.1f}"
    rows.append([C("M", bold=True, align="center"), C("X size, stitch box", "X车线外框宽x高", bold=True),
                 C(f"Bounding box of the STITCH line (page 3), W x H. Same for all sizes. Proto B (150 mm X): "
                   f"{sb_[2] - sb_[0]:.0f} x {sb_[3] - sb_[1]:.1f} mm.",
                   f"车线外框（第3页），全码相同；B件（150mm）：{sb_[2] - sb_[0]:.0f} x {sb_[3] - sb_[1]:.1f}mm。"),
                 C('0.125"', sub="0.3 cm", align="center")]
                + [C(mcell, sub=msub, align="center", tbd=True) for _ in range(4)] + [C("0", align="center")])
    rows.append([C("N", bold=True, align="center"), C("Tape position", "织带位置", bold=True),
                 C("Tape centre on shoulder seam, neck seam to armhole seam.", "织带中线对肩缝，领骨至袖窿骨。"),
                 C('0.06"', sub="0.15 cm", align="center"),
                 C("centred", align="center"), C("centred", align="center"), C("centred", align="center"),
                 C("centred", align="center"), C("-", align="center")])
    rows.append([C("P", bold=True, align="center"), C("Armhole straight", "夹直", bold=True),
                 C("Shoulder point straight to the underarm point, as base.", "肩点直量至夹底，同原版。"),
                 C('0.25"', sub="0.6 cm", align="center")]
                + [C("as base", align="center", tbd=True) for _ in range(4)] + [C("as base", align="center")])
    rows.append([C("Q", bold=True, align="center"), C("Back neck drop", "后领深", bold=True),
                 C("HPS line straight down to the back neck seam at CB, as base.", "高肩点连线垂直量至后中领骨，同原版。"),
                 C('0.125"', sub="0.3 cm", align="center")]
                + [C("as base", align="center", tbd=True) for _ in range(4)] + [C("-", align="center")])
    s_, h = table(94, 22.5, [9, 27, 58, 15, 18, 18, 18, 18, 12], rows, header=head, se=1.95, sz=1.68, pad=0.72)
    o.append(s_)
    ny = 22.5 + h + 3.0
    s2, hh = heading(94, ny, "SIZE SPEC NOTES", "尺寸说明", 2.4, width=193)
    o.append(s2)
    notes = [
        ("Grade rules: +1\" length, chest, shoulder, bottom; +0.375\" sleeve and cuff; +0.25\" collar; rib 0. "
         "XL half cuff (+0.125\") breaks the rule: 9 or 9.25?", "跳码：衣长、胸围、肩宽、下摆+1英寸；袖长、袖口+3/8英寸；领宽+1/4英寸；领高不变。XL袖口只跳1/8英寸，请确认9还是9.25。"),
        ("Use the same measuring basis as DROP 001 (length from HPS or CB, collar seam to seam or edge to edge), so "
         "both drops fit the same.", "量法须与DROP 001一致（衣长由高肩点或后中量，领宽骨至骨或边至边），保证两批尺码一致。"),
        ("All values are finished garment measurements. If a garment wash is added, the chart applies after washing.",
         "以上均为成衣尺寸；如增加成衣水洗，以洗后尺寸为准。"),
        ("X size and position are the same template for all sizes; only the distance from HPS grades (+1 cm). "
         "POM letters J, L and O are not used.",
         "X全码同一模板，仅离高肩点距离按1cm跳码。量度代号不用J、L、O。"),
    ]
    yy = ny + hh + 0.4
    for i, (en, zh) in enumerate(notes):
        o.append(circle(95.4, yy + 1.35, 0.55, INK, None))
        s2, h2 = bi(97.5, yy, en, zh, 189, se=1.85, sz=1.64, gap=0.1)
        o.append(s2)
        yy += h2 + 0.8
    if yy > CONTENT_BOTTOM:
        WARN.append(f"page6 notes overflow {yy:.1f}")
    if 22.5 + h > CONTENT_BOTTOM:
        WARN.append(f"page6 table overflow {22.5 + h:.1f}")
    return page_svg(6, "MEASUREMENTS AND TOLERANCES", "尺寸表及公差（成衣尺寸）", "".join(o))


# ================================================================== PAGE 7: BOM
def page7():
    o = []
    head = [C("#"), C("Item", "物料"), C("Description / spec", "规格"), C("Supplier", "供应商"),
            C("Colour / Pantone", "颜色"), C("Placement", "部位"), C("Qty / garment", "单件用量")]
    pa = bbox(patch_outline(G200))
    pb = bbox(patch_outline(G150))
    stA = stitch_length(stitch_outline(G200))
    stB = stitch_length(stitch_follow(G150))

    def sec(en, zh):
        return ("SPAN", C(en, inline_zh=zh, bold=True, se=1.8))
    rows = [
        sec("FABRICS", "面料"),
        ["1", C("Body fabric", "大身面料", bold=True),
         C(f"Single jersey. Use the DROP 001 article ({BASE}) IF it is 100% cotton and ≥ 200 GSM "
           "(never below 50% cotton by weight: that changes the US duty class). Otherwise quote an alternative: 220-240 GSM compacted 100% cotton, same colour, "
           "and confirm whether the pattern must be adjusted for its shrinkage. Shrinkage (AATCC 135, 3 washes): "
           "length ≤ 5%, width ≤ 3% (the shoulder tape runs in the width direction and shrinks ≤ 1%). If width "
           "shrinkage above 3%: relax / compact the fabric before cutting, or adjust the pattern for the measured "
           "shrinkage.",
           "汗布。原版面料如为全棉且≥200克则沿用（棉含量不可低于50%，否则美国关税类别改变）；否则另报220-240克全棉预缩汗布，同色，并确认纸样"
           "是否需调整。缩水率（AATCC 135，洗3次）：长≤5%，宽≤3%（肩部织带沿布宽方向，缩水≤1%）。宽缩>3%时："
           "面料先预缩（松布/预缩机）再裁，或按实测缩率调整纸样。",
           tbd=True),
         C("Xinhui"), C("Cream = DROP 001 bulk shade (body colour to confirm)", "米白，同DROP 001大货", tbd=True),
         C("Body, sleeves", "大身、袖"), C("As base", "同原版")],
        ["2", C("X under-patch", "X底布", bold=True),
         C("Same jersey article, composition and GSM as body, dyed brown, pre-shrunk. Body vs brown shrinkage "
           "difference 1-2% max. Stock brown accepted if it matches.",
           "与大身同款面料（同成分同克重），染咖啡色，预缩；两者缩水率差不超过1-2%；如有同款咖啡色现货布且缩水率相符可用"),
         C("Xinhui"), C("Chocolate brown, Pantone TCX code open, lab dip", "咖啡色，潘通TCX待定，须打色样", tbd=True),
         C("Behind X, wrong side of front", "前片反面X位"),
         C(f"1 pc, PATCH layer: box {(pa[2] - pa[0]) / 10:.0f} x {(pa[3] - pa[1]) / 10:.0f} cm "
           f"(150 mm X: {(pb[2] - pb[0]) / 10:.0f} x {(pb[3] - pb[1]) / 10:.0f} cm)", "1片，按PATCH图层裁")],
        ["3", C("Neck rib", "领罗纹", bold=True), C("As base, 1\" (2.5 cm) finished.", "同原版，成品2.5cm"), C("Xinhui"),
         C("Match body", "配大身色"), C("Neck", "领口"), C("As base", "同原版")],
        sec("TRIMS", "辅料"),
        ["4", C("Checker tape", "棋盘格织带", bold=True),
         C("Woven checker, 7.5 mm squares, 2 thin lines. Width, fibre, border and line position from founder's roll "
           "(page 5).", "棋盘格提花织带，7.5mm格，两条细线；宽度、成分、边宽及细线位置以客供实物为准", tbd=True),
         C("Customer-supplied or Humen stock", "客供或虎门现货", tbd=True), C("Cream + brown-black", "米白+深棕黑"),
         C("Both shoulder seams", "两肩缝"), C("2 pcs: 18 / 19 / 20 / 21 cm each (S-XL)", "2条，每条18/19/20/21cm（S-XL）")],
        ["5", C("Back neck tape", "后领贴", bold=True),
         C("As base, but extended 2 cm past each shoulder seam onto the front neckline, fully covering the checker "
           "tape end. Trim the checker tape end to 5 mm inside the neck seam allowance before attaching the rib.",
           "同原版，但两端各过肩缝2cm至前领，完全盖住织带端口；上领前织带端修剪至缝份内5mm。"), C("Xinhui"),
         C("As base", "同原版"), C("Inside back neck", "后领内"), C("As base + 4 cm", "原版长度+4cm")],
        ["6", C("Backing", "衬", bold=True),
         C("(a) No backing: two jersey layers hooped + light spray adhesive; (b) 1.5 oz fusible no-show mesh left in. "
           "Compare a and b on the swatch. No tear-away or wash-away unless the factory shows it on the swatch.",
           "（a）不加衬：两层汗布上绷+少量喷胶；（b）1.5oz热熔网衬保留。小样对比a与b；除非工厂小样证明可行，不用撕纸或水溶纸。",
           tbd=True),
         C("Xinhui"), C("White or none", "白色或无"), C("Behind X", "X位"), C("1 pc or none", "1片或无")],
        ["7", C("Thread, X outline", "X车线", bold=True),
         C("402 spun polyester (flatbed) or 120D/2 polyester embroidery thread, 40 wt (embroidery machine); needle "
           "and bobbin.", "402涤纶线或同粗细绣花线（电脑绣花用120D/2），面线底线"),
         C("Xinhui"), C("Proto A cream (tonal), Proto B brown-black (contrast)", "A件米白，B件深棕黑，大货待定",
                        tbd=True), C("X outline", "X轮廓"),
         C(f"Stitch {stA / 1000:.2f} m (A), {stB / 1000:.2f} m (B); thread per factory",
           f"车线{stA / 1000:.2f}m（A）/{stB / 1000:.2f}m（B）；用线量工厂核算")],
        ["8", C("Thread, tape and seams", "织带及缝线", bold=True), C("As base spun polyester.", "同原版"), C("Xinhui"),
         C("Tape stitch: cream (a) or brown-black (b), page 5; seams cream", "织带线按第5页（a）米白或（b）深棕黑；缝线米白"),
         C("Tape edges, all seams", "织带边及各缝"), C("As base", "同原版")],
        sec("LABELS AND PACKING", "唛头及包装"),
        ["9", C("Main label", "主唛", bold=True),
         C("Existing CS woven label (1000 pcs ordered). If the existing woven main label says DROP 001 it cannot be "
           "used on this style; new main label artwork (no drop number, or the new drop number) from Cultsiders.",
           "现有CS织唛（已订1000个）。如现有主唛织有DROP 001则本款不可用，需新主唛（无期数或新期数），稿件由客户提供。",
           tbd=True), C("Xinhui"), C("Black / white", "黑底白字"),
         C("Inside CB neck", "后中领内"), C("1")],
        ["10", C("Size + origin label", "尺码产地唛", bold=True), C("NEW. Size + MADE IN CHINA on the FRONT (visible) "
                                                              "side, woven or printed; artwork to be sent.",
                                                              "新增：唛头正面（外露面）织或印：尺码 + MADE IN CHINA"),
         C("Xinhui"), C("Black / white", "黑底白字"), C("Directly below main label", "主唛正下方"), C("1")],
        ["11", C("Care / content label", "洗水成分唛", bold=True), C("NEW, permanent. Fibre %, MADE IN CHINA, company name "
                                                              "or RN, English care text (page 8).", "新增：成分、产地、公司名或RN、英文洗涤说明", tbd=True),
         C("Xinhui"), C("White / black", "白底黑字"), C("Wearer's left side seam", "左侧骨"), C("1")],
        ["12", C("Polybag, hang tag", "胶袋、吊牌", bold=True),
         C("Existing DROP 001 package bag (500 pcs ordered), size sticker on bag. Hang tag optional (not in DROP 001).",
           "现有胶袋（已订500个），贴尺码贴纸；吊牌可选（DROP 001没有）"), C("Xinhui"), C("Clear", "透明"),
         C("-"), C("1 bag; tag 0 or 1", tbd=True)],
        sec("TOOLING", "工装及模板"),
        ["13", C("Cut guide, placement template, stitch stencil", "剪口模板、定位板及车线画线板", bold=True),
         C(f"From the 1:1 template ({TPL_PDF_NAME} / DXF), all in FACE view, never mirrored or rotated: (1) cut "
           "guide (acrylic or cardboard): sheet with the CUT_JAG window cut out and the stitch line drawn on it (Proto "
           "B: STITCH_FOLLOW), so the operator can match the teeth to the stitch; (2) placement template: CF, X "
           "centre, PATCH outline; (3) slotted stitch-marking stencil on STITCH (Proto B: STITCH_FOLLOW) with CF and "
           "X centre, for flatbed sewing only. On all three: engrave FACE UP / NECK plus an arrow to the neck (layer "
           "ORIENT) and cut the non-symmetric registration notch at CF top (layer GUIDE). After stitching, trace "
           "CUT_JAG onto the cream with an air-erasable pen; cut with duck-bill scissors.",
           "按1:1模板PDF/DXF制作，均为正面视图，不可翻转或旋转：（1）剪口模板（亚克力或硬纸板）：按CUT_JAG开窗，并画车线"
           "（B件：STITCH_FOLLOW），使锯齿对准车线；（2）定位板：前中、X中心、PATCH轮廓；（3）车线画线板（开槽，STITCH；"
           "B件：STITCH_FOLLOW），带前中及X中心，仅平车用。三者均刻FACE UP / NECK及箭头（正面朝上，箭头指领口，ORIENT图层），"
           "并在前中上端开不对称定位缺口（GUIDE图层）。车线后用气消笔沿剪口模板画线，用鸭嘴剪剪开。"),
         C("Xinhui"), C("-"), C("X", "X位"), C("1 set per X size", "每个X尺寸1套")],
        ["14", C("Embroidery program", "绣花制版", bold=True),
         C("Digitised from the DXF STITCH layer (Proto B: STITCH_FOLLOW, 150 mm file), face view, +Y to the neck, "
           "not mirrored. Digitising fee quoted separately.",
           "按DXF车线图层制版（B件用150mm文件STITCH_FOLLOW图层），正面视图，+Y指向领口，不可镜像；制版费另报。"),
         C("Xinhui or subcontractor", "工厂或外发"), C("-"), C("X", "X位"), C("1 per X size", "每个X尺寸1个")],
    ]
    s_, h = table(10, 22.5, [7, 25, 128, 23, 33, 27, 34], rows, header=head, se=1.82, sz=1.58, pad=0.58)
    o.append(s_)
    yy = 22.5 + h + 2.0
    s_, hh = heading(10, yy, "PLEASE SEND BEFORE SAMPLING (1-6) AND FOR US IMPORT (7-9)", "打样前请工厂提供（1-6）及美国进口文件（7-9）",
                     2.3, width=277)
    o.append(s_)
    asks = [
        ("DROP 001 fabric article code, composition and GSM, in writing.", "DROP 001面料编号、成分及克重（书面）。"),
        ("DROP 001 as-made measurement report, and how length and collar width are measured.",
         "DROP 001成衣尺寸报告及衣长、领宽量法。"),
        ("Base construction list: stitch types, hem heights, shoulder stay tape or elastic.",
         "原版做工清单：线迹、下摆高、肩缝是否加牵条或橡筋。"),
        ("Can the X outline run on a computerized embroidery machine? In-house or subcontract?",
         "X轮廓能否用电脑绣花？厂内或外发？"),
        ("Stock chocolate-brown jersey in the same article? Lab dip timing.", "是否有同款咖啡色现货布？打色样时间。"),
        ("Quote: sample fee, digitising fee, unit price with X and tape as separate lines, with and without wash, "
         "lead time.", "报价：样衣费、制版费、单价（X及织带分开列，含水洗与不含水洗）、交期。"),
        ("Fabric mill name, yarn spinner and cotton origin documents for body and brown fabric (UFLPA).",
         "面料厂、纱厂名称及棉花产地证明（大身及咖啡色布）。"),
        ("Composition test report, % by weight.", "成分检测报告（重量百分比）。"),
        ("Declaration: no PFAS / fluorinated finishes on fabric and tape.", "面料及织带不含PFAS（无含氟整理）声明。"),
    ]
    yy += hh + 0.3
    colw = 277 / 3
    ymax = yy
    for c in range(3):
        yl = yy
        for i in range(c * 3, c * 3 + 3):
            en, zh = asks[i]
            x = 10 + c * colw
            o.append(text(x, yl + 1.8, f"{i + 1}.", 1.85, bold=True))
            s_, h = bi(x + 3.6, yl, en, zh, colw - 6.0, se=1.85, sz=1.62, gap=0.1)
            o.append(s_)
            yl += h + 0.9
        ymax = max(ymax, yl)
    if ymax > CONTENT_BOTTOM:
        WARN.append(f"page7 asks overflow {ymax:.1f}")
    return page_svg(7, "BILL OF MATERIALS", "物料清单 BOM", "".join(o))


# ================================================================== PAGE 8: LABELS, QC, SAMPLES
def page8():
    o = []
    SEx, SZx = 1.9, 1.66
    # ---------- label placement diagram
    s_, hh = heading(10, 22, "LABEL PLACEMENT", "唛头位置", 2.6, width=132)
    o.append(s_)
    x0, y0 = 12.0, 29.0
    w, h = 60.0, 36.0
    o.append(rect(x0, y0, w, h, CREAM_D, None))

    def arc(dy, n=40):
        return [(x0 + w * i / n, y0 + dy + 5.0 * math.sin(math.pi * i / n)) for i in range(n + 1)]

    rib_bot = arc(4.0)
    o.append(poly([(x0, y0), (x0 + w, y0)] + list(reversed(rib_bot)), fill=CREAM, stroke=None))
    for i in range(1, 40):
        xx = x0 + w * i / 40
        yb_ = y0 + 4.0 + 5.0 * math.sin(math.pi * i / 40)
        o.append(line(xx, y0 + 0.4, xx, yb_ - 0.4, "#D8CFB8", 0.15))
    tape_b = arc(7.2)
    o.append(poly(rib_bot + list(reversed(tape_b)), fill="#CFC4AA", stroke=GREY, sw=0.2))
    o.append(poly(rib_bot, stroke=INK, sw=0.3, closed=False))
    lx = x0 + w / 2
    ly_ = y0 + 4.0 + 5.0 + 0.4
    o.append(rect(lx - 7, ly_, 14, 8.0, BROWN_BK, INK, 0.2))
    o.append(text(lx, ly_ + 4.9, "CS main", 1.8, bold=True, fill=WHITE, anchor="middle"))
    o.append(rect(lx - 5.5, ly_ + 8.4, 11, 7.2, WHITE, INK, 0.2))
    o.append(text(lx, ly_ + 11.3, "M", 2.0, bold=True, anchor="middle"))
    o.append(text(lx, ly_ + 14.1, "MADE IN CHINA", 1.3, bold=True, anchor="middle"))
    o.append(text(x0 + 1.2, y0 + 2.8, "neck rib", 1.6, fill=GREY))
    o.append(text(x0 + 1.2, y0 + h - 1.6, "Inside back neck (schematic)", 1.6, fill=GREY))
    o.append(leader((x0 + 6, y0 + 13.5), (x0 + 9, y0 + 6.3)))
    o.append(text(x0 + 1.2, y0 + 16.0, "back neck tape", 1.6, fill=GREY))
    o.append(leader((lx + 11, ly_ + 12), (lx + 5.8, ly_ + 12)))
    o.append(text(lx + 11.5, ly_ + 11.3, "size +", 1.6, fill=GREY))
    o.append(text(lx + 11.5, ly_ + 13.5, "origin", 1.6, fill=GREY))
    tx_ = x0 + w + 3
    s_, h1 = bi(tx_, y0, "Country of origin on the FRONT side of a label at the inside centre neck, midway between "
                "the shoulder seams, next to the main label (16 CFR 303.15(b)).",
                "产地须印在后中领内唛头的正面，位于两肩缝正中，紧挨主唛。", 142 - tx_, se=SEx, sz=SZx)
    o.append(s_)
    s_, h2 = bi(tx_, y0 + 1.8 + h1, "Care / content label: wearer's left side seam, inside, sewn into the seam.",
                "洗水成分唛：穿着者左侧骨内，车入侧骨。", 142 - tx_, se=SEx, sz=SZx)
    o.append(s_)
    b, bw, bh = tbd_badge(tx_, y0 + 3.6 + h1 + h2, 1.7)
    o.append(b)
    s_, h3 = bi(tx_, y0 + 3.6 + h1 + h2, "Height above hem.", "离下摆高度待定", 142 - tx_, se=SEx, sz=SZx,
                first_indent=bw + 0.8)
    o.append(s_)

    ty = y0 + h + 2.5
    rows = [
        [C("Main label", "主唛", bold=True),
         C("If the existing woven main label says DROP 001 it cannot be used on this style; new main label artwork "
           "(no drop number, or the new drop number) from Cultsiders.",
           "如现有主唛织有DROP 001则本款不可用，需新主唛（无期数或新期数），稿件由客户提供。", tbd=True)],
        [C("Size + origin", "尺码产地唛", bold=True), C("Front: \"M\" / \"MADE IN CHINA\". Letters at least as large as other text.",
                                                        "正面：尺码 / MADE IN CHINA")],
        [C("Care / content", "洗水成分唛", bold=True),
         C("\"100% COTTON\" (confirm) + \"EXCLUSIVE OF DECORATION\" if tape fibre differs. \"MADE IN CHINA\". Company "
           "name or RN. Care text below.", "成分待确认；如织带成分不同加注EXCLUSIVE OF DECORATION；产地；公司名或RN", tbd=True)],
        [C("Care text", "洗涤说明", bold=True),
         C("MACHINE WASH COLD, INSIDE OUT / WASH WITH LIKE COLORS / ONLY NON-CHLORINE BLEACH WHEN NEEDED / TUMBLE DRY "
           "LOW / DO NOT IRON DECORATION. Final text after whole-garment wash test.",
           "英文文字，不用ISO/GINETEX符号；成衣洗测后定稿", tbd=True)],
        [C("Rules", "规定", bold=True),
         C("English words, permanent. No ISO / GINETEX care symbols. No other place names on labels (if any, MADE IN "
           "CHINA must sit next to them, same size). Artwork from Cultsiders.",
           "英文、永久性；不用ISO符号；唛头不得出现其他地名；唛头稿由客户提供")],
    ]
    s_, h = table(10, ty, [25, 107], rows, se=1.85, sz=1.62, pad=0.65)
    o.append(s_)

    py = ty + h + 2.4
    s_, hh = heading(10, py, "PACKING", "包装", 2.4, width=132)
    o.append(s_)
    pk = [
        ("Fold with the X flat and fully visible through the bag; no fold line across the X.",
         "折叠时X平整完整朝外，折线不可压过X。"),
        ("Existing DROP 001 polybag; size sticker on the bag, readable without opening.", "用现有胶袋，贴尺码贴纸，不开袋可见。"),
        ("Carton marks: style, colour, size breakdown, qty, carton no., G.W. / N.W., MADE IN CHINA.",
         "外箱唛：款号、颜色、尺码配比、数量、箱号、毛净重、MADE IN CHINA。"),
    ]
    yy = py + hh + 0.3
    for en, zh in pk:
        o.append(circle(11.4, yy + 1.3, 0.55, INK, None))
        s_, h = bi(13.5, yy, en, zh, 128, se=SEx, sz=SZx, gap=0.1)
        o.append(s_)
        yy += h + 0.8
    left_end = yy

    # ---------- right: QC
    rx = 150
    s_, hh = heading(rx, 22, "QC CHECKLIST FOR THIS STYLE", "本款验货要点", 2.6, width=137)
    o.append(s_)
    qc = [
        ("X position and symmetry vs template; centre +/-0.5 cm, on CF +/-0.3 cm.", "X位置及对称，中心±0.5cm，前中±0.3cm。"),
        ("Cut-to-stitch nominal 4-7 mm (B: at the valleys). Accept ≥ 3 mm. Reject < 3 mm or any cut stitch.",
         "剪口距车线标准4-7mm（B方案按齿谷）；≥3mm可接受；<3mm或剪断车线为次品。"),
        ("CRITICAL: any cut, nick or hole in the brown under-patch.", "严重：咖啡色底布有任何剪口或破洞。"),
        (f"Visible brown across each arm ≥ {BROWN_MIN['200']:g} mm (Proto B ≥ {BROWN_MIN['150']:g} mm), never "
         "narrower than the tip; teeth on the two sides staggered, not opposite. X not mirrored (compare template).",
         f"每条臂可见咖啡色≥{BROWN_MIN['200']:g}mm（B件≥{BROWN_MIN['150']:g}mm），任何位置不窄于尖端；两侧锯齿错开，"
         "不相对。X不可镜像（对照模板）。"),
        ("No runs or holes at the 4 tips and 4 inner corners.", "4个尖端及4个内角无脱散、无破洞。"),
        ("Under-patch covers the window, face side out, lies flat. Edge 7-13 mm past the stitch along the arms; up "
         "to 15 mm at the 4 inner corners (and on Proto B where the stitch steps in behind a tooth) is correct per DXF.",
         "底布盖满开口，正面朝外，平服。沿臂距车线7-13mm；4个内角处（及B件车线随锯齿内收处）可达15mm，按DXF属正常。"),
        ("X edge matches the approved swatch (A / B / C). No pucker or waves; no brown lint, dye marks or "
         "show-through on cream.", "剪口效果与确认小样一致（A/B/C）；不起皱、不起波浪；米白处无咖啡色毛絮、染色或透影。"),
        ("Tape centred +/-1.5 mm, straight, same phase both sides, edge-stitch per (a) or (b), no pucker.",
         "织带居中±1.5mm，顺直，两边花位一致，边线按（a）或（b），不起皱。"),
        ("No lump or flare at HPS; tape ends not felt from inside.", "高肩点无鼓包、不外翻；内侧摸不到织带端口。"),
        ("Neck stretches over the head without broken stitches (X and tape).", "领口可套头拉开，X及织带线不断。"),
        ("Measurements per size within tolerance (page 6). Labels correct.", "各码尺寸在公差内（第6页），唛头正确。"),
    ]
    yy = 22 + hh + 0.3
    for i, (en, zh) in enumerate(qc):
        o.append(rect(rx, yy + 0.3, 2.2, 2.2, "none", INK, 0.25))
        s_, h = bi(rx + 3.6, yy, en, zh, 133.4, se=SEx, sz=SZx, gap=0.08)
        o.append(s_)
        yy += h + 0.7
    s_, h = tbd_box(rx, yy + 0.3, 137, "AQL proposal: 0 critical / 2.5 major / 4.0 minor. Photos of the X area of every "
                    "piece and measurement photos per size before shipping.",
                    "AQL建议：严重0 / 主要2.5 / 次要4.0；出货前每件X位拍照，各码量尺寸拍照。", se=1.8, sz=1.6, pad=0.8)
    o.append(s_)
    yy += h + 2.2

    # ---------- samples and tests
    s_, hh = heading(rx, yy, "SAMPLE REQUEST AND TESTS", "样衣及测试要求", 2.6, width=137)
    o.append(s_)
    yy += hh + 0.3
    sm = [
        ("1", "SWATCH (same round as the protos, real fabrics): three edges side by side. A: freehand jag 0-3 mm "
              "inside BASE (4-7 mm from the stitch); B irregular teeth 3-8 mm deep (less where the arm narrows) at "
              "5-15 mm spacing, staggered side to side, smooth stitch "
              "≥ 3 mm from the deepest valley (CUT_JAG, 1:1 template); C = B + hand-brushed or sanded raw edge. Also "
              "backing a vs b and tips 10-12 mm. Photograph all after 3 washes. The swatch decides the bulk edge; "
              "both protos use edge B.",
         "工艺小样（与头办同轮，用大货布）：三种边并排。A：BASE线内0-3mm徒手锯齿（距车线4-7mm）；B：不规则齿深3-8mm"
         "（臂变窄处更浅）、齿距5-15mm、两侧错开，车线平顺，距最深齿谷≥3mm（CUT_JAG，1:1模板）；C：B＋手工磨毛边。同时对比衬a/b及尖端10-12mm。"
         "洗3次后全部拍照。小样决定大货边；两件头办均用B边。", False),
        ("2", "PROTO: 2 pcs size M, both edge B, cut on CUT_JAG. Proto A = 200 x 210 mm X, cream tonal thread, "
              "smooth stitch (STITCH). Proto B = 150 mm X, brown-black thread, stitch follows jag (STITCH_FOLLOW). "
              "Real fabrics and real tape, per pages 3-5.",
         "头办M码2件，均用B边，按CUT_JAG剪：A件200x210mm、米白同色线、车线平顺（STITCH）；B件150mm、深棕黑线、"
         "车线沿锯齿（STITCH_FOLLOW）。用大货布及实际织带，按第3-5页。",
         False),
        ("3", "Photograph both unwashed, then home-wash only Proto B 5x (30-40°C, tumble low; photos after washes "
              "1 / 3 / 5 of edges, corners, staining, show-through, tape pucker (pass / fail); re-measure). Keep Proto A unwashed "
              "as the reference.",
         "两件先拍照，B件家洗5次（30-40°C，低温烘干；第1/3/5次拍X边、内角、沾色、透影、织带起皱（合格判定项），并复尺），A件不洗留底。",
         False),
        ("4", "Stretch test on Proto B after washing: X area and neck to full extension, no broken thread.",
         "拉伸测试（B件洗后）：X位及领口拉至最大，不断线。", False),
        ("5", "Brown fabric + tape: AATCC 61 2A (49°C) or ISO 105-C06 A1M (40°C), each about 5 home washes: change "
              "≥ 4, staining on cotton ≥ 4 (target, min 3-4); GB/T 31127 joint transfer ≥ 4; AATCC 8 dry ≥ 4 / wet "
              "≥ 3; AATCC 135, 3 cycles: length ≤ 5%, width ≤ 3% (tape ≤ 1%).",
         "咖啡色布及织带：AATCC 61 2A（49°C）或ISO 105-C06 A1M（40°C），均约等于家洗5次：变色≥4级，棉沾色≥4级"
         "（目标，最低3-4级）；GB/T 31127拼接互染≥4级；AATCC 8干摩≥4级、湿摩≥3级；AATCC 135洗3次，长≤5%，宽≤3%"
         "（织带≤1%）。", True),
    ]
    for n, en, zh, tb in sm:
        o.append(num(rx + 1.5, yy + 1.6, n, 1.4))
        ind = 0
        if tb:
            b, bw, bh = tbd_badge(rx + 4.3, yy, 1.6)
            o.append(b)
            ind = bw + 0.8
        s_, h = bi(rx + 4.3, yy, en, zh, 132.7, se=1.85, sz=1.64, first_indent=ind, gap=0.1)
        o.append(s_)
        yy += h + 0.8
    right_end = yy

    # ---------- stage flow (full width)
    fy = max(left_end, right_end) + 1.6
    s_, hh = heading(10, fy, "STAGES AND APPROVAL", "打样阶段及确认", 2.4, width=277)
    o.append(s_)
    fy += hh + 0.4
    stages = [
        ("Swatch", "工艺小样", "Edges A / B / C + backing a / b; photos after 3 washes.", "边缘A/B/C及衬a/b，洗3次后拍照。",
         False),
        ("Proto", "头办", "2 pcs M (A + B). Approve X size, thread, edge and washed look.",
         "M码2件（A+B），确认X尺寸、线色、剪口及洗后效果。", False),
        ("PP sample", "产前样", "Bulk fabric, final labels, packing; wash test + measurements. Qty open.",
         "大货布、正式唛头及包装；洗测及尺寸报告；件数待定。", True),
        ("Bulk", "大货", "Only after written PP approval.", "产前样书面确认后开货。", False),
        ("TOP", "大货样", "Photos + measurements of first pieces per size before shipping.", "出货前首批各码拍照及量尺寸。", False),
    ]
    bw_ = 277 / 5
    bh_ = 0
    boxes = []
    for i, (en, zh, d_en, d_zh, tb) in enumerate(stages):
        bx = 10 + i * bw_
        s1 = text(bx + 2.0, fy + 2.9, en, 2.0, bold=True) + text(bx + 2.2 + tw(en, 2.0, bold=True) + 1.0, fy + 2.9,
                                                                  zh, 1.75, zh=True, bold=True, fill=ZHC)
        ind = 0
        extra = ""
        if tb:
            b, bwid, bhh = tbd_badge(bx + 2.0, fy + 4.1, 1.55)
            extra = b
            ind = bwid + 0.8
        s2, h2 = bi(bx + 2.0, fy + 4.1, d_en, d_zh, bw_ - 7.5, se=1.72, sz=1.54, first_indent=ind, gap=0.08)
        boxes.append((bx, s1 + extra + s2))
        bh_ = max(bh_, 4.1 + h2 + 1.0)
    for i, (bx, content) in enumerate(boxes):
        o.append(rect(bx, fy, bw_ - 4.5, bh_, "none", INK, 0.25))
        o.append(content)
        if i < len(boxes) - 1:
            ax = bx + bw_ - 4.5
            o.append(line(ax + 0.4, fy + bh_ / 2, ax + 3.2, fy + bh_ / 2, INK, 0.3))
            o.append(arrowhead((ax + 4.2, fy + bh_ / 2), (1, 0), L=1.3, W=1.1))
    fy += bh_ + 1.2
    s_, h = bi(10, fy, "Written approval at each stage. The latest released PDF governs; chat messages do not change it. "
               "Any change of fabric, thread or method needs written approval before sewing. Target: PP approved by "
               "early December 2026, before the Chinese New Year 2027 break (6 Feb).",
               "每阶段须书面确认。以最新发出的PDF为准，聊天信息不改变工艺单。更改面料、用线或做法须先书面确认。"
               "目标：2026年12月上旬前确认产前样，赶在2027年春节（2月6日）前。", 277, se=1.8, sz=1.6, gap=0.1)
    o.append(s_)
    if fy + h > CONTENT_BOTTOM:
        WARN.append(f"page8 overflow {fy + h:.1f}")
    return page_svg(8, "LABELS, PACKING, QC, SAMPLES", "唛头、包装、验货及样衣要求", "".join(o))


# ================================================================== 1:1 TEMPLATE (PDF + DXF)
TPL_PDF = os.path.join(HERE, TPL_PDF_NAME)
DXF200 = os.path.join(HERE, DXF200_NAME)
DXF150 = os.path.join(HERE, DXF150_NAME)
CUT_COL = "#8A2A12"


SHEET_M = 1.5                 # GUIDE sheet: PATCH bounding box + 1.5 mm (minimum size of guide / stencil / template)
NOTCH = (6.0, 6.0)            # registration notch at CF top: width to +X (right in face view), depth
ENG = "#1F4E9E"               # colour of the GUIDE / ORIENT layers on the PDF (cut / engrave on the tooling)
FACE_WARN_EN = ("FACE VIEW (outside). Do not mirror or rotate. Cut guide, stitch stencil and embroidery program "
                "must use the same orientation.")
FACE_WARN_ZH = "正面视图，不可翻转或旋转；剪口模板、画线板及绣花程序方向一致。"


def guide_sheet(g):
    """GUIDE layer (face view, y down): minimum sheet for cut guide, stitch stencil and placement template, with an
    asymmetric registration notch at CF top: straight side on CF, sloped side to the right (+X). Mirrored or
    rotated, the notch no longer sits on CF at the top, so a flipped sheet is visible at once."""
    pb = bbox(patch_outline(g))
    x0, y0, x1, y1 = pb[0] - SHEET_M, pb[1] - SHEET_M, pb[2] + SHEET_M, pb[3] + SHEET_M
    nw, nd = NOTCH
    return [(x0, y0), (0.0, y0), (0.0, y0 + nd), (nw, y0), (x1, y0), (x1, y1), (x0, y1)]


def wedge_halfwidth(g, y):
    """Free half-width (mm) at height y (face view, y < 0) between CF and the upper-right arm's PATCH line."""
    P = LinearRing(patch_outline(g))
    I = LineString([(0.0, y), (400.0, y)]).intersection(P)
    xs = [p.x for p in getattr(I, "geoms", [I]) if hasattr(p, "x")]
    return min(xs) if xs else 0.0


def orient_arrow(g, tip_y, tail_y, head=5.0, shaft=1.4, head_w=5.0):
    """ORIENT layer: engraved arrow on CF pointing to the neck (face view, y down). Closed outline."""
    hy = tip_y + head
    return [(0.0, tip_y), (head_w / 2, hy), (shaft / 2, hy), (shaft / 2, tail_y), (-shaft / 2, tail_y),
            (-shaft / 2, hy), (-head_w / 2, hy)]


def orient_layout(g, ts):
    """Place the engraving (arrow + FACE UP / NECK) in the top wedge between the upper arms, clear of PATCH.
    Returns dict with the arrow outline, the text lines [(x, y_baseline, size, str, kind)] and the notch caption."""
    pc = max(y for x, y in patch_outline(g, n_arc=40, n_side=80) if abs(x) < 0.3 and y < 0)
    k = ts / 2.45
    lines = [("FACE UP / NECK", 3.1 * k, "eng", True), ("ENGRAVE arrow + text (ORIENT)", 1.75 * k, "en", False),
             ("刻箭头及文字：正面朝上，箭头指领口", 1.6 * k, "zh", False)]
    xt = 4.0 * k
    offs = [-4.9 * k, -2.35 * k, 0.0]           # baselines relative to the bottom (Chinese) line
    y = pc - 9.0 * k
    while True:
        ys = [y + d for d in offs]
        if all(wedge_halfwidth(g, yb + 0.3 * sz) >= xt + tw(s_, sz, zh=(kind == "zh"), bold=bold) + 2.5
               for (s_, sz, kind, bold), yb in zip(lines, ys)):
            break
        y -= 0.5
    tip = ys[0] - lines[0][1] - 1.5 * k
    arrow = orient_arrow(g, tip, pc - 6.0 * k, head=5.0 * k, shaft=1.4 * k, head_w=5.0 * k)
    return {"arrow": arrow, "text": [(xt, yb, sz, s_, kind, bold) for (s_, sz, kind, bold), yb in zip(lines, ys)],
            "pc": pc}


def template_layers(g):
    L = {"PATCH": patch_outline(g, n_arc=24, n_side=80),
         "STITCH": stitch_outline(g, n_arc=24, n_side=80),
         "BASE": base_outline(g, n_arc=24, n_side=80),
         "CUT_JAG": x_cut_B(g)}
    if g is G150:
        L["STITCH_FOLLOW"] = stitch_follow(g)
    L["GUIDE"] = guide_sheet(g)
    return L


def tpl_leader_label(o, p, q, lab_en, lab_zh, size):
    o.append(line(p[0], p[1], q[0], q[1], INK, 0.2))
    o.append(circle(p[0], p[1], 0.55, INK, None))
    o.append(text(q[0] + 1.0, q[1] + size * 0.35, lab_en, size, bold=True))
    o.append(text(q[0] + 1.0, q[1] + size * 0.35 + size * 1.25, lab_zh, size * 0.85, zh=True, fill=ZHC))


def check_bars_tpl(pw, cx, cy, pb, ts, m):
    """Two 50 mm bars in free space: vertical right of the GUIDE sheet (above the X-centre line, label on its right),
    horizontal under the sheet at the right. Returns (svg, y_bottom of the horizontal bar block)."""
    o = []
    vx = min(pw - m - 1.6, cx + pb[2] + SHEET_M + 1.8)
    vy = cy - 56.0
    for i in range(5):
        col = INK if i % 2 == 0 else WHITE
        o.append(rect(vx, vy + i * 10, 1.6, 10, col, INK, 0.15))
    o.append(line(vx - 1.2, vy, vx + 1.6, vy, INK, 0.2))
    o.append(line(vx - 1.2, vy + 50, vx + 1.6, vy + 50, INK, 0.2))
    lx_ = vx + 1.6 + 0.6 + ts * 0.8 * 0.72
    o.append(f'<g transform="rotate(-90 {f2(lx_)} {f2(vy + 25)})">'
             + text(lx_, vy + 25, "50 mm", ts * 0.8, bold=True, anchor="middle") + "</g>")
    # horizontal bar in the empty bottom wedge between the lower arms: bar right of CF, text left of CF
    hy = cy + pb[3] - 4.0
    hx = cx + 3.0
    for i in range(5):
        col = INK if i % 2 == 0 else WHITE
        o.append(rect(hx + i * 10, hy, 10, 1.6, col, INK, 0.15))
    o.append(line(hx, hy - 1.0, hx, hy + 1.6, INK, 0.2))
    o.append(line(hx + 50, hy - 1.0, hx + 50, hy + 1.6, INK, 0.2))
    tx_ = cx - 3.0
    o.append(text(tx_, hy + 1.2, "Check both bars = 50 mm", ts * 0.85, bold=True, anchor="end"))
    o.append(text(tx_, hy + 1.2 + ts * 1.2, "两条校准线均应为50mm", ts * 0.75, zh=True, anchor="end", fill=ZHC))
    return "".join(o), hy + 1.2 + ts * 1.2 + 0.6


def template_svg(g, pw, ph, page_no, cx, cy, proto, ts, m):
    """One 1:1 template page. Real millimetres: width/height in mm, viewBox in mm."""
    o = [rect(0, 0, pw, ph, WHITE)]
    L = template_layers(g)
    th, T, phis = x_axes(g)
    pb = bbox(L["PATCH"])
    # crosshair: CF + X centre
    o.append(line(cx, cy + pb[1] - 7.0, cx, cy + pb[3] + 6, GREY, 0.25, dash="6 1.5 1 1.5"))
    o.append(line(cx + pb[0] - 6, cy, cx + pb[2] + 0.5, cy, GREY, 0.25, dash="6 1.5 1 1.5"))
    o.append(circle(cx, cy, 1.6, "none", INK, 0.25))
    o.append(line(cx - 3.5, cy, cx + 3.5, cy, INK, 0.3))
    o.append(line(cx, cy - 3.5, cx, cy + 3.5, INK, 0.3))
    o.append(text(cx - 1.2, cy + pb[3] + 5.0, "CF", ts * 1.1, bold=True, fill=GREY, anchor="end"))
    o.append(text(cx + pb[0] + 1.5, cy - 1.2, "X CENTRE", ts * 0.95, bold=True, fill=GREY))
    o.append(text(cx + pb[0] + 1.5, cy + ts * 1.35, "X中心", ts * 0.85, zh=True, fill=GREY))
    # GUIDE sheet (minimum size) with the registration notch at CF top
    o.append(poly(tx(L["GUIDE"], cx, cy, 1.0), stroke=ENG, sw=0.3, join="miter"))
    # ORIENT: engraved arrow + FACE UP / NECK in the top wedge
    OL = orient_layout(g, ts)
    o.append(poly(tx(OL["arrow"], cx, cy, 1.0), fill="none", stroke=ENG, sw=0.3, join="miter"))
    for xt_, yb, sz, s_, kind, bold in OL["text"]:
        if kind == "eng":
            o.append(text(cx + xt_, cy + yb, s_, sz, bold=True, fill=ENG))
        else:
            o.append(text(cx + xt_, cy + yb, s_, sz, zh=(kind == "zh"), fill=GREY if kind == "en" else ZHC))
    # notch caption (right of the notch, under the sheet top edge)
    k_ = ts / 2.45
    ny = cy + L["GUIDE"][0][1] + 2.2 * k_
    nx = cx + NOTCH[0] + 2.5 * k_
    o.append(text(nx, ny + 1.75 * k_, "Registration notch at CF top:", 1.75 * k_, bold=True, fill=ENG))
    o.append(text(nx, ny + 1.75 * k_ + 2.3 * k_, "straight side on CF, slope to the right", 1.75 * k_, fill=GREY))
    o.append(text(nx, ny + 1.75 * k_ + 4.6 * k_, "定位缺口：直边对前中，斜边朝右", 1.6 * k_, zh=True, fill=ZHC))
    # layers
    o.append(poly(tx(L["PATCH"], cx, cy, 1.0), stroke="#555555", sw=0.35, dash="4 2"))
    o.append(poly(tx(L["BASE"], cx, cy, 1.0), stroke=GREY, sw=0.2, dash="0.35 0.9", join="round"))
    o.append(poly(tx(L["CUT_JAG"], cx, cy, 1.0), stroke=CUT_COL, sw=0.22))
    if "STITCH_FOLLOW" in L:
        o.append(poly(tx(L["STITCH_FOLLOW"], cx, cy, 1.0), stroke=INK, sw=0.3, dash="3 1.2 0.6 1.2"))
    o.append(poly(tx(L["STITCH"], cx, cy, 1.0), stroke=INK, sw=0.5))
    # window dims (base line box = W x H)
    o.append(dim((cx - g.W / 2, cy - g.H / 2), (cx + g.W / 2, cy - g.H / 2), -17.5,
                 f"window {g.W:g} mm", ts * 0.95, gap=1.0, lab_shift=-0.22 * g.W))
    o.append(dim((cx - g.W / 2, cy + g.H / 2), (cx - g.W / 2, cy - g.H / 2), -17.5,
                 f"window {g.H:g} mm", ts * 0.95, gap=1.0))
    # labels in the right wedge, leaders to the nearest point of each line on the upper-right arm. Where STITCH and
    # STITCH_FOLLOW coincide the dot would be ambiguous: each of the two lines is picked where it is >= 2 mm from
    # the other (STITCH_FOLLOW: where it steps in behind a tooth).
    specs = [("CUT_JAG", "剪口线（只剪米白）", L["CUT_JAG"], None),
             ("STITCH", "车线", L["STITCH"], L.get("STITCH_FOLLOW")),
             ("PATCH", "底布裁剪线", L["PATCH"], None)]
    if "STITCH_FOLLOW" in L:
        specs.insert(1, ("STITCH_FOLLOW", "B件车线", L["STITCH_FOLLOW"], L["STITCH"]))
    step = ts * 3.0
    y0 = -30.0 if len(specs) > 3 else -27.0
    # label column far enough right that the top label clears the upper-right arm's PATCH line
    lx = max(0.33 * g.W, (abs(y0) + ts + 2.0 + (g.HC + STITCH_OFF + PATCH_OFF) / math.cos(th)) / math.tan(th))
    order = list(reversed(specs))
    lys = {sp_[0]: y0 + i * step for i, sp_ in enumerate(order)}
    d_ur = (math.cos(phis[3]), math.sin(phis[3]))          # upper-right arm direction

    def t_(p):
        return dot(p, d_ur)
    dots = {}
    # Dots are ordered along the arm like the labels (upper label = further out the arm) so leaders never cross.
    # STITCH_FOLLOW first: nearest its label where the dash-dot line is >= 3 mm inside STITCH (a clear step-in
    # behind a tooth); STITCH then where STITCH_FOLLOW is >= 3 mm away, >= 6 mm further out along the arm.
    seq = sorted(order, key=lambda z: {"STITCH_FOLLOW": 0, "STITCH": 1, "CUT_JAG": 2, "PATCH": 3}[z[0]])
    for en, zh, pts, avoid in seq:
        ly = lys[en]
        cand = [p for p in pts if p[0] > 0 and p[1] < -6.0]
        if avoid is not None:
            AR = LinearRing(avoid)
            cand = [p for p in cand if AR.distance(Point(p)) >= 3.0]
        if en == "STITCH" and "STITCH_FOLLOW" in dots:
            cand = [p for p in cand if t_(p) >= t_(dots["STITCH_FOLLOW"]) + 6.0]
        if en == "CUT_JAG" and "STITCH_FOLLOW" in dots:
            cand = [p for p in cand if t_(p) <= t_(dots["STITCH_FOLLOW"]) - 5.0]
        if en == "PATCH" and "STITCH" in dots:
            cand = [p for p in cand if t_(p) >= t_(dots["STITCH"]) + 2.0]
        p = min(cand, key=lambda q: (q[0] - lx) ** 2 + (q[1] - ly) ** 2)
        dots[en] = p
        tpl_leader_label(o, (cx + p[0], cy + p[1]), (cx + lx, cy + ly), en, zh, ts)
    # crosshair note under the X CENTRE label
    s_, h_ = bi(cx + pb[0] + 1.5, cy + ts * 1.35 + 1.4, "Crosshair: on the garment CF; X centre 27 cm below HPS "
                "(size M).", "十字线：对前中，X中心距高肩点27cm（M码）", 0.19 * g.W + 12.0,
                se=ts * 0.78, sz=ts * 0.7, gap=0.12, fill=GREY)
    o.append(s_)
    # BASE: left wedge, text right-aligned
    cutR = LinearRing(L["CUT_JAG"])
    by_ = -24.0
    bx_ = -lx
    candB = [p for p in L["BASE"] if p[0] < 0 and p[1] < -6.0
             and cutR.distance(LineString([p, (p[0] + 0.01, p[1])])) > 2.5]
    pB = min(candB, key=lambda q: (q[0] - bx_) ** 2 + (q[1] - by_) ** 2)
    o.append(line(cx + pB[0], cy + pB[1], cx + bx_, cy + by_, INK, 0.2))
    o.append(circle(cx + pB[0], cy + pB[1], 0.55, INK, None))
    o.append(text(cx + bx_ - 1.0, cy + by_ + ts * 0.35, "BASE (variant A)", ts, bold=True, anchor="end"))
    o.append(text(cx + bx_ - 1.0, cy + by_ + ts * 0.35 + ts * 1.25, "基准线（A方案）", ts * 0.85, zh=True, fill=ZHC,
                  anchor="end"))
    return o, L, pb


def template_page(g, pw, ph, page_no, cy, proto, ts, desc_en, desc_zh):
    cx = pw / 2
    m = 10.0
    o, L, pb = template_svg(g, pw, ph, page_no, cx, cy, proto, ts, m)
    # title block
    t1 = f"{STYLE}  X TEMPLATE 1:1"
    o.append(text(m, m + 5.0, t1, ts * 2.0, bold=True))
    tz = m + tw(t1, ts * 2.0, bold=True) + 2.0
    o.append(text(tz, m + 5.0, "X模板 1:1", ts * 1.4, zh=True, bold=True, fill=ZHC))
    bw = tw("PROPOSAL, not final", ts * 1.35, bold=True) + 6
    bx = pw - m - bw
    o.append(rect(bx, m - 1.0, bw, ts * 4.3, TBD_FILL, TBD_LINE, 0.4, rx=0.8))
    o.append(text(bx + bw / 2, m - 1.0 + ts * 1.75, "PROPOSAL, not final", ts * 1.35, bold=True, anchor="middle"))
    o.append(text(bx + bw / 2, m - 1.0 + ts * 3.45, "建议稿，非最终版", ts * 1.1, zh=True, bold=True, anchor="middle"))
    # version / page (small, between the title and the badge)
    vx = tz + tw("X模板 1:1", ts * 1.4, zh=True, bold=True) + 4.0
    o.append(text(vx, m + 1.6, f"{proto}. Template page {page_no} / 2.", ts * 0.78, fill=GREY))
    o.append(text(vx, m + 1.6 + ts * 1.1, f"Tech pack {VERSION} DRAFT {DATE}, page 3.", ts * 0.78, fill=GREY))
    if vx + tw(f"Tech pack {VERSION} DRAFT {DATE}, page 3.", ts * 0.78) > bx - 1.5:
        WARN.append(f"template p{page_no}: version text hits the PROPOSAL badge")
    y = m + 5.0 + ts * 2.3
    s1 = "PRINT AT 100%  /  "
    o.append(text(m, y, s1, ts * 1.25, bold=True))
    o.append(text(m + tw(s1, ts * 1.25, bold=True), y, "实际大小打印，勿缩放", ts * 1.1, zh=True, bold=True))
    y += ts * 0.9
    s_, h = bi(m, y, desc_en, desc_zh, pw - 2 * m, se=ts * 0.95, sz=ts * 0.85, gap=0.2)
    o.append(s_)
    y += h + ts * 0.5
    # face-view warning (all tooling and the embroidery program use this one orientation)
    s_, h = bi(m + 1.6, y + 1.2, FACE_WARN_EN, FACE_WARN_ZH, pw - 2 * m - 3.2, se=ts * 0.95, sz=ts * 0.88,
               bold=True, gap=0.3)
    o.append(rect(m, y, pw - 2 * m, h + 2.4, "#FBEFEA", CUT_COL, 0.5, rx=0.6))
    o.append(s_)
    top_used = y + h + 2.4
    lab_top = cy + pb[1] - 3.5 - 0.9 - 0.9 * ts * 0.95          # top of the window-width label box
    if top_used > lab_top - 0.8:
        WARN.append(f"template p{page_no}: title block {top_used:.1f} hits the window dimension {lab_top:.1f}")
    bars, bars_bottom = check_bars_tpl(pw, cx, cy, pb, ts, m)
    o.append(bars)
    # the horizontal bar must sit in the bottom wedge, clear of the lower arms' PATCH lines
    need = max(53.0, 3.0 + tw("Check both bars = 50 mm", ts * 0.85, bold=True)) + 2.0
    if wedge_halfwidth(g, -(pb[3] - 5.0)) < need:
        WARN.append(f"template p{page_no}: horizontal check bar / text hits PATCH")
    # legend
    ly = cy + pb[3] + 7.0
    wmin = BROWN_MIN[g.name]
    tipf = TIP_FREE[g.name]
    dxf_name = DXF200_NAME if g is G200 else DXF150_NAME
    r2k_name = DXF200_R2K_NAME if g is G200 else DXF150_R2K_NAME
    st_line = "STITCH_FOLLOW" if g is G150 else "STITCH"
    items = [("solid", "STITCH (solid): machine path through both layers, 4 mm outside BASE, inner corners r ≥ 3 mm. "
              "Factory digitises it (fee quoted separately).",
              "车线（实线）：穿两层，距BASE 4mm，内角半径≥3mm；工厂按此制版（制版费另报）。"),
             ("cut", f"CUT_JAG (jagged layer): cut the cream only. Teeth 3-8 mm deep (less where the arm "
              f"narrows), 5-15 mm apart, ≥ 3 mm from the stitch, staggered side to side: together ≤ 40% of the "
              f"arm width, visible brown ≥ {wmin:g} mm, never narrower than the tip. No teeth on corner arcs "
              f"(cut r ≥ 7 mm) or in the last {tipf:g} mm before each tip.",
              f"剪口线（锯齿，CUT_JAG）：只剪米白。齿深3-8mm（臂变窄处更浅），齿距5-15mm，距车线≥3mm，两侧错开："
              f"同一截面合计≤臂宽40%，可见咖啡色≥{wmin:g}mm，不窄于尖端。内角圆弧（剪口半径≥7mm）及尖端前"
              f"{tipf:g}mm不做齿。"),
             ("base", "BASE (dotted): STITCH offset 4 mm inward, r ≥ 7 mm; the B valleys sit on it. Variant A "
              "(swatch only): cut freehand 0-3 mm inside BASE.",
              "基准线BASE（点线）：车线向内4mm，半径≥7mm，B方案齿谷在此线上；A方案（仅小样）：BASE内0-3mm徒手剪。"),
             ("dash", "PATCH (dashed): brown under-patch cut line = stitch + 10 mm, r ≥ 3 mm; no trimming after "
              "sewing.", "底布裁剪线（虚线）：车线外10mm，半径≥3mm；车后不修剪。")]
    if "STITCH_FOLLOW" in L:
        items.append(("dashdot", "STITCH_FOLLOW (dash-dot, Proto B): stitch that follows the jag, ≥ 4 mm from the "
                      "cut, turns r ≥ 3 mm. Proto B sews this line, not STITCH.",
                      "B件车线（点划线）：沿锯齿，距剪口≥4mm，转角半径≥3mm；B件车此线，不车STITCH。"))
    items.append(("guide", "GUIDE + ORIENT (blue): cut guide, stitch stencil and placement template are sheets at "
                  "least this size, used face up. Cut the CF notch (straight side on CF, slope to the right); engrave "
                  f"the arrow + FACE UP / NECK. The cut guide also carries the {st_line} line"
                  + (": before tracing, check that each tooth on the guide sits where the stitch steps in."
                     if g is G150 else ", laid exactly on the sewn stitch."),
                  "GUIDE及ORIENT（蓝色）：剪口模板、画线板及定位板不小于此外框，正面朝上使用；前中上端开定位缺口"
                  "（直边对前中，斜边朝右）；刻箭头及FACE UP / NECK（正面朝上，箭头指领口）。剪口模板同时刻"
                  f"{st_line}线"
                  + ("：描线前核对模板上每个齿正对车线内折处。" if g is G150 else "，对准已车好的车线。")))
    layers = ("STITCH, BASE, CUT_JAG, PATCH" + (", STITCH_FOLLOW" if g is G150 else "")
              + ", GUIDE, ORIENT, CENTRE, CHECK, NOTES")
    items.append(("none", f"DXF: {dxf_name} (R12) + R2000 copy. Layers as named here + CENTRE, CHECK, NOTES. "
                  "Units mm; measure the 50 mm CHECK square after import. Origin = X centre, +Y = neck.",
                  "DXF：R12及R2000两版；单位mm，导入后先量50mm校准方块；原点为X中心，+Y指向领口。"))
    se_, sz_ = ts * 0.85, ts * 0.76
    gap_ = ts * 0.55
    bottom = ph - EDGE_MIN               # line boxes; edge_check() verifies the real ink
    avail = bottom - ly
    # one column when it fits, else two columns (A4 page)
    heights1 = [bi(0, 0, en, zh, pw - 2 * m - 15, se=se_, sz=sz_, gap=0.12)[1] for _, en, zh in items]
    ncol = 1 if sum(heights1) + gap_ * (len(items) - 1) <= avail else 2
    colw_ = (pw - 2 * m - 5.0 * (ncol - 1)) / ncol
    sw_ = 15.0 if ncol == 1 else 11.0          # swatch column
    if ncol == 2:
        gap_ = ts * 0.33
    hs = [bi(0, 0, en, zh, colw_ - sw_, se=se_, sz=sz_, gap=0.12)[1] for _, en, zh in items]
    split = len(items)
    if ncol == 2:
        best = None
        for sp_ in range(1, len(items)):
            hA = sum(hs[:sp_]) + gap_ * (sp_ - 1)
            hB = sum(hs[sp_:]) + gap_ * (len(items) - sp_ - 1)
            if best is None or max(hA, hB) < best[0]:
                best = (max(hA, hB), sp_)
        split = best[1]
    ly0 = ly
    ly_end = ly
    for idx, (st, en, zh) in enumerate(items):
        if idx == split:
            ly = ly0
        x0 = m + (0 if idx < split else colw_ + 5.0)
        yy = ly + ts * 0.45
        k_ = (sw_ - 3.0) / 12.0                 # swatch length scale
        if st == "solid":
            o.append(line(x0, yy, x0 + 12 * k_, yy, INK, 0.5))
        elif st == "cut":
            o.append(poly([(x0 + u * k_, yy + v) for u, v in ((0, 0), (2, 1.2), (3.5, -0.3), (6, 1.4), (8, 0),
                                                                (10, 1.0), (12, 0))],
                          stroke=CUT_COL, sw=0.22, closed=False))
        elif st == "dash":
            o.append(line(x0, yy, x0 + 12 * k_, yy, "#555555", 0.35, dash="4 2"))
        elif st == "base":
            o.append(line(x0, yy, x0 + 12 * k_, yy, GREY, 0.2, dash="0.35 0.9"))
        elif st == "dashdot":
            o.append(line(x0, yy, x0 + 12 * k_, yy, INK, 0.3, dash="3 1.2 0.6 1.2"))
        elif st == "guide":
            o.append(poly([(x0, yy + 1.6), (x0, yy - 0.6), (x0 + 5 * k_, yy - 0.6), (x0 + 5 * k_, yy + 1.4),
                           (x0 + 7 * k_, yy - 0.6), (x0 + 12 * k_, yy - 0.6), (x0 + 12 * k_, yy + 1.6)],
                          stroke=ENG, sw=0.3, closed=False, join="miter"))
        elif st == "cross":
            o.append(line(x0, yy, x0 + 12 * k_, yy, GREY, 0.25, dash="6 1.5 1 1.5"))
            o.append(line(x0 + 6 * k_, yy - 2, x0 + 6 * k_, yy + 2, GREY, 0.25))
        s_, h = bi(x0 + sw_, ly, en, zh, colw_ - sw_, se=se_, sz=sz_, gap=0.12,
                   fill=GREY if st == "none" else INK)
        o.append(s_)
        ly_end = max(ly_end, ly + h)
        ly += h + gap_
    if ly_end > bottom:
        WARN.append(f"template p{page_no}: legend overflow {ly_end:.1f} > {bottom:.1f}")
    body = "".join(o)
    return ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{pw}mm" height="{ph}mm" viewBox="0 0 {pw} {ph}">' + body + "</svg>"), L


def write_dxf(path, g, L):
    """Plain ASCII DXF, R12 (AC1009): closed POLYLINE entities, units mm, origin = X centre, +Y up (to the neck)."""
    lay, polys, lines_, texts = dxf_content(g, L)
    colors = DXF_COLORS
    allp = ([p for v in polys.values() for p in v] + [p for ln in lines_ for p in (ln[1:3], ln[3:5])]
            + [(t_[1], t_[2]) for t_ in texts] + [(t_[1] + 0.6 * t_[3] * len(t_[4]), t_[2] + t_[3]) for t_ in texts])
    xmin, ymin = min(p[0] for p in allp) - 5, min(p[1] for p in allp) - 5
    xmax, ymax = max(p[0] for p in allp) + 5, max(p[1] for p in allp) + 5
    out = []

    def w(code, val):
        out.append(f"{code:>3}")
        out.append(str(val))

    def f(v):
        return f"{v:.4f}"
    w(0, "SECTION"); w(2, "HEADER")
    w(9, "$ACADVER"); w(1, "AC1009")
    w(9, "$INSBASE"); w(10, f(0)); w(20, f(0)); w(30, f(0))
    w(9, "$EXTMIN"); w(10, f(xmin)); w(20, f(ymin)); w(30, f(0))
    w(9, "$EXTMAX"); w(10, f(xmax)); w(20, f(ymax)); w(30, f(0))
    w(9, "$INSUNITS"); w(70, 4)
    w(9, "$MEASUREMENT"); w(70, 1)
    w(0, "ENDSEC")
    w(0, "SECTION"); w(2, "TABLES")
    w(0, "TABLE"); w(2, "LTYPE"); w(70, 1)
    w(0, "LTYPE"); w(2, "CONTINUOUS"); w(70, 0); w(3, "Solid line"); w(72, 65); w(73, 0); w(40, f(0))
    w(0, "ENDTAB")
    w(0, "TABLE"); w(2, "LAYER"); w(70, len(lay) + 1)
    for name, col in [("0", 7)] + [(n, colors[n]) for n in lay]:
        w(0, "LAYER"); w(2, name); w(70, 0); w(62, col); w(6, "CONTINUOUS")
    w(0, "ENDTAB")
    w(0, "TABLE"); w(2, "STYLE"); w(70, 1)
    w(0, "STYLE"); w(2, "STANDARD"); w(70, 0); w(40, f(0)); w(41, f(1)); w(50, f(0)); w(71, 0); w(42, f(2.5))
    w(3, "txt"); w(4, "")
    w(0, "ENDTAB")
    w(0, "ENDSEC")
    w(0, "SECTION"); w(2, "BLOCKS"); w(0, "ENDSEC")
    w(0, "SECTION"); w(2, "ENTITIES")
    for name, pts in polys.items():
        w(0, "POLYLINE"); w(8, name); w(66, 1); w(10, f(0)); w(20, f(0)); w(30, f(0)); w(70, 1)
        for x, y in pts:
            w(0, "VERTEX"); w(8, name); w(10, f(x)); w(20, f(y)); w(30, f(0))
        w(0, "SEQEND"); w(8, name)
    for (layer, x1, y1, x2, y2) in lines_:
        w(0, "LINE"); w(8, layer); w(10, f(x1)); w(20, f(y1)); w(30, f(0)); w(11, f(x2)); w(21, f(y2)); w(31, f(0))
    for (layer, x, y, hgt, s) in texts:
        w(0, "TEXT"); w(8, layer); w(10, f(x)); w(20, f(y)); w(30, f(0)); w(40, f(hgt)); w(1, s)
    w(0, "ENDSEC")
    w(0, "EOF")
    txt = "\n".join(out) + "\n"
    txt.encode("ascii")
    with open(path, "w", encoding="ascii", newline="\r\n") as fh:
        fh.write(txt)
    return {k: len(v) for k, v in polys.items()}


DXF_COLORS = {"STITCH": 7, "BASE": 4, "CUT_JAG": 1, "PATCH": 5, "STITCH_FOLLOW": 6, "GUIDE": 150, "ORIENT": 150,
              "CENTRE": 8, "CHECK": 30, "NOTES": 3}


def dxf_content(g, L):
    """Shared DXF content (R12 and R2000 writers). Coordinates in mm, +Y towards the neck.
    Returns (layer order, closed polylines {layer: pts}, lines [(layer, x1, y1, x2, y2)], texts [(layer, x, y, h, s)])."""
    lay = (["STITCH", "BASE", "CUT_JAG", "PATCH"] + (["STITCH_FOLLOW"] if "STITCH_FOLLOW" in L else [])
           + ["GUIDE", "ORIENT", "CENTRE", "CHECK", "NOTES"])
    tol = {"STITCH": 0.02, "BASE": 0.02, "PATCH": 0.02, "CUT_JAG": 0.04, "STITCH_FOLLOW": 0.03, "GUIDE": 0.0}
    polys = {}
    for name in lay:
        if name in L:
            ring = LinearRing([(x, -y) for x, y in L[name]]).simplify(tol[name], preserve_topology=True)
            polys[name] = list(ring.coords)[:-1]
    OL = orient_layout(g, 3.0 if g is G200 else 2.45)
    polys["ORIENT"] = [(x, -y) for x, y in OL["arrow"]]
    ext_x = g.W / 2 + 24
    ext_y = g.H / 2 + 24
    # 50 x 50 mm check square, top-left, clear of the X and the patch
    sx0, sy0 = -ext_x, ext_y + 8.0
    sq = [(sx0, sy0), (sx0 + CHECK_SQ, sy0), (sx0 + CHECK_SQ, sy0 + CHECK_SQ), (sx0, sy0 + CHECK_SQ)]
    polys["CHECK"] = sq
    lines_ = [("CENTRE", 0, -ext_y, 0, ext_y), ("CENTRE", -ext_x, 0, ext_x, 0),
              ("CHECK", sx0, sy0, sx0 + CHECK_SQ, sy0 + CHECK_SQ)]
    texts = [("CHECK", sx0 + 3.0, sy0 + CHECK_SQ / 2 + 4.0, 3.0, "CHECK 50 X 50 MM"),
             ("CHECK", sx0 + 3.0, sy0 + CHECK_SQ / 2 - 2.0, 3.0, "MEASURE AFTER IMPORT")]
    for xt_, yb, sz, s_, kind, bold in OL["text"]:
        if kind == "eng":
            texts.append(("ORIENT", xt_, -yb, round(0.72 * sz, 2), s_))
    notes = [f"{STYLE} X TEMPLATE {g.name} MM, PROPOSAL, NOT FINAL. {VERSION} {DATE}",
             "FACE VIEW (OUTSIDE). DO NOT MIRROR OR ROTATE. CUT GUIDE, STITCH STENCIL AND EMBROIDERY PROGRAM MUST USE "
             "THE SAME ORIENTATION.",
             "UNITS MM. CHECK SQUARE = 50 X 50 MM (LAYER CHECK). ORIGIN = X CENTRE ON CF. +Y = TOWARDS NECK.",
             "GUIDE = MIN. SHEET FOR CUT GUIDE, STITCH STENCIL AND PLACEMENT TEMPLATE, WITH ASYMMETRIC REGISTRATION "
             "NOTCH AT CF TOP (STRAIGHT SIDE ON CF, SLOPE TO +X).",
             "ORIENT = ENGRAVE ARROW + FACE UP / NECK ON ALL TOOLING. CUT GUIDE ALSO CARRIES THE "
             + ("STITCH_FOLLOW LINE: EACH TOOTH MUST SIT WHERE THE STITCH STEPS IN." if "STITCH_FOLLOW" in L
                else "STITCH LINE, TO LAY IT ON THE SEWN STITCH."),
             f"CUT_JAG TEETH 3-8 MM DEEP (LESS WHERE THE ARM NARROWS), 5-15 MM APART, STAGGERED; BOTH SIDES TOGETHER "
             f"<= 40% OF ARM WIDTH; VISIBLE BROWN >= {BROWN_MIN[g.name]:g} MM; NO TEETH IN THE LAST "
             f"{TIP_FREE[g.name]:g} MM BEFORE EACH TIP.",
             "STITCH = MACHINE PATH. CUT_JAG = CUT CREAM ONLY (EDGE B, BOTH PROTOS). PATCH = UNDER-PATCH CUT (STITCH + 10).",
             "BASE = STITCH OFFSET 4 MM INWARD, R >= 7. EDGE A: CUT FREEHAND 0-3 MM INSIDE BASE. B VALLEYS SIT ON BASE."]
    if "STITCH_FOLLOW" in L:
        notes.append("STITCH_FOLLOW = PROTO B STITCH, FOLLOWS THE JAG (>= 4 MM FROM CUT).")
        notes.append("150 MM FILE: OUTLINE BASED ON THE 200 MM X, TIPS KEPT AT 10 MM. USE THIS FILE; DO NOT SCALE "
                     "THE 200 MM FILE.")
    for i, s in enumerate(notes):
        texts.append(("NOTES", -ext_x, -ext_y - 8 - i * 5, 3.0, s))
    return lay, {k: polys[k] for k in lay if k in polys}, lines_, texts


def write_dxf_r2000(path, g, L):
    """Same content as write_dxf, as an R2000 (AC1015) file with LWPOLYLINE and $INSUNITS = 4 (mm)."""
    import ezdxf
    lay, polys, lines_, texts = dxf_content(g, L)
    doc = ezdxf.new("R2000", setup=False, units=4)
    doc.header["$MEASUREMENT"] = 1
    for name in lay:
        doc.layers.add(name, color=DXF_COLORS[name])
    msp = doc.modelspace()
    for name, pts in polys.items():
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": name})
    for (layer, x1, y1, x2, y2) in lines_:
        msp.add_line((x1, y1), (x2, y2), dxfattribs={"layer": layer})
    for (layer, x, y, hgt, s) in texts:
        msp.add_text(s, height=hgt, dxfattribs={"layer": layer, "insert": (x, y)})
    doc.saveas(path)
    return {k: len(v) for k, v in polys.items()}


def audit_dxf(path, g):
    """Read back a DXF: layers present, closed polylines, CHECK square 50 x 50, BASE 4 mm inside STITCH,
    window size, cut >= 3 mm from the stitch. Raises on failure."""
    import ezdxf
    from ezdxf import recover
    doc, auditor = recover.readfile(path)
    if auditor.has_errors:
        raise SystemExit(f"{os.path.basename(path)}: DXF audit errors {auditor.errors}")
    msp = doc.modelspace()
    rings = {}
    for e in msp:
        if e.dxftype() in ("POLYLINE", "LWPOLYLINE"):
            pts = [tuple(v)[:2] for v in (e.points() if e.dxftype() == "POLYLINE" else e.get_points("xy"))]
            if not e.is_closed:
                raise SystemExit(f"{os.path.basename(path)}: open polyline on {e.dxf.layer}")
            rings[e.dxf.layer] = pts
    need = ["STITCH", "BASE", "CUT_JAG", "PATCH", "CHECK", "GUIDE", "ORIENT"] + (["STITCH_FOLLOW"] if g is G150 else [])
    for n_ in need:
        if n_ not in rings:
            raise SystemExit(f"{os.path.basename(path)}: layer {n_} missing")
    cb = bbox(rings["CHECK"])
    if abs(cb[2] - cb[0] - CHECK_SQ) > 1e-3 or abs(cb[3] - cb[1] - CHECK_SQ) > 1e-3:
        raise SystemExit(f"{os.path.basename(path)}: check square is not 50 x 50")
    S_, B_, C_ = LinearRing(rings["STITCH"]), LinearRing(rings["BASE"]), LinearRing(rings["CUT_JAG"])
    bb_ = bbox(rings["BASE"])
    dbs = max(S_.distance(Point(p)) for p in rings["BASE"])
    res = (f"{os.path.basename(path)}: ${doc.dxfversion} INSUNITS={doc.header.get('$INSUNITS')}, window "
           f"{bb_[2] - bb_[0]:.1f} x {bb_[3] - bb_[1]:.1f}, BASE-STITCH {B_.distance(S_):.2f}-{dbs:.2f}, cut-stitch "
           f"min {C_.distance(S_):.2f}, check {cb[2] - cb[0]:.1f} x {cb[3] - cb[1]:.1f}")
    if abs(bb_[2] - bb_[0] - g.W) > 0.2 or abs(bb_[3] - bb_[1] - g.H) > 0.2:
        raise SystemExit(res + " : window size wrong")
    if C_.distance(S_) < 3.0 or not (3.9 < B_.distance(S_) <= 4.01):
        raise SystemExit(res + " : offsets wrong")
    Gp = Polygon(rings["GUIDE"])
    Gm = Polygon([(-x, y) for x, y in rings["GUIDE"]])
    Gr = Polygon([(-x, -y) for x, y in rings["GUIDE"]])
    if not Gp.contains(Polygon(rings["PATCH"])):
        raise SystemExit(res + " : GUIDE sheet does not contain PATCH")
    if Gp.symmetric_difference(Gm).area < 20.0 or Gp.symmetric_difference(Gr).area < 20.0:
        raise SystemExit(res + " : GUIDE notch does not make the sheet orientation-proof")
    tops = [t_ for t_ in msp if t_.dxftype() == "TEXT" and t_.dxf.layer == "ORIENT"]
    if not any("FACE UP / NECK" in t_.dxf.text for t_ in tops):
        raise SystemExit(res + " : ORIENT text missing")
    notes_ = " ".join(t_.dxf.text for t_ in msp if t_.dxftype() == "TEXT" and t_.dxf.layer == "NOTES")
    if "DO NOT MIRROR OR ROTATE" not in notes_:
        raise SystemExit(res + " : face-view note missing")
    print("DXF audit ok:", res)


def build_template():
    pages = []
    svg1, L1 = template_page(
        G200, 297.0, 420.0, 1, 204.0, "Proto A", 3.0,
        f"Proto A: window 200 x 210 mm (base cut line), stitch box 208 x 218 mm, patch box 228 x 238 mm. Arm 25 mm "
        f"at BASE, visible brown ≥ {BROWN_MIN['200']:g} mm, round tips 11 mm (10-12). Same X for all sizes. Proto A: "
        f"edge B cut on CUT_JAG, smooth stitch on STITCH.",
        f"A件：开口200 x 210mm，车线外框208 x 218mm，底布外框228 x 238mm；BASE处臂宽25mm，可见咖啡色≥"
        f"{BROWN_MIN['200']:g}mm，尖端11mm圆头（10-12mm）；全码相同。A件按CUT_JAG做B边，沿STITCH平顺车线。")
    sb = bbox(stitch_outline(G150))
    pbb = bbox(patch_outline(G150))
    svg2, L2 = template_page(
        G150, 210.0, 297.0, 2, 142.0, "Proto B", 2.45,
        f"Proto B: window 150 x 157.5 mm, stitch box {sb[2] - sb[0]:.0f} x {sb[3] - sb[1]:.1f} mm, patch box "
        f"{pbb[2] - pbb[0]:.0f} x {pbb[3] - pbb[1]:.1f} mm, arm 19 mm at BASE, visible brown ≥ "
        f"{BROWN_MIN['150']:g} mm. Outline based on the 200 mm X, tips kept at 10 mm. Use this 150 mm file; do not "
        f"scale the 200 mm file. Edge B on CUT_JAG, stitch on STITCH_FOLLOW.",
        f"B件：开口150 x 157.5mm，BASE处臂宽19mm，可见咖啡色≥{BROWN_MIN['150']:g}mm。以200mm为基础，尖端保持10mm；"
        f"须用150mm文件，不可由200mm文件缩放。按CUT_JAG做B边，车STITCH_FOLLOW。")
    writer = PdfWriter()
    for i, svg in enumerate((svg1, svg2), 1):
        check_text(svg, f"template {i}")
        with open(os.path.join(SVG_DIR, f"template-p{i}.svg"), "w", encoding="utf-8") as fh:
            fh.write(svg)
        pdf_bytes = cairosvg.svg2pdf(bytestring=svg.encode("utf-8"))
        for pg in PdfReader(io.BytesIO(pdf_bytes)).pages:
            writer.add_page(pg)
    writer.add_metadata({"/Title": f"{STYLE} X template 1:1 PROPOSAL {VERSION} {DATE}", "/Author": "Cultsiders"})
    with open(TPL_PDF, "wb") as fh:
        writer.write(fh)
    n1 = write_dxf(DXF200, G200, L1)
    n2 = write_dxf(DXF150, G150, L2)
    write_dxf_r2000(os.path.join(HERE, DXF200_R2K_NAME), G200, L1)
    write_dxf_r2000(os.path.join(HERE, DXF150_R2K_NAME), G150, L2)
    print("DXF vertices 200:", n1, " 150:", n2)
    for pth, g_ in ((DXF200, G200), (DXF150, G150), (os.path.join(HERE, DXF200_R2K_NAME), G200),
                    (os.path.join(HERE, DXF150_R2K_NAME), G150)):
        audit_dxf(pth, g_)


# ================================================================== CJK FONT (TrueType copy)
def _cjk_charset():
    """GB2312 (all rows) + ASCII/Latin-1/punctuation/fullwidth + every character in this source file."""
    cs = set(range(0x20, 0x7F)) | set(range(0xA0, 0x180)) | set(range(0x2000, 0x2070))
    cs |= set(range(0x2100, 0x2300)) | set(range(0x3000, 0x3040)) | set(range(0xFF00, 0xFFF0))
    for hi in list(range(0xA1, 0xAA)) + list(range(0xB0, 0xF8)):
        for lo in range(0xA1, 0xFF):
            try:
                cs.add(ord(bytes([hi, lo]).decode("gb2312")))
            except UnicodeDecodeError:
                pass
    with open(os.path.abspath(__file__), encoding="utf-8") as fh:
        cs |= {ord(c) for c in fh.read() if ord(c) >= 0x20}
    return cs


def build_cjk_fonts():
    """Write fonts/NotoSansSCTT-{Regular,Bold}.ttf: Noto Sans CJK SC (OFL 1.1), subset, CFF outlines
    converted to TrueType quadratics (cu2qu, max error 1 unit of 1000), renamed family FAM_ZH.
    cairo then embeds CIDFontType2 (glyf) subsets instead of its own CFF subsets."""
    from fontTools import subset as ft_subset
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTFont, newTable
    os.makedirs(FONT_DIR, exist_ok=True)
    cs = _cjk_charset()
    stamp = os.path.join(FONT_DIR, "charset.txt")
    want = "".join(chr(c) for c in sorted(cs))
    files = {b: os.path.join(FONT_DIR, f"NotoSansSCTT-{'Bold' if b else 'Regular'}.ttf") for b in (False, True)}
    fresh = (os.path.exists(stamp) and all(os.path.exists(f) for f in files.values())
             and open(stamp, encoding="utf-8").read() == want)
    if not fresh:
        for bold, out in files.items():
            f = TTFont(ZH_SRC[bold], fontNumber=2)
            o = ft_subset.Options()
            o.hinting = False
            o.desubroutinize = True
            o.notdef_outline = True
            o.layout_features = []
            o.name_IDs = ["*"]
            o.drop_tables += ["VORG", "vhea", "vmtx", "BASE", "GPOS", "GSUB", "GDEF"]
            sub = ft_subset.Subsetter(o)
            sub.populate(unicodes=cs)
            sub.subset(f)
            order = f.getGlyphOrder()
            gs = f.getGlyphSet()
            glyf = newTable("glyf")
            glyf.glyphOrder = order
            glyf.glyphs = {}
            for gname in order:
                pen = TTGlyphPen(None)
                gs[gname].draw(Cu2QuPen(pen, 1.0, reverse_direction=True))
                glyf.glyphs[gname] = pen.glyph()
            f["glyf"] = glyf
            f["loca"] = newTable("loca")
            del f["CFF "]
            mx = f["maxp"]
            mx.tableVersion = 0x00010000
            for k in ("maxZones", "maxTwilightPoints", "maxStorage", "maxFunctionDefs", "maxInstructionDefs",
                      "maxStackElements", "maxSizeOfInstructions", "maxComponentElements", "maxComponentDepth"):
                setattr(mx, k, 0)
            mx.maxZones = 1
            f["head"].glyphDataFormat = 0
            f["post"].formatType = 3.0
            f.sfntVersion = "\x00\x01\x00\x00"
            style = "Bold" if bold else "Regular"
            nm = f["name"]
            nm.names = [r for r in nm.names if r.nameID in (0, 7, 8, 9, 10, 11, 12, 13, 14)]
            for nid, val in ((1, FAM_ZH), (2, style), (3, f"NotoSansSCTT-{style};cultsiders-build"),
                             (4, f"{FAM_ZH} {style}"), (5, "Version 2.004; TrueType outlines (cu2qu)"),
                             (6, f"NotoSansSCTT-{style}")):
                nm.setName(val, nid, 3, 1, 0x409)
                nm.setName(val, nid, 1, 0, 0)
            f.save(out)
        with open(stamp, "w", encoding="utf-8") as fh:
            fh.write(want)
    conf = os.environ["FONTCONFIG_FILE"]
    with open(conf, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n<fontconfig>\n'
                 '  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>\n'
                 f'  <dir>{FONT_DIR}</dir>\n  <cachedir>{os.path.join(FONT_DIR, "cache")}</cachedir>\n'
                 '</fontconfig>\n')
    return cs


def verify_pdf(path, cs=None, scale=6.0, thr=40):
    """Check the final PDF (not the SVG previews): (1) every embedded font is TrueType (FontFile2) and one of
    Liberation Sans / FAM_ZH, no CFF (FontFile3); (2) every non-space character of the text layer has a real
    glyph box and visible ink when pdfium renders the page. Returns (chars checked, font names)."""
    names = set()
    for page in PdfReader(path).pages:
        fonts = page.get("/Resources", {}).get("/Font", {})
        for fref in fonts.values():
            fo = fref.get_object()
            base = str(fo.get("/BaseFont"))
            desc = [fo] + [d.get_object() for d in fo.get("/DescendantFonts", [])]
            for d in desc:
                fd = d.get("/FontDescriptor")
                if fd is None:
                    continue
                fd = fd.get_object()
                if "/FontFile3" in fd or "/FontFile" in fd:
                    raise SystemExit(f"{os.path.basename(path)}: font {base} is not embedded as TrueType")
                if "/FontFile2" not in fd:
                    raise SystemExit(f"{os.path.basename(path)}: font {base} not embedded")
            names.add(base.split("+")[-1])
    for nm_ in names:
        if not (nm_.startswith("LiberationSans") or nm_.startswith("NotoSansSCTT")):
            raise SystemExit(f"{os.path.basename(path)}: unexpected font {nm_} (fontconfig fallback?)")
    pdf = pdfium.PdfDocument(path)
    total, bad = 0, []
    for pi in range(len(pdf)):
        page = pdf[pi]
        W, H = page.get_size()
        img = page.render(scale=scale, grayscale=True).to_numpy()
        if img.ndim == 3:
            img = img[..., 0]
        tp = page.get_textpage()
        for ci in range(tp.count_chars()):
            ch = tp.get_text_range(ci, 1)
            if not ch or ch.isspace():
                continue
            total += 1
            if cs is not None and ord(ch) not in cs:
                bad.append((pi + 1, ch, "not in font charset"))
                continue
            l, b, r, t = tp.get_charbox(ci, loose=False)
            if r - l < 0.05 or t - b < 0.05:
                bad.append((pi + 1, ch, "empty glyph box: " + tp.get_text_range(max(ci - 8, 0), 17)))
                continue
            x0, x1 = max(int(l * scale) - 1, 0), min(int(r * scale) + 2, img.shape[1])
            y0, y1 = max(int((H - t) * scale) - 1, 0), min(int((H - b) * scale) + 2, img.shape[0])
            sub = img[y0:y1, x0:x1]
            if sub.size == 0 or int(sub.max()) - int(sub.min()) < thr:
                bad.append((pi + 1, ch, "no ink: " + tp.get_text_range(max(ci - 8, 0), 17)))
    print(f"verify {os.path.basename(path)}: {total} characters checked for ink, {len(bad)} failures; "
          f"fonts {sorted(names)}")
    if bad:
        for b_ in bad[:40]:
            print("   p%d %r %s" % b_)
        raise SystemExit("PDF glyph check failed")
    return total, names


def edge_check(path, edge=EDGE_MIN, scale=4.0):
    """Render every page of the final PDF and fail if any ink lies closer than 'edge' mm to a page edge
    (printers with an unprintable margin would clip it). Returns the smallest clearance per page (mm)."""
    pdf = pdfium.PdfDocument(path)
    out = []
    for pi in range(len(pdf)):
        page = pdf[pi]
        img = page.render(scale=scale, grayscale=True).to_numpy()
        if img.ndim == 3:
            img = img[..., 0]
        ink = img < 235
        rows, cols = np.where(ink.any(axis=1))[0], np.where(ink.any(axis=0))[0]
        pxmm = scale * 72.0 / 25.4
        H, W = img.shape
        clr = min(rows[0], H - 1 - rows[-1], cols[0], W - 1 - cols[-1]) / pxmm
        out.append(clr)
        if clr < edge - 0.15:
            raise SystemExit(f"{os.path.basename(path)} page {pi + 1}: ink {clr:.2f} mm from the page edge "
                             f"(min {edge:g} mm)")
    print(f"edge check {os.path.basename(path)}: min clearance per page " + ", ".join(f"{c:.1f}" for c in out) + " mm")
    return out


def pdf_previews(path, outs, width):
    pdf = pdfium.PdfDocument(path)
    if len(pdf) != len(outs):
        raise SystemExit(f"{os.path.basename(path)}: {len(pdf)} pages, expected {len(outs)}")
    for i, out in enumerate(outs):
        page = pdf[i]
        w_pt = page.get_size()[0]
        big = page.render(scale=2 * width / w_pt).to_pil().convert("RGB")
        im = big.resize((width, round(width * big.size[1] / big.size[0])), Image.LANCZOS)
        im.save(out, optimize=True)


# ================================================================== BUILD
FORBIDDEN = ["canon", "luffy", "one piece", "nike", "naruto", "demon slayer"]


def check_text(svg, n):
    for bad, name in ((chr(0x2014), "em dash"), (chr(0x2013), "en dash"), (chr(0x2015), "horizontal bar"),
                      (chr(0x2012), "figure dash"), (chr(0x2E3A), "two-em dash")):
        if bad in svg:
            raise SystemExit(f"page {n}: contains {name}")
    low = html.unescape(svg).lower()
    for wd in FORBIDDEN:
        if wd in low:
            raise SystemExit(f"page {n}: contains forbidden word '{wd}'")
    for wd in ("小号", "大号"):
        if wd in svg:
            raise SystemExit(f"page {n}: contains {wd} (use only for garment sizes)")


CUT_STATS = {}


def geometry_checks():
    for g in (G200, G150):
        C_ = LinearRing(x_cut_B(g))
        S_ = LinearRing(stitch_outline(g))
        P_ = LinearRing(patch_outline(g))
        dcs = C_.distance(S_)
        dps = P_.distance(S_)
        sb = bbox(stitch_outline(g))
        pb = bbox(patch_outline(g))
        print(f"X {g.name}: tip {2 * g.HT:.1f} mm, arm {2 * g.HC:.2f} mm, stitch box {sb[2] - sb[0]:.1f} x "
              f"{sb[3] - sb[1]:.1f}, patch box {pb[2] - pb[0]:.1f} x {pb[3] - pb[1]:.1f}, cut-to-stitch min "
              f"{dcs:.2f}, patch-to-stitch min {dps:.2f}, stitch length {S_.length:.0f} mm")
        if dcs < 3.0:
            raise SystemExit(f"X {g.name}: cut closer than 3 mm to the stitch ({dcs:.2f})")
        B_ = LinearRing(base_outline(g))
        if not 3.9 < B_.distance(S_) <= 4.01:
            raise SystemExit(f"X {g.name}: BASE is not 4 mm inside STITCH ({B_.distance(S_):.2f})")
        cs_ = cut_stats(g)
        CUT_STATS[g.name] = cs_
        print(f"   CUT_JAG: {cs_['n']} teeth {cs_['dmin']:.1f}-{cs_['dmax']:.1f} mm ({cs_['n_shallow']} under 3 mm, all "
              f"where the arm is <= {cs_['shallow_wmax']:.1f} mm wide); combined depth max {100 * cs_['comb']:.1f}% of "
              f"the arm; narrowest brown centre to end of teeth {cs_['arm_min']:.2f} mm, centre to tips "
              f"{cs_['tip_min']:.2f} mm (tip {2 * g.HT:g})")
        if cs_["comb"] > COMB_MAX + 1e-3:
            raise SystemExit(f"X {g.name}: teeth take {100 * cs_['comb']:.1f}% of the arm (max {100 * COMB_MAX:g}%)")
        if cs_["arm_min"] < BROWN_MIN[g.name] or cs_["tip_min"] < 2 * g.HT - 0.1:
            raise SystemExit(f"X {g.name}: visible brown too narrow")
        if cs_["n_shallow"] and cs_["shallow_wmax"] > 2 * g.HC - 0.5:
            raise SystemExit(f"X {g.name}: tooth under 3 mm outside the narrowing part of the arm")
        if g is G150:
            F_ = LinearRing(stitch_follow(g))
            print(f"   STITCH_FOLLOW: min distance to cut {F_.distance(C_):.2f} mm, length {F_.length:.0f} mm")
            if F_.distance(C_) < 3.0:
                raise SystemExit("STITCH_FOLLOW closer than 3 mm to the cut")


def main():
    os.makedirs(SVG_DIR, exist_ok=True)
    cs = build_cjk_fonts()
    geometry_checks()
    pages = [page1(), page2(), page3(), page4(), page5(), page6(), page7(), page8()]
    assert len(pages) == N_PAGES
    writer = PdfWriter()
    for i, svg in enumerate(pages, 1):
        check_text(svg, i)
        with open(os.path.join(SVG_DIR, f"page-{i:02d}.svg"), "w", encoding="utf-8") as fh:
            fh.write(svg)
        pdf_bytes = cairosvg.svg2pdf(bytestring=svg.encode("utf-8"))
        for pg in PdfReader(io.BytesIO(pdf_bytes)).pages:
            writer.add_page(pg)
    writer.add_metadata({"/Title": f"{STYLE} tech pack {VERSION} DRAFT {DATE}", "/Author": "Cultsiders"})
    with open(OUT_PDF, "wb") as fh:
        writer.write(fh)
    print(f"wrote {OUT_PDF}")
    build_template()
    print(f"wrote {TPL_PDF}, {DXF200}, {DXF150}")
    verify_pdf(OUT_PDF, cs)
    verify_pdf(TPL_PDF, cs)
    edge_check(OUT_PDF)
    edge_check(TPL_PDF)
    # previews are rendered from the FINAL PDFs (pdfium), not from the SVGs, so they show exactly what prints
    pdf_previews(OUT_PDF, [os.path.join(HERE, f"page-{i:02d}.png") for i in range(1, N_PAGES + 1)], 1600)
    pdf_previews(TPL_PDF, [os.path.join(HERE, f"template-p{i}.png") for i in (1, 2)], 1400)
    for w_ in WARN:
        print("WARN:", w_)


if __name__ == "__main__":
    main()
