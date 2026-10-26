"""LuxOS - QR kody site Wi-Fi: text WIFI:..., kodovani a cteni QR kodu (zxing-cpp), udaje z NetworkManageru.

Format (ZXing / Android / iOS):  WIFI:T:WPA;S:<ssid>;P:<heslo>;H:true;;
  T = WPA (WPA/WPA2), SAE (WPA3), WEP nebo nopass; znaky \\ ; , : " se v S a P escapuji zpetnym lomitkem.

QR kody kresli i cte knihovna zxing-cpp (libZXing, C API pres ctypes; 2 MB, bez ImageMagicku jako zbar).
LUXOS_ZXING_LIB prepise cestu ke knihovne (testy bez instalace).
"""
import ctypes
import os
import subprocess

SPECIAL = '\\;,:"'


# ---- text WIFI: ---------------------------------------------------------------------
def escape(value):
    return "".join("\\" + c if c in SPECIAL else c for c in value)


def security_type(key_mgmt):
    """Typ T: z key-mgmt NetworkManageru; None = nepodporovano (podnikova sit 802.1X)."""
    km = (key_mgmt or "").strip().lower()
    if km in ("", "none", "owe"):
        return "nopass" if km != "none" else "WEP"   # key-mgmt none = staticke WEP
    if km == "wpa-psk":
        return "WPA"
    if km == "sae":
        return "SAE"
    return None


def wifi_payload(ssid, password="", security="WPA", hidden=False):
    if security not in ("WPA", "SAE", "WEP", "nopass"):
        raise ValueError(security)
    if security == "nopass":
        password = ""
    text = f"WIFI:T:{security};S:{escape(ssid)};"
    if password:
        text += f"P:{escape(password)};"
    if hidden:
        text += "H:true;"
    return text + ";"


def _split_fields(body):
    """Rozdeli 'T:WPA;S:a\\;b;;' na pole s ohledem na escapovani."""
    fields, cur, esc = [], [], False
    for c in body:
        if esc:
            cur.append(c)
            esc = False
        elif c == "\\":
            esc = True
        elif c == ";":
            fields.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    if cur:
        fields.append("".join(cur))
    return fields


def _raw_fields(body):
    """Totez, ale hodnoty zustanou neescapovane - kvuli rozliseni uvozovek a escapovanych uvozovek."""
    fields, cur, esc = [], [], False
    for c in body:
        if esc:
            cur.append(c)
            esc = False
        elif c == "\\":
            cur.append(c)
            esc = True
        elif c == ";":
            fields.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    if cur:
        fields.append("".join(cur))
    return fields


def parse_wifi(text):
    """Text QR kodu -> {"ssid", "password", "security", "hidden"} nebo None (neni sit Wi-Fi)."""
    if not text or not text[:5].upper() == "WIFI:":
        return None
    body = text[5:]
    info = {"ssid": "", "password": "", "security": "WPA", "hidden": False}
    t_seen = False
    for raw, value in zip(_raw_fields(body), _split_fields(body)):
        if ":" not in raw:
            continue
        key = raw.split(":", 1)[0].upper()
        value = value[len(key) + 1:]
        rawval = raw[len(key) + 1:]
        # "abc" v neescapovanych uvozovkach (ZXing: hexadecimalni retezec jako text)
        if len(rawval) >= 2 and rawval[0] == '"' and rawval.endswith('"') and not rawval.endswith('\\"'):
            value = value[1:-1]
        if key == "S":
            info["ssid"] = value
        elif key == "P":
            info["password"] = value
        elif key == "T":
            t_seen = True
            v = value.strip().upper()
            info["security"] = {"WPA2": "WPA", "WPA3": "SAE", "NOPASS": "nopass", "": "nopass"}.get(v, v)
        elif key == "H":
            info["hidden"] = value.strip().lower() == "true"
    if not info["ssid"]:
        return None
    if not t_seen:
        info["security"] = "WPA" if info["password"] else "nopass"
    if info["security"] not in ("WPA", "SAE", "WEP", "nopass"):
        info["security"] = "WPA"   # neznamy typ (napr. WPA2-EAP): zkusit jako heslo
    return info


# ---- zxing-cpp ----------------------------------------------------------------------
_LIB = None
FORMAT_LUM = 0x01000000
FORMAT_BGRA = 0x04020100
FORMAT_RGBA = 0x04000102


class QRError(Exception):
    pass


def _lib():
    global _LIB
    if _LIB is not None:
        return _LIB
    names = [os.environ.get("LUXOS_ZXING_LIB") or "", "libZXing.so.4", "libZXing.so"]
    lib = None
    for name in names:
        if not name:
            continue
        try:
            lib = ctypes.CDLL(name)
            break
        except OSError:
            continue
    if lib is None:
        raise QRError("libZXing (zxing-cpp) is not installed")
    V, I, B = ctypes.c_void_p, ctypes.c_int, ctypes.c_bool
    sig = {
        "ZXing_BarcodeFormatFromString": (I, [ctypes.c_char_p]),
        "ZXing_CreatorOptions_new": (V, [I]),
        "ZXing_CreatorOptions_setOptions": (None, [V, ctypes.c_char_p]),
        "ZXing_CreatorOptions_delete": (None, [V]),
        "ZXing_CreateBarcodeFromText": (V, [ctypes.c_char_p, I, V]),
        "ZXing_Barcode_delete": (None, [V]),
        "ZXing_WriterOptions_new": (V, []),
        "ZXing_WriterOptions_setScale": (None, [V, I]),
        "ZXing_WriterOptions_setAddQuietZones": (None, [V, B]),
        "ZXing_WriterOptions_delete": (None, [V]),
        "ZXing_WriteBarcodeToImage": (V, [V, V]),
        "ZXing_Image_data": (ctypes.POINTER(ctypes.c_uint8), [V]),
        "ZXing_Image_width": (I, [V]),
        "ZXing_Image_height": (I, [V]),
        "ZXing_Image_delete": (None, [V]),
        "ZXing_ImageView_new": (V, [ctypes.c_char_p, I, I, I, I, I]),
        "ZXing_ImageView_delete": (None, [V]),
        "ZXing_ReaderOptions_new": (V, []),
        "ZXing_ReaderOptions_setFormats": (None, [V, ctypes.POINTER(I), I]),
        "ZXing_ReaderOptions_setTryHarder": (None, [V, B]),
        "ZXing_ReaderOptions_setTryInvert": (None, [V, B]),
        "ZXing_ReaderOptions_delete": (None, [V]),
        "ZXing_ReadBarcodes": (V, [V, V]),
        "ZXing_Barcodes_size": (I, [V]),
        "ZXing_Barcodes_at": (V, [V, I]),
        "ZXing_Barcodes_delete": (None, [V]),
        "ZXing_Barcode_text": (V, [V]),
        "ZXing_LastErrorMsg": (V, []),
        "ZXing_free": (None, [V]),
    }
    for name, (res, args) in sig.items():
        fn = getattr(lib, name)
        fn.restype = res
        fn.argtypes = args
    lib.qr_format = lib.ZXing_BarcodeFormatFromString(b"QRCode")
    _LIB = lib
    return lib


def available():
    try:
        _lib()
        return True
    except (QRError, AttributeError):
        return False


def _take_string(lib, ptr):
    if not ptr:
        return ""
    try:
        return ctypes.string_at(ptr).decode("utf-8", "replace")
    finally:
        lib.ZXing_free(ptr)


def encode(text, ec_level="M"):
    """Text -> matice QR kodu bez okraje: seznam radku, kazdy seznam 0/1 (1 = cerny modul).
    Text jen v ASCII se zakoduje bez ECI (nejsirsi podpora ctecek), jinak UTF-8 s ECI 26."""
    lib = _lib()
    data = text.encode("utf-8")
    options = f"ecLevel={ec_level}"
    if not text.isascii():
        options += ",eci=26"
    opts = lib.ZXing_CreatorOptions_new(lib.qr_format)
    lib.ZXing_CreatorOptions_setOptions(opts, options.encode())
    bc = lib.ZXing_CreateBarcodeFromText(data, len(data), opts)
    lib.ZXing_CreatorOptions_delete(opts)
    if not bc:
        raise QRError(_take_string(lib, lib.ZXing_LastErrorMsg()) or "QR code could not be created")
    wopts = lib.ZXing_WriterOptions_new()
    lib.ZXing_WriterOptions_setScale(wopts, 1)
    lib.ZXing_WriterOptions_setAddQuietZones(wopts, False)
    img = lib.ZXing_WriteBarcodeToImage(bc, wopts)
    lib.ZXing_WriterOptions_delete(wopts)
    lib.ZXing_Barcode_delete(bc)
    if not img:
        raise QRError(_take_string(lib, lib.ZXing_LastErrorMsg()) or "QR code could not be drawn")
    try:
        w, h = lib.ZXing_Image_width(img), lib.ZXing_Image_height(img)
        raw = ctypes.string_at(lib.ZXing_Image_data(img), w * h)
    finally:
        lib.ZXing_Image_delete(img)
    return [[1 if raw[y * w + x] < 128 else 0 for x in range(w)] for y in range(h)]


def decode(data, width, height, fmt=FORMAT_LUM, stride=None, harder=True):
    """Najde QR kody v obrazku (bajty, Lum = 1 bajt/pixel, BGRA/RGBA = 4) a vrati jejich texty."""
    lib = _lib()
    pix = 1 if fmt == FORMAT_LUM else 4
    stride = stride or width * pix
    buf = bytes(data)        # drzet odkaz: ImageView data nekopiruje
    if len(buf) < stride * (height - 1) + width * pix:
        return []
    iv = lib.ZXing_ImageView_new(buf, width, height, fmt, stride, pix)
    if not iv:
        return []
    opts = lib.ZXing_ReaderOptions_new()
    formats = (ctypes.c_int * 1)(lib.qr_format)
    lib.ZXing_ReaderOptions_setFormats(opts, formats, 1)
    lib.ZXing_ReaderOptions_setTryHarder(opts, harder)
    lib.ZXing_ReaderOptions_setTryInvert(opts, harder)
    texts = []
    try:
        res = lib.ZXing_ReadBarcodes(iv, opts)
        if res:
            for i in range(lib.ZXing_Barcodes_size(res)):
                t = _take_string(lib, lib.ZXing_Barcode_text(lib.ZXing_Barcodes_at(res, i)))
                if t:
                    texts.append(t)
            lib.ZXing_Barcodes_delete(res)
    finally:
        lib.ZXing_ReaderOptions_delete(opts)
        lib.ZXing_ImageView_delete(iv)
    return texts


# ---- NetworkManager -----------------------------------------------------------------
NMCLI = os.environ.get("LUXOS_NMCLI") or "nmcli"


def _nmcli(args, timeout=10, root=False):
    cmd = ([os.environ.get("LUXOS_PKEXEC") or "pkexec"] if root else []) + [NMCLI] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)
    return r.returncode, r.stdout, r.stderr


def active_wifi():
    """Aktivni pripojeni Wi-Fi: {"uuid", "name", "device"} nebo None."""
    rc, out, _err = _nmcli(["-t", "-f", "TYPE,UUID,DEVICE,NAME", "connection", "show", "--active"])
    if rc != 0:
        return None
    for line in out.splitlines():
        parts = _split_terse(line)
        if len(parts) >= 4 and parts[0] == "802-11-wireless":
            return {"uuid": parts[1], "device": parts[2], "name": parts[3]}
    return None


def _split_terse(line):
    """Radek nmcli -t: pole oddelena ':' (v hodnotach escapovane '\\:')."""
    parts, cur, esc = [], [], False
    for c in line:
        if esc:
            cur.append(c)
            esc = False
        elif c == "\\":
            esc = True
        elif c == ":":
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    parts.append("".join(cur))
    return parts


FIELDS = ("802-11-wireless.ssid", "802-11-wireless.hidden", "802-11-wireless-security.key-mgmt",
          "802-11-wireless-security.psk", "802-11-wireless-security.wep-key0")


def parse_connection(output):
    """Vystup 'nmcli --escape no -t -f ... connection show' -> slovnik pole: hodnota."""
    vals = {}
    for line in output.splitlines():
        key, sep, value = line.partition(":")
        if sep and key in FIELDS:
            vals[key] = value
    return vals


def wifi_details(uuid, secrets=True, root=False):
    """Udaje site pro QR kod. Vraci (info, chyba); info: ssid, security, password, hidden, need_auth."""
    args = ["--escape", "no", "-t", "-f", ",".join(FIELDS)]
    if secrets:
        args.insert(0, "--show-secrets")
    rc, out, err = _nmcli(args + ["connection", "show", "uuid", uuid], timeout=60 if root else 10, root=root)
    if rc != 0:
        if root and rc in (126, 127):
            return None, "cancelled"
        return None, (err.strip() or out.strip() or "nmcli failed")
    vals = parse_connection(out)
    sec = security_type(vals.get("802-11-wireless-security.key-mgmt", ""))
    if "802-11-wireless-security.key-mgmt" not in vals:
        sec = "nopass"
    info = {"ssid": vals.get("802-11-wireless.ssid", ""), "security": sec,
            "hidden": vals.get("802-11-wireless.hidden", "").strip() == "yes", "password": ""}
    if sec in ("WPA", "SAE"):
        info["password"] = vals.get("802-11-wireless-security.psk", "")
    elif sec == "WEP":
        info["password"] = vals.get("802-11-wireless-security.wep-key0", "")
    # Heslo bez opravneni (systemove pripojeni, polkit) nmcli vrati prazdne
    info["need_auth"] = sec in ("WPA", "SAE", "WEP") and not info["password"]
    return info, None


def connect_args(info):
    """Argumenty nmcli pro pripojeni k siti z QR kodu."""
    args = ["device", "wifi", "connect", info["ssid"]]
    if info.get("security") != "nopass" and info.get("password"):
        args += ["password", info["password"]]
        if info.get("security") == "WEP":
            args += ["wep-key-type", "key"]
    if info.get("hidden"):
        args += ["hidden", "yes"]
    return args


def connect(info, timeout=60):
    """Pripoji se k siti (nmcli). Vraci (ok, zprava)."""
    rc, out, err = _nmcli(["--wait", str(timeout)] + connect_args(info), timeout=timeout + 10)
    return rc == 0, (err.strip() or out.strip())
