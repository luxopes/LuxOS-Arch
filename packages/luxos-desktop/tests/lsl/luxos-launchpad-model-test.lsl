# Test luxos_launchpad_model.lsl bez displeje (test_luxos_launchpad_wl.py): vypise radky "ok NAZEV" / "FAIL NAZEV ..."
load luxos_launchpad_model as model

failures = 0
NOW = 1800000000

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

function ids(found):
    return [e["id"] for e in found]
end

apps = [
    model.entry("org.gnome.Epiphany.desktop", {"name": "Prohlížeč", "c_name": "Web", "generic": "Webový prohlížeč",
        "c_generic": "Web Browser", "keywords": "web;internet;", "exec": "epiphany", "categories": "Network;GNOME;"}),
    model.entry("firefox.desktop", {"name": "Firefox", "c_name": "Firefox", "generic": "Webový prohlížeč",
        "c_generic": "Web Browser", "keywords": "internet;www;", "exec": "firefox", "categories": "Network;WebBrowser;"}),
    model.entry("luxos-terminal.desktop", {"name": "Terminál", "c_name": "Terminal", "generic": "Příkazová řádka",
        "keywords": "shell;prompt;command;", "exec": "luxos-terminal", "categories": "System;TerminalEmulator;"}),
    model.entry("luxos-text.desktop", {"name": "Textový editor", "c_name": "Text Editor", "exec": "luxos-text",
        "categories": "Utility;TextEditor;"}),
    model.entry("thunar.desktop", {"name": "Soubory", "c_name": "Files", "generic": "Správce souborů",
        "exec": "thunar", "categories": "System;FileManager;"}),
    model.entry("gimp.desktop", {"name": "GNU Image Manipulation Program", "generic": "Editor obrázků",
        "exec": "gimp-2.10", "categories": "Graphics;"}),
    model.entry("luxos-calculator.desktop", {"name": "Kalkulačka", "c_name": "Calculator", "exec": "luxos-calculator",
        "categories": "Utility;Calculator;"}),
    model.entry("org.kde.kate.desktop", {"name": "Kate", "generic": "Pokročilý textový editor", "exec": "kate",
        "categories": "Utility;TextEditor;"}),
    model.entry("noname.desktop", {"exec": "x"})
]

call expect("fold", model.fold("Příliš ŽLUŤOUČKÝ kůň úpěl ďábelské ódy ß"), "prilis zlutoucky kun upel dabelske ody ss")
call expect("noname", apps[8]["name"], "noname.desktop")
call expect("category-rank", [apps[0]["category"], apps[5]["category"], apps[2]["category"], apps[8]["category"]], [0, 2, 10, 11])

# diakritika: dotaz bez hacku najde nazev s hacky a naopak
call expect("czech-ascii", ids(model.search(apps, "prohlizec", {}, NOW))[0], "org.gnome.Epiphany.desktop")
call expect("czech-diacritics", ids(model.search(apps, "Prohlížeč", {}, NOW))[0], "org.gnome.Epiphany.desktop")
call expect("czech-upper", ids(model.search(apps, "KALKULACKA", {}, NOW)), ["luxos-calculator.desktop"])
# nazev pred popisem: "prohlizec" je jmeno Epiphany, Firefoxu jen popis
call expect("name-before-generic", ids(model.search(apps, "prohlizec", {}, NOW)), ["org.gnome.Epiphany.desktop", "firefox.desktop"])
# nelokalizovany nazev, klicova slova, program, id
call expect("c-name", ids(model.search(apps, "calc", {}, NOW))[0], "luxos-calculator.desktop")
call expect("keyword", ids(model.search(apps, "shell", {}, NOW)), ["luxos-terminal.desktop"])
call expect("exec", ids(model.search(apps, "gimp", {}, NOW))[0], "gimp.desktop")
call expect("id", ids(model.search(apps, "epiphany", {}, NOW))[0], "org.gnome.Epiphany.desktop")
# prefix pred zacatkem slova pred vnitrkem
call expect("prefix-first", ids(model.search(apps, "te", {}, NOW))[0:2], ["luxos-terminal.desktop", "luxos-text.desktop"])
call expect("word-start", ids(model.search(apps, "editor", {}, NOW))[0], "luxos-text.desktop")
call expect("word-start-manip", ids(model.search(apps, "manip", {}, NOW)), ["gimp.desktop"])
# fuzzy: pismena po poradi s mezerami
call expect("fuzzy", ids(model.search(apps, "frfx", {}, NOW)), ["firefox.desktop"])
call expect("fuzzy-too-loose", ids(model.search(apps, "fx", {}, NOW)), ["firefox.desktop"])
call expect("fuzzy-single", ids(model.search(apps, "q", {}, NOW)), [])
# vic slov: kazde musi sedet
call expect("two-words", ids(model.search(apps, "text edit", {}, NOW)), ["luxos-text.desktop", "org.kde.kate.desktop"])
call expect("two-words-miss", ids(model.search(apps, "text zzz", {}, NOW)), [])
call expect("empty", ids(model.search(apps, "   ", {}, NOW)), [])
# pouzivani: stejne dobra shoda (popis "Webovy prohlizec") vyhraje casteji spoustena, slabou ale neprebije
usage = {"firefox.desktop": {"count": 30, "last": NOW - 100}}
call expect("boost-tie", ids(model.search(apps, "webovy", usage, NOW)), ["firefox.desktop", "org.gnome.Epiphany.desktop"])
call expect("boost-no-tie", ids(model.search(apps, "prohlizec", usage, NOW))[0], "org.gnome.Epiphany.desktop")

# razeni mrizky
usage = {"thunar.desktop": {"count": 5, "last": NOW - 50}, "gimp.desktop": {"count": 9, "last": NOW - 5000},
    "firefox.desktop": {"count": 5, "last": NOW - 10}, "gone.desktop": {"count": 99, "last": NOW}}
call expect("alpha", ids(model.order(apps, "alpha", usage))[0:4], ["firefox.desktop", "gimp.desktop", "luxos-calculator.desktop", "org.kde.kate.desktop"])
call expect("most", ids(model.order(apps, "most", usage))[0:4], ["gimp.desktop", "firefox.desktop", "thunar.desktop", "luxos-calculator.desktop"])
call expect("recent", ids(model.order(apps, "recent", usage))[0:4], ["firefox.desktop", "thunar.desktop", "gimp.desktop", "luxos-calculator.desktop"])
call expect("category", ids(model.order(apps, "category", usage))[0:3], ["firefox.desktop", "org.gnome.Epiphany.desktop", "gimp.desktop"])
call expect("order-all", len(model.order(apps, "most", usage)), len(apps))

# pocty spusteni: soubor launchpad-usage.json, poskozeny soubor, prevzeti z rofi
u = model.parse_usage("{\"version\": 1, \"apps\": {\"a.desktop\": {\"count\": 3, \"last\": 17}, \"bad\": 5}}")
call expect("usage-parse", u, {"a.desktop": {"count": 3, "last": 17}})
call expect("usage-broken", model.parse_usage("{not json"), None)
call expect("usage-wrong", model.parse_usage("[1, 2]"), None)
u = model.record(u, "b.desktop", NOW)
u = model.record(u, "a.desktop", NOW)
call expect("usage-record", [u["a.desktop"], u["b.desktop"]], [{"count": 4, "last": NOW}, {"count": 1, "last": NOW}])
call expect("usage-roundtrip", model.parse_usage(model.usage_text(u)), u)
call expect("rofi", model.parse_rofi_history("12 firefox.desktop\n0 luxos-launchpad-sentinel\nx bad\n0 thunar.desktop\n"),
    {"firefox.desktop": {"count": 12, "last": 0}, "thunar.desktop": {"count": 1, "last": 0}})
if failures > 0:
    exit(1)
end
