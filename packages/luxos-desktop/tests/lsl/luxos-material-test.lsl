# Testovaci program pro tests/test_luxos_material.py (luxos_material.lsl), protejsek glass-ref/material-ref.c:
#   luxos-material-test dump CASES OUT   stejne radky jako material-ref dump
#   luxos-material-test basics           jednobarevne a hranove zmenseniny, styl a zavoj (JSON)
#   luxos-material-test bench DIR        casy (median, ms) generovani materialu a pasu listy
#   luxos-material-test api              strip/mezipamet/layer_position s tapetou z XDG_CONFIG_HOME (JSON)
load cairo, json, time
load luxos_material as material

COLORS = [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.7, 0.3],
          [1.0, 0.0, 1.0], [0.0, 1.0, 1.0], [1.0, 1.0, 0.0], [0.5, 0.5, 0.5]]

function pixels_text(surface):
    parts = []
    for px in cairo.surface_to_intarray(surface):
        parts.append(String(px & 0xffffffff))
    end
    return " ".join(parts)
end

function dump(cases, outpath):
    out = []
    last = ""
    gl = None
    m = []
    n = 0
    for line in readfile(cases).split("\n"):
        f = line.split(" ")
        if len(f) != 9:
            continue
        end
        wall = f[0]
        key = f[0] + " " + f[1] + " " + f[2]
        if key != last:
            call material.reload()
            gl = material.glass(wall)
            m = material.map_for(gl, Int(f[1]), Int(f[2]))
            parts = ["glass", wall, f[1], f[2]]
            for v in m:
                parts.append(String(v))
            end
            out.append(" ".join(parts) + " " + pixels_text(gl[0]))
            last = key
        end
        w = Int(f[5])
        h = Int(f[6])
        s = cairo.image_surface_create(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.create(s)
        light = material.paint(cr, 0, 0, w, h, Float(f[7]), Int(f[3]), Int(f[4]), Int(f[8]), gl, m)
        call cairo.destroy(cr)
        flag = "0"
        if light:
            flag = "1"
        end
        out.append("case " + String(n) + " " + flag + " " + pixels_text(s))
        call cairo.surface_destroy(s)
        n = n + 1
    end
    call writefile(outpath, "\n".join(out) + "\n")
    return 0
end

function solid(c):
    s = cairo.image_surface_create(cairo.FORMAT_RGB24, 16, 16)
    cr = cairo.create(s)
    call cairo.set_source_rgb(cr, c[0], c[1], c[2])
    call cairo.paint(cr)
    call cairo.destroy(cr)
    return s
end

function blurred(s):
    pixels = material.blur(cairo.surface_to_intarray(s), 16, 16)
    call cairo.surface_destroy(s)
    return [0, pixels, 16, 16]
end

function basics():
    solid_out = []
    styles = []
    for c in COLORS:
        gl = blurred(solid(c))
        solid_out.append(gl[1][8 * 16 + 8] & 0xffffff)
        st = material.stats(gl, 0, 0, 16, 16)
        light = st[2] >= 0.56
        styles.append([light, material.veil(st, light), material.veil(st, True), material.veil(st, False)])
    end
    s = solid([0.0, 0.0, 0.0])
    cr = cairo.create(s)
    call cairo.set_source_rgb(cr, 1.0, 1.0, 1.0)
    call cairo.rectangle(cr, 8, 0, 8, 16)
    call cairo.fill(cr)
    call cairo.destroy(cr)
    gl = blurred(s)
    edge = []
    for x in range(5, 11):
        edge.append(gl[1][8 * 16 + x] & 0xffffff)
    end
    print json.encode({"solid": solid_out, "styles": styles, "edge": edge})
    return 0
end

function median(values):
    s = sorted(values)
    return s[len(s) // 2]
end

function bench(dir):
    out = {}
    for ext in ["png", "jpg"]:
        t = []
        for i in range(15):
            call material.reload()
            a = time.perf_counter()
            gl = material.glass(dir + "/noise." + ext)
            t.append((time.perf_counter() - a) * 1000.0)
        end
        out["glass_" + ext + "_ms"] = median(t)
    end
    # samotne rozmazani zmenseniny (bez dekodovani obrazku)
    gl = material.glass(dir + "/noise.png")
    src = cairo.surface_to_intarray(gl[0])
    t = []
    for i in range(15):
        a = time.perf_counter()
        call material.blur(src, gl[2], gl[3])
        t.append((time.perf_counter() - a) * 1000.0)
    end
    out["blur_ms"] = median(t)
    # pas listy 1920x32 a vyskakovaci okno 340x420 bez mezipameti (tapeta uz nactena)
    m = material.map_for(gl, 1920, 1080)
    for spec in [["strip_ms", 0, 0, 1920, 32, 0.0], ["popup_ms", 1560, 40, 340, 420, 18.0]]:
        t = []
        for i in range(15):
            s = cairo.image_surface_create(cairo.FORMAT_ARGB32, spec[3], spec[4])
            cr = cairo.create(s)
            a = time.perf_counter()
            call material.paint(cr, 0, 0, spec[3], spec[4], spec[5], spec[1], spec[2], -1, gl, m)
            call cairo.surface_flush(s)
            t.append((time.perf_counter() - a) * 1000.0)
            call cairo.destroy(cr)
            call cairo.surface_destroy(s)
        end
        out[spec[0]] = median(t)
    end
    # cela cesta API: zmena tapety -> prvni pas listy (nastaveni + dekodovani + rozmazani + kresleni)
    t = []
    for i in range(9):
        call material.reload()
        a = time.perf_counter()
        call material.strip("eDP-1", 1920, 1080, 0, 0, 1920, 32, 0, -1, 1)
        t.append((time.perf_counter() - a) * 1000.0)
    end
    out["first_strip_ms"] = median(t)
    # kazdy dalsi snimek: hotovy povrch z mezipameti
    t = []
    for i in range(201):
        a = time.perf_counter()
        call material.strip("eDP-1", 1920, 1080, 0, 0, 1920, 32, 0, -1, 1)
        t.append((time.perf_counter() - a) * 1000.0)
    end
    out["cached_strip_ms"] = median(t)
    print json.encode(out)
    return 0
end

function api():
    out = {}
    out["wallpaper"] = material.wallpaper_path("eDP-1")
    out["wallpaper_hdmi"] = material.wallpaper_path("HDMI-A-1")
    a = material.strip("eDP-1", 1920, 1080, 0, 0, 1920, 32, 0, -1, 1)
    if a == None:
        print json.encode(out)
        return 0
    end
    b = material.strip("eDP-1", 1920, 1080, 0, 0, 1920, 32, 0, -1, 1)
    out["same_surface"] = a[0] == b[0]
    out["light"] = a[1]
    c = material.strip("eDP-1", 1920, 1080, 0, 0, 1920, 32, 0, -1, 2)
    out["hidpi_size"] = [cairo.image_surface_get_width(c[0]), cairo.image_surface_get_height(c[0])]
    for i in range(20):
        call material.strip("eDP-1", 1920, 1080, i, 0, 100, 32, 0, -1, 1)
    end
    out["strips_cached"] = len(material.state["strips"])
    call material.forget_output("eDP-1")
    out["after_forget"] = len(material.state["strips"])
    call material.strip("HDMI-A-1", 2560, 1440, 0, 0, 2560, 32, 0, -1, 1)
    call material.reload()
    out["after_reload"] = [len(material.state["strips"]), len(material.state["glasses"])]
    out["none_without_size"] = material.strip("eDP-1", 1920, 1080, 0, 0, 0, 32, 0, -1, 1) == None
    T = material.ANCHOR_TOP
    B = material.ANCHOR_BOTTOM
    L = material.ANCHOR_LEFT
    R = material.ANCHOR_RIGHT
    area = [0, 0, 1920, 1080]
    out["layers"] = [material.layer_position(T + L + R, [0, 0, 0, 0], 0, 32, area),
                     material.layer_position(B, [0, 0, 8, 0], 600, 70, area),
                     material.layer_position(T + R, [8, 12, 0, 0], 340, 400, [0, 32, 1920, 1048]),
                     material.layer_position(0, [0, 0, 0, 0], 400, 300, area),
                     material.layer_position(T + B + L + R, [0, 0, 0, 0], 0, 0, area),
                     material.layer_position(L + R, [0, 10, 0, 20], 0, 50, area),
                     material.layer_position(B + L, [0, 0, 4, 6], 64, 64, [1920, 0, 1280, 1024])]
    print json.encode(out)
    return 0
end

if len(args) == 4 and args[1] == "dump":
    call dump(args[2], args[3])
elif len(args) == 2 and args[1] == "basics":
    call basics()
elif len(args) == 3 and args[1] == "bench":
    call bench(args[2])
elif len(args) == 2 and args[1] == "api":
    call api()
else:
    print "usage: luxos-material-test dump CASES OUT | basics | bench DIR | api"
    exit(2)
end
