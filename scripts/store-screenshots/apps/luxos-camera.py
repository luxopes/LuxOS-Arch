"""Kamera: nahled z testovaci kamery s vyfocenou fotkou a odpocet samospouste.

Bez webkamery: LUXOS_CAMERA_TEST=1 (testovaci kamera aplikace) s LUXOS_CAMERA_TEST_IMAGE - obrazek
nakresleny zde v cairo (pokoj s oknem, kvetinou a hrnkem), zadna skutecna kamera ani fotka.
Fotka se ulozi do docasneho HOME (~/Pictures/Camera). Video se nenahrava (mikrofon).
luxos-camera pridava na zacatek sys.path /usr/lib/luxos/python - spoustec v s.tmp proto nejdriv
nacte luxos_i18n, luxos_camera a luxos_qr z pracovni kopie.
"""
import math
import os
import sys


def scene(path, w=1280, h=720):
    import cairo
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
    cr = cairo.Context(surf)
    # stena
    g = cairo.LinearGradient(0, 0, 0, h)
    g.add_color_stop_rgb(0, 0.93, 0.88, 0.80)
    g.add_color_stop_rgb(1, 0.84, 0.77, 0.68)
    cr.set_source(g)
    cr.paint()
    # okno s oblohou a kopci
    wx, wy, ww, wh = 120, 90, 430, 380
    sky = cairo.LinearGradient(0, wy, 0, wy + wh)
    sky.add_color_stop_rgb(0, 0.45, 0.70, 0.95)
    sky.add_color_stop_rgb(1, 0.78, 0.89, 0.99)
    cr.rectangle(wx, wy, ww, wh)
    cr.set_source(sky)
    cr.fill()
    cr.save()
    cr.rectangle(wx, wy, ww, wh)
    cr.clip()
    for cx, cy, r in ((230, 170, 34), (270, 160, 44), (315, 172, 32), (430, 230, 26), (460, 222, 34)):
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.set_source_rgb(1, 1, 1)
        cr.fill()
    cr.move_to(wx, wy + wh)
    cr.curve_to(wx + 100, wy + 250, wx + 220, wy + 300, wx + ww, wy + 270)
    cr.line_to(wx + ww, wy + wh)
    cr.close_path()
    cr.set_source_rgb(0.47, 0.70, 0.42)
    cr.fill()
    cr.move_to(wx, wy + wh)
    cr.curve_to(wx + 160, wy + 300, wx + 300, wy + 340, wx + ww, wy + 320)
    cr.line_to(wx + ww, wy + wh)
    cr.close_path()
    cr.set_source_rgb(0.36, 0.60, 0.34)
    cr.fill()
    cr.restore()
    # ram okna
    cr.set_source_rgb(0.98, 0.97, 0.95)
    cr.set_line_width(16)
    cr.rectangle(wx, wy, ww, wh)
    cr.stroke()
    cr.set_line_width(10)
    cr.move_to(wx + ww / 2, wy)
    cr.line_to(wx + ww / 2, wy + wh)
    cr.move_to(wx, wy + wh / 2)
    cr.line_to(wx + ww, wy + wh / 2)
    cr.stroke()
    # police s knihami
    cr.set_source_rgb(0.55, 0.38, 0.24)
    cr.rectangle(720, 190, 420, 16)
    cr.fill()
    x = 740
    for i, (bw, bh, col) in enumerate(((34, 120, (0.80, 0.30, 0.28)), (28, 104, (0.25, 0.45, 0.70)),
                                       (40, 126, (0.95, 0.75, 0.30)), (26, 98, (0.35, 0.60, 0.45)),
                                       (36, 116, (0.55, 0.40, 0.70)), (30, 108, (0.90, 0.55, 0.35)))):
        cr.rectangle(x, 190 - bh, bw, bh)
        cr.set_source_rgb(*col)
        cr.fill()
        x += bw + 6
    cr.arc(1060, 150, 36, 0, 2 * math.pi)       # kulata vaza
    cr.set_source_rgb(0.30, 0.62, 0.66)
    cr.fill()
    # stul
    cr.rectangle(0, 560, w, h - 560)
    tbl = cairo.LinearGradient(0, 560, 0, h)
    tbl.add_color_stop_rgb(0, 0.66, 0.47, 0.31)
    tbl.add_color_stop_rgb(1, 0.52, 0.36, 0.23)
    cr.set_source(tbl)
    cr.fill()
    # kvetina v kvetinaci
    cr.save()
    cr.translate(860, 560)
    for ang, ln in ((-60, 190), (-35, 230), (-10, 250), (15, 235), (40, 200), (65, 160), (-80, 140)):
        cr.save()
        cr.rotate(math.radians(ang))
        cr.scale(0.32, 1)
        cr.arc(0, -ln / 2 - 40, ln / 2, 0, 2 * math.pi)
        cr.restore()
        cr.set_source_rgb(0.24 + (ang % 3) * 0.04, 0.58, 0.32)
        cr.fill()
    cr.move_to(-70, -60)
    cr.line_to(70, -60)
    cr.line_to(52, 40)
    cr.line_to(-52, 40)
    cr.close_path()
    cr.set_source_rgb(0.88, 0.50, 0.36)
    cr.fill()
    cr.restore()
    # hrnek
    cr.rectangle(400, 500, 110, 120)
    cr.set_source_rgb(0.97, 0.97, 0.98)
    cr.fill()
    cr.set_line_width(16)
    cr.arc(515, 555, 30, -math.pi / 2, math.pi / 2)
    cr.stroke()
    cr.save()
    cr.scale(1, 0.3)
    cr.arc(455, 500 / 0.3, 55, 0, 2 * math.pi)
    cr.restore()
    cr.set_source_rgb(0.42, 0.27, 0.16)
    cr.fill()
    surf.write_to_png(path)


def shots(s):
    img = os.path.join(s.tmp, "camera-scene.png")
    scene(img)
    files = s.src("luxos-desktop/files")
    run = os.path.join(s.tmp, "luxos-camera-run")
    with open(run, "w", encoding="utf-8") as f:
        f.write("#!%s\nimport runpy, sys\nsys.path[:0] = %r\n"
                "import luxos_i18n, luxos_camera, luxos_qr  # pracovni kopie\n"
                "sys.argv[0] = %r\nrunpy.run_path(sys.argv[0], run_name='__main__')\n"
                % (sys.executable, [s.src("luxos-i18n/files"), os.path.join(files, "python")],
                   os.path.join(files, "bin", "luxos-camera")))
    os.chmod(run, 0o755)
    s.python_env()
    env = {"LUXOS_CAMERA_TEST": "1", "LUXOS_CAMERA_TEST_IMAGE": img}
    p = s.launch([run], env=env)
    win = s.window(pid=p.pid, size=(960, 680))
    s.sleep(3.0)
    # 1: po vyfoceni (mezernik = spoust) - nahled posledni fotky vlevo dole
    s.key("space", win, delay=3.0)
    s.capture("1", win)
    # 2: samospoust 3 s (tlacitko 3s vedle prepinace Foto/Video) s odpoctem pres nahled
    s.click(771, 634, win, delay=0.6)
    s.key("space", win, delay=1.3)
    s.capture("2", win)
    s.sleep(3.0)
