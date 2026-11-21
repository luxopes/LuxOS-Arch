# LuxOS - klient IPC luxwm pro shell (lista, nastaveni, luxwm-msg). Protokol: docs/developers/luxwm-ipc.md
# (radkovy JSON na $XDG_RUNTIME_DIR/luxwm-$WAYLAND_DISPLAY.sock). Udalosti chodi v hlavni smycce GLib.
#
#   connect(f)            f(udalost) pro kazdou udalost (slovnik s "event"); vraci True, kdyz je spojeni hned;
#                         bez luxwm (labwc, X11) zkousi znovu po 1, 2, 4 ... nejvys 30 s, po spojeni obnovi odbery
#   subscribe([tema..])   odber; pamatuje si ho pro dalsi spojeni
#   request(zprava, f)    posle prikaz, f(odpoved) nebo None; False kdyz spojeni neni
#   connected(), disconnect(), socket_path()
#   on_state(f)           f(True/False) pri spojeni a odpojeni
load glib, env, fd, net, json
load luxos_glib as lglib

MAX_LINE = 65536

c = {"fd": -1, "watch": 0, "handler": None, "state": None, "topics": [], "pending": [], "next_id": 1,
     "buffer": None, "retry": 0, "delay": 1, "auto": False}

function socket_path():
    path = env.get("LUXWM_SOCK", "")
    if path != "":
        return path
    end
    runtime = env.get("XDG_RUNTIME_DIR", "")
    display = env.get("WAYLAND_DISPLAY", "")
    if runtime == "" or display.startswith("/"):
        return ""
    end
    if display == "":
        display = "wayland-0"
    end
    return runtime + "/luxwm-" + display + ".sock"
end

function connected():
    return c["fd"] >= 0
end

function on_state(f):
    c["state"] = f
    return 0
end

function write_line(text):
    if c["fd"] < 0:
        return False
    end
    data = net.bytes(text + "\n")
    try:
        call fd.write(c["fd"], data, len(data))
    else:
        call drop()
        return False
    end
    return True
end

function send(message, f):
    message["id"] = c["next_id"]
    c["next_id"] += 1
    if not write_line(json.encode(message)):
        return False
    end
    c["pending"].append([message["id"], f])
    return True
end

function request(message, f):
    return send(message, f)
end

function subscribe(topics):
    for topic in topics:
        if topic not in c["topics"]:
            c["topics"].append(topic)
        end
    end
    if c["fd"] >= 0:
        return send({"cmd": "subscribe", "events": topics}, None)
    end
    return False
end

function deliver(line):
    message = None
    safe:
        message = json.decode(line)
    end
    if type(message) != "Dictionary":
        return 0
    end
    if "event" in message:
        handler = c["handler"]
        if handler != None:
            call handler(message)
        end
        return 0
    end
    rid = message.get("id", None)
    for i in range(len(c["pending"])):
        entry = c["pending"][i]
        if entry[0] == rid:
            call c["pending"].pop(i)
            if entry[1] != None:
                f = entry[1]
                call f(message)
            end
            break
        end
    end
    return 0
end

# Bajty se skladaji az do konce radku: znak UTF-8 muze byt rozdeleny mezi dve cteni
function on_readable(handle, condition):
    unsafe:
        chunk = __lsl_byte_zeros(4096)
    end
    n = 0
    try:
        n = fd.read(handle, chunk, 4096)
    else:
        n = 0
    end
    if n == fd.again:
        return True
    end
    if n <= 0:
        c["watch"] = 0
        call drop()
        return False
    end
    buffer = c["buffer"]
    start = len(buffer)
    unsafe:
        grown = __lsl_byte_zeros(start + n)
        call __lsl_byte_copy(grown, buffer, 0, 0, start)
        call __lsl_byte_copy(grown, chunk, start, 0, n)
    end
    buffer = grown
    first = 0
    i = start
    while i < len(buffer):
        if buffer[i] == 10:
            line = ""
            unsafe:
                line = __lsl_text_from_bytes(buffer, first, i - first)
            end
            first = i + 1
            call deliver(line)
            if c["fd"] != handle:
                return False
            end
        end
        i += 1
    end
    rest = len(buffer) - first
    if rest > MAX_LINE:
        call drop()
        return False
    end
    unsafe:
        left = __lsl_byte_zeros(rest)
        call __lsl_byte_copy(left, buffer, 0, first, rest)
    end
    c["buffer"] = left
    return True
end

function notify(up):
    f = c["state"]
    if f != None:
        call f(up)
    end
    return 0
end

function open_socket():
    path = socket_path()
    if path == "":
        return False
    end
    handle = -1
    try:
        handle = fd.connect_unix(path)
    else:
        return False
    end
    c["fd"] = handle
    unsafe:
        c["buffer"] = __lsl_byte_zeros(0)
    end
    c["pending"] = []
    c["delay"] = 1
    # G_IO_IN 1 | G_IO_ERR 8 | G_IO_HUP 16
    c["watch"] = glib.fd_add(handle, 25, on_readable)
    if len(c["topics"]) > 0:
        call send({"cmd": "subscribe", "events": c["topics"]}, None)
    end
    call notify(True)
    return True
end

function on_retry(unused):
    c["retry"] = 0
    if c["fd"] < 0 and c["auto"] and not open_socket():
        call schedule_retry()
    end
    return False
end

function schedule_retry():
    if c["retry"] == 0 and c["auto"]:
        # zaznam obsluhy uvolni GLib (glib.timeout_add_seconds by ho drzel navzdy: bez luxwm, napr. pod labwc,
        # pribyval kazdych 30 s)
        c["retry"] = lglib.timeout_add_seconds_data(c["delay"], on_retry, 0)
        c["delay"] = min(30, c["delay"] * 2)
    end
    return 0
end

function drop():
    if c["fd"] < 0:
        return 0
    end
    if c["watch"] != 0:
        call glib.source_remove(c["watch"])
        c["watch"] = 0
    end
    safe:
        call fd.close(c["fd"])
    end
    c["fd"] = -1
    c["pending"] = []
    call notify(False)
    call schedule_retry()
    return 0
end

function connect(handler):
    c["handler"] = handler
    c["auto"] = True
    if c["fd"] >= 0:
        return True
    end
    if open_socket():
        return True
    end
    call schedule_retry()
    return False
end

function disconnect():
    c["auto"] = False
    if c["retry"] != 0:
        call glib.source_remove(c["retry"])
        c["retry"] = 0
    end
    call drop()
    return 0
end
