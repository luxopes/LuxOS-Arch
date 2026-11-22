# LuxOS Control Center - rychle nastaveni z horni listy (jako v macOS); prepis luxos-control-center do LSL.
# Dlazdice: Wi-Fi (+ odkaz na QR kod site), Bluetooth, Nerusit, Tmavy rezim, Sporic dat, Sporic baterie; posuvniky jasu a hlasitosti;
# stav baterie; prave hrajici hudba (MPRIS); Obrazovky (Zrcadlit / Rozsirit / Jen externi) jen pri 2+ pripojenych
# monitorech - misto okna, ktere by vyskakovalo pri pripojeni. Okno se zavre pri ztrate fokusu nebo klavesou Esc.
# Na Waylandu je okno plocha layer-shell pod tlacitkem listy (luxos_hub_popup), bez jedineho volani X11,
# ve vzhledu Samsung One UI (ONEUI_CSS) a ovladatelne i klavesnici; X11 zustava u vzhledu verze 1.1.1.
# Wi-Fi a Bluetooth tam jako v Androidu: klik na bublinu s ikonou prepne, jinam na dlazdici otevre okno Wi-Fi
# z listy, resp. aplikaci Bluetooth.
#
#   call cc.create()      skryte okno se styly podle motivu (pouziva luxos-hub i samostatny program)
#   call cc.toggle()      ukaze/skryje okno (klik v liste)
#   cc.panel_text()       vystup pro plugin genmon (--panel)
# Stav drzi slovnik `cc` (zadne tridy: obsluhy signalu jsou funkce modulu s vazanymi daty).
load env, json
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_layer as layer
load luxos_mpris as mpris
load luxos_text as text
load luxos_wl as wl
load luxos_hub_popup as popup
load luxos_glass as glass
load luxos_luxwm as wm
load luxos_svg_icon as svg_icon

# Vzhled Ovladaciho centra verze 1.1.1 (luxos_cc.lsl na vetvi glass-ui): karta 18 px ze skla, dlazdice
# a sekce 14 px, posuvniky 22 px, odkazy dole jako text
CSS = ("window.cc { background: transparent; }\n"
    + ".cc-box { background-color: @cc_bg; border-radius: 18px; " + popup.card("cc") + " padding: 12px; color: @cc_fg; }\n"
    + ".cc-box.lx-wallglass, .cc-box.lg-panel { background-color: transparent; }\n"
    + ".tile { background-color: @cc_tile; border-radius: 14px; padding: 10px 12px; border: none; box-shadow: none; background-image: none; color: @cc_fg; }\n"
    + ".tile:hover { background-color: @cc_tile_hover; }\n"
    + ".tile .bubble { background-color: @cc_bubble; border-radius: 999px; min-width: 30px; min-height: 30px; color: @cc_fg; }\n"
    + ".tile.on .bubble { background-color: @cc_accent; color: white; }\n"
    + ".tile .title { font-weight: 600; font-size: 12px; }\n"
    + ".tile .title.long { font-size: 11px; }\n"
    + ".tile .sub { font-size: 11px; color: @cc_dim; }\n"
    + ".tile:disabled { opacity: 0.45; }\n"
    + ".tile.mode { padding: 8px 4px 6px 4px; }\n"
    + ".tile.mode .title { font-weight: 500; font-size: 11px; }\n"
    + ".section { background-color: @cc_tile; border-radius: 14px; padding: 10px 12px; }\n"
    + ".section .title { font-weight: 600; font-size: 12px; }\n"
    + ".section .sub { font-size: 11px; color: @cc_dim; }\n"
    + ".cc-box scale trough { min-height: 22px; border-radius: 11px; background-color: @cc_trough; border: none; }\n"
    + ".cc-box scale highlight { border-radius: 11px; background-color: @cc_fill; border: none; min-height: 22px; }\n"
    + ".cc-box scale slider { min-width: 22px; min-height: 22px; margin: 0; border-radius: 11px; background-color: white; border: none; box-shadow: 0 1px 3px rgba(0,0,0,0.35); }\n"
    + ".footer { background: none; border: none; box-shadow: none; color: @cc_fg; padding: 4px 6px; font-size: 12px; font-weight: 500; border-radius: 8px; }\n"
    + ".footer:hover { background-color: @cc_tile; }\n"
    + "button.plain { padding: 0; border: none; background: none; box-shadow: none; }\n"
    + ".art { border-radius: 9px; min-width: 42px; min-height: 42px; color: white; background-image: linear-gradient(135deg, #ff5f6d, #c445ff); }\n"
    + "button.media { padding: 4px; border: none; background: none; box-shadow: none; color: @cc_fg; border-radius: 999px; min-width: 30px; min-height: 30px; }\n"
    + "button.media:hover { background-color: @cc_tile_hover; }\n"
    + ".avatar { border-radius: 999px; min-width: 34px; min-height: 34px; font-weight: 800; color: white; background-image: linear-gradient(135deg, @cc_accent, #8b4dff); }\n")

# Wayland: vzhled Samsung One UI podle prototypu vlastnika (~/.local/share/luxos-control-center-preview, ui.py a
# drawing.py): rozmery, pisma, barvy a pruhlednosti z jeho kresby v meritku 0,8 (karta 432 -> 346 px, vejde se
# s baterii i obrazovkami pod listu na 1366x768). Pilulky jsou bile s pruhlednosti podle prototypu (alfa/0,15 * 0,28
# ve svetlem, * 0,10 v tmavem rezimu), bubliny vypnute bile 28 % / 10 %, zapnute plne bile s tmavou ikonou.
# Ikony jsou kresby prototypu (CC_ICONS, luxos_svg_icon), ne symbolicke ikony motivu.
ONEUI_RADIUS = 28
ONEUI_WIDTH = 346
ONEUI_CSS = (".oneui .cc-box { border-radius: " + String(ONEUI_RADIUS) + "px; padding: 0 16px 17.6px 16px; border: none; box-shadow: none; "
    + "background-image: linear-gradient(to bottom, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0)); color: @cc1_ink; }\n"
    + ".oneui label { color: @cc1_ink; }\n"
    + ".oneui .sub, .oneui .tile .sub, .oneui .section .sub { color: @cc1_dim; font-size: 9.2px; font-weight: 400; }\n"
    + ".oneui .head-row { margin-top: 14.4px; min-height: 28px; }\n"
    + ".oneui .head { font-size: 15.2px; font-weight: 600; padding-left: 1.6px; }\n"
    + ".oneui button.round { min-width: 28px; min-height: 28px; padding: 0; border-radius: 999px; border: none; box-shadow: none; background: none; }\n"
    + ".oneui button.round:hover { background-color: @cc1_pill_soft; }\n"
    + ".oneui .tile, .oneui .section, .oneui button.row { border-radius: 999px; border: 1px solid @cc1_edge; box-shadow: none; background-image: none; }\n"
    # ucet: pilulka 49,6 px, bile kolecko s pismenem (fotka profilu ho prekryje)
    + ".oneui .account { margin-top: 10.4px; }\n"
    + ".oneui .account .section { min-height: 47.6px; padding: 0 10.4px 0 10.2px; background-color: @cc1_pill_soft; }\n"
    + ".oneui .account .title { font-size: 12px; font-weight: 600; }\n"
    + ".oneui .avatar { min-width: 32px; min-height: 32px; border-radius: 999px; background-image: none; background-color: rgba(255, 255, 255, 0.92); "
    + "color: #3b4355; font-size: 18.4px; font-weight: 600; }\n"
    # dlazdice 152 x 56, bublina 35,2, nazev 11,2 px, popisek 9,2 px
    + ".oneui .tiles { margin-top: 10.4px; }\n"
    + ".oneui .tile { min-height: 54px; padding: 0 7px; background-color: @cc1_pill_toggle; }\n"
    + ".oneui .tile:hover { background-color: @cc1_pill_hover; }\n"
    + ".oneui .tile .title { font-size: 11.2px; font-weight: 600; }\n"
    + ".oneui .tile .title.long { font-size: 10.4px; }\n"
    + ".oneui .bubble { min-width: 35.2px; min-height: 35.2px; padding: 0; border: none; box-shadow: none; background-image: none; border-radius: 999px; background-color: @cc1_bubble; }\n"
    + ".oneui .bubble.on { background-color: rgba(255, 255, 255, 0.98); }\n"
    + ".oneui button.bubble:hover { background-color: @cc1_pill_hover; }\n"
    + ".oneui button.bubble.on:hover { background-color: rgba(255, 255, 255, 0.85); }\n"
    # sporice: jedna pilulka 63,2 px, dve poloviny s bublinou 33,6 px
    + ".oneui .savers { margin-top: 11.2px; min-height: 61.2px; padding: 0; background-color: @cc1_pill_row; }\n"
    + ".oneui .savers .tile { background: none; border: none; padding: 0 0 0 13.4px; min-height: 0; }\n"
    + ".oneui .savers .bubble { min-width: 33.6px; min-height: 33.6px; }\n"
    + ".oneui .savers .title { font-size: 10.4px; }\n"
    + ".oneui .savers .sub { font-size: 8.8px; }\n"
    # posuvniky 40 px (prototyp 39,2; cele pixely, jinak se vypln a kolecko lisi o radek), kulate tlacitko vedle stejne velke
    # prototyp: radek posuvniku konci 10,4 px pred okrajem obsahu
    + ".oneui .slider-row { margin-top: 11.2px; margin-right: 10.4px; }\n"
    + ".oneui .slider-row.first { margin-top: 12.8px; }\n"
    # Pilulka posuvniku je box kolem nej: GTK nosi stred kolecka po celem zlabu, vnitrni okraj boxu (pul kolecka)
    # drzi kolecko uvnitr pilulky (na 100 % by jinak prejelo pod kulate tlacitko vedle). Okraj na samotnem
    # posuvniku by GTK odecetl od drahy kolecka a klik by prestal odpovidat poloze. Levy okraj pilulky je vzdy
    # bily (kolecko na nule je tam taky), vypln a kolecko nepruhledne bile (One UI i v tmavem rezimu).
    + ".oneui .level { min-height: 40px; padding: 0 20px; border-radius: 20px; background-color: @cc1_pill_slider; "
    + "background-image: linear-gradient(to right, @cc1_fill 20px, transparent 20px); box-shadow: inset 0 0 0 1px @cc1_edge; }\n"
    + ".oneui scale { padding: 0; margin: 0; }\n"
    + ".oneui scale trough { min-height: 40px; border-radius: 0; background: none; border: none; box-shadow: none; }\n"
    + ".oneui scale highlight { min-height: 40px; border-radius: 0; background-color: @cc1_fill; border: none; }\n"
    + ".oneui scale slider { min-width: 40px; min-height: 40px; margin: 0; border-radius: 20px; background-color: @cc1_fill; background-image: none; border: none; box-shadow: none; }\n"
    # krouzek kolem kolecka jen kdyz GTK ukazuje fokus (focus-visible okna, jako obrys tlacitek), ne po kliknuti
    # mysi; GTK 3 nema :focus-visible, proto trida keynav
    + ".oneui.keynav scale:focus slider { box-shadow: 0 0 0 2px alpha(@cc_accent, 0.9); }\n"
    + ".oneui .level-icon { margin-left: 12px; }\n"
    + ".oneui button.side { min-width: 40px; min-height: 40px; padding: 0; border-radius: 999px; border: none; box-shadow: none; background-image: none; background-color: @cc1_bubble; }\n"
    + ".oneui button.side:hover { background-color: @cc1_pill_hover; }\n"
    + ".oneui button.side.on { background-color: rgba(255, 255, 255, 0.98); }\n"
    # radek QR 39,2 px, baterie 49,6 px s bilou bublinou
    + ".oneui button.row { margin-top: 12.8px; min-height: 37.2px; background-color: @cc1_pill_row; padding: 0 10.4px 0 12.8px; }\n"
    + ".oneui button.row:hover, .oneui button.plain:hover .section { background-color: @cc1_pill_hover; }\n"
    + ".oneui button.row label { font-size: 10.4px; font-weight: 500; }\n"
    + ".oneui .battery { margin-top: 12px; }\n"
    + ".oneui .battery .section { min-height: 47.6px; padding: 0 10.4px 0 9.4px; background-color: @cc1_pill_row; }\n"
    + ".oneui .battery .title { font-size: 12px; font-weight: 600; }\n"
    + ".oneui .section.media { margin-top: 12px; border-radius: 24px; padding: 8px 10.4px; background-color: @cc1_pill_row; }\n"
    + ".oneui .section.media .title { font-size: 11.2px; font-weight: 600; }\n"
    + ".oneui .art { min-width: 33.6px; min-height: 33.6px; border-radius: 8px; }\n"
    + ".oneui button.media { min-width: 28px; min-height: 28px; padding: 0; }\n"
    + ".oneui button.media:hover { background-color: @cc1_pill_hover; }\n"
    + ".oneui .section.screens { margin-top: 12px; border-radius: 24px; padding: 8px 10.4px 6px 10.4px; background-color: @cc1_pill_row; }\n"
    + ".oneui .section.screens .title { font-size: 11.2px; font-weight: 600; }\n"
    + ".oneui .tile.mode { border-radius: 16px; padding: 4px 4px 2px 4px; background: none; border: none; min-height: 0; }\n"
    + ".oneui .tile.mode:hover { background-color: @cc1_pill_hover; }\n"
    + ".oneui .tile.mode .title { font-size: 9.6px; font-weight: 500; }\n"
    + ".oneui .tile.mode .bubble { min-width: 30px; min-height: 30px; }\n"
    # zvoleny rezim obrazovek bila bublina jako zapnute dlazdice (ne modra z vzhledu X11)
    + ".oneui .tile.mode.on .bubble { background-color: rgba(255, 255, 255, 0.98); color: #343947; }\n"
    # dolni odkazy: pilulka 45,6 px, ikony 16 px, pismo 8 px
    + ".oneui .footbar { margin-top: 15.2px; min-height: 43.6px; background-color: @cc1_pill_soft; border: 1px solid @cc1_edge; border-radius: 999px; padding: 0 4px; }\n"
    + ".oneui .footbar .footer { padding: 4px 6px; border-radius: 999px; font-size: 8px; font-weight: 500; }\n"
    + ".oneui .footbar .footer:hover { background-color: @cc1_pill_hover; }\n"
    + ".oneui button:focus { outline: 2px solid alpha(@cc_accent, 0.9); outline-offset: 1px; -gtk-outline-radius: 999px; }\n"
    + ".oneui scale:focus, .oneui scale:focus trough { outline-width: 0; outline-style: none; }\n")

# Barvy prototypu: inkoust a popisky podle svetleho/tmaveho skla, pilulky bile s alfou podle typu radku
# (prototyp pill(alpha): alfa/0,15 * 0,28 ve svetlem, * 0,10 v tmavem rezimu), obrys 0,7 px
function oneui_colors(dark):
    base = 0.10 if dark else 0.28
    out = ""
    for item in [["toggle", 0.17], ["row", 0.16], ["soft", 0.12], ["slider", 0.23], ["hover", 0.25]]:
        out = out + "@define-color cc1_pill_" + item[0] + " rgba(255, 255, 255, " + String(item[1] / 0.15 * base) + ");\n"
    end
    out = out + "@define-color cc1_bubble rgba(255, 255, 255, " + String(base) + ");\n"
    out = out + "@define-color cc1_edge " + ("rgba(255, 255, 255, 0.06)" if dark else "rgba(25, 31, 43, 0.04)") + ";\n"
    # vypln posuvniku: prototyp ma bilou 91 % nad pilulkou; prekryvajici se kolecko by pruhlednou zdvojilo, proto plna
    out = out + "@define-color cc1_fill " + ("#efeff1" if dark else "#fdfdfd") + ";\n"
    out = out + "@define-color cc1_ink " + ("#ffffff" if dark else "#191f2b") + ";\n"
    out = out + "@define-color cc1_dim " + ("#edf0f5" if dark else "#353b47") + ";\n"
    return out
end

# Ikony prototypu (drawing.py ICONS + ui.py), kresba 24x24, cary 1,7 px; doplnene v jeho stylu: nocni svetlo
# (mesic s hvezdami, mesic samotny patri tmavemu rezimu jako v prototypu), Bluetooth nedostupne, Ethernet,
# napajeni a ovladani prehravace
CC_ICONS = {
    "wifi": "<path d=\"M3 8a14 14 0 0 1 18 0M6 11.5a9 9 0 0 1 12 0M9 15a4.5 4.5 0 0 1 6 0\"/><circle cx=\"12\" cy=\"19\" r=\"1\" fill=\"currentColor\" stroke=\"none\"/>",
    "ethernet": "<rect x=\"4\" y=\"8\" width=\"16\" height=\"10\" rx=\"2\"/><path d=\"M8 12v2m4-2v2m4-2v2M9 8V5h6v3\"/>",
    "bluetooth": "<path d=\"m7 7 10 10-5 4V3l5 4L7 17\"/>",
    "bluetooth-off": "<path d=\"m7 7 10 10-5 4V3l5 4L7 17\"/><path d=\"M4 4l16 16\"/>",
    "minus": "<path d=\"M21 12a9 9 0 1 1-18 0 9 9 0 1 1 18 0ZM8 11h8v2H8Z\" fill=\"currentColor\" fill-rule=\"evenodd\" stroke=\"none\"/>",
    "moon": "<path d=\"M20.5 15.7A9 9 0 0 1 8.3 3.5 9 9 0 1 0 20.5 15.7Z\" fill=\"currentColor\" stroke=\"none\"/>",
    "nightlight": "<path d=\"M18 16.4A7.6 7.6 0 0 1 7.6 6 7.6 7.6 0 1 0 18 16.4Z\" fill=\"currentColor\" stroke=\"none\"/>"
        + "<path d=\"M17 2.5l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9ZM21 9.5l.5 1.1 1.1.5-1.1.5-.5 1.1-.5-1.1-1.1-.5 1.1-.5Z\" fill=\"currentColor\" stroke=\"none\"/>",
    "data": "<path d=\"M4 19v-3M9 19v-7M14 19V8M19 19V3\" stroke-width=\"3.2\"/>",
    "battery": "<rect x=\"2\" y=\"6\" width=\"18\" height=\"12\" rx=\"2.5\"/><path d=\"M23 10v4\"/><path d=\"m11 8-4 5h4l-1 3 5-5h-4l1-3\" stroke-width=\"1.1\"/>",
    "batteryempty": "<rect x=\"2\" y=\"6\" width=\"18\" height=\"12\" rx=\"2.5\"/><path d=\"M23 10v4\"/>",
    "sun": "<circle cx=\"12\" cy=\"12\" r=\"4\" fill=\"currentColor\" stroke=\"none\"/><path d=\"M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5\"/>",
    "sound": "<path d=\"M4 9h4l5-4v14l-5-4H4Z\" fill=\"currentColor\" stroke=\"none\"/><path d=\"M16 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14\"/>",
    "muted": "<path d=\"M4 9h4l5-4v14l-5-4H4Z\" fill=\"currentColor\" stroke=\"none\"/><path d=\"m17 9 5 6m0-6-5 6\"/>",
    "chevron": "<path d=\"m9 4 8 8-8 8\"/>",
    "monitor": "<rect x=\"2\" y=\"3\" width=\"20\" height=\"14\" rx=\"2\"/><path d=\"M8 21h8m-4-4v4\"/>",
    "qr": "<rect x=\"3\" y=\"3\" width=\"6\" height=\"6\" rx=\"1.2\"/><rect x=\"15\" y=\"3\" width=\"6\" height=\"6\" rx=\"1.2\"/><rect x=\"3\" y=\"15\" width=\"6\" height=\"6\" rx=\"1.2\"/>"
        + "<path d=\"M15 14h2v3h4m-7 3v1m6-7v1m-3 6h1m3-3v3\"/>",
    "power": "<path d=\"M12 2v10m-6-7a9 9 0 1 0 12 0\"/>",
    # ozubene kolo: preferences-system-symbolic sady elementary jako v prototypu (16x16 -> 24x24)
    "settings": "<path transform=\"scale(1.5)\" fill=\"currentColor\" stroke=\"none\" d=\"M7 0C6.8 0 6.63.86 6.51 2.19a6 6 0 0 0-1.55.65C3.92 1.98 3.19 1.5 3.05 1.64L1.64 3.05c-.14.14.34.87 1.2 1.9a6 6 0 0 0-.64 1.56C.86 6.63 0 6.8 0 7v2c0 .2.86.37 2.19.49a6 6 0 0 0 .65 1.55c-.86 1.04-1.34 1.77-1.2 1.91l1.41 1.41c.14.14.87-.34 1.9-1.2a6 6 0 0 0 1.56.64C6.63 15.14 6.8 16 7 16h2c.2 0 .37-.86.49-2.19a6 6 0 0 0 1.55-.65c1.04.86 1.77 1.34 1.91 1.2l1.41-1.41c.14-.14-.35-.87-1.2-1.9a6 6 0 0 0 .64-1.56C15.14 9.37 16 9.2 16 9V7c0-.2-.86-.37-2.19-.49a6 6 0 0 0-.65-1.55c.86-1.04 1.34-1.77 1.2-1.91l-1.41-1.41c-.14-.14-.87.35-1.9 1.2a6 6 0 0 0-1.56-.64C9.37.86 9.2 0 9 0Zm1 4.75a3.25 3.25 0 1 1 0 6.5 3.25 3.25 0 0 1 0-6.5Z\"/>",
    "play": "<path d=\"M8 5v14l11-7Z\" fill=\"currentColor\" stroke=\"none\"/>",
    "pause": "<path d=\"M7 5h3.5v14H7ZM13.5 5H17v14h-3.5Z\" fill=\"currentColor\" stroke=\"none\"/>",
    "previous": "<path d=\"M18 6v12l-9-6ZM6 6v12\" fill=\"currentColor\"/>",
    "next": "<path d=\"M6 6v12l9-6ZM18 6v12\" fill=\"currentColor\"/>"
}

# Baterie prototypu (batteryfull): zelena vypln podle nabiti, pod 20 % cervena
function battery_glyph(level):
    width = max(1.5, 13.0 * Float(min(100, max(0, level))) / 100.0)
    fill = "#38c81c" if level >= 20 else "#ff3b30"
    return ("<rect x=\"1\" y=\"5\" width=\"19\" height=\"14\" rx=\"3\"/><path d=\"M23 9v6\"/><rect x=\"4\" y=\"8\" width=\""
        + String(width) + "\" height=\"8\" rx=\"1.2\" fill=\"" + fill + "\" stroke=\"none\"/>")
end

SIGUSR1 = 10
SIGUSR2 = 12

cc = {}            # stav okna (widgety a priznaky)
created = False

function config_dir():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.config"
    end
    return base + "/luxos"
end

# Relace na Waylandu: Nerusit drzi luxos-notify (cz.luxos.NotificationHistory), xfconf tam nebezi
function wayland():
    value = env.get("WAYLAND_DISPLAY", "")
    return value != None and value != ""
end

function soft_brightness_path():
    return config_dir() + "/brightness"
end

function panel_text():
    return "<icon>luxos-control-center-symbolic</icon><iconclick>luxos-cc-toggle</iconclick><tool>" + i18n.T("Control Center") + "</tool>"
end

# ---- stav systemu --------------------------------------------------------------------------------

# Uzivatel prihlaseneho uctu LuxAI nebo None (cte jen soubor, bez site)
function account_user():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.config"
    end
    raw = glib.read_text(base + "/luxai/account.json")
    if raw == "":
        return None
    end
    data = None
    try:
        data = json.decode(raw)
    else:
        data = None
    end
    if data == None or type(data) != "Dictionary":
        return None
    end
    token = data.get("sessionToken")
    if token == None or token == "":
        return None
    end
    user = data.get("user")
    if user == None or type(user) != "Dictionary":
        return {}
    end
    return user
end

# Adapter BlueZ pres D-Bus (bez bluetoothctl, ktery bez sluzby visi sekundy): [on nebo None, text]
function bluetooth_state():
    result = [None, i18n.T("Not available")]
    try:
        bus = gio.system_bus()
        if gio.name_has_owner(bus, "org.bluez", 500):
            on = gio.get_property_value(bus, "org.bluez", "/org/bluez/hci0", "org.bluez.Adapter1", "Powered") == True
            if on:
                result = [True, i18n.T("On")]
            else:
                result = [False, i18n.T("Off")]
            end
        end
    else:
        result = [None, i18n.T("Not available")]
    end
    return result
end

# Sporic dat/baterie: priznakovy soubor v ~/.config/luxos (bez spousteni skriptu)
function flag_state(name):
    return exists(config_dir() + "/" + name)
end

function dark_state():
    return glib.read_text(config_dir() + "/appearance").strip() == "dark"
end

function power_supply_dir():
    base = env.get("LUXOS_POWER_SUPPLY", "")
    if base == None or base == "":
        return "/sys/class/power_supply"
    end
    return base
end

function read_int(path):
    return text.to_int(glib.read_text(path), None)
end

# [kapacita %, stav, minuty do vybiti/nabiti nebo None] nebo None - stejny odhad jako luxos-battery
function battery():
    base = power_supply_dir()
    for name in glib.list_dir(base):
        if name.startswith("BAT"):
            cap = read_int(base + "/" + name + "/capacity")
            status = glib.read_text(base + "/" + name + "/status").strip()
            if cap == None or status == "":
                return None
            end
            return [cap, status, battery_minutes(base + "/" + name, status)]
        end
    end
    return None
end

function battery_minutes(bat, status):
    values = read_triplet(bat, "energy_now", "energy_full", "power_now")
    if values == None:
        values = read_triplet(bat, "charge_now", "charge_full", "current_now")
    end
    if values == None or values[2] <= 0:
        return None
    end
    now = values[0]
    full = values[1]
    rate = values[2]
    mins = 0
    if status == "Discharging":
        mins = now * 60 // rate
    elif status == "Charging" and full > now:
        mins = (full - now) * 60 // rate
    else:
        return None
    end
    if mins > 0 and mins < 6000:
        return mins
    end
    return None
end

function read_triplet(bat, a, b, c):
    out = []
    for name in [a, b, c]:
        value = read_int(bat + "/" + name)
        if value == None:
            return None
        end
        out.append(abs(value))
    end
    return out
end

function fmt_minutes(mins):
    if mins >= 60:
        return String(mins // 60) + " h " + String(mins % 60) + " min"
    end
    return String(mins) + " min"
end

# Cesta k podsviceni (notebook) nebo ""
function backlight():
    base = env.get("LUXOS_BACKLIGHT", "")
    if base == None or base == "":
        base = "/sys/class/backlight"
    end
    names = glib.list_dir(base)
    if len(names) == 0:
        return ""
    end
    return base + "/" + names[0]
end

# Jas v procentech: podsviceni, jinak softwarovy jas monitoru (X11, xrandr); None kdyz nejde zjistit
function brightness():
    bl = backlight()
    if bl != "":
        value = read_int(bl + "/brightness")
        maximum = read_int(bl + "/max_brightness")
        if value == None or maximum == None or maximum == 0:
            return None
        end
        return Int(Float(value * 100) / Float(maximum) + 0.5)
    end
    soft = read_int(soft_brightness_path())
    if soft == None:
        return 100
    end
    return soft
end

# ---- stavba UI --------------------------------------------------------------------------------------

function label(text_value, class_name, xalign):
    lab = gtk.label_new(text_value)
    call gtk.label_set_xalign(lab, xalign)
    if class_name != "":
        call gtk.widget_add_class(lab, class_name)
    end
    return lab
end

# Ovladaci prvky dostanou fokus klavesnice jen ve vzhledu One UI (Tab, sipky, Enter); na X11 zustava okno
# bez fokusu prvku jako dosud
function focusable(widget):
    call gtk.widget_set_can_focus(widget, cc["oneui"])
    return widget
end

# Dlazdice: {widget, button, bubble, image, title, sub, action, settings}. Se settings (Wi-Fi, Bluetooth na
# Waylandu) jako v Androidu: bublina s ikonou je vlastni tlacitko nad dlazdici (prepne), zbytek dlazdice otevre
# nastaveni - mysi, dotykem i klavesnici bez hledani mista stisku (dve zastavky Tab). Bublina lezi v GtkOverlay
# vedle tlacitka: uvnitr nej by udalosti dostalo vnejsi tlacitko (jeho okno udalosti je nad potomky) a Tab by do
# ni nevesel.
function tile_new(icon, title, action, settings):
    tile = {"action": action, "name": title, "settings": settings}
    button = focusable(gtk.button_new_empty())
    call gtk.widget_add_class(button, "tile")
    tile["widget"] = button
    box = gtk.box_new(gtk.HORIZONTAL, 9 if cc["oneui"] else 10)
    bubble = gtk.box_new(gtk.HORIZONTAL, 0)
    tile["spot"] = bubble
    if settings != None:
        overlay = gtk.overlay_new()
        call gtk.container_add(overlay, button)
        tile["widget"] = overlay
        # misto pro bublinu v dlazdici (velikost bubliny One UI)
        spot = gtk.box_new(gtk.HORIZONTAL, 0)
        call gtk.widget_set_size_request(spot, 35, 35)
        call gtk.box_pack_start(box, spot, False, False, 0)
        tile["spot"] = spot
        bubble = focusable(gtk.button_new_empty())
        call gtk.widget_set_tooltip(bubble, title)
        call gtk.connect_data(bubble, "clicked", 0, on_bubble_clicked, tile)
        call gtk.widget_set_margins(bubble, 8, 0, 0, 0)
        call gtk.widget_set_halign(bubble, gtk.ALIGN_START)
        call gtk.overlay_add_overlay(overlay, bubble)
    else:
        call gtk.widget_set_halign(bubble, gtk.ALIGN_CENTER)
        call gtk.box_pack_start(box, bubble, False, False, 0)
    end
    call gtk.widget_set_valign(bubble, gtk.ALIGN_CENTER)
    call gtk.widget_add_class(bubble, "bubble")
    # obrazek vyplni bublinu baleni, ne hexpand: ten by se rozsiril na celou bublinu v radku dlazdice,
    # bublina by dostala cast volneho mista a text kratkych nazvu by se posunul doprava
    image = oneui_icon(icon, 19.2)
    if settings != None:
        call gtk.container_add(bubble, image)
    else:
        call gtk.box_pack_start(bubble, image, True, True, 0)
    end
    column = text_column()
    # pevna sirka (okno se nerozsiri za okraj): delsi preklad mensim pismem ("Datensparmodus") a na dva
    # radky ("Economiseur de / batterie"), az pak se zkrati
    title_label = label(title, "title", 0)
    call gtk.label_set_line_wrap(title_label, True)
    call gtk.label_set_lines(title_label, 2)
    call gtk.label_set_ellipsize(title_label, gtk.ELLIPSIZE_END)
    call gtk.label_set_max_width_chars(title_label, 12)
    if len(title) > 12:
        # mensi pismo: na radek se vejde vic znaku ("Ne pas deranger" zustane na jednom)
        call gtk.widget_add_class(title_label, "long")
        call gtk.label_set_max_width_chars(title_label, 15)
    end
    call gtk.widget_set_tooltip(title_label, title)
    sub = label("", "sub", 0)
    call gtk.label_set_ellipsize(sub, gtk.ELLIPSIZE_END)
    call gtk.label_set_max_width_chars(sub, 12)
    call gtk.box_pack_start(column, title_label, False, False, 0)
    call gtk.box_pack_start(column, sub, False, False, 0)
    call gtk.box_pack_start(box, column, True, True, 0)
    call gtk.container_add(button, box)
    tile["box"] = box
    tile["button"] = button
    tile["image"] = image
    tile["title"] = title_label
    tile["sub"] = sub
    tile["bubble"] = bubble
    call gtk.connect_data(button, "clicked", 0, on_tile_clicked, tile)
    return tile
end

# Nazev a popisek pod sebou, svisle uprostred radku; One UI s mezerou prototypu (popisek 17,6 px pod nazvem)
# a o kousek vys
function text_column():
    column = gtk.box_new(gtk.VERTICAL, 4 if cc["oneui"] else 0)
    call gtk.widget_set_valign(column, gtk.ALIGN_CENTER)
    if cc["oneui"]:
        call gtk.widget_set_margins(column, 0, 0, 0, 3)
    end
    return column
end

# Ikona [nazev v motivu (X11), kresba prototypu (One UI)]; One UI v pixelech prototypu * 0,8
function oneui_icon(icon, size):
    if cc["oneui"]:
        return cc_icon(icon[1], size, "ink")
    end
    return gtk.image_new_from_icon_name(icon[0], gtk.ICON_MENU)
end

# Ikony prototypu: [obrazek, kresba, velikost, role]; role "ink" = inkoust skla, "on" = tmava na bile bubline
function cc_icon(name, size, role):
    image = gtk.image_new()
    item = [image, name, size, role]
    cc["icons"].append(item)
    call paint_icon(item)
    return image
end

function paint_icon(item):
    body = item[1]
    if not body.startswith("<"):
        body = CC_ICONS[body]
    end
    color = "#343947"
    if item[3] == "ink":
        color = "#ffffff" if cc["dark"] else "#191f2b"
    end
    call svg_icon.set(item[0], body, item[2], color, cc["scale"])
    return 0
end

# Jina kresba nebo role ikony (zapnuta bublina, ztlumeni, uroven baterie)
function set_icon(image, name, role):
    for item in cc["icons"]:
        if item[0] == image and (item[1] != name or item[3] != role):
            item[1] = name
            item[3] = role
            call paint_icon(item)
        end
    end
    return 0
end

function icon_name(image):
    for item in cc["icons"]:
        if item[0] == image:
            return item[1]
        end
    end
    return ""
end

# Prepnuti svetly/tmavy nebo jine HiDPI: vsechny ikony znovu
function paint_icons():
    for item in cc["icons"]:
        call paint_icon(item)
    end
    return 0
end

function on_bubble_clicked(tile, button):
    if tile.get("wired", False):
        return on_tile_clicked(tile, button)
    end
    call log_test("tile " + tile["name"] + " toggle")
    action = tile["action"]
    call action()
    return 0
end

function on_tile_clicked(tile, button):
    if tile["settings"] == None:
        return on_bubble_clicked(tile, button)
    end
    call log_test("tile " + tile["name"] + " settings")
    action = tile["settings"]
    call action()
    return 0
end

# on: True/False/None (None = vypnuto), sub: text nebo None (beze zmeny)
function tile_set_state(tile, on, sub):
    call gtk.widget_set_class(tile["button"], "on", on == True)
    call gtk.widget_set_class(tile["bubble"], "on", on == True)
    if cc["oneui"]:
        call set_icon(tile["image"], icon_name(tile["image"]), "on" if on == True else "ink")
    end
    if sub != None:
        call gtk.label_set_text(tile["sub"], sub)
    end
    return 0
end

function tile_is_on(tile):
    return gtk.widget_has_class(tile["button"], "on")
end

# Posuvnik s ikonou: {box, scale, icon, button, lock, on_change, on_icon, busy, want}
# on_change(hodnota) vraci prikaz (argv) k nastaveni hodnoty, nebo None; on_icon = klik na ikonu (One UI:
# kulate tlacitko vedle posuvniku s ikonou side_icon, ikona icon je uvnitr pilulky)
function slider_new(title, icon, on_change, on_icon, side_icon, tooltip):
    row = {"lock": False, "on_change": on_change, "on_icon": on_icon, "busy": False, "want": -1}
    if cc["oneui"]:
        return slider_new_oneui(row, icon, side_icon, tooltip)
    end
    if type(icon) == "List":
        icon = icon[0]
    end
    box = gtk.box_new(gtk.VERTICAL, 6)
    call gtk.widget_add_class(box, "section")
    call gtk.box_pack_start(box, label(title, "title", 0), False, False, 0)
    line = gtk.box_new(gtk.HORIZONTAL, 8)
    button = gtk.button_new_empty()
    call gtk.widget_set_can_focus(button, False)
    call gtk.button_set_relief(button, gtk.RELIEF_NONE)
    image = gtk.image_new_from_icon_name(icon, gtk.ICON_MENU)
    call gtk.container_add(button, image)
    call gtk.connect_data(button, "clicked", 0, on_slider_icon, row)
    scale = gtk.scale_new_with_range(gtk.HORIZONTAL, 0, 100, 1)
    call gtk.scale_set_draw_value(scale, False)
    call gtk.widget_set_hexpand(scale, True)
    call gtk.connect_data(scale, "value-changed", 0, on_slider_changed, row)
    call gtk.box_pack_start(line, button, False, False, 0)
    call gtk.box_pack_start(line, scale, True, True, 0)
    call gtk.box_pack_start(box, line, False, False, 0)
    row["box"] = box
    row["scale"] = scale
    row["icon"] = image
    row["button"] = button
    return row
end

function slider_new_oneui(row, icon, side_icon, tooltip):
    box = gtk.box_new(gtk.HORIZONTAL, 10)
    scale = focusable(gtk.scale_new_with_range(gtk.HORIZONTAL, 0, 100, 1))
    call gtk.scale_set_draw_value(scale, False)
    call gtk.range_set_increments(scale, 5, 10)
    call gtk.connect_data(scale, "value-changed", 0, on_slider_changed, row)
    pill = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_add_class(pill, "level")
    call gtk.box_pack_start(pill, scale, True, True, 0)
    overlay = gtk.overlay_new()
    call gtk.widget_set_hexpand(overlay, True)
    call gtk.container_add(overlay, pill)
    level = cc_icon(icon[1], 19.2, "on")
    call gtk.widget_add_class(level, "level-icon")
    call gtk.widget_set_halign(level, gtk.ALIGN_START)
    call gtk.widget_set_valign(level, gtk.ALIGN_CENTER)
    call gtk.overlay_add_overlay(overlay, level)
    call gtk.overlay_set_pass_through(overlay, level)
    button = focusable(gtk.button_new_empty())
    call gtk.widget_add_class(button, "side")
    call gtk.widget_set_valign(button, gtk.ALIGN_CENTER)
    call gtk.widget_set_tooltip(button, tooltip)
    image = oneui_icon(side_icon, 19.2)
    call gtk.container_add(button, image)
    call gtk.connect_data(button, "clicked", 0, on_slider_icon, row)
    call gtk.box_pack_start(box, overlay, True, True, 0)
    call gtk.box_pack_start(box, button, False, False, 0)
    row["box"] = box
    row["scale"] = scale
    row["icon"] = image
    row["button"] = button
    return row
end

function on_slider_icon(row, button):
    handler = row["on_icon"]
    if handler != None:
        call handler()
    end
    return 0
end

# Tazeni posuvnikem posle desitky zmen: bezi vzdy nejvys jeden prikaz (pactl, brightnessctl) a po jeho
# skonceni se nastavi posledni hodnota - jinak by se spoustely desitky procesu a dobehly v nahodnem
# poradi (zvuk by mohl zustat na nektere z mezilehlych hodnot)
function on_slider_changed(row, scale):
    if row["lock"]:
        return 0
    end
    row["want"] = gtk.range_get_value(scale)
    if not row["busy"]:
        call slider_apply(row)
    end
    return 0
end

function slider_apply(row):
    handler = row["on_change"]
    argv = handler(row["want"])
    row["want"] = -1
    if argv != None:
        row["busy"] = glib.spawn_watched_data(argv, on_slider_done, row) != 0
    end
    return 0
end

function on_slider_done(row, pid, status):
    row["busy"] = False
    if row["want"] >= 0:
        call slider_apply(row)
    end
    return 0
end

function slider_set_value(row, value):
    row["lock"] = True
    call gtk.range_set_value(row["scale"], value)
    row["lock"] = False
    return 0
end

# Odkaz dole -> [tlacitko, ikona, popisek] (ikona a popisek jen One UI)
function footer_button(box, title, command, icon):
    image = None
    name = None
    if cc["oneui"]:
        button = focusable(gtk.button_new_empty())
        line = gtk.box_new(gtk.HORIZONTAL, 6)
        call gtk.widget_set_halign(line, gtk.ALIGN_CENTER)
        image = cc_icon(icon[1], 16.0, "ink")
        call gtk.box_pack_start(line, image, False, False, 0)
        name = label(title.replace("…", ""), "", 0)
        call gtk.label_set_ellipsize(name, gtk.ELLIPSIZE_END)
        call gtk.box_pack_start(line, name, False, False, 0)
        call gtk.container_add(button, line)
        call gtk.widget_set_tooltip(button, title)
    else:
        button = focusable(gtk.button_new(title))
    end
    call gtk.widget_add_class(button, "footer")
    call gtk.connect_data(button, "clicked", 0, on_launch_clicked, command)
    call gtk.box_pack_start(box, button, False, False, 0)
    return [button, image, name]
end

# Spusti program a zavre okno
function on_launch_clicked(command, button):
    call glib.spawn_app(command.split(" "))
    call close()
    return 0
end

# Sipka na konci radku (prototyp 18 px)
function chevron():
    if cc["oneui"]:
        return cc_icon("chevron", 14.4, "ink")
    end
    return gtk.image_new_from_icon_name("go-next-symbolic", gtk.ICON_MENU)
end

function media_button(box, name, icon, size):
    button = focusable(gtk.button_new_empty())
    call gtk.widget_set_valign(button, gtk.ALIGN_CENTER)
    call gtk.widget_add_class(button, "media")
    if cc["oneui"]:
        call gtk.container_add(button, cc_icon(icon[1], 19.2 if name == "PlayPause" else 16.0, "ink"))
    else:
        call gtk.container_add(button, gtk.image_new_from_icon_name(icon[0], size))
    end
    call gtk.connect_data(button, "clicked", 0, on_media_clicked, name)
    call gtk.box_pack_start(box, button, False, False, 0)
    return button
end

function on_media_clicked(name, button):
    # Ikona se prepne hned po kliknuti (hlidac stav zmeni lokalne), prehravac ji pak potvrdi signalem
    if cc["player"] != None and cc["mpris"]:
        call mpris.send(cc["player"], name)
    end
    return 0
end

function css_text():
    name = gtk.settings_theme_name().lower()
    dark = name.find("dark") >= 0
    css = popup.colors("cc", dark) + CSS
    cc["dark"] = dark
    if cc["oneui"]:
        css = css + oneui_colors(dark) + ONEUI_CSS
    end
    return css
end

# Svetly/tmavy rezim se muze prepnout za behu (automaticky podle slunce)
function on_theme_changed(pspec, settings):
    call gtk.css_set(cc["provider"], css_text())
    if cc["oneui"]:
        call paint_icons()
    end
    return 0
end

# Skryte okno Ovladaciho centra se styly podle motivu
function create():
    global created
    if created:
        return 0
    end
    created = True
    cc["oneui"] = wayland()
    cc["icons"] = []
    cc["scale"] = 1
    cc["dark"] = False
    cc["provider"] = gtk.css_load(css_text())
    # Profilova fotka (~/.face) jako pozadi kolecka profilu - vlastni styl, meni se jen s fotkou
    cc["face_provider"] = gtk.css_load("")
    cc["face_key"] = ""
    call gtk.connect(gtk.settings_get_default(), "notify::gtk-theme-name", on_theme_changed)
    cc["player"] = None
    cc["media_art"] = None
    cc["media_dirty"] = True
    cc["timer"] = 0
    cc["placed"] = [0, 0]
    cc["pending"] = {}
    cc["mpris"] = False
    cc["muted"] = False
    cc["night"] = False
    cc["soft_save"] = 0
    if wayland():
        call wm.connect(on_wm_event)
    end
    cc["test_log"] = env.get("LUXOS_CC_TEST_LOG", "")
    if cc["test_log"] == None:
        cc["test_log"] = ""
    end

    cc["lost"] = -100000

    win = gtk.window_new(i18n.T("Control Center"))
    cc["win"] = win
    call gtk.widget_add_class(win, "cc")
    call gtk.window_set_resizable(win, False)
    call gtk.window_set_rgba(win)
    if wayland():
        call gtk.widget_add_class(win, "oneui")
        call popup.setup_radius(win, "luxos-control-center", ONEUI_RADIUS)
        # vystupy pro dlazdici Obrazovky; spojeni GTK, zadna vlastni obsluha udalosti (ta patri Emoji v hubu)
        call wl.attach(layer.wl_display())
    else:
        call window_hints_x11(win)
    end

    # One UI: mezery mezi radky jsou okraje radku z ONEUI_CSS (prototyp ma kazdou jinou)
    outer = gtk.box_new(gtk.VERTICAL, 0 if cc["oneui"] else 10)
    call gtk.widget_add_class(outer, "cc-box")
    call gtk.widget_set_size_request(outer, ONEUI_WIDTH if cc["oneui"] else 340, -1)
    call gtk.container_add(win, outer)
    if wayland():
        call popup.glass(win, outer)
    else:
        # X11 (verze 1.1.1): sklo z tapety plochy pod kartou (luxos_glass.panel, jen s kompozitorem)
        call glass.panel(win, outer, 18)
    end

    # One UI: nadpis a ozubene kolo (vsechna nastaveni) nad profilem
    if cc["oneui"]:
        head = gtk.box_new(gtk.HORIZONTAL, 7)
        call gtk.widget_add_class(head, "head-row")
        call gtk.box_pack_start(head, label(i18n.T("Control Center"), "head", 0), True, True, 0)
        gear = focusable(gtk.button_new_empty())
        call gtk.widget_add_class(gear, "round")
        call gtk.widget_set_tooltip(gear, i18n.T("All Settings…"))
        call gtk.container_add(gear, cc_icon("settings", 17.6, "ink"))
        call gtk.connect_data(gear, "clicked", 0, on_launch_clicked, settings_command())
        call gtk.box_pack_end(head, gear, False, False, 0)
        # napajeni: nabidka LuxOS z listy (zamknout, odhlasit, restart, vypnout) jako v prototypu
        power = focusable(gtk.button_new_empty())
        call gtk.widget_add_class(power, "round")
        call gtk.widget_set_tooltip(power, i18n.T("Shut Down"))
        call gtk.container_add(power, cc_icon("power", 17.6, "ink"))
        call gtk.connect(power, "clicked", on_power_clicked)
        call gtk.box_pack_end(head, power, False, False, 0)
        cc["power"] = power
        call gtk.box_pack_start(outer, head, False, False, 0)
    end

    # Profil: ucet LuxAI (~/.config/luxai/account.json), klik otevre Ucet LuxAI
    prof = focusable(gtk.button_new_empty())
    call gtk.button_set_relief(prof, gtk.RELIEF_NONE)
    call gtk.widget_add_class(prof, "plain")
    call gtk.widget_add_class(prof, "account")
    pbox = gtk.box_new(gtk.HORIZONTAL, 10)
    call gtk.widget_add_class(pbox, "section")
    avatar = gtk.label_new("")
    call gtk.widget_add_class(avatar, "avatar")
    call gtk.widget_set_valign(avatar, gtk.ALIGN_CENTER)
    cc["p_avatar"] = avatar
    ptext = text_column()
    cc["p_title"] = label("", "title", 0)
    cc["p_sub"] = label("", "sub", 0)
    call gtk.box_pack_start(ptext, cc["p_title"], False, False, 0)
    call gtk.box_pack_start(ptext, cc["p_sub"], False, False, 0)
    call gtk.box_pack_start(pbox, avatar, False, False, 0)
    call gtk.box_pack_start(pbox, ptext, True, True, 0)
    call gtk.box_pack_end(pbox, chevron(), False, False, 0)
    call gtk.container_add(prof, pbox)
    call gtk.connect_data(prof, "clicked", 0, on_launch_clicked, "luxos-account")
    call gtk.box_pack_start(outer, prof, False, False, 0)

    grid = gtk.grid_new()
    call gtk.widget_add_class(grid, "tiles")
    call gtk.grid_set_row_spacing(grid, 10 if cc["oneui"] else 8)
    call gtk.grid_set_column_spacing(grid, 10 if cc["oneui"] else 8)
    call gtk.grid_set_column_homogeneous(grid, True)
    if wayland():
        cc["t_wifi"] = tile_new(["network-wireless-symbolic", "wifi"], i18n.T("Wi-Fi"), toggle_wifi, open_wifi)
        cc["t_bt"] = tile_new(["bluetooth-active-symbolic", "bluetooth"], i18n.T("Bluetooth"), toggle_bt_power, toggle_bt)
    else:
        cc["t_wifi"] = tile_new(["network-wireless-symbolic", "wifi"], i18n.T("Wi-Fi"), toggle_wifi, None)
        cc["t_bt"] = tile_new(["bluetooth-active-symbolic", "bluetooth"], i18n.T("Bluetooth"), toggle_bt, None)
    end
    cc["t_dnd"] = tile_new(["notifications-disabled-symbolic", "minus"], i18n.T("Do Not Disturb"), toggle_dnd, None)
    cc["t_dark"] = tile_new(["weather-clear-night-symbolic", "moon"], i18n.T("Dark Mode"), toggle_dark, None)
    cc["t_data"] = tile_new(["network-cellular-signal-good-symbolic", "data"], i18n.T("Data Saver"), toggle_data, None)
    cc["t_power"] = tile_new(["battery-level-50-symbolic", "battery"], i18n.T("Battery Saver"), toggle_power, None)
    tiles = [cc["t_wifi"], cc["t_bt"], cc["t_dnd"], cc["t_dark"]]
    # One UI: sporice dat a baterie spolu v jedne pilulce pod ctyrmi velkymi dlazdicemi
    if not cc["oneui"]:
        tiles = tiles + [cc["t_data"], cc["t_power"]]
    end
    index = 0
    while index < len(tiles):
        call gtk.grid_attach(grid, tiles[index]["widget"], index % 2, index // 2, 1, 1)
        index += 1
    end
    call gtk.box_pack_start(outer, grid, False, False, 0)
    if cc["oneui"]:
        savers = gtk.box_new(gtk.HORIZONTAL, 0)
        call gtk.box_set_homogeneous(savers, True)
        call gtk.box_set_spacing(cc["t_data"]["box"], 7)
        call gtk.box_set_spacing(cc["t_power"]["box"], 7)
        call gtk.widget_add_class(savers, "section")
        call gtk.widget_add_class(savers, "savers")
        call gtk.box_pack_start(savers, cc["t_data"]["button"], True, True, 0)
        call gtk.box_pack_start(savers, cc["t_power"]["button"], True, True, 0)
        call gtk.box_pack_start(outer, savers, False, False, 0)
    end

    # One UI: kulate tlacitko vedle jasu zapina nocni svetlo (luxwm); X11: klik na ikonu otevre Monitory
    if cc["oneui"]:
        cc["s_bright"] = slider_new(i18n.T("Display"), ["display-brightness-symbolic", "sun"], set_brightness, toggle_night, ["", "nightlight"], i18n.T("Night Light"))
    else:
        cc["s_bright"] = slider_new(i18n.T("Display"), "display-brightness-symbolic", set_brightness, open_displays, "video-display-symbolic", i18n.T("Displays"))
    end
    cc["s_vol"] = slider_new(i18n.T("Sound"), ["audio-volume-high-symbolic", "sound"], set_volume, toggle_mute, ["audio-volume-high-symbolic", "sound"], i18n.T("Mute"))
    if cc["oneui"]:
        call gtk.widget_add_class(cc["s_bright"]["box"], "slider-row")
        call gtk.widget_add_class(cc["s_bright"]["box"], "first")
        call gtk.widget_add_class(cc["s_vol"]["box"], "slider-row")
    end

    # QR kod Wi-Fi: pripojeno = sdilet sit (luxos-wifi-qr), Wi-Fi zapnuta bez site = naskenovat kod
    if cc["oneui"]:
        # radek-pilulka s ikonou QR a sipkou jako v prototypu
        wifi_qr = focusable(gtk.button_new_empty())
        call gtk.widget_add_class(wifi_qr, "row")
        line = gtk.box_new(gtk.HORIZONTAL, 10)
        call gtk.box_pack_start(line, cc_icon("qr", 18.4, "ink"), False, False, 0)
        cc["wifi_qr_label"] = label(i18n.T("Share Wi-Fi with QR Code…"), "", 0)
        call gtk.label_set_ellipsize(cc["wifi_qr_label"], gtk.ELLIPSIZE_END)
        call gtk.box_pack_start(line, cc["wifi_qr_label"], True, True, 0)
        call gtk.box_pack_end(line, chevron(), False, False, 0)
        call gtk.container_add(wifi_qr, line)
        call gtk.widget_show_all(line)
    else:
        wifi_qr = focusable(gtk.button_new(i18n.T("Share Wi-Fi with QR Code…")))
        cc["wifi_qr_label"] = gtk.bin_get_child(wifi_qr)
        call gtk.widget_add_class(wifi_qr, "footer")
        call gtk.widget_set_halign(wifi_qr, gtk.ALIGN_START)
    end
    call gtk.connect(wifi_qr, "clicked", on_wifi_qr_clicked)
    call gtk.widget_set_no_show_all(wifi_qr, True)
    cc["wifi_qr"] = wifi_qr
    cc["wifi_qr_scan"] = False
    cc["wifi_signin"] = False
    cc["wifi_qr_mode"] = ""
    # One UI: posuvniky hned pod dlazdicemi, odkaz QR pod nimi (na X11 odkaz pod dlazdici Wi-Fi jako dosud)
    if cc["oneui"]:
        call gtk.box_pack_start(outer, cc["s_bright"]["box"], False, False, 0)
        call gtk.box_pack_start(outer, cc["s_vol"]["box"], False, False, 0)
        call gtk.box_pack_start(outer, wifi_qr, False, False, 0)
        call displays_section(outer)
    else:
        call gtk.box_pack_start(outer, wifi_qr, False, False, 0)
        call gtk.box_pack_start(outer, cc["s_bright"]["box"], False, False, 0)
        call displays_section(outer)
        call gtk.box_pack_start(outer, cc["s_vol"]["box"], False, False, 0)
    end

    # Prave hrajici hudba (MPRIS: Firefox, Spotify, VLC, mpv...) - jen kdyz nejaky prehravac bezi
    media = gtk.box_new(gtk.HORIZONTAL, 10)
    call gtk.widget_add_class(media, "section")
    call gtk.widget_add_class(media, "media")
    cc["media_box"] = media
    cc["m_art"] = gtk.image_new()
    art_wrap = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_set_valign(art_wrap, gtk.ALIGN_CENTER)
    call gtk.widget_add_class(art_wrap, "art")
    call gtk.box_pack_start(art_wrap, cc["m_art"], True, True, 0)
    call gtk.box_pack_start(media, art_wrap, False, False, 0)
    mtext = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_valign(mtext, gtk.ALIGN_CENTER)
    cc["m_title"] = label("", "title", 0)
    call gtk.label_set_ellipsize(cc["m_title"], gtk.ELLIPSIZE_END)
    call gtk.label_set_max_width_chars(cc["m_title"], 8 if cc["oneui"] else 18)
    cc["m_artist"] = label("", "sub", 0)
    call gtk.label_set_ellipsize(cc["m_artist"], gtk.ELLIPSIZE_END)
    call gtk.label_set_max_width_chars(cc["m_artist"], 8 if cc["oneui"] else 18)
    call gtk.box_pack_start(mtext, cc["m_title"], False, False, 0)
    call gtk.box_pack_start(mtext, cc["m_artist"], False, False, 0)
    call gtk.box_pack_start(media, mtext, True, True, 0)
    cc["m_prev"] = media_button(media, "Previous", ["media-skip-backward-symbolic", "previous"], gtk.ICON_MENU)
    cc["m_play"] = media_button(media, "PlayPause", ["media-playback-start-symbolic", "play"], gtk.ICON_LARGE_TOOLBAR)
    cc["m_next"] = media_button(media, "Next", ["media-skip-forward-symbolic", "next"], gtk.ICON_MENU)
    call gtk.widget_set_no_show_all(media, True)
    call gtk.box_pack_start(outer, media, False, False, 0)
    try:
        call mpris.init(gio.session_bus())
        cc["mpris"] = True
        call mpris.connect(on_media_changed)
    else:
        call eprint("luxos-control-center: media: " + String(last_error()))
    end

    bat_box = gtk.box_new(gtk.HORIZONTAL, 10)
    call gtk.widget_add_class(bat_box, "section")
    bat_button = focusable(gtk.button_new_empty())
    call gtk.button_set_relief(bat_button, gtk.RELIEF_NONE)
    call gtk.widget_add_class(bat_button, "plain")
    call gtk.widget_add_class(bat_button, "battery")
    call gtk.connect_data(bat_button, "clicked", 0, on_launch_clicked, "luxos-power")
    bat_lead = None
    if cc["oneui"]:
        # bila bublina s baterii prototypu (zelena vypln podle nabiti)
        cc["bat_icon"] = cc_icon(battery_glyph(100), 19.2, "on")
        bat_lead = gtk.box_new(gtk.HORIZONTAL, 0)
        call gtk.widget_add_class(bat_lead, "bubble")
        call gtk.widget_add_class(bat_lead, "on")
        call gtk.widget_set_valign(bat_lead, gtk.ALIGN_CENTER)
        call gtk.box_pack_start(bat_lead, cc["bat_icon"], True, True, 0)
    else:
        cc["bat_icon"] = gtk.image_new_from_icon_name("battery-level-50-symbolic", gtk.ICON_LARGE_TOOLBAR)
        bat_lead = cc["bat_icon"]
    end
    bat_text = text_column()
    cc["bat_title"] = label("", "title", 0)
    cc["bat_sub"] = label("", "sub", 0)
    call gtk.box_pack_start(bat_text, cc["bat_title"], False, False, 0)
    call gtk.box_pack_start(bat_text, cc["bat_sub"], False, False, 0)
    call gtk.box_pack_start(bat_box, bat_lead, False, False, 0)
    call gtk.box_pack_start(bat_box, bat_text, True, True, 0)
    call gtk.box_pack_end(bat_box, chevron(), False, False, 0)
    call gtk.container_add(bat_button, bat_box)
    cc["bat_wrap"] = bat_button
    call gtk.box_pack_start(outer, bat_button, False, False, 0)

    # One UI: odkazy zleva se stejnymi mezerami jako v prototypu
    footer = gtk.box_new(gtk.HORIZONTAL, 24 if cc["oneui"] else 4)
    if cc["oneui"]:
        call gtk.widget_add_class(footer, "footbar")
    end
    call footer_button(footer, i18n.T("Desktop & Dock…"), "luxos-settings desktop", ["video-display-symbolic", "monitor"])
    cc["foot_power"] = footer_button(footer, i18n.T("Battery…"), "luxos-power", ["battery-good-symbolic", "batteryempty"])
    # One UI: kratce "Nastaveni" jako prototyp (radek ma 8 px pismo)
    call footer_button(footer, i18n.T("Settings") if cc["oneui"] else i18n.T("All Settings…"), settings_command(), ["preferences-system-symbolic", "settings"])
    call gtk.box_pack_start(outer, footer, False, False, 0)

    call gtk.connect(win, "focus-in-event", on_focus_in)
    if cc["test_log"] != "" and cc["oneui"]:
        call gtk.connect_data(win, "set-focus", 1, on_set_focus, 0)
    end
    call gtk.connect(win, "focus-out-event", on_focus_out)
    call gtk.connect(win, "key-press-event", on_key)
    call gtk.connect(win, "notify::focus-visible", on_focus_visible)
    if not wayland():
        call gtk.connect(win, "realize", on_realize_x11)
        call gtk.connect(win, "configure-event", on_configure_x11)
    end
    # Na pozadi: zavreni okno jen skryje, dalsi klik v liste ho hned ukaze (SIGUSR1)
    call gtk.connect(win, "delete-event", on_delete)
    call refresh_fast()
    call refresh_slow()
    return 0
end

function window_hints_x11(win):
    call gtk.window_set_undecorated(win)
    call gtk.window_set_skip_taskbar_hint(win, True)
    call gtk.window_set_skip_pager_hint(win, True)
    call gtk.window_set_keep_above(win, True)
    call gtk.window_set_type_hint(win, gtk.TYPE_HINT_DIALOG)
    call gtk.window_stick(win)
    # vlastni WM_CLASS i ve sdilenem procesu luxos-hub
    call gtk.window_set_wmclass(win, "luxos-control-center", "Luxos-control-center")
    return 0
end

# Vsechna nastaveni: okno Nastaveni LuxOS v obou relacich (Xfce Spravce nastaveni je v nem odkazem jen na X11)
function settings_command():
    return "luxos-settings"
end

function log_test(message):
    if cc["test_log"] != "":
        call appendfile(cc["test_log"], message + "\n")
    end
    return 0
end

function is_visible():
    if not created:
        return False
    end
    return gtk.widget_get_visible(cc["win"])
end

function toggle():
    if not created:
        call create()
    end
    if gtk.widget_get_visible(cc["win"]):
        call close()
        return 0
    end
    # klik na tlacitko v liste, ktery oknu prave vzal fokus (a tim ho zavrel), ho nesmi hned znovu otevrit
    if wayland() and popup.same_click(cc["lost"]):
        return 0
    end
    call refresh_fast()
    if cc["media_dirty"]:
        call apply_media()
    end
    if wayland():
        call show_wayland()
    else:
        call gtk.widget_show_all(cc["win"])
        call place_x11()
        stamp = gtk.get_current_event_time()
        if stamp == 0:
            stamp = gtk.CURRENT_TIME
        end
        call gtk.window_present_with_time(cc["win"], stamp)
    end
    # udaje ze sluzeb (nmcli, pactl, oznameni) az po zobrazeni okna: spousteni procesu nebrzdi
    # vystup nmcli/pactl se cte jako text ("enabled", "Mute: yes"): vzdy s LC_ALL=C, jinak by cesky
    # "povoleno" znamenalo vypnutou Wi-Fi a prepinac by umel jen zapnout
    # prvni vykresleni (Python je mel ve vlakne)
    call glib.idle_add(refresh_slow_once)
    if cc["timer"] == 0:
        cc["timer"] = glib.timeout_add_seconds(3, periodic)
    end
    call log_test("shown")
    # test: tazeni posuvnikem (LUXOS_CC_TEST_SLIDE = pocet zmen po 5 ms; LUXOS_CC_TEST_SLIDER = s_bright, jinak Zvuk)
    slide = env.get("LUXOS_CC_TEST_SLIDE", "")
    if cc["test_log"] != "" and slide != None and slide != "":
        target = env.get("LUXOS_CC_TEST_SLIDER", "")
        if target != "s_bright":
            target = "s_vol"
        end
        cc["slide"] = [0, Int(slide), target]
        call glib.timeout_add(5, test_slide)
    end
    return 0
end

function test_slide():
    cc["slide"][0] = cc["slide"][0] + 1
    call gtk.range_set_value(cc[cc["slide"][2]]["scale"], cc["slide"][0])
    return cc["slide"][0] < cc["slide"][1]
end

# Plocha layer-shell: monitor a poloha pred zobrazenim, fokus da kompozitor (klavesnice on demand).
# Zadne gtk_window_present: GDK by na Waylandu cekal na aktivacni token v blokujicim roundtripu.
function show_wayland():
    # ikony prototypu v HiDPI monitoru, kde se okno ukaze (pri prvnim zobrazeni a po zmene)
    scale = popup.scale_of(cc["win"])
    if scale != cc["scale"]:
        cc["scale"] = scale
        call paint_icons()
    end
    call gtk.widget_show_all(gtk.bin_get_child(cc["win"]))
    width = gtk.widget_get_preferred_width(cc["win"])[1]
    call log_test("placed " + popup.place(cc["win"], width, "right"))
    call popup.show(cc["win"])
    if cc["test_log"] != "":
        call glib.timeout_add(400, log_tile_positions)
    end
    return 0
end

# Testy: ovladaci prvky podle jmena [jmeno, widget]
function test_marks():
    return [["wifi-bubble", cc["t_wifi"]["spot"]], ["wifi-title", cc["t_wifi"]["title"]], ["bt-bubble", cc["t_bt"]["spot"]],
        ["bt-title", cc["t_bt"]["title"]], ["dnd", cc["t_dnd"]["bubble"]], ["dark", cc["t_dark"]["bubble"]],
        ["data", cc["t_data"]["bubble"]], ["power", cc["t_power"]["bubble"]], ["bright", cc["s_bright"]["scale"]],
        ["bright-side", cc["s_bright"]["button"]], ["vol", cc["s_vol"]["scale"]], ["vol-side", cc["s_vol"]["button"]],
        ["qr", cc["wifi_qr"]], ["power-button", cc["power"]]]
end

# Testy: stred prvku v okne ("tilepos wifi-bubble x y", u posuvniku i sirka "tilepos vol x y w") a velikost okna
function log_tile_positions():
    for mark in test_marks():
        a = gtk.widget_get_allocation(mark[1])
        call log_test("tilepos " + mark[0] + " " + String(a[0] + a[2] // 2) + " " + String(a[1] + a[3] // 2) + " " + String(a[2]))
    end
    call log_test("size " + String(gtk.widget_get_allocated_width(cc["win"])) + " " + String(gtk.widget_get_allocated_height(cc["win"])))
    return False
end

# Testy: prvek s fokusem klavesnice ("focus vol")
function on_set_focus(unused, widget, window):
    tiles = [["wifi-bubble", cc["t_wifi"]["bubble"]], ["bt-bubble", cc["t_bt"]["bubble"]], ["wifi-tile", cc["t_wifi"]["button"]],
        ["bt-tile", cc["t_bt"]["button"]], ["dnd", cc["t_dnd"]["button"]],
        ["dark", cc["t_dark"]["button"]], ["data", cc["t_data"]["button"]], ["power", cc["t_power"]["button"]]]
    name = "other"
    for mark in test_marks() + tiles:
        if mark[1] == widget:
            name = mark[0]
        end
    end
    call log_test("focus " + name)
    return 0
end

function refresh_slow_once():
    call refresh_slow()
    return False
end

function close():
    call gtk.widget_hide(cc["win"])
    call log_test("hidden")
    return 0
end

# umisteni vpravo pod horni listou na monitoru s kurzorem
function place_x11():
    pointer = gtk.pointer_position()
    geo = gtk.monitor_at_point_workarea(pointer[0], pointer[1])
    size = gtk.window_get_size(cc["win"])
    w = size[0]
    h = size[1]
    # cele okno vzdy na monitoru (i kdyz po zobrazeni zmeni velikost - viz on_size)
    x = max(geo[0] + 4, geo[0] + geo[2] - w - 8)
    y = geo[1] + 6
    if y + h > geo[1] + geo[3] - 4:
        y = max(geo[1], geo[1] + geo[3] - h - 4)
    end
    call gtk.window_move(cc["win"], x, y)
    cc["placed"] = [w, h]
    return 0
end

function on_realize_x11(window):
    call place_x11()
    return 0
end

function on_configure_x11(event, window):
    call glib.idle_add(on_size_x11)
    return False
end

# obsah (baterie, prehravani, delsi texty) zmenil velikost okna: znovu umistit
function on_size_x11():
    if gtk.widget_get_visible(cc["win"]) and gtk.window_get_size(cc["win"]) != cc["placed"]:
        call place_x11()
    end
    return False
end

function on_focus_in(event, window):
    if wayland():
        call popup.focus_in(cc["win"])
    end
    return False
end

function on_focus_out(event, window):
    # testy pod Xvfb bez spravce oken: okno by se po zobrazeni hned zavrelo
    if env.get("LUXOS_HUB_NO_AUTOHIDE", "") == "1":
        return False
    end
    # Wayland: fokus bere jen klik jinam (okno, plocha), kompozitor ho hlasi spolehlive
    if wayland():
        if popup.focus_out(cc["win"]) and is_visible():
            cc["lost"] = glib.monotonic_time() // 1000
            call close()
        end
        return False
    end
    call glib.timeout_add(120, close_if_unfocused_x11)
    return False
end

# is_active() zustava po kliknuti na plochu (xfdesktop drzi grab) chybne True,
# proto rozhoduje i skutecne aktivni okno podle spravce oken (_NET_ACTIVE_WINDOW)
function close_if_unfocused_x11():
    active = gtk.screen_active_window()
    own = gtk.widget_get_window(cc["win"])
    if not gtk.window_is_active(cc["win"]) or (active != 0 and active != own):
        call close()
    end
    if active != 0:
        call glib.object_unref(active)
    end
    return False
end

function on_key(event, window):
    if gtk.event_key_keyval(event) == gtk.KEY_Escape:
        call close()
        return True
    end
    return False
end

function on_focus_visible(pspec, window):
    call gtk.widget_set_class(cc["win"], "keynav", gtk.window_get_focus_visible(cc["win"]))
    return 0
end

function on_delete(event, window):
    call close()
    return True
end

# ---- obnova stavu ------------------------------------------------------------------------------------

function on_off(on):
    if on:
        return i18n.T("On")
    end
    return i18n.T("Off")
end

# Profilova fotka uctu (~/.face z luxos-profile-picture) misto pismena; styl se meni jen po zmene souboru
function face_update():
    path = glib.home_dir() + "/.face"
    st = glib.stat(path)
    key = ""
    if len(st) > 0 and st[0] > 0:
        key = path + ":" + String(st[1])
    end
    if key == cc["face_key"]:
        return 0
    end
    cc["face_key"] = key
    css = ""
    if key != "":
        uri = "file://" + path.replace("%", "%25").replace(" ", "%20").replace("\"", "%22")
        css = ".avatar.photo, .oneui .avatar.photo { background-image: url(\"" + uri + "\"); background-size: cover; background-position: center; color: transparent; }\n"
    end
    call gtk.css_set(cc["face_provider"], css)
    call gtk.widget_set_class(cc["p_avatar"], "photo", key != "")
    if key != "":
        call log_test("photo")
    end
    return 0
end

# Okamzite udaje (soubory v ~/.config a /sys) - bez spousteni programu
function refresh_fast():
    user = account_user()
    name = ""
    if user != None:
        name = text_value(user.get("displayName"))
        if name == "":
            name = text_value(user.get("email"))
        end
    end
    initial = "✦"
    if name != "":
        initial = name[0:1].upper()
    end
    call gtk.label_set_text(cc["p_avatar"], initial)
    call face_update()
    if user != None:
        call gtk.label_set_text(cc["p_title"], name)
        call gtk.label_set_text(cc["p_sub"], i18n.T("LuxAI Account"))
    else:
        call gtk.label_set_text(cc["p_title"], i18n.T("Sign in to LuxAI"))
        call gtk.label_set_text(cc["p_sub"], i18n.T("AI in LuxAI, Lux Code and LSL IDE"))
    end
    dark = dark_state()
    call tile_set_state(cc["t_dark"], dark, on_off(dark))
    data = flag_state("datasaver")
    call tile_set_state(cc["t_data"], data, on_off(data))
    power = flag_state("powersaver")
    call tile_set_state(cc["t_power"], power, on_off(power))
    b = brightness()
    if b != None:
        call slider_set_value(cc["s_bright"], b)
    end
    bat = battery()
    call gtk.widget_set_no_show_all(cc["bat_wrap"], bat == None)
    call gtk.widget_set_visible(cc["bat_wrap"], bat != None)
    # bez baterie (stolni pocitac, VM) vede odkaz dole na Napajeni (rezim, uspani), ne na Baterii
    if cc["oneui"]:
        foot = cc["foot_power"]
        call gtk.label_set_text(foot[2], i18n.T("Battery") if bat != None else i18n.T("Power"))
        call set_icon(foot[1], "batteryempty" if bat != None else "power", "ink")
    end
    if bat != None:
        cap = bat[0]
        status = bat[1]
        mins = bat[2]
        level = min(100, (cap + 5) // 10 * 10)
        icon = "battery-level-" + String(level)
        if status == "Charging":
            icon = icon + "-charging"
        end
        if cc["oneui"]:
            call set_icon(cc["bat_icon"], battery_glyph(cap), "on")
            call gtk.label_set_text(cc["bat_title"], i18n.T("Battery") + " " + String(cap) + " %")
        else:
            call gtk.image_set_from_icon_name(cc["bat_icon"], icon + "-symbolic", gtk.ICON_LARGE_TOOLBAR)
            call gtk.label_set_text(cc["bat_title"], i18n.T("Battery") + "  " + String(cap) + " %")
        end
        sub = i18n.T("Fully charged")
        if status == "Charging":
            sub = i18n.T("Charging")
        elif status == "Discharging":
            sub = i18n.T("On battery")
        end
        if mins != None:
            if status == "Discharging":
                sub = sub + " · " + i18n.TF("%s remaining", [fmt_minutes(mins)])
            else:
                sub = sub + " · " + i18n.TF("%s until full", [fmt_minutes(mins)])
            end
        end
        call gtk.label_set_text(cc["bat_sub"], sub)
    end
    return 0
end

function text_value(value):
    if value == None:
        return ""
    end
    return String(value)
end

# Udaje ze sluzeb (sit, Bluetooth, zvuk, oznameni) - asynchronne, bez blokovani okna
function refresh_slow():
    call glib.spawn_capture(["env", "LC_ALL=C", "nmcli", "radio", "wifi"], on_wifi_radio, 0)
    call show_bt(bluetooth_state())
    if wayland():
        call notify_call("GetDoNotDisturb", [], "", on_dnd_reply)
    else:
        call glib.spawn_capture(["xfconf-query", "-c", "xfce4-notifyd", "-p", "/do-not-disturb"], on_dnd, 0)
    end
    call glib.spawn_capture(["env", "LC_ALL=C", "pactl", "get-sink-volume", "@DEFAULT_SINK@"], on_volume, 0)
    if wayland():
        call wm.request({"cmd": "get_night_light"}, on_night_state)
        call displays_apply(displays_wayland())
    else:
        call glib.spawn_capture(["xrandr", "--current"], on_displays, 0)
    end
    return 0
end

# Bez adapteru Bluetooth preskrtnuta ikona, aby vypnuta bublina nevypadala jako porucha
function show_bt(state):
    call tile_set_state(cc["t_bt"], state[0], state[1])
    if cc["oneui"]:
        call set_icon(cc["t_bt"]["image"], "bluetooth-off" if state[0] == None else "bluetooth", "on" if state[0] == True else "ink")
    end
    return 0
end

# Pocitac jen s kabelem (bez karty Wi-Fi): dlazdice Ethernet, bublina i zbytek otevrou okno site v liste
function show_wired(wired):
    tile = cc["t_wifi"]
    if tile.get("wired", False) == wired:
        return 0
    end
    tile["wired"] = wired
    call gtk.label_set_text(tile["title"], i18n.T("Ethernet") if wired else i18n.T("Wi-Fi"))
    call set_icon(tile["image"], "ethernet" if wired else "wifi", "on" if tile_is_on(tile) else "ink")
    return 0
end

function on_wifi_radio(unused, output, status):
    if status != 0:
        call tile_set_state(cc["t_wifi"], None, "")
        call set_wifi_qr("")
        return 0
    end
    on = output.strip() == "enabled"
    call glib.spawn_capture(["env", "LC_ALL=C", "nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi"], on_wifi_list, on)
    return 0
end

# Odkaz pod dlazdicemi: "share"/"scan" (QR kod Wi-Fi), "signin" (sit bez internetu - prihlaseni
# do site s portalem rucne, kdyz se okno neotevrelo samo) nebo "" (skryty)
function set_wifi_qr(mode):
    button = cc["wifi_qr"]
    if mode != cc["wifi_qr_mode"]:
        call log_test("wifi-qr:" + mode)
        cc["wifi_qr_mode"] = mode
    end
    if mode == "":
        call gtk.widget_set_visible(button, False)
        return 0
    end
    cc["wifi_qr_scan"] = mode == "scan"
    cc["wifi_signin"] = mode == "signin"
    if mode == "signin":
        call gtk.label_set_text(cc["wifi_qr_label"], i18n.T("Sign In to Network…"))
    elif mode == "scan":
        call gtk.label_set_text(cc["wifi_qr_label"], i18n.T("Join Wi-Fi with QR Code…"))
    else:
        call gtk.label_set_text(cc["wifi_qr_label"], i18n.T("Share Wi-Fi with QR Code…"))
    end
    call gtk.widget_set_visible(button, True)
    return 0
end

function on_wifi_qr_clicked(button):
    if cc["wifi_signin"]:
        call log_test("network sign-in")
        call glib.spawn_app(["luxos-network-login"])
    elif cc["wifi_qr_scan"]:
        call log_test("wifi-qr scan")
        call glib.spawn_app(["luxos-wifi-qr", "--scan"])
    else:
        call log_test("wifi-qr share")
        call glib.spawn_app(["luxos-wifi-qr"])
    end
    call close()
    return 0
end

function on_wifi_list(on, output, status):
    ssid = ""
    if status == 0:
        for line in output.split("\n"):
            if line.startswith("yes:"):
                # nmcli -t escapuje ":" a "\\" v hodnotach (sit "Kavarna: 5G" -> "Kavarna\\: 5G")
                ssid = line[4:].replace("\\:", ":").replace("\\\\", "\\")
                break
            end
        end
    end
    if ssid != "":
        call show_wired(False)
    end
    if not on:
        call show_wired(False)
        call tile_set_state(cc["t_wifi"], False, i18n.T("Off"))
        call set_wifi_qr("")
        return 0
    end
    if ssid != "":
        call tile_set_state(cc["t_wifi"], True, ssid)
        call set_wifi_qr("share")
        call glib.spawn_capture(["env", "LC_ALL=C", "nmcli", "-t", "-f", "CONNECTIVITY", "general"], on_connectivity, ssid)
        return 0
    end
    call glib.spawn_capture(["env", "LC_ALL=C", "nmcli", "-t", "-f", "TYPE,STATE", "device"], on_wifi_devices, 0)
    return 0
end

# Pripojeno, ale bez internetu (omezene / portal): misto sdileni nabidnout prihlaseni do site
# "Prihlasit se k <sit>…" (i po zavrenem okne prihlaseni, dokud neni internet)
function on_connectivity(network, output, status):
    state = output.strip()
    if status == 0 and (state == "portal" or state == "limited"):
        call set_wifi_qr("signin")
        call log_test("wifi-signin:" + network)
        if network != "":
            call gtk.label_set_text(cc["wifi_qr_label"], i18n.TF("Sign In to “%s”…", [network]))
        end
    end
    return 0
end

function on_wifi_devices(unused, output, status):
    wired = ""
    if status == 0:
        wired = output
    end
    no_wifi = wired.find("wifi:") < 0
    if wired.find("ethernet:connected") >= 0 and no_wifi and wayland():
        call show_wired(True)
        call tile_set_state(cc["t_wifi"], True, i18n.T("Connected"))
        call set_wifi_qr("")
        call glib.spawn_capture(["env", "LC_ALL=C", "nmcli", "-t", "-f", "CONNECTIVITY", "general"], on_connectivity, "")
        return 0
    end
    call show_wired(False)
    if wired.find("ethernet:connected") >= 0:
        call tile_set_state(cc["t_wifi"], True, i18n.T("Ethernet"))
        call set_wifi_qr("")
        call glib.spawn_capture(["env", "LC_ALL=C", "nmcli", "-t", "-f", "CONNECTIVITY", "general"], on_connectivity, "")
    else:
        call tile_set_state(cc["t_wifi"], True, i18n.T("Not connected"))
        call set_wifi_qr("scan")
    end
    return 0
end

function on_dnd(unused, output, status):
    on = status == 0 and output.strip() == "true"
    call tile_set_state(cc["t_dnd"], on, on_off(on))
    return 0
end

function notify_call(method, values, signature, handler):
    safe:
        call gio.call_async(gio.session_bus(), "org.freedesktop.Notifications", "/cz/luxos/NotificationHistory", "cz.luxos.NotificationHistory", method, values, signature, 3000, handler, 0)
    end
    return 0
end

function on_dnd_reply(unused, values, error):
    on = values != None and len(values) > 0 and values[0] == True
    call tile_set_state(cc["t_dnd"], on, on_off(on))
    return 0
end

function on_dnd_set(unused, values, error):
    return 0
end

function on_volume(unused, output, status):
    if status != 0 or output.strip() == "":
        return 0
    end
    level = parse_percent(output)
    call glib.spawn_capture(["env", "LC_ALL=C", "pactl", "get-sink-mute", "@DEFAULT_SINK@"], on_mute, level)
    return 0
end

# Prvni cislo s % v textu ("Volume: front-left: 65536 / 100% / 0,00 dB")
function parse_percent(output):
    index = 0
    n = len(output)
    while index < n:
        if output[index] == "%":
            start = index
            while start > 0 and text.is_digit(output[start - 1]):
                start -= 1
            end
            if start < index:
                return Int(output[start:index])
            end
        end
        index += 1
    end
    return 0
end

function on_mute(level, output, status):
    muted = status == 0 and output.strip().endswith("yes")
    cc["muted"] = muted
    call slider_set_value(cc["s_vol"], level)
    call show_muted(muted)
    return 0
end

# Ikona ztlumeni; v One UI je tlacitko vedle posuvniku bile, kdyz zvuk hraje
function show_muted(muted):
    call gtk.widget_set_class(cc["s_vol"]["button"], "on", not muted)
    if cc["oneui"]:
        call set_icon(cc["s_vol"]["icon"], "muted" if muted else "sound", "ink" if muted else "on")
        return 0
    end
    icon = "audio-volume-high-symbolic"
    if muted:
        icon = "audio-volume-muted-symbolic"
    end
    call gtk.image_set_from_icon_name(cc["s_vol"]["icon"], icon, gtk.ICON_MENU)
    return 0
end

# Obnova jen pri zobrazenem okne (skryte okno na pozadi se zbytecne nebudi)
function periodic():
    if gtk.widget_get_visible(cc["win"]):
        call refresh_slow()
        return True
    end
    cc["timer"] = 0
    return False
end

# ---- hudba a video (MPRIS): udalosti, zadne dotazovani -------------------------------------------

function on_media_changed():
    if gtk.widget_get_visible(cc["win"]):
        call apply_media()
    else:
        cc["media_dirty"] = True     # skryte okno: obalku apod. nacist az pri zobrazeni
    end
    return 0
end

function apply_media():
    cc["media_dirty"] = False
    media = None
    if cc["mpris"]:
        media = mpris.current()
    end
    if media == None:
        cc["player"] = None
        call gtk.widget_set_no_show_all(cc["media_box"], True)
        call gtk.widget_hide(cc["media_box"])
        return 0
    end
    cc["player"] = media["bus"]
    title = media["title"]
    if title == "":
        title = media["app"]
    end
    call gtk.label_set_text(cc["m_title"], title)
    artist = media["artist"]
    if artist == "" and media["title"] != "":
        artist = media["app"]
    end
    call gtk.label_set_text(cc["m_artist"], artist)
    call set_play_icon(media["playing"])
    call gtk.widget_set_sensitive(cc["m_next"], media["can_next"])
    call gtk.widget_set_sensitive(cc["m_prev"], media["can_prev"])
    art = media["art"]
    if art != cc["media_art"]:
        cc["media_art"] = art
        pixbuf = 0
        if art.startswith("file://"):
            path = glib.filename_from_uri(art)
            if path != "":
                pixbuf = gtk.pixbuf_new_from_file_at_scale(path, 42, 42, True)
            end
        end
        if pixbuf != 0:
            call gtk.image_set_from_pixbuf(cc["m_art"], pixbuf)
            call glib.object_unref(pixbuf)
        else:
            call gtk.image_set_from_icon_name(cc["m_art"], "audio-x-generic-symbolic", gtk.ICON_LARGE_TOOLBAR)
        end
    end
    if not gtk.widget_get_visible(cc["media_box"]):
        call gtk.widget_set_no_show_all(cc["media_box"], False)
        call gtk.widget_show_all(cc["media_box"])
    end
    return 0
end

function set_play_icon(playing):
    if cc["oneui"]:
        call set_icon(gtk.bin_get_child(cc["m_play"]), "pause" if playing else "play", "ink")
        return 0
    end
    icon = "media-playback-start-symbolic"
    if playing:
        icon = "media-playback-pause-symbolic"
    end
    call gtk.image_set_from_icon_name(gtk.bin_get_child(cc["m_play"]), icon, gtk.ICON_LARGE_TOOLBAR)
    return 0
end

# ---- akce ----------------------------------------------------------------------------------------------

function toggle_wifi():
    call glib.spawn_capture(["env", "LC_ALL=C", "nmcli", "radio", "wifi"], on_toggle_wifi_state, 0)
    return 0
end

function on_toggle_wifi_state(unused, output, status):
    target = "on"
    if status == 0 and output.strip() == "enabled":
        target = "off"
    end
    call glib.spawn_watched_data(["nmcli", "radio", "wifi", target], on_command_done_slow, 0)
    return 0
end

function on_command_done_slow(unused, pid, status):
    call refresh_slow()
    return 0
end

# Okno Bluetooth: zapnuti, sparovana zarizeni i pripojeni noveho
function toggle_bt():
    call glib.spawn_app(["luxos-bluetooth"])
    call close()
    return 0
end

# Bublina Bluetooth na Waylandu: zapnout/vypnout adapter (BlueZ Powered, zablokovany rfkill odblokuje);
# bez Bluetooth nebo pri chybe okno Bluetooth
function toggle_bt_power():
    state = bluetooth_state()
    if state[0] == None:
        return toggle_bt()
    end
    ok = False
    try:
        call gio.set_property(gio.system_bus(), "org.bluez", "/org/bluez/hci0", "org.bluez.Adapter1", "Powered", not state[0], "b")
        ok = True
    else:
        if not state[0]:
            call glib.spawn_sync_quiet(["rfkill", "unblock", "bluetooth"])
            safe:
                call gio.set_property(gio.system_bus(), "org.bluez", "/org/bluez/hci0", "org.bluez.Adapter1", "Powered", True, "b")
                ok = True
            end
        end
    end
    if not ok:
        return toggle_bt()
    end
    call show_bt(bluetooth_state())
    return 0
end

# Zbytek dlazdice Wi-Fi na Waylandu: okno Wi-Fi z listy (luxos-bar, SIGUSR1 podle $XDG_RUNTIME_DIR/luxos-bar.pid)
function open_wifi():
    call close()
    call signal_bar(SIGUSR1)
    return 0
end

# Tlacitko napajeni v One UI: nabidka LuxOS listy (SIGUSR2)
function on_power_clicked(button):
    call log_test("power")
    call close()
    call signal_bar(SIGUSR2)
    return 0
end

function signal_bar(signum):
    pid = text.to_int(glib.read_text(popup.runtime_file("luxos-bar.pid")).strip(), 0)
    if pid > 0 and glib.read_text("/proc/" + String(pid) + "/cmdline").find("luxos-bar") >= 0:
        call glib.kill(pid, signum)
    end
    return 0
end

function toggle_dnd():
    on = not tile_is_on(cc["t_dnd"])
    call tile_set_state(cc["t_dnd"], on, on_off(on))
    if wayland():
        call notify_call("SetDoNotDisturb", [on], "(b)", on_dnd_set)
        return 0
    end
    value = "false"
    if on:
        value = "true"
    end
    call glib.spawn_quiet(["xfconf-query", "-c", "xfce4-notifyd", "-p", "/do-not-disturb", "-n", "-t", "bool", "-s", value])
    return 0
end

# Na Waylandu karta zustane otevrena jako u ostatnich dlazdic: novy motiv prebarvi on_theme_changed, sklo
# z nove tapety luxos_hub_popup (sleduje appearance.conf)
function toggle_dark():
    dark = not dark_state()
    call glib.spawn_quiet(["luxos-appearance", "toggle"])
    if wayland():
        call tile_set_state(cc["t_dark"], dark, on_off(dark))
    else:
        call close()
    end
    return 0
end

function toggle_data():
    return toggle_flag(cc["t_data"], "datasaver", "luxos-datasaver")
end

function toggle_power():
    return toggle_flag(cc["t_power"], "powersaver", "luxos-powersaver")
end

# Dlazdice se prepne hned, prikaz (sit, systemova cast, monitor) dobehne na pozadi
function toggle_flag(tile, flag, command):
    on = not flag_state(flag)
    call tile_set_state(tile, on, on_off(on))
    mode = "off"
    if on:
        mode = "on"
    end
    pid = glib.spawn_watched_data([command, mode], on_flag_done, 0)
    if pid == 0:
        call refresh_fast()
    end
    return 0
end

function on_flag_done(unused, pid, status):
    call refresh_fast()
    return 0
end

function set_volume(value):
    # posunuti ztlumeneho zvuku ho zapne (jako v macOS) - jinak by posuvnik "nefungoval"
    if cc["muted"]:
        cc["muted"] = False
        call glib.spawn_quiet(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
        call show_muted(False)
    end
    return ["pactl", "set-sink-volume", "@DEFAULT_SINK@", String(value) + "%"]
end

function toggle_mute():
    call glib.spawn_watched_data(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"], on_command_done_slow, 0)
    return 0
end

# ---- obrazovky: Zrcadlit / Rozsirit / Jen externi -----------------------------------------------------
# Jen kdyz jsou pripojene aspon dva monitory. Prepina luxos-displays (rezim se ulozi pro tuto sadu monitoru
# a pouzije se i po opetovnem pripojeni a prihlaseni); stav se cte z "xrandr --current" (bez sondovani),
# na Waylandu z vystupu kompozitoru (luxos_wl).

function is_internal_name(name):
    return name.startswith("eDP") or name.startswith("LVDS") or name.startswith("DSI")
end

# "1920x1080+0+0" -> [w, h, x, y], jinak None
function parse_geometry(word):
    parts = word.split("+")
    if len(parts) != 3:
        return None
    end
    size = parts[0].split("x")
    if len(size) != 2:
        return None
    end
    out = []
    for value in [size[0], size[1], parts[1], parts[2]]:
        number = text.to_int(value, None)
        if number == None:
            return None
        end
        out.append(number)
    end
    return out
end

# Vystup "xrandr --current" -> stav (displays_state)
function displays_parse(output):
    screens = []
    for line in output.split("\n"):
        if line == "" or line.startswith(" ") or line.startswith("\t"):
            continue
        end
        words = line.split(" ")
        if len(words) < 2 or words[1] != "connected":
            continue
        end
        index = 2
        primary = False
        if len(words) > index and words[index] == "primary":
            primary = True
            index += 1
        end
        geo = None
        if len(words) > index:
            geo = parse_geometry(words[index])
        end
        screens.append([words[0], geo, primary])
    end
    return displays_state(screens)
end

# Monitory na Waylandu: hlavy wlr-output-management (i vypnute monitory), jinak zapnute vystupy wl_output
# (luxwm hlavy ukaze jen programum z privileged.conf, hub mezi ne nepatri)
function displays_wayland():
    screens = []
    if not wl.available():
        return displays_state(screens)
    end
    for head in wl.heads():
        info = wl.head_info(head)
        geo = None
        if info[2]:
            geo = [info[5], info[6], info[3], info[4]]
        end
        screens.append([info[0], geo, False])
    end
    if len(screens) == 0:
        for output in wl.outputs():
            g = wl.output_geometry(output)
            screens.append([wl.output_name(output), [g[2], g[3], g[0], g[1]], False])
        end
    end
    return displays_state(screens)
end

# [[nazev, [w, h, x, y] nebo None (vypnuty), hlavni], ...] -> {"count": pripojenych, "internal": vestaveny pripojen,
#   "mode": "mirror" | "extend" | "external" | "internal" | "" (neznamy), "size": [w, h] hlavniho/prvniho aktivniho}
function displays_state(screens):
    count = 0
    internal = False
    active = []
    first = None
    for screen in screens:
        name = screen[0]
        count += 1
        if is_internal_name(name):
            internal = True
        end
        geo = screen[1]
        if geo != None:
            active.append([name, geo])
            if screen[2] or first == None:
                first = geo
            end
        end
    end
    mode = ""
    if count >= 2 and len(active) >= 2:
        mode = "mirror"
        origin = active[0][1]
        for item in active:
            geo = item[1]
            if geo[2] != origin[2] or geo[3] != origin[3]:
                mode = "extend"
            end
        end
    elif count >= 2 and len(active) == 1:
        if is_internal_name(active[0][0]):
            mode = "internal"
        elif internal:
            mode = "external"
        end
    end
    size = None
    if first != None:
        size = [first[0], first[1]]
    end
    return {"count": count, "internal": internal, "mode": mode, "size": size}
end

# Tlacitko rezimu: ikona v kolecku nad nazvem (jako dlazdice, zapnuty rezim modre)
function mode_button_new(icon, title, mode):
    button = focusable(gtk.button_new_empty())
    call gtk.widget_add_class(button, "tile")
    call gtk.widget_add_class(button, "mode")
    call gtk.widget_set_tooltip(button, title)
    column = gtk.box_new(gtk.VERTICAL, 4)
    bubble = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_set_halign(bubble, gtk.ALIGN_CENTER)
    call gtk.widget_add_class(bubble, "bubble")
    image = gtk.image_new_from_icon_name(icon, gtk.ICON_MENU)
    call gtk.widget_set_hexpand(image, True)
    call gtk.widget_set_vexpand(image, True)
    call gtk.box_pack_start(bubble, image, True, True, 0)
    call gtk.box_pack_start(column, bubble, False, False, 0)
    title_label = label(title, "title", 0.5)
    call gtk.label_set_ellipsize(title_label, gtk.ELLIPSIZE_END)
    call gtk.label_set_max_width_chars(title_label, 10)
    call gtk.box_pack_start(column, title_label, False, False, 0)
    call gtk.container_add(button, column)
    call gtk.connect_data(button, "clicked", 0, on_display_mode_clicked, mode)
    return button
end

function displays_section(outer):
    box = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.widget_add_class(box, "section")
    call gtk.widget_add_class(box, "screens")
    head = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.box_pack_start(head, label(i18n.T("Screens"), "title", 0), False, False, 0)
    cc["disp_sub"] = label("", "sub", 1)
    call gtk.label_set_ellipsize(cc["disp_sub"], gtk.ELLIPSIZE_END)
    call gtk.box_pack_end(head, cc["disp_sub"], True, True, 0)
    call gtk.box_pack_start(box, head, False, False, 0)
    row = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.box_set_homogeneous(row, True)
    cc["d_mirror"] = mode_button_new("luxos-display-mirror-symbolic", i18n.T("Mirror"), "mirror")
    cc["d_extend"] = mode_button_new("luxos-display-extend-symbolic", i18n.T("Extend"), "extend")
    cc["d_external"] = mode_button_new("luxos-display-external-symbolic", i18n.T("External Only"), "external")
    for button in [cc["d_mirror"], cc["d_extend"], cc["d_external"]]:
        call gtk.box_pack_start(row, button, True, True, 0)
    end
    call gtk.box_pack_start(box, row, False, False, 0)
    cc["disp_box"] = box
    cc["disp_state"] = {"count": 0, "internal": False, "mode": "", "size": None}
    cc["disp_busy"] = False
    cc["disp_next"] = ""
    cc["disp_logged"] = ""
    # skryte, dokud xrandr neukaze druhy monitor (show_all okna ho nezobrazi)
    call gtk.widget_set_no_show_all(box, True)
    call gtk.box_pack_start(outer, box, False, False, 0)
    return 0
end

function on_displays(unused, output, status):
    # behem prepinani by mezistav (jeden vystup vypnuty) prepsal prave zvoleny rezim
    if status != 0 or cc["disp_busy"]:
        return 0
    end
    call displays_apply(displays_parse(output))
    return 0
end

function displays_apply(state):
    cc["disp_state"] = state
    box = cc["disp_box"]
    show = state["count"] >= 2
    if not show:
        call gtk.widget_set_no_show_all(box, True)
        call gtk.widget_hide(box)
    else:
        # Jen externi: jen u notebooku (s vestavenym displejem)
        call gtk.widget_set_no_show_all(cc["d_external"], not state["internal"])
        call gtk.widget_set_no_show_all(box, False)
        call gtk.widget_show_all(box)
        if not state["internal"]:
            call gtk.widget_hide(cc["d_external"])
        end
    end
    mode = state["mode"]
    call gtk.widget_set_class(cc["d_mirror"], "on", mode == "mirror")
    call gtk.widget_set_class(cc["d_extend"], "on", mode == "extend")
    call gtk.widget_set_class(cc["d_external"], "on", mode == "external")
    call gtk.label_set_text(cc["disp_sub"], displays_sub(state))
    key = ""
    if show:
        key = mode + ":" + String(state["count"])
    end
    if key != cc["disp_logged"]:
        cc["disp_logged"] = key
        call log_test("displays:" + key)
    end
    return 0
end

function displays_sub(state):
    mode = state["mode"]
    if mode == "mirror":
        sub = i18n.T("Mirroring")
        if state["size"] != None:
            sub = sub + " · " + String(state["size"][0]) + " × " + String(state["size"][1])
        end
        return sub
    elif mode == "extend":
        return i18n.T("Extended")
    elif mode == "external":
        return i18n.T("Only external screen")
    elif mode == "internal":
        return i18n.T("Only this computer's screen")
    end
    return ""
end

# Prepnuti hned (tlacitko se rozsviti ihned), luxos-displays dobehne na pozadi a stav se pak precte znovu
# Klik behem prepinani se nezahodi: posledni volba se pouzije hned po dobehnuti predchozi
function on_display_mode_clicked(mode, button):
    state = cc["disp_state"]
    if state["mode"] == mode:
        return 0
    end
    call log_test("display-set:" + mode)
    call displays_apply({"count": state["count"], "internal": state["internal"], "mode": mode, "size": None})
    if cc["disp_busy"]:
        cc["disp_next"] = mode
        return 0
    end
    call display_mode_run(mode)
    return 0
end

function display_mode_run(mode):
    cc["disp_next"] = ""
    pid = glib.spawn_watched_data(["luxos-displays", mode], on_display_mode_done, 0)
    cc["disp_busy"] = pid != 0
    return 0
end

function on_display_mode_done(unused, pid, status):
    cc["disp_busy"] = False
    if cc["disp_next"] != "":
        call display_mode_run(cc["disp_next"])
        return 0
    end
    call log_test("display-done")
    if wayland():
        call displays_apply(displays_wayland())
        return 0
    end
    call glib.spawn_capture(["xrandr", "--current"], on_displays, 0)
    # plocha se zmenila (napr. vypnuty vestaveny displej): okno znovu na monitor s kurzorem
    if gtk.widget_get_visible(cc["win"]):
        call place_x11()
    end
    return 0
end

# Na Waylandu nova aplikace Monitory: luxos-displays bez argumentu ji otevre
function open_displays():
    if wayland():
        call glib.spawn_app(["luxos-displays"])
    else:
        call glib.spawn_app(["luxos-display-settings"])
    end
    call close()
    return 0
end

function set_brightness(value):
    v = max(value, 10)
    if wayland():
        if backlight() == "":
            return set_brightness_soft(v)
        end
        return set_brightness_logind(v)
    end
    if backlight() != "":
        return ["brightnessctl", "-q", "set", String(v) + "%"]
    end
    # Monitor bez podsviceni (stolni pocitac, VM): softwarovy jas vsech vystupu
    call glib.mkdir_p(config_dir())
    call writefile(soft_brightness_path(), String(v))
    return ["luxos-displays", "brightness", String(v)]
end

# Wayland: podsviceni pres logind (Session.SetBrightness) - bez brightnessctl, bez prav k /sys a bez procesu.
# Posuvnik ceka na odpoved stejne jako na dobehnuti prikazu (nejvys jedna zmena na ceste).
function set_brightness_logind(percent):
    bl = backlight()
    maximum = None
    if bl != "":
        maximum = read_int(bl + "/max_brightness")
    end
    if maximum == None or maximum <= 0:
        return None
    end
    row = cc["s_bright"]
    name = bl[text.rfind(bl, "/") + 1:]
    value = (maximum * Int(percent) + 50) // 100
    call log_test("brightness " + name + " " + String(value))
    try:
        call gio.call_async(gio.system_bus(), "org.freedesktop.login1", "/org/freedesktop/login1/session/auto", "org.freedesktop.login1.Session", "SetBrightness", ["backlight", name, value], "(ssu)", 3000, on_brightness_set, row)
        row["busy"] = True
    else:
        call eprint("luxos-control-center: brightness: " + String(last_error()))
    end
    return None
end

# Monitor bez podsviceni: softwarovy jas v luxwm (gamma tabulka nebo zavoj), ulozeny pro pristi prihlaseni
# (luxwm ho cte pri startu); soubor az po dotazeni, ne pri kazdem kroku posuvniku
function set_brightness_soft(percent):
    call wm.request({"cmd": "set_brightness", "value": Int(percent)}, None)
    cc["soft_value"] = Int(percent)
    if cc["soft_save"] != 0:
        call glib.source_remove(cc["soft_save"])
    end
    cc["soft_save"] = glib.timeout_add(600, save_brightness_soft)
    call log_test("soft-brightness " + String(Int(percent)))
    return None
end

function save_brightness_soft():
    cc["soft_save"] = 0
    call glib.mkdir_p(config_dir())
    call writefile(soft_brightness_path(), String(cc["soft_value"]) + "\n")
    return False
end

function on_wm_event(event):
    return 0
end

function on_night_state(reply):
    if reply != None and reply.get("ok", False):
        call show_night(reply.get("on", False) == True)
    end
    return 0
end

function show_night(on):
    cc["night"] = on
    call gtk.widget_set_class(cc["s_bright"]["button"], "on", on)
    call set_icon(cc["s_bright"]["icon"], "nightlight", "on" if on else "ink")
    return 0
end

# Mesic vedle jasu: prepne hned, luxwm potvrdi (v rozvrhu plati do pristi hranice)
function toggle_night():
    on = not cc["night"]
    call log_test("night " + ("on" if on else "off"))
    call show_night(on)
    call wm.request({"cmd": "set_night_light", "on": on}, on_night_state)
    return 0
end

function on_brightness_set(row, values, error):
    if values == None:
        call eprint("luxos-control-center: brightness: " + String(error))
    end
    call on_slider_done(row, 0, 0)
    return 0
end
