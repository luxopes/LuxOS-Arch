# lsl: internal-abi
# lsl: link libcairo.so.2
# LuxOS - protokoly Waylandu pro shell (bar, Dock, zamek, snimek, schranka, emoji, monitory, necinnost)
# nad libluxos-wl (files/src/luxos-wl, C vygenerovane wayland-scannerem). Knihovna se nacita az za behu
# (dlopen): program bez ni bezi dal (X11 relace) a modul nepotrebuje nic mimo vlastni soubor, takze se
# da presunout do adresare systemovych vazeb LSL. LUXOS_WL_LIB = jina cesta (testy).
#
#   connect(name)          vlastni spojeni ("" = $WAYLAND_DISPLAY), udalosti v hlavni smycce GLib
#   attach(display)        spojeni GTK (luxos_layer.wl_display()): shell ma jen jeden soket
#   on_event(f)            f(kind, handle, a, b) pro vsechny udalosti (konstanty nize); nastavit pred connect
#   roundtrip(), disconnect(), has(rozhrani) -> verze nebo 0, available() -> knihovna nactena
#   bind_only([rozhrani..])  pred connect/attach: navazat jen tyto globaly (plocha jen vystupy)
# Vystupy:   outputs(), output_name(o), output_geometry(o) -> [x, y, w, h] (poloha z xdg-output),
#            output_scale(o), output_name_at(x, y) -> nazev vystupu s levym hornim rohem x, y ("" = neni)
# Okna:      toplevels() (wlr: ovladani), list_toplevels() (ext: identifikator pro snimek okna),
#            toplevel_app_id/title/identifier/state(t), activate(t), minimize(t, zap), maximize(t, zap),
#            close(t); STATE_* bity stavu
# Zamek:     lock() -> LOCKED/LOCK_FINISHED, lock_surface(o) -> SURFACE_CONFIGURE(s, w, h),
#            surface_begin(s) -> cairo surface (ARGB32) nebo 0, surface_commit(s, surface), KEY(s, keysym,
#            znak), unlock()
# Snimek:    capture_output(o, kurzor), capture_toplevel(lt, kurzor) -> READY(c, w, h)/FAILED(c, duvod),
#            capture_surface(c, w, h) -> kopie jako cairo surface, capture_write_png(c, w, h, cesta),
#            capture_format(c), capture_free(c)
# Schranka:  clipboard_set(text, primarni), clipboard_types(primarni) -> [mime..], CLIPBOARD_CHANGED(0,
#            primarni, text), clipboard_request(mime, primarni) -> CLIPBOARD_DATA(r, delka, chyba),
#            clipboard_text(r), clipboard_free(r)
# Emoji:     type_text(text) napise text do okna s fokusem (virtualni klavesnice)
# Monitory:  heads(), head_info(h) -> [jmeno, popis, zapnuto, x, y, w, h, mHz, meritko/1000, otoceni],
#            head_modes(h) -> [[w, h, mHz, preferovany, aktualni]..], output_config_begin(),
#            output_config_head(h, zapnuto, w, h, mHz, x, y, otoceni, meritko/1000), output_config_apply(test)
#            -> OUTPUT_CONFIG_RESULT(0, 1 ok / 0 chyba / 2 zruseno)
# Necinnost: idle_watch(ms) -> IDLE(w)/RESUMED(w), idle_release(w)
#
# Pamet: jeden zaznam zpetneho volani na cely proces (udalosti se rozesilaji podle druhu a handlu),
# objekty a texty drzi knihovna a uvolnuje je sama; nic neroste s poctem udalosti.
load glib, env

OUTPUT_NEW = 1
OUTPUT_REMOVED = 2
TOPLEVEL_NEW = 3
TOPLEVEL_CHANGED = 4
TOPLEVEL_CLOSED = 5
LIST_TOPLEVEL_NEW = 6
LIST_TOPLEVEL_CHANGED = 7
LIST_TOPLEVEL_CLOSED = 8
LOCKED = 9
LOCK_FINISHED = 10
SURFACE_CONFIGURE = 11
KEY = 12
CAPTURE_READY = 13
CAPTURE_FAILED = 14
CLIPBOARD_CHANGED = 15
CLIPBOARD_CANCELLED = 16
CLIPBOARD_DATA = 17
HEAD_NEW = 18
HEAD_CHANGED = 19
HEAD_REMOVED = 20
OUTPUT_CONFIG_RESULT = 21
IDLE = 22
RESUMED = 23
DISCONNECTED = 24

STATE_ACTIVATED = 1
STATE_MAXIMIZED = 2
STATE_MINIMIZED = 4
STATE_FULLSCREEN = 8

DEFAULT_LIB = "/usr/lib/luxos/libluxos-wl.so.0"
NAMES = ["lwl_set_handler", "lwl_bind_only", "lwl_connect", "lwl_attach", "lwl_disconnect", "lwl_roundtrip", "lwl_has",
    "lwl_output_count", "lwl_output_at", "lwl_output_name", "lwl_output_x", "lwl_output_y", "lwl_output_width",
    "lwl_output_height", "lwl_output_scale", "lwl_toplevel_count", "lwl_toplevel_at", "lwl_toplevel_app_id",
    "lwl_toplevel_title", "lwl_toplevel_identifier", "lwl_toplevel_state", "lwl_toplevel_activate",
    "lwl_toplevel_set_minimized", "lwl_toplevel_set_maximized", "lwl_toplevel_close", "lwl_lock",
    "lwl_lock_surface", "lwl_unlock", "lwl_surface_width", "lwl_surface_height", "lwl_surface_begin",
    "lwl_surface_commit", "lwl_capture_output", "lwl_capture_toplevel", "lwl_capture_data", "lwl_capture_stride",
    "lwl_capture_format", "lwl_capture_free", "lwl_clipboard_set", "lwl_clipboard_mime_types",
    "lwl_clipboard_request", "lwl_clipboard_data", "lwl_clipboard_free", "lwl_type", "lwl_head_count",
    "lwl_head_at", "lwl_head_name", "lwl_head_description", "lwl_head_enabled", "lwl_head_x", "lwl_head_y",
    "lwl_head_width", "lwl_head_height", "lwl_head_refresh", "lwl_head_scale", "lwl_head_transform",
    "lwl_head_mode_count", "lwl_head_mode", "lwl_output_config_begin", "lwl_output_config_head",
    "lwl_output_config_apply", "lwl_idle_watch", "lwl_idle_release"]

# cairo_format_t podle formatu wl_shm (0 ARGB8888, 1 XRGB8888)
CAIRO_ARGB32 = 0
CAIRO_RGB24 = 1

lib = 0
fns = {}
handler = None
record = 0

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

function flag(value):
    if value:
        return 1
    end
    return 0
end

# Vsechny funkce knihovny najednou: chybejici symbol = knihovna se nepouzije (zadny pad pozdeji).
function load_library():
    global lib
    if lib != 0:
        return True
    end
    path = env.get("LUXOS_WL_LIB", "")
    if path == "":
        path = DEFAULT_LIB
    end
    unsafe:
        handle = __lsl_qbe_call2(__lsl_symbol("dlopen"), cstr(path), 2)
    end
    if handle == 0:
        return False
    end
    found = {}
    for name in NAMES:
        unsafe:
            address = __lsl_qbe_call2(__lsl_symbol("dlsym"), handle, cstr(name))
        end
        if address == 0:
            return False
        end
        found[name] = address
    end
    for name in NAMES:
        fns[name] = found[name]
    end
    lib = handle
    return True
end

function available():
    return load_library()
end

function sym(name):
    return ptr(fns[name])
end

function call0(name):
    unsafe:
        return __lsl_qbe_icall0(sym(name))
    end
end

function call1(name, a):
    unsafe:
        return __lsl_qbe_icall1(sym(name), ptr(a))
    end
end

function call2(name, a, b):
    unsafe:
        return __lsl_qbe_icall2(sym(name), ptr(a), ptr(b))
    end
end

function text0(name):
    unsafe:
        return glib.from_c(__lsl_qbe_call0(sym(name)))
    end
end

function text1(name, a):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(sym(name), ptr(a)))
    end
end

# ---- udalosti ----

# C predava int: horni polovina registru neni definovana
function dispatch(kind, handle, a, b):
    if handler == None:
        return 0
    end
    unsafe:
        k = __lsl_qbe_s32(ptr(kind))
        h = __lsl_qbe_s32(ptr(handle))
        x = __lsl_qbe_s32(ptr(a))
        y = __lsl_qbe_s32(ptr(b))
    end
    call handler(k, h, x, y)
    return 0
end

function on_event(f):
    global handler, record
    handler = f
    if not load_library():
        return False
    end
    if record == 0:
        record = glib.record_new(dispatch, 4)
        unsafe:
            call __lsl_qbe_call2(sym("lwl_set_handler"), glib.callback_first(), ptr(record))
        end
    end
    return True
end

function bind_only(interfaces):
    if not load_library():
        return False
    end
    names = ",".join(interfaces)
    unsafe:
        call __lsl_qbe_call1(sym("lwl_bind_only"), cstr(names))
    end
    return True
end

function connect(name):
    if not load_library():
        return False
    end
    if name == None:
        name = ""
    end
    unsafe:
        return __lsl_qbe_icall1(sym("lwl_connect"), cstr(name)) == 1
    end
end

function attach(display):
    if display == 0 or not load_library():
        return False
    end
    return call1("lwl_attach", display) == 1
end

function disconnect():
    if lib == 0:
        return 0
    end
    unsafe:
        call __lsl_qbe_call0(sym("lwl_disconnect"))
    end
    return 0
end

function roundtrip():
    return call0("lwl_roundtrip") == 1
end

function has(interface):
    if lib == 0:
        return 0
    end
    unsafe:
        return __lsl_qbe_icall1(sym("lwl_has"), cstr(interface))
    end
end

# ---- vystupy ----

function outputs():
    result = []
    count = call0("lwl_output_count")
    index = 0
    while index < count:
        result.append(call1("lwl_output_at", index))
        index += 1
    end
    return result
end

function output_name(output):
    return text1("lwl_output_name", output)
end

function output_geometry(output):
    return [call1("lwl_output_x", output), call1("lwl_output_y", output), call1("lwl_output_width", output),
        call1("lwl_output_height", output)]
end

function output_scale(output):
    return call1("lwl_output_scale", output)
end

function output_name_at(x, y):
    if lib == 0:
        return ""
    end
    for output in outputs():
        if call1("lwl_output_x", output) == x and call1("lwl_output_y", output) == y:
            return output_name(output)
        end
    end
    return ""
end

# ---- okna ----

function toplevel_list(which):
    result = []
    count = call1("lwl_toplevel_count", which)
    index = 0
    while index < count:
        result.append(call2("lwl_toplevel_at", which, index))
        index += 1
    end
    return result
end

function toplevels():
    return toplevel_list(0)
end

function list_toplevels():
    return toplevel_list(1)
end

function toplevel_app_id(toplevel):
    return text1("lwl_toplevel_app_id", toplevel)
end

function toplevel_title(toplevel):
    return text1("lwl_toplevel_title", toplevel)
end

function toplevel_identifier(toplevel):
    return text1("lwl_toplevel_identifier", toplevel)
end

function toplevel_state(toplevel):
    return call1("lwl_toplevel_state", toplevel)
end

function activate(toplevel):
    return call1("lwl_toplevel_activate", toplevel) == 1
end

function minimize(toplevel, on):
    return call2("lwl_toplevel_set_minimized", toplevel, flag(on)) == 1
end

function maximize(toplevel, on):
    return call2("lwl_toplevel_set_maximized", toplevel, flag(on)) == 1
end

function close(toplevel):
    return call1("lwl_toplevel_close", toplevel) == 1
end

# ---- zamek ----

function lock():
    return call0("lwl_lock") == 1
end

function lock_surface(output):
    return call1("lwl_lock_surface", output)
end

function unlock():
    return call0("lwl_unlock") == 1
end

function surface_size(surface):
    return [call1("lwl_surface_width", surface), call1("lwl_surface_height", surface)]
end

# cairo surface nad volnym buferem plochy; po kresleni surface_commit (ten surface znici)
function surface_begin(surface):
    width = call1("lwl_surface_width", surface)
    height = call1("lwl_surface_height", surface)
    unsafe:
        data = __lsl_qbe_call1(sym("lwl_surface_begin"), ptr(surface))
        if data == 0:
            return 0
        end
        return __lsl_qbe_call5(__lsl_symbol("cairo_image_surface_create_for_data"), data, CAIRO_ARGB32, ptr(width), ptr(height), ptr(width) * 4)
    end
end

function surface_commit(surface, image):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("cairo_surface_flush"), ptr(image))
        call __lsl_qbe_call1(__lsl_symbol("cairo_surface_destroy"), ptr(image))
    end
    return call1("lwl_surface_commit", surface) == 1
end

# ---- snimek ----

function capture_output(output, cursor):
    return call2("lwl_capture_output", output, flag(cursor))
end

function capture_toplevel(toplevel, cursor):
    return call2("lwl_capture_toplevel", toplevel, flag(cursor))
end

# format wl_shm: 0 ARGB8888, 1 XRGB8888
function capture_format(capture):
    return call1("lwl_capture_format", capture)
end

# Vlastni kopie pixelu jako cairo image surface (volajici ji znici cairo.surface_destroy); 0 kdyz neni.
function capture_surface(capture, width, height):
    format = call1("lwl_capture_format", capture)
    stride = call1("lwl_capture_stride", capture)
    cairo_format = CAIRO_ARGB32
    if format == 1:
        cairo_format = CAIRO_RGB24
    elif format != 0:
        return 0
    end
    unsafe:
        data = __lsl_qbe_call1(sym("lwl_capture_data"), ptr(capture))
        if data == 0:
            return 0
        end
        image = __lsl_qbe_call3(__lsl_symbol("cairo_image_surface_create"), cairo_format, ptr(width), ptr(height))
        target = __lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_data"), image)
        target_stride = __lsl_qbe_icall1(__lsl_symbol("cairo_image_surface_get_stride"), image)
        row = 0
        while row < ptr(height):
            call __lsl_qbe_call3(__lsl_symbol("memcpy"), target + row * target_stride, data + row * ptr(stride), ptr(width) * 4)
            row += 1
        end
        call __lsl_qbe_call1(__lsl_symbol("cairo_surface_mark_dirty"), image)
        return image
    end
end

function capture_write_png(capture, width, height, path):
    image = capture_surface(capture, width, height)
    if image == 0:
        return False
    end
    unsafe:
        status = __lsl_qbe_icall2(__lsl_symbol("cairo_surface_write_to_png"), ptr(image), cstr(path))
        call __lsl_qbe_call1(__lsl_symbol("cairo_surface_destroy"), ptr(image))
    end
    return status == 0
end

function capture_free(capture):
    unsafe:
        call __lsl_qbe_call1(sym("lwl_capture_free"), ptr(capture))
    end
    return 0
end

# ---- schranka ----

function clipboard_set(text, primary):
    unsafe:
        return __lsl_qbe_icall2(sym("lwl_clipboard_set"), cstr(text), flag(primary)) == 1
    end
end

function clipboard_types(primary):
    result = []
    for line in text1("lwl_clipboard_mime_types", flag(primary)).split("\n"):
        if line != "":
            result.append(line)
        end
    end
    return result
end

function clipboard_request(mime, primary):
    unsafe:
        return __lsl_qbe_icall2(sym("lwl_clipboard_request"), cstr(mime), flag(primary))
    end
end

function clipboard_text(request):
    return text1("lwl_clipboard_data", request)
end

function clipboard_free(request):
    unsafe:
        call __lsl_qbe_call1(sym("lwl_clipboard_free"), ptr(request))
    end
    return 0
end

# ---- psani ----

function type_text(text):
    unsafe:
        return __lsl_qbe_icall1(sym("lwl_type"), cstr(text)) == 1
    end
end

# ---- monitory ----

function heads():
    result = []
    count = call0("lwl_head_count")
    index = 0
    while index < count:
        result.append(call1("lwl_head_at", index))
        index += 1
    end
    return result
end

function head_info(head):
    return [text1("lwl_head_name", head), text1("lwl_head_description", head), call1("lwl_head_enabled", head) == 1,
        call1("lwl_head_x", head), call1("lwl_head_y", head), call1("lwl_head_width", head),
        call1("lwl_head_height", head), call1("lwl_head_refresh", head), call1("lwl_head_scale", head),
        call1("lwl_head_transform", head)]
end

function head_modes(head):
    result = []
    count = call1("lwl_head_mode_count", head)
    index = 0
    while index < count:
        mode = []
        field = 0
        while field < 5:
            unsafe:
                mode.append(__lsl_qbe_icall3(sym("lwl_head_mode"), ptr(head), ptr(index), ptr(field)))
            end
            field += 1
        end
        result.append(mode)
        index += 1
    end
    return result
end

function output_config_begin():
    return call0("lwl_output_config_begin") == 1
end

function output_config_head(head, enabled, width, height, refresh, x, y, transform, scale):
    unsafe:
        return __lsl_qbe_icall9(sym("lwl_output_config_head"), ptr(head), flag(enabled), ptr(width), ptr(height), ptr(refresh), ptr(x), ptr(y), ptr(transform), ptr(scale)) == 1
    end
end

function output_config_apply(test_only):
    return call1("lwl_output_config_apply", flag(test_only)) == 1
end

# ---- necinnost ----

function idle_watch(ms):
    return call1("lwl_idle_watch", ms)
end

function idle_release(watch):
    unsafe:
        call __lsl_qbe_call1(sym("lwl_idle_release"), ptr(watch))
    end
    return 0
end
