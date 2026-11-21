# LuxOS - Nastaveni > Vymenitelne disky (drive thunar-volman-settings): co se stane po zasunuti USB disku, karty
# nebo disku CD/DVD a po pripojeni fotoaparatu ci telefonu.
# Kanal xfconf thunar-volman v obou relacich: na X11 ho cte thunar-volman (spousti ho Thunar --daemon z relace Xfce),
# zapis pres xfconf-query; na Waylandu pripojuje luxos-backdrop (luxos_automount.lsl) a xfconfd nebezi, okno cte
# a zapisuje primo soubor kanalu (luxos_xfconf) jako stranka Zamceni obrazovky.
# Fotoaparaty, telefony a zvukova CD jen na X11 (prikazy thunar-volman); na Waylandu se ukazi v Souborech (gvfs).
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_xfconf as xfconf
load luxos_settings_ui as ui

CH = "thunar-volman"

app = {"conf": {}}

function conf_get(prop):
    if ui.wayland():
        return app["conf"].get(prop, "false") == "true"
    end
    return ui.run(["xfconf-query", "-c", CH, "-p", prop]) == "true"
end

function on_switch(prop, on):
    value = "true" if on else "false"
    if ui.wayland():
        app["conf"][prop] = value
        return xfconf.write(CH, {prop: ["bool", value]})
    end
    return ui.run(["xfconf-query", "-c", CH, "-p", prop, "-n", "-t", "bool", "-s", value])
end

function on_drives(unused, on):
    call on_switch("/automount-drives/enabled", on)
    call gtk.widget_set_sensitive(app["browse"], on or conf_get("/automount-media/enabled"))
    return 0
end

function on_media(unused, on):
    call on_switch("/automount-media/enabled", on)
    call gtk.widget_set_sensitive(app["browse"], on or conf_get("/automount-drives/enabled"))
    return 0
end

function build(host):
    if ui.wayland():
        app["conf"] = xfconf.channel(CH)
    end
    page = ui.page_box()
    g = ui.group(page, i18n.T("When a Drive Is Connected"))
    drives = conf_get("/automount-drives/enabled")
    media = conf_get("/automount-media/enabled")
    call ui.row(g, i18n.T("Mount USB drives and memory cards"), i18n.T("Files on the drive are ready right away, without clicking it in Files."),
                ui.switch(drives, on_drives, 0))
    call ui.row(g, i18n.T("Mount inserted CDs and DVDs"), "", ui.switch(media, on_media, 0))
    app["browse"] = ui.switch(conf_get("/autobrowse/enabled"), on_switch, "/autobrowse/enabled")
    call ui.row(g, i18n.T("Open a window with the drive's files"), "", app["browse"])
    call gtk.widget_set_sensitive(app["browse"], drives or media)
    if not ui.wayland():
        g = ui.group(page, i18n.T("Cameras and Phones"))
        call ui.row(g, i18n.T("Import photos when a camera is connected"), "",
                    ui.switch(conf_get("/autophoto/enabled"), on_switch, "/autophoto/enabled"))
        call ui.row(g, i18n.T("Play audio CDs when inserted"), "",
                    ui.switch(conf_get("/autoplay-audio-cds/enabled"), on_switch, "/autoplay-audio-cds/enabled"))
    end
    note = ui.label(i18n.T("Internal disks are never mounted automatically. Programs on a drive never start by themselves."), "hint")
    call gtk.widget_set_margins(note, 16, 16, 8, 0)
    call gtk.box_pack_start(page, note, False, False, 0)
    return page
end

function test(command, rest):
    return False
end
