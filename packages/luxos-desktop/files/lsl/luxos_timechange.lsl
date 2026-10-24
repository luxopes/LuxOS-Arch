# LuxOS - upozorneni na zmenu casu (letni/zimni cas) v luxos-hub.
# Jen v pasmech, kde se cas meni (podle /etc/localtime pres localtime_r - zadna tabulka zemi): vecer
# pred zmenou ("Dnes v noci zacina zimni cas, 03:00 -> 02:00") a rano po ni. Vypina se v Plocha a Dock
# (Horni lista) nebo tlacitkem Vypnout v upozorneni: ~/.config/luxos/notifications.conf TIME_CHANGE=0.
# Kontrola po prihlaseni, po probuzeni a dvakrat denne (192 volani localtime_r), presne casy hlida
# jednorazovy casovac - zadna smycka.
#   call timechange.subscribe()     po startu hubu
#   call timechange.check()         po probuzeni
# LUXOS_TIME_OFFSET (s) posune "ted" (testy), LUXOS_TIMECHANGE_DELAY prvni kontrola po prihlaseni (s).
load env
load luxos_glib, glib as glib
load luxos_i18n as i18n
load luxos_text as text

HOUR = 3600
DAY = 86400
EVENING = 18           # upozorneni pred zmenou: v 18:00 den pred ni
MORNING = 7            # upozorneni po zmene: nejdriv v 7:00 (ne ve 3 v noci, kdy nikdo nesedi u pocitace)

tc = {"pending": {}}

function config_dir():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.config"
    end
    return base + "/luxos"
end

function conf_path():
    return config_dir() + "/notifications.conf"
end

function state_path():
    return config_dir() + "/time-change.state"
end

function enabled():
    return text.parse_kv(glib.read_text(conf_path())).get("TIME_CHANGE") != "0"
end

function now():
    return glib.now() + text.to_int(env.get("LUXOS_TIME_OFFSET", ""), 0)
end

# Posun mistniho casu proti UTC v sekundach
function offset(t):
    f = glib.localtime(t)
    return glib.timegm(f[0], f[1], f[2], f[3], f[4], f[5]) - t
end

# Prvni sekunda s novym posunem mezi a (stary) a b (novy)
function find_change(a, b):
    old = offset(a)
    while b - a > 1:
        middle = a + (b - a) // 2
        if offset(middle) == old:
            a = middle
        else:
            b = middle
        end
    end
    return b
end

# Nejblizsi zmena v pristich 8 dnech (0 = zadna)
function next_change(t):
    old = offset(t)
    limit = t + 8 * DAY
    while t < limit:
        step = t + HOUR
        if offset(step) != old:
            return find_change(t, step)
        end
        t = step
    end
    return 0
end

function hhmm(t):
    f = glib.gmtime(t)
    return text.pad(f[3], 2) + ":" + text.pad(f[4], 2)
end

# Mistni cas den pred zmenou / v den zmeny v dane hodine
function evening_before(change):
    f = glib.localtime(change - 9 * HOUR)
    return glib.mktime(f[0], f[1], f[2], EVENING, 0, 0)
end

function morning_after(change):
    f = glib.localtime(change + 60)
    at = glib.mktime(f[0], f[1], f[2], MORNING, 0, 0)
    if at < change + 60:
        return change + 60
    end
    return at
end

# [titulek, text] upozorneni; before = vecer pred zmenou
function message(change, before):
    old = offset(change - 1)
    new = offset(change)
    dst = glib.localtime(change)[8] > 0
    was_dst = glib.localtime(change - 1)[8] > 0
    times = [hhmm(change + old), hhmm(change + new)]
    title = ""
    if before:
        title = i18n.T("The time changes tonight")
        if dst and not was_dst:
            title = i18n.T("Summer time starts tonight")
        elif was_dst and not dst:
            title = i18n.T("Winter time starts tonight")
        end
        body = i18n.TF("Clocks go back from %s to %s. Your computer changes the time automatically.", times)
        if new > old:
            body = i18n.TF("Clocks go forward from %s to %s. Your computer changes the time automatically.", times)
        end
        return [title, body]
    end
    title = i18n.T("The time has changed")
    if dst and not was_dst:
        title = i18n.T("Summer time has started")
    elif was_dst and not dst:
        title = i18n.T("Winter time has started")
    end
    body = i18n.TF("Clocks went back from %s to %s.", times)
    if new > old:
        body = i18n.TF("Clocks went forward from %s to %s.", times)
    end
    return [title, body]
end

function notify(change, before, key, state):
    m = message(change, before)
    call glib.spawn_capture(["notify-send", "-a", "LuxOS", "-i", "preferences-system-time", "-w",
                             "-A", "off=" + i18n.T("Turn Off"), m[0], m[1]], on_action, 0)
    state[key] = String(change)
    call glib.mkdir_p(config_dir())
    out = ""
    for name in ["BEFORE", "AFTER"]:
        if name in state:
            out = out + name + "=" + String(state[name]) + "\n"
        end
    end
    call glib.write_atomic(state_path(), out)
    return 0
end

# Tlacitko Vypnout v upozorneni: TIME_CHANGE=0 (ostatni radky souboru zustanou)
function on_action(unused, output, status):
    if output.strip() != "off":
        return 0
    end
    out = ""
    for line in glib.read_text(conf_path()).split("\n"):
        if line != "" and not line.strip().startswith("TIME_CHANGE="):
            out = out + line + "\n"
        end
    end
    call glib.mkdir_p(config_dir())
    call glib.write_atomic(conf_path(), out + "TIME_CHANGE=0\n")
    return 0
end

# Jednorazova kontrola v presny cas (jen jeden casovac na kazdy cas)
function schedule(at, t):
    key = String(at)
    if key in tc["pending"] or at - t > 2 * DAY:
        return 0
    end
    tc["pending"][key] = True
    call glib.timeout_add_seconds_data(at - t + 1, fire, key)
    return 0
end

function fire(key):
    if key in tc["pending"]:
        call tc["pending"].pop(key)
    end
    call check()
    return False
end

function check():
    if not enabled():
        return True
    end
    t = now()
    state = text.parse_kv(glib.read_text(state_path()))
    # zmena uz probehla (posledni 1,5 dne): rano po ni
    if offset(t - 36 * HOUR) != offset(t):
        change = find_change(t - 36 * HOUR, t)
        if state.get("AFTER") != String(change):
            if t >= morning_after(change):
                call notify(change, False, "AFTER", state)
            else:
                call schedule(morning_after(change), t)
            end
        end
    end
    change = next_change(t)
    if change != 0:
        at = evening_before(change)
        if t >= at:
            if state.get("BEFORE") != String(change):
                call notify(change, True, "BEFORE", state)
            end
        else:
            call schedule(at, t)
        end
        call schedule(morning_after(change), t)
    end
    return True
end

function first_check():
    call check()
    return False
end

function subscribe():
    call glib.timeout_add_seconds(text.to_int(env.get("LUXOS_TIMECHANGE_DELAY", ""), 60), first_check)
    call glib.timeout_add_seconds(12 * HOUR, check)
    return 0
end
