# LuxOS - Nastaveni > Zvuk (drive pavucontrol): vystupni a vstupni zarizeni, hlasitost, ztlumeni a hlasitost
# jednotlivych aplikaci.
#
# Mluvi se serverem PulseAudio/PipeWire pres `pactl` (JSON: -f json), jako luxos-audio-switch a lista. Pri zobrazene
# strance bezi `pactl subscribe`: zmena hlasitosti klavesou nebo koleckem nad ikonou zvuku v liste, nove prehravana
# aplikace nebo pripojena sluchatka se ukazou hned (po davce udalosti 150 ms se hodnoty nactou znovu a promitnou
# do ovladacich prvku BEZ zapisu zpet). Pri odchodu ze stranky a zavreni okna se sledovani ukonci.
# Zmena vystupu: vychozi zarizeni a presun uz hrajicich zvuku (stejne jako luxos-audio-switch).
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_sys as lsys
load luxos_settings_ui as ui
load json

DEFAULT_SINK = "@DEFAULT_SINK@"
DEFAULT_SOURCE = "@DEFAULT_SOURCE@"
EVENT_DELAY = 150       # ms: davka udalosti ze serveru se vyridi najednou
SLIDER_WIDTH = 240

app = {"hidden": True, "stream": 0, "armed": False, "restart": 0, "page": 0, "started": 0,
       "sinks": [], "sources": [], "streams": [], "default_sink": "", "default_source": "",
       "out_combo": 0, "in_combo": 0, "out_vol": 0, "in_vol": 0, "out_mute": 0, "in_mute": 0,
       "out_names": [], "in_names": [], "apps_group": 0, "stream_keys": [], "stream_sliders": {},
       "shown": {"out_vol": -1, "in_vol": -1}, "available": True}

# ---- pactl ------------------------------------------------------------------------------------------------

function pactl(args):
    return ui.run(["env", "LC_ALL=C", "pactl"] + args)
end

function pactl_json(args):
    out = pactl(["-f", "json"] + args)
    if out == "":
        return None
    end
    data = None
    try:
        data = json.decode(out)
    else:
        return None
    end
    return data
end

function as_list(value):
    if type(value) == "List":
        return value
    end
    return []
end

function get(dict, key, default):
    if type(dict) == "Dictionary" and key in dict and dict[key] != None:
        return dict[key]
    end
    return default
end

# Nejvyssi hodnota kanalu v procentech (pactl: 65536 = 100 %)
function volume_percent(vol):
    best = 0
    if type(vol) != "Dictionary":
        return 0
    end
    for channel in vol:
        entry = vol[channel]
        value = get(entry, "value", 0)
        pct = Int(Float(value) * 100.0 / 65536.0 + 0.5)
        if pct > best:
            best = pct
        end
    end
    return best
end

function device(item):
    return {"name": String(get(item, "name", "")), "desc": String(get(item, "description", "")),
            "vol": volume_percent(get(item, "volume", None)), "mute": get(item, "mute", False) == True,
            "state": String(get(item, "state", ""))}
end

function read_all():
    info = pactl_json(["info"])
    if info == None:
        app["available"] = False
        return False
    end
    app["available"] = True
    app["default_sink"] = String(get(info, "default_sink_name", ""))
    app["default_source"] = String(get(info, "default_source_name", ""))
    app["sinks"] = [device(s) for s in as_list(pactl_json(["list", "sinks"]))]
    # vstupy: bez "monitoru" vystupu (zvuk, ktery hraje pocitac)
    app["sources"] = [d for d in [device(s) for s in as_list(pactl_json(["list", "sources"]))] if not d["name"].endswith(".monitor")]
    streams = []
    for item in as_list(pactl_json(["list", "sink-inputs"])):
        props = get(item, "properties", {})
        name = String(get(props, "application.name", ""))
        if name == "":
            name = String(get(props, "media.name", ""))
        end
        if name == "":
            name = i18n.T("Unknown app")
        end
        streams.append({"id": Int(get(item, "index", -1)), "name": name, "vol": volume_percent(get(item, "volume", None)),
                        "mute": get(item, "mute", False) == True})
    end
    app["streams"] = streams
    return True
end

function find(devices, name):
    for d in devices:
        if d["name"] == name:
            return d
        end
    end
    if len(devices) > 0:
        return devices[0]
    end
    return None
end

# ---- zapis ------------------------------------------------------------------------------------------------

function on_out_volume(unused, value):
    # zmena, kterou jsme sami promitli do posuvniku, se nezapisuje zpet
    if value == app["shown"]["out_vol"]:
        return 0
    end
    app["shown"]["out_vol"] = value
    call ui.launch(["pactl", "set-sink-volume", DEFAULT_SINK, String(value) + "%"])
    return 0
end

function on_in_volume(unused, value):
    if value == app["shown"]["in_vol"]:
        return 0
    end
    app["shown"]["in_vol"] = value
    call ui.launch(["pactl", "set-source-volume", DEFAULT_SOURCE, String(value) + "%"])
    return 0
end

function on_out_mute(unused, on):
    call ui.launch(["pactl", "set-sink-mute", DEFAULT_SINK, "1" if on else "0"])
    return 0
end

function on_in_mute(unused, on):
    call ui.launch(["pactl", "set-source-mute", DEFAULT_SOURCE, "1" if on else "0"])
    return 0
end

# Vychozi vystup a presun uz hrajicich zvuku na nej (jinak by hrala dal na starem)
function on_out_device(unused, name):
    if name == "" or name == app["default_sink"]:
        return 0
    end
    app["default_sink"] = name
    call pactl(["set-default-sink", name])
    for line in pactl(["list", "short", "sink-inputs"]).split("\n"):
        parts = line.split("\t")
        if len(parts) > 0 and parts[0].strip() != "":
            call pactl(["move-sink-input", parts[0].strip(), name])
        end
    end
    call refresh(0)
    return 0
end

function on_in_device(unused, name):
    if name == "" or name == app["default_source"]:
        return 0
    end
    app["default_source"] = name
    call pactl(["set-default-source", name])
    for line in pactl(["list", "short", "source-outputs"]).split("\n"):
        parts = line.split("\t")
        if len(parts) > 0 and parts[0].strip() != "":
            call pactl(["move-source-output", parts[0].strip(), name])
        end
    end
    call refresh(0)
    return 0
end

function on_stream_volume(id, value):
    key = "stream" + String(id)
    if value == app["shown"].get(key, -1):
        return 0
    end
    app["shown"][key] = value
    call ui.launch(["pactl", "set-sink-input-volume", String(id), String(value) + "%"])
    return 0
end

# ---- ovladaci prvky ---------------------------------------------------------------------------------------

function fill_combo(combo, devices, active):
    names = [d["name"] for d in devices]
    ui.state["quiet"] = True
    call gtk.combo_box_text_remove_all(combo)
    for d in devices:
        label = d["desc"] if d["desc"] != "" else d["name"]
        call gtk.combo_box_text_append(combo, d["name"], label)
    end
    if active != "":
        call ui.combo_set_active_id(combo, active)
    end
    ui.state["quiet"] = False
    return names
end

function set_slider(slider, key, value):
    app["shown"][key] = value
    ui.state["quiet"] = True
    call gtk.range_set_value(slider, Float(value))
    ui.state["quiet"] = False
    return 0
end

function device_rows(page, title, kind):
    g = ui.group(page, title)
    if kind == "out":
        combo = ui.combo([], "", "", on_out_device, 0)
        slider = ui.slider(0, 100, 0, SLIDER_WIDTH, on_out_volume, 0)
        sw = ui.switch(False, on_out_mute, 0)
        call ui.row(g, i18n.T("Output device"), "", combo)
        call ui.row(g, i18n.T("Output volume"), "", slider)
        call ui.row(g, i18n.T("Mute"), "", sw)
        app["out_combo"] = combo
        app["out_vol"] = slider
        app["out_mute"] = sw
    else:
        combo = ui.combo([], "", "", on_in_device, 0)
        slider = ui.slider(0, 100, 0, SLIDER_WIDTH, on_in_volume, 0)
        sw = ui.switch(False, on_in_mute, 0)
        call ui.row(g, i18n.T("Input device"), "", combo)
        call ui.row(g, i18n.T("Input volume"), "", slider)
        call ui.row(g, i18n.T("Mute microphone"), "", sw)
        app["in_combo"] = combo
        app["in_vol"] = slider
        app["in_mute"] = sw
    end
    return g
end

# Hodnoty serveru do ovladacich prvku (bez zapisu zpet)
function apply():
    if app["out_combo"] == 0:
        return 0
    end
    sinks = app["sinks"]
    sources = app["sources"]
    if [d["name"] for d in sinks] != app["out_names"]:
        app["out_names"] = fill_combo(app["out_combo"], sinks, app["default_sink"])
    else:
        ui.state["quiet"] = True
        call ui.combo_set_active_id(app["out_combo"], app["default_sink"])
        ui.state["quiet"] = False
    end
    if [d["name"] for d in sources] != app["in_names"]:
        app["in_names"] = fill_combo(app["in_combo"], sources, app["default_source"])
    else:
        ui.state["quiet"] = True
        call ui.combo_set_active_id(app["in_combo"], app["default_source"])
        ui.state["quiet"] = False
    end
    out = find(sinks, app["default_sink"])
    inp = find(sources, app["default_source"])
    call gtk.widget_set_sensitive(app["out_combo"], len(sinks) > 0)
    call gtk.widget_set_sensitive(app["out_vol"], out != None)
    call gtk.widget_set_sensitive(app["out_mute"], out != None)
    call gtk.widget_set_sensitive(app["in_combo"], len(sources) > 0)
    call gtk.widget_set_sensitive(app["in_vol"], inp != None)
    call gtk.widget_set_sensitive(app["in_mute"], inp != None)
    if out != None:
        call set_slider(app["out_vol"], "out_vol", min(100, out["vol"]))
        call ui.switch_set(app["out_mute"], out["mute"])
    end
    if inp != None:
        call set_slider(app["in_vol"], "in_vol", min(100, inp["vol"]))
        call ui.switch_set(app["in_mute"], inp["mute"])
    end
    call apply_streams()
    return 0
end

# Aplikace, ktere prave hraji: radky se prestavi jen pri zmene seznamu, jinak se jen posunou posuvniky
function apply_streams():
    g = app["apps_group"]
    keys = [String(s["id"]) + ":" + s["name"] for s in app["streams"]]
    if keys != app["stream_keys"]:
        app["stream_keys"] = keys
        app["stream_sliders"] = {}
        for child in gtk.container_get_children(g["box"]):
            call gtk.widget_destroy(child)
        end
        g["rows"] = 0
        if len(app["streams"]) == 0:
            call ui.row(g, i18n.T("Apps that play sound appear here."), "", 0)
        end
        for s in app["streams"]:
            slider = ui.slider(0, 100, min(100, s["vol"]), SLIDER_WIDTH, on_stream_volume, s["id"])
            app["shown"]["stream" + String(s["id"])] = min(100, s["vol"])
            app["stream_sliders"][s["id"]] = slider
            call ui.row(g, s["name"], "", slider)
        end
        call gtk.widget_show_all(g["box"])
        return 0
    end
    for s in app["streams"]:
        if s["id"] in app["stream_sliders"]:
            call set_slider(app["stream_sliders"][s["id"]], "stream" + String(s["id"]), min(100, s["vol"]))
        end
    end
    return 0
end

function refresh(unused):
    app["armed"] = False
    if app["hidden"]:
        return False
    end
    call read_all()
    call apply()
    return False
end

# ---- sledovani serveru ------------------------------------------------------------------------------------

function on_events(unused, chunk):
    if chunk == "":
        app["stream"] = 0
        # server skoncil (restart PipeWire): zkusit znovu, dokud je stranka videt
        if not app["hidden"] and app["restart"] == 0:
            app["restart"] = glib.timeout_add_seconds_data(3, restart_watch, 0)
        end
        return 0
    end
    if not app["armed"] and not app["hidden"]:
        app["armed"] = True
        call glib.timeout_add_data(EVENT_DELAY, refresh, 0)
    end
    return 0
end

function restart_watch(unused):
    app["restart"] = 0
    if not app["hidden"] and app["stream"] == 0:
        call watch()
    end
    return False
end

function watch():
    app["stream"] = glib.spawn_stream(["env", "LC_ALL=C", "pactl", "subscribe"], on_events, 0)
    return 0
end

function show(host):
    if not app["hidden"]:
        return 0
    end
    app["hidden"] = False
    call refresh(0)
    if app["stream"] == 0:
        call watch()
    end
    return 0
end

function leave(host):
    app["hidden"] = True
    if app["restart"] != 0:
        call glib.source_remove(app["restart"])
        app["restart"] = 0
    end
    pid = app["stream"]
    app["stream"] = 0
    if pid != 0:
        call lsys.kill(pid, 15)
    end
    return 0
end

# ---- stranka ----------------------------------------------------------------------------------------------

function build(host):
    app["out_names"] = []
    app["in_names"] = []
    app["stream_keys"] = []
    app["stream_sliders"] = {}
    app["shown"] = {"out_vol": -1, "in_vol": -1}
    page = ui.page_box()
    app["page"] = page
    call device_rows(page, i18n.T("Output"), "out")
    call device_rows(page, i18n.T("Input"), "in")
    app["apps_group"] = ui.group(page, i18n.T("Applications"))
    call read_all()
    if not app["available"]:
        g = ui.group(page, i18n.T("Sound"))
        call ui.row(g, i18n.T("The sound server is not running."), i18n.T("Sound settings need PipeWire or PulseAudio."), 0)
    end
    call apply()
    return page
end

function test(command, rest):
    return False
end
