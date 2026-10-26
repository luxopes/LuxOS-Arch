"""LuxOS - profilova fotka uzivatele (prihlasovaci a zamykaci obrazovka, nabidka, Ovladaci centrum).

Fotka se ulozi jako ctverec PNG do ~/.face (cte ho zamykaci obrazovka xfce4-screensaver a Ovladaci
centrum) a preda se AccountsService (SetIconFile): ta si ji zkopiruje do /var/lib/AccountsService/icons,
odkud ji bere prihlasovaci obrazovka (luxos-greeter) a nabidka v liste (whiskermenu). Vlastni ucet
smi aktivni uzivatel menit bez hesla (polkit org.freedesktop.accounts.change-own-user-data).

  crop_rect(w, h, view, zoom, ox, oy)   vyrez obrazku pod kruhem (x, y, strana) v pixelech obrazku
  clamp_offset(w, h, view, zoom, ox, oy) posun obrazku tak, aby kruh zustal cely zakryty
  render(pixbuf, rect, size)            ctvercovy GdkPixbuf size x size z vyrezu
  save(pixbuf) / remove() / current()   ulozeni, odebrani a aktualni fotka

Testy: LUXOS_ACCOUNTS_FAKE=soubor - misto AccountsService se cesta zapise do souboru.
"""
import os

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gio, GLib  # noqa: E402

SIZE = 384                 # vystup: ostry i na HiDPI (avatar prihlaseni ~104 px x meritko)
MAX_ZOOM = 4.0
MAX_SOURCE = 2048          # vetsi fotky se pri nacteni zmensi (pamet, plynule posouvani)
ACCOUNTS = "org.freedesktop.Accounts"
ACCOUNTS_PATH = "/org/freedesktop/Accounts"
USER_IFACE = "org.freedesktop.Accounts.User"
ICONS_DIR = "/var/lib/AccountsService/icons"


def face_path():
    return os.path.join(os.path.expanduser("~"), ".face")


# ---- geometrie orezu ------------------------------------------------------------------
def base_scale(w, h, view):
    """Meritko, pri kterem kratsi strana obrazku presne vyplni kruh o prumeru view."""
    return view / max(1, min(w, h))


def clamp_offset(w, h, view, zoom, ox, oy):
    """Posun stredu obrazku proti stredu kruhu (px okna) tak, aby kruh nikdy nebyl prazdny."""
    s = base_scale(w, h, view) * zoom
    mx = max(0.0, (w * s - view) / 2)
    my = max(0.0, (h * s - view) / 2)
    return max(-mx, min(mx, ox)), max(-my, min(my, oy))


def crop_rect(w, h, view, zoom, ox, oy):
    """Ctverec pod kruhem v souradnicich obrazku: (x, y, strana)."""
    zoom = max(1.0, min(MAX_ZOOM, zoom))
    ox, oy = clamp_offset(w, h, view, zoom, ox, oy)
    s = base_scale(w, h, view) * zoom
    side = view / s
    cx = w / 2 - ox / s
    cy = h / 2 - oy / s
    x = max(0.0, min(w - side, cx - side / 2))
    y = max(0.0, min(h - side, cy - side / 2))
    return x, y, side


def render(pixbuf, rect, size=SIZE):
    """Vyrez rect (x, y, strana) zmenseny/zvetseny na size x size (RGB, bez pruhlednosti)."""
    x, y, side = rect
    k = size / side
    out = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, size, size)
    out.fill(0xffffffff)
    if pixbuf.get_has_alpha():
        # pruhledne PNG na bilem pozadi (jinak by vysly cerne okraje)
        pixbuf.composite(out, 0, 0, size, size, -x * k, -y * k, k, k, GdkPixbuf.InterpType.HYPER, 255)
    else:
        pixbuf.scale(out, 0, 0, size, size, -x * k, -y * k, k, k, GdkPixbuf.InterpType.HYPER)
    return out


def load(path):
    """Fotka ze souboru otocena podle EXIF a zmensena na nejvys MAX_SOURCE px. GLib.Error pri chybe."""
    pb =GdkPixbuf.Pixbuf.new_from_file(path)
    pb = pb.apply_embedded_orientation() or pb
    w, h = pb.get_width(), pb.get_height()
    if max(w, h) > MAX_SOURCE:
        k = MAX_SOURCE / max(w, h)
        pb = pb.scale_simple(max(1, round(w * k)), max(1, round(h * k)), GdkPixbuf.InterpType.BILINEAR)
    return pb


# ---- AccountsService ------------------------------------------------------------------
def _user_proxy():
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    path = bus.call_sync(ACCOUNTS, ACCOUNTS_PATH, ACCOUNTS, "FindUserById",
                         GLib.Variant("(x)", (os.getuid(),)), GLib.VariantType("(o)"),
                         Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
    return bus, path


def _set_icon_file(path):
    """SetIconFile v AccountsService; vraci None nebo text chyby."""
    fake = os.environ.get("LUXOS_ACCOUNTS_FAKE")
    if fake:
        with open(fake, "w", encoding="utf-8") as f:
            f.write(path)
        return None
    try:
        bus, obj = _user_proxy()
        bus.call_sync(ACCOUNTS, obj, USER_IFACE, "SetIconFile", GLib.Variant("(s)", (path,)), None,
                      Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, 20000, None)
        return None
    except GLib.Error as e:
        return Gio.DBusError.strip_remote_error(e) or e.message or str(e)


def accounts_icon():
    """IconFile z AccountsService, pokud soubor existuje (jinak None)."""
    fake = os.environ.get("LUXOS_ACCOUNTS_FAKE")
    if fake:
        try:
            with open(fake, encoding="utf-8") as f:
                path = f.read().strip()
        except OSError:
            return None
        return path if path and os.path.isfile(path) else None
    try:
        bus, obj = _user_proxy()
        res = bus.call_sync(ACCOUNTS, obj, "org.freedesktop.DBus.Properties", "Get",
                            GLib.Variant("(ss)", (USER_IFACE, "IconFile")), GLib.VariantType("(v)"),
                            Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
    except GLib.Error:
        return None
    return res if res and os.path.isfile(res) and os.access(res, os.R_OK) else None


def current():
    """Cesta k aktualni fotce (~/.face, jinak AccountsService) nebo None."""
    face = face_path()
    if os.path.isfile(face) and os.path.getsize(face) > 0:
        return face
    return accounts_icon()


def save(pixbuf):
    """Ulozi ctvercovou fotku do ~/.face a preda ji AccountsService. Vraci None nebo text chyby
    (~/.face plati i pri chybe AccountsService - zamykaci obrazovka a lista ho ukazou)."""
    face = face_path()
    tmp = face + ".tmp"
    try:
        pixbuf.savev(tmp, "png", ["compression"], ["9"])
        os.chmod(tmp, 0o644)
        os.replace(tmp, face)
    except (GLib.Error, OSError) as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return getattr(e, "strerror", None) or getattr(e, "message", None) or str(e)
    return _set_icon_file(face)


def remove():
    """Odebere fotku (zustane avatar s pocatecnim pismenem). Vraci None nebo text chyby."""
    try:
        os.unlink(face_path())
    except FileNotFoundError:
        pass
    except OSError as e:
        return e.strerror
    return _set_icon_file("")


def initials(name):
    """Pismeno do nahradniho avataru (jako na prihlasovaci obrazovce)."""
    return ((name or "").strip()[:1] or "?").upper()


def real_name():
    """Cele jmeno uzivatele (GECOS), jinak prihlasovaci jmeno."""
    return GLib.get_real_name() if GLib.get_real_name() not in ("", "Unknown") else GLib.get_user_name()
