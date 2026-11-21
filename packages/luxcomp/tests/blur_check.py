# Vyhodnoceni snimku blur.sh: rozptyl jasu v radku pod plochou (pruhy okna 4 px cerna/bila).
# S rozmazanim musi byt pruhy pryc (smerodatna odchylka < 3), bez materialu videt (> 20).
import sys
import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

def row_std(path, y, x0, x1):
    pb = GdkPixbuf.Pixbuf.new_from_file(path)
    data, stride, n = pb.get_pixels(), pb.get_rowstride(), pb.get_n_channels()
    vals = []
    for x in range(x0, x1):
        i = y * stride + x * n
        vals.append(0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2])
    mean = sum(vals) / len(vals)
    return mean, (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5

out = sys.argv[1]
# plocha: x 1320..1720, y 40..540; okno s pruhy pod ni od y ~118
ok = True
for name, want in (("blur-on", "blur"), ("blur-after-move", "blur"), ("blur-solid", "flat"), ("blur-absent", "stripes")):
    mean, std = row_std(f"{out}/{name}.png", 400, 1360, 1680)
    good = std < 3 if want in ("blur", "flat") else std > 20
    ok &= good
    print(f"{name}: mean {mean:.1f} std {std:.2f} expect {want}: {'ok' if good else 'FAIL'}")
# mimo plochu pruhy zustanou
mean, std = row_std(f"{out}/blur-on.png", 400, 400, 720)
print(f"reference stripes outside: std {std:.2f}")
ok &= std > 60
sys.exit(0 if ok else 1)
