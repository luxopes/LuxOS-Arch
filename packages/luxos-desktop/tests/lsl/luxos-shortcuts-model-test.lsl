# Test luxos_shortcuts_model.lsl bez displeje (test_luxos_shortcuts.py): radky "ok NAZEV" / "FAIL NAZEV ...".
# Vsechna volani xfconf-query jdou na falesny prikaz (LUXOS_XFCONF_QUERY = tests/fake-shortcuts/xfconf-query,
# stav v FAKE_XFCONF, zaznam volani v FAKE_XFCONF_LOG). SC_TEST_TMP = docasna slozka, SC_DEFAULTS = vychozi XML.
load env, json
load luxos_sys
load luxos_glib as lglib
load luxos_shortcuts_model as ls

failures = 0
TMP = env.get("SC_TEST_TMP", "/nonexistent")
DEFAULTS_XML = env.get("SC_DEFAULTS", "")

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

function reset_fake():
    for p in [env.get("FAKE_XFCONF", ""), env.get("FAKE_XFCONF_LOG", ""), ls.store_path(), env.get("LUXOS_XKB_CONF", "")]:
        if p != "" and exists(p):
            call lglib.unlink(p)
        end
    end
end

function user_values():
    data = None
    safe:
        data = json.decode(lglib.read_text(env.get("FAKE_XFCONF", "")))
    end
    if data == None:
        return {}
    end
    return data
end

function calls():
    found = []
    for line in lglib.read_text(env.get("FAKE_XFCONF_LOG", "")).split("\n"):
        if line.strip() != "":
            found.append(json.decode(line))
        end
    end
    return found
end

function writes():
    return [c for c in calls() if "-s" in c or "-r" in c]
end

function act(m, aid):
    return ls.find_action(m, aid)
end

function labels(items):
    return [a["label"] for a in items]
end

# ---- Accel ----
call expect("parse", ls.parse_accel("<Super><Shift>4"), [["super", "shift"], "4"])
call expect("parse-solo", ls.parse_accel("XF86Calculator"), [[], "XF86Calculator"])
call expect("parse-upper", ls.parse_accel("<Super>A"), [["super"], "a"])
bad = ["", None, "<Super>", "<Foo>a", "<Super", "<Super>a b", 5]
for i in range(len(bad)):
    call expect("parse-bad-" + String(i), ls.parse_accel(bad[i]), None)
end
call expect("normalize-order", ls.normalize("<Shift><Super>Down"), ls.normalize("<Super><Shift>Down"))
call expect("normalize-3", ls.normalize("<Super><Shift>3"), "<Shift><Super>3")
call expect("normalize-ctrl", ls.normalize("<Control><Alt>Delete"), "<Primary><Alt>Delete")
call expect("normalize-mod4", ls.normalize("<Mod4>space"), "<Super>space")
call expect("normalize-mod1", ls.normalize("<Mod1>F4"), "<Alt>F4")
call expect("normalize-lower", ls.normalize("<Super>E"), "<Super>e")
call expect("normalize-tab", ls.normalize("<Super>Tab") != ls.normalize("<Super><Shift>Tab"), True)
for t in ["<Primary><Shift><Alt><Super>x", "F11", "<Super>KP_1"]:
    call expect("normalize-stable " + t, ls.normalize(ls.normalize(t)), ls.normalize(t))
end
formats = [["<Super><Shift>4", "Super + Shift + 4"], ["<Shift><Super>4", "Super + Shift + 4"], ["<Primary><Super>f", "Ctrl + Super + F"],
    ["<Super><Alt>Escape", "Super + Alt + Esc"], ["<Primary><Alt>Delete", "Ctrl + Alt + Delete"], ["<Super>comma", "Super + ,"],
    ["<Super>space", "Super + Space"], ["<Super>Up", "Super + ↑"], ["<Super>grave", "Super + `"], ["XF86Calculator", "Calculator"],
    ["XF86AudioPlay", "Audio Play"], ["<Super>KP_1", "Super + Num 1"], ["<Alt><Shift>Page_Down", "Alt + Shift + Page Down"],
    ["<Shift>Print", "Shift + Print Screen"]]
for f in formats:
    call expect("format " + f[0], ls.format_accel(f[0]), f[1])
end
call expect("format-no-cmd-symbol", ls.format_accel("<Super>q").find("⌘"), -1)
for a in ["<Super>e", "<Primary><Alt>t", "F11", "Print", "XF86Calculator"]:
    call expect("allowed " + a, ls.accel_allowed(a), True)
end
# pismeno bez modifikatoru by blokovalo psani, samotne modifikatory nejsou zkratka
for a in ["e", "<Shift>e", "Escape", "<Super>Shift_L", ""]:
    call expect("not-allowed " + a, ls.accel_allowed(a), False)
end

# ---- Parsing ----
listing = "/commands/custom/<Super>e                  thunar\n/commands/custom/<Super>t                  xfce4-terminal --drop-down\n/commands/custom/<Super>t/startup-notify   true\n/commands/custom/<Super>x\n/commands/custom/override                  true\n/commands/default/<Alt>F2                  xfrun4\n/xfwm4/custom/<Super>q                     close_window_key\n/xfwm4/default/<Alt>F4                     close_window_key\n"
out = ls.parse_listing(listing)
call expect("listing-cmd", out["cmd"], {"<Super>e": "thunar", "<Super>t": "xfce4-terminal --drop-down", "<Super>x": ""})
call expect("listing-wm", out["wm"], {"<Super>q": "close_window_key"})
call expect("listing-empty", ls.parse_listing(""), {"cmd": {}, "wm": {}})
d = ls.read_defaults(DEFAULTS_XML)
call expect("defaults-xml", [d["cmd"]["<Super>e"], d["cmd"]["<Super><Shift>4"], d["wm"]["<Super>q"], "override" in d["cmd"]], ["thunar", "luxos-screenshot --portion", "close_window_key", False])
call expect("defaults-missing", ls.read_defaults(TMP + "/missing.xml"), {"cmd": {}, "wm": {}})

p = TMP + "/kb.conf"
call writefile(p, "Section \"InputClass\"\n  Option \"XkbLayout\" \"cz,us\"\n  Option \"XkbOptions\" \"terminate:ctrl_alt_bksp,grp:alt_shift_toggle\"\nEndSection\n")
call expect("layout-switch-alt-shift", ls.layout_switch(p), "Alt + Shift")
call writefile(p, "Option \"XkbOptions\" \"grp:win_space_toggle\"\n")
call expect("layout-switch-super-space", ls.layout_switch(p), "Super + Space")
call writefile(p, "Option \"XkbLayout\" \"us\"\n")
call expect("layout-switch-none", ls.layout_switch(p), "")
call expect("layout-switch-missing", ls.layout_switch(TMP + "/none.conf"), "")
call writefile(p, "Option \"XkbOptions\" \"grp:shifts_toggle,compose:ralt\"\n")
call expect("layout-switch-luxos", ls.layout_switch(p), "Left Shift + Right Shift")

flag = ls.super_tap_flag()
call expect("super-flag-path", flag, env.get("XDG_CONFIG_HOME", "") + "/luxos/super-launchpad-off")
call expect("super-default-on", ls.super_tap_enabled(""), True)
call expect("super-off", [ls.set_super_tap(False, ""), exists(flag), ls.super_tap_enabled("")], [True, True, False])
call expect("super-off-again", ls.set_super_tap(False, ""), True)
call expect("super-on", [ls.set_super_tap(True, ""), exists(flag)], [True, False])
call expect("super-on-again", ls.set_super_tap(True, ""), True)
call writefile(TMP + "/file-not-dir", "")
call expect("super-unwritable", ls.set_super_tap(False, TMP + "/file-not-dir/x/flag"), False)

call expect("short-label-exo", ls.short_label("exo-open --launch WebBrowser"), "Web Browser")
call expect("short-label-path", ls.short_label("/usr/bin/xfce4-appfinder --collapsed"), "xfce4-appfinder")
call expect("short-label-exo-alone", ls.short_label("exo-open --launch"), "exo-open")
call expect("short-label-bad-quote", ls.short_label("bad 'quote"), "bad")
call expect("field-codes", ls.strip_field_codes("firefox %u"), "firefox")
call expect("field-codes-quoted", ls.strip_field_codes("env A=1 'my app' --file=%f"), "env A=1 'my app' --file=")
call expect("field-codes-percent", ls.strip_field_codes("echo 100%%"), "echo 100%")

# ---- Store ----
call reset_fake()
sp = TMP + "/s/shortcuts.json"
call expect("store-missing", ls.load_names(sp), {})
call ls.save_names({"<Super>n": {"name": "Notes", "command": "mousepad"}}, sp)
call expect("store-roundtrip", ls.load_names(sp), {"<Super>n": {"name": "Notes", "command": "mousepad"}})
call writefile(sp, "{broken")
call expect("store-broken", ls.load_names(sp), {})
call writefile(sp, json.encode({"custom": {"<Mod4>n": {"name": "A", "command": "a"}, "bad<": {"name": "x", "command": "y"}, "<Super>m": "nope", "<Super>k": {"name": 1, "command": "z"}}}))
call expect("store-filtered", ls.load_names(sp), {"<Super>n": {"name": "A", "command": "a"}})
call writefile(sp, "[1, 2]")
call expect("store-list", ls.load_names(sp), {})

# ---- Model ----
call reset_fake()
m = ls.new_model(None, "")
call expect("initial-available", m["available"], True)
call expect("initial-close", ls.accels_for(m, act(m, "close")), ["<Super>q", "<Alt>F4"])
call expect("initial-hide", ls.accels_for(m, act(m, "hide")), ["<Super>m", "<Super>h", "<Super>Down"])
call expect("initial-shot-region", ls.accels_for(m, act(m, "shot-region")), ["<Shift><Super>4", "<Shift>Print"])
call expect("initial-search", ls.accels_for(m, act(m, "search")), ["<Super>space"])
call expect("initial-all-default", [a["id"] for a in ls.actions(m) if not ls.is_default(m, a)], [])
call expect("initial-no-custom", ls.custom_actions(m), [])
call expect("initial-no-writes", writes(), [])
call expect("initial-channel", [c for c in calls() if c[:2] != ["-c", "xfce4-keyboard-shortcuts"]], [])

files = act(m, "files")
call expect("conflict-own", ls.conflict(m, files, "<Super>e"), None)
call expect("conflict-free", ls.conflict(m, files, "<Super>y"), None)
call expect("conflict-terminal", ls.conflict(m, files, "<Super>t"), "Terminal")
call expect("conflict-wm", ls.conflict(m, files, "<Super>q"), "Close window")
call expect("conflict-cmd-for-wm", ls.conflict(m, act(m, "close"), "<Super>e"), "Files")
call expect("conflict-none-action", ls.conflict(m, None, ls.normalize("<Super><Shift>3")), "Screenshot")
call expect("conflict-workspace", ls.conflict(m, files, "<Primary><Super>1"), "Go to workspace 1")

# zmena a obnoveni: systemova zkratka se vypne prazdnou hodnotou, po obnoveni zadne zbytky
call reset_fake()
m = ls.new_model(None, "")
call expect("change", ls.assign(m, act(m, "files"), "<Super>f", "<Super>e"), True)
call expect("change-accels", ls.accels_for(m, act(m, "files")), ["<Super>f"])
call expect("change-not-default", ls.is_default(m, act(m, "files")), False)
u = user_values()
call expect("change-values", [u["/commands/custom/<Super>e"], u["/commands/custom/<Super>f"]], ["", "thunar"])
call expect("restore", ls.restore(m, act(m, "files")), True)
call expect("restore-accels", [ls.accels_for(m, act(m, "files")), ls.is_default(m, act(m, "files"))], [["<Super>e"], True])
call expect("restore-clean", user_values(), {})

call reset_fake()
m = ls.new_model(None, "")
call ls.assign(m, act(m, "files"), "<Super>t", "<Super>e")
call expect("replace-files", ls.accels_for(m, act(m, "files")), ["<Super>t"])
call expect("replace-terminal-keeps", ls.accels_for(m, act(m, "terminal")), ["<Primary><Alt>t"])
call expect("replace-owner", ls.owner_label(m, "<Super>t"), "Files")
call ls.restore(m, act(m, "terminal"))
call expect("replace-restore-terminal", ls.accels_for(m, act(m, "terminal")), ["<Super>t", "<Primary><Alt>t"])
call expect("replace-files-lost", ls.accels_for(m, act(m, "files")), [])

call reset_fake()
m = ls.new_model(None, "")
call ls.assign(m, act(m, "launchpad"), "<Super>q", "<Super>a")
call expect("cross-kind-close", ls.accels_for(m, act(m, "close")), ["<Alt>F4"])
call expect("cross-kind-value", user_values()["/xfwm4/custom/<Super>q"], "")
call expect("cross-kind-launchpad", ls.accels_for(m, act(m, "launchpad")), ["<Super>q", "XF86LaunchA"])

# systemova vlastnost je "<Super><Shift>4" - zapis musi pouzit stejny nazev, ne kanonicky
call reset_fake()
m = ls.new_model(None, "")
call ls.assign(m, act(m, "shot-region"), "<Primary><Super>4", ls.normalize("<Super><Shift>4"))
u = user_values()
call expect("raw-name", [u.get("/commands/custom/<Super><Shift>4", None), u.get("/commands/custom/<Primary><Super>4", None), "/commands/custom/<Shift><Super>4" in u], ["", "luxos-screenshot --portion", False])

call reset_fake()
m = ls.new_model(None, "")
call ls.assign(m, act(m, "files"), "<Super>e", "<Super>e")
call expect("same-accel-noop", [user_values(), ls.accels_for(m, act(m, "files"))], [{}, ["<Super>e"]])

call reset_fake()
m = ls.new_model(None, "")
call expect("disable", ls.disable(m, act(m, "close")), True)
call expect("disable-accels", [ls.accels_for(m, act(m, "close")), ls.owner(m, "<Super>q")], [[], None])
call ls.restore(m, act(m, "close"))
call expect("disable-restore", ls.accels_for(m, act(m, "close")), ["<Super>q", "<Alt>F4"])

call reset_fake()
m = ls.new_model(None, "")
call expect("custom-save", ls.save_custom(m, "Notes", "mousepad", "<Super>n", ""), True)
call expect("custom-list", [[a["label"], a["values"][0]] for a in ls.custom_actions(m)], [["Notes", "mousepad"]])
call expect("custom-names", ls.load_names(""), {"<Super>n": {"name": "Notes", "command": "mousepad"}})
call expect("custom-conflict", ls.conflict(m, act(m, "files"), "<Super>n"), "Notes")
call expect("custom-edit", ls.save_custom(m, "My Notes", "mousepad ~/notes.txt", "<Super><Alt>n", "<Super>n"), True)
call expect("custom-edit-old-free", ls.owner(m, "<Super>n"), None)
call expect("custom-edit-list", [[a["label"], a["values"][0]] for a in ls.custom_actions(m)], [["My Notes", "mousepad ~/notes.txt"]])
call expect("custom-edit-names", ls.load_names("").keys(), ["<Alt><Super>n"])
call expect("custom-delete", ls.delete_custom(m, "<Alt><Super>n"), True)
call expect("custom-delete-state", [ls.custom_actions(m), ls.load_names(""), user_values()], [[], {}, {}])

call reset_fake()
m = ls.new_model(None, "")
call ls.save_custom(m, "Browser", "firefox", "<Super>l", "")
call expect("custom-overrides-lock", ls.accels_for(m, act(m, "lock")), ["<Primary><Super>q"])
call expect("custom-overrides-owner", ls.owner_label(m, "<Super>l"), "Browser")
call ls.delete_custom(m, "<Super>l")
call expect("custom-delete-returns-lock", ls.accels_for(m, act(m, "lock")), ["<Primary><Super>q", "<Super>l"])

# vlastni zkratka se stejnym prikazem jako katalog patri do Vlastnich, ne k Souborum
call reset_fake()
m = ls.new_model(None, "")
call ls.save_custom(m, "Second Files", "thunar", "<Super>j", "")
call expect("named-catalog-command", [ls.accels_for(m, act(m, "files")), labels(ls.custom_actions(m))], [["<Super>e"], ["Second Files"]])

call reset_fake()
call ls.xfconf_call(["-p", "/commands/custom/<Super>g", "-n", "-t", "string", "-s", "gimp"])
m = ls.new_model(None, "")
call expect("unnamed-custom", [[a["label"], a["values"][0], a["id"]] for a in ls.custom_actions(m)], [["gimp", "gimp", "custom:<Super>g"]])
call ls.save_names({"<Super>g": {"name": "Old", "command": "inkscape"}}, "")
call ls.reload(m)
call expect("unnamed-custom-other-command", ls.custom_actions(m)[0]["label"], "gimp")

call reset_fake()
m = ls.new_model(None, "")
call ls.save_custom(m, "Notes", "mousepad", "<Super>n", "")
call ls.save_custom(m, "Browser", "firefox", "<Super>l", "")
call ls.assign(m, act(m, "files"), "<Super>f", "<Super>e")
call ls.disable(m, act(m, "close"))
call expect("restore-all", ls.restore_all(m), True)
call expect("restore-all-default", [a["id"] for a in m["catalog"] if not ls.is_default(m, a)], [])
call expect("restore-all-custom", labels(ls.custom_actions(m)), ["Notes"])
call expect("restore-all-names", ls.load_names(""), {"<Super>n": {"name": "Notes", "command": "mousepad"}})
call expect("restore-all-values", user_values(), {"/commands/custom/<Super>n": "mousepad"})

# vychozi prikazy mimo katalog; falesny xfconf je ma vypnute (nejsou v XML)
call reset_fake()
m = ls.new_model({"cmd": {"<Super>e": "thunar", "<Alt>F2": "xfrun4", "<Super>r": "xfrun4"}, "wm": {"<Super>q": "close_window_key"}}, "")
other = ls.other_actions(m)
call expect("other-actions", [[a["id"], a["label"]] for a in other], [["other:xfrun4", "xfrun4"]])
call expect("other-actions-off", ls.accels_for(m, other[0]), [])

call reset_fake()
# xfconf neodpovida (jako FAKE_XFCONF_FAIL v testu Pythonu)
call luxos_sys.setenv("LUXOS_XFCONF_QUERY", "/bin/false")
m = ls.new_model(None, "")
call expect("unavailable", m["available"], False)
call expect("unavailable-defaults", ls.accels_for(m, act(m, "files")), ["<Super>e"])
call expect("unavailable-write", ls.assign(m, act(m, "files"), "<Super>f", "<Super>e"), False)
call luxos_sys.setenv("LUXOS_XFCONF_QUERY", env.get("SC_FAKE", ""))
call expect("unavailable-nothing", user_values(), {})
call expect("never-real-xfconf", ls.xfconf_cmd(), env.get("SC_FAKE", ""))

# ---- Alt+Tab po aplikacich a polozky katalogu (test_luxos_windows.py) ----
call reset_fake()
cat = {}
for a in ls.catalog():
    cat[a["id"]] = a["values"]
end
call expect("catalog-app-windows", [cat["cycle-app"], cat["cycle-app-reverse"], cat["switch-app"]], [["cycle_app_windows_key"], ["cycle_reverse_app_windows_key"], ["switch_window_key"]])
call expect("format-grave", [ls.format_accel("<Alt>grave"), ls.format_accel("<Alt><Shift>grave")], ["Alt + `", "Alt + Shift + `"])
call expect("group-apps-default", ls.group_apps_enabled(), False)
call expect("group-apps-on", [ls.set_group_apps(True), ls.group_apps_enabled()], [True, True])
call expect("group-apps-off", [ls.set_group_apps(False), ls.group_apps_enabled()], [True, False])
call expect("group-apps-state", user_values(), {"/general/cycle_group_apps": "false"})
call expect("group-apps-call", ["-c", "xfwm4", "-p", "/general/cycle_group_apps", "-n", "-t", "bool", "-s", "false"] in writes(), True)

if failures > 0:
    exit(1)
end
