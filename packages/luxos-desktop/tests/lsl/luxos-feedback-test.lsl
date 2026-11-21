# Test luxos_feedback.lsl bez okna a bez site (test_luxos_feedback.py): co se z logu odstrani pred odeslanim,
# JSON pro okno a adresa serveru. Vypise radky "ok NAZEV" / "FAIL NAZEV ..."
load env
load luxos_feedback as fb

failures = 0

function expect(name, got, want):
    global failures
    if got == want:
        print "ok " + name
    else:
        failures += 1
        print "FAIL " + name + " got " + String(got) + " want " + String(want)
    end
    return 0
end

ctx = {"home": "/home/novak", "user": "novak", "host": "novak-pc", "ssids": ["Domov Novak", "x"]}

function r(text):
    return fb.redact(text, ctx)
end

# IPv6 (vcetne zony a v hranatych zavorkach), casy a jine dvojtecky zustanou
for addr in ["2001:db8:85a3::8a2e:370:7334", "fe80::1%wlan0", "2001:0db8:0000:0000:0000:ff00:0042:8329", "::1", "[2a00:1028:9192:35c2::5]:443"]:
    out = r("connect to " + addr + " failed")
    call expect("ipv6 " + addr, out.find("db8") < 0 and out.find("35c2") < 0 and out.find("<ip>") >= 0, True)
end
call expect("times", r("Nov 19 08:25:26 std::string a:b"), "Nov 19 08:25:26 std::string a:b")
# SSID v logu wpa_supplicant / NetworkManager a ulozene site
call expect("ssid-quoted", r("wlan0: Trying to associate with SSID 'Kavarna U Lipy'"), "wlan0: Trying to associate with SSID '<ssid>'")
call expect("ssid-eq", r("ssid=\"Moje sit\" freq=2412"), "ssid=\"<ssid>\" freq=2412")
call expect("ssid-saved", r("device (wlan0): Activation: starting connection 'Domov Novak'"), "device (wlan0): Activation: starting connection '<ssid>'")
call expect("ssid-short", r("x y"), "x y")
# domov, uzivatel, pocitac, e-mail, IPv4, MAC, tajne hodnoty a dlouhe klice
call expect("home", r("open /home/novak/Dokumenty/a.txt"), "open ~/Dokumenty/a.txt")
call expect("user-host", r("novak@novak-pc: user novak, novakova"), "<user>@<host>: user <user>, novakova")
call expect("host", r("novak-pc kernel: oops"), "<host> kernel: oops")
call expect("email", r("mail jan.novak+x@example.co.uk sent"), "mail <email> sent")
call expect("ipv4", r("from 192.168.1.20 port 22, version 1.2.3.4.5"), "from <ip> port 22, version 1.2.3.4.5")
call expect("mac", r("dev aa:bb:cc:dd:ee:0F up"), "dev <mac> up")
call expect("secret", r("Password = hunter2 token: abc Authorization=Bearer"), "Password = <redacted> token: <redacted> Authorization=<redacted>")
call expect("long", r("key " + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q" + " /usr/lib/x"), "key <redacted> /usr/lib/x")
call expect("unicode-user", r("čnovak novak"), "čnovak <user>")
lines = fb.log_lines("-- Boot 1 --\n\nline 1 /home/novak\n" + "y " * 200 + "\n", ctx, 50)
call expect("log-lines", [lines[0], len(lines[1])], ["line 1 ~", 300])
call expect("log-tail", len(fb.log_lines("a\nb\nc\n", ctx, 2)), 2)
# okno ukazuje presne odesilany JSON (jako json.dumps(indent=2, ensure_ascii=False))
call expect("pretty", fb.pretty({"os": "LuxOS", "gpu": ["A"], "memoryGB": 15.5, "packages": {}, "e": [], "n": 3}), "{\n  \"os\": \"LuxOS\",\n  \"gpu\": [\n    \"A\"\n  ],\n  \"memoryGB\": 15.5,\n  \"packages\": {},\n  \"e\": [],\n  \"n\": 3\n}")
# server: https kamkoli, http jen na tento pocitac
function origin(value):
    return fb.origin_from(value)
end
call expect("origin-unset", origin(""), "https://lux-ai.cz")
call expect("origin-https", origin("https://staging.lux-ai.cz/"), "https://staging.lux-ai.cz")
call expect("origin-local", origin("http://127.0.0.1:8080"), "http://127.0.0.1:8080")
call expect("origin-localhost", origin("http://localhost:5000/"), "http://localhost:5000")
call expect("origin-ipv6", origin("http://[::1]:9"), "http://[::1]:9")
call expect("origin-remote-http", origin("http://evil.example"), "https://lux-ai.cz")
call expect("origin-garbage", origin("ftp://x"), "https://lux-ai.cz")
call expect("kinds", [k[0] for k in fb.KINDS], ["bug", "idea", "other"])
if failures > 0:
    exit(1)
end
