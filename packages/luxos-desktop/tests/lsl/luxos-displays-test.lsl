# Logika luxos_displays.lsl bez kompozitoru (test_luxos_displays_wl.py): usporadani, plany rezimu,
# zrcadleni s meritkem a hledani ulozene sady. Vystup "ok NAZEV" nebo "FAIL NAZEV ..."; kod 1 pri chybe.
load luxos_displays as dw

failed = [0]

function expect(name, got, want):
    if got == want:
        print "ok " + name
    else:
        print "FAIL " + name + " got " + String(got) + " want " + String(want)
        failed[0] = failed[0] + 1
    end
end

function head(name, description, modes, x, enabled):
    cur = modes[0]
    for m in modes:
        if m[4] == 1:
            cur = m
        end
    end
    return {"head": 0, "name": name, "description": description, "enabled": enabled, "x": x, "y": 0,
            "width": cur[0], "height": cur[1], "refresh": cur[2], "scale": 1000, "transform": 0, "modes": modes,
            "key": name + "|" + description, "identity": dw.identity(name, description), "internal": dw.is_internal(name)}
end

LAPTOP = head("eDP-1", "BOE 0x0BCA (eDP-1)", [[1920, 1200, 60000, 1, 1], [1920, 1200, 48000, 0, 0], [1280, 800, 60000, 0, 0]], 0, True)
TV = head("HDMI-A-1", "Samsung TV 123 (HDMI-A-1)", [[3840, 2160, 60000, 1, 0], [1920, 1080, 60000, 0, 1], [1280, 720, 60000, 0, 0]], 1920, True)
PROJ = head("DP-2", "Epson EB 777 (DP-2)", [[1024, 768, 60000, 1, 1]], 3840, True)

# velikosti
call expect("logical 1.25", dw.logical(1920, 1200, 0, 1250), [1536, 960])
call expect("logical 1.75", dw.logical(2560, 1600, 0, 1750), [1462, 914])
call expect("logical rotated", dw.logical(1920, 1080, 1, 1000), [1080, 1920])
call expect("resolutions", dw.resolutions(TV), [[3840, 2160], [1920, 1080], [1280, 720]])
call expect("custom mode refused", dw.has_mode(TV, 1600, 900, 0), False)

# geometrie
call expect("touch", dw.touches([0, 0, 100, 100], [100, 50, 100, 100]), True)
call expect("corner only", dw.touches([0, 0, 100, 100], [100, 100, 100, 100]), False)
call expect("gap invalid", dw.valid({"a": [0, 0, 100, 100], "b": [150, 0, 100, 100]}), False)
call expect("overlap invalid", dw.valid({"a": [0, 0, 100, 100], "b": [50, 0, 100, 100]}), False)
r = {"a": [0, 0, 1920, 1080], "b": [1920, 0, 1280, 1024]}
call expect("drop below snaps to edge", dw.drop(r, "b", 300, 1300, "a", 0), {"a": [0, 0], "b": [300, 1080]})
call expect("drop with snap aligns", dw.drop(r, "b", 1950, 10, "a", 50), {"a": [0, 0], "b": [1920, 0]})
call expect("drop left normalizes", dw.drop(r, "b", -1500, 0, "a", 0), {"a": [1280, 0], "b": [0, 0]})
call expect("drop into overlap", dw.valid({"a": [0, 0, 1920, 1080], "b": dw.drop(r, "b", 500, 500, "a", 0)["b"] + [1280, 1024]}), True)

# plany
store = {"outputs": {}, "sets": {}}
outs = [TV, LAPTOP]
p = dw.plan(store, outs, "", "")
call expect("new set extends, built-in is main", [p["mode"], p["primary"]], ["extend", "eDP-1"])
call expect("new set keeps current places", [p["config"]["eDP-1"]["x"], p["config"]["HDMI-A-1"]["x"]], [0, 1920])
call expect("new monitor gets preferred mode", [p["config"]["HDMI-A-1"]["width"], p["config"]["HDMI-A-1"]["refresh"]], [3840, 60000])
p = dw.plan(store, outs, "internal", "")
call expect("internal only", [p["config"]["eDP-1"]["enabled"], p["config"]["HDMI-A-1"]["enabled"], p["primary"]], [True, False, "eDP-1"])
p = dw.plan(store, outs, "external", "")
call expect("external only", [p["config"]["eDP-1"]["enabled"], p["config"]["HDMI-A-1"]["enabled"], p["primary"], p["config"]["HDMI-A-1"]["x"]], [False, True, "HDMI-A-1", 0])

# zrcadleni: TV umi 1920x1200? ne -> doporuceny 3840x2160 s meritkem, logicka plocha pokryje vzor
p = dw.plan(store, outs, "mirror", "")
tv = p["config"]["HDMI-A-1"]
size = dw.config_size(tv)
# 16:9 televize pod 16:10 vzorem: vyska sedi na par px, vzor uprostred sirky (pruhy vlevo i vpravo)
call expect("mirror scale covers main", size[0] >= 1920 and size[1] >= 1200 and size[1] < 1210, True)
call expect("main at origin", [p["config"]["eDP-1"]["x"], p["config"]["eDP-1"]["y"]], [0, 0])
call expect("mirror centred on main", [abs(2 * tv["x"] + size[0] - 1920) <= 2, abs(2 * tv["y"] + size[1] - 1200) <= 2, tv["x"] < -50], [True, True, True])
call expect("centred mirror detected", dw.mirrored([[0, 0, 1920, 1200], [tv["x"], tv["y"], size[0], size[1]]]), True)
call expect("mirror config valid", dw.check_config(outs, p["config"], True), "")
call expect("origin mirror still detected", dw.mirrored([[0, 0, 1920, 1200], [0, 0, 2138, 1202]]), True)
call expect("side by side not mirrored", dw.mirrored([[0, 0, 1920, 1200], [1920, 0, 1920, 1200]]), False)
off = {"enabled": True, "width": 3840, "height": 2160, "refresh": 60000, "x": 100, "y": 0, "transform": 0, "scale": tv["scale"]}
call expect("off-centre mirror refused", dw.check_config(outs, {"eDP-1": p["config"]["eDP-1"], "HDMI-A-1": off}, True), "mirrored displays must share the centre")
outs3 = [LAPTOP, PROJ]
p = dw.plan(store, outs3, "mirror", "")
call expect("projector mirror shrinks", dw.config_size(p["config"]["DP-2"])[0] >= 1920, True)

# ulozeni a nalezeni sady i v jinych konektorech
config = dw.plan(store, outs, "extend", "")["config"]
config["HDMI-A-1"].update({"width": 1920, "height": 1080, "scale": 1250, "x": 0, "y": 0})
config["eDP-1"]["x"] = 1536
config["eDP-1"]["y"] = 0
call dw.remember(store, outs, config, "HDMI-A-1", "extend", True)
p = dw.plan(store, outs, "", "")
call expect("saved layout", [p["primary"], p["config"]["HDMI-A-1"]["x"], p["config"]["eDP-1"]["x"], p["config"]["HDMI-A-1"]["scale"]], ["HDMI-A-1", 0, 1536, 1250])
TV2 = head("HDMI-A-2", "Samsung TV 123 (HDMI-A-2)", TV["modes"], 1920, True)
p = dw.plan(store, [LAPTOP, TV2], "", "")
call expect("same monitors, other connector", [p["primary"], p["config"]["HDMI-A-2"]["x"], p["config"]["eDP-1"]["x"]], ["HDMI-A-2", 0, 1536])
call dw.remember(store, outs, config, "HDMI-A-1", "mirror", False)
p = dw.plan(store, outs, "extend", "")
call expect("mirror keeps stored places", p["config"]["eDP-1"]["x"], 1536)
call expect("bad config refused", dw.check_config(outs, {"eDP-1": {"enabled": True, "width": 1920, "height": 1200, "refresh": 60000, "x": 5000, "y": 0, "transform": 0, "scale": 1000}, "HDMI-A-1": config["HDMI-A-1"]}, False), "displays overlap or have a gap")
call expect("unknown mode refused", dw.check_config(outs, {"eDP-1": {"enabled": True, "width": 800, "height": 600, "refresh": 60000, "x": 0, "y": 0, "transform": 0, "scale": 1000}, "HDMI-A-1": {"enabled": False}}, False), "unsupported mode for eDP-1")
call expect("all off refused", dw.check_config(outs, {"eDP-1": {"enabled": False}, "HDMI-A-1": {"enabled": False}}, False), "no display enabled")

if failed[0] > 0:
    exit(1)
end
