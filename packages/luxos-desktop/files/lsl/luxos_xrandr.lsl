# LuxOS - monitory na X11 (drive files/python/luxos_displays.py a luxos_arrange.py): cteni xrandr, ulozene
# rozliseni/frekvence/otoceni, rozlozeni a rezimy pro sadu monitoru, zrcadleni a velikost textu. Pouziva pomocnik
# luxos-displays (prikazy pro skript /usr/bin/luxos-displays a okno Monitory na X11). Geometrie usporadani
# (prichyceni bez mezer a prekryvu) je spolecna s Waylandem v luxos_displays.lsl.
#
# Vystup (parse): {"name", "connected", "primary", "active", "geometry": [w, h, x, y] nebo None, "rotation",
#   "rotations", "mm": [w, h], "edid" (hex), "modes": [{"name", "rates": ["60.00"..], "current", "preferred"}]}
#   frekvence jsou texty jako je pise xrandr (do xrandr se vraci beze zmeny), porovnavaji se v mHz
# Ulozeni ~/.config/luxos/displays.json (LUXOS_DISPLAYS_CONF), stejny format jako drive v Pythonu:
#   {"version": 1, "outputs": {klic: {"mode", "rate", "rotate"}}, "layouts": {klic sady: {"primary", "mirror",
#    "pos": {klic: [x, y]}}}, "modes": {klic sady: {"mode"}}}
#   klic vystupu "KONEKTOR|md5(EDID)[:12]", klic sady = serazene klice spojene "+".
# LUXOS_XRANDR prepise prikaz xrandr (testy).
load env, json, process
load luxos_glib, glib as glib
load luxos_displays as dw

ROTATIONS = ["normal", "right", "inverted", "left"]
MODES = ["extend", "mirror", "external", "internal"]
# Velikost textu = Xft/DPI v kanalu xsettings (xfsettingsd ji posle GTK, panelu, xfwm4, Qt i Firefoxu);
# None = vychozi (vlastnost se odstrani)
TEXT_SIZES = [84, None, 108, 120, 132]
DEFAULT_DPI = 96
RATE_CAP = 61000        # mHz: 59.94 / 60.00 / 60.02 Hz projdou, 90/120/144/165 Hz ne
ASPECT_TOLERANCE = 0.02 # 1366x768 i 1920x1080 jsou 16:9

function conf_path():
    path = env.get("LUXOS_DISPLAYS_CONF", "")
    if path != None and path != "":
        return path
    end
    return glib.user_config_dir() + "/luxos/displays.json"
end

# Program z PATH (nebo cesta); "" kdyz neni
function program(name):
    found = glib.find_program_in_path(name)
    if found == None:
        return ""
    end
    return found
end

# Vystup programu, "" pri chybe (jako drive subprocess.run s capture_output)
function run(argv):
    path = program(argv[0])
    if path == "":
        return ""
    end
    result = None
    safe:
        result = process.capture_result(path, argv[1:])
    end
    if result == None or not result["ok"]:
        return ""
    end
    return result["stdout"]
end

function run_ok(argv):
    path = program(argv[0])
    if path == "":
        return False
    end
    result = None
    safe:
        result = process.capture_result(path, argv[1:])
    end
    return result != None and result["ok"]
end

function xrandr_cmd():
    cmd = env.get("LUXOS_XRANDR", "")
    if cmd == None or cmd == "":
        return "xrandr"
    end
    return cmd
end

function run_xrandr(arguments):
    return run([xrandr_cmd()] + arguments)
end

# ---- parsovani xrandr ---------------------------------------------------------------------------------

function is_digits(s):
    if len(s) == 0:
        return False
    end
    for ch in s:
        if ord(ch) < 48 or ord(ch) > 57:
            return False
        end
    end
    return True
end

# Slova oddelena mezerami nebo tabulatory (jako str.split())
function words(s):
    return [w for w in s.replace("\t", " ").split(" ") if w != ""]
end

# "60.02" -> 60020; None kdyz to neni cislo (\d+(\.\d+)?)
function mhz(rate):
    if type(rate) != "String":
        return None
    end
    cut = rate.find(".")
    whole = rate
    frac = ""
    if cut >= 0:
        whole = rate[:cut]
        frac = rate[cut + 1:]
        if not is_digits(frac):
            return None
        end
    end
    if not is_digits(whole):
        return None
    end
    frac = (frac + "000")[:3]
    return Int(whole) * 1000 + Int(frac)
end

# "WxH+X+Y" (X, Y i zaporne) -> [w, h, x, y] nebo None
function parse_geometry(s):
    x = s.find("x")
    if x <= 0:
        return None
    end
    w = s[:x]
    rest = s[x + 1:]
    p = rest.find("+")
    if p <= 0 or not is_digits(w) or not is_digits(rest[:p]):
        return None
    end
    h = rest[:p]
    rest = rest[p + 1:]
    p = rest.find("+")
    if p < 0:
        return None
    end
    values = [rest[:p], rest[p + 1:]]
    result = [Int(w), Int(h)]
    for v in values:
        digits = v[1:] if v.startswith("-") else v
        if not is_digits(digits):
            return None
        end
        result.append(Int(v))
    end
    return result
end

# "344mm x 194mm" kdekoli v textu -> [344, 194] nebo None
function parse_mm(s):
    at = s.find("mm x ")
    while at >= 0:
        start = at
        while start > 0 and is_digits(s[start - 1]):
            start -= 1
        end
        tail = s[at + 5:]
        stop = 0
        while stop < len(tail) and is_digits(tail[stop]):
            stop += 1
        end
        if start < at and stop > 0 and tail[stop:].startswith("mm"):
            return [Int(s[start:at]), Int(tail[:stop])]
        end
        nxt = s[at + 1:].find("mm x ")
        at = -1 if nxt < 0 else at + 1 + nxt
    end
    return None
end

function is_hex(s):
    for ch in s.lower():
        if "0123456789abcdef".find(ch) < 0:
            return False
        end
    end
    return len(s) > 0
end

# Tokeny za nazvem rezimu -> [[frekvence, aktualni, doporucena]..]; xrandr pise priznaky primo za cislo
# ("60.00*+") nebo oddelene mezerou ("60.00 +")
function parse_rates(tokens):
    rates = []
    for tok in tokens:
        flags_only = True
        for ch in tok:
            if ch != "*" and ch != "+":
                flags_only = False
            end
        end
        if flags_only:
            if len(rates) > 0:
                last = rates[len(rates) - 1]
                last[1] = last[1] or tok.find("*") >= 0
                last[2] = last[2] or tok.find("+") >= 0
            end
            continue
        end
        stop = len(tok)
        while stop > 0 and (tok[stop - 1] == "*" or tok[stop - 1] == "+"):
            stop -= 1
        end
        number = tok[:stop]
        if mhz(number) == None or number.endswith("."):
            continue
        end
        flags = tok[stop:]
        rates.append([number, flags.find("*") >= 0, flags.find("+") >= 0])
    end
    return rates
end

function find_mode(out, name):
    for md in out["modes"]:
        if md["name"] == name:
            return md
        end
    end
    return None
end

# Vystup "xrandr [--current] [--prop]" -> seznam vystupu
function parse(text):
    outputs = []
    out = None
    in_edid = False
    for line in text.split("\n"):
        status = ""
        rest = ""
        if line != "" and line[0] != " " and line[0] != "\t":
            sp = line.find(" ")
            if sp > 0:
                tail = line[sp + 1:]
                for word in ["connected", "disconnected", "unknown connection"]:
                    if status == "" and tail.startswith(word):
                        status = word
                        rest = tail[len(word):]
                    end
                end
            end
        end
        if status != "":
            out = {"name": line[:line.find(" ")], "connected": status == "connected", "primary": False,
                   "active": False, "geometry": None, "rotation": "normal", "rotations": ROTATIONS[:],
                   "mm": [0, 0], "edid": "", "modes": []}
            outputs.append(out)
            in_edid = False
            cut = rest.find("(")
            head = rest if cut < 0 else rest[:cut]
            tail = "" if cut < 0 else rest[cut + 1:]
            ws = words(head)
            if "primary" in ws:
                out["primary"] = True
                ws = [w for w in ws if w != "primary"]
            end
            if len(ws) > 0:
                g = parse_geometry(ws[0])
                if g != None:
                    out["geometry"] = g
                    out["active"] = True
                    if len(ws) > 1 and ws[1] in ROTATIONS:
                        out["rotation"] = ws[1]
                    end
                end
            end
            cut = tail.find(")")
            supported = tail if cut < 0 else tail[:cut]
            after = "" if cut < 0 else tail[cut + 1:]
            rots = [w for w in words(supported) if w in ROTATIONS]
            if len(rots) > 0:
                out["rotations"] = rots
            end
            mm = parse_mm(after)
            if mm != None:
                out["mm"] = mm
            end
            continue
        end
        if out == None:
            continue
        end
        if line.startswith("\t"):
            # vlastnosti (--prop): EDID je hex na nasledujicich radcich s dvojitym tabulatorem
            stripped = line.strip()
            if stripped.startswith("EDID:"):
                in_edid = True
                continue
            end
            if in_edid and line.startswith("\t\t") and is_hex(stripped):
                out["edid"] = out["edid"] + stripped.lower()
                continue
            end
            in_edid = False
            continue
        end
        in_edid = False
        if line.startswith("  ") and not line.startswith("    "):
            parts = words(line)
            if len(parts) == 0 or parts[0].find("x") < 0:
                continue
            end
            md = find_mode(out, parts[0])
            if md == None:
                md = {"name": parts[0], "rates": [], "current": None, "preferred": None}
                out["modes"].append(md)
            end
            for r in parse_rates(parts[1:]):
                if r[0] not in md["rates"]:
                    md["rates"].append(r[0])
                end
                if r[1]:
                    md["current"] = r[0]
                end
                if r[2] and md["preferred"] == None:
                    md["preferred"] = r[0]
                end
            end
        end
    end
    return outputs
end

function query():
    return parse(run_xrandr(["--current", "--prop"]))
end

function connected(outputs):
    return [o for o in outputs if o["connected"]]
end

# ---- rezimy ---------------------------------------------------------------------------------------------

# Velikost z nazvu rezimu ("1920x1080", "1920x1080i", "1920x1080_60.00") -> [w, h], [0, 0] kdyz neni
function mode_size(name):
    if type(name) != "String":
        return [0, 0]
    end
    x = name.find("x")
    if x <= 0 or not is_digits(name[:x]):
        return [0, 0]
    end
    stop = x + 1
    while stop < len(name) and is_digits(name[stop]):
        stop += 1
    end
    if stop == x + 1:
        return [0, 0]
    end
    return [Int(name[:x]), Int(name[x + 1:stop])]
end

function is_interlaced(name):
    x = name.find("x")
    return x > 0 and name.endswith("i") and is_digits(name[:x]) and is_digits(name[x + 1:len(name) - 1])
end

# [rezim, frekvence] prave pouzivane vystupem, nebo [None, None]
function current_mode(out):
    for md in out["modes"]:
        if md["current"] != None:
            return [md["name"], md["current"]]
        end
    end
    return [None, None]
end

# Doporuceny rezim monitoru (EDID "+"), jinak prvni (nejvetsi) v seznamu
function preferred_mode(out):
    for md in out["modes"]:
        if md["preferred"] != None:
            return [md["name"], md["preferred"]]
        end
    end
    if len(out["modes"]) > 0:
        md = out["modes"][0]
        return [md["name"], md["rates"][0] if len(md["rates"]) > 0 else None]
    end
    return [None, None]
end

# Pouziva vystup meritko (--scale/--scale-from ze zrcadleni)? Plocha v hlavicce se pak lisi od rezimu.
function is_scaled(out):
    if out["geometry"] == None:
        return False
    end
    name = current_mode(out)[0]
    if name == None:
        return False
    end
    size = mode_size(name)
    if out["rotation"] == "left" or out["rotation"] == "right":
        size = [size[1], size[0]]
    end
    return out["geometry"][0] != size[0] or out["geometry"][1] != size[1]
end

# Navrat meritka 1:1 po zrcadleni s --scale-from (jinak by rozsirena plocha zustala zmensena)
function unscale_args(out):
    if is_scaled(out):
        return ["--scale", "1x1"]
    end
    return []
end

function max_rate(rates):
    best = None
    for r in rates:
        if best == None or mhz(r) > mhz(best):
            best = r
        end
    end
    return best
end

# Frekvence pro nove vybrany rezim: doporucena, jinak nejvyssi
function best_rate(md, preferred):
    if len(md["rates"]) == 0:
        return None
    end
    if preferred != None and preferred in md["rates"]:
        return preferred
    end
    if md["preferred"] != None:
        return md["preferred"]
    end
    return max_rate(md["rates"])
end

# [[rezim, doporuceny]..] k nabidnuti: bez prokladanych a duplicit, od nejvetsiho
function resolution_choices(out):
    pref = preferred_mode(out)[0]
    cur = current_mode(out)[0]
    seen = []
    for md in out["modes"]:
        name = md["name"]
        if (is_interlaced(name) and name != cur) or name in seen:
            continue
        end
        seen.append(name)
    end
    i = 1
    while i < len(seen):
        j = i
        while j > 0 and size_key_greater(seen[j], seen[j - 1]):
            t = seen[j]
            seen[j] = seen[j - 1]
            seen[j - 1] = t
            j -= 1
        end
        i += 1
    end
    return [[n, n == pref] for n in seen]
end

function size_key_greater(a, b):
    sa = mode_size(a)
    sb = mode_size(b)
    if sa[0] * sa[1] != sb[0] * sb[1]:
        return sa[0] * sa[1] > sb[0] * sb[1]
    end
    return sa[0] > sb[0]
end

function fmt_rate(rate):
    m = mhz(rate)
    if m == None:
        return rate
    end
    # 2 desetinna mista jako "%.2f" (xrandr je pise vzdy, mHz je presnejsi)
    hundredths = (m + 5) // 10
    if hundredths % 100 == 0:
        return String(hundredths // 100) + " Hz"
    end
    return String(hundredths // 100) + "." + String(hundredths % 100 + 100)[1:] + " Hz"
end

function fmt_mode(name):
    size = mode_size(name)
    if size[0] == 0:
        return name
    end
    return String(size[0]) + " × " + String(size[1]) + (" i" if is_interlaced(name) else "")
end

# ---- nazev monitoru -----------------------------------------------------------------------------------

# G_CHECKSUM_MD5 = 0 (stejny otisk jako hashlib.md5 v Pythonu: ulozene klice zustanou platne)
function edid_id(edid):
    if edid == "":
        return ""
    end
    unsafe:
        return glib.take_c(__lsl_qbe_call3(__lsl_symbol("g_compute_checksum_for_string"), 0, glib.cstr(edid), -1))[:12]
    end
end

function hex_byte(s, i):
    return Int("0123456789abcdef".find(s[2 * i]) * 16 + "0123456789abcdef".find(s[2 * i + 1]))
end

# Nazev modelu z EDID (deskriptor 0xFC), nebo ""
function edid_name(edid):
    s = edid.lower()
    if len(s) % 2 != 0 or (s != "" and not is_hex(s)) or len(s) < 256:
        return ""
    end
    for off in [54, 72, 90, 108]:
        if hex_byte(s, off) == 0 and hex_byte(s, off + 1) == 0 and hex_byte(s, off + 2) == 0 and hex_byte(s, off + 3) == 252:
            name = ""
            for i in range(off + 5, off + 18):
                b = hex_byte(s, i)
                if b == 10:
                    break
                end
                name = name + (chr(b) if b < 128 else chr(65533))
            end
            return name.strip()
        end
    end
    return ""
end

function is_internal(name):
    return dw.is_internal(name)
end

function output_key(out):
    return out["name"] + "|" + edid_id(out["edid"])
end

function set_key(outputs):
    return "+".join(sorted([output_key(o) for o in outputs if o["connected"]]))
end

# ---- ulozene nastaveni ----------------------------------------------------------------------------------

function read_conf(path):
    data = None
    safe:
        data = json.decode(glib.read_text(path))
    end
    if type(data) != "Dictionary":
        return {}
    end
    return data
end

function dict_part(path, name):
    part = read_conf(path).get(name)
    result = {}
    if type(part) == "Dictionary":
        for k in part.keys():
            if type(part[k]) == "Dictionary":
                result[k] = part[k]
            end
        end
    end
    return result
end

function path_or_default(path):
    if path == None or path == "":
        return conf_path()
    end
    return path
end

function load(path):
    return dict_part(path_or_default(path), "outputs")
end

# Ulozena rozlozeni monitoru {klic sady: rozlozeni}
function load_layouts(path):
    return dict_part(path_or_default(path), "layouts")
end

# Ulozene rezimy vice monitoru {klic sady: {"mode": rezim}}
function load_modes(path):
    modes = dict_part(path_or_default(path), "modes")
    result = {}
    for k in modes.keys():
        if modes[k].get("mode") in MODES:
            result[k] = modes[k]
        end
    end
    return result
end

# Ulozit zaznamy monitoru; layouts/modes None = ponechat rozlozeni a rezimy ze souboru
function save(entries, path, layouts, modes):
    path = String(path_or_default(path))
    if layouts == None:
        layouts = load_layouts(path)
    end
    if modes == None:
        modes = load_modes(path)
    end
    cut = len(path) - 1
    while cut > 0 and path[cut] != "/":
        cut -= 1
    end
    if cut > 0:
        call glib.mkdir_p(path[:cut])
    end
    data = {"version": 1, "outputs": entries}
    if len(layouts) > 0:
        data["layouts"] = layouts
    end
    if len(modes) > 0:
        data["modes"] = modes
    end
    return glib.write_atomic(path, json.encode(data) + chr(10))
end

# Zaznam k ulozeni, nebo None pro vychozi stav (doporuceny rezim, bez otoceni)
function entry_for(out, mode, rate, rotation):
    pref = preferred_mode(out)
    if mode == pref[0] and (rate == None or rate == "" or rate == pref[1]) and rotation == "normal":
        return None
    end
    e = {"mode": mode, "rotate": rotation}
    if rate != None and rate != "":
        e["rate"] = rate
    end
    return e
end

# Argumenty xrandr pro ulozeny zaznam (bez --output), nebo None, kdyz neplati
function output_args(out, entry):
    if type(entry) != "Dictionary" or len(entry) == 0 or not out["connected"]:
        return None
    end
    md = find_mode(out, entry.get("mode", ""))
    rot = entry.get("rotate", "normal")
    if rot not in out["rotations"]:
        rot = "normal"
    end
    if md == None:
        # rezim monitor nenabizi (jiny monitor, zmena ovladace): jen otoceni, rezim automaticky
        if rot == "normal":
            return None
        end
        return ["--auto", "--rotate", rot]
    end
    args = ["--mode", md["name"]]
    rate = entry.get("rate")
    if type(rate) == "String" and rate != "" and rate in md["rates"]:
        args = args + ["--rate", rate]
    end
    return args + ["--rotate", rot]
end

# [[vystup, argumenty]..] pro vystupy se zaznamem a pro vystupy se zbylym meritkem ze zrcadleni
function all_output_args(outputs, entries):
    lines = []
    for out in outputs:
        if not out["connected"]:
            continue
        end
        args = output_args(out, entries.get(output_key(out)))
        unscale = unscale_args(out)
        if len(unscale) > 0:
            args = (args if args != None else ["--auto"]) + unscale
        end
        if args != None:
            lines.append([out["name"], args])
        end
    end
    return lines
end

# ---- Sporic baterie: vestaveny displej nejvys 60 Hz -------------------------------------------------------

# [rezim, aktualni, nova frekvence] pro snizeni frekvence vestaveneho displeje, nebo None
function rate_cap_target(out):
    if not (is_internal(out["name"]) and out["connected"] and out["active"]):
        return None
    end
    cur = current_mode(out)
    if cur[0] == None or mhz(cur[1]) <= RATE_CAP:
        return None
    end
    md = find_mode(out, cur[0])
    low = max_rate([r for r in md["rates"] if mhz(r) <= RATE_CAP])
    if low == None:
        return None
    end
    return [cur[0], cur[1], low]
end

# Snizi frekvenci; [[vystup, rezim, puvodni frekvence]..] pro pozdejsi navrat
function rate_cap(outputs):
    done = []
    for out in outputs:
        t = rate_cap_target(out)
        if t != None:
            call run_xrandr(["--output", out["name"], "--mode", t[0], "--rate", t[2]])
            done.append([out["name"], t[0], t[1]])
        end
    end
    return done
end

# Vrati puvodni frekvenci, jen kdyz vystup porad pouziva stejny rezim a frekvenci nabizi
function rate_restore(outputs, name, mode, rate):
    out = None
    for o in outputs:
        if o["name"] == name and o["connected"] and o["active"]:
            out = o
        end
    end
    if out == None:
        return False
    end
    cur = current_mode(out)
    md = find_mode(out, mode)
    if cur[0] != mode or md == None or rate not in md["rates"] or cur[1] == rate:
        return False
    end
    call run_xrandr(["--output", name, "--mode", mode, "--rate", rate])
    return True
end

# ---- velikost textu (xsettings Xft/DPI) -------------------------------------------------------------------

# Meritko obrazovky (jako 100-200 % ve Windows): 100-150 % = vetsi pismo (Xft/DPI), horni lista, Dock, kurzor
# a ramecky oken; 175 a 200 % = GTK 2x (Gdk/WindowScalingFactor) a DPI dopocitane na presny pomer.
# Velikost textu (TEXT_SIZES) se pocita relativne k meritku. Ulozene v ~/.config/luxos/display-scale.
SCALES = [100, 125, 150, 175, 200]
PANEL_SIZE = 28
DOCK_ICONS = 48
CURSOR_SIZE = 24

function scale_factor(scale):
    return 2 if scale >= 175 else 1
end

# Xft/DPI pro meritko pri vychozi velikosti textu (s WindowScalingFactor 2 se pismo jeste zdvojnasobi)
function scale_dpi(scale):
    return Int(Float(DEFAULT_DPI * scale) / 100.0 / Float(scale_factor(scale)) + 0.5)
end

function scale_path():
    return glib.user_config_dir() + "/luxos/display-scale"
end

function read_scale():
    value = 100
    safe:
        value = Int(glib.read_text(scale_path()).strip())
    end
    if not (value in SCALES):
        value = 100
    end
    return value
end

# Index v TEXT_SIZES pro Xft/DPI pri danem meritku (None/neplatne = vychozi, jinak nejblizsi)
function text_size_index(dpi):
    scale = read_scale()
    base = scale_dpi(scale)
    if dpi == None or dpi <= 0:
        dpi = base
    end
    rel = Float(dpi * DEFAULT_DPI) / Float(base)
    if abs(rel - Float(DEFAULT_DPI)) < 1.0:
        return 1
    end
    best = 0
    for i in range(len(TEXT_SIZES)):
        v = TEXT_SIZES[i] if TEXT_SIZES[i] != None else DEFAULT_DPI
        b = TEXT_SIZES[best] if TEXT_SIZES[best] != None else DEFAULT_DPI
        if abs(Float(v) - rel) < abs(Float(b) - rel):
            best = i
        end
    end
    return best
end

function read_dpi():
    text = run(["xfconf-query", "-c", "xsettings", "-p", "/Xft/DPI"]).strip()
    value = None
    safe:
        value = Int(text)
    end
    return value
end

function dpi_for(index, scale):
    size = TEXT_SIZES[index] if TEXT_SIZES[index] != None else DEFAULT_DPI
    return Int(Float(scale_dpi(scale) * size) / Float(DEFAULT_DPI) + 0.5)
end

# Velikost textu relativne k meritku; vychozi krok pri 100 % vlastnost odstrani (navrat k vychozimu DPI)
function set_text_size(index):
    scale = read_scale()
    dpi = dpi_for(index, scale)
    if dpi == DEFAULT_DPI and scale_factor(scale) == 1:
        return run_ok(["xfconf-query", "-c", "xsettings", "-p", "/Xft/DPI", "-r"])
    end
    return run_ok(["xfconf-query", "-c", "xsettings", "-p", "/Xft/DPI", "-n", "-t", "int", "-s", String(dpi)])
end

# Kolikrat vetsi kresli LuxOS prvky, ktere GTK samo nezvetsuje (lista, Dock): 125 % = 1.25, 200 % = 1.0
function scale_effective(scale):
    return Float(scale) / 100.0 / Float(scale_factor(scale))
end

# Nova velikost prvku pri zmene meritka; vlastni velikost uzivatele (prepoctena na 100 %) zustava
function scaled_size(current, base, old_scale, new_scale, lo, hi):
    unit = base
    if current != None and current > 0:
        unit = Int(Float(current) / scale_effective(old_scale) + 0.5)
    end
    return max(lo, min(hi, Int(Float(unit) * scale_effective(new_scale) + 0.5)))
end

function xfconf_int(channel, prop):
    value = None
    safe:
        value = Int(run(["xfconf-query", "-c", channel, "-p", prop]).strip())
    end
    return value
end

PLANK = ["net.launchpad.plank.dock.settings:/net/launchpad/plank/docks/dock1/", "icon-size"]

# Nastavi meritko (100-200 %). Velikost textu, vlastni velikost listy a Docku zustanou.
function set_scale(scale):
    if not (scale in SCALES):
        return False
    end
    old = read_scale()
    text = text_size_index(read_dpi())
    wsf = scale_factor(scale)
    ok = run_ok(["xfconf-query", "-c", "xsettings", "-p", "/Gdk/WindowScalingFactor", "-n", "-t", "int", "-s", String(wsf)])
    dpi = dpi_for(text, scale)
    if dpi == DEFAULT_DPI and wsf == 1:
        call run_ok(["xfconf-query", "-c", "xsettings", "-p", "/Xft/DPI", "-r"])
    else:
        ok = run_ok(["xfconf-query", "-c", "xsettings", "-p", "/Xft/DPI", "-n", "-t", "int", "-s", String(dpi)]) and ok
    end
    call run_ok(["xfconf-query", "-c", "xsettings", "-p", "/Gtk/CursorThemeSize", "-n", "-t", "int", "-s",
                 String(Int(Float(CURSOR_SIZE) * scale_effective(scale) + 0.5))])
    panel = xfconf_int("xfce4-panel", "/panels/panel-1/size")
    call run_ok(["xfconf-query", "-c", "xfce4-panel", "-p", "/panels/panel-1/size", "-n", "-t", "uint", "-s",
                 String(scaled_size(panel, PANEL_SIZE, old, scale, 16, 64))])
    icons = None
    safe:
        icons = Int(run(["gsettings", "get", PLANK[0], PLANK[1]]).strip())
    end
    if program("gsettings") != "" and run(["gsettings", "get", PLANK[0], PLANK[1]]).strip() != "":
        call run_ok(["gsettings", "set", PLANK[0], PLANK[1], String(scaled_size(icons, DOCK_ICONS, old, scale, 24, 128))])
    end
    call glib.mkdir_p(glib.user_config_dir() + "/luxos")
    call glib.write_atomic(scale_path(), String(scale) + "\n")
    # ramecky oken: hdpi (1,5x) pro 125-150 %, xhdpi pro 2x
    call run_ok(["luxos-appearance", "wm-theme"])
    return ok
end

# Profil "Default" z dialogu Xfce by xfsettingsd pouzil po prihlaseni pred LuxOS - smazat
function forget_xfce_profile():
    for p in words(run(["xfconf-query", "-c", "displays", "-l"]).replace("\n", " ")):
        if p.startswith("/Default/"):
            call run_ok(["xfconf-query", "-c", "displays", "-p", "/Default", "-r", "-R"])
            return True
        end
    end
    return False
end

# ---- rozlozeni (jako Usporadani v macOS) --------------------------------------------------------------------

function rect_size(mode, rotation):
    size = mode_size(mode if mode != None else "")
    if rotation == "left" or rotation == "right":
        return [size[1], size[0]]
    end
    return size
end

# {nazev: [x, y, w, h]} aktivnich monitoru podle xrandr
function current_rects(outputs):
    result = {}
    for o in outputs:
        if o["connected"] and o["geometry"] != None:
            g = o["geometry"]
            result[o["name"]] = [g[2], g[3], g[0], g[1]]
        end
    end
    return result
end

function key_edid(key):
    cut = key.find("|")
    if cut < 0:
        return ""
    end
    return key[cut + 1:]
end

# Ulozeny zaznam pro pripojene monitory: [zaznam, {klic vystupu: nazev}, klic], jinak [None, {}, ""].
# Nejdriv presna sada konektor+EDID, pak sada podle EDID (vsechny monitory s EDID, kazdy jiny).
function find_layout(layouts, outputs):
    conn = connected(outputs)
    if len(conn) < 2:
        return [None, {}, ""]
    end
    key = set_key(outputs)
    lay = layouts.get(key)
    if type(lay) == "Dictionary":
        names = {}
        for o in conn:
            names[output_key(o)] = o["name"]
        end
        return [lay, names, key]
    end
    ids = [edid_id(o["edid"]) for o in conn]
    for i in ids:
        if i == "" or ids.count(i) > 1:
            return [None, {}, ""]
        end
    end
    by_edid = {}
    for o in conn:
        by_edid[edid_id(o["edid"])] = o["name"]
    end
    for k in sorted(layouts.keys()):
        lay = layouts[k]
        if type(lay) != "Dictionary":
            continue
        end
        keys = k.split("+")
        if sorted([key_edid(x) for x in keys]) == sorted(ids):
            names = {}
            for x in keys:
                names[x] = by_edid[key_edid(x)]
            end
            return [lay, names, k]
        end
    end
    return [None, {}, ""]
end

# Zaznam k ulozeni z poloh {nazev: [x, y]} a nazvu hlavniho monitoru
function make_layout(outputs, pos, primary, mirror):
    keys = {}
    for o in connected(outputs):
        keys[o["name"]] = output_key(o)
    end
    stored = {}
    for n in pos.keys():
        if n in keys:
            stored[keys[n]] = [Int(pos[n][0]), Int(pos[n][1])]
        end
    end
    return {"primary": keys.get(primary, ""), "mirror": mirror == True, "pos": stored}
end

# Ulozeny rezim vice monitoru pro pripojenou sadu (hleda se jako rozlozeni), nebo None
function mode_for(outputs, modes):
    rec = find_layout(modes, outputs)[0]
    if rec == None or rec.get("mode") not in MODES:
        return None
    end
    return rec["mode"]
end

# Rezimy s novym rezimem pro pripojenou sadu (jeden monitor: None, neni co ukladat). Zaznam nalezeny
# jen podle EDID (jine konektory) se prepise pod presnym klicem sady.
function with_mode(modes, outputs, mode):
    if len(connected(outputs)) < 2 or mode not in MODES:
        return None
    end
    found = find_layout(modes, outputs)
    result = {}
    for k in modes.keys():
        if found[0] == None or k != found[2]:
            result[k] = modes[k]
        end
    end
    result[set_key(outputs)] = {"mode": mode}
    return result
end

# ---- zrcadleni ----------------------------------------------------------------------------------------------

function aspect(name):
    size = mode_size(name)
    if size[1] == 0:
        return 0.0
    end
    return Float(size[0]) / Float(size[1])
end

function area(name):
    size = mode_size(name)
    return size[0] * size[1]
end

# Neprokladane rezimy vystupu (prokladane na monitorech blikaji)
function plain_modes(out):
    return [md["name"] for md in out["modes"] if not is_interlaced(md["name"]) and mode_size(md["name"])[0] > 0]
end

# [stejny pomer stran, plocha, sirka, nazev] > jiny?
function score_greater(a, b):
    for i in range(4):
        if a[i] != b[i]:
            if i == 0:
                return a[0]
            end
            return a[i] > b[i]
        end
    end
    return False
end

# Rozliseni pro zrcadleni, ktere umi vsechny vystupy, nebo None. `wanted` = rezimy hlavniho monitoru podle
# priority (ulozeny, nativni): prvni spolecny vyhrava. Jinak nejlepsi spolecny: se stejnym pomerem stran jako
# prvni z wanted (aspon polovicni plocha nejvetsiho spolecneho), pak nejvetsi.
function common_mode(outputs, wanted):
    if len(outputs) == 0:
        return None
    end
    common = []
    for name in plain_modes(outputs[0]):
        if name in common:
            continue
        end
        everywhere = True
        for o in outputs[1:]:
            if name not in plain_modes(o):
                everywhere = False
            end
        end
        if everywhere:
            common.append(name)
        end
    end
    for name in wanted:
        if name in common:
            return name
        end
    end
    if len(common) == 0:
        return None
    end
    target = aspect(wanted[0]) if len(wanted) > 0 else 0.0
    biggest = max([area(n) for n in common])
    best = None
    best_score = None
    for name in common:
        same = target > 0 and abs(aspect(name) - target) <= ASPECT_TOLERANCE * target and area(name) * 2 >= biggest
        score = [same, area(name), mode_size(name)[0], name]
        if best == None or score_greater(score, best_score):
            best = name
            best_score = score
        end
    end
    return best
end

# Frekvence rezimu pro zrcadleni: doporucena, kdyz je to doporuceny rezim, jinak nejblize 60 Hz
function mirror_rate(out, name):
    md = find_mode(out, name)
    if md == None or len(md["rates"]) == 0:
        return None
    end
    if md["preferred"] != None:
        return md["preferred"]
    end
    best = None
    for r in md["rates"]:
        if best == None:
            best = r
        else:
            d = abs(mhz(r) - 60000)
            bd = abs(mhz(best) - 60000)
            if d < bd or (d == bd and mhz(r) > mhz(best)):
                best = r
            end
        end
    end
    return best
end

# Hlavni monitor pro zrcadleni: z ulozeneho rozlozeni, jinak vestaveny, jinak aktualni hlavni, jinak prvni
function mirror_primary(outputs, layouts):
    conn = [o for o in outputs if o["connected"] and len(o["modes"]) > 0]
    if layouts != None and len(layouts) > 0:
        found = find_layout(layouts, outputs)
        if found[0] != None:
            name = found[1].get(found[0].get("primary"))
            for o in conn:
                if o["name"] == name:
                    return name
                end
            end
        end
    end
    for o in conn:
        if is_internal(o["name"]):
            return o["name"]
        end
    end
    for o in conn:
        if o["primary"]:
            return o["name"]
        end
    end
    if len(conn) > 0:
        return conn[0]["name"]
    end
    return None
end

# (argumenty rezimu, rezim, otoceni) vystupu se zaznamem z Monitoru nebo bez nej
function effective(out, entry):
    args = output_args(out, entry)
    pmode = preferred_mode(out)[0]
    if args == None:
        rot = "normal"
        auto = ["--auto"]
        if rot in out["rotations"]:
            auto = auto + ["--rotate", rot]
        end
        return [auto, pmode, rot]
    end
    mode = pmode
    rot = "normal"
    if "--mode" in args:
        mode = args[args.index("--mode") + 1]
    end
    if "--rotate" in args:
        rot = args[args.index("--rotate") + 1]
    end
    return [args, mode, rot]
end

# Prikaz xrandr pro zrcadleni vsech pripojenych monitoru, nebo None (mene nez dva): vsechny v 0,0 se spolecnym
# rozlisenim; kdyz neni, ostatni ve svem doporucenem rezimu s --scale-from na velikost hlavniho (obraz se
# zmensi/roztahne cely, nic se neorizne). {"args", "primary", "mode" (nebo None), "scale": {vystup: "WxH"}}
function mirror_plan(outputs, entries, layouts, primary):
    conn = [o for o in outputs if o["connected"] and len(o["modes"]) > 0]
    if len(conn) < 2:
        return None
    end
    if primary not in [o["name"] for o in conn]:
        primary = mirror_primary(outputs, layouts)
    end
    prim = None
    for o in conn:
        if o["name"] == primary:
            prim = o
        end
    end
    wanted = []
    saved = effective(prim, entries.get(output_key(prim)) if entries != None else None)[1]
    pref = preferred_mode(prim)[0]
    for name in [saved, pref]:
        if name != None and name not in wanted and not is_interlaced(name):
            wanted.append(name)
        end
    end
    mode = common_mode(conn, wanted)
    chosen = {}
    scale = {}
    if mode != None:
        for o in conn:
            chosen[o["name"]] = mode
        end
    else:
        # bez spolecneho rozliseni: hlavni nativne, ostatni v doporucenem rezimu zmensene/zvetsene
        base = wanted[0] if len(wanted) > 0 else plain_modes(prim)[0]
        bsize = mode_size(base)
        for o in conn:
            if o["name"] == primary:
                chosen[o["name"]] = base
            else:
                own = preferred_mode(o)[0]
                if own == None or is_interlaced(own):
                    own = plain_modes(o)[0]
                end
                chosen[o["name"]] = own
                if mode_size(own) != bsize:
                    scale[o["name"]] = String(bsize[0]) + "x" + String(bsize[1])
                end
            end
        end
    end
    args = []
    for out in outputs:
        if not out["connected"] or len(out["modes"]) == 0:
            args = args + ["--output", out["name"], "--off"]
        end
    end
    others = sorted([o["name"] for o in conn if o["name"] != primary])
    for name in [primary] + others:
        o = None
        for c in conn:
            if c["name"] == name:
                o = c
            end
        end
        args = args + ["--output", name, "--mode", chosen[name]]
        rate = mirror_rate(o, chosen[name])
        if rate != None:
            args = args + ["--rate", rate]
        end
        args = args + ["--rotate", "normal"]
        if name in scale:
            args = args + ["--scale-from", scale[name]]
        else:
            args = args + ["--scale", "1x1"]
        end
        args = args + ["--pos", "0x0"]
        if name == primary:
            args.append("--primary")
        end
    end
    return {"args": args, "primary": primary, "mode": mode, "scale": scale}
end

# ---- prikaz xrandr podle ulozeneho rozlozeni ---------------------------------------------------------------

function int_pair(p):
    if type(p) != "List" or len(p) < 2:
        return None
    end
    result = []
    for v in p[:2]:
        if type(v) == "Int":
            result.append(v)
        elif type(v) == "Float":
            result.append(Int(v))
        else:
            return None
        end
    end
    return result
end

# Prikaz xrandr podle ulozeneho rozlozeni, nebo None (zadne pro tuto sadu): {"args", "pos": {nazev: [x, y]},
# "primary", "mirror"}. Polohy se znovu usadi podle aktualnich velikosti (jine rozliseni nebo otoceni nesmi
# vytvorit mezeru ani prekryv). force_extend: zrcadleni vypnout (Super+P Rozsirit).
function plan(outputs, entries, layouts, force_extend):
    found = find_layout(layouts, outputs)
    lay = found[0]
    names = found[1]
    if lay == None:
        return None
    end
    conn = {}
    for o in outputs:
        if o["connected"]:
            conn[o["name"]] = o
        end
    end
    stored = lay.get("pos") if type(lay.get("pos")) == "Dictionary" else {}
    sizes = {}
    proposals = {}
    margs = {}
    for key in names.keys():
        name = names[key]
        out = conn[name]
        e = effective(out, entries.get(output_key(out)))
        margs[name] = e[0]
        sizes[name] = rect_size(e[1], e[2])
        proposals[name] = int_pair(stored.get(key))
    end
    # monitor bez ulozene polohy: vpravo od ostatnich
    right = 0
    for n in proposals.keys():
        if proposals[n] != None:
            right = max(right, proposals[n][0] + sizes[n][0])
        end
    end
    for n in sorted(proposals.keys()):
        if proposals[n] == None:
            proposals[n] = [right, 0]
            right += sizes[n][0]
        end
    end
    primary = names.get(lay.get("primary")) if type(lay.get("primary")) == "String" else None
    if primary not in conn:
        primary = sorted(conn.keys())[0]
        for n in sorted(conn.keys()):
            if is_internal(n):
                primary = n
                break
            end
        end
    end
    if lay.get("mirror") == True and not force_extend:
        m = mirror_plan(outputs, entries, None, primary)
        if m != None:
            pos = {}
            for n in conn.keys():
                pos[n] = [0, 0]
            end
            return {"args": m["args"], "pos": pos, "primary": primary, "mirror": True}
        end
    end
    rects = {}
    for n in conn.keys():
        rects[n] = [proposals[n][0], proposals[n][1], sizes[n][0], sizes[n][1]]
    end
    pos = dw.settle(sizes, proposals, dw.settle_order(rects, primary), {})
    args = []
    for out in outputs:
        if not out["connected"]:
            args = args + ["--output", out["name"], "--off"]
        end
    end
    for name in [primary] + sorted([n for n in conn.keys() if n != primary]):
        args = args + ["--output", name] + margs[name] + unscale_args(conn[name])
        args = args + ["--pos", String(pos[name][0]) + "x" + String(pos[name][1])]
        if name == primary:
            args.append("--primary")
        end
    end
    return {"args": args, "pos": pos, "primary": primary, "mirror": False}
end

# Odpovida skutecny stav (xrandr) planu? Polohy aktivnich monitoru a hlavni monitor.
function matches(outputs, expected):
    act = {}
    for o in outputs:
        if o["connected"] and o["geometry"] != None:
            act[o["name"]] = o
        end
    end
    for name in expected["pos"].keys():
        o = act.get(name)
        p = expected["pos"][name]
        if o == None or o["geometry"][2] != p[0] or o["geometry"][3] != p[1]:
            return False
        end
    end
    prim = act.get(expected["primary"])
    return prim != None and prim["primary"]
end
