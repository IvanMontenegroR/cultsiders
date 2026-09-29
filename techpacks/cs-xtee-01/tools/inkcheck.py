#!/usr/bin/env python3
"""Per-character ink check on a real PDF (pdfium render), not on SVG previews.
For every non-space char in the text layer, render the page and check that the
char's loose box contains visible contrast (max-min luminance > threshold).
Also draws every glyph of every embedded font program referenced... (fontTools check separately)."""
import sys
import numpy as np
import pypdfium2 as pdfium

def check(path, scale=6.0, thr=40, verbose=True):
    pdf = pdfium.PdfDocument(path)
    total = 0
    bad = []
    for pi in range(len(pdf)):
        page = pdf[pi]
        W, H = page.get_size()
        img = page.render(scale=scale, grayscale=True).to_numpy()
        if img.ndim == 3:
            img = img[..., 0]
        tp = page.get_textpage()
        n = tp.count_chars()
        for ci in range(n):
            ch = tp.get_text_range(ci, 1)
            if not ch or ch.isspace():
                continue
            total += 1
            l, b, r, t = tp.get_charbox(ci, loose=False)
            if r - l < 0.05 or t - b < 0.05:
                l, b, r, t = tp.get_charbox(ci, loose=True)
            x0 = max(int(l * scale) - 1, 0); x1 = min(int(r * scale) + 2, img.shape[1])
            y0 = max(int((H - t) * scale) - 1, 0); y1 = min(int((H - b) * scale) + 2, img.shape[0])
            sub = img[y0:y1, x0:x1]
            if sub.size == 0 or int(sub.max()) - int(sub.min()) < thr:
                ctx = tp.get_text_range(max(ci - 12, 0), 25).replace("\n", " ").replace("\r", "")
                bad.append((pi + 1, ch, (round(l,1), round(b,1), round(r,1), round(t,1)), ctx))
    if verbose:
        print(f"{path}: {total} chars checked, {len(bad)} without ink")
        for b_ in bad[:60]:
            print("  p%d %r box=%s ctx=%r" % b_)
    return total, bad

if __name__ == "__main__":
    for p in sys.argv[1:]:
        check(p)
