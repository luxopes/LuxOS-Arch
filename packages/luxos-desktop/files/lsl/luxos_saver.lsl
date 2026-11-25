# lsl: link libgdk_pixbuf-2.0.so.0 libpangocairo-1.0.so.0 libpango-1.0.so.0 libcairo.so.2 libgio-2.0.so.0 libgobject-2.0.so.0 libglib-2.0.so.0
# LuxOS - kresba setricu obrazovky (styly viz luxos-screensaver.lsl) bez okna: X11 setric (luxos-screensaver,
# okno xfce4-screensaver) i klid zamku na Waylandu (luxos-lock) kresli totez.
#
#   saver_init(styl, monitor), fps(), draw(cr, sirka, vyska, cela), dirty(sirka, vyska), invalidate()
#   style_for_theme(nazev)    styl tematu xfce4-screensaver (screensavers-luxos-wallpaper -> desktop, ...)

load env, math, random, process
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load cairo, pango
load luxos_i18n as i18n
load luxos_text

SLIDE = 20.0      # sekund na tapetu
FADE = 3.0        # delka prolinani
FPS = 15
FADE_FPS = 60     # prolinani tapet plynule (jen FADE sekund; jinak stoji a staci FPS)
STYLES = ["desktop", "wallpapers", "analog", "clock", "aurora", "photos", "logo", "blank"]
ANALOG_FPS = 20       # vterinova rucicka plynule; prekresluje se jen ctverec s hodinami
ANALOG_SLIDE = 30.0   # rucickove hodiny: sekund na tapetu
ANALOG_FADE = 2.5
FULL_EVERY = 5.0      # cela obrazovka nejpozdeji po tolika sekundach (i kdyz se meni jen hodiny)
FULL_BURST = 0.5      # po odkryti / mezere: tak dlouho kazdy snimek cely (i kdyz okno prekresli jiny)
PHOTO_EXT = [".jpg", ".jpeg", ".png", ".webp"]
LOGO = "/usr/share/icons/hicolor/scalable/apps/luxos-logo.svg"
OPERATOR_ADD = 12
FILTER_BILINEAR = 4
WEIGHT_ULTRALIGHT = 200
WEIGHT_LIGHT = 300
WEIGHT_SEMIBOLD = 600

S = {"style": "desktop", "start": 0.0, "slides": [], "phase": 0.0, "formats": None, "logo": None, "frame": None,
     "images": [], "aurora": 0, "full_until": 0.0, "full_at": -FULL_EVERY}
# rucickove hodiny: tapety [klic, surface] (klic "index|w|h"), rozpracovane nacitani, predkresleny ciselnik
A = {"slides": [], "offset": 0, "walls": [], "loading": [], "face": None, "dark": False, "dark_at": 0.0,
     "full": True, "drawn": ""}

function cstr(text):
    return glib.cstr(text)
end

function ptr(value):
    return glib.ptr(value)
end

function home():
    return env.get("HOME", glib.home_dir())
end

function config_home():
    value = env.get("XDG_CONFIG_HOME", "")
    if value == "":
        return home() + "/.config"
    end
    return value
end

# ---- nastaveni, tapety, fotky -------------------------------------------------------------------------------

function walls_dir():
    return env.get("LUXOS_SCREENSAVER_WALLS", "/usr/share/backgrounds/luxos")
end

# Tapety LuxOS bez svetle/tmave vychozi a bez odkazu na stejny soubor
function walls():
    found = []
    base = walls_dir()
    for name in glib_list_dir(base):
        if name.startswith("luxos-") and name.endswith(".jpg") and name != "luxos-dark.jpg" and name != "luxos-light.jpg":
            real = glib.realpath(base + "/" + name)
            if real != "" and not (real in found):
                found.append(real)
            end
        end
    end
    return sorted(found)
end

function glib_list_dir(path):
    return glib.list_dir(path)
end

function is_file(path):
    return path != "" and exists(path) and not glib.is_dir(path)
end

function ui_lang():
    for name in ["LC_ALL", "LC_TIME", "LANG"]:
        value = env.get(name, "")
        if value != "":
            value = value.split("_")[0].split(".")[0]
            if value == "":
                return "en"
            end
            return value
        end
    end
    return "en"
end

# Hodnoty sekce [greeter] souboru nastaveni luxos-greeter (klice jako configparser: mala pismena, = nebo :)
function greeter_conf():
    out = {}
    text = glib.read_text(env.get("LUXOS_GREETER_CONF", "/etc/lightdm/luxos-greeter.conf"))
    section = ""
    for raw in text.split("\n"):
        line = raw.strip()
        if line == "" or line.startswith("#") or line.startswith(";"):
            continue
        end
        if line.startswith("[") and line.endswith("]"):
            section = line[1:len(line) - 1].strip()
            continue
        end
        if section != "greeter":
            continue
        end
        cut = line.find("=")
        colon = line.find(":")
        if cut < 0 or (colon >= 0 and colon < cut):
            cut = colon
        end
        if cut > 0:
            out[line[0:cut].strip().lower()] = line[cut + 1:].strip()
        end
    end
    return out
end

# [pismo, format hodin, format data] jako luxos-greeter; "" = datum podle jazyka (local_date)
function greeter_formats():
    g = greeter_conf()
    v = g.get("clock-24h", "").strip().lower()
    h24 = ui_lang() != "en"
    if v != "" and v != "auto":
        h24 = v in ["1", "true", "yes", "on"]
    end
    font = g.get("font", "").strip()
    if font == "":
        font = "Inter"
    end
    clock = g.get("clock-format", "").strip()
    if clock == "":
        clock = "%-I:%M"
        if h24:
            clock = "%-H:%M"
        end
    end
    return [font, clock, g.get("date-format", "").strip()]
end

# strftime z libc pro mistni cas t (sekundy); "" kdyz format nic nevytvori
function strftime(fmt, t):
    unsafe:
        cell = __lsl_byte_zeros(8)
        call __lsl_qbe_store64(glib.data(cell), ptr(Int(t)))
        tm = __lsl_byte_zeros(64)
        call __lsl_qbe_call2(__lsl_symbol("localtime_r"), glib.data(cell), glib.data(tm))
        buffer = __lsl_byte_zeros(512)
        n = __lsl_qbe_call4(__lsl_symbol("strftime"), glib.data(buffer), 511, cstr(fmt), glib.data(tm))
        if n <= 0:
            return ""
        end
        return __lsl_text_from_bytes(buffer, 0, n)
    end
end

# Datum jako v luxos-greeter: vlastni date-format (strftime), jinak podle jazyka (dlouhy tvar luxos_i18n)
function local_date(t, fmt):
    if fmt != "":
        text = strftime(fmt, t)
        if text != "":
            return text
        end
    end
    row = i18n.CAL.get(ui_lang(), i18n.CAL["en"])
    tm = glib.localtime(Int(t))
    days = row[0].split(" ")
    months = row[2].split(" ")
    month = months[tm[1] - 1]
    out = row[3].replace("{A}", days[tm[6]]).replace("{a}", row[1].split(" ")[tm[6]])
    out = out.replace("{B}", month).replace("{b}", month[0:3])
    out = out.replace("{dd}", i18n.pad2(tm[2])).replace("{mm}", i18n.pad2(tm[1]))
    return out.replace("{d}", String(tm[2])).replace("{m}", String(tm[1])).replace("{Y}", String(tm[0]))
end

function now_unix():
    unsafe:
        return Float(__lsl_qbe_call0(__lsl_symbol("g_get_real_time"))) / 1000000.0
    end
end

function appearance_dark():
    return glib.read_text(config_home() + "/luxos/appearance").strip() == "dark"
end

# Tapeta plochy z xfconf (xfce4-desktop) ve stejnem poradi jako zamykaci dialog xfce4-screensaver:
# monitor<nazev>/workspace0, monitor<nazev>, monitor0/workspace0, pak kterykoli monitor;
# bez tapety vychozi tapeta LuxOS aktualniho rezimu (svetly/tmavy).
function desktop_wallpaper(monitor):
    out = ""
    safe:
        result = process.capture_result("/usr/bin/env", ["timeout", "5", "xfconf-query", "-c", "xfce4-desktop", "-l", "-v"])
        out = String(result["stdout"])
    end
    have = {}
    prefix = "/backdrop/screen0/"
    for line in out.split("\n"):
        cut = line.find(" ")
        if cut < 0:
            continue
        end
        prop = line[0:cut]
        val = line[cut + 1:].strip()
        if prop.startswith(prefix + "monitor") and prop.endswith("/last-image") and val != "":
            have[prop[len(prefix):len(prop) - len("/last-image")]] = val
        end
    end
    keys = []
    if monitor != "":
        keys = ["monitor" + monitor + "/workspace0", "monitor" + monitor]
    end
    keys.append("monitor0/workspace0")
    names = sorted(have.keys())
    for k in names:
        if k.endswith("/workspace0"):
            keys.append(k)
        end
    end
    for k in keys + names:
        if k in have and is_file(have[k]):
            return have[k]
        end
    end
    mode = "light"
    if appearance_dark():
        mode = "dark"
    end
    return "/usr/share/backgrounds/luxos/luxos-" + mode + ".jpg"
end

function photo_ext(name):
    low = name.lower()
    for ext in PHOTO_EXT:
        if low.endswith(ext):
            return True
        end
    end
    return False
end

# Fotky z ~/Pictures (xdg-user-dir) i v podslozkach, nejvys asi 500, nahodne poradi; odkazy na slozky se
# neprochazeji (jako os.walk)
function photo_list():
    pics = home() + "/Pictures"
    safe:
        result = process.capture_result("/usr/bin/env", ["timeout", "2", "xdg-user-dir", "PICTURES"])
        named = String(result["stdout"]).strip()
        if named != "" and glib.is_dir(named):
            pics = named
        end
    end
    found = []
    todo = [pics]
    while len(todo) > 0 and len(found) <= 500:
        folder = todo.pop(0)
        for name in glib_list_dir(folder):
            path = folder + "/" + name
            if glib.is_dir(path):
                if glib.readlink(path) == "":
                    todo.append(path)
                end
            elif photo_ext(name):
                found.append(path)
            end
        end
    end
    call random.shuffle(found)
    return found
end

# ---- obrazky --------------------------------------------------------------------------------------------

function pixbuf_load(path):
    if path == "" or path == None:
        return 0
    end
    return gtk.pixbuf_new_from_file(path)
end

function pixbuf_size(pixbuf):
    return [gtk.pixbuf_get_width(pixbuf) & 2147483647, gtk.pixbuf_get_height(pixbuf) & 2147483647]
end

# Obrazek ze souboru pres celou plochu w x h (jako tapeta plochy "Zvetsit"), vystredeny
function paint_cover(cr, path, w, h, alpha):
    src = pixbuf_load(path)
    if src == 0:
        return False
    end
    size = pixbuf_size(src)
    sc = max(Float(w) / size[0], Float(h) / size[1])
    tw = max(1, math.round(size[0] * sc))
    th = max(1, math.round(size[1] * sc))
    scaled = gtk.pixbuf_scale_simple(src, tw, th, gtk.INTERP_BILINEAR)
    call glib.object_unref(src)
    if scaled == 0:
        return False
    end
    call gtk.cairo_set_source_pixbuf(cr, scaled, (w - tw) / 2.0, (h - th) / 2.0)
    call cairo.paint_with_alpha(cr, alpha)
    call cairo.set_source_rgb(cr, 0, 0, 0)
    call glib.object_unref(scaled)
    return True
end

# Dekodovana tapeta (2560x1440 = 11 MB) se hned uvolni; bez vraceni volne pameti haldy systemu by ji proces
# drzel dal (PSS setrice +20 MB)
function trim():
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("malloc_trim"), 0)
    end
    return 0
end

function surface_new(format, w, h):
    return cairo.image_surface_create(format, max(1, w), max(1, h))
end

# Tapeta pro styl s pomalym pohybem: obrazek o kousek vetsi nez plocha jako [surface, sirka, vyska] nebo None.
# Drzi se jen posledni tri (aktualni, dalsi a predchozi pri prolinani).
function slide_image(path, w, h):
    key = path + "|" + String(w) + "|" + String(h)
    for item in S["images"]:
        if item[0] == key:
            return item[1]
        end
    end
    value = None
    src = pixbuf_load(path)
    if src != 0:
        size = pixbuf_size(src)
        scale = max(Float(w) / size[0], Float(h) / size[1])
        sw = Int(size[0] * scale) + 1
        sh = Int(size[1] * scale) + 1
        scaled = gtk.pixbuf_scale_simple(src, sw, sh, gtk.INTERP_BILINEAR)
        call glib.object_unref(src)
        if scaled != 0:
            surf = surface_new(cairo.FORMAT_RGB24, sw, sh)
            c = cairo.create(surf)
            call gtk.cairo_set_source_pixbuf(c, scaled, 0, 0)
            call cairo.paint(c)
            call cairo.destroy(c)
            call glib.object_unref(scaled)
            value = [surf, sw, sh]
        end
    end
    keep = []
    for item in S["images"]:
        if item[0].endswith("|" + String(w) + "|" + String(h)) and len(keep) < 2:
            keep.append(item)
        elif item[1] != None:
            call cairo.surface_destroy(item[1][0])
        end
    end
    keep.append([key, value])
    S["images"] = keep
    call trim()
    return value
end

function paint_wall(cr, path, w, h, alpha, t):
    img = slide_image(path, w, h)
    if img == None:
        return 0
    end
    # pomaly pohyb (Ken Burns) po zbyle plose obrazku; cele pixely: posun o zlomek by cairo nutil filtrovat
    # celou obrazovku (dva takove obrazky na snimek pri prolinani)
    dx = math.round((img[1] - w) * (0.5 + 0.5 * math.sin(t / 37)))
    dy = math.round((img[2] - h) * (0.5 + 0.5 * math.cos(t / 53)))
    call cairo.set_source_surface(cr, img[0], -dx, -dy)
    call cairo.paint_with_alpha(cr, alpha)
    return 0
end

# ---- text ----------------------------------------------------------------------------------------------

function text_layout(cr, text, px, weight, family):
    lay = pango.cairo_create_layout(cr)
    unsafe:
        fd = __lsl_qbe_call0(__lsl_symbol("pango_font_description_new"))
        call __lsl_qbe_call2(__lsl_symbol("pango_font_description_set_family"), fd, cstr(family + ",Inter,Cantarell,Noto Sans,sans-serif"))
        call __lsl_qbe_call2(__lsl_symbol("pango_font_description_set_weight"), fd, ptr(weight))
        call __lsl_qbe_call2(__lsl_symbol("pango_font_description_set_absolute_size"), fd, Float(px) * 1024.0)
        call __lsl_qbe_call2(__lsl_symbol("pango_layout_set_font_description"), ptr(lay), fd)
        call __lsl_qbe_call1(__lsl_symbol("pango_font_description_free"), fd)
    end
    call pango.layout_set_text(lay, text)
    return lay
end

# [[ink x, y, w, h], [logicky x, y, w, h]] v pixelech
function pixel_extents(lay):
    unsafe:
        cells = __lsl_byte_zeros(32)
        base = glib.array_data(cells)
        call __lsl_qbe_call3(__lsl_symbol("pango_layout_get_pixel_extents"), ptr(lay), base, base + 16)
        out = []
        index = 0
        while index < 8:
            out.append(__lsl_qbe_s32(__lsl_qbe_load32(base + index * 4)))
            index += 1
        end
        return [out[0:4], out[4:8]]
    end
end

# mekky stin: nekolik posunutych kopii s malou pruhlednosti (jako luxos-greeter)
function shadow_text(cr, lay, x, y, alpha, blur):
    for d in [[0, 1], [0, 2], [-1, 1.5], [1, 1.5], [0, 3]]:
        call cairo.move_to(cr, x + d[0] * blur * 0.35, y + d[1] * blur * 0.45)
        call cairo.set_source_rgba(cr, 0, 0, 0, 0.055 * alpha)
        call pango.cairo_show_layout(cr, lay)
    end
    call cairo.move_to(cr, x, y)
    call cairo.set_source_rgba(cr, 1, 1, 1, alpha)
    call pango.cairo_show_layout(cr, lay)
    return 0
end

# Datum a velke tenke hodiny presne jako luxos-greeter v klidu (draw_bg, t = 0)
function greeter_clock(cr, w, h):
    f = S["formats"]
    u = max(0.55, h / 1080.0)
    t = now_unix()
    clock = strftime(f[1], t)
    if clock == "":
        clock = strftime("%H:%M", t)
    end
    y0 = h * 0.105
    dl = text_layout(cr, local_date(t, f[2]), 27 * u, WEIGHT_SEMIBOLD, f[0])
    logi = pixel_extents(dl)[1]
    call shadow_text(cr, dl, w / 2.0 - logi[2] / 2.0, y0, 0.92, 2 * u)
    call pango.layout_unref(dl)
    cl = text_layout(cr, clock, 180 * u, WEIGHT_ULTRALIGHT, f[0])
    ink = pixel_extents(cl)[0]
    call shadow_text(cr, cl, w / 2.0 - ink[0] - ink[2] / 2.0, y0 + logi[3] + 14 * u - ink[1], 1.0, 4 * u)
    call pango.layout_unref(cl)
    return 0
end

function big_clock(cr, w, h, alpha):
    t = now_unix()
    hh = strftime("%H:%M", t)
    day = local_date(t, "")
    size = max(48.0, h * 0.16)
    call cairo.select_font_face(cr, "Inter", 0, 1)
    call cairo.set_font_size(cr, size)
    ext = cairo.text_extents(cr, hh)
    x = w / 2.0 - ext[4] / 2
    y = h * 0.30
    call cairo.set_source_rgba(cr, 0, 0, 0, 0.25)
    call cairo.move_to(cr, x + 2, y + 3)
    call cairo.show_text(cr, hh)
    call cairo.set_source_rgba(cr, 1, 1, 1, alpha)
    call cairo.move_to(cr, x, y)
    call cairo.show_text(cr, hh)
    call cairo.select_font_face(cr, "Inter", 0, 0)
    call cairo.set_font_size(cr, max(16.0, size * 0.18))
    ext = cairo.text_extents(cr, day)
    call cairo.set_source_rgba(cr, 1, 1, 1, 0.85)
    call cairo.move_to(cr, w / 2.0 - ext[4] / 2, y + size * 0.42)
    call cairo.show_text(cr, day)
    return 0
end

# ---- setric ---------------------------------------------------------------------------------------------

function saver_init(style, monitor):
    S["style"] = "desktop"
    if style in STYLES:
        S["style"] = style
    end
    S["start"] = monotonic()
    S["slides"] = walls()
    if S["style"] == "photos":
        photos = photo_list()
        if len(photos) > 0:
            S["slides"] = photos
        end
    elif S["style"] == "desktop":
        S["slides"] = [desktop_wallpaper(monitor)]
    end
    S["phase"] = random.random() * 100
    if S["style"] == "desktop" or S["style"] == "analog":
        S["formats"] = greeter_formats()
    end
    if S["style"] == "analog":
        call analog_init(S["slides"])
    end
    return 0
end

function fps():
    # stojici tapeta s hodinami staci jednou za sekundu (setri procesor)
    if S["style"] == "analog":
        return ANALOG_FPS
    elif S["style"] == "desktop":
        return 1
    end
    return FPS
end

# Snimky za sekundu prave ted (zamek se pta kazdy snimek): prolinani tapet plynule, jinak fps()
function fps_now():
    if (S["style"] == "wallpapers" or S["style"] == "photos") and len(S["slides"]) > 1:
        phase = (monotonic() - S["start"]) % SLIDE
        if phase > SLIDE - FADE - 1.0 / FPS:
            return FADE_FPS
        end
    end
    return fps()
end

# Obsah okna nelze brat za platny (odkryti, navrat od dialogu s heslem, mezera v kresleni):
# nekolik pristich snimku cele obrazovky
function invalidate():
    S["full_until"] = max(S["full_until"], monotonic() + FULL_BURST)
    return 0
end

# Obdelnik [x, y, sirka, vyska], ktery se zmenil od posledniho snimku; None = cela obrazovka
function dirty(w, h):
    now = monotonic()
    if now < S["full_until"]:
        return None
    end
    if now - S["full_at"] >= FULL_EVERY:
        return None             # pojistka: obcas cela obrazovka, nikdy jen stary obsah okna
    end
    if S["style"] == "analog":
        return analog_dirty(w, h, now - S["start"])
    end
    return None
end

function draw(cr, w, h, full):
    if full:
        S["full_at"] = monotonic()
    end
    t = monotonic() - S["start"]
    style = S["style"]
    if style == "analog":
        return analog_draw(cr, w, h, t)
    end
    if style == "clock" or style == "blank":
        call cairo.set_source_rgb(cr, 0, 0, 0)
    else:
        call cairo.set_source_rgb(cr, 0.04, 0.04, 0.08)
    end
    call cairo.paint(cr)
    if style == "desktop":
        # tapeta stoji (stejna jako na plose), jen hodiny - jako klid luxos-greeter
        frame = S["frame"]
        if frame == None or frame[1] != w or frame[2] != h:
            if frame != None:
                call cairo.surface_destroy(frame[0])
            end
            surf = surface_new(cairo.FORMAT_RGB24, w, h)
            c = cairo.create(surf)
            call cairo.set_source_rgb(c, 0.04, 0.04, 0.08)
            call cairo.paint(c)
            call paint_cover(c, S["slides"][0], w, h, 1.0)
            call cairo.set_source_rgba(c, 0, 0, 0, 0.10)
            call cairo.paint(c)
            call cairo.destroy(c)
            frame = [surf, w, h]
            S["frame"] = frame
            call trim()
        end
        call cairo.set_source_surface(cr, frame[0], 0, 0)
        call cairo.paint(cr)
        call greeter_clock(cr, w, h)
    elif style == "wallpapers" or style == "photos":
        slides = S["slides"]
        if len(slides) > 0:
            idx = Int(math.floor(t / SLIDE))
            phase = t - idx * SLIDE
            call paint_wall(cr, slides[idx % len(slides)], w, h, 1.0, t)
            if phase > SLIDE - FADE:
                call paint_wall(cr, slides[(idx + 1) % len(slides)], w, h, (phase - (SLIDE - FADE)) / FADE, t)
            elif phase > 1.0:
                # dalsi tapetu nacist uz ted, kdy obraz stoji (dekodovani trva desitky az stovky ms); az pri
                # prolinani by se na nem animace zasekla
                call slide_image(slides[(idx + 1) % len(slides)], w, h)
            end
        end
        # ztmaveni pro citelnost hodin
        call cairo.set_source_rgba(cr, 0, 0, 0, 0.28)
        call cairo.paint(cr)
        call big_clock(cr, w, h, 0.95)
    elif style == "clock":
        # pomaly posun, aby se hodiny nevypalily do displeje
        dx = math.sin(t / 47 + S["phase"]) * w * 0.18
        dy = math.cos(t / 61 + S["phase"]) * h * 0.14
        call cairo.translate(cr, dx, dy + h * 0.12)
        call big_clock(cr, w, h, 0.9)
    elif style == "aurora":
        call aurora(cr, w, h, t)
        call big_clock(cr, w, h, 0.75)
    elif style == "logo":
        call floating_logo(cr, w, h, t)
    end
    return 0
end

# Barevna svetla v nizkem rozliseni (levne i na 4K), roztazena pres obrazovku
function aurora(cr, w, h, t):
    sw = 96
    sh = max(54, Int(96 * h / max(w, 1)))
    if S["aurora"] == 0 or cairo.image_surface_get_height(S["aurora"]) != sh:
        if S["aurora"] != 0:
            call cairo.surface_destroy(S["aurora"])
        end
        S["aurora"] = surface_new(cairo.FORMAT_RGB24, sw, sh)
    end
    surf = S["aurora"]
    c = cairo.create(surf)
    call cairo.set_source_rgb(c, 0.03, 0.02, 0.09)
    call cairo.paint(c)
    call cairo.set_operator(c, OPERATOR_ADD)
    blobs = [[0.36, 0.30, 1.00], [0.75, 0.25, 0.95], [0.15, 0.65, 0.95], [0.95, 0.35, 0.60]]
    i = 0
    for b in blobs:
        x = sw * (0.5 + 0.42 * math.sin(t / (23 + i * 7) + i * 1.7 + S["phase"]))
        y = sh * (0.5 + 0.40 * math.cos(t / (29 + i * 5) + i * 2.3 + S["phase"]))
        rad = sw * (0.38 + 0.12 * math.sin(t / 17 + i))
        g = cairo.pattern_create_radial(x, y, 0, x, y, rad)
        call cairo.pattern_add_color_stop_rgba(g, 0, b[0], b[1], b[2], 0.85)
        call cairo.pattern_add_color_stop_rgba(g, 1, b[0], b[1], b[2], 0)
        call cairo.set_source(c, g)
        call cairo.paint(c)
        call cairo.pattern_destroy(g)
        i += 1
    end
    call cairo.destroy(c)
    call cairo.surface_flush(surf)
    call cairo.save(cr)
    call cairo.scale(cr, Float(w) / sw, Float(h) / sh)
    call cairo.set_source_surface(cr, surf, 0, 0)
    call gtk.cairo_source_filter(cr, FILTER_BILINEAR)
    call cairo.paint(cr)
    call cairo.restore(cr)
    return 0
end

# odraz od okraju (trojuhelnikova vlna)
function bounce(v, span):
    v = v - math.floor(v / (2 * span)) * 2 * span
    if v < span:
        return v
    end
    return 2 * span - v
end

function floating_logo(cr, w, h, t):
    if S["logo"] == None:
        size = Int(h * 0.16)
        S["logo"] = gtk.pixbuf_new_from_file_at_scale(LOGO, size, size, True)
    end
    if S["logo"] == 0:
        return 0
    end
    size = pixbuf_size(S["logo"])
    x = bounce(t * w * 0.035 + S["phase"] * 97, Float(max(w - size[0], 1)))
    y = bounce(t * h * 0.045 + S["phase"] * 53, Float(max(h - size[1], 1)))
    call gtk.cairo_set_source_pixbuf(cr, S["logo"], x, y)
    call cairo.paint_with_alpha(cr, 0.9)
    return 0
end

# ---- rucickove hodiny -------------------------------------------------------------------------------------
# Tapety LuxOS s prolinanim a velke klasicke rucickove hodiny s datem. Tapety jsou predpocitane obrazky
# velikosti obrazovky (dalsi se nacita na pozadi v GIO, aby se vterinova rucicka nezastavila); mimo
# prolinani se prekresluje jen ctverec s hodinami. Ciselnik je predkresleny; svetly nebo tmavy podle vzhledu.

function analog_init(slides):
    A["slides"] = slides
    if len(slides) == 0:
        A["slides"] = [""]
    end
    A["offset"] = random.randrange(len(A["slides"]))
    A["dark"] = appearance_dark()
    A["dark_at"] = monotonic()
    return 0
end

function geometry(w, h):
    r = min(h * 0.235, w * 0.36)
    return [w / 2.0, h * 0.44, r]
end

function box(w, h):
    g = geometry(w, h)
    m = g[2] * 1.12                # i se stinem
    x = max(0, Int(g[0] - m))
    y = max(0, Int(g[1] - m))
    return [x, y, min(w - x, Int(2 * m) + 2), min(h - y, Int(2 * m) + 2)]
end

# [index tapety, prolinani 0..1]
function analog_slide(t):
    n = len(A["slides"])
    k = Int(math.floor(t / ANALOG_SLIDE))
    phase = t - k * ANALOG_SLIDE
    fade = 0.0
    if n > 1:
        fade = max(0.0, (phase - (ANALOG_SLIDE - ANALOG_FADE)) / ANALOG_FADE)
    end
    return [(k + A["offset"]) % n, fade]
end

function wall_key(idx, w, h):
    return String(idx) + "|" + String(w) + "|" + String(h)
end

function wall_get(key):
    for item in A["walls"]:
        if item[0] == key:
            return item[1]
        end
    end
    return 0
end

function wall_put(key, surf):
    if wall_get(key) == 0:
        A["walls"].append([key, surf])
    else:
        call cairo.surface_destroy(surf)
    end
    return 0
end

function analog_state(idx, fade):
    yday = glib.localtime(glib.now())[7]
    return String(idx) + "|" + String(fade > 0) + "|" + String(yday) + "|" + String(A["dark"])
end

function analog_dirty(w, h, t):
    s = analog_slide(t)
    if monotonic() - A["dark_at"] > 60:
        A["dark_at"] = monotonic()
        dark = appearance_dark()
        if dark != A["dark"]:
            A["dark"] = dark
            A["full"] = True
        end
    end
    have = wall_get(wall_key(s[0], w, h)) != 0
    if A["full"] or s[1] > 0 or analog_state(s[0], s[1]) != A["drawn"] or not have:
        return None
    end
    return box(w, h)
end

# Tapeta pres celou obrazovku se ztmavenim pro citelnost hodin a data
function wall_surface(pixbuf, w, h, x, y):
    surf = surface_new(cairo.FORMAT_RGB24, w, h)
    cr = cairo.create(surf)
    call cairo.set_source_rgb(cr, 0.05, 0.05, 0.09)
    call cairo.paint(cr)
    if pixbuf != 0:
        call gtk.cairo_set_source_pixbuf(cr, pixbuf, x, y)
        call cairo.paint(cr)
    end
    call cairo.set_source_rgba(cr, 0, 0, 0, 0.16)
    call cairo.paint(cr)
    call cairo.destroy(cr)
    call cairo.surface_flush(surf)
    return surf
end

function render_wall(idx, w, h):
    surf = 0
    src = pixbuf_load(A["slides"][idx])
    if src == 0:
        return wall_surface(0, w, h, 0, 0)
    end
    size = pixbuf_size(src)
    sc = max(Float(w) / size[0], Float(h) / size[1])
    tw = max(1, math.round(size[0] * sc))
    th = max(1, math.round(size[1] * sc))
    scaled = gtk.pixbuf_scale_simple(src, tw, th, gtk.INTERP_BILINEAR)
    call glib.object_unref(src)
    surf = wall_surface(scaled, w, h, (w - tw) / 2.0, (h - th) / 2.0)
    if scaled != 0:
        call glib.object_unref(scaled)
    end
    return surf
end

# Tapeta [index] velikosti obrazovky; wait=False ji zacne nacitat na pozadi a vrati 0, dokud neni
function analog_wall(idx, w, h, wait):
    key = wall_key(idx, w, h)
    surf = wall_get(key)
    if surf != 0:
        return surf
    end
    if not wait:
        if not (key in A["loading"]):
            if load_async(idx, w, h):
                A["loading"].append(key)
            else:
                call wall_put(key, render_wall(idx, w, h))
                return wall_get(key)
            end
        end
        return 0
    end
    call wall_put(key, render_wall(idx, w, h))
    call trim()
    return wall_get(key)
end

# Nacteni a zmenseni obrazku ve vlakne GIO (gdk_pixbuf_new_from_stream_at_scale_async), slozeni na obrazovku
# az v hlavni smycce; False = nejde (pak hned synchronne)
function load_async(idx, w, h):
    path = A["slides"][idx]
    if path == "":
        return False
    end
    unsafe:
        cells = __lsl_byte_zeros(16)
        base = glib.array_data(cells)
        if __lsl_qbe_call3(__lsl_symbol("gdk_pixbuf_get_file_info"), cstr(path), base, base + 4) == 0:
            return False
        end
        sw = __lsl_qbe_s32(__lsl_qbe_load32(base))
        sh = __lsl_qbe_s32(__lsl_qbe_load32(base + 4))
        if sw <= 0 or sh <= 0:
            return False
        end
        file = __lsl_qbe_call1(__lsl_symbol("g_file_new_for_path"), cstr(path))
        stream = __lsl_qbe_call3(__lsl_symbol("g_file_read"), file, 0, 0)
        call glib.object_unref(file)
        if stream == 0:
            return False
        end
        sc = max(Float(w) / sw, Float(h) / sh)
        tw = max(1, math.round(sw * sc))
        th = max(1, math.round(sh * sc))
        job = [idx, w, h, tw, th, stream, 0]
        tracked = glib.track(on_loaded, 2, job)
        job[6] = tracked[1]
        call __lsl_qbe_call7(__lsl_symbol("gdk_pixbuf_new_from_stream_at_scale_async"), stream, ptr(tw), ptr(th), 0, 0, __lsl_symbol("lsl_arch_callback_u3"), ptr(tracked[0]))
    end
    return True
end

function on_loaded(job, source, result):
    unsafe:
        pixbuf = __lsl_qbe_call2(__lsl_symbol("gdk_pixbuf_new_from_stream_finish"), ptr(result), 0)
    end
    call glib.release(job[6])
    call glib.object_unref(job[5])
    key = wall_key(job[0], job[1], job[2])
    if key in A["loading"]:
        call A["loading"].remove(key)
    end
    call wall_put(key, wall_surface(pixbuf, job[1], job[2], (job[1] - job[3]) / 2.0, (job[2] - job[4]) / 2.0))
    if pixbuf != 0:
        call glib.object_unref(pixbuf)
    end
    call trim()
    return 0
end

function analog_keep(keys):
    kept = []
    for item in A["walls"]:
        if item[0] in keys:
            kept.append(item)
        else:
            call cairo.surface_destroy(item[1])
        end
    end
    A["walls"] = kept
    return 0
end

function colors():
    if A["dark"]:
        return {"face": [0.10, 0.10, 0.13, 0.62], "rim": [1, 1, 1, 0.16], "ink": [0.96, 0.96, 0.98],
                "minor": [1, 1, 1, 0.38], "shadow": 0.45}
    end
    return {"face": [1, 1, 1, 0.80], "rim": [1, 1, 1, 0.9], "ink": [0.11, 0.11, 0.13],
            "minor": [0.11, 0.11, 0.13, 0.42], "shadow": 0.30}
end

function rgba(cr, c):
    return cairo.set_source_rgba(cr, c[0], c[1], c[2], c[3])
end

function rgb(cr, c):
    return cairo.set_source_rgb(cr, c[0], c[1], c[2])
end

# Ciselnik (stin, kotouc, rysky, cislice) ve ctverci box(): [surface, x, y]
function face_surface(w, h):
    key = String(A["dark"]) + "|" + String(w) + "|" + String(h)
    if A["face"] != None and A["face"][0] == key:
        return A["face"][1:4]
    end
    if A["face"] != None:
        call cairo.surface_destroy(A["face"][1])
    end
    b = box(w, h)
    g = geometry(w, h)
    r = g[2]
    c = colors()
    surf = surface_new(cairo.FORMAT_ARGB32, b[2], b[3])
    cr = cairo.create(surf)
    call cairo.translate(cr, g[0] - b[0], g[1] - b[1])
    i = 10
    while i > 0:                    # mekky stin pod kotoucem
        call cairo.arc(cr, 0, r * 0.025, r * (1.0 + i * 0.009), 0, 2 * math.PI)
        call cairo.set_source_rgba(cr, 0, 0, 0, c["shadow"] * 0.035)
        call cairo.fill(cr)
        i -= 1
    end
    call cairo.arc(cr, 0, 0, r, 0, 2 * math.PI)
    call rgba(cr, c["face"])
    call cairo.fill_preserve(cr)
    call cairo.set_line_width(cr, max(1.0, r * 0.012))
    call rgba(cr, c["rim"])
    call cairo.stroke(cr)
    call cairo.set_line_cap(cr, cairo.LINE_CAP_ROUND)
    i = 0
    while i < 60:
        a = i * math.PI / 30
        hour = i % 5 == 0
        r0 = r * 0.89
        lw = r * 0.008
        if hour:
            r0 = r * 0.83
            lw = r * 0.022
        end
        call cairo.move_to(cr, math.sin(a) * r0, -math.cos(a) * r0)
        call cairo.line_to(cr, math.sin(a) * r * 0.93, -math.cos(a) * r * 0.93)
        call cairo.set_line_width(cr, lw)
        if hour:
            call rgb(cr, c["ink"])
        else:
            call rgba(cr, c["minor"])
        end
        call cairo.stroke(cr)
        i += 1
    end
    font = "Inter"
    if S["formats"] != None:
        font = S["formats"][0]
    end
    n = 1
    while n <= 12:
        a = n * math.PI / 6
        lay = text_layout(cr, String(n), r * 0.13, WEIGHT_LIGHT, font)
        ink = pixel_extents(lay)[0]
        x = math.sin(a) * r * 0.70
        y = -math.cos(a) * r * 0.70
        call cairo.move_to(cr, x - ink[0] - ink[2] / 2.0, y - ink[1] - ink[3] / 2.0)
        call rgb(cr, c["ink"])
        call pango.cairo_show_layout(cr, lay)
        call pango.layout_unref(lay)
        n += 1
    end
    call cairo.destroy(cr)
    call cairo.surface_flush(surf)
    A["face"] = [key, surf, b[0], b[1]]
    return [surf, b[0], b[1]]
end

function hand(cr, angle, length, tail, width, c, shadow):
    call cairo.save(cr)
    call cairo.rotate(cr, angle)
    call cairo.set_line_cap(cr, cairo.LINE_CAP_ROUND)
    call cairo.set_line_width(cr, width)
    call cairo.move_to(cr, width * 0.15, tail + width * 0.35)      # stin vpravo dole
    call cairo.line_to(cr, width * 0.15, -length + width * 0.35)
    call cairo.set_source_rgba(cr, 0, 0, 0, shadow)
    call cairo.stroke(cr)
    call cairo.move_to(cr, 0, tail)
    call cairo.line_to(cr, 0, -length)
    call rgb(cr, c)
    call cairo.stroke(cr)
    call cairo.restore(cr)
    return 0
end

function draw_hands(cr, w, h, now):
    g = geometry(w, h)
    r = g[2]
    c = colors()
    lt = glib.localtime(Int(math.floor(now)))
    sec = lt[5] + (now - math.floor(now))
    mins = lt[4] + sec / 60.0
    hrs = (lt[3] % 12) + mins / 60.0
    accent = [1.0, 0.42, 0.21]
    call cairo.save(cr)
    call cairo.translate(cr, g[0], g[1])
    call hand(cr, hrs * math.PI / 6, r * 0.50, r * 0.08, r * 0.055, c["ink"], 0.18)
    call hand(cr, mins * math.PI / 30, r * 0.76, r * 0.10, r * 0.038, c["ink"], 0.18)
    call hand(cr, sec * math.PI / 30, r * 0.86, r * 0.20, r * 0.012, accent, 0.15)
    call cairo.arc(cr, 0, 0, r * 0.035, 0, 2 * math.PI)
    call rgb(cr, accent)
    call cairo.fill(cr)
    call cairo.arc(cr, 0, 0, r * 0.012, 0, 2 * math.PI)
    call rgb(cr, c["ink"])
    call cairo.fill(cr)
    call cairo.restore(cr)
    return 0
end

function draw_date(cr, w, h):
    g = geometry(w, h)
    font = "Inter"
    fmt = ""
    if S["formats"] != None:
        font = S["formats"][0]
        fmt = S["formats"][2]
    end
    u = max(0.55, h / 1080.0)
    lay = text_layout(cr, local_date(now_unix(), fmt), 30 * u, WEIGHT_SEMIBOLD, font)
    logi = pixel_extents(lay)[1]
    call shadow_text(cr, lay, g[0] - logi[2] / 2.0, g[1] + g[2] * 1.16, 0.95, 2.5 * u)
    call pango.layout_unref(lay)
    return 0
end

function analog_draw(cr, w, h, t):
    s = analog_slide(t)
    idx = s[0]
    fade = s[1]
    n = len(A["slides"])
    nxt_idx = (idx + 1) % n
    cur = analog_wall(idx, w, h, True)
    # dalsi tapetu pripravit vcas na pozadi (nacteni velke tapety trva i stovky ms)
    nxt = 0
    if n > 1:
        nxt = analog_wall(nxt_idx, w, h, False)
    end
    call analog_keep([wall_key(idx, w, h), wall_key(nxt_idx, w, h)])
    call cairo.set_source_surface(cr, cur, 0, 0)
    call cairo.paint(cr)
    if fade > 0 and nxt != 0:
        call cairo.set_source_surface(cr, nxt, 0, 0)
        call cairo.paint_with_alpha(cr, fade * fade * (3 - 2 * fade))
    end
    face = face_surface(w, h)
    call cairo.set_source_surface(cr, face[0], face[1], face[2])
    call cairo.paint(cr)
    call draw_hands(cr, w, h, now_unix())
    call draw_date(cr, w, h)
    A["full"] = False
    A["drawn"] = analog_state(idx, fade)
    return 0
end

# Tema xfce4-screensaver (xfconf /saver/themes/list, "screensavers-" + nazev souboru .desktop) -> styl; nezname
# tema (jiny setric) -> vychozi styl (stridajici se tapety, jako vychozi tema v /etc/xdg)
DEFAULT_STYLE = "wallpapers"
THEMES = {"screensavers-luxos": "wallpapers", "screensavers-luxos-wallpaper": "desktop", "screensavers-luxos-analog": "analog",
          "screensavers-luxos-clock": "clock", "screensavers-luxos-aurora": "aurora", "screensavers-luxos-photos": "photos",
          "screensavers-luxos-logo": "logo"}

function style_for_theme(name):
    return THEMES.get(name, DEFAULT_STYLE)
end
