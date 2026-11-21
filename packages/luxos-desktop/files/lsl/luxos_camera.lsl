# lsl: link libgstapp-1.0.so.0 libgstreamer-1.0.so.0 libcairo.so.2 libgobject-2.0.so.0 libglib-2.0.so.0
# LuxOS - webkamera (v4l2 + GStreamer) pro aplikace v LSL (Kamera, Profilova fotka; drive files/python/luxos_camera.py).
#
#   scan_devices() -> [kamery, pocet uzlu bez opravneni]   kamera = {"path", "name"}
#   probe_caps(path) -> [caps, je MJPEG, chyba]    vhodny format kamery ("missing" bez v4l2src, "open")
#   pick_caps(caps_text) -> [caps, je MJPEG] nebo None   <= 1280 px, >= 20 fps, raw pred MJPEG
#   start(dev, caps, jpeg) -> "" nebo chyba    nahled: zrcadleny obraz BGRx, snimky si program vyzvedava
#   start_with(dev, caps, jpeg, volby)         volby: mirror, image (testovaci obrazek), record = {"path",
#                                              "encoder": [video, muxer, pripona, audio], "audio": zdroj nebo ""}
#   poll() -> "frame" | "error" | "eos" | ""   z casovace hlavni smycky (zadna vlakna: zpetna volani LSL jen
#                                              v hlavnim vlakne); error_text(), error_busy(), error_debug(),
#                                              error_source() (cesta prvku, napr. .../asrc)
#   surface() -> posledni snimek (cairo RGB24, 0 = zatim zadny), stop(), set_mirror(zap), send_eos(),
#   wait_eos(sekundy) (dopsani videa pri zavreni okna), has(prvek) - je plugin GStreamer nainstalovan
# Testovani bez kamery: LUXOS_CAMERA_TEST=1 (jedna testovaci kamera videotestsrc), 2 (dve), none (zadna),
# busy (kamera obsazena), denied (chybi opravneni). LUXOS_VIDEO_DEV_DIR: kde hledat uzly video* (vychozi
# /dev); pojistka testu (scripts/luxos_testguard.py) ji nastavi na prazdnou slozku.
load env
load luxos_glib, glib as glib
load luxos_sys as sys
load luxos_text as text

MAX_WIDTH = 1280               # vetsi rozliseni zbytecne zatezuje CPU (dekodovani, kresleni)
VIDIOC_QUERYCAP = 2154321408   # _IOR('V', 0, struct v4l2_capability), 104 bajtu
V4L2_CAP_VIDEO_CAPTURE = 1
V4L2_CAP_DEVICE_CAPS = 2147483648

cam = {"init": False, "pipeline": 0, "sink": 0, "bus": 0, "surface": 0, "w": 0, "h": 0, "error": "", "busy": False,
    "debug": "", "source": ""}

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function cstr(value):
    unsafe:
        return __lsl_address(value) + 16
    end
end

function test_mode():
    return env.get("LUXOS_CAMERA_TEST", "").strip().lower()
end

function video_dir():
    d = env.get("LUXOS_VIDEO_DEV_DIR", "")
    if d == "":
        return "/dev"
    end
    return d
end

function node_number(name):
    digits = ""
    for ch in name:
        if text.is_digit(ch):
            digits += ch
        end
    end
    if digits == "":
        return 0
    end
    return Int(digits)
end

function video_nodes():
    # podle cisla uzlu (video10 za video9)
    keyed = []
    for name in glib.list_dir(video_dir()):
        if name.startswith("video"):
            keyed.append(text.pad(node_number(name), 9) + "\t" + name)
        end
    end
    return [video_dir() + "/" + key[key.find("\t") + 1:] for key in sorted(keyed)]
end

# Popis kamery z VIDIOC_QUERYCAP: jmeno, nebo "" (neni kamera / metadatovy uzel stejne kamery)
function query_name(fd, path):
    unsafe:
        buffer = __lsl_byte_zeros(104)
        base = __lsl_qbe_load64(__lsl_address(buffer) + 24)
        if __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("ioctl"), ptr(fd), VIDIOC_QUERYCAP, base)) != 0:
            return ""
        end
        caps = __lsl_qbe_load32(base + 84)
        dcaps = __lsl_qbe_load32(base + 88)
        name = glib.from_c(base + 16)
    end
    used = caps
    if caps & V4L2_CAP_DEVICE_CAPS:
        used = dcaps
    end
    if used & V4L2_CAP_VIDEO_CAPTURE == 0:
        return ""
    end
    # UVC: "Integrated Camera: Integrated C"
    name = name[:32].strip()
    if name.find(":") > 0:
        name = name[:name.find(":")].strip()
    end
    if name == "":
        return path
    end
    return name
end

function open_node(path):
    unsafe:
        # O_RDWR | O_NONBLOCK
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("open"), cstr(path), 2 | 2048))
    end
end

function scan_devices():
    mode = test_mode()
    if mode == "1" or mode == "2" or mode == "busy" or mode == "denied":
        n = 2 if mode == "2" else 1
        return [[{"path": "test:" + String(i), "name": "Test Camera " + String(i + 1)} for i in range(n)], 0]
    end
    if mode == "none":
        return [[], 0]
    end
    devices = []
    denied = 0
    for path in video_nodes():
        fd = open_node(path)
        if fd < 0:
            # EPERM, EACCES
            if sys.errno() == 13 or sys.errno() == 1:
                denied += 1
            end
            continue
        end
        name = query_name(fd, path)
        call sys.close(fd)
        if name != "":
            devices.append({"path": path, "name": name})
        end
    end
    # stejne nazvy odlisit cislem
    seen = {}
    for d in devices:
        seen[d["name"]] = seen.get(d["name"], 0) + 1
        if seen[d["name"]] > 1:
            d["name"] = d["name"] + " (" + String(seen[d["name"]]) + ")"
        end
    end
    return [devices, denied]
end

# ---- formaty kamery ------------------------------------------------------------------------------

function init():
    if not cam["init"]:
        unsafe:
            call __lsl_qbe_call2(__lsl_symbol("gst_init"), 0, 0)
        end
        cam["init"] = True
    end
end

# Zlomky "n/d" z textu
function fractions(spec):
    out = []
    for part in spec.replace("{", " ").replace("}", " ").replace("[", " ").replace("]", " ").replace(",", " ").split(" "):
        cut = part.find("/")
        if cut > 0:
            n = part[:cut].strip()
            d = part[cut + 1:].strip()
            if text.is_digits(n) and text.is_digits(d) and Int(d) != 0:
                out.append([Int(n), Int(d)])
            end
        end
    end
    return out
end

# Nejvyssi snimkova frekvence <= 30 z popisu struktury caps; [fps, "n/d" nebo ""]
function best_fps(description):
    key = "framerate=(fraction)"
    at = description.find(key)
    if at < 0:
        return [0.0, ""]
    end
    value = description[at + len(key):]
    if value.startswith("{"):
        value = value[:value.find("}") + 1]
    elif value.startswith("["):
        value = value[:value.find("]") + 1]
    else:
        stop = len(value)
        for sep in [",", ";", " "]:
            if value.find(sep) >= 0 and value.find(sep) < stop:
                stop = value.find(sep)
            end
        end
        value = value[:stop]
    end
    rates = fractions(value)
    if len(rates) == 0:
        return [0.0, ""]
    end
    if value.startswith("["):
        # rozsah - frekvenci necht vyjedna v4l2src
        top = 0.0
        for r in rates:
            top = max(top, Float(r[0]) / r[1])
        end
        return [min(top, 30.0), ""]
    end
    low = [r for r in rates if Float(r[0]) / r[1] <= 30.5]
    if len(low) == 0:
        low = rates
    end
    best = low[0]
    for r in low:
        if Float(r[0]) / r[1] > Float(best[0]) / best[1]:
            best = r
        end
    end
    return [Float(best[0]) / best[1], String(best[0]) + "/" + String(best[1])]
end

# Porovnani skore [mala, >= 20 fps, plocha, raw, fps] jako n-tice v Pythonu
function better(a, b):
    for i in range(len(a)):
        if a[i] != b[i]:
            return a[i] > b[i]
        end
    end
    return False
end

function structure_int(s, field):
    unsafe:
        cell = __lsl_byte_zeros(8)
        where = __lsl_qbe_load64(__lsl_address(cell) + 24)
        if __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("gst_structure_get_int"), ptr(s), cstr(field), where)) == 0:
            return None
        end
        return __lsl_qbe_s32(__lsl_qbe_load32(where))
    end
end

# Z nabidky kamery (text GstCaps) vybere rozumny format: <= 1280 px, >= 20 fps, raw pred MJPEG
function pick_caps(caps_text):
    call init()
    best = None
    best_score = None
    unsafe:
        caps = __lsl_qbe_call1(__lsl_symbol("gst_caps_from_string"), cstr(caps_text))
    end
    if caps == 0:
        return None
    end
    unsafe:
        count = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gst_caps_get_size"), caps))
    end
    for i in range(count):
        unsafe:
            s = __lsl_qbe_call2(__lsl_symbol("gst_caps_get_structure"), caps, ptr(i))
            name = glib.from_c(__lsl_qbe_call1(__lsl_symbol("gst_structure_get_name"), s))
            description = glib.take_c(__lsl_qbe_call1(__lsl_symbol("gst_structure_to_string"), s))
            fmt = glib.from_c(__lsl_qbe_call2(__lsl_symbol("gst_structure_get_string"), s, cstr("format")))
        end
        if name != "video/x-raw" and name != "image/jpeg":
            continue
        end
        w = structure_int(s, "width")
        h = structure_int(s, "height")
        if w == None or h == None:
            continue
        end
        fps = best_fps(description)
        small = w <= MAX_WIDTH
        area = w * h if small else -w * h
        score = [small, fps[0] >= 20, area, name == "video/x-raw", fps[0]]
        if best_score == None or better(score, best_score):
            out = name + ",width=" + String(w) + ",height=" + String(h)
            if fps[1] != "":
                out += ",framerate=" + fps[1]
            end
            if name == "video/x-raw" and fmt != "":
                out += ",format=" + fmt
            end
            best = [out, name == "image/jpeg"]
            best_score = score
        end
    end
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("gst_mini_object_unref"), ptr(caps))
    end
    return best
end

# Otevre kameru (stav READY) a zjisti nabizene formaty: [caps, jpeg, chyba]
function probe_caps(path):
    call init()
    unsafe:
        src = __lsl_qbe_call2(__lsl_symbol("gst_element_factory_make"), cstr("v4l2src"), 0)
    end
    if src == 0:
        return ["", False, "missing"]
    end
    offered = ""
    failed = False
    unsafe:
        call __lsl_qbe_call4(__lsl_symbol("g_object_set"), src, cstr("device"), cstr(path), 0)
        # GST_STATE_READY = 2, GST_STATE_CHANGE_FAILURE = 0
        if __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("gst_element_set_state"), src, 2)) == 0:
            failed = True
        else:
            pad = __lsl_qbe_call2(__lsl_symbol("gst_element_get_static_pad"), src, cstr("src"))
            caps = __lsl_qbe_call2(__lsl_symbol("gst_pad_query_caps"), pad, 0)
            if caps != 0:
                offered = glib.take_c(__lsl_qbe_call1(__lsl_symbol("gst_caps_to_string"), caps))
                call __lsl_qbe_call1(__lsl_symbol("gst_mini_object_unref"), caps)
            end
            call __lsl_qbe_call1(__lsl_symbol("gst_object_unref"), pad)
        end
        # GST_STATE_NULL = 1
        call __lsl_qbe_call2(__lsl_symbol("gst_element_set_state"), src, 1)
        call __lsl_qbe_call1(__lsl_symbol("gst_object_unref"), src)
    end
    if failed:
        return ["", False, "open"]
    end
    picked = None
    if offered != "":
        picked = pick_caps(offered)
    end
    if picked == None:
        return ["", False, ""]
    end
    return [picked[0], picked[1], ""]
end

# ---- nahled --------------------------------------------------------------------------------------

function start(path, caps, jpeg):
    return start_with(path, caps, jpeg, {"mirror": True})
end

function has(factory):
    call init()
    unsafe:
        found = __lsl_qbe_call1(__lsl_symbol("gst_element_factory_find"), cstr(factory))
        if found == 0:
            return False
        end
        call __lsl_qbe_call1(__lsl_symbol("gst_object_unref"), found)
    end
    return True
end

function element_set(name, property, value):
    if cam["pipeline"] == 0:
        return 0
    end
    unsafe:
        element = __lsl_qbe_call2(__lsl_symbol("gst_bin_get_by_name"), ptr(cam["pipeline"]), cstr(name))
        if element != 0:
            call __lsl_qbe_call3(__lsl_symbol("gst_util_set_object_arg"), element, cstr(property), cstr(value))
            call __lsl_qbe_call1(__lsl_symbol("gst_object_unref"), element)
        end
    end
end

function set_mirror(on):
    call element_set("flip", "method", "horizontal-flip" if on else "none")
end

function start_with(path, caps, jpeg, opts):
    call init()
    call stop()
    image = opts.get("image", "")
    src = ""
    if path.startswith("test:") and image != "":
        src = "filesrc name=img ! decodebin ! videoconvert ! imagefreeze is-live=true ! video/x-raw,framerate=15/1 ! "
    elif path.startswith("test:"):
        pattern = "smpte" if path == "test:0" else "ball"
        src = "videotestsrc name=src is-live=true pattern=" + pattern + " ! video/x-raw,width=1280,height=720,framerate=30/1 ! "
    else:
        src = "v4l2src name=src ! "
        if caps != "":
            src += caps + " ! "
        end
        if jpeg:
            src += "jpegdec ! "
        end
    end
    desc = src + "videoconvert ! videoflip name=flip ! tee name=t t. ! queue leaky=downstream max-size-buffers=2 ! videoconvert ! video/x-raw,format=BGRx ! appsink name=view sync=false drop=true max-buffers=1 "
    record = opts.get("record", None)
    if record != None:
        enc = record["encoder"]
        desc += "t. ! queue leaky=downstream max-size-buffers=0 max-size-bytes=0 max-size-time=3000000000 ! videoconvert ! " + enc[0] + " ! queue ! " + enc[1] + " name=mux ! filesink name=out "
        if record.get("audio", "") != "" and enc[3] != "":
            desc += record["audio"] + " name=asrc ! queue max-size-time=3000000000 ! audioconvert ! audioresample ! " + enc[3] + " ! queue ! mux. "
        end
    end
    message = ""
    unsafe:
        cell = __lsl_byte_zeros(8)
        where = __lsl_qbe_load64(__lsl_address(cell) + 24)
        pipe = __lsl_qbe_call2(__lsl_symbol("gst_parse_launch"), cstr(desc), where)
        error = __lsl_qbe_load64(where)
        if error != 0:
            message = glib.from_c(__lsl_qbe_load64(error + 8))
            call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
            if pipe != 0:
                call __lsl_qbe_call1(__lsl_symbol("gst_object_unref"), pipe)
            end
        end
    end
    if message != "":
        return message
    end
    cam["pipeline"] = pipe
    if not path.startswith("test:"):
        call element_set("src", "device", path)
    elif image != "":
        call element_set("img", "location", image)
    end
    if record != None:
        call element_set("out", "location", record["path"])
    end
    call set_mirror(opts.get("mirror", True))
    unsafe:
        cam["sink"] = __lsl_qbe_call2(__lsl_symbol("gst_bin_get_by_name"), pipe, cstr("view"))
        cam["bus"] = __lsl_qbe_call1(__lsl_symbol("gst_element_get_bus"), pipe)
        # GST_STATE_PLAYING = 4
        call __lsl_qbe_call2(__lsl_symbol("gst_element_set_state"), pipe, 4)
    end
    cam["error"] = ""
    return ""
end

# Konec proudu: muxer dopise soubor a na sbernici prijde EOS (poll vrati "eos")
function send_eos():
    if cam["pipeline"] == 0:
        return 0
    end
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("gst_element_send_event"), ptr(cam["pipeline"]), __lsl_qbe_call0(__lsl_symbol("gst_event_new_eos")))
    end
end

# Ceka na EOS nebo chybu (nejvys sekundy) - pri zavirani okna, kdy uz hlavni smycka nebezi
function wait_eos(seconds):
    if cam["pipeline"] == 0:
        return 0
    end
    call send_eos()
    unsafe:
        # GST_MESSAGE_EOS | GST_MESSAGE_ERROR
        message = __lsl_qbe_call3(__lsl_symbol("gst_bus_timed_pop_filtered"), ptr(cam["bus"]), ptr(seconds) * 1000000000, 1 | 2)
        if message != 0:
            call __lsl_qbe_call1(__lsl_symbol("gst_mini_object_unref"), message)
        end
    end
end

function stop():
    if cam["pipeline"] == 0:
        return 0
    end
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("gst_element_set_state"), ptr(cam["pipeline"]), 1)
        call __lsl_qbe_call1(__lsl_symbol("gst_object_unref"), ptr(cam["sink"]))
        call __lsl_qbe_call1(__lsl_symbol("gst_object_unref"), ptr(cam["bus"]))
        call __lsl_qbe_call1(__lsl_symbol("gst_object_unref"), ptr(cam["pipeline"]))
        if ptr(cam["surface"]) != 0:
            call __lsl_qbe_call1(__lsl_symbol("cairo_surface_destroy"), ptr(cam["surface"]))
        end
    end
    cam["pipeline"] = 0
    cam["sink"] = 0
    cam["bus"] = 0
    cam["surface"] = 0
end

function running():
    return cam["pipeline"] != 0
end

function surface():
    return cam["surface"]
end

function error_text():
    return cam["error"]
end

function error_busy():
    return cam["busy"]
end

function error_debug():
    return cam["debug"]
end

function error_source():
    return cam["source"]
end

# Chyba na sbernici GStreamer (kamera obsazena, odpojena...): "error", konec videa "eos", novy snimek: "frame"
function poll():
    if cam["pipeline"] == 0:
        return ""
    end
    unsafe:
        # GST_MESSAGE_EOS = 1
        message = __lsl_qbe_call2(__lsl_symbol("gst_bus_pop_filtered"), ptr(cam["bus"]), 1)
        if message != 0:
            call __lsl_qbe_call1(__lsl_symbol("gst_mini_object_unref"), message)
            return "eos"
        end
        # GST_MESSAGE_ERROR = 2
        message = __lsl_qbe_call2(__lsl_symbol("gst_bus_pop_filtered"), ptr(cam["bus"]), 2)
        if message != 0:
            # GstMessage.src (za GstMiniObject 64 B, type a timestamp)
            src = __lsl_qbe_load64(message + 80)
            cam["source"] = ""
            if src != 0:
                cam["source"] = glib.take_c(__lsl_qbe_call1(__lsl_symbol("gst_object_get_path_string"), src))
            end
            cell = __lsl_byte_zeros(16)
            base = __lsl_qbe_load64(__lsl_address(cell) + 24)
            call __lsl_qbe_call3(__lsl_symbol("gst_message_parse_error"), message, base, base + 8)
            error = __lsl_qbe_load64(base)
            reason = glib.from_c(__lsl_qbe_load64(error + 8))
            cam["debug"] = glib.from_c(__lsl_qbe_load64(base + 8))
            # GST_RESOURCE_ERROR_BUSY = 4
            busy = __lsl_qbe_s32(__lsl_qbe_load32(error)) == __lsl_qbe_s32(__lsl_qbe_call0(__lsl_symbol("gst_resource_error_quark"))) and __lsl_qbe_s32(__lsl_qbe_load32(error + 4)) == 4
            call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
            call __lsl_qbe_call1(__lsl_symbol("g_free"), __lsl_qbe_load64(base + 8))
            call __lsl_qbe_call1(__lsl_symbol("gst_mini_object_unref"), message)
            cam["error"] = reason
            cam["busy"] = busy or reason.lower().find("busy") >= 0
            return "error"
        end
        sample = __lsl_qbe_call2(__lsl_symbol("gst_app_sink_try_pull_sample"), ptr(cam["sink"]), 0)
        if sample == 0:
            return ""
        end
        s = __lsl_qbe_call2(__lsl_symbol("gst_caps_get_structure"), __lsl_qbe_call1(__lsl_symbol("gst_sample_get_caps"), sample), 0)
        wcell = __lsl_byte_zeros(8)
        hcell = __lsl_byte_zeros(8)
        wp = __lsl_qbe_load64(__lsl_address(wcell) + 24)
        hp = __lsl_qbe_load64(__lsl_address(hcell) + 24)
        call __lsl_qbe_call3(__lsl_symbol("gst_structure_get_int"), s, cstr("width"), wp)
        call __lsl_qbe_call3(__lsl_symbol("gst_structure_get_int"), s, cstr("height"), hp)
        w = __lsl_qbe_s32(__lsl_qbe_load32(wp))
        h = __lsl_qbe_s32(__lsl_qbe_load32(hp))
        buffer = __lsl_qbe_call1(__lsl_symbol("gst_sample_get_buffer"), sample)
        info = __lsl_byte_zeros(104)
        map = __lsl_qbe_load64(__lsl_address(info) + 24)
        got = False
        # GST_MAP_READ = 1; GstMapInfo: data +16, size +24
        if __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("gst_buffer_map"), buffer, map, 1)) != 0:
            if __lsl_qbe_load64(map + 24) >= w * 4 * h and w > 0 and h > 0:
                call copy_frame(__lsl_qbe_load64(map + 16), w, h)
                got = True
            end
            call __lsl_qbe_call2(__lsl_symbol("gst_buffer_unmap"), buffer, map)
        end
        call __lsl_qbe_call1(__lsl_symbol("gst_mini_object_unref"), sample)
    end
    if got:
        return "frame"
    end
    return ""
end

# Snimek BGRx do cairo RGB24 (stejne poradi bajtu na little endian)
function copy_frame(pixels, w, h):
    unsafe:
        if ptr(cam["surface"]) == 0 or cam["w"] != w or cam["h"] != h:
            if ptr(cam["surface"]) != 0:
                call __lsl_qbe_call1(__lsl_symbol("cairo_surface_destroy"), ptr(cam["surface"]))
            end
            # CAIRO_FORMAT_RGB24 = 1
            cam["surface"] = __lsl_qbe_call3(__lsl_symbol("cairo_image_surface_create"), 1, ptr(w), ptr(h))
            cam["w"] = w
            cam["h"] = h
        end
        surface = ptr(cam["surface"])
        call __lsl_qbe_call1(__lsl_symbol("cairo_surface_flush"), surface)
        target = __lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_data"), surface)
        stride = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_stride"), surface))
        row = ptr(w) * 4
        y = 0
        while y < ptr(h):
            call __lsl_qbe_call3(__lsl_symbol("memcpy"), target + y * stride, ptr(pixels) + y * row, row)
            y += 1
        end
        call __lsl_qbe_call1(__lsl_symbol("cairo_surface_mark_dirty"), surface)
    end
end
