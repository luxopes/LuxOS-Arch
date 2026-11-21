# LuxOS - Baterie a napajeni bez GTK: stav baterie z vlastnosti UPower, historie pro grafy a ukazkova data.
# Oddelene od luxos-power.lsl, aby slo testovat bez displeje a sbernice (tests/lsl/luxos-power-model-test.lsl).
#
#   status_text(info), fmt_duration(sekundy)      "Nabiji se · plne za 1 h 5 min"
#   combine(first, display, each)                 vic baterii: stav, procenta a casy z DisplayDevice, kapacity soucet
#   clean_history(raw, kind, info, now, gap, span) zaznamy upower [[cas, hodnota, stav]] -> body grafu (None = preruseni)
#   clip_history(body, start)
#   charge_cycles(info, folder)                   pocet cyklu z UPower, jinak z jadra (cycle_count); 0 = neudava
#   demo_info(full), demo_history(kind, now)      LUXOS_POWER_DEMO
load math
load luxos_glib, glib as glib
load luxos_i18n as i18n
load luxos_text as text

STATE_UNKNOWN = 0
STATE_CHARGING = 1
STATE_DISCHARGING = 2
STATE_EMPTY = 3
STATE_FULL = 4
STATE_PENDING_CHARGE = 5
STATE_PENDING_DISCHARGE = 6
ON_BATTERY = [2, 3, 6]
# zaznamu upower za tyden jsou stovky; points musi byt vetsi nez jejich pocet (jinak prevzorkuje pres mezery,
# 0 = nic), upower zapisuje jen zmeny - pri nabijecce na 100 % treba dva dny nic: bere se tyden a orizne
HISTORY_LOOKBACK = 604800
HISTORY_POINTS = 100000

function fmt_duration(seconds):
    if seconds <= 0:
        return ""
    end
    m = Int(seconds) // 60
    if m < 60:
        return i18n.TF("%d min", [m])
    end
    return i18n.TF("%d h %d min", [m // 60, m % 60])
end

function status_text(info):
    st = info.get("State", 0)
    if st == STATE_CHARGING:
        left = fmt_duration(info.get("TimeToFull", 0))
        if left != "":
            return i18n.T("Charging") + " · " + i18n.TF("full in %s", [left])
        end
        return i18n.T("Charging")
    end
    if st in ON_BATTERY:
        left = fmt_duration(info.get("TimeToEmpty", 0))
        if left != "":
            return i18n.T("On battery") + " · " + i18n.TF("about %s left", [left])
        end
        return i18n.T("On battery")
    end
    if st == STATE_FULL:
        return i18n.T("Fully charged")
    end
    return i18n.T("Plugged in, not charging")
end

# Notebooky s vnitrni a vymennou baterii: stav, procenta a casy za vsechny, zdravi ze souctu kapacit
function combine(first, display, each):
    info = {}
    for key in first.keys():
        info[key] = first[key]
    end
    for key in ["Percentage", "State", "TimeToEmpty", "TimeToFull", "EnergyRate"]:
        if key in display:
            info[key] = display[key]
        end
    end
    full = 0.0
    design = 0.0
    for b in each:
        full = full + Float(b.get("EnergyFull", 0.0))
        design = design + Float(b.get("EnergyFullDesign", 0.0))
    end
    info["EnergyFull"] = full
    info["EnergyFullDesign"] = design
    if "Capacity" in info:
        call info.pop("Capacity")
    end
    return info
end

function charge_cycles(info, folder):
    n = Int(info.get("ChargeCycles", -1))
    if n > 0:
        return n
    end
    for name in glib.list_dir(folder):
        if name.startswith("BAT"):
            value = glib.read_text(folder + "/" + name + "/cycle_count").strip()
            if text.is_digits(value) and Int(value) > 0:
                return Int(value)
            end
        end
    end
    return 0
end

# upower pri kazdem startu zapise 0 se stavem "unknown" (neni to vybiti) a zapisuje jen zmeny: hodnota plati
# az do dalsiho zaznamu (schody), posledni do ted. None = preruseni cary (vypnuty pocitac: zaznam "unknown"
# nebo mezera bez zmeny u vybijeni - vybijeni se meni porad)
function clean_history(raw, kind, info, now, gap, span):
    out = []
    last = None
    for rec in by_time(raw):
        t = rec[0]
        v = Float(rec[1])
        st = rec[2]
        if st == STATE_UNKNOWN:
            if len(out) > 0 and out[len(out) - 1] != None:
                out.append(None)
            end
            last = None
            continue
        end
        if last != None:
            if last[2] == STATE_DISCHARGING and t - last[0] > gap:
                out.append(None)
            else:
                out.append([t, last[1], last[2]])
            end
        end
        out.append([t, v, st])
        last = [t, v, st]
    end
    if last != None:
        key = "EnergyRate"
        if kind == "charge":
            key = "Percentage"
        end
        state = info.get("State", last[2])
        out.append([now, last[1], last[2]])
        if key in info and state != STATE_UNKNOWN:
            out.append([now, Float(info[key]), state])
        end
    end
    while len(out) > 0 and out[len(out) - 1] == None:
        call out.pop()
    end
    if span > 0:
        out = clip_history(out, now - span)
    end
    return out
end

# Poradi zaznamu (cas, hodnota, stav) jako razeni n-tic; upower je vraci skoro serazene
function before(a, b):
    if a[0] != b[0]:
        return a[0] < b[0]
    end
    if a[1] != b[1]:
        return a[1] < b[1]
    end
    return a[2] < b[2]
end

function by_time(raw):
    out = []
    for rec in raw:
        i = len(out)
        out.append(rec)
        while i > 0 and before(rec, out[i - 1]):
            out[i] = out[i - 1]
            i -= 1
        end
        out[i] = rec
    end
    return out
end

# Jen body od start; hodnota platna na zacatku okna (posledni starsi zaznam) zacina na start
function clip_history(points, start):
    out = []
    before = None
    for p in points:
        if p == None:
            if len(out) > 0:
                out.append(None)
            else:
                before = None
            end
            continue
        end
        if p[0] < start:
            before = p
            continue
        end
        if before != None and len(out) == 0:
            out.append([start, before[1], before[2]])
        end
        out.append(p)
    end
    while len(out) > 0 and out[0] == None:
        call out.pop(0)
    end
    return out
end

function demo_info(full):
    if full:
        return {"Percentage": 100.0, "State": STATE_FULL, "TimeToEmpty": 0, "TimeToFull": 0, "EnergyRate": 0.0,
                "Energy": 52.4, "EnergyFull": 52.4, "EnergyFullDesign": 57.0, "ChargeCycles": 0,
                "Model": "Demo battery", "Vendor": "LuxOS"}
    end
    return {"Percentage": 64.0, "State": STATE_DISCHARGING, "TimeToEmpty": 4 * 3600 + 25 * 60, "TimeToFull": 0,
            "EnergyRate": 7.8, "Energy": 33.6, "EnergyFull": 52.4, "EnergyFullDesign": 57.0, "ChargeCycles": 212,
            "Model": "Demo battery", "Vendor": "LuxOS"}
end

function demo_history(kind, now):
    out = []
    level = 92.0
    for i in range(240):
        t = now - 86400 + i * 360
        hour = (i * 6) // 60
        charging = (hour >= 7 and hour < 9) or (hour >= 17 and hour < 18)
        if charging:
            level = min(100.0, level + 4.5)
        else:
            level = max(5.0, level - 0.9 - 0.4 * math.sin(Float(i) / 7.0))
        end
        if kind == "charge":
            state = STATE_DISCHARGING
            if charging:
                state = STATE_CHARGING
            end
            out.append([t, level, state])
        elif charging:
            out.append([t, 14.0, 0])
        else:
            out.append([t, 6.5 + 3.0 * abs(math.sin(Float(i) / 9.0)), 0])
        end
    end
    return out
end

# Desetinne cislo na jedno misto ("7.8"); desetinny oddelovac podle jazyka dosadi i18n.decimal
function fixed1(value):
    n = math.round_half_even_int(Float(value) * 10.0)
    return String(n // 10) + "." + String(n % 10)
end

function fixed0(value):
    return String(math.round_half_even_int(Float(value)))
end
