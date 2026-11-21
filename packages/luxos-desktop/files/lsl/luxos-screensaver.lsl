# lsl: link libgdk-3.so.0 libgdk_pixbuf-2.0.so.0 libpangocairo-1.0.so.0 libpango-1.0.so.0 libcairo.so.2 libXext.so.6 libX11.so.6 libgio-2.0.so.0 libgobject-2.0.so.0 libglib-2.0.so.0
# LuxOS - setrice obrazovky (/usr/lib/xfce4-screensaver/luxos, styly vybira --style; drive Python):
#
#   desktop     tapeta plochy uzivatele a velke hodiny (vychozi; jako zamykaci obrazovka macOS) - presne
#               jako klidovy stav luxos-greeter a zamykaciho dialogu xfce4-screensaver LuxOS
#               (luxos-lock-ui.c), takze prechod setric -> dialog s heslem je plynuly
#   wallpapers  tapety LuxOS s pomalym prolinanim a velke hodiny
#   analog      tapety LuxOS s prolinanim a velke rucickove hodiny s datem (svetle/tmave podle vzhledu);
#               mimo prolinani se prekresluji jen hodiny (plynula vterinova rucicka, 20 snimku/s)
#   clock       velke hodiny na cernem pozadi, pomalu se posouvaji (setri OLED)
#   aurora      plynule se prelevajici barevne svetlo
#   photos      prezentace fotek z ~/Pictures (bez fotek tapety LuxOS)
#   logo        logo LuxOS pomalu pluje po obrazovce
#   blank       jen cerna (nahled volby Cerna obrazovka)
#
# xfce4-screensaver ho spousti s XSCREENSAVER_WINDOW (X okno, do ktereho se kresli; jedno na monitor).
# Bez teto promenne (nahled v nastaveni, test) otevre vlastni okno; --window na cele obrazovce, jinak 640x400.
#
# Testy bez obrazovky: --wallpaper [MONITOR] (tapeta stylu desktop), --info STYL (styl, snimky/s, pocet
# obrazku), --walls, --styles, --render STYL SIRKA VYSKA PNG [SEKUND OD STARTU], --analog-dirty SIRKA VYSKA,
# --hands TMAVE(0/1) CAS_UNIX PNG. LUXOS_SCREENSAVER_WALLS = slozka s tapetami misto /usr/share/backgrounds/luxos.
load env, math, random, process
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load cairo, pango
load luxos_i18n as i18n
load luxos_text
load luxos_saver as saver

X = {"win": 0, "display": 0, "interval": 0.05, "tick": 0.0, "viewable": True, "dpms_at": -10.0, "dpms_on": True,
     "dpms": -1, "area": 0}

function ptr(value):
    return glib.ptr(value)
end

# ---- okno xfce4-screensaver --------------------------------------------------------------------------------

# Monitor neni vypnuty (DPMS); dotaz nejvys jednou za 2 s, bez DPMS vzdy zapnuty
function screen_on():
    now = monotonic()
    if now - X["dpms_at"] < 2.0:
        return X["dpms_on"]
    end
    X["dpms_at"] = now
    unsafe:
        dpy = __lsl_qbe_call1(__lsl_symbol("gdk_x11_display_get_xdisplay"), ptr(X["display"]))
        cells = __lsl_byte_zeros(16)
        base = glib.array_data(cells)
        if X["dpms"] == -1:
            X["dpms"] = 0
            if __lsl_qbe_call3(__lsl_symbol("DPMSQueryExtension"), dpy, base, base + 4) != 0 and __lsl_qbe_call1(__lsl_symbol("DPMSCapable"), dpy) != 0:
                X["dpms"] = 1
            end
        end
        X["dpms_on"] = True
        if X["dpms"] == 1:
            call __lsl_qbe_call3(__lsl_symbol("DPMSInfo"), dpy, base, base + 8)
            level = __lsl_qbe_load32(base) & 65535
            state = __lsl_qbe_load32(base + 8) & 255
            X["dpms_on"] = state == 0 or level == 0     # DPMSModeOn
        end
    end
    return X["dpms_on"]
end

function tick(unused):
    now = monotonic()
    # mezera (xfce4-screensaver nas pri dialogu s heslem pozastavi) = obsah okna neplati
    if now - X["tick"] > 3 * X["interval"] + 0.2:
        call saver.invalidate()
    end
    X["tick"] = now
    win = X["win"]
    unsafe:
        viewable = __lsl_qbe_call1(__lsl_symbol("gdk_window_is_viewable"), ptr(win)) & 4294967295 != 0
    end
    if viewable and not X["viewable"]:
        call saver.invalidate()
    end
    X["viewable"] = viewable
    if not viewable or not screen_on():
        return True             # skryte okno / monitor vypnuty (DPMS): nekreslit
    end
    unsafe:
        w = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gdk_window_get_width"), ptr(win)))
        h = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gdk_window_get_height"), ptr(win)))
        region = __lsl_qbe_call1(__lsl_symbol("gdk_window_get_visible_region"), ptr(win))
        b = saver.dirty(w, h)
        if b != None:
            rect = __lsl_byte_zeros(16)
            rb = glib.array_data(rect)
            call __lsl_qbe_store32(rb, ptr(b[0]))
            call __lsl_qbe_store32(rb + 4, ptr(b[1]))
            call __lsl_qbe_store32(rb + 8, ptr(b[2]))
            call __lsl_qbe_store32(rb + 12, ptr(b[3]))
            call __lsl_qbe_call2(__lsl_symbol("cairo_region_intersect_rectangle"), region, rb)
        end
        if __lsl_qbe_call1(__lsl_symbol("cairo_region_is_empty"), region) & 4294967295 == 0:
            ctx = __lsl_qbe_call2(__lsl_symbol("gdk_window_begin_draw_frame"), ptr(win), region)
            cr = __lsl_qbe_call1(__lsl_symbol("gdk_drawing_context_get_cairo_context"), ctx)
            call saver.draw(cr, w, h, b == None)
            call __lsl_qbe_call2(__lsl_symbol("gdk_window_end_draw_frame"), ptr(win), ctx)
        end
        call __lsl_qbe_call1(__lsl_symbol("cairo_region_destroy"), region)
    end
    return True
end

function tick_once(unused):
    call tick(0)
    return False
end

# Odkryti, namapovani, zmena velikosti nebo viditelnosti naseho okna (Expose 12, VisibilityNotify 15,
# MapNotify 19, ConfigureNotify 22): hned cela obrazovka
function on_xevent(unused, xevent, event):
    unsafe:
        kind = __lsl_qbe_s32(__lsl_qbe_load32(ptr(xevent))) & 127
    end
    if kind == 12 or kind == 15 or kind == 19 or kind == 22:
        call saver.invalidate()
        call glib.idle_add_data(tick_once, 0)
    end
    return 0
end

# Kresleni do okna, ktere vytvoril xfce4-screensaver (jedno okno na monitor)
function run_foreign(xid, style):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("gdk_init"), 0, 0)
        display = __lsl_qbe_call0(__lsl_symbol("gdk_display_get_default"))
        if display == 0:
            call exit(1)
        end
        win = __lsl_qbe_call2(__lsl_symbol("gdk_x11_window_foreign_new_for_display"), display, ptr(xid))
        if win == 0:
            call exit(1)
        end
        monitor = ""
        mon = __lsl_qbe_call2(__lsl_symbol("gdk_display_get_monitor_at_window"), display, win)
        if mon != 0:
            model = __lsl_qbe_call1(__lsl_symbol("gdk_monitor_get_model"), mon)
            if model != 0:
                monitor = glib.from_c(model)
            end
        end
        X["display"] = display
        X["win"] = win
        # GDK_EXPOSURE_MASK 1 << 1 | GDK_STRUCTURE_MASK 1 << 15 | GDK_VISIBILITY_NOTIFY_MASK 1 << 17
        mask = __lsl_qbe_call1(__lsl_symbol("gdk_window_get_events"), win) & 4294967295
        call __lsl_qbe_call2(__lsl_symbol("gdk_window_set_events"), win, mask | 2 | 32768 | 131072)
        tracked = glib.track(on_xevent, 2, 0)
        call __lsl_qbe_call3(__lsl_symbol("gdk_window_add_filter"), win, __lsl_symbol("lsl_arch_callback_u3"), ptr(tracked[0]))
    end
    call saver.saver_init(style, monitor)
    X["interval"] = 1.0 / saver.fps()
    X["tick"] = monotonic()
    call glib.timeout_add_data(1000 // saver.fps(), tick, 0)
    call tick(0)
    call glib.main()
    return 0
end

# ---- vlastni okno (nahled v nastaveni, --window) -----------------------------------------------------------

function on_draw(cr, area):
    call saver.draw(cr, gtk.widget_get_allocated_width(area), gtk.widget_get_allocated_height(area), True)
    return False
end

function on_redraw(unused):
    call gtk.widget_queue_draw(X["area"])
    return True
end

function on_quit(event, widget):
    call gtk.main_quit()
    return True
end

function on_destroy(widget):
    call gtk.main_quit()
    return 0
end

function run_window(style, fullscreen):
    call gtk.init()
    call saver.saver_init(style, "")
    win = gtk.window_new("LuxOS")
    area = gtk.drawing_area_new()
    X["area"] = area
    call gtk.connect(area, "draw", on_draw)
    call gtk.container_add(win, area)
    call gtk.window_set_default_size(win, 640, 400)
    if fullscreen:
        call gtk.window_fullscreen(win)
        call gtk.connect(win, "key-press-event", on_quit)
        call gtk.connect(win, "button-press-event", on_quit)
    end
    call gtk.connect(win, "destroy", on_destroy)
    call glib.timeout_add_data(1000 // saver.fps(), on_redraw, 0)
    call gtk.widget_show_all(win)
    call gtk.main()
    return 0
end

# ---- testy bez obrazovky ----------------------------------------------------------------------------------

function render(style, w, h, out, elapsed):
    call saver.saver_init(style, "")
    saver.S["start"] = monotonic() - elapsed
    surf = saver.surface_new(cairo.FORMAT_RGB24, w, h)
    cr = cairo.create(surf)
    call saver.draw(cr, w, h, True)
    call cairo.destroy(cr)
    call cairo.surface_flush(surf)
    call cairo.surface_write_to_png(surf, out)
    return 0
end

function box_text(b):
    if b == None:
        return "full"
    end
    return String(b)
end

function analog_dirty_test(w, h):
    call saver.saver_init("analog", "")
    b = saver.dirty(w, h)
    print "first " + box_text(b)       # prvni snimek cely
    surf = saver.surface_new(cairo.FORMAT_RGB24, w, h)
    cr = cairo.create(surf)
    call saver.draw(cr, w, h, True)
    b = saver.dirty(w, h)
    g = saver.geometry(w, h)
    print "box " + box_text(b) + " " + String(g)
    # prolinani: cela obrazovka
    saver.S["start"] = saver.S["start"] - (saver.ANALOG_SLIDE - saver.ANALOG_FADE / 2)
    print "fade " + box_text(saver.dirty(w, h))
    call cairo.destroy(cr)
    return 0
end

function hands_test(dark, t, out):
    call saver.saver_init("analog", "")
    saver.A["dark"] = dark
    surf = saver.surface_new(cairo.FORMAT_ARGB32, 200, 200)
    cr = cairo.create(surf)
    call saver.draw_hands(cr, 200, 200, t)
    call cairo.destroy(cr)
    call cairo.surface_flush(surf)
    call cairo.surface_write_to_png(surf, out)
    print "face " + String(saver.colors()["face"])
    return 0
end

# Cislo okna z XSCREENSAVER_WINDOW: "0x2a00004" (xfce4-screensaver) nebo desitkove; 0 = neplatne
function parse_xid(text):
    text = text.strip().lower()
    base = 10
    if text.startswith("0x"):
        text = text[2:]
        base = 16
    end
    value = 0
    for ch in text:
        digit = "0123456789abcdef".find(ch)
        if digit < 0 or digit >= base:
            return 0
        end
        value = value * base + digit
    end
    return value
end

function arg_or(index, default):
    if len(args) > index:
        return args[index]
    end
    return default
end

function main():
    style = "desktop"
    index = 1
    while index < len(args) - 1:
        if args[index] == "--style":
            style = args[index + 1]
            break
        end
        index += 1
    end
    command = arg_or(1, "")
    if command == "--wallpaper":
        print saver.desktop_wallpaper(arg_or(2, ""))
    elif command == "--info":
        call saver.saver_init(arg_or(2, ""), "")
        print saver.S["style"] + " " + String(saver.fps()) + " " + String(len(saver.S["slides"]))
    elif command == "--walls":
        for path in saver.walls():
            print path
        end
    elif command == "--styles":
        print luxos_text.join(saver.STYLES, " ")
    elif command == "--render":
        call render(args[2], Int(args[3]), Int(args[4]), args[5], Float(arg_or(6, "0")))
    elif command == "--analog-dirty":
        call analog_dirty_test(Int(args[2]), Int(args[3]))
    elif command == "--hands":
        call hands_test(args[2] == "1", Float(args[3]), args[4])
    else:
        xid = env.get("XSCREENSAVER_WINDOW", "")
        if xid != "" and not ("--window" in args):
            call run_foreign(parse_xid(xid), style)
        else:
            call run_window(style, "--window" in args)
        end
    end
    return 0
end

call main()
