# LuxOS - cteni kanalu xfconf primo ze souboru (na Waylandu xfconfd nemusi bezet): systemovy vychozi kanal
# z /etc/xdg a uzivatelsky v ~/.config, ktery ma prednost. Vlastnosti jako {"/saver/idle-activation/delay": "10"}.
#
#   xfconf.channel(nazev) -> {cesta: hodnota}     cela vlastnost jako text (bool "true"/"false")
#   xfconf.user_path(nazev)                       soubor uzivatele (pro gio.file_monitor)
load glib
load luxos_glib as lglib
load luxos_text as text

SYSTEM = "/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/"

function user_path(name):
    return glib.user_config_dir() + "/xfce4/xfconf/xfce-perchannel-xml/" + name + ".xml"
end

function attr(line, name):
    cut = line.find(name + "=\"")
    if cut < 0:
        return ""
    end
    rest = line[cut + len(name) + 2:]
    return rest[0:rest.find("\"")]
end

# vnorene <property> skladaji cestu
function read_into(path, into):
    stack = []
    for raw in text.lines(lglib.read_text(path)):
        line = raw.strip()
        if line.startswith("<property "):
            name = attr(line, "name")
            if line.endswith("/>"):
                into["/" + text.join(stack + [name], "/")] = attr(line, "value")
            else:
                stack.append(name)
            end
        elif line.startswith("</property>") and len(stack) > 0:
            call stack.pop()
        end
    end
    return into
end

function channel(name):
    return read_into(user_path(name), read_into(SYSTEM + name + ".xml", {}))
end
