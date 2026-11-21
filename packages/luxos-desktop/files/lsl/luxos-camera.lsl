# LuxOS - Kamera: fotky a videa z webkamery ve stylu Photo Booth (drive Python).
#
#   luxos-camera                 okno s nahledem z kamery
#   luxos-camera --scan-wifi     naskenovat QR kod site Wi-Fi a pripojit se (luxos_qr, zxing-cpp)
#
# Nahled: v4l2src -> (jpegdec) -> videoflip (zrcadleni) -> tee -> appsink (luxos_camera); snimky vyzvedava
# casovac hlavni smycky a kresli cairo. Fotky (JPEG) jdou do $(xdg-user-dir PICTURES)/Camera, videa (s x264enc
# MP4, jinak WebM VP8 + Opus) do $(xdg-user-dir VIDEOS)/Camera. Nahravani videa jen prestavi pipeline s vetvi
# pro zapis. Nastaveni (rezim, samospoust, kamera, zrcadleni) v ~/.config/luxos/camera.json.
#
# Testovani bez kamery: LUXOS_CAMERA_TEST=1 (jedna testovaci kamera videotestsrc), 2 (dve), none (zadna kamera),
# busy (kamera obsazena), denied (chybi opravneni). LUXOS_CAMERA_TEST_IMAGE=obrazek.png: testovaci kamera
# ukazuje tento obrazek (napr. QR kod). LUXOS_VIDEO_DEV_DIR, LUXOS_NMCLI, LUXOS_ZXING_LIB jako luxos-wifi-qr.
load env, cairo, math, json
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_camera as camera
load luxos_qr as qr
load luxos_sys as sys
load luxos_testctl as testctl

SCAN_INTERVAL_MS = 300      # jak casto zkouset precist QR kod
TIMER_SECONDS = 3
CSS = ".preview { background-color: black; }\n.bar { padding: 10px 16px; border-top: 1px solid alpha(currentColor, 0.10); }\n.shutter, .shutter:hover, .shutter:active, .shutter:disabled, .thumb, .thumb:hover {\n    background-image: none; background-color: transparent; border: none; box-shadow: none;\n    padding: 0; min-width: 0; min-height: 0; }\n.mode button { padding: 4px 14px; font-weight: 600; }\n.timer { padding: 4px 10px; border-radius: 999px; }\n.countdown { color: white; font-size: 140px; font-weight: 800;\n             text-shadow: 0 2px 12px alpha(black, 0.6); }\n.rec { background-color: alpha(black, 0.55); color: white; border-radius: 999px;\n       padding: 4px 14px; margin-top: 14px; font-weight: 700; font-feature-settings: \"tnum\"; }\n.flash { background-color: white; }\n.state-title { font-size: 20px; font-weight: 800; }\n.dim { opacity: 0.65; }\n.code { font-family: monospace; padding: 6px 10px; border-radius: 8px;\n        background-color: alpha(currentColor, 0.07); }\n.scan-hint { background-color: alpha(black, 0.55); color: white; border-radius: 999px;\n             padding: 6px 16px; margin-bottom: 18px; font-weight: 600; }\n.primary { border-radius: 999px; padding: 6px 22px; font-weight: 700; background-image: none;\n           background-color: #3d7bff; color: white; border: none; box-shadow: none; }\n"
PHOTO_EXT = [".jpg", ".jpeg", ".png"]
MEDIA_EXT = [".jpg", ".jpeg", ".png", ".webm", ".mp4", ".mkv"]

ui = {"window": 0, "scan": False, "updating": False}
st = {"cfg": {}, "mode": "photo", "devices": [], "device": None, "caps": {}, "state": "", "nodes": [], "poll": 0,
    "recording": None, "stopping": False, "countdown": 0, "countdown_id": 0, "last": "", "thumb": 0,
    "thumb_video": False, "flash_start": 0, "scan_last": 0, "scan_paused": False, "notice_id": 0, "probe": 0}

function test_image():
    return env.get("LUXOS_CAMERA_TEST_IMAGE", "")
end

# ---- nastaveni a soubory ---------------------------------------------------------------------------------------

function config_dir():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == "":
        base = env.get("HOME", "") + "/.config"
    end
    return base + "/luxos"
end

function config_path():
    return config_dir() + "/camera.json"
end

function load_config():
    text = glib.read_text(config_path())
    data = None
    safe:
        data = json.decode(text)
    end
    if type(data) != "Dictionary":
        return {}
    end
    return data
end

function save_config():
    call glib.mkdir_p(config_dir())
    safe:
        call glib.write_atomic(config_path(), json.encode(st["cfg"]))
    end
end

# Slozka XDG (stejna jako xdg-user-dir) + podslozka Camera; GUserDirectory: PICTURES 4, VIDEOS 7
function user_dir(kind, fallback):
    base = glib.user_special_dir(kind).rstrip("/")
    home = env.get("HOME", "").rstrip("/")
    if base == "" or base == home:
        base = home + "/" + fallback
    end
    return base + "/Camera"
end

function pictures_dir():
    return user_dir(4, "Pictures")
end

function videos_dir():
    return user_dir(7, "Videos")
end

function unique_path(folder, prefix, ext):
    call glib.mkdir_p(folder)
    if not glib.is_dir(folder):
        return ""
    end
    stamp = sys.strftime_local("%Y-%m-%d %H.%M.%S")
    path = folder + "/" + prefix + " " + stamp + "." + ext
    n = 2
    while sys.lexists(path):
        path = folder + "/" + prefix + " " + stamp + " (" + String(n) + ")." + ext
        n += 1
    end
    return path
end

function has_ext(path, exts):
    low = path.lower()
    for e in exts:
        if low.endswith(e):
            return True
        end
    end
    return False
end

# [video enkoder, muxer, pripona, audio enkoder] podle dostupnych pluginu (VP8/WebM je v good), None bez enkoderu
function video_encoder():
    if camera.has("x264enc") and camera.has("mp4mux"):
        audio = ""
        for e in ["avenc_aac", "voaacenc", "fdkaacenc", "opusenc"]:
            if camera.has(e):
                audio = e
                break
            end
        end
        return ["x264enc tune=zerolatency speed-preset=veryfast bitrate=4000 key-int-max=60 ! video/x-h264,profile=high,stream-format=avc,alignment=au", "mp4mux", "mp4", audio]
    end
    if camera.has("vp8enc") and camera.has("webmmux"):
        unsafe:
            cpus = __lsl_qbe_s32(__lsl_qbe_call0(__lsl_symbol("g_get_num_processors")))
        end
        threads = max(1, min(4, cpus - 1))
        audio = ""
        if camera.has("opusenc"):
            audio = "opusenc"
        elif camera.has("vorbisenc"):
            audio = "vorbisenc"
        end
        return ["vp8enc deadline=1 cpu-used=8 threads=" + String(threads) + " end-usage=cbr target-bitrate=3000000 keyframe-max-dist=60", "webmmux", "webm", audio]
    end
    return None
end

function audio_source():
    if camera.test_mode() != "":
        return "audiotestsrc is-live=true wave=sine volume=0.05" if camera.has("audiotestsrc") else ""
    end
    # pipewire-pulse
    if camera.has("pulsesrc"):
        return "pulsesrc"
    end
    if camera.has("pipewiresrc"):
        return "pipewiresrc"
    end
    return ""
end

function accessible(path):
    unsafe:
        # access(R_OK | W_OK)
        return __lsl_qbe_call2(__lsl_symbol("access"), __lsl_address(path) + 16, 6) == 0
    end
end

# ---- okno ------------------------------------------------------------------------------------------------------

function label(text, css):
    l = gtk.label_new(text)
    call gtk.label_set_line_wrap(l, True)
    call gtk.label_set_justify(l, gtk.JUSTIFY_CENTER)
    for c in css.split(" "):
        if c != "":
            call gtk.widget_add_class(l, c)
        end
    end
    return l
end

function overlay_label(overlay, text, css, valign, name):
    l = label(text, css)
    call gtk.widget_set_halign(l, gtk.ALIGN_CENTER)
    call gtk.widget_set_valign(l, valign)
    call gtk.widget_set_name(l, name)
    call gtk.widget_set_no_show_all(l, True)
    call gtk.overlay_add_overlay(overlay, l)
    call gtk.overlay_set_pass_through(overlay, l)
    return l
end

function build():
    scan = ui["scan"]
    title = i18n.T("Join Wi-Fi with QR Code") if scan else i18n.T("Camera")
    window = gtk.window_new(title)
    ui["window"] = window
    call gtk.window_set_wmclass(window, "luxos-camera", "luxos-camera")
    call gtk.window_set_default_size(window, 860, 660)
    call gtk.widget_set_size_request(window, 480, 420)
    call gtk.window_set_icon_name(window, "luxos-camera")
    st["cfg"] = load_config()
    st["mode"] = "video" if st["cfg"].get("mode", "") == "video" else "photo"

    header = gtk.window_set_header(window, title)
    ui["mirror"] = gtk.toggle_button_new_empty()
    call gtk.container_add(ui["mirror"], gtk.image_new_from_icon_name("object-flip-horizontal-symbolic", gtk.ICON_MENU))
    call gtk.widget_set_tooltip(ui["mirror"], i18n.T("Mirror preview"))
    call gtk.connect_data(ui["mirror"], "toggled", 0, on_mirror, 0)
    call gtk.header_bar_pack_end(header, ui["mirror"])
    ui["combo"] = gtk.combo_box_text_new()
    call gtk.widget_set_tooltip(ui["combo"], i18n.T("Choose camera"))
    call gtk.widget_set_no_show_all(ui["combo"], True)
    call gtk.connect_data(ui["combo"], "changed", 0, on_camera_changed, 0)
    call gtk.header_bar_pack_end(header, ui["combo"])

    root = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.container_add(window, root)

    # Nahled + prekryvy (odpocet, nahravani, blesk, napoveda QR)
    overlay = gtk.overlay_new()
    call gtk.box_pack_start(root, overlay, True, True, 0)
    ui["stack"] = gtk.stack_new(False)
    call gtk.stack_set_transition_duration(ui["stack"], 150)
    call gtk.container_add(overlay, ui["stack"])
    ui["view"] = gtk.drawing_area_new()
    call gtk.widget_add_class(ui["view"], "preview")
    call gtk.connect_data(ui["view"], "draw", 1, draw_preview, 0)
    call gtk.stack_add_named(ui["stack"], ui["view"], "preview")
    page = build_state_page()
    call gtk.stack_add_named(ui["stack"], page, "state")
    # Gtk.Stack prepne jen na viditelnou stranku (i pred show_all okna)
    call gtk.widget_show(ui["view"])
    call gtk.widget_show_all(page)

    ui["count"] = overlay_label(overlay, "", "countdown", gtk.ALIGN_CENTER, "countdown")
    # Gtk.Box v GTK3 nekresli CSS pozadi - indikator je jeden Gtk.Label
    ui["rec"] = overlay_label(overlay, "", "rec", gtk.ALIGN_START, "rec")
    ui["flash"] = gtk.event_box_new()
    call gtk.widget_add_class(ui["flash"], "flash")
    call gtk.widget_set_no_show_all(ui["flash"], True)
    call gtk.overlay_add_overlay(overlay, ui["flash"])
    call gtk.overlay_set_pass_through(overlay, ui["flash"])
    ui["scan_label"] = overlay_label(overlay, i18n.T("Hold a Wi-Fi QR code in front of the camera."), "scan-hint", gtk.ALIGN_END, "scan-hint")

    # Spodni lista: posledni snimek | spoust | fotka/video + casovac
    bar = gtk.box_new(gtk.HORIZONTAL, 12)
    call gtk.widget_add_class(bar, "bar")
    call gtk.box_pack_start(root, bar, False, False, 0)

    ui["thumb_btn"] = gtk.button_new_empty()
    call gtk.button_set_relief(ui["thumb_btn"], gtk.RELIEF_NONE)
    call gtk.widget_set_tooltip(ui["thumb_btn"], i18n.T("Open last capture"))
    call gtk.widget_add_class(ui["thumb_btn"], "thumb")
    ui["thumb_area"] = gtk.drawing_area_new()
    call gtk.widget_set_size_request(ui["thumb_area"], 56, 56)
    call gtk.connect_data(ui["thumb_area"], "draw", 1, draw_thumb, 0)
    call gtk.container_add(ui["thumb_btn"], ui["thumb_area"])
    call gtk.connect_data(ui["thumb_btn"], "clicked", 0, on_open_last, 0)
    call gtk.widget_set_valign(ui["thumb_btn"], gtk.ALIGN_CENTER)
    call gtk.box_pack_start(bar, ui["thumb_btn"], False, False, 0)

    ui["shutter"] = gtk.button_new_empty()
    call gtk.button_set_relief(ui["shutter"], gtk.RELIEF_NONE)
    call gtk.widget_add_class(ui["shutter"], "shutter")
    ui["shutter_area"] = gtk.drawing_area_new()
    call gtk.widget_set_size_request(ui["shutter_area"], 68, 68)
    call gtk.connect_data(ui["shutter_area"], "draw", 1, draw_shutter, 0)
    call gtk.container_add(ui["shutter"], ui["shutter_area"])
    call gtk.connect_data(ui["shutter"], "clicked", 0, on_shutter, 0)
    call gtk.box_set_center_widget(bar, ui["shutter"])

    right = gtk.box_new(gtk.HORIZONTAL, 10)
    call gtk.widget_set_valign(right, gtk.ALIGN_CENTER)
    call gtk.box_pack_end(bar, right, False, False, 0)
    ui["timer"] = gtk.toggle_button_new_empty()
    call gtk.widget_set_tooltip(ui["timer"], i18n.T("Take the picture after 3 seconds"))
    call gtk.widget_add_class(ui["timer"], "timer")
    tb = gtk.box_new(gtk.HORIZONTAL, 4)
    call gtk.box_pack_start(tb, gtk.image_new_from_icon_name("alarm-symbolic", gtk.ICON_MENU), False, False, 0)
    call gtk.box_pack_start(tb, gtk.label_new("3s"), False, False, 0)
    call gtk.container_add(ui["timer"], tb)
    call gtk.toggle_button_set_active(ui["timer"], st["cfg"].get("timer", False) == True)
    call gtk.connect_data(ui["timer"], "toggled", 0, on_timer, 0)
    modes = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_add_class(modes, "linked")
    call gtk.widget_add_class(modes, "mode")
    ui["photo"] = gtk.radio_button_new(0, i18n.T("Photo"))
    ui["video"] = gtk.radio_button_new(ui["photo"], i18n.T("Video"))
    call gtk.toggle_button_set_active(ui["video"] if st["mode"] == "video" else ui["photo"], True)
    call gtk.connect_data(ui["photo"], "toggled", 0, on_mode, 0)
    call gtk.box_pack_start(modes, ui["photo"], False, False, 0)
    call gtk.box_pack_start(modes, ui["video"], False, False, 0)
    call gtk.box_pack_start(right, ui["timer"], False, False, 0)
    call gtk.box_pack_start(right, modes, False, False, 0)
    if scan:
        # v rezimu QR neni co fotit
        call gtk.widget_set_no_show_all(bar, True)
        call gtk.widget_hide(bar)
    end

    call gtk.connect_data(window, "key-press-event", 1, on_key, 0)
    call gtk.connect_data(window, "delete-event", 1, on_close, 0)
    call gtk.connect_data(window, "destroy", 0, on_destroy, 0)
    call load_last_capture()
end

function build_state_page():
    box = gtk.box_new(gtk.VERTICAL, 10)
    call gtk.widget_set_halign(box, gtk.ALIGN_CENTER)
    call gtk.widget_set_valign(box, gtk.ALIGN_CENTER)
    call gtk.widget_set_margin(box, 30)
    ui["state_icon"] = gtk.image_new()
    call gtk.image_set_pixel_size(ui["state_icon"], 72)
    call gtk.widget_add_class(ui["state_icon"], "dim")
    ui["state_title"] = label("", "state-title")
    call gtk.widget_set_name(ui["state_title"], "state-title")
    ui["state_hint"] = label("", "dim")
    call gtk.label_set_max_width_chars(ui["state_hint"], 56)
    call gtk.widget_set_name(ui["state_hint"], "state-hint")
    ui["state_code"] = label("", "code")
    call gtk.label_set_selectable(ui["state_code"], True)
    call gtk.widget_set_name(ui["state_code"], "state-code")
    call gtk.widget_set_no_show_all(ui["state_code"], True)
    ui["spinner"] = gtk.spinner_new()
    call gtk.widget_set_size_request(ui["spinner"], 32, 32)
    call gtk.widget_set_no_show_all(ui["spinner"], True)
    ui["retry"] = gtk.button_new(i18n.T("Try Again"))
    call gtk.widget_set_halign(ui["retry"], gtk.ALIGN_CENTER)
    call gtk.widget_set_margins(ui["retry"], 0, 0, 8, 0)
    call gtk.widget_add_class(ui["retry"], "primary")
    call gtk.widget_set_no_show_all(ui["retry"], True)
    call gtk.connect_data(ui["retry"], "clicked", 0, on_retry, 0)
    for key in ["state_icon", "spinner", "state_title", "state_hint", "state_code", "retry"]:
        call gtk.box_pack_start(box, ui[key], False, False, 0)
    end
    return box
end

# Stavy: starting, none, busy, denied, error; v rezimu QR i connecting, connected
function show_state(state, detail):
    prev = st["state"]
    st["state"] = state
    texts = {"starting": ["camera-web-symbolic", i18n.T("Starting the camera…"), ""],
        "none": ["camera-disabled-symbolic", i18n.T("No camera found"), i18n.T("Connect a webcam, or check that the built-in camera is turned on. Some laptops have a camera switch, a privacy shutter or a key with a camera symbol.")],
        "busy": ["camera-web-symbolic", i18n.T("The camera is being used by another app"), i18n.T("Close the other app that uses the camera (a video call, a browser tab…) and try again.")],
        "denied": ["changes-prevent-symbolic", i18n.T("Camera access is not allowed"), i18n.T("Your user account is not allowed to use the camera. Log out and log in again; if that does not help, add yourself to the video group and restart:")],
        "error": ["dialog-warning-symbolic", i18n.T("The camera could not be started"), detail],
        "connecting": ["network-wireless-symbolic", i18n.TF("Joining “%s”…", [detail]), ""],
        "connected": ["network-wireless-signal-excellent-symbolic", i18n.TF("Connected to “%s”", [detail]), i18n.T("You can close this window.")]}
    if state == "error" and ui["scan"] and prev == "connecting":
        texts["error"] = ["dialog-warning-symbolic", i18n.T("The network could not be joined"), detail]
    end
    item = texts.get(state, texts["error"])
    busy = state == "starting" or state == "connecting"
    call gtk.image_set_from_icon_name(ui["state_icon"], item[0], gtk.ICON_DIALOG)
    call gtk.widget_hide(ui["scan_label"])
    call gtk.widget_set_visible(ui["state_icon"], not busy)
    call gtk.widget_set_visible(ui["spinner"], busy)
    call gtk.spinner_set(ui["spinner"], busy)
    call gtk.label_set_text(ui["state_title"], item[1])
    call gtk.label_set_text(ui["state_hint"], item[2])
    call gtk.widget_set_visible(ui["state_hint"], item[2] != "")
    call gtk.label_set_text(ui["state_code"], "sudo usermod -aG video $USER")
    call gtk.widget_set_visible(ui["state_code"], state == "denied")
    retry = state == "busy" or state == "denied" or state == "error" or state == "none"
    call gtk.widget_set_visible(ui["retry"], retry)
    call gtk.stack_set_visible_child_name(ui["stack"], "state")
    call update_controls()
    if retry:
        # jinak by fokus dostal (a oznacil) prikaz ve state_code
        call gtk.widget_grab_focus(ui["retry"])
    end
end

# ---- kamery ------------------------------------------------------------------------------------------------------

# Pripojeni/odpojeni kamery: kontrola seznamu uzlu video* kazde 2 s
function watch_devices(unused):
    if camera.test_mode() == "" and st["recording"] == None:
        nodes = camera.video_nodes()
        if nodes != st["nodes"]:
            dev = st["device"]
            start = st["state"] == "none" or st["state"] == "denied" or st["state"] == "error" or (dev != None and not (dev["path"] in nodes))
            call refresh_devices(start, False)
        end
    end
    return True
end

function refresh_devices(start, force):
    st["nodes"] = camera.video_nodes()
    found = camera.scan_devices()
    devices = found[0]
    old = st["device"]
    st["devices"] = devices
    ui["updating"] = True
    call gtk.combo_box_text_remove_all(ui["combo"])
    for d in devices:
        call gtk.combo_box_text_append(ui["combo"], d["path"], d["name"])
    end
    wanted = old["path"] if old != None else st["cfg"].get("device", "")
    st["device"] = None
    for d in devices:
        if d["path"] == wanted:
            st["device"] = d
        end
    end
    if st["device"] == None and len(devices) > 0:
        st["device"] = devices[0]
    end
    if st["device"] != None:
        call gtk.combo_box_set_active_id(ui["combo"], st["device"]["path"])
    end
    ui["updating"] = False
    call gtk.widget_set_visible(ui["combo"], len(devices) > 1)
    mode = camera.test_mode()
    if len(devices) == 0:
        call stop_pipeline()
        call show_state("denied" if found[1] > 0 or mode == "denied" else "none", "")
        return 0
    end
    if mode == "denied":
        call show_state("denied", "")
        return 0
    end
    if start or force or (old != None and old["path"] != st["device"]["path"]) or not camera.running():
        call start_preview(None)
    end
end

function on_camera_changed(unused, combo):
    if ui["updating"]:
        return 0
    end
    index = gtk.combo_box_get_active(combo)
    if index < 0 or index >= len(st["devices"]):
        return 0
    end
    dev = st["devices"][index]
    if st["device"] == None or dev["path"] != st["device"]["path"]:
        st["device"] = dev
        st["cfg"]["device"] = dev["path"]
        call save_config()
        call start_preview(None)
    end
    return 0
end

function on_retry(unused, b):
    call refresh_devices(True, True)
    return 0
end

function mirror_default():
    dev = st["device"]
    if dev == None:
        return True
    end
    name = dev["name"].lower()
    rear = name.find("rear") >= 0 or name.find("back") >= 0 or name.find("world") >= 0
    saved = st["cfg"].get("mirror", {})
    if type(saved) == "Dictionary" and dev["name"] in saved:
        return saved[dev["name"]] == True
    end
    return not rear
end

# ---- pipeline ----------------------------------------------------------------------------------------------------

function stop_pipeline():
    if st["poll"] != 0:
        call glib.source_remove(st["poll"])
        st["poll"] = 0
    end
    call camera.stop()
end

# Spusti nahled (a s record = {"path", "encoder", "audio"} i zapis videa)
function start_preview(record):
    call stop_pipeline()
    dev = st["device"]
    if dev == None:
        return 0
    end
    if camera.test_mode() == "busy":
        call show_state("busy", "")
        return 0
    end
    if record == None:
        call show_state("starting", "")
    end
    ui["updating"] = True
    call gtk.toggle_button_set_active(ui["mirror"], mirror_default())
    ui["updating"] = False
    if dev["path"].startswith("test:") or dev["path"] in st["caps"]:
        call build_pipeline(dev, record)
        return 0
    end
    # zjisteni formatu otevre kameru (desitky ms): az po vykresleni stavu "Spoustim kameru"
    st["probe"] += 1
    call glib.timeout_add_data(50, probe, [st["probe"], dev, record])
end

function probe(job):
    dev = job[1]
    if job[0] != st["probe"] or st["device"] == None or st["device"]["path"] != dev["path"]:
        return False
    end
    result = camera.probe_caps(dev["path"])
    if result[2] == "missing":
        call show_state("error", i18n.T("The GStreamer plugin for cameras (gst-plugins-good) is missing."))
    elif result[2] == "open":
        call show_state("busy" if accessible(dev["path"]) else "denied", "")
    else:
        st["caps"][dev["path"]] = [result[0], result[1]]
        call build_pipeline(dev, job[2])
    end
    return False
end

function build_pipeline(dev, record):
    caps = st["caps"].get(dev["path"], ["", False])
    opts = {"mirror": gtk.toggle_button_get_active(ui["mirror"]), "image": test_image() if dev["path"].startswith("test:") else ""}
    if record != None:
        if record.get("audio", True) == False:
            record["source"] = ""
        else:
            record["source"] = audio_source()
        end
        record["audio"] = record["source"] != "" and record["encoder"][3] != ""
        opts["record"] = {"path": record["path"], "encoder": record["encoder"], "audio": record["source"] if record["audio"] else ""}
    end
    error = camera.start_with(dev["path"], caps[0], caps[1], opts)
    if error != "":
        call show_state("error", error)
        return 0
    end
    st["scan_paused"] = False
    st["recording"] = record
    # snimky z appsink vyzvedava hlavni smycka (zadna vlakna)
    st["poll"] = glib.timeout_add_data(15, poll_camera, 0)
    if record != None:
        record["start"] = glib.monotonic_time()
        call gtk.widget_show(ui["rec"])
        call update_rec_time(0)
        call glib.timeout_add_data(500, update_rec_time, 0)
    end
    call update_controls()
end

function poll_camera(unused):
    if not camera.running():
        st["poll"] = 0
        return False
    end
    got = camera.poll()
    if got == "error":
        st["poll"] = 0
        call on_error()
        return False
    elif got == "eos":
        st["poll"] = 0
        call finish_recording(0)
        return False
    elif got == "frame":
        if st["state"] != "preview":
            st["state"] = "preview"
            call gtk.stack_set_visible_child_name(ui["stack"], "preview")
            call gtk.widget_set_visible(ui["scan_label"], ui["scan"])
            call update_controls()
        end
        if ui["scan"]:
            call scan_frame()
        end
        call gtk.widget_queue_draw(ui["view"])
    end
    return True
end

function on_error():
    source = camera.error_source()
    reason = camera.error_text()
    debug = camera.error_debug()
    lines = debug.split("\n")
    call eprint("luxos-camera: " + source + ": " + reason + " (" + lines[0] + ")")
    rec = st["recording"]
    if rec != None and source.find("asrc") >= 0 and rec["audio"] and glib.monotonic_time() - rec["start"] < 3000000:
        # Mikrofon neni k dispozici: nahrat bez zvuku
        rec["audio"] = False
        call camera.stop()
        call glib.unlink(rec["path"])
        call start_preview(rec)
        return 0
    end
    if rec != None:
        call abort_recording()
    end
    call stop_pipeline()
    text = (reason + " " + debug).lower()
    dev = st["device"]
    if camera.error_busy() or text.find("busy") >= 0:
        call show_state("busy", "")
    elif text.find("permission denied") >= 0:
        call show_state("denied", "")
    elif dev != None and not dev["path"].startswith("test:") and not sys.lexists(dev["path"]):
        # kamera odpojena
        call refresh_devices(True, False)
    else:
        call show_state("error", reason)
    end
end

function draw_preview(unused, cr, widget):
    aw = Float(gtk.widget_get_allocated_width(widget))
    ah = Float(gtk.widget_get_allocated_height(widget))
    call cairo.set_source_rgb(cr, 0.0, 0.0, 0.0)
    call cairo.paint(cr)
    surf = camera.surface()
    if surf == 0:
        return False
    end
    w = Float(cairo.image_surface_get_width(surf))
    h = Float(cairo.image_surface_get_height(surf))
    scale = min(aw / w, ah / h)
    call cairo.translate(cr, (aw - w * scale) / 2, (ah - h * scale) / 2)
    call cairo.scale(cr, scale, scale)
    call cairo.set_source_surface(cr, surf, 0.0, 0.0)
    # CAIRO_FILTER_GOOD pri zmenseni, jinak BILINEAR
    call gtk.cairo_source_filter(cr, 1 if scale < 1 else 4)
    call cairo.paint(cr)
    return False
end

# ---- QR kod site Wi-Fi -------------------------------------------------------------------------------------------

function scan_frame():
    now = glib.monotonic_time()
    if st["scan_paused"] or now - st["scan_last"] < SCAN_INTERVAL_MS * 1000:
        return 0
    end
    st["scan_last"] = now
    texts = qr.decode_surface(camera.surface())
    if len(texts) == 0:
        return 0
    end
    info = None
    for t in texts:
        if info == None:
            info = qr.parse_wifi(t)
        end
    end
    if info == None:
        call scan_notice(i18n.T("This QR code is not a Wi-Fi network."))
        return 0
    end
    st["scan_paused"] = True
    dialog = gtk.message_dialog_new(ui["window"], gtk.MESSAGE_QUESTION, gtk.BUTTONS_NONE, i18n.TF("Join the Wi-Fi network “%s”?", [info["ssid"]]))
    if info["security"] == "nopass":
        call gtk.object_set_string(dialog, "secondary-text", i18n.T("Open network – no password needed."))
    end
    call gtk.dialog_add_button(dialog, i18n.T("Cancel"), gtk.RESPONSE_CANCEL)
    call gtk.dialog_add_button(dialog, i18n.T("Join"), gtk.RESPONSE_OK)
    call gtk.dialog_set_default_response(dialog, gtk.RESPONSE_OK)
    call gtk.connect_data(dialog, "response", 1, on_scan_answer, info)
    call gtk.widget_show_all(dialog)
end

function on_scan_answer(info, response, dialog):
    call gtk.widget_destroy(dialog)
    if gtk.s32(response) != gtk.RESPONSE_OK:
        # stejny kod hned znovu nenabizet
        call glib.timeout_add_data(1500, scan_resume, 0)
        return 0
    end
    call stop_pipeline()
    call show_state("connecting", info["ssid"])
    call qr.connect(info, on_connected, info)
    return 0
end

function on_connected(info, ok, message):
    if ok:
        call show_state("connected", info["ssid"])
    else:
        call eprint("luxos-camera: nmcli: " + message)
        call show_state("error", i18n.TF("Could not join “%s”: %s", [info["ssid"], message if message != "" else "nmcli"]))
    end
end

function scan_resume(unused):
    st["scan_paused"] = False
    return False
end

function scan_notice(text):
    call gtk.label_set_text(ui["scan_label"], text)
    if st["notice_id"] != 0:
        call glib.source_remove(st["notice_id"])
    end
    st["notice_id"] = glib.timeout_add_data(3000, scan_notice_back, 0)
end

function scan_notice_back(unused):
    st["notice_id"] = 0
    call gtk.label_set_text(ui["scan_label"], i18n.T("Hold a Wi-Fi QR code in front of the camera."))
    return False
end

# ---- ovladani ----------------------------------------------------------------------------------------------------

function live():
    return camera.running() and st["state"] == "preview"
end

function update_controls():
    on = live()
    busy = st["recording"] != None or st["stopping"]
    counting = st["countdown"] > 0
    call gtk.widget_set_sensitive(ui["shutter"], (on or busy) and not st["stopping"])
    call gtk.widget_set_sensitive(ui["photo"], not busy and not counting)
    call gtk.widget_set_sensitive(ui["video"], not busy and not counting)
    call gtk.widget_set_sensitive(ui["combo"], not busy and not counting)
    call gtk.widget_set_sensitive(ui["mirror"], on and not busy)
    if st["recording"] != None:
        call gtk.widget_set_tooltip(ui["shutter"], i18n.T("Stop recording"))
    elif st["mode"] == "video":
        call gtk.widget_set_tooltip(ui["shutter"], i18n.T("Start recording"))
    else:
        call gtk.widget_set_tooltip(ui["shutter"], i18n.T("Take Photo"))
    end
    call gtk.widget_queue_draw(ui["shutter_area"])
end

function on_mode(unused, b):
    st["mode"] = "photo" if gtk.toggle_button_get_active(ui["photo"]) else "video"
    st["cfg"]["mode"] = st["mode"]
    call save_config()
    call update_controls()
    return 0
end

function on_timer(unused, b):
    st["cfg"]["timer"] = gtk.toggle_button_get_active(b)
    call save_config()
    return 0
end

function on_mirror(unused, b):
    if ui["updating"]:
        return 0
    end
    on = gtk.toggle_button_get_active(b)
    call camera.set_mirror(on)
    if st["device"] != None:
        saved = st["cfg"].get("mirror", {})
        if type(saved) != "Dictionary":
            saved = {}
        end
        saved[st["device"]["name"]] = on
        st["cfg"]["mirror"] = saved
        call save_config()
    end
    return 0
end

function window_key(keyval):
    if ui["scan"]:
        return False
    end
    if keyval == gtk.KEY_space or keyval == gtk.KEY_Return or keyval == gtk.KEY_KP_Enter:
        if gtk.widget_get_sensitive(ui["shutter"]):
            call on_shutter(0, 0)
        end
        return True
    end
    if keyval == gtk.KEY_Escape and st["countdown"] > 0:
        call cancel_countdown()
        return True
    end
    return False
end

function on_key(unused, event, window):
    return window_key(gtk.event_key_keyval(event))
end

function on_shutter(unused, b):
    if st["recording"] != None:
        call stop_recording()
        return 0
    end
    if st["countdown"] > 0:
        call cancel_countdown()
        return 0
    end
    if not live():
        return 0
    end
    if gtk.toggle_button_get_active(ui["timer"]):
        st["countdown"] = TIMER_SECONDS
        call gtk.label_set_text(ui["count"], String(st["countdown"]))
        call gtk.widget_show(ui["count"])
        st["countdown_id"] = glib.timeout_add_data(1000, tick, 0)
        call update_controls()
    else:
        call fire()
    end
    return 0
end

function tick(unused):
    st["countdown"] -= 1
    if st["countdown"] > 0:
        call gtk.label_set_text(ui["count"], String(st["countdown"]))
        return True
    end
    st["countdown_id"] = 0
    call gtk.widget_hide(ui["count"])
    call update_controls()
    if live():
        call fire()
    end
    return False
end

function cancel_countdown():
    if st["countdown_id"] != 0:
        call glib.source_remove(st["countdown_id"])
    end
    st["countdown_id"] = 0
    st["countdown"] = 0
    call gtk.widget_hide(ui["count"])
    call update_controls()
end

function fire():
    if st["mode"] == "photo":
        call take_photo()
    else:
        call start_recording()
    end
end

# ---- fotka -------------------------------------------------------------------------------------------------------

# Posledni snimek nahledu (uz zrcadleny jako v okne) jako GdkPixbuf, 0 kdyz neni
function frame_pixbuf():
    surf = camera.surface()
    if surf == 0:
        return 0
    end
    call cairo.surface_flush(surf)
    return gtk.surface_to_pixbuf(surf, cairo.image_surface_get_width(surf), cairo.image_surface_get_height(surf))
end

function take_photo():
    pix = frame_pixbuf()
    call do_flash()
    if pix == 0:
        call toast(i18n.T("The photo could not be taken."))
        return 0
    end
    path = unique_path(pictures_dir(), i18n.T("Photo"), "jpg")
    error = "cannot create " + pictures_dir()
    if path != "":
        error = gtk.pixbuf_save_jpeg(pix, path)
    end
    if error != "":
        call gtk.object_unref(pix)
        call toast(i18n.TF("The photo could not be saved: %s", [error]))
        return 0
    end
    call set_thumb(path, pix, False)
end

function do_flash():
    call gtk.widget_set_opacity(ui["flash"], 1.0)
    call gtk.widget_show(ui["flash"])
    st["flash_start"] = glib.monotonic_time()
    call glib.timeout_add_data(16, flash_step, 0)
end

function flash_step(unused):
    t = (glib.monotonic_time() - st["flash_start"]) / 350000.0
    if t >= 1:
        call gtk.widget_hide(ui["flash"])
        return False
    end
    call gtk.widget_set_opacity(ui["flash"], 1 - t * t)
    return True
end

# ---- video -------------------------------------------------------------------------------------------------------

function start_recording():
    enc = video_encoder()
    if enc == None:
        call toast(i18n.T("No video encoder is installed (gst-plugins-good)."))
        return 0
    end
    path = unique_path(videos_dir(), i18n.T("Video"), enc[2])
    if path == "":
        call toast(i18n.TF("The video could not be saved: %s", ["cannot create " + videos_dir()]))
        return 0
    end
    call do_flash()
    call start_preview({"path": path, "encoder": enc})
end

function update_rec_time(unused):
    rec = st["recording"]
    if rec == None or not ("start" in rec):
        return False
    end
    sec = (glib.monotonic_time() - rec["start"]) // 1000000
    secs = String(sec % 60)
    if len(secs) < 2:
        secs = "0" + secs
    end
    call gtk.label_set_markup(ui["rec"], "<span color=\"#ff3b30\">●</span>  " + String(sec // 60) + ":" + secs)
    return True
end

function stop_recording():
    rec = st["recording"]
    if rec == None or st["stopping"]:
        return 0
    end
    st["stopping"] = True
    call update_controls()
    # Nahled videa = posledni snimek; EOS necha muxer dopsat soubor
    rec["thumb"] = frame_pixbuf()
    call camera.send_eos()
    call glib.timeout_add_seconds_data(5, eos_timeout, rec)
end

function eos_timeout(rec):
    if st["recording"] == rec and st["stopping"]:
        call finish_recording(0)
    end
    return False
end

function finish_recording(unused):
    rec = st["recording"]
    call stop_pipeline()
    st["recording"] = None
    st["stopping"] = False
    call gtk.widget_hide(ui["rec"])
    if rec != None:
        size = glib.stat(rec["path"])
        if len(size) > 0 and size[0] > 0:
            call set_thumb(rec["path"], rec.get("thumb", 0), True)
        elif rec.get("thumb", 0) != 0:
            call gtk.object_unref(rec["thumb"])
        end
    end
    call start_preview(None)
end

function abort_recording():
    st["recording"] = None
    st["stopping"] = False
    call gtk.widget_hide(ui["rec"])
end

# ---- posledni snimek ---------------------------------------------------------------------------------------------

function load_last_capture():
    best = ""
    best_time = -1
    for folder in [pictures_dir(), videos_dir()]:
        for name in glib.list_dir(folder):
            path = folder + "/" + name
            if has_ext(name, MEDIA_EXT):
                info = glib.stat(path)
                if len(info) > 0 and info[1] > best_time:
                    best = path
                    best_time = info[1]
                end
            end
        end
    end
    if best != "":
        call set_thumb(best, 0, not has_ext(best, PHOTO_EXT))
    else:
        call gtk.widget_set_sensitive(ui["thumb_btn"], False)
    end
end

# Nahled posledniho snimku: kratsi strana 112 px, kresli se v polovicni velikosti (ostre i na HiDPI)
function set_thumb(path, pix, video):
    st["last"] = path
    st["thumb_video"] = video
    if pix == 0 and not video:
        pix = gtk.pixbuf_new_from_file_at_scale(path, 160, 160, True)
    end
    if st["thumb"] != 0:
        call gtk.object_unref(st["thumb"])
        st["thumb"] = 0
    end
    if pix != 0:
        w = gtk.pixbuf_get_width(pix)
        h = gtk.pixbuf_get_height(pix)
        s = 112.0 / min(w, h)
        st["thumb"] = gtk.pixbuf_scale(pix, max(1, Int(w * s)), max(1, Int(h * s)))
        call gtk.object_unref(pix)
    end
    call gtk.widget_set_sensitive(ui["thumb_btn"], True)
    call gtk.widget_queue_draw(ui["thumb_area"])
end

function on_open_last(unused, b):
    if st["last"] != "" and sys.lexists(st["last"]):
        uri = ""
        unsafe:
            uri = glib.take_c(__lsl_qbe_call3(__lsl_symbol("g_filename_to_uri"), __lsl_address(st["last"]) + 16, 0, 0))
        end
        if not glib.launch_uri(uri):
            call glib.spawn_quiet(["xdg-open", st["last"]])
        end
    end
    return 0
end

function draw_thumb(unused, cr, widget):
    w = Float(gtk.widget_get_allocated_width(widget))
    h = Float(gtk.widget_get_allocated_height(widget))
    fg = gtk.widget_get_color(widget, gtk.widget_get_state_flags(widget))
    call cairo.save(cr)
    call cairo.rounded_rectangle(cr, 1.0, 1.0, w - 2, h - 2, 10.0)
    call cairo.clip(cr)
    if st["thumb"] != 0:
        tw = gtk.pixbuf_get_width(st["thumb"]) / 2.0
        th = gtk.pixbuf_get_height(st["thumb"]) / 2.0
        call cairo.translate(cr, (w - tw) / 2, (h - th) / 2)
        call cairo.scale(cr, 0.5, 0.5)
        call gtk.cairo_set_source_pixbuf(cr, st["thumb"], 0, 0)
        call cairo.paint(cr)
    else:
        call cairo.set_source_rgba(cr, fg[0], fg[1], fg[2], 0.08)
        call cairo.paint(cr)
    end
    call cairo.restore(cr)
    call cairo.rounded_rectangle(cr, 1.0, 1.0, w - 2, h - 2, 10.0)
    call cairo.set_source_rgba(cr, fg[0], fg[1], fg[2], 0.18)
    call cairo.set_line_width(cr, 1.0)
    call cairo.stroke(cr)
    if st["thumb_video"] and st["last"] != "":
        # Znacka videa: trojuhelnik v kolecku
        call cairo.arc(cr, w / 2, h / 2, 12.0, 0.0, 2 * math.PI)
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.55)
        call cairo.fill(cr)
        call cairo.move_to(cr, w / 2 - 4, h / 2 - 6)
        call cairo.line_to(cr, w / 2 + 7, h / 2)
        call cairo.line_to(cr, w / 2 - 4, h / 2 + 6)
        call cairo.close_path(cr)
        call cairo.set_source_rgb(cr, 1.0, 1.0, 1.0)
        call cairo.fill(cr)
    end
    return False
end

function draw_shutter(unused, cr, widget):
    w = Float(gtk.widget_get_allocated_width(widget))
    h = Float(gtk.widget_get_allocated_height(widget))
    cx = w / 2
    cy = h / 2
    r = min(w, h) / 2 - 3
    fg = gtk.widget_get_color(widget, gtk.widget_get_state_flags(widget))
    alpha = 1.0 if gtk.widget_get_sensitive(ui["shutter"]) else 0.4
    call cairo.arc(cr, cx, cy, r, 0.0, 2 * math.PI)
    call cairo.set_source_rgba(cr, fg[0], fg[1], fg[2], 0.85 * alpha)
    call cairo.set_line_width(cr, 4.0)
    call cairo.stroke(cr)
    if st["recording"] != None:
        s = r * 0.8
        call cairo.rounded_rectangle(cr, cx - s / 2, cy - s / 2, s, s, 6.0)
        call cairo.set_source_rgba(cr, 1.0, 0.23, 0.19, alpha)
        call cairo.fill(cr)
        return False
    end
    call cairo.arc(cr, cx, cy, r - 6, 0.0, 2 * math.PI)
    if st["mode"] == "video":
        call cairo.set_source_rgba(cr, 1.0, 0.23, 0.19, alpha)
        call cairo.fill(cr)
    else:
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, alpha)
        call cairo.fill_preserve(cr)
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.15 * alpha)
        call cairo.set_line_width(cr, 1.0)
        call cairo.stroke(cr)
    end
    return False
end

function toast(text):
    dialog = gtk.message_dialog_new(ui["window"], gtk.MESSAGE_WARNING, gtk.BUTTONS_OK, text)
    call gtk.dialog_run(dialog)
    call gtk.widget_destroy(dialog)
end

# Rozpracovane video dokoncit (EOS), jinak by soubor nesel prehrat
function on_close(unused, event, window):
    if st["recording"] != None and camera.running():
        call camera.wait_eos(5)
    end
    call stop_pipeline()
    return False
end

function on_destroy(unused, window):
    call stop_pipeline()
    call gtk.main_quit()
    return 0
end

# ---- testy (LUXOS_TEST_CONTROL=1) ------------------------------------------------------------------------------

function on_test(command, rest):
    if command == "state":
        dev = st["device"]
        rec = st["recording"]
        print "state " + json.encode({"state": st["state"], "page": gtk.stack_get_visible_child_name(ui["stack"]),
            "mode": st["mode"], "recording": rec["path"] if rec != None else "", "audio": rec["audio"] if rec != None else False,
            "countdown": st["countdown"], "timer": gtk.toggle_button_get_active(ui["timer"]),
            "mirror": gtk.toggle_button_get_active(ui["mirror"]), "device": dev["path"] if dev != None else "",
            "devices": [d["name"] for d in st["devices"]], "combo": gtk.widget_get_visible(ui["combo"]),
            "shutter": gtk.widget_get_sensitive(ui["shutter"]), "last": st["last"], "thumb": st["thumb"] != 0,
            "thumb_video": st["thumb_video"], "frame": camera.surface() != 0, "scan_paused": st["scan_paused"]})
    elif command == "key":
        print "key " + String(window_key(Int(rest)))
    elif command == "camera":
        call gtk.combo_box_set_active_id(ui["combo"], rest)
    elif command == "mirror":
        call gtk.toggle_button_set_active(ui["mirror"], rest == "1")
    elif command == "timer":
        call gtk.toggle_button_set_active(ui["timer"], rest == "1")
    elif command == "mode":
        call gtk.toggle_button_set_active(ui["video"] if rest == "video" else ui["photo"], True)
    elif command == "close":
        call gtk.window_close(ui["window"])
    end
end

# ---- start ---------------------------------------------------------------------------------------------------------

ui["scan"] = "--scan-wifi" in args[1:]
call glib.set_prgname("luxos-camera")
call glib.set_application_name(i18n.T("Camera"))
call gtk.init()
call camera.init()
call gtk.css_load(CSS)
call build()
call gtk.widget_show_all(ui["window"])
call refresh_devices(True, False)
call gtk.widget_grab_focus(ui["shutter"])
call glib.timeout_add_seconds_data(2, watch_devices, 0)
call testctl.start(on_test)
call gtk.main()
