"""4 in X proposal: size comparison flats (S / M / XL, same X) and a 1:1 home-test template.

Reuses the drawing helpers from build_techpack.py. Writes into ./mockup-4in/.
Run: python3 mockup_4in.py
"""
import math
import os

import cairosvg
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject
from shapely.geometry import Polygon

import build_techpack as bt

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "mockup-4in")

# 4 in window: 101.6 x 106.7 mm (same 1:1.05 ratio as the 200 / 150 mm files),
# 15 mm arm opening so brown still shows after the jersey edge rolls 2-4 mm per side, 12 mm tips.
G100 = bt.XGeo("100", 101.6, 106.7, 7.5, 6.0)
R_CUT = 5.0        # cut line inner corners
STITCH_OFF = 3.0   # cut to stitch (stitch inner corner r = 2)
PATCH_OFF = 10.0   # stitch to under-patch edge

# Garment sizes in inches (factory chart, half chest corrected). Armhole depth and neck drop are drawing assumptions.
SIZES = {
    "S": dict(length=25, half_chest=24.75, shoulder=19, sleeve=10.625, collar=6.5, half_cuff=8.125, armhole=26.0),
    "M": dict(length=26, half_chest=25.75, shoulder=20, sleeve=11.0, collar=6.75, half_cuff=8.5, armhole=27.0),
    "L": dict(length=27, half_chest=26.75, shoulder=21, sleeve=11.375, collar=7.0, half_cuff=8.875, armhole=28.0),
    "XL": dict(length=28, half_chest=27.75, shoulder=22, sleeve=11.75, collar=7.25, half_cuff=9.0, armhole=29.0),
}
# X centre below the HPS line, cm: top of the X about 3 in below the front neck seam on M; +1 cm per size.
X_CY = {"S": 22.0, "M": 23.0, "L": 24.0, "XL": 25.0}


def set_size(sz):
    d = SIZES[sz]
    bt.NECK_HW = d["collar"] * 2.54 / 2
    bt.SP = (d["shoulder"] * 2.54 / 2, 2.5)
    bt.SLV_L = d["sleeve"] * 2.54
    bt.CUFF = d["half_cuff"] * 2.54
    bt.BODY_HW = d["half_chest"] * 2.54 / 2
    bt.UA = (bt.BODY_HW, d["armhole"])
    bt.LEN = d["length"] * 2.54


def x_lines():
    cut = bt.x_outline(0.0, R_CUT, g=G100, n_arc=16, n_side=40)
    stitch = bt.x_outline(STITCH_OFF, R_CUT, g=G100, n_arc=16, n_side=40)
    patch = list(Polygon(stitch).buffer(PATCH_OFF, join_style=1, quad_segs=12).exterior.coords)
    return cut, stitch, patch


def comparison():
    """Three flats at the same scale, same 4 in X, to show the X does not need to grade."""
    s = 0.8                      # page mm per garment cm
    W, H = 330.0, 106.0
    parts = [f'<rect width="{W}" height="{H}" fill="#FAFAF7"/>']
    cut, stitch, _ = x_lines()
    for i, sz in enumerate(("S", "M", "XL")):
        set_size(sz)
        cx, hy = 55 + i * 110, 16
        svg, P = bt.draw_tee(cx, hy, s, view="front", show_x=False, detail=False, lw=0.35)
        parts.append(svg)
        k = s / 10.0
        ox, oy = P(0, X_CY[sz])
        parts.append(bt.poly(bt.tx(cut, ox, oy, k), fill=bt.BROWN, stroke=bt.INK, sw=0.08))
        parts.append(bt.poly(bt.tx(stitch, ox, oy, k), stroke=bt.INK, sw=0.08,
                             dash="0.6 0.45"))
        chest_in = SIZES[sz]["half_chest"] * 2
        parts.append(bt.text(cx, 10, sz, 5.0, bold=True, anchor="middle"))
        parts.append(bt.text(cx, 84, f'Chest {chest_in:g} in  ·  X 4 in', 2.8, anchor="middle", fill=bt.GREY))
        pct = 4.0 / SIZES[sz]["half_chest"] * 100
        parts.append(bt.text(cx, 89, f'X = {pct:.0f}% of the front width', 2.8, anchor="middle", fill=bt.GREY))
    parts.append(bt.text(12, 100, "Same scale, flat. Same 4 in (10 cm) X on every size; only its height grades +1 cm per size.",
                         2.6, fill=bt.GREY))
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}">{"".join(parts)}</svg>'
    open(os.path.join(OUT, "x4in-sizes.svg"), "w").write(svg)
    cairosvg.svg2png(bytestring=svg.encode(), write_to=os.path.join(OUT, "x4in-sizes.png"), output_width=2000)


def template():
    """1:1 home-test template on one page that fits both A4 and US Letter."""
    W, H = 210.0, 279.4
    cut, stitch, patch = x_lines()
    cx, cy = W / 2, 118.0
    T = lambda pts: [(cx + x, cy + y) for (x, y) in pts]
    p = [f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>']
    p.append(bt.text(14, 20, "CS-XTEE-01  ·  X 4 in (10 cm)  ·  plantilla 1:1", 5.0, bold=True))
    p.append(bt.text(14, 28, "Imprimí al 100% (sin ajustar a la página) y medí la barra de 50 mm antes de usarla.", 3.2))
    p.append(bt.poly(T(patch), stroke=bt.GREY, sw=0.3, dash="3 2"))
    p.append(bt.poly(T(stitch), stroke=bt.INK, sw=0.35, dash="1.6 1.1"))
    p.append(bt.poly(T(cut), fill="#E6D3C1", stroke=bt.INK, sw=0.5))
    p.append(bt.line(cx, cy - 62, cx, cy + 62, bt.MID, 0.2, dash="4 1.5 1 1.5"))
    p.append(bt.text(cx + 1.5, cy - 58, "CF", 2.8, fill=bt.GREY))
    p.append(bt.text(cx + 1.5, cy - 63.5, "cuello / neck ↑", 2.8, fill=bt.GREY))
    # 50 mm check bar
    y = 190
    for i in range(5):
        p.append(bt.rect(14 + i * 10, y, 10, 2.2, bt.INK if i % 2 == 0 else "#FFFFFF", bt.INK, 0.2))
    p.append(bt.text(68, y + 2.2, "50 mm", 3.0, bold=True))
    legend = [
        ("línea llena", "CORTE: se corta solo la tela crema por acá. Adentro queda el marrón a la vista."),
        ("punteado fino", "COSTURA: 3 mm por fuera del corte, atraviesa las dos telas."),
        ("punteado largo", "PARCHE MARRÓN: se corta por acá y va por dentro de la remera."),
    ]
    y = 205
    for a, b in legend:
        p.append(bt.text(14, y, a, 3.0, bold=True))
        p.append(bt.text(46, y, b, 3.0))
        y += 6.5
    y += 3
    steps = [
        "Prueba rápida (10 min): recortá la X por la línea llena en papel marrón, pegala con cinta en una",
        "remera crema, ponétela y sacate una foto al espejo a 2 m. Probá también 2 cm más arriba o más abajo.",
        "Prueba de costura: parche marrón por dentro, cosé la línea de costura, cortá solo la tela crema por",
        "la línea llena, lavá 3 veces. Así ves cómo se enrolla el borde antes de pagar una muestra.",
    ]
    for s_ in steps:
        p.append(bt.text(14, y, s_, 3.0))
        y += 5.2
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}">{"".join(p)}</svg>'
    open(os.path.join(OUT, "x4in-template-1to1.svg"), "w").write(svg)
    pdf = os.path.join(OUT, "x4in-template-1to1.pdf")
    cairosvg.svg2pdf(bytestring=svg.encode(), write_to=pdf)
    # Ask viewers not to shrink the page when printing.
    r, w = PdfReader(pdf), PdfWriter()
    for pg in r.pages:
        w.add_page(pg)
    w._root_object[NameObject("/ViewerPreferences")] = DictionaryObject({NameObject("/PrintScaling"): NameObject("/None")})
    with open(pdf, "wb") as fh:
        w.write(fh)
    cairosvg.svg2png(bytestring=svg.encode(), write_to=os.path.join(OUT, "x4in-template-1to1.png"), output_width=1400)


def stats():
    cut, stitch, patch = x_lines()
    bb = lambda pts: (max(x for x, _ in pts) - min(x for x, _ in pts), max(y for _, y in pts) - min(y for _, y in pts))
    print("cut box %.1f x %.1f mm" % bb(cut))
    print("stitch box %.1f x %.1f mm, stitch length %.0f mm" % (*bb(stitch), bt.stitch_length(stitch)))
    print("patch box %.1f x %.1f mm" % bb(patch))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    comparison()
    template()
    stats()
