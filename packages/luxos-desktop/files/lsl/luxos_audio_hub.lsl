# LuxOS Zvuk - automaticke prepnuti vystupu na nove pripojene zarizeni (bezi uvnitr luxos-hub).
# `pactl subscribe` hlasi zmeny karet (monitor HDMI/DisplayPort zmeni dostupnost portu), serveru (vychozi
# vystup) a pridani/odebrani vystupu (USB, Bluetooth). Po davce udalosti (0,4 s) se spusti pomocny program
# `luxos_audio_switch.py check`, ktery porovna stav s minulym a prepne (profil karty, vychozi vystup,
# presun prehravanych zvuku), pri odpojeni vrati puvodni; rucni volbu uzivatele respektuje.
# Zmeny hlasitosti (udalosti 'change' na sink/source) pomocny program nespousti.
#   call audio.subscribe()   jen kdyz je pactl
load env
load luxos_glib, glib as glib

HELPER = "/usr/lib/luxos/python/luxos_audio_switch.py"

state = {"running": False, "pending": False, "armed": False, "started": 0, "fails": 0}

function helper_path():
    value = env.get("LUXOS_AUDIO_HELPER", "")
    if value == None or value == "":
        return HELPER
    end
    return value
end

function log(message):
    return eprint("luxos-hub: audio: " + message)
end

function subscribe():
    # vychozi stav po prihlaseni (co uz pripojene je, se neprepina)
    call check_now()
    call watch()
    return 0
end

function watch():
    state["started"] = glib.now()
    if glib.spawn_stream(["env", "LC_ALL=C", "pactl", "subscribe"], on_events, 0) == 0:
        call log("pactl subscribe could not be started")
    end
    return False
end

function relevant(chunk):
    return chunk.find(" on card #") >= 0 or chunk.find(" on server") >= 0 or chunk.find("'new' on sink #") >= 0 or chunk.find("'remove' on sink #") >= 0
end

function on_events(unused, chunk):
    if chunk == "":
        # pipewire-pulse skoncil (restart, odhlaseni): znovu za 3 s, pri opakovanem rychlem konci za minutu
        if glib.now() - state["started"] < 10:
            state["fails"] = state["fails"] + 1
        else:
            state["fails"] = 0
        end
        delay = 3
        if state["fails"] > 3:
            delay = 60
        end
        call glib.timeout_add_seconds(delay, watch)
        return 0
    end
    if relevant(chunk) and not state["armed"]:
        state["armed"] = True
        call glib.timeout_add_data(400, on_settled, 0)
    end
    return 0
end

function on_settled(unused):
    state["armed"] = False
    call check_now()
    return False
end

function check_now():
    if state["running"]:
        state["pending"] = True
        return 0
    end
    state["running"] = True
    if glib.spawn_watched_data(["python3", "-I", helper_path(), "check"], on_checked, 0) == 0:
        state["running"] = False
        call log("helper " + helper_path() + " could not be started")
    end
    return 0
end

function on_checked(unused, pid, status):
    state["running"] = False
    if state["pending"]:
        state["pending"] = False
        call check_now()
    end
    return 0
end
