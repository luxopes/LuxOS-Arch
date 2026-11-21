# Test luxos_keyboard_model.lsl bez displeje (test_luxos_keyboard.py): radky "ok NAZEV" / "FAIL NAZEV ...".
# KBD_TEST_TMP = docasna slozka testu, KBD_TEST_RULES = skutecny evdev.lst (nepovinne).
load env
load luxos_glib as lglib
load luxos_keyboard_model as kb

failures = 0
TMP = env.get("KBD_TEST_TMP", "/nonexistent")

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

function same(text):
    return text
end

LOCALED = "# Written by systemd-localed(8), read by systemd-localed and Xorg. It's\n# probably wise not to edit this file manually. Use localectl(1) to\n# update this file.\nSection \"InputClass\"\n        Identifier \"system-keyboard\"\n        MatchIsKeyboard \"on\"\n        Option \"XkbLayout\" \"cz,us\"\n        Option \"XkbModel\" \"pc105\"\n        Option \"XkbVariant\" \"qwerty,\"\n        Option \"XkbOptions\" \"grp:alt_shift_toggle,compose:ralt\"\nEndSection\n"
OLD_INSTALLER = "Section \"InputClass\"\n    Identifier \"system-keyboard\"\n    MatchIsKeyboard \"on\"\n    Option \"XkbLayout\" \"de\"\n    Option \"XkbVariant\" \"\"\n    Option \"XkbOptions\" \"\"\nEndSection\n"
L = [["cz", "qwerty"], ["us", ""]]

# ---- Parse ----
cfg = kb.parse_conf(LOCALED)
call expect("localed-format", [cfg["layouts"], cfg["model"], cfg["options"]], [L, "pc105", ["grp:alt_shift_toggle", "compose:ralt"]])
cfg = kb.parse_conf(OLD_INSTALLER)
call expect("old-installer-format", [cfg["layouts"], cfg["options"]], [[["de", ""]], []])
call expect("fewer-variants", kb.from_strings("cz,us,de", "qwerty", "", "")["layouts"], [["cz", "qwerty"], ["us", ""], ["de", ""]])
cfg = kb.parse_vconsole("KEYMAP=cz-qwerty\nXKBLAYOUT=cz,us\nXKBVARIANT=\"qwerty,\"\nXKBOPTIONS=grp:caps_toggle\n")
call expect("vconsole", [cfg["layouts"], cfg["options"]], [L, ["grp:caps_toggle"]])
# vystup instalatoru (setup-chroot.sh, packages/luxos-installer/tests/test-keyboard.sh "multi")
cfg = kb.parse_conf("Section \"InputClass\"\n        Identifier \"system-keyboard\"\n        MatchIsKeyboard \"on\"\n        Option \"XkbLayout\" \"cz,us\"\n        Option \"XkbVariant\" \"qwerty,\"\n        Option \"XkbOptions\" \"grp:alt_shift_toggle\"\nEndSection\n")
call expect("installer-multi", [cfg["layouts"], cfg["options"]], [L, ["grp:alt_shift_toggle"]])

d = TMP + "/fallbacks"
call lglib.mkdir_p(d)
conf = d + "/00-keyboard.conf"
vcon = d + "/vconsole.conf"
call expect("fallback-nothing", kb.read_system(conf, vcon)["layouts"], [["us", ""]])
call writefile(vcon, "KEYMAP=sk-qwerty\nXKBLAYOUT=sk\nXKBVARIANT=qwerty\n")
call expect("fallback-vconsole", kb.read_system(conf, vcon)["layouts"], [["sk", "qwerty"]])
call writefile(conf, LOCALED)
call expect("fallback-conf", kb.read_system(conf, vcon)["layouts"], L)

# ---- Generate ----
call expect("strings", kb.xkb_strings(L), ["cz,us", "qwerty,"])
call expect("strings-one", kb.xkb_strings([["us", ""]]), ["us", ""])
for case in [[L, ["grp:alt_shift_toggle"], ""], [[["de", ""]], [], "pc105"], [[["cz", ""], ["us", ""], ["ua", "phonetic"], ["de", ""]], ["grp:caps_toggle", "compose:ralt"], ""]]:
    call expect("roundtrip-" + case[0][0][0] + String(len(case[0])), kb.parse_conf(kb.conf_text(case[0], case[1], case[2])), {"layouts": case[0], "model": case[2], "options": case[1]})
end
call expect("no-variant-line", kb.conf_text([["cz", ""], ["us", ""]], ["grp:alt_shift_toggle"], "").find("XkbVariant"), -1)
call expect("no-options-line", kb.conf_text([["cz", ""]], [], "").find("XkbOptions"), -1)
call expect("localectl", kb.localectl_cmd(L, ["grp:alt_shift_toggle"], "pc105"), ["localectl", "set-x11-keymap", "cz,us", "pc105", "qwerty,", "grp:alt_shift_toggle"])
call expect("localectl-us", kb.localectl_cmd([["us", ""]], [], ""), ["localectl", "set-x11-keymap", "us", "", "", ""])
call expect("setxkbmap", kb.setxkbmap_cmd(L, ["grp:ctrl_shift_toggle"]), ["setxkbmap", "-layout", "cz,us", "-variant", "qwerty,", "-option", "", "-option", "grp:ctrl_shift_toggle"])
argv = kb.setxkbmap_cmd([["us", ""]], [])
call expect("setxkbmap-clears", argv[len(argv) - 2:], ["-option", ""])

# validate: spatne hodnoty se do konfigurace X ani prikazove radky nedostanou
bad = [[[], []], [[["cz", ""], ["us", ""], ["de", ""], ["fr", ""], ["pl", ""]], []], [[["cz", ""], ["cz", ""]], []],
       [[["cz\"", ""]], []], [[["cz", "qw erty"]], []], [[["CZ", ""]], []], [[["cz", ""]], ["grp:alt shift"]],
       [[["cz", ""]], ["grp:x\""]], [[["cz\n", ""]], []], [[["cz", "qwerty\n"]], []], [[["cz", ""]], ["grp:caps_toggle\n"]]]
for i in range(len(bad)):
    call expect("invalid-" + String(i), kb.validate(bad[i][0], bad[i][1], "") != "", True)
end
models = ["pc105\n", "pc105\"\n        Option \"X\" \"y", None]
for i in range(len(models)):
    call expect("invalid-model-" + String(i), kb.validate([["cz", ""]], [], models[i]) != "", True)
end
call expect("model-line", kb.conf_text([["cz", ""]], [], "pc105").find("Option \"XkbModel\" \"pc105\"") >= 0, True)
call expect("valid", kb.validate([["cz", ""], ["cz", "qwerty"], ["us", ""], ["ua", "phonetic"]], ["grp:alt_shift_toggle"], ""), "")

call expect("switch-of", kb.switch_of(["compose:ralt", "grp:caps_toggle"]), "grp:caps_toggle")
call expect("switch-of-none", kb.switch_of(["compose:ralt"]), "")
call expect("with-switch", kb.with_switch(["grp:caps_toggle", "compose:ralt"], "grp:alt_shift_toggle"), ["grp:alt_shift_toggle", "compose:ralt"])
call expect("with-switch-none", kb.with_switch(["grp:caps_toggle", "compose:ralt"], ""), ["compose:ralt"])
# Super+Mezernik je v LuxOS Hledani - nesmi byt v nabidce
call expect("no-win-space", "grp:win_space_toggle" in [o[0] for o in kb.SWITCH_OPTIONS], False)
call expect("default-first", kb.SWITCH_OPTIONS[0], ["grp:shifts_toggle", "Both Shift keys"])
call expect("default-switch", kb.DEFAULT_SWITCH, "grp:shifts_toggle")
call expect("alt-shift-offered", ["grp:alt_shift_toggle", "Alt + Shift"] in kb.SWITCH_OPTIONS, True)

# ---- prevod stareho vychoziho prepinani ----
call expect("migrate-plain", kb.migrate_options("grp:alt_shift_toggle"), "grp:shifts_toggle")
call expect("migrate-middle", kb.migrate_options("terminate:ctrl_alt_bksp,grp:alt_shift_toggle,compose:ralt"), "terminate:ctrl_alt_bksp,grp:shifts_toggle,compose:ralt")
call expect("migrate-led", kb.migrate_options("grp:alt_shift_toggle,grp_led:scroll"), "grp:shifts_toggle,grp_led:scroll")
for keep in ["", "compose:ralt", "grp:ctrl_shift_toggle", "grp:shifts_toggle", "grp:caps_toggle,compose:ralt", "grp:alt_shift_toggle,grp:caps_toggle", "grp:alt_shift_toggle_bidir"]:
    call expect("migrate-keep " + keep, kb.migrate_options(keep), None)
end

counter = [0]

# [zmeneno, obsah conf, obsah vconsole, znacka existuje, conf, vconsole, znacka]
function migrate_files(conf_text, vc_text, marker_exists):
    counter[0] = counter[0] + 1
    folder = TMP + "/migrate" + String(counter[0])
    call lglib.mkdir_p(folder)
    c = folder + "/00-keyboard.conf"
    v = folder + "/vconsole.conf"
    marker = folder + "/lib/migrated"
    if conf_text != None:
        call writefile(c, conf_text)
        call kb.chmod(c, 420)
    end
    if vc_text != None:
        call writefile(v, vc_text)
    end
    if marker_exists:
        call lglib.mkdir_p(folder + "/lib")
        call writefile(marker, "")
    end
    changed = kb.migrate_default_switch(c, v, marker)
    return [changed, lglib.read_text(c) if exists(c) else None, lglib.read_text(v) if exists(v) else None, exists(marker), c, v, marker]
end

old = kb.conf_text(L, ["grp:alt_shift_toggle", "compose:ralt"], "pc105")
vc = "KEYMAP=cz-qwerty\nXKBLAYOUT=cz,us\nXKBMODEL=pc105\nXKBVARIANT=qwerty,\nXKBOPTIONS=grp:alt_shift_toggle,compose:ralt\n"
r = migrate_files(old, vc, False)
call expect("migrate-old-default", [r[0], r[1], r[2], r[3]], [True, old.replace("grp:alt_shift_toggle", "grp:shifts_toggle"), vc.replace("grp:alt_shift_toggle", "grp:shifts_toggle"), True])
call expect("migrate-mode", kb.file_mode(r[4]), 420)
cfg = kb.read_system(r[4], r[5])
call expect("migrate-read", [cfg["options"], cfg["layouts"], cfg["model"]], [["grp:shifts_toggle", "compose:ralt"], L, "pc105"])
call expect("migrate-no-tmp", exists(r[4] + ".luxos-new"), False)
call expect("migrate-marker-text", lglib.read_text(r[6]), "grp:shifts_toggle\n")
# podruhe (znacka existuje) uz nic - ani kdyz si uzivatel Alt+Shift pozdeji vybere znovu
call writefile(r[4], old)
call expect("migrate-second", kb.migrate_default_switch(r[4], r[5], r[6]), False)
call expect("migrate-second-same", lglib.read_text(r[4]), old)

old = kb.conf_text([["de", ""], ["us", ""]], ["grp:alt_shift_toggle"], "")
r = migrate_files(old, "KEYMAP=de\nXKBOPTIONS=\"grp:alt_shift_toggle\"\n", False)
call expect("migrate-quoted", [r[0], r[1].find("Option \"XkbOptions\" \"grp:shifts_toggle\"") >= 0, r[2]], [True, True, "KEYMAP=de\nXKBOPTIONS=\"grp:shifts_toggle\"\n"])

for opts in [["grp:ctrl_shift_toggle"], [], ["compose:ralt"], ["grp:caps_toggle", "compose:ralt"]]:
    content = kb.conf_text([["cz", ""], ["us", ""]], opts, "")
    r = migrate_files(content, None, False)
    call expect("migrate-keeps " + String(opts), [r[0], r[1], r[3]], [False, content, True])
end
call expect("migrate-keeps-marker-text", lglib.read_text(r[6]), "unchanged\n")

# instalace jeste rozlozeni nezapsala: nic, ani znacka (zkusi se pri dalsi aktualizaci)
r = migrate_files(None, None, False)
call expect("migrate-without-config", [r[0], r[1], r[3]], [False, None, False])

old = kb.conf_text([["cz", ""], ["us", ""]], ["grp:alt_shift_toggle"], "")
r = migrate_files(old, None, True)
call expect("migrate-marker-blocks", [r[0], r[1]], [False, old])

# ---- Catalog ----
rules = TMP + "/fake.lst"
call writefile(rules, "! model\n  pc105  Generic 105-key PC\n\n! layout\n  us   English (US)\n  cz   Czech\n  ara  Arabic\n\n! variant\n  qwerty  cz: Czech (QWERTY)\n  phonetic ua: Ukrainian (phonetic)\n\n! option\n  grp:alt_shift_toggle  Alt+Shift\n")
cat = kb.catalog(rules)
keys = [item[0][0] + ":" + item[0][1] for item in cat]
call expect("catalog-common-first", keys[0], "us:")
call expect("catalog-no-dups", len(keys), len(set(keys)))
call expect("catalog-ara", "ara:" in keys, True)
call expect("catalog-variant", "ua:phonetic" in keys, True)
call expect("catalog-no-options", "grp:alt_shift_toggle:" in keys, False)
call expect("describe-variant", kb.describe(["ua", "phonetic"], cat, same), "Ukrainian (phonetic)")
call expect("describe-common", kb.describe(["cz", "qwerty"], cat, same), "Czech (QWERTY)")
call expect("describe-unknown", kb.describe(["xx", "yy"], [], same), "xx (yy)")
call expect("short", kb.short(["cz", "qwerty"]), "CZ qwerty")

real = env.get("KBD_TEST_RULES", "")
if real != "" and exists(real):
    cat = kb.catalog(real)
    call expect("real-rules-count", len(cat) > 300, True)
    bad_keys = [item[0] for item in cat if kb.validate([item[0]], [], "") != ""]
    call expect("real-rules-valid", bad_keys, [])
    # razeni podle popisu (male pismena)
    rest = [item[1].lower() for item in cat[len(kb.COMMON):]]
    call expect("real-rules-sorted", rest == sorted(rest), True)
end

if failures > 0:
    exit(1)
end
