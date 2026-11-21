# Test luxos_whats_new.lsl bez displeje (test_luxos_whats_new.py): radky "ok NAZEV" / "FAIL NAZEV ...";
# argumenty: slozka s novinkami luxos-branding, docasna slozka
load luxos_whats_new as wn
load luxos_glib, glib as glib

failures = 0

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

notes_dir = args[1]
tmp = args[2]
notes = wn.load_notes(notes_dir)
# po aktualizaci 1.0.0 -> 1.0.1 jen 1.0.1; po zobrazeni (mark_seen) uz nic
call expect("pending-101", wn.pending(notes, "1.0.0", "1.0.1"), ["1.0.1"])
call expect("pending-0912", wn.pending(notes, "0.9.12", "1.0.1"), ["1.0.1", "1.0.0"])
call expect("pending-seen", wn.pending(notes, "1.0.1", "1.0.1"), [])
call expect("pending-102", wn.pending(notes, "1.0.0", "1.0.2"), ["1.0.2", "1.0.1"])
call expect("pending-103", wn.pending(notes, "1.0.1", "1.0.3"), ["1.0.3", "1.0.2"])
call expect("pending-new-user", len(wn.pending(notes, "", "1.0.1")) >= 2, True)
call expect("version-order", [wn.newer("1.0.10", "1.0.9"), wn.newer("0.9.9", "0.9.10"), wn.compare("1.0", "1.0")], [True, False, 0])
call expect("by-version", wn.by_version(["0.9.9", "1.0.10", "0.9.10", "1.0.2"]), ["1.0.10", "1.0.2", "0.9.10", "0.9.9"])

# chybne soubory a bez polozek se preskoci, verze z nazvu souboru
call glib.mkdir_p(tmp + "/notes")
call glib.write_atomic(tmp + "/notes/2.0.json", "{\"items\": [{\"title\": {\"en\": \"A\"}}]}")
call glib.write_atomic(tmp + "/notes/2.1.json", "{broken")
call glib.write_atomic(tmp + "/notes/2.2.json", "{\"version\": \"2.2\", \"items\": []}")
call expect("load-skip", sorted(wn.load_notes(tmp + "/notes").keys()), ["2.0"])

call expect("tr-lang", wn.tr({"en": "Hello", "cs": "Ahoj"}, ["cs_CZ", "cs", "en"]), "Ahoj")
call expect("tr-fallback-en", wn.tr({"en": "Hello", "cs": "Ahoj"}, ["sv_SE", "sv", "en"]), "Hello")
call expect("tr-first", wn.tr({"de": "Hallo"}, ["sv", "en"]), "Hallo")
call expect("tr-text", wn.tr("plain", ["cs"]), "plain")

# symbolicke ikony: barevna ikona aplikace pod nazvem -symbolic (odkaz) se odmitne
call glib.write_atomic(tmp + "/a-symbolic.svg", "<svg><path fill=\"#363636\"/></svg>")
call expect("symbolic-real", wn.symbolic_file_ok(tmp + "/a-symbolic.svg"), True)
call glib.write_atomic(tmp + "/preferences-system-search.svg", "<svg><defs><linearGradient id=\"g\"/></defs></svg>")
call glib.write_atomic(tmp + "/view-grid.svg", "<svg><path fill=\"currentColor\"/></svg>")
call expect("symbolic-missing", [wn.symbolic_file_ok(""), wn.symbolic_file_ok(tmp + "/nope-symbolic.png")], [False, False])
call expect("symbolic-colour", wn.symbolic_file_ok(tmp + "/preferences-system-search.svg"), False)
call expect("symbolic-mono", wn.symbolic_file_ok(tmp + "/view-grid.svg"), True)
if exists(tmp + "/mark-location-symbolic.svg"):
    call expect("symbolic-link-colour", wn.symbolic_file_ok(tmp + "/mark-location-symbolic.svg"), False)
    call expect("symbolic-link-mono", wn.symbolic_file_ok(tmp + "/view-grid-symbolic.svg"), True)
end

call glib.write_atomic(tmp + "/version", "NAME=LuxOS\nVERSION=\"1.0.4\"\n")
call expect("version", wn.current_version(tmp + "/version"), "1.0.4")
call wn.mark_seen(tmp + "/cfg/luxos/whats-new-seen", "1.0.4")
call expect("seen", wn.read_seen(tmp + "/cfg/luxos/whats-new-seen"), "1.0.4")

if failures > 0:
    exit(1)
end
