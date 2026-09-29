# CS-XTEE-01 (working code)

Oversized boxy tee with a reverse-appliqué X on the front and a checker (ichimatsu) tape over both shoulder seams. Base block: Xinhui XH25-IM1222-M (DROP 001).

**Status: DRAFT v0.1.** Not ready to send to the factory. Open points are marked TBD (yellow) in the PDF.

| File | What it is |
|---|---|
| `CS-XTEE-TechPack-v0.1-DRAFT.pdf` | 8-page tech pack, English + Simplified Chinese |
| `CS-XTEE-01-X-template-1to1-PROPOSAL.pdf` | 1:1 X template (A3: 200 mm X, A4: 150 mm X). Print at 100%, check the 50 mm bar |
| `CS-XTEE-01-X-template-*.dxf` | Same X for the factory's embroidery/cutting program (R12 and R2000), units mm |
| `tape/sarga-tile.svg` | Founder's checker + twill tile |
| `tape/tape-options.*` | 15 mm vs 20 mm tape options drawn from that tile |

## Rebuild

```
apt-get install -y fonts-noto-cjk fonts-liberation
pip install cairosvg pypdf pypdfium2 pillow shapely fonttools numpy
python3 build_techpack.py
```

The script regenerates both PDFs, the DXFs, and page previews, and fails if it finds em/en dashes, missing glyphs or text closer than 8 mm to a page edge.
