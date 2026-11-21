# LuxOS - pripojeni vymenitelnych disku po zasunuti v relaci na Waylandu (na X11 to dela thunar-volman pres Thunar
# --daemon). Bezi v luxos-backdrop; `load luxos_automount as automount`, `call automount.start()`.
#
# Nastaveni sdili s thunar-volman (kanal xfconf thunar-volman, Nastaveni > Vymenitelne disky), cte se pri kazde udalosti:
#   /automount-drives/enabled   USB disky a karty, /automount-media/enabled   CD/DVD,
#   /autobrowse/enabled         po pripojeni otevrit okno (vychozi aplikace pro slozky)
# Jen nove objevene souborove systemy (InterfacesAdded UDisks2), ne disky pripojene uz pri startu; jen ty, ktere
# UDisks2 oznaci k automatickemu pripojeni (HintAuto, ne HintSystem/HintIgnore - vnitrni disky nikdy), a bez
# dotazu na heslo (auth.no_user_interaction: neaktivni relace nebo cizi disk polkit odmitne, nic se nestane).
load glib, gio
load luxos_glib as lglib
load luxos_gio as lgio
load luxos_xfconf as xfconf

UDISKS = "org.freedesktop.UDisks2"
BLOCK = "org.freedesktop.UDisks2.Block"
FS = "org.freedesktop.UDisks2.Filesystem"
DRIVE = "org.freedesktop.UDisks2.Drive"

S = {"bus": 0}

function start():
    try:
        S["bus"] = gio.system_bus()
    else:
        return False
    end
    call gio.subscribe_values(S["bus"], UDISKS, "org.freedesktop.DBus.ObjectManager", "InterfacesAdded", "/org/freedesktop/UDisks2", on_added)
    return True
end

function enabled(conf, prop):
    return conf.get(prop, "false") == "true"
end

function props(path, iface):
    out = {}
    safe:
        out = gio.get_all_properties(S["bus"], UDISKS, path, iface)
    end
    return out
end

# Novy objekt nebo nove rozhrani (medium vlozene do ctecky): values = [cesta, {rozhrani: vlastnosti}]
function on_added(sender, path, interface, signal, values):
    object = values[0]
    if not (FS in values[1]):
        return 0
    end
    if len(values[1][FS].get("MountPoints", [])) > 0:
        return 0
    end
    block = values[1].get(BLOCK, None)
    if block == None:
        block = props(object, BLOCK)
    end
    if not block.get("HintAuto", False) or block.get("HintSystem", True) or block.get("HintIgnore", False):
        return 0
    end
    conf = xfconf.channel("thunar-volman")
    optical = False
    drive = block.get("Drive", "/")
    if drive != "/" and drive != "":
        optical = props(drive, DRIVE).get("Optical", "") != ""
    end
    if (optical and not enabled(conf, "/automount-media/enabled")) or (not optical and not enabled(conf, "/automount-drives/enabled")):
        return 0
    end
    call lgio.call_async(S["bus"], UDISKS, object, FS, "Mount", [{"auth.no_user_interaction": True}], "(a{sv})", 30000, on_mounted, object)
    return 0
end

function on_mounted(object, reply, error):
    if reply == None:
        call glib.report("luxos-automount: " + object + ": " + String(error) + "\n")
        return 0
    end
    if enabled(xfconf.channel("thunar-volman"), "/autobrowse/enabled"):
        call lglib.launch_uri(glib.filename_to_uri(reply[0]))
    end
    return 0
end
