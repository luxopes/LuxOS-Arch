# LuxOS - automaticke prepnuti zvukoveho vystupu na nove pripojene zarizeni (/usr/lib/luxos/luxos-audio-switch,
# spousti ho luxos-hub, luxos_audio_hub.lsl; drive files/python/luxos_audio_switch.py).
#
# luxos-hub sleduje `pactl subscribe` a pri zmene karty, serveru nebo pridani/odebrani vystupu spusti
# `luxos-audio-switch check`. Ten porovna stav karet s minulym (soubor v $XDG_RUNTIME_DIR) a:
#   - HDMI / DisplayPort (zvuk monitoru): port na karte zmeni dostupnost "not available" -> "available".
#     Kdyz aktivni profil karty port neobsahuje (analogovy profil, kde HDMI vystup vubec neni), prepne kartu
#     na nejlepsi dostupny profil s timto portem (pokud mozno se stejnym vstupem). Pak vystup s portem nastavi
#     jako vychozi a presune na nej prehravane zvuky. pipewire-pulse ani WirePlumber tohle samy neudelaji.
#   - USB / Bluetooth: nova karta s vystupem -> jeji vystup je vychozi.
#   - Odpojeni: port neni dostupny / karta zmizela -> vrati predchozi profil a vychozi vystup.
# Nebojuje s uzivatelem: kdyz si po automatickem prepnuti vybere jiny vystup (nebo profil), po odpojeni se nic
# nevraci. Pri prvnim spusteni v relaci se jen ulozi vychozi stav - co uz pripojene je, se neprepina.
#
#   luxos-audio-switch check     jedna kontrola (LUXOS_PACTL prepise program pactl, LUXOS_AUDIO_WAIT cekani
#                                na novy vystup v s - testy)
load env, json, process, time
load luxos_glib, glib as glib
load luxos_sys as sys
load luxos_text as text

S_IFMT = 61440
S_IFDIR = 16384

function get(table, key, default):
    if table == None or type(table) != "Dictionary":
        return default
    end
    value = table.get(key)
    if value == None:
        return default
    end
    return value
end

function log(message):
    call eprint("luxos-audio-switch: " + message)
    return 0
end

function wait_seconds():
    value = env.get("LUXOS_AUDIO_WAIT", "")
    if value == None or value == "":
        return 3.0
    end
    return Float(value)
end

# [st_mode, st_uid] bez nasledovani odkazu, nebo [] kdyz cesta neni
function lstat(path):
    unsafe:
        buffer = __lsl_byte_zeros(256)
        base = __lsl_qbe_load64(__lsl_address(buffer) + 24)
        if __lsl_qbe_call2(__lsl_symbol("lstat"), sys.cstr(path), base) != 0:
            return []
        end
        # struct stat x86_64: st_mode +24, st_uid +28
        return [__lsl_qbe_load32(base + 24), __lsl_qbe_load32(base + 28)]
    end
end

function mkdir_private(path):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("mkdir"), sys.cstr(path), 448) == 0
    end
end

# Bez XDG_RUNTIME_DIR vlastni slozka 700 v /tmp (soubor primo v /tmp muze predem vytvorit jiny uzivatel);
# nebezpecna slozka = stav se neuklada (None)
function state_path():
    run = env.get("XDG_RUNTIME_DIR", "")
    if run == None or run == "":
        tmp = env.get("TMPDIR", "")
        if tmp == None or tmp == "":
            tmp = "/tmp"
        end
        run = tmp + "/luxos-" + String(sys.getuid())
        call mkdir_private(run)
        info = lstat(run)
        if len(info) == 0 or (info[0] & S_IFMT) != S_IFDIR or info[1] != sys.getuid() or (info[0] & 63) != 0:
            return None
        end
    end
    return run + "/luxos-audio-switch.json"
end

# Vystup pactl (LC_ALL=C: pactl jinak preklada "available"), None pri chybe
function pactl(args):
    program = env.get("LUXOS_PACTL", "")
    if program == None or program == "":
        program = "pactl"
    end
    result = None
    safe:
        result = process.capture_result("/usr/bin/env", ["LC_ALL=C", "timeout", "10", program] + args)
    end
    if result == None:
        call log("pactl " + " ".join(args) + ": cannot run")
        return None
    end
    if not result["ok"]:
        call log("pactl " + " ".join(args) + ": " + String(result["stderr"]).strip())
        return None
    end
    return String(result["stdout"])
end

function pactl_json(args):
    out = pactl(["-f", "json"] + args)
    if out == None or out.strip() == "":
        return None
    end
    value = None
    safe:
        value = json.decode(out)
    end
    return value
end

function list_of(value):
    if value == None or type(value) != "List":
        return []
    end
    return value
end

function is_output(name):
    n = name.lower()
    return n.find("output") >= 0 or n.startswith("[out]")
end

function is_display_port(name, port):
    blob = (name + " " + String(get(port, "type", "")) + " " + String(get(port, "description", ""))).lower()
    return blob.find("hdmi") >= 0 or blob.find("displayport") >= 0
end

function card_bus(card):
    bus = String(get(get(card, "properties", {}), "device.bus", ""))
    if bus == "" and String(get(card, "name", "")).startswith("bluez_card."):
        bus = "bluetooth"
    end
    return bus
end

# za prvni teckou (alsa_card.X -> X)
function after_dot(name):
    cut = name.find(".")
    if cut < 0:
        return name
    end
    return name[cut + 1:]
end

# Vystupy (sinky) karty: device.id == object.id karty, jinak podle jmena (alsa_card.X -> alsa_output.X.*)
function card_sinks(card, sinks):
    obj = String(get(get(card, "properties", {}), "object.id", ""))
    key = after_dot(String(get(card, "name", "")))
    out = []
    for s in sinks:
        dev = String(get(get(s, "properties", {}), "device.id", ""))
        if obj != "" and dev != "":
            if dev == obj:
                out.append(s)
            end
        elif key != "" and after_dot(String(get(s, "name", ""))).startswith(key):
            out.append(s)
        end
    end
    return out
end

function sink_with_port(card, sinks, port):
    for s in card_sinks(card, sinks):
        for p in list_of(get(s, "ports", [])):
            if get(p, "name", "") == port:
                return s
            end
        end
    end
    return None
end

function first_sink(card, sinks):
    found = card_sinks(card, sinks)
    if len(found) == 0:
        return None
    end
    return found[0]
end

function sink_named(sinks, name):
    for s in sinks:
        if get(s, "name", "") == name:
            return s
        end
    end
    return None
end

function card_named(cards, name):
    for c in cards:
        if get(c, "name", "") == name:
            return c
        end
    end
    return None
end

# {karta: {"bus":..., "ports": {port HDMI/DP: dostupnost}}}
function snapshot(cards):
    out = {}
    for c in cards:
        ports = {}
        table = get(c, "ports", {})
        for name in table.keys():
            p = table[name]
            if is_output(name) and is_display_port(name, p):
                ports[name] = String(get(p, "availability", ""))
            end
        end
        out[String(c["name"])] = {"bus": card_bus(c), "ports": ports}
    end
    return out
end

# Nejlepsi dostupny profil s portem; prednost ma profil se stejnym vstupem jako ten aktivni
function best_profile(card, port):
    profiles = get(card, "profiles", {})
    inputs = []
    for part in String(get(card, "active_profile", "")).split("+"):
        if part.startswith("input:"):
            inputs.append(part)
        end
    end
    best = None
    best_input = False
    best_prio = 0
    for name in list_of(get(get(get(card, "ports", {}), port, {}), "profiles", [])):
        info = get(profiles, name, {})
        if get(info, "available", True) != True or Int(get(info, "sinks", 1)) < 1:
            continue
        end
        parts = name.split("+")
        same_input = len(inputs) > 0
        for i in inputs:
            if i not in parts:
                same_input = False
            end
        end
        prio = Int(get(info, "priority", 0))
        if best == None or (same_input and not best_input) or (same_input == best_input and prio > best_prio):
            best = name
            best_input = same_input
            best_prio = prio
        end
    end
    return best
end

# Po zmene profilu chvili pockat na novy vystup (vznikne asynchronne); kind: "port", "card", "sink"
function wait_sink(card_name, kind, arg):
    deadline = time.monotonic() + wait_seconds()
    while True:
        cards = list_of(pactl_json(["list", "cards"]))
        sinks = list_of(pactl_json(["list", "sinks"]))
        card = card_named(cards, card_name)
        found = None
        if card != None:
            if kind == "port":
                found = sink_with_port(card, sinks, arg)
            elif kind == "card":
                found = first_sink(card, sinks)
            else:
                found = sink_named(sinks, arg)
            end
        end
        if found != None or time.monotonic() >= deadline:
            return found
        end
        call time.sleep(0.2)
    end
end

function make_default(sink_name):
    call pactl(["set-default-sink", sink_name])
    # prehravane zvuky na novy vystup (i ty, kterym nekdo vystup nastavil rucne)
    listing = pactl(["list", "short", "sink-inputs"])
    if listing == None:
        return 0
    end
    for line in listing.split("\n"):
        idx = line.split("\t")[0].strip()
        if text.is_digits(idx):
            call pactl(["move-sink-input", idx, sink_name])
        end
    end
    return 0
end

function default_sink():
    return String(get(pactl_json(["info"]), "default_sink_name", ""))
end

# Prepnout na HDMI/DP port karty; vraci zaznam pro pozdejsi navrat nebo None
function switch_to_port(card, port, sinks, current):
    name = String(card["name"])
    prev_profile = None
    active = String(get(card, "active_profile", ""))
    sink = sink_with_port(card, sinks, port)
    if sink == None:
        # aktivni profil port nema (analogovy profil bez HDMI vystupu)
        profile = best_profile(card, port)
        if profile == None:
            call log(name + ": no available profile for " + port)
            return None
        end
        if profile != active:
            if pactl(["set-card-profile", name, profile]) == None:
                return None
            end
            prev_profile = active
            active = profile
        end
        sink = wait_sink(name, "port", port)
    end
    if sink == None:
        call log(name + ": no output for " + port)
        return None
    end
    if get(sink, "active_port", "") != port:
        call pactl(["set-sink-port", String(sink["name"]), port])
    end
    call make_default(String(sink["name"]))
    call log(name + " " + port + " -> default output " + String(sink["name"]))
    return {"card": name, "port": port, "sink": sink["name"], "profile": active, "prev_profile": prev_profile,
            "prev_sink": current, "manual": False}
end

function switch_to_card(card, current):
    sink = wait_sink(String(card["name"]), "card", None)
    if sink == None:
        return None
    end
    call make_default(String(sink["name"]))
    call log(String(card["name"]) + " -> default output " + String(sink["name"]))
    return {"card": card["name"], "port": None, "sink": sink["name"], "profile": get(card, "active_profile", None),
            "prev_profile": None, "prev_sink": current, "manual": False}
end

function restore(auto, cards, sinks):
    card = card_named(cards, auto["card"])
    prev_profile = get(auto, "prev_profile", "")
    if prev_profile != "" and card != None and get(card, "active_profile", None) == get(auto, "profile", None):
        call pactl(["set-card-profile", String(card["name"]), String(prev_profile)])
        call wait_sink(String(card["name"]), "sink", get(auto, "prev_sink", ""))
        fresh = pactl_json(["list", "sinks"])
        if fresh != None:
            sinks = list_of(fresh)
        end
    end
    prev = String(get(auto, "prev_sink", ""))
    if prev != "" and sink_named(sinks, prev) != None:
        call make_default(prev)
        call log("restored default output " + prev)
    end
    return 0
end

function save(st):
    path = state_path()
    if path == None:
        return 0
    end
    if not glib.write_atomic(path, json.encode(st)):
        call log("state: cannot write " + path)
    end
    return 0
end

function load_state():
    path = state_path()
    if path == None:
        return None
    end
    raw = glib.read_text(path)
    if raw == None or raw == "":
        return None
    end
    value = None
    safe:
        value = json.decode(raw)
    end
    if value == None or type(value) != "Dictionary" or type(value.get("cards")) != "Dictionary":
        return None
    end
    return value
end

function run_check():
    cards = pactl_json(["list", "cards"])
    sinks = pactl_json(["list", "sinks"])
    if cards == None or sinks == None:
        return 1
    end
    cards = list_of(cards)
    sinks = list_of(sinks)
    current = default_sink()
    now = snapshot(cards)
    st = load_state()
    if st == None:
        # prvni beh v relaci: jen zapamatovat, co uz pripojene je
        call save({"cards": now, "auto": None, "default": current})
        return 0
    end
    before = st["cards"]
    auto = st.get("auto")
    if auto != None and type(auto) != "Dictionary":
        auto = None
    end

    # uzivatel si mezitim vybral jiny vystup: jeho volba plati, nic se nevrati
    if auto != None and current != "" and current != get(auto, "sink", ""):
        auto["manual"] = True
    end

    # odpojeni zarizeni, na ktere se automaticky prepnulo
    if auto != None:
        card = now.get(auto["card"])
        port = get(auto, "port", "")
        gone = card == None or (port != "" and card["ports"].get(port) == "not available")
        if gone:
            if get(auto, "manual", False) != True:
                call restore(auto, cards, sinks)
            end
            auto = None
            current = default_sink()
        end
    end

    # nove pripojene: HDMI/DP port na existujici karte, nebo nova karta USB/Bluetooth
    target = None
    for name in now.keys():
        info = now[name]
        old = before.get(name)
        if old == None or type(old) != "Dictionary":
            if (info["bus"] == "usb" or info["bus"] == "bluetooth") and target == None:
                target = ["card", card_named(cards, name), None]
            end
            continue
        end
        old_ports = get(old, "ports", {})
        for port in info["ports"].keys():
            if info["ports"][port] == "available" and old_ports.get(port) == "not available" and target == None:
                target = ["port", card_named(cards, name), port]
            end
        end
    end
    if target != None:
        new = None
        if target[0] == "port":
            new = switch_to_port(target[1], target[2], sinks, current)
        else:
            new = switch_to_card(target[1], current)
        end
        if new != None:
            # navrat na puvodni vystup jen z prvniho automatickeho prepnuti
            if auto != None and get(auto, "manual", False) != True:
                prev = get(auto, "prev_sink", "")
                if prev != "":
                    new["prev_sink"] = prev
                end
            end
            auto = new
        end
        current = default_sink()
        fresh = pactl_json(["list", "cards"])
        if fresh != None:
            cards = list_of(fresh)
        end
        now = snapshot(cards)
    end

    call save({"cards": now, "auto": auto, "default": current})
    return 0
end

if len(args) == 2 and args[1] == "check":
    call exit(run_check())
end
call eprint("usage: luxos-audio-switch check  (used by luxos-hub)")
call exit(2)
