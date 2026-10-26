# lsl: internal-abi
# lsl: link libX11.so.6 libXfixes.so.3 libgdk-3.so.0 libcairo.so.2 libgobject-2.0.so.0 libglib-2.0.so.0
# LuxOS - primo Xlib pres spojeni GDK (cil linux-x86_64-gnu) pro Snimek obrazovky: okna aplikaci od nejvyssiho,
# globalni klavesy bez zabrani klavesnice (XGrabKey jako libkeybinder), sledovani korenoveho okna (filtr GDK)
# a kurzor mysi (XFixes).
#
#   atom(name), window_list() -> [[x, y, w, h], ...] od nejvyssiho (viditelna okna aplikaci na aktivni plose)
#   grab_key(keysym, mods) / ungrab_key(keysym, mods)   klavesa na korenovem okne (vcetne NumLock/CapsLock)
#   root_filter(f, data)       f(data, typ udalosti, okno, atom/keycode, stav) pro udalosti korenoveho okna;
#                              filtr se pridava jen jednou, root_watch(True/False) zapne/vypne sledovani
#   cursor_surface() -> [surface ARGB32, x, y, w, h] nebo [] (pixely zarizeni)
#
# Udalosti X: KeyPress 2, KeyRelease 3, ConfigureNotify 22, MapNotify 19, PropertyNotify 28.
load glib
load luxos_glib

KEY_PRESS = 2
KEY_RELEASE = 3
MAP_NOTIFY = 19
CONFIGURE_NOTIFY = 22
PROPERTY_NOTIFY = 28
CONTROL_MASK = 4

state = {"filter": 0, "handler": None, "data": None, "mask": -1, "atoms": {}}

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function cstr(text):
    unsafe:
        return __lsl_address(text) + 16
    end
end

function data(bytes):
    unsafe:
        return __lsl_qbe_load64(__lsl_address(bytes) + 24)
    end
end

function xdisplay():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("gdk_x11_get_default_xdisplay"))
    end
end

function root_xid():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("gdk_x11_get_default_root_xwindow"))
    end
end

function trap_push():
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("gdk_x11_display_error_trap_push"), __lsl_qbe_call0(__lsl_symbol("gdk_display_get_default")))
        return 0
    end
end

# Kod chyby X behem pasti (0 = bez chyby)
function trap_pop():
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gdk_x11_display_error_trap_pop"), __lsl_qbe_call0(__lsl_symbol("gdk_display_get_default"))))
    end
end

function atom(name):
    atoms = state["atoms"]
    if name in atoms:
        return atoms[name]
    end
    unsafe:
        value = __lsl_qbe_call3(__lsl_symbol("XInternAtom"), xdisplay(), cstr(name), 0)
        atoms[name] = value
        return value
    end
end

# Hodnoty vlastnosti formatu 32 (CARDINAL/ATOM/WINDOW) jako seznam; [] kdyz neni
function cardinals(window, name):
    out = []
    prop_atom = atom(name)
    unsafe:
        cells = __lsl_byte_zeros(48)
        base = data(cells)
        ok = __lsl_qbe_call12(__lsl_symbol("XGetWindowProperty"), xdisplay(), ptr(window), ptr(prop_atom), 0, 4096, 0, 0, base, base + 8, base + 16, base + 24, base + 32)
        if ok != 0:
            return out
        end
        format = __lsl_qbe_s32(__lsl_qbe_load32(base + 8))
        count = __lsl_qbe_load64(base + 16)
        items = __lsl_qbe_load64(base + 32)
        if items == 0:
            return out
        end
        if format == 32:
            index = 0
            while index < count:
                out.append(__lsl_qbe_load64(items + index * 8) & 4294967295)
                index += 1
            end
        end
        call __lsl_qbe_call1(__lsl_symbol("XFree"), items)
        return out
    end
end

# [x, y, sirka, vyska] klientske casti okna v korenovych souradnicich, [] kdyz okno zmizelo
function client_geometry(window):
    unsafe:
        dpy = xdisplay()
        cells = __lsl_byte_zeros(64)
        base = data(cells)
        if __lsl_qbe_call9(__lsl_symbol("XGetGeometry"), dpy, ptr(window), base, base + 8, base + 12, base + 16, base + 20, base + 24, base + 28) == 0:
            return []
        end
        w = __lsl_qbe_load32(base + 16)
        h = __lsl_qbe_load32(base + 20)
        if __lsl_qbe_call8(__lsl_symbol("XTranslateCoordinates"), dpy, ptr(window), root_xid(), 0, 0, base + 32, base + 36, base + 40) == 0:
            return []
        end
        return [__lsl_qbe_s32(__lsl_qbe_load32(base + 32)), __lsl_qbe_s32(__lsl_qbe_load32(base + 36)), w, h]
    end
end

# Viditelna okna aplikaci na aktivni plose od nejvyssiho (jako Wnck: normalni, dialogy, nastroje...),
# obdelnik vcetne ramecku xfwm4, u oken GTK se stinem (_GTK_FRAME_EXTENTS) jen viditelna cast
function window_list(skip):
    out = []
    call trap_push()
    root = root_xid()
    stack = cardinals(root, "_NET_CLIENT_LIST_STACKING")
    current = cardinals(root, "_NET_CURRENT_DESKTOP")
    ok_types = [atom("_NET_WM_WINDOW_TYPE_NORMAL"), atom("_NET_WM_WINDOW_TYPE_DIALOG"), atom("_NET_WM_WINDOW_TYPE_UTILITY"), atom("_NET_WM_WINDOW_TYPE_TOOLBAR"), atom("_NET_WM_WINDOW_TYPE_MENU"), atom("_NET_WM_WINDOW_TYPE_SPLASH")]
    hidden = atom("_NET_WM_STATE_HIDDEN")
    index = len(stack) - 1
    while index >= 0:
        window = stack[index]
        index -= 1
        if window in skip:
            continue
        end
        types = cardinals(window, "_NET_WM_WINDOW_TYPE")
        if len(types) > 0 and types[0] not in ok_types:
            continue
        end
        if hidden in cardinals(window, "_NET_WM_STATE"):
            continue
        end
        desktop = cardinals(window, "_NET_WM_DESKTOP")
        if len(desktop) > 0 and len(current) > 0 and desktop[0] != current[0] and desktop[0] != 4294967295:
            continue
        end
        geo = client_geometry(window)
        if len(geo) == 0 or geo[2] <= 0 or geo[3] <= 0:
            continue
        end
        rect = geo
        gtk_ext = cardinals(window, "_GTK_FRAME_EXTENTS")
        if len(gtk_ext) == 4 and geo[2] - gtk_ext[0] - gtk_ext[1] > 0 and geo[3] - gtk_ext[2] - gtk_ext[3] > 0:
            rect = [geo[0] + gtk_ext[0], geo[1] + gtk_ext[2], geo[2] - gtk_ext[0] - gtk_ext[1], geo[3] - gtk_ext[2] - gtk_ext[3]]
        else:
            ext = cardinals(window, "_NET_FRAME_EXTENTS")
            if len(ext) == 4:
                rect = [geo[0] - ext[0], geo[1] - ext[2], geo[2] + ext[0] + ext[1], geo[3] + ext[2] + ext[3]]
            end
        end
        out.append(rect)
    end
    call trap_pop()
    return out
end

# ---- globalni klavesy -----------------------------------------------------------------------------------------

# Varianty modifikatoru, ktere uzivatel nevnima (CapsLock 2, NumLock 16)
LOCK_VARIANTS = [0, 2, 16, 18]

function keycode(keysym):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("XKeysymToKeycode"), xdisplay(), ptr(keysym)) & 255
    end
end

# True pri uspechu (jinak klavesu uz zabral jiny program)
function grab_key(keysym, mods):
    code = keycode(keysym)
    if code == 0:
        return False
    end
    call trap_push()
    for extra in LOCK_VARIANTS:
        unsafe:
            # owner_events False, GrabModeAsync 1 pro mys i klavesnici
            call __lsl_qbe_call7(__lsl_symbol("XGrabKey"), xdisplay(), ptr(code), ptr(mods) | ptr(extra), root_xid(), 0, 1, 1)
        end
    end
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("XSync"), xdisplay(), 0)
    end
    return trap_pop() == 0
end

function ungrab_key(keysym, mods):
    code = keycode(keysym)
    if code == 0:
        return False
    end
    call trap_push()
    for extra in LOCK_VARIANTS:
        unsafe:
            call __lsl_qbe_call4(__lsl_symbol("XUngrabKey"), xdisplay(), ptr(code), ptr(mods) | ptr(extra), root_xid())
        end
    end
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("XFlush"), xdisplay())
    end
    call trap_pop()
    return True
end

# ---- sledovani korenoveho okna ------------------------------------------------------------------------------------

function root_filter(handler, bound):
    state["handler"] = handler
    state["data"] = bound
    if state["filter"] != 0:
        return 0
    end
    tracked = luxos_glib.track(filter_trampoline, 2, 0)
    state["filter"] = tracked[0]
    unsafe:
        root = __lsl_qbe_call0(__lsl_symbol("gdk_get_default_root_window"))
        call __lsl_qbe_call3(__lsl_symbol("gdk_window_add_filter"), root, __lsl_symbol("lsl_arch_callback_u3"), ptr(tracked[0]))
    end
    return 0
end

# GdkFilterFunc(GdkXEvent *, GdkEvent *, gpointer) -> GDK_FILTER_CONTINUE (0)
function filter_trampoline(unused, xevent, event):
    handler = state["handler"]
    if handler == None:
        return 0
    end
    unsafe:
        raw = ptr(xevent)
        kind = __lsl_qbe_s32(__lsl_qbe_load32(raw)) & 127
        window = 0
        detail = 0
        mods = 0
        if kind == 2 or kind == 3:
            window = __lsl_qbe_load64(raw + 32)
            mods = __lsl_qbe_load32(raw + 80)
            detail = __lsl_qbe_load32(raw + 84)
        elif kind == 28:
            window = __lsl_qbe_load64(raw + 32)
            detail = __lsl_qbe_load64(raw + 40)
        elif kind == 22 or kind == 19:
            window = __lsl_qbe_load64(raw + 40)
        else:
            return 0
        end
    end
    call handler(state["data"], kind, window, detail, mods)
    return 0
end

# Udalosti zmen vlastnosti (aktivni okno, poradi oken) a podoken (prekryti) korenoveho okna; vypnuti vrati masku
function root_watch(on):
    unsafe:
        root = __lsl_qbe_call0(__lsl_symbol("gdk_get_default_root_window"))
        if on:
            if state["mask"] == -1:
                state["mask"] = __lsl_qbe_call1(__lsl_symbol("gdk_window_get_events"), root)
            end
            # GDK_PROPERTY_CHANGE_MASK 1 << 16 | GDK_SUBSTRUCTURE_MASK 1 << 21
            call __lsl_qbe_call2(__lsl_symbol("gdk_window_set_events"), root, ptr(state["mask"]) | 65536 | 2097152)
        elif state["mask"] != -1:
            call __lsl_qbe_call2(__lsl_symbol("gdk_window_set_events"), root, ptr(state["mask"]))
            state["mask"] = -1
        end
        return 0
    end
end

# ---- kurzor (XFixes) ----------------------------------------------------------------------------------------------

# [cairo surface ARGB32, x, y, sirka, vyska] leveho horniho rohu kurzoru v pixelech zarizeni, [] kdyz nejde
function cursor_surface():
    unsafe:
        image = __lsl_qbe_call1(__lsl_symbol("XFixesGetCursorImage"), xdisplay())
        if image == 0:
            return []
        end
        x = __lsl_qbe_load32(image) & 65535
        y = __lsl_qbe_load32(image + 2) & 65535
        if x >= 32768:
            x = x - 65536
        end
        if y >= 32768:
            y = y - 65536
        end
        w = __lsl_qbe_load32(image + 4) & 65535
        h = __lsl_qbe_load32(image + 6) & 65535
        xhot = __lsl_qbe_load32(image + 8) & 65535
        yhot = __lsl_qbe_load32(image + 10) & 65535
        pixels = __lsl_qbe_load64(image + 24)
        if w == 0 or h == 0 or w * h > 262144:
            call __lsl_qbe_call1(__lsl_symbol("XFree"), image)
            return []
        end
        # XFixes dava predem vynasobene ARGB po 64bitovych slovech - stejny format jako CAIRO_FORMAT_ARGB32
        surface = __lsl_qbe_call3(__lsl_symbol("cairo_image_surface_create"), 0, w, h)
        call __lsl_qbe_call1(__lsl_symbol("cairo_surface_flush"), surface)
        target = __lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_data"), surface)
        stride = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_stride"), surface))
        row = 0
        while row < h:
            col = 0
            while col < w:
                call __lsl_qbe_store32(target + row * stride + col * 4, __lsl_qbe_load64(pixels + (row * w + col) * 8) & 4294967295)
                col += 1
            end
            row += 1
        end
        call __lsl_qbe_call1(__lsl_symbol("cairo_surface_mark_dirty"), surface)
        call __lsl_qbe_call1(__lsl_symbol("XFree"), image)
        return [surface, x - xhot, y - yhot, w, h]
    end
end
