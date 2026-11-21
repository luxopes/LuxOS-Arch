# lsl: link libgdk_pixbuf-2.0.so.0 libgio-2.0.so.0 libgobject-2.0.so.0 libglib-2.0.so.0
# LuxOS - profilova fotka uzivatele (prihlasovaci a zamykaci obrazovka, nabidka, Ovladaci centrum); drive
# files/python/luxos_avatar.py (Ucet LuxAI si fotku cte sam, photo_path v luxos-account).
#
# Fotka se ulozi jako ctverec PNG do ~/.face (cte ho zamykaci obrazovka a Ovladaci centrum) a preda se
# AccountsService (SetIconFile): ta si ji zkopiruje do /var/lib/AccountsService/icons, odkud ji bere
# prihlasovaci obrazovka. Vlastni ucet smi aktivni uzivatel menit bez hesla (polkit change-own-user-data).
#
#   crop_rect(w, h, view, zoom, ox, oy) -> [x, y, strana]   vyrez obrazku pod kruhem v pixelech obrazku
#   clamp_offset(w, h, view, zoom, ox, oy) -> [ox, oy]      posun, aby kruh zustal cely zakryty
#   render(pixbuf, rect, size)       ctvercovy GdkPixbuf size x size z vyrezu (nova reference)
#   load(path)                       fotka otocena podle EXIF, nejvys MAX_SOURCE px (0 kdyz to neni obrazek)
#   save(pixbuf) / remove() -> "" nebo text chyby, current() -> cesta nebo ""
# Testy: LUXOS_ACCOUNTS_FAKE=soubor - misto AccountsService se cesta zapise do souboru.
load env
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_sys as sys

SIZE = 384                 # vystup: ostry i na HiDPI (avatar prihlaseni ~104 px x meritko)
MAX_ZOOM = 4.0
MAX_SOURCE = 2048          # vetsi fotky se pri nacteni zmensi (pamet, plynule posouvani)
ACCOUNTS = "org.freedesktop.Accounts"
ACCOUNTS_PATH = "/org/freedesktop/Accounts"
USER_IFACE = "org.freedesktop.Accounts.User"

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

function face_path():
    return glib.home_dir() + "/.face"
end

# ---- geometrie orezu ------------------------------------------------------------------

# Meritko, pri kterem kratsi strana obrazku presne vyplni kruh o prumeru view
function base_scale(w, h, view):
    return Float(view) / max(1, min(w, h))
end

# Posun stredu obrazku proti stredu kruhu (px okna) tak, aby kruh nikdy nebyl prazdny
function clamp_offset(w, h, view, zoom, ox, oy):
    s = base_scale(w, h, view) * zoom
    mx = max(0.0, (w * s - view) / 2)
    my = max(0.0, (h * s - view) / 2)
    return [max(-mx, min(mx, Float(ox))), max(-my, min(my, Float(oy)))]
end

function crop_rect(w, h, view, zoom, ox, oy):
    zoom = max(1.0, min(MAX_ZOOM, Float(zoom)))
    off = clamp_offset(w, h, view, zoom, ox, oy)
    s = base_scale(w, h, view) * zoom
    side = view / s
    cx = w / 2.0 - off[0] / s
    cy = h / 2.0 - off[1] / s
    return [max(0.0, min(w - side, cx - side / 2)), max(0.0, min(h - side, cy - side / 2)), side]
end

# ---- obrazky (GdkPixbuf) ----------------------------------------------------------------

function width(pixbuf):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gdk_pixbuf_get_width"), ptr(pixbuf)))
    end
end

function height(pixbuf):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gdk_pixbuf_get_height"), ptr(pixbuf)))
    end
end

function unref(object):
    unsafe:
        if ptr(object) != 0:
            call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), ptr(object))
        end
    end
end

# Vyrez rect [x, y, strana] zmenseny/zvetseny na size x size (RGB, bez pruhlednosti)
function render(pixbuf, rect, size):
    k = Float(size) / rect[2]
    dx = Float(-rect[0] * k)
    dy = Float(-rect[1] * k)
    unsafe:
        out = __lsl_qbe_call5(__lsl_symbol("gdk_pixbuf_new"), 0, 0, 8, ptr(size), ptr(size))
        call __lsl_qbe_call2(__lsl_symbol("gdk_pixbuf_fill"), out, 4294967295)
        if __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gdk_pixbuf_get_has_alpha"), ptr(pixbuf))) != 0:
            # pruhledne PNG na bilem pozadi (jinak by vysly cerne okraje); GDK_INTERP_HYPER
            call __lsl_qbe_call12(__lsl_symbol("gdk_pixbuf_composite"), ptr(pixbuf), out, 0, 0, ptr(size), ptr(size), Float(dx), Float(dy), Float(k), Float(k), 3, 255)
        else:
            call __lsl_qbe_call11(__lsl_symbol("gdk_pixbuf_scale"), ptr(pixbuf), out, 0, 0, ptr(size), ptr(size), Float(dx), Float(dy), Float(k), Float(k), 3)
        end
        return out
    end
end

# Fotka ze souboru otocena podle EXIF a zmensena na nejvys MAX_SOURCE px; 0 pri chybe
function load(path):
    unsafe:
        cell = __lsl_byte_zeros(8)
        raw = __lsl_qbe_call2(__lsl_symbol("gdk_pixbuf_new_from_file"), cstr(path), __lsl_qbe_load64(__lsl_address(cell) + 24))
        if raw == 0:
            error = __lsl_qbe_load64(__lsl_qbe_load64(__lsl_address(cell) + 24))
            if error != 0:
                call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
            end
            return 0
        end
        turned = __lsl_qbe_call1(__lsl_symbol("gdk_pixbuf_apply_embedded_orientation"), raw)
        if turned != 0:
            call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), raw)
            raw = turned
        end
        pb = raw
    end
    w = width(pb)
    h = height(pb)
    if max(w, h) <= MAX_SOURCE:
        return pb
    end
    k = Float(MAX_SOURCE) / max(w, h)
    small = scaled(pb, max(1, round_half_even(w * k)), max(1, round_half_even(h * k)))
    call unref(pb)
    return small
end

function round_half_even(value):
    whole = Int(value)
    rest = value - whole
    if rest > 0.5 or (rest == 0.5 and whole % 2 != 0):
        return whole + 1
    end
    return whole
end

function scaled(pixbuf, w, h):
    unsafe:
        # GDK_INTERP_BILINEAR
        return __lsl_qbe_call4(__lsl_symbol("gdk_pixbuf_scale_simple"), ptr(pixbuf), ptr(w), ptr(h), 2)
    end
end

# PNG s nejvyssi kompresi; "" nebo zprava chyby
function save_png(pixbuf, path):
    unsafe:
        keys = glib.cstr_array(["compression"])
        values = glib.cstr_array(["9"])
        cell = __lsl_byte_zeros(8)
        where = __lsl_qbe_load64(__lsl_address(cell) + 24)
        ok = __lsl_qbe_call6(__lsl_symbol("gdk_pixbuf_savev"), ptr(pixbuf), cstr(path), cstr("png"), glib.array_data(keys), glib.array_data(values), where)
        if __lsl_qbe_s32(ok) != 0:
            return ""
        end
        error = __lsl_qbe_load64(where)
        message = "error"
        if error != 0:
            message = glib.from_c(__lsl_qbe_load64(error + 8))
            call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
        end
        return message
    end
end

function chmod(path, mode):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("chmod"), cstr(path), ptr(mode)) == 0
    end
end

function strerror():
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("strerror"), sys.errno()))
    end
end

# ---- AccountsService ------------------------------------------------------------------

function user_path(bus):
    return gio.call_values(bus, ACCOUNTS, ACCOUNTS_PATH, ACCOUNTS, "FindUserById", [sys.getuid()], "(x)", 5000)[0]
end

# SetIconFile v AccountsService; "" nebo text chyby (bez predpony "GDBus.Error:jmeno: ")
function set_icon_file(path):
    fake = env.get("LUXOS_ACCOUNTS_FAKE", "")
    if fake != "":
        call writefile(fake, path)
        return ""
    end
    message = ""
    try:
        bus = gio.system_bus()
        obj = user_path(bus)
        # ALLOW_INTERACTIVE_AUTHORIZATION: polkit se smi zeptat (cizi ucet, omezeni spravcem)
        call gio.call_sync_flags(bus, ACCOUNTS, obj, USER_IFACE, "SetIconFile", [path], "(s)", 20000, 2)
    else:
        message = String(last_error())
    end
    if message.find("GDBus.Error:") >= 0:
        message = message[message.find("GDBus.Error:"):]
        if message.find(": ") >= 0:
            message = message[message.find(": ") + 2:]
        end
    end
    return message
end

# IconFile z AccountsService, pokud soubor existuje (jinak "")
function accounts_icon():
    fake = env.get("LUXOS_ACCOUNTS_FAKE", "")
    path = ""
    if fake != "":
        path = glib.read_text(fake).strip()
    else:
        try:
            bus = gio.system_bus()
            path = String(gio.get_property_value(bus, ACCOUNTS, user_path(bus), USER_IFACE, "IconFile"))
        else:
            path = ""
        end
    end
    if path != "" and not glib.is_dir(path) and readable(path):
        return path
    end
    return ""
end

function readable(path):
    unsafe:
        # access(R_OK)
        return __lsl_qbe_call2(__lsl_symbol("access"), cstr(path), 4) == 0
    end
end

# Cesta k aktualni fotce (~/.face, jinak AccountsService) nebo ""
function current():
    face = face_path()
    info = glib.stat(face)
    if len(info) > 0 and info[0] > 0 and not glib.is_dir(face):
        return face
    end
    return accounts_icon()
end

# Ulozi ctvercovou fotku do ~/.face a preda ji AccountsService; "" nebo text chyby (~/.face plati i pri chybe
# AccountsService - zamykaci obrazovka a lista ho ukazou)
function save(pixbuf):
    face = face_path()
    tmp = face + ".tmp"
    error = save_png(pixbuf, tmp)
    if error == "" and not chmod(tmp, 420):
        error = strerror()
    end
    if error == "" and not glib.rename(tmp, face):
        error = strerror()
    end
    if error != "":
        call glib.unlink(tmp)
        return error
    end
    return set_icon_file(face)
end

# Odebere fotku (zustane avatar s pocatecnim pismenem); "" nebo text chyby
function remove():
    if not glib.unlink(face_path()) and sys.lexists(face_path()):
        return strerror()
    end
    return set_icon_file("")
end

# Pismeno do nahradniho avataru (jako na prihlasovaci obrazovce)
function initials(name):
    text = name.strip()
    if text == "":
        return "?"
    end
    return text[0].upper()
end

# Cele jmeno uzivatele (GECOS), jinak prihlasovaci jmeno; LUXOS_AVATAR_NAME jen pro snimky do Obchodu
# (jinak by se ukazalo skutecne jmeno z /etc/passwd)
function real_name():
    if env.get("LUXOS_AVATAR_NAME", "") != "":
        return env.get("LUXOS_AVATAR_NAME", "")
    end
    unsafe:
        name = glib.from_c(__lsl_qbe_call0(__lsl_symbol("g_get_real_name")))
        if name == "" or name == "Unknown":
            name = glib.from_c(__lsl_qbe_call0(__lsl_symbol("g_get_user_name")))
        end
        return name
    end
end
