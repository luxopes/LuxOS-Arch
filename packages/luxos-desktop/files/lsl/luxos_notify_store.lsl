# LuxOS - historie oznameni (zvonek v liste) pro luxos-notify: zaznamy v pameti, ulozene v
# ~/.local/share/luxos/notifications.json (0600, obsah zprav). Jen logika bez GTK a D-Bus.
#
# Zaznam: {"id", "time" (us), "tz", "app_id" (desktop-entry), "app", "icon", "summary", "body",
#          "actions" [[klic, popis]..], "timeout", "read", "nid" (cislo oznameni), "sender", "gone"}
# Nejnovejsi prvni, nejvys MAX zaznamu, set_max(n) jinak (HISTORY_SIZE, jako log-max-size xfce4-notifyd).
#
#   load(dir)                     nacte dir/notifications.json a cislo pristiho oznameni
#   save()                        zapise soubor (atomicky)
#   add(e) -> [id, smazane id..]  novy zaznam; nejstarsi nad MAX vypadnou
#   find(id), with_nid(nid)       zaznam podle id / zaznamy oznameni
#   remove(ids) -> smazane id     mark_read(ids) -> zmenene id, mark_all_read() -> zmenene id
#   truncate(keep), clear()
#   row(e)                        n-tice (sxssssssa(ss)ib) rozhrani org.xfce.Notifyd.Log
#   rows(start_after, count, only_unread)
load glib, json
load luxos_glib as lglib
load luxos_notify_sys as sys

MAX = 100

state = {"dir": "", "path": "", "entries": [], "next_nid": 1, "seq": 0, "max": MAX}

function load(dir):
    path = dir + "/notifications.json"
    state["dir"] = dir
    state["path"] = path
    text = lglib.read_text(path)
    if text == "":
        return 0
    end
    data = None
    try:
        data = json.decode(text)
    else:
        # poskozeny soubor nesmi zastavit oznameni; necha se prepsat dalsim ulozenim
        call glib.report("luxos-notify: " + path + ": " + String(last_error()) + chr(10))
        return 0
    end
    if type(data) != "Dictionary":
        return 0
    end
    entries = []
    for e in data.get("entries", []):
        if type(e) == "Dictionary" and type(e.get("id", None)) == "String":
            entries.append(e)
        end
    end
    state["entries"] = entries[0:state["max"]]
    next_nid = data.get("next_nid", 1)
    if type(next_nid) == "Int" and next_nid > 0 and next_nid < 4294967295:
        state["next_nid"] = next_nid
    end
    return len(entries)
end

function set_max(n):
    state["max"] = n
    return 0
end

function save():
    if state["path"] == "":
        return False
    end
    call lglib.mkdir_p(state["dir"])
    text = json.encode({"version": 1, "next_nid": state["next_nid"], "entries": state["entries"]})
    # 0600: historie obsahuje text zprav
    return sys.write_private(state["path"], text)
end

# Nove cislo oznameni; pokracuje i po restartu (aplikace si stara cisla pamatuji)
function take_nid():
    nid = state["next_nid"]
    state["next_nid"] = nid + 1
    if state["next_nid"] >= 4294967295:
        state["next_nid"] = 1
    end
    return nid
end

function new_id():
    state["seq"] += 1
    return String(sys.real_time()) + "-" + String(state["seq"])
end

function add(e):
    e["id"] = new_id()
    state["entries"].insert(0, e)
    dropped = [e["id"]]
    while len(state["entries"]) > state["max"]:
        dropped.append(state["entries"].pop()["id"])
    end
    return dropped
end

function find(id):
    for e in state["entries"]:
        if e["id"] == id:
            return e
        end
    end
    return None
end

function with_nid(nid):
    return [e for e in state["entries"] if e.get("nid", 0) == nid]
end

function remove(ids):
    removed = [e["id"] for e in state["entries"] if e["id"] in ids]
    state["entries"] = [e for e in state["entries"] if not (e["id"] in ids)]
    return removed
end

function mark_read(ids):
    changed = []
    for e in state["entries"]:
        if e["id"] in ids and not e["read"]:
            e["read"] = True
            changed.append(e["id"])
        end
    end
    return changed
end

function mark_all_read():
    return mark_read([e["id"] for e in state["entries"]])
end

function truncate(keep):
    removed = [e["id"] for e in state["entries"][keep:]]
    state["entries"] = state["entries"][0:keep]
    return removed
end

function clear():
    removed = [e["id"] for e in state["entries"]]
    state["entries"] = []
    return removed
end

function has_unread():
    for e in state["entries"]:
        if not e["read"]:
            return True
        end
    end
    return False
end

function app_counts():
    counts = {}
    for e in state["entries"]:
        counts[e["app_id"]] = counts.get(e["app_id"], 0) + 1
    end
    return [[k, counts[k]] for k in sorted(counts.keys())]
end

function row(e):
    return [e["id"], e["time"], e["tz"], e["app_id"], e["app"], e["icon"], e["summary"], e["body"], e["actions"], e["timeout"], e["read"]]
end

# Starsi zaznamy za start_after ("" = od nejnovejsiho), nejvys count (0 = vsechny)
function rows(start_after, count, only_unread):
    result = []
    started = start_after == ""
    for e in state["entries"]:
        if not started:
            started = e["id"] == start_after
            continue
        end
        if only_unread and e["read"]:
            continue
        end
        result.append(row(e))
        if count > 0 and len(result) >= count:
            break
        end
    end
    return result
end
