# LuxOS - Nastaveni > Soukromi a zabezpeceni: prehled ochrany jako Zabezpeceni ve Windows na jednom miste.
#
# - Lux Guard: stav sluzby, antivirus (zapnout/vypnout pres pkexec luxos-guard set-antivirus), stari databaze viru,
#   kontrola slozky Stazene hned (luxos-guard scan, asynchronne, vysledek pod tlacitkem),
# - karantena (luxos-guard quarantine --json): soubory s virem, Obnovit / Smazat,
# - obnova souboru ze snimku domova (okno Lux Guard),
# - ochrana systemu (/usr jen pro cteni - LuxOS Care), brana firewall (odkaz na jeji stranku).
# Stav se cte z `luxos-guard status --json` (sluzba Lux Guard na soketu) pri kazdem zobrazeni stranky.
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_settings_ui as ui
load luxos_sys as lsys
load json

app = {"page": 0, "status": {}, "guard_row": 0, "av": 0, "db": 0, "scan": 0, "scan_result": 0, "q_group": 0,
       "snap": 0, "protect": 0, "note": 0, "busy": False}

function run_json(argv, default):
    out = ui.run(argv)
    if out == "":
        return default
    end
    data = default
    try:
        data = json.decode(out)
    else:
        return default
    end
    return data
end

function read_status():
    st = run_json(["luxos-guard", "status", "--json"], None)
    if type(st) != "Dictionary":
        st = {"active": False, "antivirus": False, "antivirus_conf": False, "quarantine": 0, "database": 0,
              "snapshots": 0, "newest_snapshot": 0}
    end
    app["status"] = st
    return st
end

function when(seconds):
    if seconds == None or seconds == 0:
        return i18n.T("never")
    end
    out = ui.run(["date", "-d", "@" + String(seconds), "+%Y-%m-%d %H:%M"])
    return out
end

function note(message):
    call gtk.label_set_text(app["note"], message)
    call gtk.widget_set_visible(app["note"], message != "")
    return 0
end

# ---- antivirus --------------------------------------------------------------------------------------------

function on_av_done(unused, output, status):
    app["busy"] = False
    if status != 0:
        call note(i18n.T("The change was not made (cancelled or not allowed)."))
    end
    call refresh()
    return 0
end

function on_av(unused, on):
    app["busy"] = True
    call note("")
    call glib.spawn_capture(["pkexec", "luxos-guard", "set-antivirus", "yes" if on else "no"], on_av_done, 0)
    return 0
end

function on_scan_done(unused, output, status):
    call gtk.widget_set_sensitive(app["scan"], True)
    found = 0
    for line in output.split("\n"):
        if line.strip().startswith("VIRUS") or line.strip().startswith(i18n.T("VIRUS: %s").split(":")[0]):
            found += 1
        end
    end
    if status == 0:
        message = i18n.T("No viruses found in Downloads.")
    elif found > 0:
        message = i18n.T("Viruses found and moved to quarantine: %d").replace("%d", String(found))
    else:
        message = i18n.T("Downloads checked. Some files are risky programs - Lux Guard asks before they run.")
    end
    call gtk.label_set_text(app["scan_result"], message)
    call gtk.widget_set_visible(app["scan_result"], True)
    call refresh()
    return 0
end

function on_scan(unused):
    call gtk.widget_set_sensitive(app["scan"], False)
    call gtk.label_set_text(app["scan_result"], i18n.T("Checking… The first check starts the antivirus and can take up to a minute."))
    call gtk.widget_set_visible(app["scan_result"], True)
    downloads = glib.user_special_dir(2)
    if downloads == "":
        downloads = glib.home_dir() + "/Downloads"
    end
    call glib.spawn_capture(["luxos-guard", "scan", downloads], on_scan_done, 0)
    return 0
end

# ---- karantena --------------------------------------------------------------------------------------------

function on_q_done(unused, output, status):
    if status != 0:
        call note(i18n.T("Not possible (unknown item, or a file with the same name exists)."))
    else:
        call note("")
    end
    call refresh()
    return 0
end

function on_restore(entry, button):
    call glib.spawn_capture(["luxos-guard", "quarantine", "restore", entry["id"]], on_q_done, 0)
    return 0
end

function on_delete(entry, button):
    call glib.spawn_capture(["luxos-guard", "quarantine", "delete", entry["id"]], on_q_done, 0)
    return 0
end

function fill_quarantine():
    g = app["q_group"]
    for child in gtk.container_get_children(g["box"]):
        call gtk.widget_destroy(child)
    end
    g["rows"] = 0
    entries = run_json(["luxos-guard", "quarantine", "--json"], [])
    if type(entries) != "List" or len(entries) == 0:
        call ui.row(g, i18n.T("Quarantine is empty."), i18n.T("Files with a virus are moved here."), 0)
    else:
        for e in entries:
            path = String(e.get("path", ""))
            name = path.split("/")[-1]
            box = gtk.box_new(gtk.HORIZONTAL, 6)
            restore = gtk.button_new(i18n.T("Restore"))
            call glib.connect_data(restore, "clicked", 0, on_restore, e)
            delete = gtk.button_new(i18n.T("Delete"))
            call gtk.widget_add_class(delete, "destructive-action")
            call glib.connect_data(delete, "clicked", 0, on_delete, e)
            call gtk.box_pack_start(box, restore, False, False, 0)
            call gtk.box_pack_start(box, delete, False, False, 0)
            call ui.row(g, name, String(e.get("signature", "")) + " · " + when(e.get("time", 0)), box)
        end
    end
    call gtk.widget_show_all(g["box"])
    return 0
end

# ---- ostatni ----------------------------------------------------------------------------------------------

function on_guard_window(unused):
    call ui.launch(["luxos-guard-gui"])
    return 0
end

function on_firewall(unused):
    call ui.launch(["luxos-settings", "firewall"])
    return 0
end

function usr_protected():
    return ui.run(["findmnt", "-no", "OPTIONS", "/usr"]).split(",")[0] == "ro"
end

function refresh():
    st = read_status()
    if st["active"]:
        call gtk.label_set_text(app["guard_row"], i18n.T("Active"))
    else:
        call gtk.label_set_text(app["guard_row"], i18n.T("Not running"))
    end
    ui.state["quiet"] = True
    call ui.switch_set(app["av"], st.get("antivirus_conf", False))
    ui.state["quiet"] = False
    call gtk.widget_set_sensitive(app["av"], not app["busy"])
    call gtk.label_set_text(app["db"], when(st.get("database", 0)))
    call gtk.widget_set_sensitive(app["scan"], st.get("antivirus", False))
    snaps = st.get("snapshots", 0)
    if snaps > 0:
        call gtk.label_set_text(app["snap"], i18n.T("%d snapshots, newest %s").replace("%d", String(snaps)).replace("%s", when(st.get("newest_snapshot", 0))))
    else:
        call gtk.label_set_text(app["snap"], i18n.T("No snapshots yet"))
    end
    call gtk.label_set_text(app["protect"], i18n.T("On") if usr_protected() else i18n.T("Off"))
    call fill_quarantine()
    return 0
end

function value_label():
    l = gtk.label_new("")
    call gtk.widget_add_class(l, "hint")
    return l
end

function build(host):
    page = ui.page_box()
    app["page"] = page
    g = ui.group(page, i18n.T("Virus & Threat Protection"))
    app["guard_row"] = value_label()
    call ui.row(g, "Lux Guard", i18n.T("Checks files and programs from downloads, attachments and USB drives."), app["guard_row"])
    app["av"] = ui.switch(False, on_av, 0)
    call ui.row(g, i18n.T("Antivirus"), i18n.T("ClamAV signatures; starts only when a file needs checking."), app["av"])
    app["db"] = value_label()
    call ui.row(g, i18n.T("Virus database updated"), i18n.T("Updated automatically every day."), app["db"])
    app["scan"] = gtk.button_new(i18n.T("Check Downloads Now"))
    call gtk.connect(app["scan"], "clicked", on_scan)
    call ui.row(g, i18n.T("Check for viruses"), i18n.T("Downloads, Desktop and Documents are also checked every week."), app["scan"])
    app["scan_result"] = ui.label("", "hint")
    call gtk.box_pack_start(page, app["scan_result"], False, False, 6)
    call gtk.widget_set_no_show_all(app["scan_result"], True)
    app["note"] = ui.label("", "")
    call gtk.box_pack_start(page, app["note"], False, False, 6)
    call gtk.widget_set_no_show_all(app["note"], True)

    app["q_group"] = ui.group(page, i18n.T("Quarantine"))

    g3 = ui.group(page, i18n.T("File Recovery"))
    app["snap"] = value_label()
    call ui.row(g3, i18n.T("Snapshots of your files"), i18n.T("Every hour - deleted or encrypted files can be restored."), app["snap"])
    open_guard = gtk.button_new(i18n.T("Restore Files…"))
    call gtk.connect(open_guard, "clicked", on_guard_window)
    call ui.row(g3, i18n.T("Lux Guard window"), i18n.T("Restore files, watched programs and recent decisions."), open_guard)

    g4 = ui.group(page, i18n.T("System"))
    app["protect"] = value_label()
    call ui.row(g4, i18n.T("System protection"), i18n.T("System files are read-only and checked every week."), app["protect"])
    fw = gtk.button_new(i18n.T("Firewall…"))
    call gtk.connect(fw, "clicked", on_firewall)
    call ui.row(g4, i18n.T("Firewall"), i18n.T("Blocks connections from the network you did not allow."), fw)
    call refresh()
    return page
end

function show(host):
    if app["page"] != 0 and not app["busy"]:
        call refresh()
    end
    return 0
end

function test(command, rest):
    return False
end
