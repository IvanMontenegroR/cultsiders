import io, sys
from pypdf import PdfReader
from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen
for path in sys.argv[1:]:
    seen = {}
    for pi, page in enumerate(PdfReader(path).pages, 1):
        for fref in page["/Resources"]["/Font"].values():
            fo = fref.get_object()
            for d in fo.get("/DescendantFonts", [fo]):
                d = d.get_object()
                fd = d["/FontDescriptor"].get_object()
                ff = fd["/FontFile2"].get_object().get_data()
                f = TTFont(io.BytesIO(ff))
                gs = f.getGlyphSet()
                empty = 0; err = 0
                for g in f.getGlyphOrder():
                    bp = BoundsPen(gs)
                    try:
                        gs[g].draw(bp)
                    except Exception as e:
                        err += 1
                        continue
                    if bp.bounds is None:
                        empty += 1
                key = (pi, str(fo["/BaseFont"]))
                seen[key] = (len(f.getGlyphOrder()), empty, err)
    for k, v in seen.items():
        print(path.split("/")[-1], "p%d %s glyphs=%d empty=%d draw_errors=%d" % (k[0], k[1], *v))
