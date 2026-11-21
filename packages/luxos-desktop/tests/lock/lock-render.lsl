# Testy: kresba zamku a prihlaseni (luxos_lock_draw) bez kompozitoru do PNG v pixelech zarizeni, stejne stavy
# jako snimky X11 (tests/lock/x11_goldens.py), a cena snimku.
#
#   lock-render VYSTUP SIRKA VYSKA MERITKO TAPETA STAV...
# Stavy: idle prompt typing wrong caps fingerprint lockout battery layout power enter-50 shake greeter
# greeter-wrong greeter-users. Za kazdy stav "frame <stav> <prumer us> <max us>" (10 snimku po zahrivacim).
load cairo, glib, env, math
load luxos_glib as lglib
load luxos_i18n as i18n
load luxos_lock_draw as draw

RUNS = 10
NAME = "Alex Novák"

function base_ui(mode):
    ui = draw.new_ui(mode)
    ui["clock"] = "9:41"
    ui["date"] = i18n.format_tm(lglib.gmtime(lglib.timegm(2026, 11, 20, 9, 41, 0)), "long")
    ui["lang"] = i18n.lang()
    ui["name"] = NAME
    ui["placeholder"] = i18n.T("Enter Password")
    ui["caps_text"] = i18n.T("Caps Lock is on")
    ui["power"] = [["suspend", i18n.T("Sleep")], ["reboot", i18n.T("Restart")], ["poweroff", i18n.T("Shut Down")]]
    ui["reveal"] = 1.0
    ui["rev_to"] = 1.0
    return ui
end

# LOCK_RENDER_CLOCK, _DATE, _NAME, _NET (wifi/wired) a _SESSIONS=1: jine vstupy (srovnani se snimkem z VM)
function overrides(ui):
    if env.get("LOCK_RENDER_CLOCK", "") != "":
        ui["clock"] = env.get("LOCK_RENDER_CLOCK", "")
        ui["date"] = env.get("LOCK_RENDER_DATE", "")
    end
    if env.get("LOCK_RENDER_NAME", "") != "":
        ui["name"] = env.get("LOCK_RENDER_NAME", "")
        if len(ui["users"]) > 0:
            ui["users"][0]["real"] = ui["name"]
        end
    end
    if env.get("LOCK_RENDER_NET", "") != "":
        ui["net"] = [env.get("LOCK_RENDER_NET", ""), 3]
    end
    if env.get("LOCK_RENDER_SESSIONS", "") == "1":
        ui["sessions"] = [ui["sessions"][0]] if len(ui["sessions"]) > 0 else []
    end
    return ui
end

function state_ui(name):
    if name.startswith("greeter"):
        ui = base_ui("greeter")
        # stejne jako luxos-greeter --demo
        ui["sessions"] = ["Xfce Session", "Openbox"]
        ui["users"] = [{"real": "Anna Nováková", "face": None, "other": False}]
        if name == "greeter-users":
            ui["users"].append({"real": "Petr Svoboda", "face": None, "other": False})
            ui["users"].append({"real": "Eva Dvořáková", "face": None, "other": False})
        end
    else:
        ui = base_ui("lock")
    end
    if name == "idle":
        ui["reveal"] = 0.0
        ui["rev_to"] = 0.0
    elif name == "enter-50":
        ui["reveal"] = 0.5
    elif name == "typing":
        ui["length"] = 7
    elif name == "wrong" or name == "greeter-wrong" or name == "shake":
        ui["hint"] = i18n.T("Incorrect password. Try again.")
        ui["error"] = True
    elif name == "caps":
        ui["caps"] = True
        ui["length"] = 3
    elif name == "fingerprint":
        ui["hint"] = i18n.T("Touch the fingerprint sensor or enter your password")
    elif name == "lockout":
        ui["hint"] = i18n.TF("Too many failed attempts. The account is locked for %d min, then try again.", [1])
        ui["error"] = True
    elif name == "battery":
        ui["battery"] = [84, False]
        ui["net"] = ["wifi", 3]
    elif name == "layout":
        ui["layouts"] = 2
    elif name == "power":
        ui["hover"] = "reboot"
    end
    return ui
end

function main():
    out = arg(1)
    w = Int(arg(2))
    h = Int(arg(3))
    scale = Float(arg(4))
    wallpaper = arg(5)
    t0 = glib.monotonic_time()
    bd = draw.backdrop(wallpaper, w, h, scale)
    print "backdrop " + String((glib.monotonic_time() - t0) / 1000)
    surface = cairo.image_surface_create(cairo.FORMAT_ARGB32, Int(Float(w) * scale + 0.5), Int(Float(h) * scale + 0.5))
    for i in range(6, arg_count()):
        name = arg(i)
        ui = overrides(state_ui(name))
        ui["scale"] = scale
        if name == "shake":
            # stejna faze jako snimek X11: 30 ms z 480 ms zatreseni
            p = 30.0 / 480.0
            ui["shake"] = draw.cround(math.sin(p * cairo.PI * 8.0) * (1.0 - p) * 16.0 * max(0.55, Float(h) / 1080.0))
        end
        call draw.paint(surface, w, h, ui, bd)
        total = 0
        worst = 0
        for r in range(RUNS):
            t1 = glib.monotonic_time()
            call draw.paint(surface, w, h, ui, bd)
            call cairo.surface_flush(surface)
            dt = glib.monotonic_time() - t1
            total = total + dt
            worst = max(worst, dt)
        end
        print "frame " + name + " " + String(total / RUNS) + " " + String(worst)
        call cairo.surface_write_to_png(surface, out + "/" + name + ".png")
    end
    return 0
end

call main()
