# Vyhodnoceni snimku blur.sh: vysokofrekvencni energie v radku pod plochou (prumerny rozdil jasu
# sousednich pixelu; okno ma cerno-bile pruhy 4 px). S materialem musi pruhy zmizet (< 1), bez nej
# zustat videt (> 10); jednolita barva je rovna (< 0.5).
import sys
import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf


def row(path, y, x0, x1):
    pb = GdkPixbuf.Pixbuf.new_from_file(path)
    data, stride, n = pb.get_pixels(), pb.get_rowstride(), pb.get_n_channels()
    return [0.2126 * data[y * stride + x * n] + 0.7152 * data[y * stride + x * n + 1]
            + 0.0722 * data[y * stride + x * n + 2] for x in range(x0, x1)]


def ripple(vals):
    return sum(abs(vals[i + 1] - vals[i]) for i in range(len(vals) - 1)) / (len(vals) - 1)


out = sys.argv[1]
names = [("blur-on", 1.0, None), ("blur-after-move", 1.0, None)]
if len(sys.argv) < 3:
    names += [("blur-solid", 0.5, None), ("blur-absent", None, 10.0)]
ok = True
# plocha: x 1320..1720, y 40..540; okno s pruhy pod ni
for name, below, above in names:
    r = ripple(row(f"{out}/{name}.png", 400, 1360, 1680))
    good = (below is None or r < below) and (above is None or r > above)
    ok &= good
    print(f"{name}: ripple {r:.2f}: {'ok' if good else 'FAIL'}")
r = ripple(row(f"{out}/blur-on.png", 400, 400, 720))
print(f"stripes outside the surface: ripple {r:.2f}")
ok &= r > 50
sys.exit(0 if ok else 1)
