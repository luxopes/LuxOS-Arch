# lsl: link libX11.so.6 libgtk-3.so.0 libgdk-3.so.0 libgdk_pixbuf-2.0.so.0 libgio-2.0.so.0 libgobject-2.0.so.0 libglib-2.0.so.0
# LuxOS - ostra ikona okna pro Alt+Tab (/usr/lib/luxos/luxos-wm-icon, drive luxos_wm_icon.py).
#
#   luxos-wm-icon OKNO INSTANCE TRIDA      (spousti luxos-appname-watch pri aktivaci okna)
#
# GTK3 posila spravci oken ikonu z tematu jen v nabizenych velikostech; u ikon jen ve SVG napevno 48 px.
# Alt+Tab LuxOS kresli ikony 96 px (luxos-gtk3.css, #xfwm-tabwin), xfwm4 je zvetsil a byly rozmazane.
# Kdyz okno nema ikonu aspon 96 px, pridaji se do _NET_WM_ICON velikosti 128 a 192 z ikony aplikace
# (soubor .desktop, tema ikon). Puvodni velikosti zustavaji.
load env
load luxos_glib, glib as glib
load luxos_apps as apps
load luxos_x11 as x11
load luxos_sys as sys

WANT = 96            # velikost ikony v Alt+Tab
SIZES = [128, 192]   # pridane velikosti (192 = 96 pri dvojnasobnem meritku)
XA_CARDINAL = 6
LOOKUP_FORCE_SIZE = 16
INTERP_HYPER = 3

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

# _NET_WM_ICON -> [sirka, vyska, ARGB...]; None = okno neexistuje
function read_icons(window):
    prop = x11.atom("_NET_WM_ICON")
    out = []
    call x11.trap_push()
    unsafe:
        cells = __lsl_byte_zeros(48)
        base = x11.data(cells)
        ok = __lsl_qbe_call12(__lsl_symbol("XGetWindowProperty"), x11.xdisplay(), ptr(window), ptr(prop), 0, 16777216, 0, XA_CARDINAL, base, base + 8, base + 16, base + 24, base + 32)
        format = __lsl_qbe_s32(__lsl_qbe_load32(base + 8))
        count = __lsl_qbe_load64(base + 16)
        items = __lsl_qbe_load64(base + 32)
    end
    failed = x11.trap_pop() != 0 or ok != 0
    if items != 0:
        # format 32 vraci Xlib jako pole long (8 bajtu na x86_64), platne jsou dolni 4 bajty
        if format == 32 and not failed:
            unsafe:
                index = 0
                while index < count:
                    out.append(__lsl_qbe_load64(items + index * 8) & 4294967295)
                    index += 1
                end
            end
        end
        unsafe:
            call __lsl_qbe_call1(__lsl_symbol("XFree"), items)
        end
    end
    if failed:
        return None
    end
    return out
end

function largest(values):
    best = 0
    i = 0
    while i + 1 < len(values):
        w = values[i]
        h = values[i + 1]
        if w <= 0 or h <= 0 or i + 2 + w * h > len(values):
            break
        end
        best = max(best, min(w, h))
        i += 2 + w * h
    end
    return best
end

# Aplikace okna: StartupWMClass ma prednost (stejne jako luxos-appname-watch), pak jmeno souboru .desktop
function find_app(instance, wm_class):
    names = []
    for n in [instance, wm_class]:
        if n != "":
            names.append(n.lower())
        end
    end
    infos = apps.all_infos()
    for info in infos:
        wmc = apps.wm_class(info).lower()
        if wmc != "" and wmc in names:
            return info
        end
    end
    for info in infos:
        stem = apps.strip_desktop(apps.id(info)).lower()
        if stem in names:
            return info
        end
        for n in names:
            if stem.endswith("." + n):
                return info
            end
        end
    end
    return 0
end

# Pixbuf velikosti size s alfa kanalem z ikony aplikace (nova reference), 0 kdyz ikona neni
function icon_pixbuf(gicon, size):
    unsafe:
        theme = __lsl_qbe_call0(__lsl_symbol("gtk_icon_theme_get_default"))
        found = __lsl_qbe_call4(__lsl_symbol("gtk_icon_theme_lookup_by_gicon"), theme, ptr(gicon), ptr(size), LOOKUP_FORCE_SIZE)
        if found == 0:
            return 0
        end
        pb = __lsl_qbe_call2(__lsl_symbol("gtk_icon_info_load_icon"), found, 0)
        call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), found)
        if pb == 0:
            return 0
        end
        if __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gdk_pixbuf_get_width"), pb)) != size or __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gdk_pixbuf_get_height"), pb)) != size:
            scaled = __lsl_qbe_call4(__lsl_symbol("gdk_pixbuf_scale_simple"), pb, ptr(size), ptr(size), INTERP_HYPER)
            call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), pb)
            pb = scaled
        end
        if pb != 0 and __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gdk_pixbuf_get_has_alpha"), pb)) == 0:
            alpha = __lsl_qbe_call5(__lsl_symbol("gdk_pixbuf_add_alpha"), pb, 0, 0, 0, 0)
            call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), pb)
            pb = alpha
        end
        return pb
    end
end

# Puvodni hodnoty + velikosti SIZES (sirka, vyska, ARGB) jako pole long pro XChangeProperty
function write_icons(window, current, pixbufs):
    total = len(current)
    for size in SIZES:
        total += 2 + size * size
    end
    unsafe:
        buffer = __lsl_byte_zeros(total * 8)
        out = x11.data(buffer)
        at = 0
        for v in current:
            call __lsl_qbe_store64(ptr(out + at * 8), ptr(v))
            at += 1
        end
        index = 0
        for pb in pixbufs:
            size = SIZES[index]
            index += 1
            call __lsl_qbe_store64(ptr(out + at * 8), ptr(size))
            call __lsl_qbe_store64(ptr(out + at * 8 + 8), ptr(size))
            at += 2
            px = __lsl_qbe_call1(__lsl_symbol("gdk_pixbuf_get_pixels"), ptr(pb))
            stride = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gdk_pixbuf_get_rowstride"), ptr(pb)))
            y = 0
            while y < size:
                row = px + y * stride
                x = 0
                while x < size:
                    # RGBA v pameti -> ARGB (prohodit R a B)
                    v = __lsl_qbe_load32(row + x * 4)
                    call __lsl_qbe_store64(ptr(out + at * 8), ptr((v & 4278255360) | ((v & 255) << 16) | ((v >> 16) & 255)))
                    at += 1
                    x += 1
                end
                y += 1
            end
        end
        prop = x11.atom("_NET_WM_ICON")
        call x11.trap_push()
        call __lsl_qbe_call8(__lsl_symbol("XChangeProperty"), x11.xdisplay(), ptr(window), ptr(prop), XA_CARDINAL, 32, 0, out, ptr(total))
        call __lsl_qbe_call1(__lsl_symbol("XSync"), x11.xdisplay())
        call x11.trap_pop()
    end
    return 0
end

function sharpen(window, instance, wm_class):
    current = read_icons(window)
    if current == None or largest(current) >= WANT:
        return 0
    end
    info = find_app(instance, wm_class)
    if info == 0:
        return 0
    end
    unsafe:
        gicon = __lsl_qbe_call1(__lsl_symbol("g_app_info_get_icon"), ptr(info))
    end
    if gicon == 0:
        return 0
    end
    pixbufs = []
    for size in SIZES:
        pb = icon_pixbuf(gicon, size)
        if pb == 0:
            for p in pixbufs:
                unsafe:
                    call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), ptr(p))
                end
            end
            return 0
        end
        pixbufs.append(pb)
    end
    call write_icons(window, current, pixbufs)
    for p in pixbufs:
        unsafe:
            call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), ptr(p))
        end
    end
    return 0
end

function parse_window(value):
    v = value.lower()
    result = 0
    if v.startswith("0x"):
        for ch in v[2:]:
            d = "0123456789abcdef".find(ch)
            if d < 0:
                return 0
            end
            result = result * 16 + d
        end
        return result
    end
    for ch in v:
        d = "0123456789".find(ch)
        if d < 0:
            return 0
        end
        result = result * 10 + d
    end
    return result
end

if len(args) < 2:
    call eprint("usage: luxos-wm-icon WINDOW INSTANCE CLASS  (used by luxos-appname-watch)")
    call exit(2)
end
call sys.setenv("GDK_BACKEND", "x11")
ready = 0
unsafe:
    ready = __lsl_qbe_call2(__lsl_symbol("gtk_init_check"), 0, 0) & 255
end
if ready == 0:
    call exit(1)
end
instance = ""
wm_class = ""
if len(args) > 2:
    instance = args[2]
end
if len(args) > 3:
    wm_class = args[3]
end
call exit(sharpen(parse_window(args[1]), instance, wm_class))
