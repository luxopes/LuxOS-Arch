# LuxOS - hlavni monitor z luxwm pro Dock, oznameni a OSD (docs/developers/luxwm-ipc.md, Hlavni monitor):
# udalost IPC "output" nese nazev a polohu hlavniho monitoru, monitor GDK se najde podle pocatku.
#
#   follow(f)   f(monitor) hned, jak je hlavni monitor znamy, a po kazde jeho zmene (i kdyz GDK monitor
#               pridal az po udalosti luxwm); bez luxwm (labwc) se nevola - okno umisti kompozitor
load luxos_luxwm as wm
load luxos_layer as layer
load glib

P = {"handler": None, "origin": None, "monitor": 0}

function monitor_at(origin):
    for monitor in layer.monitors():
        g = layer.monitor_geometry(monitor)
        if g[0] == origin[0] and g[1] == origin[1]:
            return monitor
        end
    end
    return 0
end

function apply():
    if P["origin"] == None:
        return 0
    end
    monitor = monitor_at(P["origin"])
    if monitor != 0 and monitor != P["monitor"]:
        P["monitor"] = monitor
        call P["handler"](monitor)
    end
    return 0
end

function on_wm(event):
    if event.get("event") != "output":
        return 0
    end
    for o in event.get("outputs", []):
        if o.get("primary") == True and o.get("width", 0) > 0:
            P["origin"] = [o["x"], o["y"]]
        end
    end
    return apply()
end

function on_monitors(monitor, display):
    # odpojeny monitor: GDK objekt zanika, dalsi shoda podle pocatku ho nahradi
    P["monitor"] = 0
    return apply()
end

function follow(handler):
    P["handler"] = handler
    display = layer.default_display()
    call glib.signal_connect(display, "monitor-added", on_monitors, 1)
    call glib.signal_connect(display, "monitor-removed", on_monitors, 1)
    call wm.subscribe(["output"])
    call wm.connect(on_wm)
    return 0
end
