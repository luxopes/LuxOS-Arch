# Posta LuxOS - sluzba na pozadi (`luxos-mail --background`, spousti ji relace pres XDG autostart).
# Drzi jedno spojeni IMAP na ucet: po synchronizaci ceka v IDLE na INBOX (server sam oznami novou zpravu),
# bez IDLE kontroluje kazdych 5 minut. Nova neprectena zprava -> upozorneni "Nova posta od X" s akci
# Otevrit (otevre aplikaci na te zprave); rezim Nerusit respektuje xfce4-notifyd. Po zmene site
# (NetworkManager) a probuzeni (logind) se spoji znovu, pri vypadku ceka 5 s, 10 s ... nejvys 15 min.
# Spatne heslo se znovu nezkousi (zadne zablokovani uctu na serveru), az po zadani noveho.
# Schranky LuxAI (ucet "auth": "luxai") heslo nemaji: pred kazdym spojenim si sluzba vyzada od serveru
# LuxAI kratkodoby token (ucet LuxAI tohoto pocitace, mail_luxai) a prihlasi se SASL OAUTHBEARER/XOAUTH2.
#
# Okno (luxos-mail) mezipamet jen cte a o vse ostatni zada sluzbu pres abstraktni socket UNIX
# "luxos-mail-<uid>" (jen procesy tehoz uzivatele): radky JSON {"id", "op", ...} -> {"id", "ok", ...}
# a udalosti {"event": "changed"|"status", ...} pro vsechna pripojena okna.
load env, json, net
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_sys
load luxos_i18n as i18n
load mail_bytes as mb
load mail_mime as mime
load mail_imap as imap
load mail_store as store
load mail_secret as secret
load mail_luxai as luxai

ITEMS = "UID FLAGS INTERNALDATE RFC822.SIZE ENVELOPE BODYSTRUCTURE"
INITIAL = 500
OLDER = 500
IDLE_REFRESH = 1500
POLL_SECONDS = 300
BACKOFF_MAX = 900
MAX_BODY = 67108864
NM = "org.freedesktop.NetworkManager"

svc = {"listen": -1, "clients": [], "session": 0, "system": 0, "notes": {}, "badge": -1, "accounts": {}, "order": [],
       "nm_state": 0, "exit_timer": 0, "next_note": 0}

function log(message):
    return eprint("luxos-mail: " + message)
end

function socket_name():
    return store.socket_name("")
end

function now():
    return glib.now()
end

# ---- klienti (okna) -------------------------------------------------------------------------------------------

function send_json(client, value):
    if client["fd"] < 0:
        return False
    end
    if not mb.send(client["fd"], json.encode(value) + "\n"):
        call drop_client(client)
        return False
    end
    return True
end

function broadcast(value):
    for c in svc["clients"].copy():
        call send_json(c, value)
    end
    return 0
end

function drop_client(client):
    if client["fd"] >= 0:
        call luxos_sys.close(client["fd"])
        client["fd"] = -1
    end
    if client in svc["clients"]:
        call svc["clients"].remove(client)
    end
    call schedule_exit_check()
    return 0
end

function on_accept(unused, fd, condition):
    loop:
        conn = luxos_sys.unix_accept(svc["listen"])
        if conn < 0:
            break
        end
        if luxos_sys.peer_uid(conn) != mb.getuid():
            call luxos_sys.close(conn)
            continue
        end
        client = {"fd": conn, "buf": ByteArray()}
        svc["clients"].append(client)
        call glib.fd_add_data(conn, 1 + 8 + 16, on_client_data, client)
    end
    return True
end

function on_client_data(client, fd, condition):
    if client["fd"] < 0:
        return False
    end
    data = mb.recv(client["fd"], 262144)
    if data == False:
        return True
    end
    if len(data) == 0:
        call drop_client(client)
        return False
    end
    client["buf"] = mb.concat(client["buf"], data)
    loop:
        buf = client["buf"]
        nl = mb.find_byte(buf, 10, 0, len(buf))
        if nl < 0:
            break
        end
        line = net.text(buf, 0, nl)
        client["buf"] = mb.sub(buf, nl + 1, len(buf))
        req = None
        safe:
            req = json.decode(line)
        end
        if type(req) == "Dictionary":
            reply = {}
            try:
                reply = handle(req)
            else:
                kind = imap.error_kind(last_error())
                reply = {"ok": False, "kind": kind[0], "error": kind[1]}
            end
            reply["id"] = req.get("id", 0)
            reply["op"] = req.get("op", "")
            call send_json(client, reply)
            if client["fd"] < 0:
                return False
            end
        end
    end
    return True
end

# ---- stav uctu ----------------------------------------------------------------------------------------------

function new_state(cfg):
    return {"cfg": cfg, "conn": {}, "state": "offline", "kind": "", "error": "", "password": "", "watch": [], "backoff": 0,
            "retry": 0, "idle_timer": 0, "poll_timer": 0, "debounce": 0, "boxes": [], "started": False}
end

function status_of(st):
    return {"account": st["cfg"]["id"], "state": st["state"], "kind": st["kind"], "error": st["error"]}
end

function set_state(st, state, kind, error):
    changed = st["state"] != state or st["error"] != error
    st["state"] = state
    st["kind"] = kind
    st["error"] = error
    if changed:
        ev = status_of(st)
        ev["event"] = "status"
        call broadcast(ev)
    end
    return 0
end

function connected(st):
    conn = st["conn"]
    return len(conn) > 0 and not conn["closed"]
end

function cancel_timers(st):
    for key in ["retry", "idle_timer", "poll_timer", "debounce"]:
        if st[key] != 0:
            call glib.source_remove(st[key])
            st[key] = 0
        end
    end
    return 0
end

function stop_watch(st):
    if len(st["watch"]) == 2:
        call glib.source_remove(st["watch"][0])
        call glib.release(st["watch"][1])
    end
    st["watch"] = []
    return 0
end

function disconnect(st):
    call stop_watch(st)
    call cancel_timers(st)
    if connected(st):
        call imap.close(st["conn"])
    end
    st["conn"] = {}
    return 0
end

function is_luxai(cfg):
    return cfg.get("auth", "") == "luxai"
end

# Chyby, po kterych se samo znovu nezkousi (cekani na uzivatele: nove heslo, prihlaseni k LuxAI)
function blocked_kind(kind):
    return kind in ["auth", "nopassword", "luxai_session", "luxai_signedout", "luxai_denied", "nooauth"]
end

# Spojeni a prihlaseni tokenem LuxAI (novy token pri kazdem spojeni; plati 15 minut, otevrene spojeni
# vcetne IDLE plati dal)
function luxai_login(cfg, s):
    address = String(s.get("user", cfg["email"]))
    t = luxai.token(address)
    if not t["ok"]:
        call imap.fail(t["kind"], t["error"])
    end
    conn = imap.connect(s["host"], s["port"], s["security"], 15000)
    try:
        call imap.login_oauth(conn, address, t["token"], s["port"])
    else:
        err = last_error()
        call imap.close(conn)
        Error(MailError: String(err).replace("MailError: ", ""))
    end
    return conn
end

# Spojeni, prihlaseni, seznam schranek; MailError pri chybe
function open_connection(st):
    cfg = st["cfg"]
    s = cfg["imap"]
    if is_luxai(cfg):
        call set_state(st, "connecting", "", "")
        conn = luxai_login(cfg, s)
        try:
            call imap.enable_extensions(conn)
        else:
            err = last_error()
            call imap.close(conn)
            Error(MailError: String(err).replace("MailError: ", ""))
        end
        st["conn"] = conn
        call refresh_mailboxes(st)
        return conn
    end
    if st["password"] == "":
        st["password"] = secret.lookup(cfg["id"])
    end
    if st["password"] == "":
        call imap.fail("nopassword", "The password is not in the keyring.")
    end
    call set_state(st, "connecting", "", "")
    conn = imap.connect(s["host"], s["port"], s["security"], 15000)
    try:
        call imap.login(conn, s.get("user", cfg["email"]), st["password"])
        call imap.enable_extensions(conn)
    else:
        err = last_error()
        call imap.close(conn)
        Error(MailError: String(err).replace("MailError: ", ""))
    end
    st["conn"] = conn
    call refresh_mailboxes(st)
    return conn
end

function refresh_mailboxes(st):
    id = st["cfg"]["id"]
    old = {}
    for b in store.load_mailboxes(id):
        old[b["raw"]] = b
    end
    boxes = imap.list_mailboxes(st["conn"])
    has_inbox = False
    for b in boxes:
        prev = old.get(b["raw"], {})
        b["unseen"] = prev.get("unseen", 0)
        b["total"] = prev.get("total", 0)
        if b["raw"] == "INBOX":
            has_inbox = True
        end
    end
    if not has_inbox:
        boxes.insert(0, {"raw": "INBOX", "name": "INBOX", "delim": "/", "role": "inbox", "selectable": True, "unseen": 0, "total": 0})
    end
    st["boxes"] = boxes
    call store.save_mailboxes(id, boxes)
    return boxes
end

function update_box_counts(st, raw, unseen, total):
    boxes = st["boxes"]
    if len(boxes) == 0:
        boxes = store.load_mailboxes(st["cfg"]["id"])
        st["boxes"] = boxes
    end
    for b in boxes:
        if b["raw"] == raw:
            b["unseen"] = unseen
            b["total"] = total
        end
    end
    call store.save_mailboxes(st["cfg"]["id"], boxes)
    call update_badge()
    return 0
end

function role_box(st, role):
    for b in st["boxes"]:
        if b["role"] == role and b.get("selectable", True):
            return b["raw"]
        end
    end
    return ""
end

# ---- synchronizace schranky ------------------------------------------------------------------------------------

function make_row(f):
    env = imap.envelope(f.get("ENVELOPE", None))
    bs = imap.bodystructure(f.get("BODYSTRUCTURE", None))
    sender = ["", ""]
    if len(env["from"]) > 0:
        sender = env["from"][0]
    end
    to = ""
    if len(env["to"]) > 0:
        to = mime.address_display(env["to"][0])
    end
    internal = mime.parse_date(imap.tstr(f.get("INTERNALDATE", None)))
    date = env["date"]
    if date == 0:
        date = internal
    end
    if internal == 0:
        internal = date
    end
    flags = []
    for x in imap.tlist(f.get("FLAGS", None)):
        flags.append(imap.tstr(x))
    end
    return {"uid": imap.tint(f.get("UID", None), 0), "flags": store.flags_letters(flags), "internal": internal, "date": date,
            "from_name": sender[0], "from_email": sender[1], "to": to, "subject": env["subject"], "preview": "",
            "size": imap.tint(f.get("RFC822.SIZE", None), 0), "att": imap.has_attachments(bs), "_pp": imap.preview_part(bs)}
end

function fetch_previews(conn, rows):
    groups = {}
    order = []
    for r in rows:
        pp = r.get("_pp", {})
        if len(pp) == 0:
            continue
        end
        key = pp["section"]
        if key not in groups:
            groups[key] = []
            order.append(key)
        end
        groups[key].append(r)
    end
    for key in order:
        items = groups[key]
        start = 0
        while start < len(items):
            chunk = items[start:min(len(items), start + 200)]
            start += 200
            by_uid = {}
            uids = []
            for r in chunk:
                by_uid[r["uid"]] = r
                uids.append(r["uid"])
            end
            res = imap.uid_fetch(conn, imap.compress_set(uids), "UID BODY.PEEK[" + key + "]<0.2048>")
            for f in imap.fetches(res["untagged"]):
                uid = imap.tint(f.get("UID", None), 0)
                if uid not in by_uid:
                    continue
                end
                data = f.get("BODY[" + key + "]", None)
                if type(data) == "String":
                    data = net.bytes(data)
                end
                if type(data) != "ByteArray":
                    continue
                end
                r = by_uid[uid]
                pp = r["_pp"]
                safe:
                    r["preview"] = mime.preview_text(data, pp["encoding"], pp["params"].get("charset", ""), pp["type"] == "text/html")
                end
            end
        end
    end
    return 0
end

function apply_flags(by_uid, fetch_list):
    changed = False
    for f in fetch_list:
        uid = imap.tint(f.get("UID", None), 0)
        if uid in by_uid and "FLAGS" in f:
            flags = []
            for x in imap.tlist(f["FLAGS"]):
                flags.append(imap.tstr(x))
            end
            letters = store.flags_letters(flags)
            if by_uid[uid]["flags"] != letters:
                by_uid[uid]["flags"] = letters
                changed = True
            end
        end
    end
    return changed
end

function count_unseen(rows):
    n = 0
    for r in rows:
        if r["flags"].find("S") < 0 and r["flags"].find("D") < 0:
            n += 1
        end
    end
    return n
end

# Prirustkova synchronizace; vraci {"new": [nove radky], "changed": Bool}
function sync_mailbox(st, raw, older=False):
    conn = st["conn"]
    id = st["cfg"]["id"]
    state = store.load_state(id, raw)
    info = imap.select(conn, raw, state["uidvalidity"], state["highestmodseq"])
    rows = store.load_index(id, raw)
    if state["uidvalidity"] != 0 and info["uidvalidity"] != 0 and info["uidvalidity"] != state["uidvalidity"]:
        call log("UIDVALIDITY changed for a mailbox, refreshing its cache")
        call store.wipe_mailbox(id, raw)
        rows = []
        state = store.load_state(id, raw)
    end
    first = len(rows) == 0 and state["uidnext"] == 0
    by_uid = {}
    last_uid = 0
    oldest = 0
    for r in rows:
        by_uid[r["uid"]] = r
        if r["uid"] > last_uid:
            last_uid = r["uid"]
        end
        if oldest == 0 or r["uid"] < oldest:
            oldest = r["uid"]
        end
    end
    changed = False
    new_rows = []
    fetched = []
    if first:
        if info["exists"] > 0:
            start = max(1, info["exists"] - INITIAL + 1)
            fetched = imap.fetches(imap.fetch_seq(conn, String(start) + ":*", ITEMS)["untagged"])
        end
    elif older:
        if oldest > 1:
            uids = imap.uid_search(conn, "UID 1:" + String(oldest - 1))
            uids = sorted(uids)
            if len(uids) > OLDER:
                uids = uids[len(uids) - OLDER:]
            end
            if len(uids) > 0:
                fetched = imap.fetches(imap.uid_fetch(conn, imap.compress_set(uids), ITEMS)["untagged"])
            end
        end
    elif info["uidnext"] == 0 or info["uidnext"] > state["uidnext"] or last_uid == 0:
        fetched = imap.fetches(imap.uid_fetch(conn, String(last_uid + 1) + ":*", ITEMS)["untagged"])
    end
    # Dovecot posila behem FETCH i nevyzadane "* n FETCH (UID u MODSEQ (m) FLAGS (...))" (zmena priznaku,
    # napr. $HasNoAttachment po BODYSTRUCTURE); se zapnutym CONDSTORE/QRESYNC maji UID. Odpovedi pro stejne
    # UID se slouci (pozdejsi priznaky, obalka z prvni), jinak by prazdna odpoved prepsala zpravu.
    merged = {}
    order = []
    for f in fetched:
        uid = imap.tint(f.get("UID", None), 0)
        if uid <= 0:
            continue
        end
        if uid in merged:
            for key in f.keys():
                merged[uid][key] = f[key]
            end
        else:
            merged[uid] = f
            order.append(uid)
        end
    end
    for uid in order:
        f = merged[uid]
        if uid in by_uid or "ENVELOPE" not in f:
            continue
        end
        if not first and not older and uid <= last_uid:
            continue
        end
        row = make_row(f)
        new_rows.append(row)
    end
    if len(new_rows) > 0:
        call fetch_previews(conn, new_rows)
        for r in new_rows:
            call r.pop("_pp", None)
            by_uid[r["uid"]] = r
        end
        changed = True
    end
    # zmeny priznaku a smazane zpravy
    if not first and len(rows) > 0:
        vanished_known = False
        if len(info["fetches"]) > 0 and apply_flags(by_uid, info["fetches"]):
            changed = True
        end
        gone = info["vanished"]
        if conn["qresync"] and state["highestmodseq"] > 0:
            vanished_known = True
        end
        if conn["condstore"] and state["highestmodseq"] > 0 and info["highestmodseq"] > 0:
            if info["highestmodseq"] != state["highestmodseq"]:
                mods = "CHANGEDSINCE " + String(state["highestmodseq"])
                if conn["qresync"]:
                    mods = mods + " VANISHED"
                end
                res = imap.uid_fetch(conn, "1:" + String(max(last_uid, 1)), "UID FLAGS", mods)
                if apply_flags(by_uid, imap.fetches(res["untagged"])):
                    changed = True
                end
                extra = {"vanished": [], "exists": 0, "uidvalidity": 0, "uidnext": 0, "highestmodseq": 0, "fetches": []}
                call imap.absorb(extra, res["untagged"])
                gone = gone + extra["vanished"]
            end
        else:
            res = imap.uid_fetch(conn, String(max(oldest, 1)) + ":" + String(max(last_uid, 1)), "UID FLAGS")
            fl = imap.fetches(res["untagged"])
            if apply_flags(by_uid, fl):
                changed = True
            end
            present = {}
            for f in fl:
                present[imap.tint(f.get("UID", None), 0)] = True
            end
            for uid in list_keys(by_uid):
                if uid >= oldest and uid <= last_uid and uid not in present:
                    gone.append(uid)
                end
            end
            vanished_known = True
        end
        if not vanished_known:
            present = {}
            for uid in imap.uid_search(conn, "UID " + String(max(oldest, 1)) + ":*"):
                present[uid] = True
            end
            for uid in list_keys(by_uid):
                if uid not in present:
                    gone.append(uid)
                end
            end
        end
        for uid in gone:
            if uid in by_uid:
                call by_uid.pop(uid)
                changed = True
                safe:
                    call remove_path(store.body_path(id, raw, uid))
                end
            end
        end
    end
    merged = store.sort_messages(by_uid.values())
    if changed or first:
        call store.save_index(id, raw, merged)
    end
    max_uid = 0
    min_uid = 0
    for r in merged:
        if r["uid"] > max_uid:
            max_uid = r["uid"]
        end
        if min_uid == 0 or r["uid"] < min_uid:
            min_uid = r["uid"]
        end
    end
    if first:
        state["notified"] = max_uid
    end
    state["uidvalidity"] = info["uidvalidity"]
    state["uidnext"] = max(info["uidnext"], max_uid + 1)
    state["highestmodseq"] = info["highestmodseq"]
    state["oldest"] = min_uid
    state["exists"] = info["exists"]
    if type(state.get("notified")) != "Int":
        state["notified"] = max_uid
    end
    call store.save_state(id, raw, state)
    call update_box_counts(st, raw, count_unseen(merged), info["exists"])
    if changed:
        call broadcast({"event": "changed", "account": id, "mailbox": raw})
    end
    return {"new": new_rows, "changed": changed, "state": state}
end

function list_keys(d):
    out = []
    for k in d.keys():
        out.append(k)
    end
    return out
end

# ---- upozorneni ------------------------------------------------------------------------------------------------

function notify_new(st, raw, result):
    id = st["cfg"]["id"]
    state = result["state"]
    last = state.get("notified", 0)
    fresh = []
    top = last
    for r in result["new"]:
        if r["uid"] > last and r["flags"].find("S") < 0 and r["flags"].find("D") < 0:
            fresh.append(r)
        end
        if r["uid"] > top:
            top = r["uid"]
        end
    end
    if top != last:
        state["notified"] = top
        call store.save_state(id, raw, state)
    end
    if len(fresh) == 0 or svc["session"] == 0:
        return 0
    end
    if len(fresh) > 3:
        summary = i18n.TF("New messages: %d", [len(fresh)])
        body = st["cfg"]["email"]
        newest = fresh[0]
        for r in fresh:
            if r["uid"] > newest["uid"]:
                newest = r
            end
        end
        call send_note(summary, body, {"account": id, "mailbox": raw, "uid": newest["uid"]})
        return 0
    end
    for r in fresh:
        who = r["from_name"]
        if who == "":
            who = r["from_email"]
        end
        subject = r["subject"]
        if subject == "":
            subject = i18n.T("(no subject)")
        end
        body = glib.markup_escape(subject)
        if r["preview"] != "":
            body = body + "\n" + glib.markup_escape(r["preview"][0:min(len(r["preview"]), 120)])
        end
        call send_note(i18n.TF("New mail from %s", [who]), body, {"account": id, "mailbox": raw, "uid": r["uid"]})
    end
    return 0
end

function send_note(summary, body, target):
    actions = ["default", i18n.T("Open")]
    hints = {"category": ["s", "email.arrived"], "desktop-entry": ["s", "luxos-mail"]}
    call gio.call_async(svc["session"], "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify",
                        [i18n.T("Mail"), 0, "luxos-mail", summary, body, actions, hints, -1],
                        "(susssasa{sv}i)", 5000, on_notified, target)
    return 0
end

function on_notified(target, values, error):
    if values == None:
        call log("notification failed: " + error)
        return 0
    end
    svc["notes"][values[0]] = target
    if env.get("LUXOS_MAIL_NOTIFY_LOG", "") != "":
        safe:
            call appendfile(env.get("LUXOS_MAIL_NOTIFY_LOG", ""), json.encode({"id": values[0], "target": target}) + "\n")
        end
    end
    return 0
end

function on_action(sender, path, interface, signal, values):
    if len(values) < 2 or values[0] not in svc["notes"]:
        return 0
    end
    target = svc["notes"][values[0]]
    call glib.spawn([store.gui_binary(), "--open", target["account"], target["mailbox"], String(target["uid"])])
    return 0
end

function on_closed(sender, path, interface, signal, values):
    if len(values) >= 1 and values[0] in svc["notes"]:
        call svc["notes"].pop(values[0])
    end
    return 0
end

# Pocet neprectenych v Docku (Plank: com.canonical.Unity.LauncherEntry)
function update_badge():
    total = 0
    for id in svc["order"]:
        st = svc["accounts"][id]
        for b in st["boxes"]:
            if b["role"] == "inbox":
                total += b.get("unseen", 0)
            end
        end
    end
    if total == svc["badge"] or svc["session"] == 0:
        return 0
    end
    svc["badge"] = total
    safe:
        call gio.emit_values(svc["session"], "/cz/luxos/Mail", "com.canonical.Unity.LauncherEntry", "Update",
                             ["application://luxos-mail.desktop", {"count": ["x", total], "count-visible": ["b", total > 0]}], "(sa{sv})")
    end
    return 0
end

# ---- zivotni cyklus spojeni -------------------------------------------------------------------------------------

function start_account(st):
    call disconnect(st)
    ok = True
    err = ""
    try:
        call open_connection(st)
        result = sync_mailbox(st, "INBOX")
        call notify_new(st, "INBOX", result)
        call refresh_counts(st)
    else:
        ok = False
        err = String(last_error())
    end
    if not ok:
        call connection_failed(st, err)
        return False
    end
    st["backoff"] = 0
    call set_state(st, "online", "", "")
    call go_idle(st)
    return True
end

# Pocty neprectenych v ostatnich schrankach (STATUS), jen pro schranky bez mistni mezipameti
function refresh_counts(st):
    conn = st["conn"]
    for b in st["boxes"]:
        if b["raw"] == "INBOX" or not b.get("selectable", True) or b["role"] == "junk" or b["role"] == "trash":
            continue
        end
        r = imap.command(conn, "STATUS " + imap.quote(b["raw"]) + " (MESSAGES UNSEEN)", False)
        for resp in r["untagged"]:
            t = imap.resp_tokens(resp)
            if len(t) >= 3 and imap.tstr(t[0]).upper() == "STATUS":
                items = imap.tlist(t[2])
                i = 0
                while i + 1 < len(items):
                    key = imap.tstr(items[i]).upper()
                    if key == "UNSEEN":
                        b["unseen"] = imap.tint(items[i + 1], 0)
                    elif key == "MESSAGES":
                        b["total"] = imap.tint(items[i + 1], 0)
                    end
                    i += 2
                end
            end
        end
    end
    call store.save_mailboxes(st["cfg"]["id"], st["boxes"])
    call update_badge()
    return 0
end

function connection_failed(st, err):
    kind = imap.error_kind(err)
    call disconnect(st)
    call log("account " + st["cfg"]["id"] + ": " + kind[0] + ": " + kind[1])
    if blocked_kind(kind[0]):
        # spatne heslo: nezkouset znovu (server by ucet zablokoval), cekat na nove heslo;
        # schranka LuxAI: cekat na nove prihlaseni k uctu LuxAI (fail2ban na serveru po opakovani blokuje)
        st["password"] = ""
        call set_state(st, "error", kind[0], kind[1])
        return 0
    end
    call set_state(st, "offline", kind[0], kind[1])
    delay = 5
    k = 0
    while k < st["backoff"] and delay < BACKOFF_MAX:
        delay = delay * 2
        k += 1
    end
    delay = min(delay, BACKOFF_MAX)
    st["backoff"] = st["backoff"] + 1
    st["retry"] = glib.timeout_add_seconds_data(delay, on_retry, st)
    return 0
end

function on_retry(st):
    st["retry"] = 0
    call start_account(st)
    return False
end

function go_idle(st):
    if not connected(st):
        return 0
    end
    conn = st["conn"]
    try:
        if conn["selected"] != "INBOX":
            call imap.select(conn, "INBOX")
        end
        if imap.has_cap(conn, "IDLE"):
            call imap.idle_start(conn)
            st["watch"] = glib.fd_add_data(imap.socket_fd(conn), 1 + 8 + 16, on_idle_data, st)
            st["idle_timer"] = glib.timeout_add_seconds_data(IDLE_REFRESH, on_idle_refresh, st)
        else:
            st["poll_timer"] = glib.timeout_add_seconds_data(POLL_SECONDS, on_poll, st)
        end
    else:
        call connection_failed(st, String(last_error()))
    end
    return 0
end

# Ukonci IDLE pred dalsim prikazem; False kdyz spojeni mezitim spadlo
function leave_idle(st):
    call stop_watch(st)
    if st["idle_timer"] != 0:
        call glib.source_remove(st["idle_timer"])
        st["idle_timer"] = 0
    end
    if st["poll_timer"] != 0:
        call glib.source_remove(st["poll_timer"])
        st["poll_timer"] = 0
    end
    if not connected(st):
        return False
    end
    ok = True
    try:
        call imap.idle_done(st["conn"])
    else:
        ok = False
        call connection_failed(st, String(last_error()))
    end
    return ok
end

function on_idle_data(st, fd, condition):
    if not connected(st):
        st["watch"] = []
        return False
    end
    news = False
    ok = True
    err = ""
    try:
        resps = imap.poll(st["conn"])
        for r in resps:
            line = imap.first_line(r).upper()
            if line.find("EXISTS") >= 0 or line.find("EXPUNGE") >= 0 or line.find("FETCH") >= 0 or line.find("VANISHED") >= 0:
                news = True
            end
        end
    else:
        ok = False
        err = String(last_error())
    end
    if not ok:
        st["watch"] = []
        call connection_failed(st, err)
        return False
    end
    if news and st["debounce"] == 0:
        st["debounce"] = glib.timeout_add_data(400, on_idle_news, st)
    end
    return True
end

function on_idle_news(st):
    st["debounce"] = 0
    if not leave_idle(st):
        return False
    end
    ok = True
    try:
        result = sync_mailbox(st, "INBOX")
        call notify_new(st, "INBOX", result)
    else:
        ok = False
        call connection_failed(st, String(last_error()))
    end
    if ok:
        call go_idle(st)
    end
    return False
end

# IDLE obnovit pred 29 minutami (RFC 2177); zaroven overi, ze spojeni zije
function on_idle_refresh(st):
    st["idle_timer"] = 0
    if leave_idle(st):
        call go_idle(st)
    end
    return False
end

function on_poll(st):
    st["poll_timer"] = 0
    if not connected(st):
        call start_account(st)
        return False
    end
    ok = True
    try:
        result = sync_mailbox(st, "INBOX")
        call notify_new(st, "INBOX", result)
    else:
        ok = False
        call connection_failed(st, String(last_error()))
    end
    if ok:
        call go_idle(st)
    end
    return False
end

# Sit znovu pripojena nebo probuzeni: zrusit cekani a spojit se hned (stare spojeni po zmene site nemusi zit)
function reconnect_all(reason):
    call log("reconnecting (" + reason + ")")
    for id in svc["order"]:
        st = svc["accounts"][id]
        if st["state"] == "error":
            continue
        end
        st["backoff"] = 0
        call start_account(st)
    end
    return 0
end

function on_nm_state(sender, path, interface, signal, values):
    if len(values) < 1:
        return 0
    end
    state = values[0]
    previous = svc["nm_state"]
    svc["nm_state"] = state
    # 70 = NM_STATE_CONNECTED_GLOBAL
    if state == 70 and previous != 70 and previous != 0:
        call glib.timeout_add_data(1500, on_reconnect_timer, "network")
    end
    return 0
end

function on_sleep(sender, path, interface, signal, values):
    if len(values) >= 1 and values[0] == False:
        call glib.timeout_add_data(3000, on_reconnect_timer, "resume")
    end
    return 0
end

function on_reconnect_timer(reason):
    call reconnect_all(reason)
    return False
end

# ---- pozadavky okna -------------------------------------------------------------------------------------------

function account_state(id):
    if id not in svc["accounts"]:
        call imap.fail("noaccount", "Unknown account.")
    end
    return svc["accounts"][id]
end

# Spusti operaci nad spojenim uctu: ukonci IDLE, pripadne se spoji, po operaci zpet do IDLE
function begin_op(st):
    if connected(st):
        if not leave_idle(st):
            call imap.fail("closed", st["error"])
        end
        return 0
    end
    # odmitnute heslo: nezkouset ho znovu pri kazde akci v okne (server by ucet zablokoval)
    if st["state"] == "error" and blocked_kind(st["kind"]):
        call imap.fail(st["kind"], st["error"])
    end
    call disconnect(st)
    call open_connection(st)
    st["backoff"] = 0
    call set_state(st, "online", "", "")
    return 0
end

function end_op(st, err):
    if err != "":
        kind = imap.error_kind(err)
        if kind[0] == "closed" or kind[0] == "timeout" or kind[0] == "connect" or kind[0] == "tls" or kind[0] == "unavailable" or kind[0].startswith("luxai_"):
            call connection_failed(st, err)
            return 0
        end
        if blocked_kind(kind[0]) or kind[0] == "cert":
            call connection_failed(st, err)
            return 0
        end
    end
    if connected(st):
        call go_idle(st)
    end
    return 0
end

function account_op(req):
    st = account_state(req.get("account", ""))
    op = req["op"]
    result = {"ok": True}
    err = ""
    try:
        call begin_op(st)
        raw = req.get("mailbox", "INBOX")
        if op == "sync":
            r = sync_mailbox(st, raw, False)
            if raw == "INBOX":
                call notify_new(st, raw, r)
            end
            result["changed"] = r["changed"]
        elif op == "older":
            r = sync_mailbox(st, raw, True)
            result["added"] = len(r["new"])
        elif op == "body":
            result["path"] = fetch_body(st, raw, req["uid"])
        elif op == "flags":
            call set_flags(st, raw, req["uids"], req.get("add", True), req["flags"])
        elif op == "trash":
            result["deleted"] = trash(st, raw, req["uids"])
        elif op == "mailboxes":
            call refresh_mailboxes(st)
            call refresh_counts(st)
        end
    else:
        err = String(last_error())
    end
    call end_op(st, err)
    if err != "":
        kind = imap.error_kind(err)
        return {"ok": False, "kind": kind[0], "error": kind[1]}
    end
    return result
end

function fetch_body(st, raw, uid):
    conn = st["conn"]
    id = st["cfg"]["id"]
    if conn["selected"] != raw:
        call imap.select(conn, raw)
    end
    res = imap.uid_fetch(conn, String(uid), "UID RFC822.SIZE")
    for f in imap.fetches(res["untagged"]):
        if imap.tint(f.get("RFC822.SIZE", None), 0) > MAX_BODY:
            call imap.fail("toolarge", "The message is too large.")
        end
    end
    res = imap.uid_fetch(conn, String(uid), "UID BODY.PEEK[]")
    for f in imap.fetches(res["untagged"]):
        if imap.tint(f.get("UID", None), 0) != uid:
            continue
        end
        data = f.get("BODY[]", None)
        if type(data) == "String":
            data = net.bytes(data)
        end
        if type(data) == "ByteArray":
            return store.save_body(id, raw, uid, data)
        end
    end
    call imap.fail("gone", "The message no longer exists on the server.")
end

function rewrite_rows(st, raw, uids, add, letter, remove):
    id = st["cfg"]["id"]
    rows = store.load_index(id, raw)
    keep = []
    wanted = {}
    for u in uids:
        wanted[u] = True
    end
    for r in rows:
        if r["uid"] in wanted:
            if remove:
                safe:
                    call remove_path(store.body_path(id, raw, r["uid"]))
                end
                continue
            end
            f = r["flags"].replace(letter, "")
            if add:
                f = f + letter
            end
            r["flags"] = f
        end
        keep.append(r)
    end
    call store.save_index(id, raw, keep)
    state = store.load_state(id, raw)
    total = state.get("exists", 0)
    if remove:
        total = max(0, total - len(uids))
        state["exists"] = total
        call store.save_state(id, raw, state)
    end
    call update_box_counts(st, raw, count_unseen(keep), total)
    call broadcast({"event": "changed", "account": id, "mailbox": raw})
    return 0
end

function set_flags(st, raw, uids, add, flags):
    conn = st["conn"]
    if conn["selected"] != raw:
        call imap.select(conn, raw)
    end
    call imap.store_flags(conn, imap.compress_set(uids), add, flags)
    for f in flags:
        letter = store.flags_letters([f])
        if letter != "":
            call rewrite_rows(st, raw, uids, add, letter, False)
        end
    end
    return 0
end

# Do Kose; v Kosi (nebo bez Kose na serveru, ktery ho nejde vytvorit) smazat natrvalo. Vraci "moved"/"deleted"
function trash(st, raw, uids):
    conn = st["conn"]
    if conn["selected"] != raw:
        call imap.select(conn, raw)
    end
    set_text = imap.compress_set(uids)
    target = role_box(st, "trash")
    if target == "" and raw != "Trash":
        r = imap.create(conn, "Trash")
        call refresh_mailboxes(st)
        target = role_box(st, "trash")
        if target == "":
            target = "Trash"
        end
        if conn["selected"] != raw:
            call imap.select(conn, raw)
        end
    end
    how = "moved"
    if raw == target or target == "":
        call imap.store_flags(conn, set_text, True, ["\\Deleted"])
        call imap.expunge(conn, set_text)
        how = "deleted"
    else:
        call imap.move(conn, set_text, target)
    end
    call rewrite_rows(st, raw, uids, False, "", True)
    return how
end

# Novy ucet: overit prihlaseni, ulozit heslo do klicenky, ulozit ucet a pripojit
function add_account(req):
    email = String(req.get("email", "")).strip()
    s = req.get("imap", {})
    password = String(req.get("password", ""))
    if email == "" or type(s) != "Dictionary" or s.get("host", "") == "" or password == "":
        call imap.fail("invalid", "Missing account details.")
    end
    port = s.get("port", 993)
    if type(port) != "Int":
        port = mime.to_int(String(port), 993)
    end
    s = {"host": String(s["host"]).strip(), "port": port, "security": String(s.get("security", "ssl")), "user": String(s.get("user", email)).strip()}
    if s["user"] == "":
        s["user"] = email
    end
    conn = imap.connect(s["host"], s["port"], s["security"], 15000)
    try:
        call imap.login(conn, s["user"], password)
    else:
        err = last_error()
        call imap.close(conn)
        Error(MailError: String(err).replace("MailError: ", ""))
    end
    call imap.logout(conn)
    id = store.account_id(email)
    stored = secret.store(id, email, s["host"], password)
    if stored != True:
        call imap.fail("keyring", String(stored))
    end
    accounts = store.load_accounts()
    out = []
    for a in accounts:
        if a["id"] != id:
            out.append(a)
        end
    end
    smtp = req.get("smtp", {})
    if type(smtp) != "Dictionary":
        smtp = {}
    end
    cfg = {"id": id, "email": email, "name": String(req.get("name", "")), "imap": s, "smtp": smtp}
    out.append(cfg)
    call store.save_accounts(out)
    if id in svc["accounts"]:
        call disconnect(svc["accounts"][id])
    else:
        svc["order"].append(id)
    end
    st = new_state(cfg)
    st["password"] = password
    svc["accounts"][id] = st
    call start_account(st)
    return {"ok": True, "account": id, "state": st["state"], "error": st["error"]}
end

# Schranky LuxAI uctu tohoto pocitace; "added" = uz pridane v Poste
function luxai_mailboxes(req):
    r = luxai.mailboxes()
    if not r["ok"]:
        return r
    end
    ids = []
    for a in store.load_accounts():
        ids.append(a["id"])
    end
    for m in r["mailboxes"]:
        m["added"] = store.account_id(m["address"]) in ids
    end
    return {"ok": True, "mailboxes": r["mailboxes"]}
end

# Nova schranka LuxAI: nastaveni serveru vzdy ze serveru LuxAI (ne z pozadavku okna), overeni prihlaseni
# tokenem, ulozeni uctu bez hesla a pripojeni
function add_luxai_account(req):
    address = String(req.get("address", "")).strip().lower()
    r = luxai.mailboxes()
    if not r["ok"]:
        return r
    end
    box = {}
    for m in r["mailboxes"]:
        if m["address"] == address:
            box = m
        end
    end
    if len(box) == 0:
        return {"ok": False, "kind": "luxai_denied", "error": "The LuxAI account has no access to " + address + "."}
    end
    conn = luxai_login({"email": address}, box["imap"])
    call imap.logout(conn)
    id = store.account_id(address)
    out = []
    for a in store.load_accounts():
        if a["id"] != id:
            out.append(a)
        end
    end
    name = String(box.get("display_name", ""))
    cfg = {"id": id, "email": address, "name": name, "auth": "luxai", "imap": box["imap"], "smtp": box["smtp"]}
    out.append(cfg)
    call store.save_accounts(out)
    # stary zaznam v klicence (drive pridano heslem) uz neni potreba
    call secret.clear(id)
    if id in svc["accounts"]:
        call disconnect(svc["accounts"][id])
    else:
        svc["order"].append(id)
    end
    st = new_state(cfg)
    svc["accounts"][id] = st
    call start_account(st)
    return {"ok": True, "account": id, "state": st["state"], "error": st["error"]}
end

# Znovu pripojit ucet i po chybe prihlaseni (po novem prihlaseni k LuxAI)
function retry_account(req):
    st = account_state(req.get("account", ""))
    st["backoff"] = 0
    call start_account(st)
    return {"ok": True, "state": st["state"], "kind": st["kind"]}
end

function set_password(req):
    st = account_state(req.get("account", ""))
    cfg = st["cfg"]
    password = String(req.get("password", ""))
    s = cfg["imap"]
    conn = imap.connect(s["host"], s["port"], s["security"], 15000)
    try:
        call imap.login(conn, s.get("user", cfg["email"]), password)
    else:
        err = last_error()
        call imap.close(conn)
        Error(MailError: String(err).replace("MailError: ", ""))
    end
    call imap.logout(conn)
    stored = secret.store(cfg["id"], cfg["email"], s["host"], password)
    if stored != True:
        call imap.fail("keyring", String(stored))
    end
    st["password"] = password
    call start_account(st)
    return {"ok": True, "state": st["state"]}
end

function remove_account(req):
    id = req.get("account", "")
    if id in svc["accounts"]:
        call disconnect(svc["accounts"][id])
        call svc["accounts"].pop(id)
        call svc["order"].remove(id)
    end
    call secret.clear(id)
    out = []
    for a in store.load_accounts():
        if a["id"] != id:
            out.append(a)
        end
    end
    call store.save_accounts(out)
    call store.remove_tree(store.account_dir(id))
    call update_badge()
    return {"ok": True}
end

function handle(req):
    op = req.get("op", "")
    if op == "hello" or op == "status":
        states = []
        for id in svc["order"]:
            states.append(status_of(svc["accounts"][id]))
        end
        return {"ok": True, "accounts": states, "pid": glib.getpid()}
    elif op == "add_account":
        return add_account(req)
    elif op == "set_password":
        return set_password(req)
    elif op == "luxai_mailboxes":
        return luxai_mailboxes(req)
    elif op == "add_luxai_account":
        return add_luxai_account(req)
    elif op == "retry_account":
        return retry_account(req)
    elif op == "remove_account":
        return remove_account(req)
    elif op == "reconnect":
        call reconnect_all("request")
        return {"ok": True}
    elif op == "quit":
        call glib.main_quit()
        return {"ok": True}
    elif op in ["sync", "older", "body", "flags", "trash", "mailboxes"]:
        return account_op(req)
    end
    return {"ok": False, "kind": "invalid", "error": "Unknown request."}
end

# Bez uctu a bez okna sluzba nema co delat (po 60 s skonci; okno ji spusti znovu)
function schedule_exit_check():
    if svc["exit_timer"] == 0:
        svc["exit_timer"] = glib.timeout_add_seconds(60, exit_check)
    end
    return 0
end

function exit_check():
    svc["exit_timer"] = 0
    if len(svc["order"]) == 0 and len(svc["clients"]) == 0:
        call log("no accounts, exiting")
        call glib.main_quit()
    end
    return False
end

function start_accounts():
    delay = 0
    for id in svc["order"]:
        call glib.timeout_add_data(200 + delay, on_start_timer, svc["accounts"][id])
        delay += 700
    end
    return False
end

function on_start_timer(st):
    call start_account(st)
    return False
end

function on_term():
    call glib.main_quit()
    return False
end

function main():
    fd = luxos_sys.unix_listen(socket_name())
    if fd < 0:
        # uz bezi (nebo socket nejde vytvorit)
        return 0
    end
    svc["listen"] = fd
    call glib.set_prgname("luxos-mail")
    call glib.fd_add_data(fd, 1, on_accept, 0)
    call glib.unix_signal_add(15, on_term)
    call glib.unix_signal_add(2, on_term)
    safe:
        svc["session"] = gio.session_bus()
    end
    if svc["session"] != 0:
        safe:
            call gio.subscribe_values(svc["session"], "org.freedesktop.Notifications", "org.freedesktop.Notifications", "ActionInvoked", "/org/freedesktop/Notifications", on_action)
            call gio.subscribe_values(svc["session"], "org.freedesktop.Notifications", "org.freedesktop.Notifications", "NotificationClosed", "/org/freedesktop/Notifications", on_closed)
        end
    end
    if env.get("LUXOS_MAIL_NO_SYSTEM_BUS", "") == "":
        safe:
            svc["system"] = gio.system_bus()
        end
    end
    if svc["system"] != 0:
        safe:
            call gio.subscribe_values(svc["system"], NM, NM, "StateChanged", "/org/freedesktop/NetworkManager", on_nm_state)
            call gio.subscribe_values(svc["system"], "org.freedesktop.login1", "org.freedesktop.login1.Manager", "PrepareForSleep", "/org/freedesktop/login1", on_sleep)
        end
    end
    for cfg in store.load_accounts():
        st = new_state(cfg)
        svc["accounts"][cfg["id"]] = st
        svc["order"].append(cfg["id"])
        st["boxes"] = store.load_mailboxes(cfg["id"])
    end
    call update_badge()
    call start_accounts()
    call schedule_exit_check()
    call glib.main()
    for id in svc["order"]:
        st = svc["accounts"][id]
        if connected(st):
            safe:
                call leave_idle(st)
                call imap.logout(st["conn"])
            end
        end
    end
    call luxos_sys.close(svc["listen"])
    return 0
end
