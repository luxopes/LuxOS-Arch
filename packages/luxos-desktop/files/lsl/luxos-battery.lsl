# LuxOS - baterie v horni liste (plugin genmon): ikona + procenta, klik = Ovladaci centrum
# Spousti se kazdych 20 s; v LSL bez dalsich procesu (bash potreboval awk na kazdy preklad).
# LUXOS_POWER_SUPPLY prepise /sys/class/power_supply (testy).
load env, os, fd
load luxos_sys
load luxos_i18n as i18n

# ${VAR:-default}: prazdna promenna plati jako nenastavena
function envd(name, fallback):
    value = env.get(name, "")
    if value == "":
        return fallback
    end
    return value
end

# Prvni radek souboru bez koncoveho odradkovani, None kdyz nejde precist
function rd(path):
    if not exists(path):
        return None
    end
    text = None
    safe:
        text = fd.read_text(path)
    end
    if text == None:
        return None
    end
    cut = text.find("\n")
    if cut >= 0:
        text = text[0:cut]
    end
    return text.strip()
end

function as_int(text):
    value = None
    safe:
        value = Int(text)
    end
    return value
end

supply = envd("LUXOS_POWER_SUPPLY", "/sys/class/power_supply")
bat = ""
for name in luxos_sys.list_dir(supply):
    if name.startswith("BAT"):
        bat = supply + "/" + name
        break
    end
end
if bat == "":
    print "<txt></txt>"
    call exit(0)
end

cap_text = rd(bat + "/capacity")
if cap_text == None:
    cap_text = ""
end
cap = as_int(cap_text)
if cap == None:
    cap = 0
end
st = rd(bat + "/status")
if st == None:
    st = ""
end

# Automaticky Sporic baterie pri 20 % (zapina Baterie a napajeni); po pripojeni
# nabijecky ho zase vypne, ale jen kdyz ho zapnul on
config = envd("XDG_CONFIG_HOME", envd("HOME", "") + "/.config") + "/luxos"
auto = config + "/powersaver-auto"
mark = envd("XDG_RUNTIME_DIR", "/tmp") + "/luxos-powersaver-auto-on"
saver = config + "/powersaver"   # stav jako luxos-powersaver status, bez dalsiho procesu
if exists(auto):
    if st == "Discharging" and cap <= 20 and not exists(mark) and not exists(saver):
        call os.capture(["luxos-powersaver", "on"])
        call writefile(mark, "")
        call os.capture_result(["notify-send", "-i", "battery-caution", "-a", "LuxOS", i18n.T("Battery Saver is on"),
                                i18n.TF("Battery is at %s %%. Connect the charger.", [cap_text])])
    elif st != "Discharging" and exists(mark):
        call os.capture(["luxos-powersaver", "off"])
        call unlink(mark)
    end
end

level = (cap + 5) // 10 * 10
icon = "battery-level-" + String(level)
if st == "Charging":
    icon = icon + "-charging"
end
if st == "Full" or (st == "Not charging" and cap >= 95):
    icon = "battery-level-100-charged"
end
if st == "Charging":
    tip = i18n.T("Charging")
elif st == "Discharging":
    tip = i18n.T("On battery")
else:
    tip = i18n.T("Fully charged")
end

# Odhad casu z aktualniho odberu (energy_* v uWh/uW, nebo charge_* v uAh/uA); stejne poradi
# a zkraceni vyhodnoceni jako v puvodnim skriptu (rd a && rd b && rd c || { ... })
now = None
full = None
rate = None
got = False
now = rd(bat + "/energy_now")
if now != None:
    full = rd(bat + "/energy_full")
    if full != None:
        rate = rd(bat + "/power_now")
        got = rate != None
    end
end
if not got:
    probe = rd(bat + "/charge_now")
    if probe != None:
        now = probe
        probe = rd(bat + "/charge_full")
        if probe != None:
            full = probe
            probe = rd(bat + "/current_now")
            if probe != None:
                rate = probe
            end
        end
    end
end
if rate != None and rate.startswith("-"):
    rate = rate[1:]
end
now_i = as_int(now)
full_i = as_int(full)
rate_i = as_int(rate)
if rate_i == None:
    rate_i = 0
end
if now_i != None and full_i != None and rate_i > 0:
    mins = None
    if st == "Discharging":
        mins = now_i * 60 // rate_i
    elif st == "Charging" and full_i > now_i:
        mins = (full_i - now_i) * 60 // rate_i
    end
    if mins != None and mins > 0 and mins < 6000:
        if mins >= 60:
            t = String(mins // 60) + " h " + String(mins % 60) + " min"
        else:
            t = String(mins) + " min"
        end
        if st == "Discharging":
            tip = tip + " · " + i18n.TF("%s remaining", [t])
        else:
            tip = tip + " · " + i18n.TF("%s until full", [t])
        end
    end
end
if exists(saver):
    tip = tip + " · " + i18n.T("Battery Saver")
end
print "<icon>" + icon + "-symbolic</icon><txt> " + cap_text + " %</txt><tool>" + cap_text + " % · " + tip + "</tool><iconclick>luxos-cc-toggle</iconclick><txtclick>luxos-cc-toggle</txtclick>"
