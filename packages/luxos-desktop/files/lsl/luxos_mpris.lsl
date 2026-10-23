# LuxOS - prehravace hudby a videa (MPRIS) rizene udalostmi D-Bus, bez dotazovani (prepis luxos_mpris.py).
# Jeden sdileny hlidac na proces (v luxos-hub ho pouziva Ovladaci centrum i volba "neuspavat pri prehravani"):
#   call mpris.init(session_bus)      jednou; stav drzi z PropertiesChanged a NameOwnerChanged
#   call mpris.connect(f)             f() po zmene (stav, metadata, prehravac prisel/odesel)
#   mpris.current()                   hrajici prehravac (jinak pozastaveny s titulkem) nebo None
#   mpris.playing()                   True, kdyz aspon jeden prehravac hraje
#   call mpris.send(name, "PlayPause") asynchronni volani; ikona se zmeni hned (optimisticky)
load luxos_glib, glib as glib
load luxos_gio, gio as gio

PREFIX = "org.mpris.MediaPlayer2."
PATH = "/org/mpris/MediaPlayer2"
IFACE = "org.mpris.MediaPlayer2.Player"
PROPS = "org.freedesktop.DBus.Properties"

bus = 0
players = {}        # dobre znamy nazev -> vlastnosti Player
owners = {}         # dobre znamy nazev -> unikatni nazev (odesilatel signalu)
callbacks = []
idle_pending = False
ready = False

function capitalize(name):
    if name == "":
        return name
    end
    return name[0:1].upper() + name[1:].lower()
end

function text_of(value):
    if value == None:
        return ""
    end
    return String(value)
end

# Slovnik pro UI z vlastnosti MPRIS (cista funkce)
function player_state(name, props):
    meta = props.get("Metadata")
    if meta == None:
        meta = {}
    end
    artist = meta.get("xesam:artist")
    artist_text = ""
    if artist != None:
        if type(artist) == "List":
            parts = []
            for a in artist:
                parts.append(String(a))
            end
            first = True
            for p in parts:
                if not first:
                    artist_text = artist_text + ", "
                end
                artist_text = artist_text + p
                first = False
            end
        else:
            artist_text = String(artist)
        end
    end
    status = props.get("PlaybackStatus")
    if status == None or status == "":
        status = "Stopped"
    end
    app = name[len(PREFIX):].split(".")[0]
    can_next = props.get("CanGoNext")
    if can_next == None:
        can_next = True
    end
    can_prev = props.get("CanGoPrevious")
    if can_prev == None:
        can_prev = True
    end
    return {"bus": name, "app": capitalize(app), "title": text_of(meta.get("xesam:title")), "artist": artist_text,
            "art": text_of(meta.get("mpris:artUrl")), "status": status, "playing": status == "Playing",
            "can_next": can_next == True, "can_prev": can_prev == True}
end

# {nazev: vlastnosti} -> stav prehravace k zobrazeni: hrajici, jinak pozastaveny nebo s titulkem
function pick_current(table):
    best = None
    for name in sorted(table.keys()):
        st = player_state(name, table[name])
        if st["playing"]:
            return st
        end
        if best == None and (st["title"] != "" or st["status"] == "Paused"):
            best = st
        end
    end
    return best
end

# ---- verejne API -----------------------------------------------------------------------------------

function init(connection):
    global bus, ready
    if ready:
        return 0
    end
    bus = connection
    ready = True
    call gio.subscribe_data(bus, "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged", "/org/freedesktop/DBus",
                            "org.mpris.MediaPlayer2", gio.SIGNAL_MATCH_ARG0_NAMESPACE, on_owner, 0)
    call gio.subscribe_data(bus, "", PROPS, "PropertiesChanged", PATH, IFACE, gio.SIGNAL_NONE, on_props, 0)
    call gio.call_async(bus, "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames", [], "", 3000, on_names, 0)
    return 0
end

function connect(handler):
    callbacks.append(handler)
    return 0
end

function current():
    return pick_current(players)
end

function playing():
    for name in players.keys():
        if players[name].get("PlaybackStatus") == "Playing":
            return True
        end
    end
    return False
end

# Ovladani prehravace; PlayPause hned prepne stav lokalne, skutecny stav pak prijde signalem
function send(name, method):
    if name not in players:
        return 0
    end
    if method == "PlayPause":
        props = players[name]
        if props.get("PlaybackStatus") == "Playing":
            props["PlaybackStatus"] = "Paused"
        else:
            props["PlaybackStatus"] = "Playing"
        end
        call changed()
    end
    call gio.call_async(bus, name, PATH, IFACE, method, [], "", 3000, on_called, name)
    return 0
end

# ---- udalosti ----------------------------------------------------------------------------------------

# Davka signalu (stav + metadata) -> jedno volani posluchacu
function changed():
    global idle_pending
    if not idle_pending:
        idle_pending = True
        call glib.idle_add(emit)
    end
    return 0
end

function emit():
    global idle_pending
    idle_pending = False
    for handler in callbacks:
        try:
            call handler()
        else:
            call eprint("luxos_mpris: " + String(last_error()))
        end
    end
    return False
end

function on_names(unused, values, error):
    if values == None:
        return 0
    end
    for name in values[0]:
        if name.startswith(PREFIX):
            call add(name, "")
        end
    end
    return 0
end

function add(name, owner):
    if name not in players:
        players[name] = {}
    end
    if owner != "":
        owners[name] = owner
    else:
        call gio.call_async(bus, "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "GetNameOwner",
                            [name], "(s)", 3000, on_owner_reply, name)
    end
    call fetch(name)
    return 0
end

function fetch(name):
    call gio.call_async(bus, name, PATH, PROPS, "GetAll", [IFACE], "(s)", 3000, on_all, name)
    return 0
end

function on_owner_reply(name, values, error):
    if values != None:
        owners[name] = values[0]
    end
    return 0
end

function on_all(name, values, error):
    if values == None:
        return 0
    end
    if name in players:
        players[name].update(values[0])
        call changed()
    end
    return 0
end

function on_owner(unused, sender, path, interface, signal, values):
    name = values[0]
    new_owner = values[2]
    if not name.startswith(PREFIX):
        return 0
    end
    if new_owner != "":
        call add(name, new_owner)
    else:
        call players.pop(name, None)
        call owners.pop(name, None)
        call changed()
    end
    return 0
end

function on_props(unused, sender, path, interface, signal, values):
    changed_props = values[1]
    invalidated = values[2]
    for name in sorted(owners.keys()):
        if owners[name] != sender or name not in players:
            continue
        end
        players[name].update(changed_props)
        if len(invalidated) > 0:
            call fetch(name)
        end
        call changed()
    end
    return 0
end

function on_called(name, values, error):
    # Prehravace, ktere zmenu neohlasi signalem: jeden dotaz na skutecny stav
    call glib.timeout_add_data(700, refetch, name)
    return 0
end

function refetch(name):
    if name in players:
        call fetch(name)
    end
    return False
end
