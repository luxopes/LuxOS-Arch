# LuxOS - klik na Wi-Fi, Zvuk nebo Oznameni v horni liste: vyskakovaci okno z luxos_bar_popups.
#   luxos-bar-popup wifi|sound|notifications   prepne okno; bezici luxos-hub (nebo samostatny proces)
#                                             ho jen prepne, jinak se tento proces stane serverem a zustane
#                                             na pozadi (dalsi klik je okamzity)
#   luxos-bar-popup --panel wifi              ikona Wi-Fi pro plugin genmon v liste
#   luxos-bar-popup --app-name ID             nazev aplikace z ID.desktop jako v okne Oznameni
#   luxos-bar-popup --migrate-panel           starsi profil: ikona Wi-Fi do listy, nm-applet ze systray (jednou;
#                                             jinak to dela luxos-hub po prihlaseni)
load env
load luxos_gtk, gtk as gtk
load luxos_bar_popups as popups

function usage():
    call eprint("Usage: luxos-bar-popup wifi|sound|notifications | --panel wifi | --app-name DESKTOP-ID")
    return 2
end

function main():
    first = arg(1)
    if first == "--migrate-panel":
        # jako luxos-hub po prihlaseni: starsi profily dostanou ikonu Wi-Fi a text rozlozeni (jednou)
        config = env.get("XDG_CONFIG_HOME", "")
        if config == None or config == "":
            config = env.get("HOME", "") + "/.config"
        end
        call popups.migrate_panel(config + "/luxos")
        call popups.migrate_keyboard(config + "/luxos")
        return 0
    end
    if first == "--app-name":
        # nazev aplikace jako v okne Oznameni (z .desktop podle jazyka) - pro testy a ladeni
        print popups.app_name(arg(2))
        return 0
    end
    if first == "--panel":
        if arg(2) != "wifi":
            return usage()
        end
        print popups.panel_text("wifi")
        return 0
    end
    if first not in popups.KINDS:
        return usage()
    end
    code = popups.client_send(first)
    if code >= 0:
        return code
    end
    # nikdo neposloucha: samostatny server se stejnymi okny
    call gtk.init()
    if not popups.start_server(True):
        # mezitim ho spustil nekdo jiny
        code = popups.client_send(first)
        return max(code, 0)
    end
    call popups.toggle(first)
    call gtk.main()
    return 0
end

call exit(main())
