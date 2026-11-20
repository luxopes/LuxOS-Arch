# Test luxos_dock_model.lsl bez displeje (test_luxos_dock.py): vypise radky "ok NAZEV" / "FAIL NAZEV ..."
load luxos_dock_model as model

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

# nastaveni: vychozi hodnoty, meze, neplatny rezim, zpet do textu
conf = model.parse_conf("")
call expect("defaults-items", conf["items"], model.DEFAULT_ITEMS)
call expect("defaults-zoom", [conf["icon_size"], conf["zoom"], conf["hide"]], [48, 150, "dodge"])
conf = model.parse_conf("ITEMS=\"a.desktop  /opt/b.desktop trash\"\nICON_SIZE=500\nZOOM=abc\nHIDE=bogus\n")
call expect("parse-items", conf["items"], ["a.desktop", "/opt/b.desktop", "trash"])
call expect("parse-clamp", [conf["icon_size"], conf["zoom"], conf["hide"]], [128, 150, "dodge"])
conf["hide"] = "autohide"
again = model.parse_conf(model.conf_text(conf))
call expect("roundtrip", [again["items"], again["icon_size"], again["zoom"], again["hide"]], [conf["items"], 128, 150, "autohide"])
call expect("empty-items", model.parse_conf("ITEMS=\"\"")["items"], [])

# Plank
call expect("launcher", model.dockitem_launcher("[PlankDockItemPreferences]\nLauncher=file:///usr/share/applications/firefox.desktop\n"), "file:///usr/share/applications/firefox.desktop")
call expect("item-file", model.item_for_launcher("file:///usr/share/applications/firefox.desktop"), "/usr/share/applications/firefox.desktop")
call expect("item-trash", model.item_for_launcher("docklet://trash"), "trash")
call expect("item-other", model.item_for_launcher("docklet://clock"), "")
call expect("order", model.plank_order("['b.dockitem', 'x.dockitem', 'a.dockitem']", ["a.dockitem", "b.dockitem", "d.dockitem", "c.dockitem"]), ["b.dockitem", "a.dockitem", "c.dockitem", "d.dockitem"])
call expect("order-empty", model.plank_order("", ["b.dockitem", "a.dockitem"]), ["a.dockitem", "b.dockitem"])
call expect("hide", [model.plank_hide("'none'"), model.plank_hide("'intellihide'"), model.plank_hide("'auto'"), model.plank_hide("")], ["none", "dodge", "autohide", "dodge"])

# rozlozeni: bez zvetseni presne mrizka, se zvetsenim ikona pod mysi = zoom, panel roste symetricky
lay = model.layout(5, 48, 8, 10, 150, 0.0, 100, 0)
call expect("flat-width", Int(lay[3]), model.panel_width(5, 48, 8, 10))
call expect("flat-lefts", [Int(lay[0][0]), Int(lay[0][4])], [10, 10 + 4 * 56])
mid = 10 + 2 * 56 + 24
lay = model.layout(5, 48, 8, 10, 150, 1.0, mid, 0)
call expect("zoom-center", Int(lay[1][2] + 0.5), 72)
call expect("zoom-symmetric", Int((lay[2] + lay[3] / 2.0) * 10.0 + 0.5), mid * 10)
call expect("zoom-under-mouse", model.item_at(lay, 8, mid), 2)
call expect("zoom-neighbour", Int(lay[1][1] + 0.5) > 48 and Int(lay[1][1] + 0.5) < 72, True)
call expect("zoom-far", Int(lay[1][0] + 0.5) < Int(lay[1][1] + 0.5), True)
half = model.layout(5, 48, 8, 10, 150, 0.5, mid, 0)
call expect("zoom-progress", Int(half[1][2] + 0.5), 60)
# mys na levem okraji: panel roste jen doprava
edge = model.layout(5, 48, 8, 10, 150, 1.0, 0, 0)
call expect("zoom-left-edge", Int(edge[2]), 0)
extra = model.max_zoom_extra(5, 48, 8, 10, 150)
call expect("max-extra", extra >= Int(lay[3]) - model.panel_width(5, 48, 8, 10) and extra < 80, True)
call expect("no-zoom-extra", model.max_zoom_extra(5, 48, 8, 10, 100), 0)
call expect("item-gap", [model.item_at(model.layout(3, 48, 8, 10, 150, 0.0, 0, 0), 8, 5), model.item_at(model.layout(3, 48, 8, 10, 150, 0.0, 0, 0), 8, 200)], [-1, -1])

if failures > 0:
    exit(1)
end
print "all ok"
