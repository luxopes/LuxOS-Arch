# LuxOS - Nastaveni > Okna a plochy: pocet ploch, prechod za posledni plochu, animace prepnuti a dvojklik na
# zahlavi. Nahrazuje xfwm4-settings, xfwm4-tweaks-settings a xfwm4-workspace-settings.
# Wayland: ~/.config/luxwm/luxwm.conf (workspaces, wrap_workspaces, slide_ms, double_click_action), luxwm ho
# hned nacte. X11: kanal xfwm4 (xfconf-query, xfwm4 zmenu hned pouzije), navic prichytavani a zamereni oken,
# ktere luxwm nema. Rozlozeni tlacitek zahlavi LuxOS nenabizi (semafor vlevo jako v macOS).
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_text as text
load luxos_look as look
load luxos_settings_ui as ui

XFWM = "xfwm4"
MAX_WORKSPACES = 8

function number(value, fallback):
    if text.is_digits(value):
        return Int(value)
    end
    return fallback
end

function workspace_options():
    return [[String(n), String(n)] for n in range(1, MAX_WORKSPACES + 1)]
end

function click_options(x11):
    out = [["maximize", i18n.T("Zoom (maximize)")], ["hide", i18n.T("Minimize")]]
    if x11:
        out.append(["shade", i18n.T("Roll up")])
        out.append(["fill", i18n.T("Fill free space")])
    end
    out.append(["none", i18n.T("Do nothing")])
    return out
end

function motion_reduced():
    return look.channel("xsettings").get("/Gtk/EnableAnimations", "true") == "false"
end

function animation_hint():
    if motion_reduced():
        return i18n.T("Off while Reduce motion is on in Accessibility.")
    end
    return ""
end

# ---- Wayland (luxwm) ---------------------------------------------------------------------------------------

function on_wm(key, value):
    return look.wm_save({key: value})
end

function on_wm_switch(key, on):
    return look.wm_save({key: "yes" if on else "no"})
end

# Vypnuto = slide_ms 0, zapnuto = vychozi delka z /usr/share/luxwm/luxwm.conf (polozka uzivatele se smaze)
function on_wm_slide(unused, on):
    return look.wm_save({"slide_ms": None if on else "0"})
end

function build_wayland(page):
    conf = look.wm_conf()
    g = ui.group(page, i18n.T("Workspaces"))
    call ui.row(g, i18n.T("Number of workspaces"), "",
                ui.combo(workspace_options(), String(number(conf.get("workspaces", ""), 4)), "%s", on_wm, "workspaces"))
    call ui.row(g, i18n.T("Go from the last workspace to the first"),
                i18n.T("Switching past the last workspace with the keyboard continues at the first one."),
                ui.switch(conf.get("wrap_workspaces", "no") == "yes", on_wm_switch, "wrap_workspaces"))
    slide = ui.switch(conf.get("slide_ms", "") != "0", on_wm_slide, 0)
    call ui.row(g, i18n.T("Animate switching workspaces"), animation_hint(), slide)
    call gtk.widget_set_sensitive(slide, not motion_reduced())
    g = ui.group(page, i18n.T("Windows"))
    call ui.row(g, i18n.T("Double-click a title bar to"), "",
                ui.combo(click_options(False), conf.get("double_click_action", "maximize"), "", on_wm, "double_click_action"))
    return 0
end

# ---- X11 (xfwm4) -------------------------------------------------------------------------------------------

function on_xf(prop, value):
    if text.is_digits(value):
        return look.xf_set(XFWM, prop, "int", value)
    end
    return look.xf_set(XFWM, prop, "string", value)
end

function on_xf_switch(prop, on):
    return look.xf_set(XFWM, prop, "bool", "true" if on else "false")
end

# click_to_focus = true je vychozi; prepinac rika opak ("zamereni sleduje mys")
function on_follow_mouse(unused, on):
    return look.xf_set(XFWM, "/general/click_to_focus", "bool", "false" if on else "true")
end

function xf_switch(xf, prop, default):
    return ui.switch(xf.get(prop, default) == "true", on_xf_switch, prop)
end

function build_x11(page):
    xf = look.channel(XFWM)
    g = ui.group(page, i18n.T("Workspaces"))
    call ui.row(g, i18n.T("Number of workspaces"), "",
                ui.combo(workspace_options(), String(number(xf.get("/general/workspace_count", ""), 2)), "%s", on_xf, "/general/workspace_count"))
    call ui.row(g, i18n.T("Go from the last workspace to the first"),
                i18n.T("Switching past the last workspace with the keyboard continues at the first one."),
                xf_switch(xf, "/general/wrap_cycle", "true"))
    slide = xf_switch(xf, "/general/workspace_slide", "true")
    call ui.row(g, i18n.T("Animate switching workspaces"), animation_hint(), slide)
    call gtk.widget_set_sensitive(slide, not motion_reduced())
    g = ui.group(page, i18n.T("Windows"))
    call ui.row(g, i18n.T("Double-click a title bar to"), "",
                ui.combo(click_options(True), xf.get("/general/double_click_action", "maximize"), "", on_xf, "/general/double_click_action"))
    call ui.row(g, i18n.T("Snap windows to screen edges"), "", xf_switch(xf, "/general/snap_to_border", "true"))
    call ui.row(g, i18n.T("Snap windows to other windows"), "", xf_switch(xf, "/general/snap_to_windows", "false"))
    call ui.row(g, i18n.T("Tile windows dragged to a screen edge"), "", xf_switch(xf, "/general/tile_on_move", "true"))
    call ui.row(g, i18n.T("Focus follows the pointer"), i18n.T("A window is focused when the pointer moves over it, without a click."),
                ui.switch(xf.get("/general/click_to_focus", "true") == "false", on_follow_mouse, 0))
    return 0
end

function build(host):
    page = ui.page_box()
    if ui.wayland():
        call build_wayland(page)
    else:
        call build_x11(page)
    end
    return page
end

function test(command, rest):
    return False
end
