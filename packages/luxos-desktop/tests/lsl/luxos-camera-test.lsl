# Test luxos_qr.lsl a luxos_camera.lsl bez displeje (test_luxos_camera.py): vypise radky "ok NAZEV" / "FAIL NAZEV ...".
#   luxos-camera-test             testy (cteni QR kodu jen s libZXing, jinak "skip zxing")
#   luxos-camera-test SOUBOR.png  vypise texty QR kodu v obrazku (snimek okna QR kodu Wi-Fi)
#   luxos-camera-test --render TEXT SOUBOR.png   QR kod na papire na stole (obrazek testovaci kamery)
# Uzly kamer: LUXOS_VIDEO_DEV_DIR s prazdnymi soubory video10, video2, video0, other (pripravi test).
load env, cairo, json
load luxos_qr as qr
load luxos_camera as camera

failures = 0

function expect(name, got, want):
    global failures
    if json.encode(got) == json.encode(want):
        print "ok " + name
    else:
        failures += 1
        print "FAIL " + name + " got " + json.encode(got) + " want " + json.encode(want)
    end
    return 0
end

function wifi(ssid, password, security, hidden):
    return {"ssid": ssid, "password": password, "security": security, "hidden": hidden}
end

# Matice QR -> obrazek cairo RGB24 s okrajem (zrcadleny jako nahled kamery)
function render(matrix, scale, mirror):
    n = len(matrix)
    size = (n + 8) * scale
    surface = cairo.image_surface_create(1, size, size)
    cr = cairo.create(surface)
    call cairo.set_source_rgb(cr, 1.0, 1.0, 1.0)
    call cairo.paint(cr)
    call cairo.set_source_rgb(cr, 0.0, 0.0, 0.0)
    for y in range(n):
        for x in range(n):
            if matrix[y][x] == 1:
                col = n - 1 - x if mirror else x
                call cairo.rectangle(cr, Float((col + 4) * scale), Float((y + 4) * scale), Float(scale), Float(scale))
            end
        end
    end
    call cairo.fill(cr)
    call cairo.destroy(cr)
    return surface
end

if len(args) > 3 and args[1] == "--render":
    matrix = qr.encode(args[2])[0]
    n = len(matrix)
    scale = 10
    scene = cairo.image_surface_create(1, 640, 480)
    cr = cairo.create(scene)
    call cairo.set_source_rgb(cr, 0.85, 0.82, 0.78)
    call cairo.paint(cr)
    x0 = (640 - n * scale) // 2
    y0 = (480 - n * scale) // 2
    call cairo.set_source_rgb(cr, 1.0, 1.0, 1.0)
    call cairo.rectangle(cr, Float(x0 - 40), Float(y0 - 40), Float(n * scale + 80), Float(n * scale + 80))
    call cairo.fill(cr)
    call cairo.set_source_rgb(cr, 0.0, 0.0, 0.0)
    for y in range(n):
        for x in range(n):
            if matrix[y][x] == 1:
                call cairo.rectangle(cr, Float(x0 + x * scale), Float(y0 + y * scale), Float(scale), Float(scale))
            end
        end
    end
    call cairo.fill(cr)
    call cairo.destroy(cr)
    call cairo.surface_write_to_png(scene, args[3])
    exit(0)
end
if len(args) > 1:
    image = cairo.image_surface_create_from_png(args[1])
    for t in qr.decode_surface(image):
        print "text " + json.encode(t)
    end
    exit(0)
end

# ---- text WIFI: ----
call expect("escape", qr.escape("a\\b;c,d:e\"f"), "a\\\\b\\;c\\,d\\:e\\\"f")
call expect("escape-plain", qr.escape("Kavárna 5G"), "Kavárna 5G")
call expect("payload", qr.wifi_payload("Home", "secret", "WPA", False), "WIFI:T:WPA;S:Home;P:secret;;")
call expect("payload-sae", qr.wifi_payload("Home", "x", "SAE", False), "WIFI:T:SAE;S:Home;P:x;;")
call expect("payload-open", qr.wifi_payload("Cafe", "ignored", "nopass", False), "WIFI:T:nopass;S:Cafe;;")
call expect("payload-wep-hidden", qr.wifi_payload("Old", "12345", "WEP", True), "WIFI:T:WEP;S:Old;P:12345;H:true;;")
call expect("payload-escaped", qr.wifi_payload("a;b", "p\"w\\", "WPA", False), "WIFI:T:WPA;S:a\\;b;P:p\\\"w\\\\;;")
call expect("parse", qr.parse_wifi("WIFI:T:WPA;S:Home;P:secret;;"), wifi("Home", "secret", "WPA", False))
# libovolne poradi, mala pismena, H:true, chybejici T
call expect("parse-order", qr.parse_wifi("wifi:S:Net;H:true;P:pw;;"), wifi("Net", "pw", "WPA", True))
call expect("parse-open", qr.parse_wifi("WIFI:S:Open;;")["security"], "nopass")
call expect("parse-empty-pw", qr.parse_wifi("WIFI:T:nopass;S:Open;P:;;")["password"], "")
call expect("parse-wpa2", qr.parse_wifi("WIFI:T:WPA2;S:x;P:y;;")["security"], "WPA")
call expect("parse-wpa3", qr.parse_wifi("WIFI:T:WPA3;S:x;P:y;;")["security"], "SAE")
call expect("parse-unknown-type", qr.parse_wifi("WIFI:T:WPA2-EAP;S:x;P:y;;")["security"], "WPA")
# hexadecimalni retezec v uvozovkach (ZXing)
call expect("parse-quoted", qr.parse_wifi("WIFI:T:WPA;S:\"0123ABCD\";P:\"pass\";;")["ssid"], "0123ABCD")
call expect("parse-escaped-quotes", qr.parse_wifi("WIFI:T:WPA;S:a\\\"b\\\";P:x;;")["ssid"], "a\"b\"")
for bad in ["", "https://luxos.example/", "WIFI:;", "WIFI:T:WPA;P:x;;"]:
    call expect("parse-bad " + bad, qr.parse_wifi(bad), None)
end
call expect("parse-none", qr.parse_wifi(None), None)
cases = [["Kavárna;1", "tajne;heslo,\\1", "WPA", False], ["\"quoted\"", ":colon:", "SAE", True], ["Чай", "пароль", "WPA", False], ["Free", "", "nopass", False]]
for c in cases:
    call expect("round-trip " + c[0], qr.parse_wifi(qr.wifi_payload(c[0], c[1], c[2], c[3])), wifi(c[0], c[1], c[2], c[3]))
end
call expect("security-psk", qr.security_type("wpa-psk"), "WPA")
call expect("security-sae", qr.security_type("sae"), "SAE")
call expect("security-wep", qr.security_type("none"), "WEP")
call expect("security-owe", qr.security_type("owe"), "nopass")
call expect("security-empty", qr.security_type(""), "nopass")
call expect("security-eap", qr.security_type("wpa-eap"), "")

# ---- nmcli ----
call expect("terse", qr.split_terse("802-11-wireless:u:wlan0:Ka\\:fe\\\\x"), ["802-11-wireless", "u", "wlan0", "Ka:fe\\x"])
call expect("active", qr.active_wifi("loopback:lo-uuid:lo:lo\n802-11-wireless:uuid-1:wlan0:Kavárna\\:1\n"), {"uuid": "uuid-1", "device": "wlan0", "name": "Kavárna:1"})
call expect("active-wired", qr.active_wifi("loopback:lo-uuid:lo:lo\n"), None)
details = qr.details(qr.parse_connection("802-11-wireless.ssid:Kavárna:1\n802-11-wireless.hidden:no\n802-11-wireless-security.key-mgmt:wpa-psk\n802-11-wireless-security.psk:tajne;heslo,\\1\n"))
call expect("details", [details["ssid"], details["password"], details["security"], details["need_auth"]], ["Kavárna:1", "tajne;heslo,\\1", "WPA", False])
call expect("details-no-secret", qr.details(qr.parse_connection("802-11-wireless.ssid:X\n802-11-wireless-security.key-mgmt:sae\n802-11-wireless-security.psk:\n"))["need_auth"], True)
call expect("details-eap", qr.details(qr.parse_connection("802-11-wireless.ssid:X\n802-11-wireless-security.key-mgmt:wpa-eap\n"))["security"], "")
call expect("connect-args", qr.connect_args({"ssid": "A", "password": "", "security": "nopass", "hidden": True}), ["device", "wifi", "connect", "A", "hidden", "yes"])
call expect("add-args", qr.add_args({"ssid": "A", "password": "p", "security": "WPA"}, "u"), ["connection", "add", "type", "wifi", "con-name", "A", "ssid", "A", "connection.uuid", "u", "wifi-sec.key-mgmt", "wpa-psk"])
wep = qr.add_args({"ssid": "A", "password": "k", "security": "WEP", "hidden": True}, "u")
call expect("add-args-wep", wep[len(wep) - 6:], ["wifi-sec.key-mgmt", "none", "wifi-sec.wep-key-type", "1", "802-11-wireless.hidden", "yes"])

# ---- kamery ----
dir = env.get("LUXOS_VIDEO_DEV_DIR", "")
if dir != "":
    call expect("video-nodes", camera.video_nodes(), [dir + "/video0", dir + "/video2", dir + "/video10"])
end
call expect("pick-raw", camera.pick_caps("video/x-raw, format=(string)YUY2, width=(int)1280, height=(int)720, framerate=(fraction)10/1; video/x-raw, format=(string)YUY2, width=(int)640, height=(int)480, framerate=(fraction)30/1; image/jpeg, width=(int)1280, height=(int)720, framerate=(fraction)30/1"), ["image/jpeg,width=1280,height=720,framerate=30/1", True])

# ---- zxing-cpp ----
if not qr.available():
    print "skip zxing"
else:
    texts = ["WIFI:T:WPA;S:Home;P:secret;;", qr.wifi_payload("Čajovna \\;x", "heslo:ěščř", "SAE", True)]
    for t in texts:
        result = qr.encode(t)
        matrix = result[0]
        call expect("encode-square " + t, [len(matrix) == len(matrix[0]), len(matrix) >= 21, result[1]], [True, True, ""])
        img = render(matrix, 6, False)
        call expect("decode " + t, qr.decode_surface(img), [t])
        call cairo.surface_destroy(img)
    end
    # zrcadleny nahled kamery a velky snimek (zmensi se pred ctenim)
    text = qr.wifi_payload("Mirror", "image", "WPA", False)
    img = render(qr.encode(text)[0], 40, True)
    call expect("decode-mirrored-large", qr.decode_surface(img), [text])
    call cairo.surface_destroy(img)
    blank = cairo.image_surface_create(1, 100, 100)
    call expect("decode-nothing", qr.decode_surface(blank), [])
    call expect("decode-null", qr.decode(0, 100, 100, qr.FORMAT_LUM, 100), [])
end
if failures > 0:
    exit(1)
end
