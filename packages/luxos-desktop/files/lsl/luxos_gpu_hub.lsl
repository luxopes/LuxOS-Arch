# LuxOS - grafika podle rezimu napajeni (bezi uvnitr luxos-hub): po prihlaseni a pri kazde zmene profilu
# power-profiles-daemon (signal PropertiesChanged s ActiveProfile, bez dotazovani) spusti `luxos-gpu apply`,
# ktery srovna prepisy Flatpaku, PowerMizer NVIDIA a samostatnou grafiku AMD s aktualnim profilem.
# Behem behu dalsi zmena jen poznaci, ze se ma spustit znovu (vzdy podle posledniho stavu).
#   call gpu.subscribe(system_bus)
load env
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_text as text

PPD_PATHS = ["/org/freedesktop/UPower/PowerProfiles", "/net/hadess/PowerProfiles"]

state = {"running": False, "pending": False, "timer": 0}

function program():
    value = env.get("LUXOS_GPU", "")
    if value == None or value == "":
        return "luxos-gpu"
    end
    return value
end

function log(message):
    return eprint("luxos-hub: gpu: " + message)
end

function subscribe(system):
    if glib.find_program_in_path(program()) == "":
        return 0
    end
    if system != 0:
        for path in PPD_PATHS:
            call gio.subscribe_values(system, "", "org.freedesktop.DBus.Properties", "PropertiesChanged", path, on_props)
        end
    end
    # Po prihlaseni (zbytky po padu, jiny profil nez pri odhlaseni); start relace ma prednost
    call glib.timeout_add_seconds(text.to_int(env.get("LUXOS_GPU_DELAY", ""), 2), on_start)
    return 0
end

function on_start():
    call schedule()
    return False
end

function on_props(sender, path, interface, signal, values):
    if len(values) < 2 or type(values[1]) != "Dictionary":
        return 0
    end
    if "ActiveProfile" in values[1]:
        # oba objekty (novy i starsi nazev) hlasi stejnou zmenu: jedno spusteni po 300 ms
        if state["timer"] != 0:
            call glib.source_remove(state["timer"])
        end
        state["timer"] = glib.timeout_add(300, on_timer)
    end
    return 0
end

function on_timer():
    state["timer"] = 0
    call schedule()
    return False
end

function schedule():
    if state["running"]:
        state["pending"] = True
        return 0
    end
    state["running"] = True
    state["pending"] = False
    if glib.spawn_watched_data([program(), "apply"], on_done, 0) == 0:
        state["running"] = False
        call log(program() + " could not be started")
    end
    return 0
end

function on_done(bound, pid, status):
    state["running"] = False
    if state["pending"]:
        call schedule()
    end
    return 0
end
