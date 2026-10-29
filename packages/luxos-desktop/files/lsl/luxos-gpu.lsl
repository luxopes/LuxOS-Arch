# LuxOS - grafika podle rezimu napajeni: v rezimu Vykon bezi hry a narocne aplikace na samostatne grafice
# (NVIDIA pres PRIME render offload, AMD/Intel/nouveau pres DRI_PRIME), jinak na integrovane (baterie).
# Jediny zdroj pravdy je aktivni profil power-profiles-daemon (ActiveProfile); nic se nezapina rucne.
#
#   luxos-gpu run PROGRAM [ARG...]   spusti program; v rezimu Vykon na samostatne grafice (promenne prostredi)
#                                    - prepsane .desktop her a aplikaci s PrefersNonDefaultGPU=true
#   luxos-gpu apply                  srovna stav s aktualnim profilem (luxos-hub po prihlaseni a pri kazde zmene):
#                                    - Flatpak: promenne pro samostatnou grafiku v uzivatelskych prepisech
#                                      (~/.local/share/flatpak/overrides/<aplikace>, skupina [Environment]) pro
#                                      spoustece her a nainstalovane hry; jen chybejici klice, vlastni klice
#                                      uzivatele se nemeni; co LuxOS pridal, je v ~/.local/state/luxos/gpu-flatpak
#                                    - NVIDIA: PowerMizer "nejvyssi vykon" (nvidia-settings), puvodni hodnota
#                                      v $XDG_RUNTIME_DIR/luxos/gpu-powermizer
#                                    - samostatna AMD: luxos-gpu-performance.service (root, polkit bez hesla)
#   luxos-gpu status                 gpu=nvidia|dri|none, name=, profile=, offload=yes|no (Baterie a napajeni)
#   luxos-gpu env                    promenne, ktere by "run" ted nastavil
#   luxos-gpu desktop-sync VYSTUP [ZDROJ]   (root, luxos-apps-sync) .desktop her a PrefersNonDefaultGPU=true
#                                    ze ZDROJE (/usr/share/applications) do VYSTUPU s Exec=luxos-gpu run ...;
#                                    vypise jejich desktop-id, odkazy na Flathub ve VYSTUPU nemeni
#   luxos-gpu system on|off          (root, luxos-gpu-performance.service) samostatna AMD na "high" / zpet
#
# Testy: LUXOS_SYSROOT (falesny koren /sys, /run, /var/lib/flatpak), LUXOS_PCI_IDS, DBUS_SYSTEM_BUS_ADDRESS.
load env, os
load gio
load luxos_sys
load luxos_text as text
load luxos_i18n as i18n

PPD = [["org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles"], ["net.hadess.PowerProfiles", "/net/hadess/PowerProfiles"]]
# Jako prime-run (nvidia-prime): OpenGL (GLVND), Vulkan (vrstva NV_optimus) a EGL/GLX offload
NVIDIA_ENV = [["__NV_PRIME_RENDER_OFFLOAD", "1"], ["__GLX_VENDOR_LIBRARY_NAME", "nvidia"], ["__VK_LAYER_NV_optimus", "NVIDIA_only"]]
# Mesa (OpenGL i Vulkan pres vrstvu device-select): druha grafika
DRI_ENV = [["DRI_PRIME", "1"]]
# Spoustece her a narocne aplikace z Flathubu (prepis plati i pro pozdeji nainstalovane); hry s Categories=Game
# nebo PrefersNonDefaultGPU=true se najdou v exportech Flatpaku
FLATPAK_APPS = ["com.valvesoftware.Steam", "com.heroicgameslauncher.hgl", "net.lutris.Lutris", "com.usebottles.bottles", "org.prismlauncher.PrismLauncher", "com.atlauncher.ATLauncher", "io.itch.itch", "org.libretro.RetroArch", "net.retrodeck.retrodeck", "org.vinegarhq.Sober", "net.pcsx2.PCSX2", "net.rpcs3.RPCS3", "info.cemu.Cemu", "org.DolphinEmu.dolphin-emu", "org.blender.Blender"]
DRI_DRIVERS = ["amdgpu", "radeon", "nouveau", "i915", "xe"]
UNIT = "luxos-gpu-performance.service"
WRAP = "luxos-gpu run "
MARK = "X-LuxOS-GPU=true"

# ---- pomocne ---------------------------------------------------------------------------------------------

# ${VAR:-default}
function envd(name, fallback):
    value = env.get(name, "")
    if value == None or value == "":
        return fallback
    end
    return value
end

function root():
    return envd("LUXOS_SYSROOT", "")
end

function home():
    return envd("HOME", "/")
end

function data_home():
    return envd("XDG_DATA_HOME", home() + "/.local/share")
end

function state_dir():
    return envd("XDG_STATE_HOME", home() + "/.local/state") + "/luxos"
end

function runtime_dir():
    return envd("XDG_RUNTIME_DIR", "/tmp") + "/luxos"
end

function read_text(path):
    value = ""
    safe:
        value = readfile(path)
    end
    if value == None:
        return ""
    end
    return value
end

function read_line(path):
    value = read_text(path)
    cut = value.find("\n")
    if cut >= 0:
        value = value[0:cut]
    end
    return value.strip()
end

# Atomicky zapis (docasny soubor + prejmenovani); False pri chybe
function write_atomic(path, value):
    tmp = path + ".tmp"
    ok = False
    safe:
        call writefile(tmp, value)
        ok = luxos_sys.rename(tmp, path)
    end
    if not ok:
        call luxos_sys.unlink(tmp)
    end
    return ok
end

function dirname(path):
    return path[0:text.rfind(path, "/")]
end

# Program bez vystupu na terminal; kod ukonceni (-1 kdyz nejde spustit)
function quiet(argv):
    status = -1
    safe:
        result = os.capture_result(argv)
        status = result["status"]
    end
    return status
end

function quiet_output(argv):
    out = None
    safe:
        result = os.capture_result(argv)
        if result["status"] == 0:
            out = result["stdout"].strip()
        end
    end
    return out
end

# ---- profil napajeni (power-profiles-daemon na systemove sbernici) --------------------------------------

function profile():
    bus = 0
    try:
        bus = gio.system_bus()
    else:
        return ""
    end
    for pair in PPD:
        value = None
        try:
            value = gio.call_values(bus, pair[0], pair[1], "org.freedesktop.DBus.Properties", "Get", [pair[0], "ActiveProfile"], "(ss)", 3000)[0]
        else:
            value = None
        end
        if type(value) == "String":
            return value
        end
    end
    return ""
end

# ---- grafika (sysfs; cteni uevent/boot_vga samostatnou grafiku neprobouzi) ---------------------------

function uevent(path):
    out = {}
    for line in read_text(path).split("\n"):
        cut = line.find("=")
        if cut > 0:
            out[line[0:cut]] = line[cut + 1:]
        end
    end
    return out
end

function gpus():
    base = root() + "/sys/class/drm"
    out = []
    seen = {}
    for name in luxos_sys.list_dir(base):
        if not name.startswith("card") or name.find("-") >= 0:
            continue
        end
        dev = base + "/" + name + "/device"
        info = uevent(dev + "/uevent")
        pci = info.get("PCI_ID", "")
        slot = info.get("PCI_SLOT_NAME", "")
        if pci == "" or pci.find(":") < 0 or slot in seen:
            continue
        end
        seen[slot] = True
        parts = pci.lower().split(":")
        out.append({"card": name, "dev": dev, "slot": slot, "vendor": parts[0], "device": parts[1], "driver": info.get("DRIVER", ""), "boot": read_line(dev + "/boot_vga") == "1"})
    end
    return out
end

# Samostatna grafika vedle grafiky, ktera kresli obrazovku (boot_vga); None = neni (jedna grafika,
# samostatna bez ovladace, NVIDIA jako jedina grafika)
function discrete():
    found = gpus()
    display = False
    for g in found:
        if g["boot"]:
            display = True
        end
    end
    if not display or len(found) < 2:
        return None
    end
    for g in found:
        if g["boot"]:
            continue
        end
        if g["vendor"] == "10de" and g["driver"] == "nvidia":
            g["kind"] = "nvidia"
            return g
        end
        if g["driver"] in DRI_DRIVERS:
            g["kind"] = "dri"
            return g
        end
    end
    return None
end

function gpu_env(g):
    if g == None:
        return []
    end
    if g["kind"] == "nvidia":
        return NVIDIA_ENV
    end
    return DRI_ENV
end

# Nazev zarizeni z pci.ids ("" kdyz neni): "TU117M [GeForce GTX 1650 Mobile / Max-Q]"
function pci_name(vendor_id, device_id):
    ids = read_text(envd("LUXOS_PCI_IDS", "/usr/share/hwdata/pci.ids"))
    start = ids.find("\n" + vendor_id + "  ")
    if start < 0:
        return ""
    end
    # jen blok tohoto vyrobce: konci prvnim dalsim radkem vyrobce (zacina hex cislici)
    block = ids[start + 1:]
    stop = len(block)
    for digit in ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "a", "b", "c", "d", "e", "f"]:
        k = block.find("\n" + digit)
        if k >= 0 and k < stop:
            stop = k
        end
    end
    block = block[0:stop] + "\n"
    at = block.find("\n\t" + device_id + "  ")
    if at < 0:
        return ""
    end
    line = block[at + 2 + len(device_id):]
    return line[0:line.find("\n")].strip()
end

# Citelny nazev: "NVIDIA GeForce GTX 1650 Mobile / Max-Q"; pci.ids (~1,7 MB) jen poprve, pak z mezipameti
function gpu_name(g):
    vendor = {"10de": "NVIDIA", "1002": "AMD", "8086": "Intel"}.get(g["vendor"], "")
    key = g["vendor"] + ":" + g["device"]
    cache = envd("XDG_CACHE_HOME", home() + "/.cache") + "/luxos/gpu-name"
    cached = read_line(cache).split("\t")
    name = ""
    if len(cached) == 2 and cached[0] == key:
        name = cached[1]
    else:
        name = pci_name(g["vendor"], g["device"])
        lb = name.find("[")
        rb = text.rfind(name, "]")
        if lb >= 0 and rb > lb:
            name = name[lb + 1:rb]
        end
        if name != "":
            safe:
                call luxos_sys.mkdir_p(dirname(cache))
                call write_atomic(cache, key + "\t" + name + "\n")
            end
        end
    end
    if name == "":
        if vendor == "":
            return i18n.T("discrete graphics")
        end
        return vendor
    end
    if vendor != "" and not name.startswith(vendor):
        name = vendor + " " + name
    end
    return name
end

# ---- Flatpak: uzivatelske prepisy (GKeyFile) -----------------------------------------------------------

# [zacatek, konec) radku skupiny bez hlavicky; [-1, -1] kdyz neni
function group_span(lines, group):
    start = -1
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("["):
            if start >= 0:
                return [start, i]
            end
            if line == "[" + group + "]":
                start = i + 1
            end
        end
        i += 1
    end
    if start >= 0:
        return [start, len(lines)]
    end
    return [-1, -1]
end

function key_index(lines, span, key):
    i = span[0]
    while i >= 0 and i < span[1]:
        line = lines[i]
        cut = line.find("=")
        if cut > 0 and line[0:cut].strip() == key:
            return i
        end
        i += 1
    end
    return -1
end

function key_get(content, group, key):
    lines = content.split("\n")
    span = group_span(lines, group)
    at = key_index(lines, span, key)
    if at < 0:
        return None
    end
    return lines[at][lines[at].find("=") + 1:].strip()
end

function key_set(content, group, key, value):
    lines = content.split("\n")
    if len(lines) > 0 and lines[len(lines) - 1] == "":
        lines = lines[0:len(lines) - 1]
    end
    span = group_span(lines, group)
    if span[0] < 0:
        if len(lines) > 0 and lines[len(lines) - 1].strip() != "":
            lines.append("")
        end
        lines.append("[" + group + "]")
        lines.append(key + "=" + value)
    else:
        at = key_index(lines, span, key)
        if at >= 0:
            lines[at] = key + "=" + value
        else:
            # za posledni neprazdny radek skupiny
            pos = span[1]
            while pos > span[0] and lines[pos - 1].strip() == "":
                pos -= 1
            end
            lines.insert(pos, key + "=" + value)
        end
    end
    return "\n".join(lines) + "\n"
end

# Odebere klic; prazdnou skupinu (jen prazdne radky) odebere cele
function key_remove(content, group, key):
    lines = content.split("\n")
    span = group_span(lines, group)
    at = key_index(lines, span, key)
    if at < 0:
        return content
    end
    call lines.pop(at)
    span = group_span(lines, group)
    empty = True
    i = span[0]
    while i < span[1]:
        if lines[i].strip() != "":
            empty = False
        end
        i += 1
    end
    if empty:
        out = []
        i = 0
        while i < len(lines):
            if i < span[0] - 1 or i >= span[1]:
                out.append(lines[i])
            end
            i += 1
        end
        lines = out
    end
    while len(lines) > 0 and lines[len(lines) - 1].strip() == "":
        lines = lines[0:len(lines) - 1]
    end
    if len(lines) == 0:
        return ""
    end
    return "\n".join(lines) + "\n"
end

function flatpak_system():
    return root() + "/var/lib/flatpak"
end

function flatpak_present():
    return os.which("flatpak") != None or exists(flatpak_system())
end

# [Desktop Entry] jako slovnik (bez lokalizovanych klicu)
function desktop_entry(content):
    lines = content.split("\n")
    span = group_span(lines, "Desktop Entry")
    out = {}
    i = span[0]
    while i >= 0 and i < span[1]:
        line = lines[i]
        cut = line.find("=")
        if cut > 0:
            key = line[0:cut].strip()
            if key.find("[") < 0 and key not in out:
                out[key] = line[cut + 1:].strip()
            end
        end
        i += 1
    end
    return out
end

# Hra nebo aplikace, ktera sama chce vykonnou grafiku
function wants_gpu(entry):
    if entry.get("PrefersNonDefaultGPU", "") == "true":
        return True
    end
    for c in entry.get("Categories", "").split(";"):
        if c.strip() == "Game":
            return True
        end
    end
    return False
end

# {aplikace: nazev} her z exportu Flatpaku (systemove i uzivatelske)
function flatpak_games():
    out = {}
    for base in [flatpak_system() + "/exports/share/applications", data_home() + "/flatpak/exports/share/applications"]:
        for name in luxos_sys.list_dir(base):
            if not name.endswith(".desktop"):
                continue
            end
            entry = desktop_entry(read_text(base + "/" + name))
            app = entry.get("X-Flatpak", "")
            if app != "" and wants_gpu(entry):
                out[app] = entry.get("Name", app)
            end
        end
    end
    return out
end

function app_label(app, games):
    if app in games:
        return games[app]
    end
    return app[text.rfind(app, ".") + 1:]
end

function records_path():
    return state_dir() + "/gpu-flatpak"
end

# [[aplikace, klic, hodnota]] - co do prepisu pridal LuxOS
function read_records():
    out = []
    for line in read_text(records_path()).split("\n"):
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] != "" and parts[1] != "":
            out.append(parts)
        end
    end
    return out
end

function write_records(records):
    path = records_path()
    if len(records) == 0:
        if exists(path):
            call luxos_sys.unlink(path)
        end
        return True
    end
    call luxos_sys.mkdir_p(dirname(path))
    lines = []
    for r in records:
        lines.append(r[0] + "\t" + r[1] + "\t" + r[2])
    end
    return write_atomic(path, "\n".join(lines) + "\n")
end

function same(a, b):
    return a[0] == b[0] and a[1] == b[1] and a[2] == b[2]
end

function contains(records, r):
    for x in records:
        if same(x, r):
            return True
        end
    end
    return False
end

function save_override(path, content):
    if content.strip() == "":
        if exists(path):
            call luxos_sys.unlink(path)
        end
        return True
    end
    call luxos_sys.mkdir_p(dirname(path))
    return write_atomic(path, content)
end

# Srovna prepisy s pozadovanym stavem [[aplikace, klic, hodnota]]; vraci {aplikace: True} zmenenych
function flatpak_reconcile(desired):
    dir = data_home() + "/flatpak/overrides"
    owned = read_records()
    keep = []
    changed = {}
    # pryc, co uz neplati (jen kdyz tam je porad nase hodnota - zmenu uzivatele nechat)
    for r in owned:
        if contains(desired, r):
            keep.append(r)
            continue
        end
        path = dir + "/" + r[0]
        content = read_text(path)
        if key_get(content, "Environment", r[1]) == r[2]:
            if save_override(path, key_remove(content, "Environment", r[1])):
                changed[r[0]] = True
            else:
                keep.append(r)
            end
        end
    end
    owned = keep
    keep = []
    for d in desired:
        path = dir + "/" + d[0]
        content = read_text(path)
        current = key_get(content, "Environment", d[1])
        if current == None:
            if save_override(path, key_set(content, "Environment", d[1], d[2])):
                keep.append(d)
                changed[d[0]] = True
            end
        elif current == d[2]:
            if contains(owned, d):
                keep.append(d)
            end
        end
        # jina hodnota = nastaveni uzivatele, nemenit a nevlastnit
    end
    call write_records(keep)
    return changed
end

# Bezici aplikace Flatpaku ($XDG_RUNTIME_DIR/.flatpak/<instance>/info, [Application] name=)
function running_flatpaks():
    out = {}
    base = envd("XDG_RUNTIME_DIR", "/tmp") + "/.flatpak"
    for inst in luxos_sys.list_dir(base):
        content = read_text(base + "/" + inst + "/info")
        lines = content.split("\n")
        span = group_span(lines, "Application")
        at = key_index(lines, span, "name")
        if at >= 0:
            out[lines[at][lines[at].find("=") + 1:].strip()] = True
        end
    end
    return out
end

function notify(title, body, icon):
    if os.which("notify-send") == None:
        return 0
    end
    return quiet(["notify-send", "-a", "LuxOS", "-i", icon, title, body])
end

# ---- NVIDIA PowerMizer (nvidia-settings, jen v bezici relaci X) -----------------------------------------

function nvidia_settings(args):
    if os.which("nvidia-settings") == None or envd("DISPLAY", "") == "":
        return None
    end
    argv = ["timeout", "5", "nvidia-settings", "--no-write-config"]
    argv.extend(args)
    return quiet_output(argv)
end

function powermizer(perf, g):
    record = runtime_dir() + "/gpu-powermizer"
    if perf and g != None and g["kind"] == "nvidia":
        if exists(record):
            return 0
        end
        current = nvidia_settings(["-t", "-q", "[gpu:0]/GpuPowerMizerMode"])
        if current == None or current == "" or not text.is_digits(current):
            return 0
        end
        if current != "1" and nvidia_settings(["-a", "[gpu:0]/GpuPowerMizerMode=1"]) != None:
            call luxos_sys.mkdir_p(runtime_dir())
            call write_atomic(record, current + "\n")
        end
        return 0
    end
    if exists(record):
        previous = read_line(record)
        if text.is_digits(previous):
            call nvidia_settings(["-a", "[gpu:0]/GpuPowerMizerMode=" + previous])
        end
        call luxos_sys.unlink(record)
    end
    return 0
end

# ---- samostatna AMD: systemova cast (root) ---------------------------------------------------------------

function system_part(perf, g):
    want = perf and g != None and g["vendor"] == "1002"
    active = exists(root() + "/run/luxos/gpu-performance")
    if want and not active:
        call quiet(["systemctl", "--no-ask-password", "--no-block", "start", UNIT])
    elif active and not want:
        call quiet(["systemctl", "--no-ask-password", "--no-block", "stop", UNIT])
    end
    return 0
end

function system_cmd(action):
    dir = root() + "/run/luxos"
    saved = dir + "/gpu-performance.saved"
    mark = dir + "/gpu-performance"
    if action == "on":
        call luxos_sys.mkdir_p(dir)
        g = discrete()
        if g != None and g["vendor"] == "1002":
            f = g["dev"] + "/power_dpm_force_performance_level"
            current = read_line(f)
            if current != "" and current != "high":
                ok = False
                safe:
                    call writefile(f, "high\n")
                    ok = True
                end
                if ok and not exists(saved):
                    call writefile(saved, f + "\t" + current + "\n")
                end
            end
        end
        call writefile(mark, "")
        return 0
    end
    if action == "off":
        for line in read_text(saved).split("\n"):
            parts = line.split("\t")
            if len(parts) == 2 and exists(parts[0]):
                safe:
                    call writefile(parts[0], parts[1] + "\n")
                end
            end
        end
        for f in [saved, mark]:
            if exists(f):
                call luxos_sys.unlink(f)
            end
        end
        return 0
    end
    call luxos_sys.eprint(i18n.T("Usage:") + " luxos-gpu system on|off")
    return 2
end

# ---- apply ------------------------------------------------------------------------------------------------

function apply():
    perf = profile() == "performance"
    g = discrete()
    desired = []
    games = {}
    if flatpak_present():
        games = flatpak_games()
        if perf and g != None:
            apps = []
            for app in FLATPAK_APPS:
                apps.append(app)
            end
            for app in sorted(games.keys()):
                if app not in apps:
                    apps.append(app)
                end
            end
            for app in apps:
                for kv in gpu_env(g):
                    desired.append([app, kv[0], kv[1]])
                end
            end
        end
    end
    changed = flatpak_reconcile(desired)
    # Bezici spoustec (Steam) si prostredi nacetl pri startu: rict, ze ho je treba spustit znovu
    running = running_flatpaks()
    for app in sorted(changed.keys()):
        if app in running:
            label = app_label(app, games)
            if perf and g != None:
                call notify(i18n.T("Graphics for games"), i18n.TF("Restart %s to run its games on %s.", [label, gpu_name(g)]), app)
            else:
                call notify(i18n.T("Graphics for games"), i18n.TF("Restart %s so its games use the integrated graphics again and save battery.", [label]), app)
            end
        end
    end
    call powermizer(perf, g)
    call system_part(perf, g)
    return 0
end

# ---- .desktop: Exec pres luxos-gpu run (root, z luxos-apps-sync) ------------------------------------------

function wrap_desktop(content):
    lines = content.split("\n")
    out = []
    marked = False
    for line in lines:
        if line.startswith("Exec=") and not line[5:].startswith(WRAP):
            line = "Exec=" + WRAP + line[5:]
        end
        if line.strip() == MARK:
            marked = True
        end
        out.append(line)
    end
    if not marked:
        i = 0
        while i < len(out):
            if out[i].strip() == "[Desktop Entry]":
                out.insert(i + 1, MARK)
                break
            end
            i += 1
        end
    end
    return "\n".join(out)
end

# Vypise desktop-id zpracovanych polozek (luxos-apps-sync je necha pri uklidu); zapisuje jen pri zmene.
function desktop_sync(outdir, srcdir):
    if not luxos_sys.mkdir_p(outdir):
        return 1
    end
    for name in luxos_sys.list_dir(srcdir):
        if not name.endswith(".desktop"):
            continue
        end
        target = outdir + "/" + name
        source = read_text(srcdir + "/" + name)
        if source == "":
            continue
        end
        current = read_text(target)
        base = source
        if current != "":
            here = desktop_entry(current)
            if here.get("X-Flatpak", "") != "":
                continue                # odkaz na aplikaci z Flathubu (ta ma prepis Flatpaku), nemenit
            end
            # cerstvy prepis nazvu z luxos-apps-sync (bez znacky) zachovat; vlastni starsi vystup ne
            if current.find("\n" + MARK) < 0:
                base = current
            end
        end
        entry = desktop_entry(base)
        if not wants_gpu(entry) or entry.get("Exec", "") == "" or entry.get("DBusActivatable", "") == "true" or entry.get("Hidden", "") == "true":
            continue
        end
        if entry.get("Type", "Application") != "Application":
            continue
        end
        wrapped = wrap_desktop(base)
        if wrapped == current or write_atomic(target, wrapped):
            print name[0:len(name) - 8]
        end
    end
    return 0
end

# ---- hlavni program -------------------------------------------------------------------------------------

function usage():
    return i18n.T("Usage:") + " luxos-gpu run PROGRAM [ARG...] | apply | status | env"
end

function run_cmd():
    if arg_count() < 3:
        call luxos_sys.eprint(usage())
        return 2
    end
    argv = []
    i = 2
    while i < arg_count():
        argv.append(arg(i))
        i += 1
    end
    if profile() == "performance":
        for kv in gpu_env(discrete()):
            # promennou nastavenou uzivatelem (DRI_PRIME=0 ...) nechat
            if not env.has(kv[0]):
                call luxos_sys.setenv(kv[0], kv[1])
            end
        end
    end
    call luxos_sys.exec(argv)
    call luxos_sys.eprint("luxos-gpu: " + argv[0] + ": " + i18n.T("cannot be started"))
    return 127
end

function status_cmd():
    g = discrete()
    p = profile()
    kind = "none"
    name = ""
    if g != None:
        kind = g["kind"]
        name = gpu_name(g)
    end
    offload = "no"
    if p == "performance" and g != None:
        offload = "yes"
    end
    print "gpu=" + kind
    print "name=" + name
    print "profile=" + p
    print "offload=" + offload
    return 0
end

function env_cmd():
    if profile() == "performance":
        for kv in gpu_env(discrete()):
            print kv[0] + "=" + kv[1]
        end
    end
    return 0
end

command = ""
if arg_count() > 1:
    command = arg(1)
end
if command == "run":
    call exit(run_cmd())
elif command == "apply":
    call exit(apply())
elif command == "status":
    call exit(status_cmd())
elif command == "env":
    call exit(env_cmd())
elif command == "desktop-sync" and arg_count() > 2:
    src = "/usr/share/applications"
    if arg_count() > 3:
        src = arg(3)
    end
    call exit(desktop_sync(arg(2), src))
elif command == "system" and arg_count() > 2:
    call exit(system_cmd(arg(2)))
elif command == "-h" or command == "--help":
    print usage()
    call exit(0)
end
call luxos_sys.eprint(usage())
call exit(2)
