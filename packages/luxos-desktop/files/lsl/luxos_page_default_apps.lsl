# LuxOS - Nastaveni > stranka (rozpracovano): luxos_page_default_apps
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_settings_ui as ui

function build(host):
    page = ui.page_box()
    call gtk.box_pack_start(page, ui.label(i18n.T("This page could not be opened."), "hint"), False, False, 0)
    return page
end

function test(command, rest):
    return False
end
