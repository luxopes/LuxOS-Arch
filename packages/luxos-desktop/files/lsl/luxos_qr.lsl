# LuxOS - QR kod site Wi-Fi pro aplikace v LSL: text WIFI:..., kresleni QR kodu (zxing-cpp) a udaje site
# z NetworkManageru (nmcli); stejne chovani jako files/python/luxos_qr.py (ten dal pouziva Kamera pro cteni).
#
# Format (ZXing / Android / iOS):  WIFI:T:WPA;S:<ssid>;P:<heslo>;H:true;;
#   T = WPA (WPA/WPA2), SAE (WPA3), WEP nebo nopass; znaky \ ; , : " se v S a P escapuji zpetnym lomitkem.
#
#   wifi_payload(ssid, heslo, typ, skryta) -> text, security_type(key-mgmt) -> typ nebo ""
#   available(), encode(text) -> [matice radku 0/1, chyba]   libZXing se nacita az za behu (dlopen)
#   active_wifi(text) / parse_connection(text) / details(vals) - rozbor vystupu nmcli
# LUXOS_ZXING_LIB prepise cestu ke knihovne (testy bez instalace).
load env
load luxos_glib, glib as glib

SPECIAL = "\\;,:\""
FIELDS = ["802-11-wireless.ssid", "802-11-wireless.hidden", "802-11-wireless-security.key-mgmt",
    "802-11-wireless-security.psk", "802-11-wireless-security.wep-key0"]
NAMES = ["ZXing_BarcodeFormatFromString", "ZXing_CreatorOptions_new", "ZXing_CreatorOptions_setOptions",
    "ZXing_CreatorOptions_delete", "ZXing_CreateBarcodeFromText", "ZXing_Barcode_delete", "ZXing_WriterOptions_new",
    "ZXing_WriterOptions_setScale", "ZXing_WriterOptions_setAddQuietZones", "ZXing_WriterOptions_delete",
    "ZXing_WriteBarcodeToImage", "ZXing_Image_data", "ZXing_Image_width", "ZXing_Image_height", "ZXing_Image_delete",
    "ZXing_LastErrorMsg", "ZXing_free"]

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
