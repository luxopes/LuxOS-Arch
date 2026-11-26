# LuxOS - stranky okna Nastaveni (luxos-settings): poradi v postrannim panelu, ikony a moduly stranek.
#
# Stranka je modul luxos_page_<id>.lsl s funkci build(host) -> widget (svisly GtkBox bez titulku a okraju).
# host: {"window": okno, "wayland": bool, "args": argumenty z prikazove radky nebo z druheho spusteni, "page": id}.
# Volitelne funkce v polozce: leave(host) pri odchodu ze stranky a zavreni okna, cli(args) -> kod nebo None
# (prikazovy rezim stareho programu pred otevrenim okna; None = otevrit okno), show(host) pri kazdem zobrazeni
# (i s novymi argumenty z druheho spusteni), test(prikaz, zbytek) -> True kdyz prikaz testu obslouzila.
#
# Polozka: id, title (anglicky, preklad i18n), icon (symbolicka ikona), color (podklad ikony), group (oddil panelu),
# keywords (anglicky, prelozi se; hledani bez diakritiky), aliases (stare prikazy = odkaz na stranku),
# only ("wayland" / "x11" / "" = obe relace), exec (samostatna aplikace misto stranky), build/leave/cli/show/test.
load luxos_page_desktop as desktop
load luxos_page_appearance as appearance
load luxos_page_accessibility as accessibility
load luxos_page_windows as windows
load luxos_page_notifications as notifications
load luxos_page_power as power
load luxos_page_sound as sound
load luxos_page_lock as lock
load luxos_page_displays as displays
load luxos_page_keyboard as keyboard
load luxos_page_mouse as mouse
load luxos_page_bluetooth as bluetooth
load luxos_page_wifi as wifi
load luxos_page_firewall as firewall
load luxos_page_fingerprint as fingerprint
load luxos_page_profile as profile
load luxos_page_default_apps as default_apps
load luxos_page_login_items as login_items
load luxos_page_drives as drives
load luxos_page_app_reset as app_reset
load luxos_page_datetime as datetime
load luxos_page_language as language
load luxos_page_users as users
load luxos_page_security as security

function page(id, title, icon, color, group, keywords, aliases, module_fns):
    item = {"id": id, "title": title, "icon": icon, "color": color, "group": group, "keywords": keywords,
            "aliases": aliases, "only": "", "exec": [], "build": None, "leave": None, "cli": None, "show": None, "test": None}
    item.update(module_fns)
    return item
end

function app(id, title, icon, color, group, keywords, argv):
    item = page(id, title, icon, color, group, keywords, [], {})
    item["exec"] = argv
    return item
end

function all():
    out = []
    out.append(page("wifi", "Wi-Fi", "network-wireless-symbolic", "#3d7bff", 0, ["network", "internet", "qr code", "password", "share"],
             ["luxos-wifi-qr"], {"build": wifi.build, "cli": wifi.cli, "show": wifi.show, "leave": wifi.leave, "test": wifi.test}))
    out.append(page("bluetooth", "Bluetooth", "bluetooth-active-symbolic", "#3d7bff", 0, ["devices", "pair", "headphones", "mouse"],
             ["luxos-bluetooth"], {"build": bluetooth.build, "leave": bluetooth.leave, "show": bluetooth.show, "test": bluetooth.test}))
    out.append(app("network", "Network", "network-workgroup-symbolic", "#3d7bff", 0, ["router", "ip address", "dns", "ping", "speed"], ["luxos-router"]))
    out.append(page("firewall", "Firewall", "security-high-symbolic", "#ff9500", 0, ["ports", "ssh", "block", "allow", "security"],
             ["luxos-firewall-settings"], {"build": firewall.build, "show": firewall.show, "test": firewall.test}))
    out.append(page("security", "Privacy & Security", "security-medium-symbolic", "#34c759", 0,
             ["antivirus", "virus", "quarantine", "lux guard", "malware", "ransomware", "snapshots", "protection"],
             ["luxos-guard-settings"], {"build": security.build, "show": security.show, "test": security.test}))
    out.append(page("notifications", "Notifications", "preferences-system-notifications-symbolic", "#ff3b30", 1,
             ["do not disturb", "banners", "alerts", "sounds", "history"], [], {"build": notifications.build, "test": notifications.test}))
    out.append(page("sound", "Sound", "audio-volume-high-symbolic", "#ff2d55", 1,
             ["volume", "speakers", "microphone", "output", "input", "headphones", "mute", "bluetooth audio"], [],
             {"build": sound.build, "show": sound.show, "leave": sound.leave, "test": sound.test}))
    out.append(page("appearance", "Appearance", "dark-mode-symbolic", "#af52de", 2,
             ["dark mode", "light mode", "accent color", "theme", "icons", "fonts", "text size", "cursor"], [],
             {"build": appearance.build, "test": appearance.test}))
    out.append(page("accessibility", "Accessibility", "preferences-desktop-accessibility-symbolic", "#3d7bff", 2,
             ["reduce motion", "larger text", "contrast", "pointer size", "sticky keys", "zoom"], [],
             {"build": accessibility.build, "test": accessibility.test}))
    out.append(page("desktop", "Desktop & Dock", "user-desktop-symbolic", "#32ade6", 2,
             ["wallpaper", "widgets", "dock", "boot screen", "magnification"], ["xfdesktop-settings"],
             {"build": desktop.build, "leave": desktop.leave}))
    menu_bar = page("menu-bar", "Menu Bar", "view-more-symbolic", "#32ade6", 2,
             ["panel", "menu bar", "CPU", "items", "clock", "tray"], [], {"build": desktop.build_menu_bar})
    menu_bar["only"] = "wayland"
    out.append(menu_bar)
    out.append(page("windows", "Windows & Workspaces", "view-dual-symbolic", "#5856d6", 2,
             ["workspaces", "title bar", "double-click", "animation", "focus", "window manager"], [],
             {"build": windows.build, "test": windows.test}))
    out.append(page("displays", "Displays", "video-display-symbolic", "#3d7bff", 2,
             ["monitor", "resolution", "scale", "refresh rate", "night light", "mirror", "rotation"],
             ["luxos-display-settings", "luxos-displays-settings"],
             {"build": displays.build, "cli": displays.cli, "leave": displays.leave, "show": displays.show, "test": displays.test}))
    out.append(page("lock", "Screen Lock", "system-lock-screen-symbolic", "#30b0c7", 2,
             ["screen saver", "password", "lock", "inactivity", "sleep"], ["luxos-lock-settings"], {"build": lock.build}))
    out.append(page("power", "Battery & Power", "battery-good-symbolic", "#34c759", 3,
             ["battery", "power mode", "battery saver", "sleep", "lid", "screen off"], ["luxos-power"],
             {"build": power.build, "leave": power.leave, "show": power.show, "test": power.test}))
    out.append(page("keyboard", "Keyboard", "input-keyboard-symbolic", "#7d7aff", 3,
             ["layout", "shortcuts", "key repeat", "language", "input source"],
             ["luxos-keyboard-settings"], {"build": keyboard.build, "cli": keyboard.cli, "show": keyboard.show, "leave": keyboard.leave, "test": keyboard.test}))
    out.append(page("mouse", "Mouse & Touchpad", "input-mouse-symbolic", "#32ade6", 3,
             ["pointer speed", "natural scrolling", "tap to click", "trackpad", "scrolling", "inertia", "left-handed"],
             ["luxos-scrolling"], {"build": mouse.build, "cli": mouse.cli, "test": mouse.test}))
    out.append(app("printers", "Printers & Scanners", "printer-symbolic", "#ff9500", 3, ["print", "scan"], ["luxos-printers"]))
    out.append(app("phone", "Phone", "phone-symbolic", "#34c759", 3, ["companion", "android", "iphone"], ["luxos-companion"]))
    out.append(page("fingerprint", "Fingerprint", "fingerprint-symbolic", "#ff3b30", 4, ["touch id", "login", "unlock", "sudo"],
             ["luxos-fingerprint"], {"build": fingerprint.build, "leave": fingerprint.leave, "test": fingerprint.test}))
    out.append(page("profile", "Profile Picture", "avatar-default-symbolic", "#30b0c7", 4, ["account", "user", "photo", "avatar", "camera"],
             ["luxos-profile-picture"], {"build": profile.build, "cli": profile.cli, "show": profile.show, "leave": profile.leave, "test": profile.test}))
    out.append(page("users", "Users", "system-users-symbolic", "#ff9500", 4,
             ["accounts", "add user", "family", "child", "administrator", "password", "remove user"], [],
             {"build": users.build, "show": users.show, "test": users.test}))
    out.append(app("account", "LuxAI Account", "system-users-symbolic", "#5856d6", 4, ["luxai", "sign in", "subscription"], ["luxos-account"]))
    out.append(app("domain", "Organization Network", "network-server-symbolic", "#3d7bff", 4, ["domain", "active directory", "company"],
            ["luxos-domain-settings"]))
    out.append(page("datetime", "Date & Time", "preferences-system-time-symbolic", "#ff3b30", 5,
             ["clock", "time zone", "timezone", "ntp", "24-hour", "12-hour", "calendar"], [],
             {"build": datetime.build, "show": datetime.show, "leave": datetime.leave, "test": datetime.test}))
    out.append(page("language", "Language & Region", "preferences-desktop-locale-symbolic", "#3d7bff", 5,
             ["language", "region", "formats", "locale", "translation", "date format", "currency"], [],
             {"build": language.build, "test": language.test}))
    out.append(page("default-apps", "Default Apps", "applications-system-symbolic", "#3d7bff", 5,
             ["browser", "email", "mail", "file manager", "terminal", "open with", "mime"], [],
             {"build": default_apps.build, "test": default_apps.test}))
    out.append(page("login-items", "Login Items", "system-run-symbolic", "#00c7be", 5, ["autostart", "startup", "open at login", "background"],
             [], {"build": login_items.build, "test": login_items.test}))
    out.append(page("drives", "Removable Drives", "drive-removable-media-symbolic", "#ff9500", 5,
             ["usb", "automount", "media", "cd", "camera", "autorun"], [], {"build": drives.build, "test": drives.test}))
    out.append(page("app-reset", "Reset App Settings", "edit-undo-symbolic", "#ff3b30", 5, ["reset", "defaults", "backup"],
             ["luxos-app-reset"], {"build": app_reset.build, "cli": app_reset.cli, "test": app_reset.test}))
    out.append(app("backup", "Backups", "drive-harddisk-symbolic", "#5856d6", 5, ["backup", "restore", "external drive", "copy"],
            ["luxos-backup-gui"]))
    out.append(app("update", "Software Update", "software-update-available-symbolic", "#34c759", 5, ["updates", "upgrade", "kernel"], ["luxos-update"]))
    out.append(app("drivers", "Drivers", "application-x-firmware-symbolic", "#af52de", 5, ["nvidia", "graphics", "firmware"], ["luxos-drivers"]))
    xfce = app("xfce", "Xfce Settings Manager", "preferences-system-symbolic", "#30b0c7", 5, ["xfce", "advanced"], ["/usr/bin/xfce4-settings-manager"])
    xfce["only"] = "x11"
    out.append(xfce)
    out.append(app("about", "About This Computer", "computer-symbolic", "#5856d6", 5, ["system", "version", "hardware", "memory"], ["luxos-about"]))
    return out
end
