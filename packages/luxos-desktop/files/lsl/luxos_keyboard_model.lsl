# LuxOS - rozlozeni klavesnice pro cely system (vsechny uzivatele a prihlasovaci obrazovku), drive
# files/python/luxos_keyboard.py. Pouziva okno Klavesnice (luxos-keyboard-settings) na X11 i Waylandu
# a prevod stareho vychoziho prepinani v luxos-desktop.install (--migrate-switch).
#
# Systemove nastaveni je v /etc/X11/xorg.conf.d/00-keyboard.conf ve formatu, ktery pise systemd-localed
# (localectl set-x11-keymap). Z nej si rozlozeni bere X server (relace, prihlasovaci obrazovka) a localed
# z nej odvodi i konzoli (/etc/vconsole.conf). Uzivatelske Xfce se ridi systemem, dokud ma kanal
# keyboard-layout /Default/XkbDisable = true. Instalator zapisuje stejny format v setup-chroot.sh.
#
# Rozlozeni = [rozlozeni, varianta]; nastaveni = {"layouts": [..], "model": text, "options": [..]}.
# LUXOS_KEYBOARD_CONF, LUXOS_VCONSOLE_CONF, LUXOS_XKB_RULES a LUXOS_KEYBOARD_MIGRATED prepisou cesty (testy).
load env
load luxos_glib as lglib
load luxos_text as text

CONF = "/etc/X11/xorg.conf.d/00-keyboard.conf"
VCONSOLE = "/etc/vconsole.conf"
RULES = "/usr/share/X11/xkb/rules/evdev.lst"
MIGRATED = "/var/lib/luxos/keyboard-switch-migrated"
MAX_LAYOUTS = 4   # XKB umi nejvyse 4 skupiny
# Vychozi prepinani: obe klavesy Shift naraz (Alt+Shift kolidoval se zkratkami Alt+Shift+...)
DEFAULT_SWITCH = "grp:shifts_toggle"
OLD_DEFAULT_SWITCH = "grp:alt_shift_toggle"   # vychozi do LuxOS 0.9.4; nahodne selhaval
# Prepinani rozlozeni (XkbOptions grp:...); Super+Mezernik je Hledani, Alt+Mezernik nabidka okna
SWITCH_OPTIONS = [["grp:shifts_toggle", "Both Shift keys"], ["grp:alt_shift_toggle", "Alt + Shift"],
    ["grp:ctrl_shift_toggle", "Ctrl + Shift"], ["grp:caps_toggle", "Caps Lock"], ["grp:menu_toggle", "Menu key"],
    ["", "Only by clicking the flag in the menu bar"]]
# Bezna rozlozeni nahore seznamu (stejne nazvy jako v instalatoru, maji preklad)
COMMON = [["English (US)", "us", ""], ["Czech", "cz", ""], ["Czech (QWERTY)", "cz", "qwerty"], ["Slovak", "sk", ""],
    ["Slovak (QWERTY)", "sk", "qwerty"], ["German", "de", ""], ["English (UK)", "gb", ""], ["French", "fr", ""],
    ["Spanish", "es", ""], ["Italian", "it", ""], ["Polish", "pl", ""], ["Hungarian", "hu", ""], ["Ukrainian", "ua", ""],
    ["Portuguese", "pt", ""], ["Portuguese (Brazil)", "br", ""], ["Swedish", "se", ""]]
LOWER = "abcdefghijklmnopqrstuvwxyz"
DIGITS = "0123456789"
UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

function path_of(name, default):
    value = env.get(name, "")
    if value != "":
        return value
    end
    return default
end

# ---- cteni ---------------------------------------------------------------------------------------------

function from_strings(layout, variant, options, model):
    codes = layout.split(",")
    variants = variant.split(",")
    layouts = []
    for i in range(len(codes)):
        if codes[i].strip() != "":
            layouts.append([codes[i].strip(), variants[i].strip() if i < len(variants) else ""])
        end
    end
    return {"layouts": layouts, "model": model.strip(), "options": [o.strip() for o in options.split(",") if o.strip() != ""]}
end

# Option "Klic" "hodnota" -> [klic, hodnota]; jiny radek -> []
function option_line(line):
    item = line.strip()
    if not item.startswith("Option"):
        return []
    end
    parts = item[6:].split("\"")
    # ["  ", klic, " ", hodnota, ...]: pred klicem jen mezery (aspon jedna), mezi klicem a hodnotou take
    if len(parts) < 5 or parts[0] == "" or parts[0].strip() != "" or parts[2] == "" or parts[2].strip() != "":
        return []
    end
    return [parts[1], parts[3]]
end

function parse_conf(content):
    vals = {}
    for line in content.split("\n"):
        kv = option_line(line)
        if len(kv) == 2:
            vals[kv[0]] = kv[1]
        end
    end
    return from_strings(vals.get("XkbLayout", ""), vals.get("XkbVariant", ""), vals.get("XkbOptions", ""), vals.get("XkbModel", ""))
end

# XKB* z /etc/vconsole.conf (systemd >= 255 je uklada i tam)
function parse_vconsole(content):
    vals = {}
    for line in content.split("\n"):
        item = line.strip()
        cut = item.find("=")
        if cut > 0 and item.startswith("XKB"):
            value = item[cut + 1:].strip()
            while value.startswith("\""):
                value = value[1:]
            end
            while value.endswith("\""):
                value = value[:len(value) - 1]
            end
            vals[item[:cut]] = value
        end
    end
    return from_strings(vals.get("XKBLAYOUT", ""), vals.get("XKBVARIANT", ""), vals.get("XKBOPTIONS", ""), vals.get("XKBMODEL", ""))
end

# Aktualni systemove nastaveni; bez souboru US bez prepinani
function read_system(conf, vconsole):
    if conf == "":
        conf = path_of("LUXOS_KEYBOARD_CONF", CONF)
    end
    if vconsole == "":
        vconsole = path_of("LUXOS_VCONSOLE_CONF", VCONSOLE)
    end
    cfg = parse_conf(lglib.read_text(conf))
    if len(cfg["layouts"]) > 0:
        return cfg
    end
    cfg = parse_vconsole(lglib.read_text(vconsole))
    if len(cfg["layouts"]) > 0:
        return cfg
    end
    return {"layouts": [["us", ""]], "model": "", "options": []}
end

# ---- kontrola a zapis --------------------------------------------------------------------------------------

function only_chars(value, allowed):
    for c in value:
        if allowed.find(c) < 0:
            return False
        end
    end
    return True
end

function valid_layout(code):
    return len(code) >= 1 and len(code) <= 32 and LOWER.find(code[0]) >= 0 and only_chars(code, LOWER + DIGITS + "_-")
end

function valid_variant(value):
    return len(value) <= 48 and only_chars(value, LOWER + UPPER + DIGITS + "_-")
end

function valid_option(value):
    cut = value.find(":")
    word = LOWER + UPPER + DIGITS + "_"
    return cut > 0 and cut < len(value) - 1 and only_chars(value[:cut], word) and only_chars(value[cut + 1:], word)
end

# Kontrola pred zapisem (hodnoty jdou do prikazove radky a konfigurace X): "" = v poradku, jinak chyba
function validate(layouts, options, model):
    if len(layouts) == 0:
        return "at least one layout is needed"
    end
    if len(layouts) > MAX_LAYOUTS:
        return "at most " + String(MAX_LAYOUTS) + " layouts are possible"
    end
    seen = []
    for key in layouts:
        name = key[0] + ":" + key[1]
        if name in seen:
            return "duplicate layout"
        end
        seen.append(name)
        if not valid_layout(key[0]) or not valid_variant(key[1]):
            return "invalid layout " + key[0] + " " + key[1]
        end
    end
    for o in options:
        if not valid_option(o):
            return "invalid option " + o
        end
    end
    if type(model) != "String" or not valid_variant(model):
        return "invalid model"
    end
    return ""
end

function xkb_strings(layouts):
    return [",".join([k[0] for k in layouts]), ",".join([k[1] for k in layouts])]
end

# Prepinani rozlozeni z XkbOptions (prvni grp:...), "" = zadne
function switch_of(options):
    for o in options:
        if o.startswith("grp:"):
            return o
        end
    end
    return ""
end

# XkbOptions s jinym prepinanim; ostatni volby (compose, ctrl...) zustanou
function with_switch(options, switch):
    rest = [o for o in options if not o.startswith("grp:")]
    if switch != "":
        return [switch] + rest
    end
    return rest
end

# 00-keyboard.conf stejne jako ho pise systemd-localed (volajici overi validate)
function conf_text(layouts, options, model):
    s = xkb_strings(layouts)
    lines = ["# Written by systemd-localed(8), read by systemd-localed and Xorg. It's",
             "# probably wise not to edit this file manually. Use localectl(1) to",
             "# update this file.",
             "Section \"InputClass\"",
             "        Identifier \"system-keyboard\"",
             "        MatchIsKeyboard \"on\"",
             "        Option \"XkbLayout\" \"" + s[0] + "\""]
    if model != "":
        lines.append("        Option \"XkbModel\" \"" + model + "\"")
    end
    if s[1].replace(",", "") != "":
        lines.append("        Option \"XkbVariant\" \"" + s[1] + "\"")
    end
    if len(options) > 0:
        lines.append("        Option \"XkbOptions\" \"" + ",".join(options) + "\"")
    end
    lines.append("EndSection")
    return "\n".join(lines) + "\n"
end

# Systemovy zapis pres systemd-localed (opravneni overi polkit, konzoli odvodi localed)
function localectl_cmd(layouts, options, model):
    s = xkb_strings(layouts)
    return ["localectl", "set-x11-keymap", s[0], model, s[1], ",".join(options)]
end

# Okamzite pouziti v bezici relaci ("-option ''" nejdriv smaze stare volby)
function setxkbmap_cmd(layouts, options):
    s = xkb_strings(layouts)
    argv = ["setxkbmap", "-layout", s[0], "-variant", s[1], "-option", ""]
    if len(options) > 0:
        argv = argv + ["-option", ",".join(options)]
    end
    return argv
end

# ---- prevod stareho vychoziho prepinani (luxos-desktop.install, post_upgrade) -----------------------------

# XkbOptions se starym vychozim prepinanim -> s novym (ostatni volby zustanou); jinak None
function migrate_options(value):
    opts = [o.strip() for o in value.split(",") if o.strip() != ""]
    if [o for o in opts if o.startswith("grp:")] != [OLD_DEFAULT_SWITCH]:
        return None
    end
    return ",".join([DEFAULT_SWITCH if o == OLD_DEFAULT_SWITCH else o for o in opts])
end

# Radek s volbami -> [zacatek, hodnota, konec] nebo []
function options_parts(line, vconsole):
    if vconsole:
        if not line.startswith("XKBOPTIONS="):
            return []
        end
        head = "XKBOPTIONS="
        rest = line[len(head):]
        if rest.startswith("\""):
            head = head + "\""
            rest = rest[1:]
        end
        tail = ""
        if rest.endswith("\""):
            tail = "\""
            rest = rest[:len(rest) - 1]
        end
        if rest.find("\"") >= 0:
            return []
        end
        return [head, rest, tail]
    end
    kv = option_line(line)
    if len(kv) != 2 or kv[0] != "XkbOptions":
        return []
    end
    cut = line.find("\"XkbOptions\"") + len("\"XkbOptions\"")
    start = line.find("\"", cut) + 1
    stop = line.find("\"", start)
    return [line[:start], line[start:stop], line[stop:]]
end

# Obsah 00-keyboard.conf (nebo vconsole.conf) s prevedenym prepinanim; None = beze zmeny
function migrate_text(content, vconsole):
    lines = content.split("\n")
    for i in range(len(lines)):
        parts = options_parts(lines[i], vconsole)
        if len(parts) == 3:
            new = migrate_options(parts[1])
            if new == None:
                return None
            end
            lines[i] = parts[0] + new + parts[2]
            return "\n".join(lines)
        end
    end
    return None
end

function file_mode(path):
    unsafe:
        buffer = __lsl_byte_zeros(256)
        if __lsl_qbe_call2(__lsl_symbol("stat"), lglib.cstr(path), lglib.data(buffer)) != 0:
            return -1
        end
        # struct stat x86_64: st_mode (u32) +24
        return __lsl_qbe_load32(lglib.data(buffer) + 24) & 4095
    end
end

function chmod(path, mode):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("chmod"), lglib.cstr(path), lglib.ptr(mode)) == 0
    end
end

function rewrite(path, vconsole):
    if not exists(path):
        return False
    end
    new = migrate_text(lglib.read_text(path), vconsole)
    if new == None:
        return False
    end
    tmp = path + ".luxos-new"
    call writefile(tmp, new)
    call chmod(tmp, file_mode(path))
    return lglib.rename(tmp, path)
end

# Jednou za zivot systemu: stare vychozi Alt+Shift -> obe klavesy Shift. Meni jen presne stare vychozi
# prepinani (jedina volba grp: = grp:alt_shift_toggle); vlastni volbu uzivatele nechava. Znacka zajisti,
# ze pozdeji vedome zvolene Alt+Shift uz dalsi aktualizace neprepise. Bez konfigurace (instalace jeste
# nezapsala rozlozeni) se nic nedeje a znacka se nevytvori. True = neco zmenila (plati od dalsiho startu X).
function migrate_default_switch(conf, vconsole, marker):
    if conf == "":
        conf = path_of("LUXOS_KEYBOARD_CONF", CONF)
    end
    if vconsole == "":
        vconsole = path_of("LUXOS_VCONSOLE_CONF", VCONSOLE)
    end
    if marker == "":
        marker = path_of("LUXOS_KEYBOARD_MIGRATED", MIGRATED)
    end
    if exists(marker) or not exists(conf):
        return False
    end
    changed = rewrite(conf, False)
    if changed:
        # localed drzi kopii XKB* i tam
        call rewrite(vconsole, True)
    end
    cut = text.rfind(marker, "/")
    if cut > 0:
        call lglib.mkdir_p(marker[:cut])
    end
    call writefile(marker, "grp:shifts_toggle\n" if changed else "unchanged\n")
    return changed
end

# ---- katalog rozlozeni ----------------------------------------------------------------------------------------

# [[rozlozeni, varianta], popis] z evdev.lst: bezna nahore (nazvy z COMMON bez prekladu), ostatni podle abecedy
function catalog(path):
    if path == "":
        path = path_of("LUXOS_XKB_RULES", RULES)
    end
    out = []
    seen = set()
    for item in COMMON:
        out.append([[item[1], item[2]], item[0]])
        seen.add(item[1] + ":" + item[2])
    end
    rest = {}
    section = ""
    for line in lglib.read_text(path).split("\n"):
        if line.startswith("!"):
            section = line[1:].strip()
            continue
        end
        if not (line.startswith(" ") or line.startswith("\t")):
            continue
        end
        entry = line.strip().replace("\t", " ")
        cut = entry.find(" ")
        if cut <= 0:
            continue
        end
        name = entry[:cut]
        desc = entry[cut:].strip()
        key = []
        if section == "layout":
            key = [name, ""]
        elif section == "variant" and desc.find(":") >= 0:
            key = [desc[:desc.find(":")].strip(), name]
            desc = desc[desc.find(":") + 1:].strip()
        else:
            continue
        end
        if not ((key[0] + ":" + key[1]) in seen):
            seen.add(key[0] + ":" + key[1])
            # stabilni razeni podle popisu: poradi v souboru jako druhy klic
            rest[desc.lower() + "\t" + pad6(len(rest))] = [key, desc]
        end
    end
    for name in sorted(rest.keys()):
        out.append(rest[name])
    end
    return out
end

function pad6(n):
    digits = String(n)
    while len(digits) < 6:
        digits = "0" + digits
    end
    return digits
end

# Citelny nazev rozlozeni (bezna maji preklad, tr = funkce prekladu)
function describe(key, items, tr):
    for item in COMMON:
        if item[1] == key[0] and item[2] == key[1]:
            return tr(item[0])
        end
    end
    for item in items:
        if item[0][0] == key[0] and item[0][1] == key[1]:
            return item[1]
        end
    end
    if key[1] != "":
        return key[0] + " (" + key[1] + ")"
    end
    return key[0]
end

# Kratky stitek jako vlajka v horni liste: CZ, CZ qwerty
function short(key):
    if key[1] != "":
        return key[0].upper() + " " + key[1]
    end
    return key[0].upper()
end
