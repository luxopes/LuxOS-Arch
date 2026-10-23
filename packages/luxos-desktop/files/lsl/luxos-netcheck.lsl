# LuxOS - upozorneni "!" v horni liste: pripojeno k siti, ale internet neni dostupny (jako v Androidu)
#   luxos-netcheck          vystup pro plugin genmon (prazdny, kdyz je vse v poradku)
#   luxos-netcheck click    klik na ikonu: prihlasovaci stranka site, nebo Ovladaci centrum
# Obnovu pluginu pri zmene site posila luxos-hub (bez pravidelneho dotazovani).
# Stav bere primo z NetworkManageru pres D-Bus (nmcli stal ~20 ms na kazde spusteni).
load gio
load luxos_sys
load luxos_i18n as i18n

# NMConnectivityState a NMState z org.freedesktop.NetworkManager
CONNECTIVITY = {0: "unknown", 1: "none", 2: "portal", 3: "limited", 4: "full"}
NM_STATE_CONNECTED_LOCAL = 60

function nm_uint(property):
    bus = gio.system_bus()
    text = gio.get_property(bus, "org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager",
                            "org.freedesktop.NetworkManager", property)
    # text GVariant "uint32 70"
    return Int(text.split(" ")[-1])
end

# full | limited | portal | none | unknown | offline (NetworkManager nebezi nebo neni pripojeno)
function state():
    result = "offline"
    try:
        if nm_uint("State") >= NM_STATE_CONNECTED_LOCAL:
            result = CONNECTIVITY.get(nm_uint("Connectivity"), "unknown")
        end
    else:
        result = "offline"
    end
    return result
end

function icon(tip):
    print "<icon>luxos-network-no-internet-symbolic</icon><tool>" + tip + "</tool><iconclick>luxos-netcheck click</iconclick>"
end

mode = "panel"
if arg_count() > 1:
    mode = arg(1)
end
if mode == "panel":
    s = state()
    if s == "portal":
        call icon(i18n.T("Sign in to the network to use the internet (click to open the sign-in page)"))
    elif s == "limited" or s == "none":
        call icon(i18n.T("Connected to the network, but the internet is not available"))
    else:
        print "<txt></txt>"
    end
elif mode == "click":
    if state() == "portal":
        # Prihlasovaci stranka verejne Wi-Fi se ukaze misto teto adresy
        call luxos_sys.exec(["xdg-open", "http://ping.archlinux.org/"])
        call exit(127)
    end
    call luxos_sys.exec(["luxos-cc-toggle"])
    call exit(127)
else:
    call luxos_sys.eprint("usage: luxos-netcheck [panel|click]")
    call exit(2)
end
