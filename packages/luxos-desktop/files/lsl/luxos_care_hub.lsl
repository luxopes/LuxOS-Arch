# LuxOS Care - cast v relaci uzivatele (bezi uvnitr luxos-hub); prepis luxos_care_session.py.
# - hlida /var/lib/luxos-care (udalost souboru, zadne dotazovani) a ukazuje upozorneni
#   ("LuxOS byl aktualizovan", "Restartujte pro dokonceni aktualizace jadra", "LuxOS opravil problem"),
# - v rezimu carefree nechá neznamy vazny problem vybrat LuxAI Flash: dotaz na sluzbu (HTTPS s tokenem
#   uzivatele) dela pomocny program v Pythonu `luxos_care_session.py ask <id>` spusteny jen pro tu chvili
#   (LSL nema TLS); ten take spusti jednotku luxos-care-apply@<id>-<cislo>.service. Zadny prikaz od AI se nespousti.
#   call care.subscribe(session_bus, system_bus)
load env, json
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_i18n as i18n
load luxos_text as text

APP = "luxos-update"
HELPER = "/usr/lib/luxos/python/luxos_care_session.py"

state = {"bus": 0, "sys": 0, "actions": {}, "asking": False, "timer": 0}

function root():
    value = env.get("LUXOS_CARE_ROOT", "")
    if value == None:
        return ""
    end
    return value
end

function state_dir():
    return root() + "/var/lib/luxos-care"
end

function cache_dir():
    base = env.get("XDG_CACHE_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.cache"
    end
    return base + "/luxos"
end

function helper_path():
    value = env.get("LUXOS_CARE_HELPER", "")
    if value == None or value == "":
        return HELPER
    end
    return value
end

function log(message):
    return eprint("luxos-hub: care: " + message)
end

function read_json(name, default):
    raw = glib.read_text(state_dir() + "/" + name)
    if raw == "":
        return default
    end
    value = default
    try:
        value = json.decode(raw)
    else:
        value = default
    end
    if type(value) != type(default):
        return default
    end
    return value
end

function read_lines(path):
    out = []
    for line in glib.read_text(path).split("\n"):
        if line.strip() != "":
            out.append(line.strip())
        end
    end
    return out
end

function mode():
    for line in glib.read_text(root() + "/etc/luxos/care.conf").split("\n"):
        if line.strip() == "MODE=classic":
            return "classic"
        end
    end
    return "carefree"
end

# ---- upozorneni ---------------------------------------------------------------------------------------

function problem_text(ev):
    t = i18n.T(String(ev.get("title", "")))
    args = ev.get("args")
    if args != None and type(args) == "List" and len(args) > 0 and t.find("%s") >= 0:
        t = t.replace("%s", String(args[0]))
    end
    return t
end

function count_of(ev):
    value = ev.get("count")
    if value == None:
        return 0
    end
    return text.to_int(String(value), 0)
end

# [nadpis, text, akce [[id, popis]]] pro udalost, nebo None
function notification_for(ev):
    k = ev.get("kind")
    if k == "updated":
        if ev.get("reboot") == True:
            return [i18n.T("Restart to finish the kernel update"), i18n.T("LuxOS installed a new kernel. Restart when it suits you."),
                    [["restart", i18n.T("Restart")], ["open", i18n.T("Details")]]]
        end
        return [i18n.T("LuxOS was updated"), i18n.TF("%d packages were updated.", [count_of(ev)]), [["open", i18n.T("Details")]]]
    end
    if k == "updates_available":
        return [i18n.T("Updates are available"), i18n.TF("%d updates are ready to install.", [count_of(ev)]), [["open", i18n.T("Update")]]]
    end
    if k == "update_failed":
        return [i18n.T("Updates could not be installed"), i18n.T("LuxOS will try again later."), [["open", i18n.T("Details")]]]
    end
    if k == "update_skipped":
        reason = ev.get("reason")
        why = ""
        if reason == "offline":
            why = i18n.T("No internet connection.")
        elif reason == "metered":
            why = i18n.T("The connection is metered (Data Saver).")
        elif reason == "battery":
            why = i18n.T("The battery is low - connect the charger.")
        end
        return [i18n.T("Update postponed"), why, [["open", i18n.T("Details")]]]
    end
    if k == "repaired":
        body = problem_text(ev)
        if ev.get("ai") == True:
            body = body + "\n" + i18n.T("The repair was chosen by LuxAI Flash.")
        end
        return [i18n.T("LuxOS fixed a problem"), body, [["open", i18n.T("Details")]]]
    end
    if k == "problem":
        return [i18n.T("LuxOS found a problem"), problem_text(ev), [["open", i18n.T("Details")]]]
    end
    if k == "rolled_back":
        return [i18n.T("LuxOS was restored"), i18n.TF("LuxOS is back in the state: %s", [String(ev.get("label", ""))]), []]
    end
    if k == "integrity":
        return [i18n.T("System files were changed"),
                i18n.TF("%d system files were changed or are missing. LuxOS can repair them by reinstalling the affected packages.", [count_of(ev)]),
                [["open", i18n.T("Details")]]]
    end
    return None
end

# Start ze snimku (luxos.snapshot= v /proc/cmdline): jmeno snimku, jinak ""
function booted_snapshot():
    for line in read_lines(root() + "/proc/cmdline"):
        for word in line.split(" "):
            if word.startswith("luxos.snapshot="):
                return word[15:].strip()
            end
        end
    end
    return ""
end

# Datum ze jmena snimku RRRR-MM-DD_HH-MM-SS -> "RRRR-MM-DD HH:MM"
function snapshot_date(name):
    if len(name) < 16:
        return name
    end
    return name[0:10] + " " + name[11:13] + ":" + name[14:16]
end

# Po prihlaseni do systemu spusteneho ze snimku: zmeny se po restartu ztrati, nabidnout trvaly navrat
function snapshot_notice():
    name = booted_snapshot()
    if name == "":
        return False
    end
    call notify(i18n.T("LuxOS is running from a snapshot"),
                i18n.TF("This is LuxOS before the update of %s. Changes are lost after a restart.", [snapshot_date(name)]),
                [["keep", i18n.T("Keep this version")]])
    return False
end

# Asynchronne: zaseknuty server upozorneni nesmi blokovat luxos-hub
function notify(title, body, actions):
    if state["bus"] == 0:
        return 0
    end
    acts = []
    for pair in actions:
        acts.append(pair[0])
        acts.append(pair[1])
    end
    call gio.call_async(state["bus"], "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify",
                        ["LuxOS", 0, "system-software-update", title, body, acts, {"desktop-entry": ["s", APP]}, -1], "(susssasa{sv}i)", 5000, on_notified, 0)
    return 0
end

# Zmenene systemove soubory (luxos-care verify): kriticke upozorneni, ktere zustane v historii
# upozorneni (hint x-luxos-keep); notify-send -w ceka na tlacitko
function notify_critical(title, body, actions):
    argv = ["notify-send", "-a", "LuxOS", "-u", "critical", "-h", "boolean:x-luxos-keep:true", "-i", "dialog-warning", "-w"]
    for pair in actions:
        argv.append("-A")
        argv.append(pair[0] + "=" + pair[1])
    end
    argv.append(title)
    argv.append(body)
    call glib.spawn_capture(argv, on_critical_action, 0)
    return 0
end

function on_critical_action(unused, output, status):
    if output.strip() == "open":
        call glib.spawn([APP])
    end
    return 0
end

function on_notified(unused, values, error):
    if values == None:
        call log("notify: " + error)
        return 0
    end
    state["actions"][values[0]] = True
    return 0
end

function on_action(sender, path, interface, signal, values):
    nid = values[0]
    action = values[1]
    if nid not in state["actions"]:
        return 0
    end
    call state["actions"].pop(nid, None)
    if action == "restart":
        call glib.spawn(["xfce4-session-logout", "--reboot", "--fast"])
    elif action == "keep":
        # lux rollback v terminalu: zepta se, overi heslo a vypise vysledek
        call glib.spawn(["luxos-terminal", "--hold", "-x", "lux", "rollback"])
    elif action == "open" or action == "default":
        call glib.spawn([APP])
    end
    return 0
end

# Udalosti k upozorneni; pri prvnim spusteni jen ty z posledni hodiny (ne cela historie)
function new_events(events, seen, first_run, now):
    out = []
    for ev in events:
        if type(ev) != "Dictionary":
            continue
        end
        seq = text.to_int(String(ev.get("seq", 0)), 0)
        if seq <= seen:
            continue
        end
        if first_run and now - text.to_int(String(ev.get("time", 0)), 0) > 3600:
            continue
        end
        out.append(ev)
    end
    # Z vice stejnych udalosti jen posledni
    last = {}
    order = []
    for ev in out:
        key = String(ev.get("kind")) + "|" + String(ev.get("title", ""))
        last[key] = ev
    end
    buckets = {}
    for key in last.keys():
        ev = last[key]
        buckets[text.pad(text.to_int(String(ev.get("seq", 0)), 0), 20) + key] = ev
    end
    for key in sorted(buckets.keys()):
        order.append(buckets[key])
    end
    return order
end

# Cas startu systemu (btime z /proc/stat), 0 kdyz nejde zjistit
function boot_time():
    for line in read_lines(root() + "/proc/stat"):
        if line.startswith("btime "):
            return text.to_int(line[6:].strip(), 0)
        end
    end
    return 0
end

# "Restartujte" k udalosti z doby pred timto startem uz neplati (restart probehl)
function drop_done_reboot(ev, booted):
    if ev.get("kind") != "updated" or ev.get("reboot") != True or booted == 0:
        return ev
    end
    if text.to_int(String(ev.get("time", 0)), 0) >= booted:
        return ev
    end
    if count_of(ev) == 0:
        return None
    end
    out = {}
    for key in ev.keys():
        out[key] = ev[key]
    end
    out["reboot"] = False
    return out
end

function process_events():
    data = read_json("events.json", {"seq": 0, "events": []})
    lines = read_lines(cache_dir() + "/care-seen")
    first = len(lines) == 0
    seen = 0
    if len(lines) > 0 and text.is_digits(lines[0]):
        seen = Int(lines[0])
    end
    current = text.to_int(String(data.get("seq", 0)), 0)
    if seen > current:
        seen = 0                                  # stav se smazal a zacal znovu
    end
    events = data.get("events", [])
    if type(events) != "List":
        events = []
    end
    booted = boot_time()
    for raw in new_events(events, seen, first, glib.now()):
        ev = drop_done_reboot(raw, booted)
        if ev == None:
            continue
        end
        n = notification_for(ev)
        if n != None and ev.get("kind") == "integrity":
            call notify_critical(n[0], n[1], n[2])
        elif n != None:
            call notify(n[0], n[1], n[2])
        end
    end
    call glib.mkdir_p(cache_dir())
    call glib.write_atomic(cache_dir() + "/care-seen", String(current) + "\n")
    return 0
end

# ---- LuxAI Flash (pomocny program v Pythonu) ---------------------------------------------------------

function valid_id(value):
    if type(value) != "String" or len(value) != 12:
        return False
    end
    for ch in value:
        if not (text.is_digit(ch) or (ord(ch) >= 97 and ord(ch) <= 102)):
            return False
        end
    end
    return True
end

function process_ai():
    if state["asking"] or mode() != "carefree" or state["sys"] == 0:
        return 0
    end
    st = read_json("state.json", {})
    asked = read_lines(cache_dir() + "/care-ai-asked")
    problems = st.get("problems", [])
    if type(problems) != "List":
        return 0
    end
    for p in problems:
        if type(p) != "Dictionary":
            continue
        end
        req = p.get("ai")
        if req == None or type(req) != "Dictionary":
            continue
        end
        rid = req.get("request_id", "")
        if req.get("status") != "pending" or not valid_id(rid) or rid in asked:
            continue
        end
        asked.append(rid)
        if len(asked) > 100:
            asked = asked[len(asked) - 100:]
        end
        call glib.mkdir_p(cache_dir())
        call glib.write_atomic(cache_dir() + "/care-ai-asked", text.join(asked, "\n") + "\n")
        state["asking"] = True
        if glib.spawn_capture(["python3", "-I", helper_path(), "ask", rid], on_ai_done, p) == 0:
            state["asking"] = False
            call log("helper " + helper_path() + " could not be started")
        end
        return 0
    end
    return 0
end

function on_ai_done(problem, output, status):
    state["asking"] = False
    result = {}
    try:
        result = json.decode(output.strip())
    else:
        result = {}
    end
    if type(result) != "Dictionary":
        result = {}
    end
    option = result.get("option")
    info = String(result.get("info", ""))
    if option == None:
        call log("LuxAI did not choose a repair (" + info + ")")
        if info == "signed_out":
            call notify(i18n.T("LuxOS found a problem"), problem_text(problem) + "\n" + i18n.T("Sign in to LuxAI to let LuxOS fix unknown problems."), [["open", i18n.T("Details")]])
        end
    elif result.get("started") == True:
        call log("LuxAI chose option " + String(option) + " for " + String(problem.get("id")))
    end
    return 0
end

# ---- napojeni -------------------------------------------------------------------------------------------

function on_change():
    state["timer"] = 0
    try:
        call process_events()
    else:
        call log("events: " + String(last_error()))
    end
    try:
        call process_ai()
    else:
        call log("ai: " + String(last_error()))
    end
    return False
end

function basename(path):
    return path[text.rfind(path, "/") + 1:]
end

function on_file(path, event, other):
    # Root zapisuje atomicky (docasny soubor + prejmenovani) -> rozhoduje cilove jmeno
    name = basename(path)
    if event == gio.FILE_RENAMED and other != "":
        name = basename(other)
    end
    if name != "events.json" and name != "state.json":
        return 0
    end
    if event != gio.FILE_CHANGES_DONE_HINT and event != gio.FILE_CREATED and event != gio.FILE_MOVED_IN and event != gio.FILE_RENAMED:
        return 0
    end
    if state["timer"] != 0:
        call glib.source_remove(state["timer"])
    end
    state["timer"] = glib.timeout_add(1500, on_change)
    return 0
end

# Volano z luxos-hub pri startu relace
function subscribe(session, system):
    state["bus"] = session
    state["sys"] = system
    if session != 0:
        call gio.subscribe_values(session, "org.freedesktop.Notifications", "org.freedesktop.Notifications", "ActionInvoked", "/org/freedesktop/Notifications", on_action)
    end
    try:
        call gio.file_monitor(state_dir(), on_file)
    else:
        call log("monitor: " + String(last_error()))
    end
    # Po prihlaseni: co se stalo pred chvili (napr. oprava pri startu)
    call glib.timeout_add_seconds(text.to_int(env.get("LUXOS_CARE_DELAY", ""), 20), on_change)
    call glib.timeout_add_seconds(text.to_int(env.get("LUXOS_CARE_DELAY", ""), 20), snapshot_notice)
    return 0
end
