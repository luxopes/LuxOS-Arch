# LuxOS - QR kod site Wi-Fi pro aplikace v LSL: text WIFI:..., kresleni a cteni QR kodu (zxing-cpp), udaje site
# z NetworkManageru a pripojeni k siti (nmcli); QR kod Wi-Fi a Kamera (drive files/python/luxos_qr.py).
#
# Format (ZXing / Android / iOS):  WIFI:T:WPA;S:<ssid>;P:<heslo>;H:true;;
#   T = WPA (WPA/WPA2), SAE (WPA3), WEP nebo nopass; znaky \ ; , : " se v S a P escapuji zpetnym lomitkem.
#
#   wifi_payload(ssid, heslo, typ, skryta) -> text, security_type(key-mgmt) -> typ nebo ""
#   parse_wifi(text) -> {"ssid", "password", "security", "hidden"} nebo None (text neni sit Wi-Fi)
#   available(), encode(text) -> [matice radku 0/1, chyba]   libZXing se nacita az za behu (dlopen)
#   decode(pixely, sirka, vyska, format, radek) -> texty QR kodu v obrazku, decode_surface(cairo RGB24)
#   active_wifi(text) / parse_connection(text) / details(vals) - rozbor vystupu nmcli
#   connect_args(info), add_args(info, uuid), connect(info, f, data) -> f(data, ok, zprava) az po nmcli
# LUXOS_ZXING_LIB prepise cestu ke knihovne (testy bez instalace).
load env, cairo
load luxos_glib, glib as glib

SPECIAL = "\\;,:\""
FIELDS = ["802-11-wireless.ssid", "802-11-wireless.hidden", "802-11-wireless-security.key-mgmt",
    "802-11-wireless-security.psk", "802-11-wireless-security.wep-key0"]
NAMES = ["ZXing_BarcodeFormatFromString", "ZXing_CreatorOptions_new", "ZXing_CreatorOptions_setOptions",
    "ZXing_CreatorOptions_delete", "ZXing_CreateBarcodeFromText", "ZXing_Barcode_delete", "ZXing_WriterOptions_new",
    "ZXing_WriterOptions_setScale", "ZXing_WriterOptions_setAddQuietZones", "ZXing_WriterOptions_delete",
    "ZXing_WriteBarcodeToImage", "ZXing_Image_data", "ZXing_Image_width", "ZXing_Image_height", "ZXing_Image_delete",
    "ZXing_LastErrorMsg", "ZXing_free", "ZXing_ImageView_new", "ZXing_ImageView_delete", "ZXing_ReaderOptions_new",
    "ZXing_ReaderOptions_setFormats", "ZXing_ReaderOptions_setTryHarder", "ZXing_ReaderOptions_setTryInvert",
    "ZXing_ReaderOptions_delete", "ZXing_ReadBarcodes", "ZXing_Barcodes_size", "ZXing_Barcodes_at",
    "ZXing_Barcodes_delete", "ZXing_Barcode_text"]
FORMAT_LUM = 16777216      # ZXing_ImageFormat_Lum 0x01000000
FORMAT_BGRA = 67240192     # ZXing_ImageFormat_BGRA 0x04020100 (cairo RGB24 na little endian)
SCAN_WIDTH = 800           # snimek kamery se pred ctenim zmensi (cteni bezi v hlavni smycce)

lib = {"tried": False, "fns": {}}

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function cstr(value):
    unsafe:
        return __lsl_address(value) + 16
    end
end

# ---- text WIFI: ---------------------------------------------------------------------

function escape(value):
    out = ""
    for ch in value:
        if SPECIAL.find(ch) >= 0:
            out += "\\"
        end
        out += ch
    end
    return out
end

# Typ T z key-mgmt NetworkManageru; "" = nepodporovano (podnikova sit 802.1X)
function security_type(key_mgmt):
    km = key_mgmt.strip().lower()
    if km == "" or km == "owe":
        return "nopass"
    end
    if km == "none":
        # staticke WEP
        return "WEP"
    end
    if km == "wpa-psk":
        return "WPA"
    end
    if km == "sae":
        return "SAE"
    end
    return ""
end

function wifi_payload(ssid, password, security, hidden):
    if security == "nopass":
        password = ""
    end
    text = "WIFI:T:" + security + ";S:" + escape(ssid) + ";"
    if password != "":
        text += "P:" + escape(password) + ";"
    end
    if hidden:
        text += "H:true;"
    end
    return text + ";"
end

# Rozdeli telo za WIFI: na pole podle neescapovaneho ';': [[surova hodnota, hodnota bez escapovani]]
function wifi_fields(body):
    fields = []
    raw = ""
    value = ""
    escaped = False
    for ch in body:
        if escaped:
            raw += ch
            value += ch
            escaped = False
        elif ch == "\\":
            raw += ch
            escaped = True
        elif ch == ";":
            fields.append([raw, value])
            raw = ""
            value = ""
        else:
            raw += ch
            value += ch
        end
    end
    if raw != "":
        fields.append([raw, value])
    end
    return fields
end

function parse_wifi(text):
    if text == None or len(text) < 5 or text[:5].upper() != "WIFI:":
        return None
    end
    info = {"ssid": "", "password": "", "security": "WPA", "hidden": False}
    t_seen = False
    for field in wifi_fields(text[5:]):
        raw = field[0]
        cut = raw.find(":")
        if cut < 0:
            continue
        end
        key = raw[:cut].upper()
        value = field[1][cut + 1:]
        rawval = raw[cut + 1:]
        # "abc" v neescapovanych uvozovkach (ZXing: hexadecimalni retezec jako text)
        if len(rawval) >= 2 and rawval[0] == "\"" and rawval.endswith("\"") and not rawval.endswith("\\\""):
            value = value[1:len(value) - 1]
        end
        if key == "S":
            info["ssid"] = value
        elif key == "P":
            info["password"] = value
        elif key == "T":
            t_seen = True
            v = value.strip().upper()
            aliases = {"WPA2": "WPA", "WPA3": "SAE", "NOPASS": "nopass", "": "nopass"}
            info["security"] = aliases.get(v, v)
        elif key == "H":
            info["hidden"] = value.strip().lower() == "true"
        end
    end
    if info["ssid"] == "":
        return None
    end
    if not t_seen:
        info["security"] = "WPA" if info["password"] != "" else "nopass"
    end
    if not (info["security"] in ["WPA", "SAE", "WEP", "nopass"]):
        # neznamy typ (napr. WPA2-EAP): zkusit jako heslo
        info["security"] = "WPA"
    end
    return info
end

# ---- zxing-cpp ----------------------------------------------------------------------

# Vsechny funkce knihovny najednou: chybejici symbol = QR kody nejsou k dispozici (zadny pad pozdeji)
function load_library():
    if lib["tried"]:
        return len(lib["fns"]) > 0
    end
    lib["tried"] = True
    for name in [env.get("LUXOS_ZXING_LIB", ""), "libZXing.so.4", "libZXing.so"]:
        if name == "":
            continue
        end
        unsafe:
            # RTLD_NOW
            handle = __lsl_qbe_call2(__lsl_symbol("dlopen"), cstr(name), 2)
        end
        if handle == 0:
            continue
        end
        found = {}
        for symbol in NAMES:
            unsafe:
                address = __lsl_qbe_call2(__lsl_symbol("dlsym"), handle, cstr(symbol))
            end
            if address == 0:
                return False
            end
            found[symbol] = address
        end
        lib["fns"] = found
        return True
    end
    return False
end

function available():
    return load_library()
end

# adresa funkce pro __lsl_qbe_callN (icall vraci jen 32 bitu, ukazatele by se orizly)
function fn(name):
    return ptr(lib["fns"][name])
end

function last_error(fallback):
    unsafe:
        raw = __lsl_qbe_call0(fn("ZXing_LastErrorMsg"))
        message = glib.from_c(raw)
        if raw != 0:
            call __lsl_qbe_call1(fn("ZXing_free"), raw)
        end
    end
    if message == "":
        return fallback
    end
    return message
end

function is_ascii(text):
    for ch in text:
        if ord(ch) > 127:
            return False
        end
    end
    return True
end

# Text -> [matice QR kodu bez okraje (radky 0/1, 1 = cerny modul), chyba]. Text jen v ASCII bez ECI
# (nejsirsi podpora ctecek), jinak UTF-8 s ECI 26.
function encode(text):
    if not load_library():
        return [[], "libZXing (zxing-cpp) is not installed"]
    end
    options = "ecLevel=M"
    if not is_ascii(text):
        options += ",eci=26"
    end
    unsafe:
        size = __lsl_qbe_call1(__lsl_symbol("strlen"), cstr(text))
        qr_format = __lsl_qbe_s32(__lsl_qbe_call1(fn("ZXing_BarcodeFormatFromString"), cstr("QRCode")))
        opts = __lsl_qbe_call1(fn("ZXing_CreatorOptions_new"), qr_format)
        call __lsl_qbe_call2(fn("ZXing_CreatorOptions_setOptions"), opts, cstr(options))
        barcode = __lsl_qbe_call3(fn("ZXing_CreateBarcodeFromText"), cstr(text), size, opts)
        call __lsl_qbe_call1(fn("ZXing_CreatorOptions_delete"), opts)
    end
    if barcode == 0:
        return [[], last_error("QR code could not be created")]
    end
    unsafe:
        wopts = __lsl_qbe_call0(fn("ZXing_WriterOptions_new"))
        call __lsl_qbe_call2(fn("ZXing_WriterOptions_setScale"), wopts, 1)
        call __lsl_qbe_call2(fn("ZXing_WriterOptions_setAddQuietZones"), wopts, 0)
        image = __lsl_qbe_call2(fn("ZXing_WriteBarcodeToImage"), barcode, wopts)
        call __lsl_qbe_call1(fn("ZXing_WriterOptions_delete"), wopts)
        call __lsl_qbe_call1(fn("ZXing_Barcode_delete"), barcode)
    end
    if image == 0:
        return [[], last_error("QR code could not be drawn")]
    end
    matrix = []
    unsafe:
        w = __lsl_qbe_s32(__lsl_qbe_call1(fn("ZXing_Image_width"), image))
        h = __lsl_qbe_s32(__lsl_qbe_call1(fn("ZXing_Image_height"), image))
        pixels = __lsl_qbe_call1(fn("ZXing_Image_data"), image)
        y = 0
        while y < h:
            row = []
            x = 0
            while x < w:
                row.append(1 if __lsl_qbe_load8(pixels + y * w + x) < 128 else 0)
                x += 1
            end
            matrix.append(row)
            y += 1
        end
        call __lsl_qbe_call1(fn("ZXing_Image_delete"), image)
    end
    return [matrix, ""]
end

# QR kody v obrazku (pixely = adresa; Lum 1 bajt/pixel, BGRA 4) -> seznam textu. Knihovna data nekopiruje,
# obrazek musi zit do konce volani.
function decode(pixels, width, height, format, stride):
    if not load_library() or pixels == 0 or width <= 0 or height <= 0:
        return []
    end
    texts = []
    pix = 1 if format == FORMAT_LUM else 4
    unsafe:
        view = __lsl_qbe_call6(fn("ZXing_ImageView_new"), ptr(pixels), ptr(width), ptr(height), ptr(format), ptr(stride), ptr(pix))
        if view == 0:
            return []
        end
        opts = __lsl_qbe_call0(fn("ZXing_ReaderOptions_new"))
        cell = __lsl_byte_zeros(8)
        formats = __lsl_qbe_load64(__lsl_address(cell) + 24)
        call __lsl_qbe_store32(formats, __lsl_qbe_s32(__lsl_qbe_call1(fn("ZXing_BarcodeFormatFromString"), cstr("QRCode"))))
        call __lsl_qbe_call3(fn("ZXing_ReaderOptions_setFormats"), opts, formats, 1)
        call __lsl_qbe_call2(fn("ZXing_ReaderOptions_setTryHarder"), opts, 1)
        call __lsl_qbe_call2(fn("ZXing_ReaderOptions_setTryInvert"), opts, 1)
        found = __lsl_qbe_call2(fn("ZXing_ReadBarcodes"), view, opts)
        if found != 0:
            n = __lsl_qbe_s32(__lsl_qbe_call1(fn("ZXing_Barcodes_size"), found))
            i = 0
            while i < n:
                raw = __lsl_qbe_call1(fn("ZXing_Barcode_text"), __lsl_qbe_call2(fn("ZXing_Barcodes_at"), found, i))
                t = glib.from_c(raw)
                if raw != 0:
                    call __lsl_qbe_call1(fn("ZXing_free"), raw)
                end
                if t != "":
                    texts.append(t)
                end
                i += 1
            end
            call __lsl_qbe_call1(fn("ZXing_Barcodes_delete"), found)
        end
        call __lsl_qbe_call1(fn("ZXing_ReaderOptions_delete"), opts)
        call __lsl_qbe_call1(fn("ZXing_ImageView_delete"), view)
    end
    return texts
end

# Snimek kamery (cairo RGB24) zmenseny na nejvys SCAN_WIDTH px: ctecka zvladne i zrcadleny obraz
function decode_surface(surface):
    if surface == 0 or not load_library():
        return []
    end
    w = cairo.image_surface_get_width(surface)
    h = cairo.image_surface_get_height(surface)
    scale = 1.0
    if w > SCAN_WIDTH:
        scale = Float(SCAN_WIDTH) / w
    end
    sw = max(1, Int(w * scale))
    sh = max(1, Int(h * scale))
    # CAIRO_FORMAT_RGB24
    small = cairo.image_surface_create(1, sw, sh)
    cr = cairo.create(small)
    call cairo.scale(cr, scale, scale)
    call cairo.set_source_surface(cr, surface, 0.0, 0.0)
    call cairo.paint(cr)
    call cairo.destroy(cr)
    call cairo.surface_flush(small)
    unsafe:
        pixels = __lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_data"), ptr(small))
        stride = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_stride"), ptr(small)))
    end
    texts = decode(pixels, sw, sh, FORMAT_BGRA, stride)
    call cairo.surface_destroy(small)
    return texts
end

# ---- NetworkManager (vystup nmcli -t) ---------------------------------------------------

# Radek nmcli -t: pole oddelena ':' (v hodnotach escapovane '\:')
function split_terse(line):
    parts = []
    current = ""
    escaped = False
    for ch in line:
        if escaped:
            current += ch
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ":":
            parts.append(current)
            current = ""
        else:
            current += ch
        end
    end
    parts.append(current)
    return parts
end

# Aktivni pripojeni Wi-Fi z "nmcli -t -f TYPE,UUID,DEVICE,NAME connection show --active": {"uuid", "device",
# "name"} nebo None
function active_wifi(output):
    for line in output.split("\n"):
        parts = split_terse(line)
        if len(parts) >= 4 and parts[0] == "802-11-wireless":
            return {"uuid": parts[1], "device": parts[2], "name": parts[3]}
        end
    end
    return None
end

# Vystup "nmcli --escape no -t -f ... connection show" -> slovnik pole: hodnota
function parse_connection(output):
    vals = {}
    for line in output.split("\n"):
        cut = line.find(":")
        if cut > 0 and line[:cut] in FIELDS:
            vals[line[:cut]] = line[cut + 1:]
        end
    end
    return vals
end

# Udaje site pro QR kod: ssid, security ("" = 802.1X), password, hidden, need_auth
function details(vals):
    sec = security_type(vals.get("802-11-wireless-security.key-mgmt", ""))
    if not ("802-11-wireless-security.key-mgmt" in vals):
        sec = "nopass"
    end
    info = {"ssid": vals.get("802-11-wireless.ssid", ""), "security": sec,
        "hidden": vals.get("802-11-wireless.hidden", "").strip() == "yes", "password": ""}
    if sec == "WPA" or sec == "SAE":
        info["password"] = vals.get("802-11-wireless-security.psk", "")
    elif sec == "WEP":
        info["password"] = vals.get("802-11-wireless-security.wep-key0", "")
    end
    # Heslo bez opravneni (systemove pripojeni, polkit) nmcli vrati prazdne
    info["need_auth"] = (sec == "WPA" or sec == "SAE" or sec == "WEP") and info["password"] == ""
    return info
end

# ---- pripojeni k siti z QR kodu ------------------------------------------------------------

# Argumenty nmcli pro pripojeni k otevrene siti
function connect_args(info):
    args = ["device", "wifi", "connect", info["ssid"]]
    if info.get("hidden", False):
        args = args + ["hidden", "yes"]
    end
    return args
end

# Argumenty nmcli pro novy profil site s heslem; heslo samo prijde az pri "up" ze souboru
function add_args(info, uuid):
    mgmt = "wpa-psk"
    if info.get("security", "") == "SAE":
        mgmt = "sae"
    elif info.get("security", "") == "WEP":
        mgmt = "none"
    end
    args = ["connection", "add", "type", "wifi", "con-name", info["ssid"], "ssid", info["ssid"], "connection.uuid", uuid,
        "wifi-sec.key-mgmt", mgmt]
    if mgmt == "none":
        args = args + ["wifi-sec.wep-key-type", "1"]
    end
    if info.get("hidden", False):
        args = args + ["802-11-wireless.hidden", "yes"]
    end
    return args
end

# nmcli bez prekladu (LC_ALL=C), chyby k vystupu
function nmcli_run(args, handler, job):
    argv = ["sh", "-c", "LC_ALL=C exec \"$@\" 2>&1", "nmcli", env.get("LUXOS_NMCLI", "nmcli")]
    call glib.spawn_capture(argv + args, handler, job)
end

# Soubor s heslem jen pro uzivatele (0600) v XDG_RUNTIME_DIR; "" kdyz nejde vytvorit
function secret_file(line):
    dir = env.get("XDG_RUNTIME_DIR", "")
    if dir == "":
        dir = env.get("TMPDIR", "/tmp")
    end
    template = dir + "/luxos-qr-XXXXXX"
    path = ""
    unsafe:
        buffer = __lsl_byte_zeros(len(template) * 4 + 1)
        base = __lsl_qbe_load64(__lsl_address(buffer) + 24)
        call __lsl_qbe_call3(__lsl_symbol("memcpy"), base, cstr(template), __lsl_qbe_call1(__lsl_symbol("strlen"), cstr(template)))
        fd = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("mkstemp"), base))
        if fd < 0:
            return ""
        end
        call __lsl_qbe_call1(__lsl_symbol("close"), fd)
        path = glib.from_c(base)
    end
    call writefile(path, line)
    return path
end

# Pripojeni (nmcli); konec ohlasi handler(data, ok, zprava). Heslo nesmi do argv (ps ho ukaze ostatnim
# uzivatelum): profil bez hesla + passwd-file 0600.
function connect(info, handler, data):
    job = {"info": info, "handler": handler, "data": data, "uuid": "", "file": ""}
    wait = ["--wait", "60"]
    if info.get("security", "") == "nopass" or info.get("password", "") == "":
        call nmcli_run(wait + connect_args(info), connect_done, job)
        return 0
    end
    unsafe:
        job["uuid"] = glib.take_c(__lsl_qbe_call0(__lsl_symbol("g_uuid_string_random")))
    end
    call nmcli_run(add_args(info, job["uuid"]), connect_added, job)
end

function connect_added(job, output, status):
    if status != 0:
        call connect_finish(job, False, output)
        return 0
    end
    key = "wep-key0" if job["info"].get("security", "") == "WEP" else "psk"
    job["file"] = secret_file("802-11-wireless-security." + key + ":" + job["info"]["password"] + "\n")
    if job["file"] == "":
        call nmcli_run(["connection", "delete", "uuid", job["uuid"]], connect_ignored, 0)
        call connect_finish(job, False, "cannot write the password file")
        return 0
    end
    call nmcli_run(["--wait", "60", "connection", "up", "uuid", job["uuid"], "passwd-file", job["file"]], connect_done, job)
    return 0
end

function connect_done(job, output, status):
    if job["file"] != "":
        call glib.unlink(job["file"])
    end
    if status != 0 and job["uuid"] != "":
        # nepovedeny profil se uklidi
        call nmcli_run(["connection", "delete", "uuid", job["uuid"]], connect_ignored, 0)
    end
    call connect_finish(job, status == 0, output)
    return 0
end

function connect_ignored(job, output, status):
    return 0
end

function connect_finish(job, ok, output):
    handler = job["handler"]
    call handler(job["data"], ok, output.strip())
end
