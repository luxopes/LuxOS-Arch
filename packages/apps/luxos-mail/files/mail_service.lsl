# Posta LuxOS - sluzba na pozadi (`luxos-mail --background`, spousti ji relace pres XDG autostart).
# Drzi jedno spojeni IMAP na ucet: po synchronizaci ceka v IDLE na INBOX (server sam oznami novou zpravu),
# bez IDLE kontroluje kazdych 5 minut. Nova neprectena zprava -> trvale upozorneni "Nova posta od X"
# s akci Otevrit (otevre aplikaci na te zprave), ulozene i v historii oznameni (zvonek v liste); dalsi
# zpravy ho nahradi souhrnem, po precteni se zavre. Rezim Nerusit respektuje xfce4-notifyd. Po zmene site
# (NetworkManager) a probuzeni (logind) se spoji znovu, pri vypadku ceka 5 s, 10 s ... nejvys 15 min.
# Spatne heslo se znovu nezkousi (zadne zablokovani uctu na serveru), az po zadani noveho.
# Schranky LuxAI (ucet "auth": "luxai") heslo nemaji: pred kazdym spojenim si sluzba vyzada od serveru
# LuxAI kratkodoby token (ucet LuxAI tohoto pocitace, mail_luxai) a prihlasi se SASL OAUTHBEARER/XOAUTH2.
# Ucty "Prihlasit se Googlem/Microsoftem" ("auth": "oauth", mail_oauth): obnovovaci token v klicence, pristupovy
# token jen v pameti, obnovi se pred kazdym spojenim, kdyz do vyprseni zbyva mene nez 5 minut. Neplatny
# obnovovaci token (invalid_grant) -> stav "oauth_expired", okno nabidne "Prihlasit se znovu" (zadne opakovani).
# Prihlaseni v prohlizeci: oauth_start otevre naslouchani na loopbacku a vrati adresu pro prohlizec, po
# presmerovani s kodem sluzba vymeni kod za tokeny, overi IMAP, ulozi ucet a vsem oknum posle udalost
# {"event": "oauth_done", ...}.
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
load mail_provider as provider
load mail_oauth as oauth
load mail_oauth_login as ol
load mail_smtp as smtp
load crypto

ITEMS = "UID FLAGS INTERNALDATE RFC822.SIZE ENVELOPE BODYSTRUCTURE"
INITIAL = 500
OLDER = 500
IDLE_REFRESH = 1500
POLL_SECONDS = 300
BACKOFF_MAX = 900
MAX_BODY = 67108864
NM = "org.freedesktop.NetworkManager"

svc = {"listen": -1, "clients": [], "session": 0, "system": 0, "notes": {}, "badge": -1, "accounts": {}, "order": [],
       "nm_state": 0, "exit_timer": 0, "next_note": 0, "flow": {}, "outbox_timer": 0, "outbox_when": 0}

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
            "retry": 0, "idle_timer": 0, "poll_timer": 0, "debounce": 0, "boxes": [], "started": False,
            "note": {"id": 0, "pending": []}, "access": "", "access_exp": 0}
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
    return kind in ["auth", "oauthonly", "nopassword", "luxai_session", "luxai_signedout", "luxai_denied", "nooauth",
                    "oauth_expired", "oauth_config", "notconnected"]
end

function is_oauth(cfg):
    return cfg.get("auth", "") == "oauth"
end

# ---- ucty s prihlasenim u poskytovatele (OAuth2) ---------------------------------------------------------------

# Poskytovatel uctu s client ID, kterym byl token vydan (obnovovaci token patri tomuto klientovi)
function account_provider(cfg):
    o = cfg.get("oauth", {})
    if type(o) != "Dictionary":
        o = {}
    end
    p = oauth.provider(String(o.get("provider", "")))
    if len(p) == 0 or String(o.get("client_id", "")) == "":
        call imap.fail("oauth_config", "The sign-in provider of this account is not configured.")
    end
    if p["client_id"] != o["client_id"]:
        p["client_id"] = o["client_id"]
        p["client_secret"] = String(o.get("client_secret", ""))
    end
    return p
end

# Platny pristupovy token: [token, novy?]. Obnovi ho, kdyz chybi, brzy vyprsi nebo force.
function oauth_access(st, force):
    if not force and st["access"] != "" and st["access_exp"] - now() > 300:
        return [st["access"], False]
    end
    cfg = st["cfg"]
    p = account_provider(cfg)
    rt = secret.lookup(cfg["id"])
    if rt == "":
        call imap.fail("oauth_expired", "The sign-in is not in the keyring.")
    end
    r = oauth.refresh(p, rt)
    if not r["ok"]:
        st["access"] = ""
        call imap.fail(r["kind"], r["error"])
    end
    # rotace obnovovaciho tokenu (Microsoft): novy nahradi stary
    if r["refresh_token"] != "" and r["refresh_token"] != rt:
        stored = secret.store(cfg["id"], cfg["email"], cfg["imap"]["host"], r["refresh_token"], oauth_label(p, cfg["email"]))
        if stored != True:
            call log("account " + cfg["id"] + ": the new sign-in could not be saved in the keyring")
        end
    end
    st["access"] = r["access_token"]
    st["access_exp"] = now() + r["expires_in"]
    return [st["access"], True]
end

function oauth_label(p, email):
    return "LuxOS Mail (" + p["name"] + "): " + email
end

# Prihlaseni uctu OAuth; server odmitl ulozeny (ne cerstvy) token -> jednou novy token a znovu.
# "User is authenticated but not connected" (Microsoft) -> zachrana (ol.recover: jina adresa, token jen pro
# Outlook, /consumers, jiny server); co pomohlo, se ulozi do uctu a zapise do logu (bez tokenu).
function oauth_login(st, s):
    cfg = st["cfg"]
    p = account_provider(cfg)
    user = String(s.get("user", cfg["email"]))
    tok = oauth_access(st, False)
    conn = {}
    retry = False
    err = ""
    try:
        conn = ol.token_connect(s, user, tok[0], p["sasl"], True)
    else:
        err = String(last_error())
        retry = imap.error_kind(err)[0] == "auth" and not tok[1]
    end
    if err == "":
        return conn
    end
    if retry:
        st["access"] = ""
        tok = oauth_access(st, True)
        err = ""
        try:
            conn = ol.token_connect(s, user, tok[0], p["sasl"], True)
        else:
            err = String(last_error())
        end
        if err == "":
            return conn
        end
    end
    if imap.error_kind(err)[0] != "notconnected":
        Error(MailError: err.replace("MailError: ", ""))
    end
    rt = secret.lookup(cfg["id"])
    rec = {"token": st["access"], "expires_in": st["access_exp"] - now(), "refresh_token": rt, "rt_changed": False}
    report = []
    found = ol.recover(p, s, oauth.address_candidates(user, cfg["email"], {}), rec, report)
    call oauth_keep_tokens(st, p, rec)
    if not found["ok"]:
        call log("account " + cfg["id"] + ": mailbox not connected, nothing helped: " + ol.report_text(report))
        Error(MailError: err.replace("MailError: ", ""))
    end
    call log("account " + cfg["id"] + ": mailbox connected with variant '" + found["variant"] + "' on " + found["server"]["host"])
    imap_cfg = {"host": found["server"]["host"], "port": found["server"]["port"], "security": found["server"]["security"], "user": found["user"]}
    if imap_cfg["host"] != s["host"] or imap_cfg["port"] != s["port"] or imap_cfg["security"] != s["security"] or imap_cfg["user"] != user:
        call save_imap(cfg, imap_cfg)
    end
    return found["conn"]
end

# Novy pristupovy/obnovovaci token ze zachrany do pameti a klicenky
function oauth_keep_tokens(st, p, rec):
    cfg = st["cfg"]
    if rec["token"] != "" and rec["token"] != st["access"]:
        st["access"] = rec["token"]
        st["access_exp"] = now() + rec["expires_in"]
    end
    if rec["rt_changed"]:
        stored = secret.store(cfg["id"], cfg["email"], cfg["imap"]["host"], rec["refresh_token"], oauth_label(p, cfg["email"]))
        if stored != True:
            call log("account " + cfg["id"] + ": the new sign-in could not be saved in the keyring")
        end
    end
    return 0
end

# Server/adresa IMAP, ktere fungovaly, do uctu (accounts.json a pamet)
function save_imap(cfg, imap_cfg):
    cfg["imap"] = imap_cfg
    out = []
    for a in store.load_accounts():
        if a["id"] == cfg["id"]:
            a["imap"] = imap_cfg
        end
        out.append(a)
    end
    call store.save_accounts(out)
    return 0
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
    if is_luxai(cfg) or is_oauth(cfg):
        call set_state(st, "connecting", "", "")
        conn = {}
        if is_oauth(cfg):
            conn = oauth_login(st, s)
        else:
            conn = luxai_login(cfg, s)
        end
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
    if raw == "INBOX":
        call check_read(st)
    end
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

# Jedno trvale upozorneni na ucet: zustane, dokud ho uzivatel nezavre (expire_timeout 0), s hintem
# x-luxos-keep se ulozi do historie oznameni (zvonek v liste, cervena tecka = neprectene). Dalsi nove
# zpravy ho nahradi (stejne id -> souhrn "Nove zpravy: N", xfce4-notifyd prepise i zaznam v historii).
# Kdyz jsou vsechny ohlasene zpravy prectene (v Poste nebo jinde - IMAP \Seen), upozorneni se zavre
# (CloseNotification, zaznam v historii se oznaci jako precteny).
NOTE_LINES = 3

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
    note = st["note"]
    known = {}
    for p in note["pending"]:
        known[p["uid"]] = True
    end
    for r in fresh:
        if r["uid"] not in known:
            note["pending"].append({"uid": r["uid"], "from_name": r["from_name"], "from_email": r["from_email"],
                                    "subject": r["subject"], "preview": r["preview"]})
        end
    end
    call show_note(st, raw)
    return 0
end

function note_sender(p):
    if p["from_name"] != "":
        return p["from_name"]
    end
    return p["from_email"]
end

function note_subject(p):
    if p["subject"] == "":
        return i18n.T("(no subject)")
    end
    return p["subject"]
end

function show_note(st, raw):
    note = st["note"]
    pending = note["pending"]
    # nejnovejsi nahore
    newest = []
    for p in pending:
        i = 0
        while i < len(newest) and newest[i]["uid"] > p["uid"]:
            i += 1
        end
        newest.insert(i, p)
    end
    if len(newest) == 1:
        p = newest[0]
        summary = i18n.TF("New mail from %s", [note_sender(p)])
        body = glib.markup_escape(note_subject(p))
        if p["preview"] != "":
            body = body + "\n" + glib.markup_escape(p["preview"][0:min(len(p["preview"]), 120)])
        end
    else:
        summary = i18n.TF("New messages: %d", [len(newest)])
        lines = []
        for p in newest[0:min(len(newest), NOTE_LINES)]:
            lines.append(glib.markup_escape(note_sender(p) + ": " + note_subject(p)))
        end
        if len(newest) > NOTE_LINES:
            lines.append("…")
        end
        body = "\n".join(lines)
    end
    call send_note(note["id"], summary, body, {"account": st["cfg"]["id"], "mailbox": raw, "uid": newest[0]["uid"]})
    return 0
end

function send_note(replaces, summary, body, target):
    actions = ["default", i18n.T("Open")]
    hints = {"category": ["s", "email.arrived"], "desktop-entry": ["s", "luxos-mail"], "x-luxos-keep": ["b", True]}
    call gio.call_async(svc["session"], "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify",
                        [i18n.T("Mail"), replaces, "luxos-mail", summary, body, actions, hints, 0],
                        "(susssasa{sv}i)", 5000, on_notified, target)
    return 0
end

function on_notified(target, values, error):
    if values == None:
        call log("notification failed: " + error)
        return 0
    end
    svc["notes"][values[0]] = target
    if target["account"] in svc["accounts"]:
        svc["accounts"][target["account"]]["note"]["id"] = values[0]
    end
    if env.get("LUXOS_MAIL_NOTIFY_LOG", "") != "":
        safe:
            call appendfile(env.get("LUXOS_MAIL_NOTIFY_LOG", ""), json.encode({"id": values[0], "target": target}) + "\n")
        end
    end
    return 0
end

# Po kazde zmene INBOXu (synchronizace, priznak z okna, IDLE): prectene/smazane zpravy z upozorneni
# vypadnou; kdyz nezbyde zadna, upozorneni se zavre. Castecne precteny souhrn se nemeni (nahrazeni
# by v historii vytvorilo novy neprecteny zaznam a zvonek by se znovu rozsvitil).
function check_read(st):
    note = st["note"]
    if len(note["pending"]) == 0:
        return 0
    end
    flags = {}
    for r in store.load_index(st["cfg"]["id"], "INBOX"):
        flags[r["uid"]] = r["flags"]
    end
    keep = []
    for p in note["pending"]:
        f = flags.get(p["uid"], None)
        if f != None and f.find("S") < 0 and f.find("D") < 0:
            keep.append(p)
        end
    end
    note["pending"] = keep
    if len(keep) == 0:
        call close_note(st)
    end
    return 0
end

function close_note(st):
    note = st["note"]
    nid = note["id"]
    st["note"] = {"id": 0, "pending": []}
    if nid == 0 or svc["session"] == 0:
        return 0
    end
    if nid in svc["notes"]:
        call svc["notes"].pop(nid)
    end
    safe:
        call gio.call_async(svc["session"], "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "CloseNotification",
                            [nid], "(u)", 5000, on_note_closed, nid)
    end
    return 0
end

function on_note_closed(nid, values, error):
    if values == None:
        call log("closing notification failed: " + error)
    end
    return 0
end

function on_action(sender, path, interface, signal, values):
    if len(values) < 2 or values[0] not in svc["notes"]:
        return 0
    end
    target = svc["notes"][values[0]]
    if "outbox" in target:
        call glib.spawn([store.gui_binary(), "--outbox"])
        return 0
    end
    call glib.spawn([store.gui_binary(), "--open", target["account"], target["mailbox"], String(target["uid"])])
    return 0
end

# Zavrene uzivatelem (krizek, akce: duvod 2) nebo aplikaci (3) -> dalsi posta zacne nove upozorneni.
# Duvod 4 posila xfce4-notifyd hned, kdyz popup vubec neukaze (Nerusit) - upozorneni ale zustava
# v historii, takze ho dal nahrazujeme a po precteni zavreme.
function on_closed(sender, path, interface, signal, values):
    if len(values) < 1:
        return 0
    end
    reason = 0
    if len(values) >= 2:
        reason = values[1]
    end
    if reason != 2 and reason != 3:
        return 0
    end
    if values[0] in svc["notes"]:
        call svc["notes"].pop(values[0])
    end
    for id in svc["order"]:
        st = svc["accounts"][id]
        if st["note"]["id"] == values[0]:
            st["note"] = {"id": 0, "pending": []}
        end
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

# Pocty neprectenych v ostatnich schrankach (STATUS), jen pro schranky bez mistni mezipameti.
# Gmail "Vsechny zpravy", "Dulezite", "S hvezdickou" ne (jen jine pohledy na tytez zpravy; STATUS velke
# schranky "All Mail" muze trvat)
function refresh_counts(st):
    conn = st["conn"]
    for b in st["boxes"]:
        if b["raw"] == "INBOX" or not b.get("selectable", True) or b["role"] in ["junk", "trash", "all", "important", "starred"]:
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
    # Odchozi: zpravy cekajici na sit hned
    safe:
        call process_outbox(True)
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
        if kind[0] == "closed" or kind[0] == "timeout" or kind[0] == "connect" or kind[0] == "tls" or kind[0] == "unavailable" or kind[0].startswith("luxai_") or kind[0] == "oauth_server":
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
    # znamy poskytovatel (Google, Microsoft ...): texty chyb a napovedy hesla v okne
    prov = String(req.get("provider", ""))
    if len(provider.info(prov)) == 0:
        prov = provider.detect(provider.domain_of(email), s["host"], [])
    end
    if prov != "":
        cfg["provider"] = prov
    end
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

# ---- prihlaseni u poskytovatele v prohlizeci (RFC 8252) ------------------------------------------------------------
# Jedno prihlaseni najednou; nove prihlaseni nebo zavreni okna prihlaseni (oauth_cancel) predchozi zrusi.
# Po 10 minutach bez presmerovani se naslouchani zavre.

FLOW_SECONDS = 600
FLOW_MAX_CONNS = 16

function unwatch(w):
    if len(w) == 2:
        call glib.source_remove(w[0])
        call glib.release(w[1])
    end
    return 0
end

function close_flow_conn(flow, c):
    call unwatch(c["watch"])
    c["watch"] = []
    if c["fd"] >= 0:
        safe:
            call net.close(c["fd"])
        end
        c["fd"] = -1
    end
    if c in flow["conns"]:
        call flow["conns"].remove(c)
    end
    return 0
end

function close_flow(flow):
    for c in flow["conns"].copy():
        call close_flow_conn(flow, c)
    end
    for w in flow["watches"]:
        call unwatch(w)
    end
    flow["watches"] = []
    for fd in flow["listeners"]:
        safe:
            call net.close(fd)
        end
    end
    flow["listeners"] = []
    if flow["timer"] != 0:
        call glib.source_remove(flow["timer"])
        flow["timer"] = 0
    end
    flow["done"] = True
    if len(svc["flow"]) > 0 and svc["flow"]["id"] == flow["id"]:
        svc["flow"] = {}
    end
    return 0
end

function flow_event(flow, result):
    ev = {"event": "oauth_done", "flow": flow["id"], "provider": flow["provider"]["id"], "ok": result.get("ok", False),
          "account": result.get("account", ""), "email": result.get("email", flow["email"]), "kind": result.get("kind", ""),
          "error": result.get("error", ""), "reauth": flow["account"] != ""}
    call broadcast(ev)
    return 0
end

function on_flow_timeout(flow):
    flow["timer"] = 0
    if flow["done"]:
        return False
    end
    call close_flow(flow)
    call flow_event(flow, {"ok": False, "kind": "oauth_timeout", "error": "The sign-in in the browser did not finish in time."})
    return False
end

function oauth_start(req):
    id = String(req.get("provider", ""))
    p = oauth.available(id)
    if len(p) == 0:
        return {"ok": False, "kind": "oauth_config", "error": "Signing in with this provider is not configured."}
    end
    account = String(req.get("account", ""))
    email = String(req.get("email", "")).strip()
    if account != "":
        st = account_state(account)
        email = st["cfg"]["email"]
    end
    if len(svc["flow"]) > 0:
        call close_flow(svc["flow"])
    end
    listeners = []
    port = 0
    ok = True
    try:
        fd = net.tcp_listen("127.0.0.1", p["redirect_port"], 16)
        listeners.append(fd)
        port = net.local_address(fd)[1]
    else:
        ok = False
    end
    if not ok:
        return {"ok": False, "kind": "oauth_listen", "error": String(last_error())}
    end
    # "localhost" muze prohlizec prelozit i na ::1: naslouchat i tam (kdyz IPv6 je)
    if p["redirect_host"] == "localhost":
        safe:
            listeners.append(net.tcp_listen("::1", port, 16))
        end
    end
    flow = {"id": oauth.random_token(9), "provider": p, "port": port, "state": oauth.random_token(24),
            "verifier": oauth.random_token(48), "email": email, "name": String(req.get("name", "")).strip(),
            "account": account, "listeners": listeners, "watches": [], "conns": [], "timer": 0, "done": False}
    for fd in listeners:
        call net.set_nonblocking(fd, True)
        flow["watches"].append(glib.fd_add_data(fd, 1, on_flow_accept, flow))
    end
    flow["timer"] = glib.timeout_add_seconds_data(FLOW_SECONDS, on_flow_timeout, flow)
    svc["flow"] = flow
    url = oauth.authorize_url(p, port, flow["state"], flow["verifier"], email)
    return {"ok": True, "flow": flow["id"], "url": url, "port": port}
end

function oauth_cancel(req):
    flow = svc["flow"]
    if len(flow) > 0 and (req.get("flow", "") == "" or req.get("flow", "") == flow["id"]):
        call close_flow(flow)
    end
    return {"ok": True}
end

function on_flow_accept(flow, fd, condition):
    if flow["done"]:
        return True
    end
    loop:
        r = []
        safe:
            r = net.accept(fd, 0)
        end
        if len(r) == 0:
            break
        end
        # jen loopback (naslouchame jen na 127.0.0.1/::1, pro jistotu)
        if r[1] != "127.0.0.1" and r[1] != "::1":
            safe:
                call net.close(r[0])
            end
            continue
        end
        if len(flow["conns"]) >= FLOW_MAX_CONNS:
            call close_flow_conn(flow, flow["conns"][0])
        end
        call net.set_nonblocking(r[0], True)
        c = {"fd": r[0], "buf": ByteArray(), "watch": []}
        flow["conns"].append(c)
        c["watch"] = glib.fd_add_data(r[0], 1 + 8 + 16, on_flow_data, [flow, c])
    end
    return True
end

function flow_reply(flow, c, status, reason, title, text, ok):
    body = oauth.page(i18n.lang(), title, text, i18n.T("Return to Mail"), ok)
    if c["fd"] >= 0:
        call mb.send(c["fd"], oauth.http_response(status, reason, body))
    end
    call close_flow_conn(flow, c)
    return 0
end

function on_flow_data(pair, fd, condition):
    flow = pair[0]
    c = pair[1]
    if c["fd"] < 0 or flow["done"]:
        return True
    end
    data = mb.recv(c["fd"], 16384)
    if data == False:
        return True
    end
    if len(data) == 0:
        call close_flow_conn(flow, c)
        return True
    end
    c["buf"] = mb.concat(c["buf"], data)
    if len(c["buf"]) > 32768:
        call flow_reply(flow, c, 400, "Bad Request", i18n.T("Signing in did not finish"), i18n.T("The browser sent an invalid request."), False)
        return True
    end
    text = net.text(c["buf"])
    if text.find("\r\n\r\n") < 0 and text.find("\n\n") < 0:
        return True
    end
    r = oauth.parse_request_line(text)
    if len(r) == 0 or r["method"] != "GET":
        call flow_reply(flow, c, 400, "Bad Request", i18n.T("Signing in did not finish"), i18n.T("The browser sent an invalid request."), False)
        return True
    end
    if r["path"] != "/":
        # napr. /favicon.ico: nic, cekat dal na presmerovani
        if c["fd"] >= 0:
            call mb.send(c["fd"], "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        end
        call close_flow_conn(flow, c)
        return True
    end
    q = r["query"]
    got = String(q.get("state", ""))
    if got == "" or len(got) != len(flow["state"]) or not crypto.constant_time_equal(got, flow["state"]):
        # cizi nebo stara adresa: neukoncit probihajici prihlaseni
        call flow_reply(flow, c, 400, "Bad Request", i18n.T("Signing in did not finish"), i18n.T("This sign-in page is out of date. Return to Mail and start signing in again."), False)
        return True
    end
    result = {}
    if "error" in q:
        kind = "oauth_failed"
        if q["error"] == "access_denied":
            kind = "oauth_denied"
        end
        detail = String(q["error"]) + ": " + String(q.get("error_description", ""))
        result = {"ok": False, "kind": kind, "error": oauth_clean(detail)}
    elif String(q.get("code", "")) == "" or len(q["code"]) > 4096:
        result = {"ok": False, "kind": "oauth_failed", "error": "The provider sent no authorization code."}
    else:
        try:
            result = complete_flow(flow, q["code"])
        else:
            kind = imap.error_kind(last_error())
            result = {"ok": False, "kind": kind[0], "error": kind[1]}
        end
    end
    name = flow["provider"]["name"]
    if result.get("ok", False):
        call log("sign-in with " + name + ": account " + result["account"] + " added")
    else:
        call log("sign-in with " + name + " failed: " + String(result.get("kind", "")) + ": " + String(result.get("error", "")))
    end
    # naslouchani a ostatni spojeni zavrit; toto spojeni jeste dostane stranku
    call flow["conns"].remove(c)
    call close_flow(flow)
    flow["conns"].append(c)
    if result.get("ok", False):
        call flow_reply(flow, c, 200, "OK", i18n.T("You are signed in"), i18n.TF("Mail is now connected to your %s account %s. You can close this page and return to Mail.", [name, result.get("email", "")]), True)
    elif result.get("kind", "") == "oauth_denied":
        call flow_reply(flow, c, 200, "OK", i18n.T("Signing in was cancelled"), i18n.TF("Mail did not get access to your %s account. You can close this page and return to Mail.", [name]), False)
    else:
        call flow_reply(flow, c, 200, "OK", i18n.T("Signing in did not finish"), i18n.T("Return to Mail to see what went wrong and try again."), False)
    end
    call flow_event(flow, result)
    if result.get("ok", False):
        st = svc["accounts"].get(result["account"], None)
        if st != None:
            # stazeni posty az po odpovedi prohlizeci
            call glib.timeout_add_data(50, on_start_timer, st)
        end
    end
    return True
end

function oauth_clean(text):
    out = []
    for ch in String(text)[0:300]:
        if ord(ch) >= 32 and ord(ch) != 127:
            out.append(ch)
        end
    end
    return "".join(out)
end

# Kod z prohlizece -> tokeny -> overeni IMAP -> obnovovaci token do klicenky -> ucet ulozen (bez spojeni,
# to zacne az po odpovedi prohlizeci). {"ok", "account", "email"} nebo chyba
function complete_flow(flow, code):
    p = flow["provider"]
    r = oauth.exchange_code(p, code, flow["verifier"], flow["port"])
    if not r["ok"]:
        return r
    end
    if r["refresh_token"] == "":
        return {"ok": False, "kind": "oauth_server", "error": "The provider sent no refresh token."}
    end
    identity = oauth.id_token_identity(r["id_token"])
    address = oauth.mailbox_address(flow["email"], identity)
    if address == "" or address.find("@") <= 0:
        return {"ok": False, "kind": "oauth_failed", "error": "The provider did not tell which mailbox the sign-in is for."}
    end
    old = {}
    if flow["account"] != "":
        old = account_state(flow["account"])["cfg"]
        if old["email"].lower() != address.lower():
            return {"ok": False, "kind": "oauth_other_account", "error": address, "email": address}
        end
        address = old["email"]
    end
    s = {"host": p["imap"]["host"], "port": p["imap"]["port"], "security": p["imap"]["security"], "user": address}
    if len(old) > 0:
        s = old["imap"]
    end
    user = String(s.get("user", address))
    err = ""
    conn = {}
    try:
        conn = ol.token_connect(s, user, r["access_token"], p["sasl"], True)
    else:
        err = String(last_error())
    end
    if err != "":
        if imap.error_kind(err)[0] != "notconnected":
            Error(MailError: err.replace("MailError: ", ""))
        end
        # Microsoft prijal token, ale schranku neotevrel: zkusit jine adresy, token jen pro Outlook, jiny server
        rec = {"token": r["access_token"], "expires_in": r["expires_in"], "refresh_token": r["refresh_token"], "rt_changed": False}
        report = []
        users = oauth.address_candidates(user, flow["email"], identity)
        found = ol.recover(p, s, users, rec, report)
        r["access_token"] = rec["token"]
        r["expires_in"] = rec["expires_in"]
        r["refresh_token"] = rec["refresh_token"]
        if not found["ok"]:
            call log("sign-in with " + p["name"] + ": mailbox not connected, nothing helped: " + ol.report_text(report))
            Error(MailError: err.replace("MailError: ", ""))
        end
        call log("sign-in with " + p["name"] + ": mailbox connected with variant '" + found["variant"] + "' on " + found["server"]["host"])
        conn = found["conn"]
        s = {"host": found["server"]["host"], "port": found["server"]["port"], "security": found["server"]["security"], "user": found["user"]}
        # nova adresa schranky (hlavni adresa misto aliasu); u Prihlasit se znovu zustava e-mail uctu
        if len(old) == 0:
            address = found["user"]
        end
    end
    call imap.logout(conn)
    id = store.account_id(address)
    stored = secret.store(id, address, s["host"], r["refresh_token"], oauth_label(p, address))
    if stored != True:
        call imap.fail("keyring", String(stored))
    end
    out = []
    for a in store.load_accounts():
        if a["id"] != id:
            out.append(a)
        end
    end
    smtp = {}
    if len(p["smtp"]) > 0:
        smtp = {"host": p["smtp"]["host"], "port": p["smtp"]["port"], "security": p["smtp"]["security"], "user": address, "auth": "xoauth2"}
    end
    name = flow["name"]
    if len(old) > 0:
        name = String(old.get("name", ""))
        if len(old.get("smtp", {})) > 0:
            smtp = old["smtp"]
        end
    end
    cfg = {"id": id, "email": address, "name": name, "auth": "oauth", "provider": p["id"], "imap": s, "smtp": smtp,
           "oauth": {"provider": p["id"], "client_id": p["client_id"], "client_secret": p["client_secret"]}}
    if len(provider.info(p["id"])) == 0:
        call cfg.pop("provider")
    end
    out.append(cfg)
    call store.save_accounts(out)
    st = {}
    if id in svc["accounts"]:
        st = svc["accounts"][id]
        call disconnect(st)
        st["cfg"] = cfg
        st["backoff"] = 0
        st["password"] = ""
    else:
        svc["order"].append(id)
        st = new_state(cfg)
        svc["accounts"][id] = st
    end
    st["access"] = r["access_token"]
    st["access_exp"] = now() + r["expires_in"]
    call set_state(st, "connecting", "", "")
    return {"ok": True, "account": id, "email": address}
end

# Poskytovatele s prihlasenim v prohlizeci (okno: tlacitko "Prihlasit se ..."); bez client ID nejsou v seznamu
function oauth_providers(req):
    out = []
    for p in oauth.providers().values():
        if len(oauth.available(p["id"])) > 0:
            out.append(p["id"])
        end
    end
    return {"ok": True, "providers": out}
end

function remove_account(req):
    id = req.get("account", "")
    revoked = False
    # ucet OAuth: nejdriv odvolat pristup Posty u poskytovatele (kdyz to umi), pak smazat vse mistni.
    # Odvolani je jen navic - bez site nebo pri chybe se ucet z pocitace smaze stejne.
    for a in store.load_accounts():
        if a["id"] == id and a.get("auth", "") == "oauth":
            p = {}
            safe:
                p = account_provider(a)
            end
            if len(p) > 0 and p.get("revoke_url", "") != "":
                revoked = oauth.revoke(p, secret.lookup(id))
                if revoked:
                    call log("account " + id + ": access revoked at " + p["name"])
                else:
                    call log("account " + id + ": access could not be revoked at " + p["name"])
                end
            end
        end
    end
    if id in svc["accounts"]:
        call disconnect(svc["accounts"][id])
        call close_note(svc["accounts"][id])
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
    return {"ok": True, "revoked": revoked}
end

# ---- odesilani (SMTP), Odchozi a koncepty ----------------------------------------------------------------------
# Okno slozi zpravu (mail_mime.compose) a ulozi ji do ~/.local/share/luxos-mail/outbox/<id>.eml s popisem
# <id>.json (ucet, obalka, odpoved na zpravu, koncept na serveru, stav psani pro "Upravit"); pak posle "send".
# Sluzba zpravu odesle pres SMTP uctu, ulozi kopii do Odeslanych (ne Gmail a Microsoft: ty si ji ulozi samy,
# kopie by byla dvakrat), oznaci puvodni zpravu \Answered ($Forwarded) a smaze koncept na serveru. Bez site nebo
# pri docasne chybe serveru zprava zustane v Odchozi a zkousi se znovu (30 s, 1 min, 2 min ... nejvys 15 min, hned
# po pripojeni site / probuzeni); po 48 hodinach bez uspechu nebo pri trvale chybe (spatne heslo, odmitnuty
# prijemce, prilis velka zprava) upozorneni "Zpravu se nepodarilo odeslat" a zprava zustane v Odchozi s chybou.
# Napsana zprava se tak nikdy neztrati (okno navic prubezne uklada rozepsanou zpravu, viz mail_ui).

OUTBOX_GIVE_UP = 172800
OUTBOX_MAX_DELAY = 900

function outbox_dir():
    return store.ensure_dir(store.base_data() + "/outbox")
end

function job_path(id, ext):
    return outbox_dir() + "/" + id + ext
end

function valid_job_id(id):
    if type(id) != "String" or id == "" or len(id) > 64:
        return False
    end
    for ch in id:
        if "abcdefghijklmnopqrstuvwxyz0123456789-".find(ch) < 0:
            return False
        end
    end
    return True
end

function load_job(id):
    if not valid_job_id(id):
        return {}
    end
    path = job_path(id, ".json")
    if not exists(path) or not exists(job_path(id, ".eml")):
        return {}
    end
    job = None
    safe:
        job = json.decode(readfile(path))
    end
    if type(job) != "Dictionary":
        return {}
    end
    job["id"] = id
    for key in ["attempts", "next", "created"]:
        if type(job.get(key)) != "Int":
            job[key] = 0
        end
    end
    return job
end

function save_job(job):
    call store.write_private(job_path(job["id"], ".json"), json.encode(job) + "\n")
    return 0
end

function remove_job(id):
    for ext in [".json", ".eml"]:
        safe:
            call remove_path(job_path(id, ext))
        end
    end
    return 0
end

function list_jobs():
    out = []
    for name in glib.list_dir(outbox_dir()):
        if name.endswith(".json"):
            job = load_job(name[0:len(name) - 5])
            if len(job) > 0:
                out.append(job)
            end
        end
    end
    return out
end

function outbox_event():
    call broadcast({"event": "outbox"})
    return 0
end

# Nastaveni SMTP uctu; chybi-li (stary ucet), od poskytovatele nebo odhad podle IMAP (smtp.<domena>:587)
function smtp_settings(cfg):
    s = cfg.get("smtp", {})
    if type(s) != "Dictionary":
        s = {}
    end
    if String(s.get("host", "")) == "" and is_oauth(cfg):
        p = {}
        safe:
            p = account_provider(cfg)
        end
        if len(p) > 0 and len(p.get("smtp", {})) > 0:
            s = {"host": p["smtp"]["host"], "port": p["smtp"]["port"], "security": p["smtp"]["security"]}
        end
    end
    if String(s.get("host", "")) == "":
        ihost = String(cfg["imap"].get("host", ""))
        host = ihost
        if ihost.startswith("imap."):
            host = "smtp." + ihost[5:]
        end
        s = {"host": host, "port": 587, "security": "starttls"}
    end
    port = s.get("port", 587)
    if type(port) != "Int":
        port = mime.to_int(String(port), 587)
    end
    security = String(s.get("security", "starttls"))
    if security != "ssl":
        security = "starttls"
    end
    user = String(s.get("user", ""))
    if user == "":
        user = String(cfg["imap"].get("user", cfg["email"]))
    end
    if user == "":
        user = cfg["email"]
    end
    return {"host": String(s["host"]).strip(), "port": port, "security": security, "user": user}
end

# Spojeni SMTP a prihlaseni podle druhu uctu (heslo, token poskytovatele, token LuxAI)
function smtp_open(st, s):
    cfg = st["cfg"]
    if is_oauth(cfg):
        p = account_provider(cfg)
        tok = oauth_access(st, False)
        conn = smtp.connect(s["host"], s["port"], s["security"])
        err = ""
        try:
            call smtp.login_oauth(conn, s["user"], tok[0], s["port"], p["sasl"])
        else:
            err = String(last_error())
            call imap.close(conn)
        end
        if err == "":
            return conn
        end
        # ulozeny (ne cerstvy) token server odmitl: jednou novy token a znovu
        if imap.error_kind(err)[0] != "auth" or tok[1]:
            Error(MailError: err.replace("MailError: ", ""))
        end
        st["access"] = ""
        tok = oauth_access(st, True)
        conn = smtp.connect(s["host"], s["port"], s["security"])
        try:
            call smtp.login_oauth(conn, s["user"], tok[0], s["port"], p["sasl"])
        else:
            err = String(last_error())
            call imap.close(conn)
            Error(MailError: err.replace("MailError: ", ""))
        end
        return conn
    end
    if is_luxai(cfg):
        t = luxai.token(String(s.get("user", cfg["email"])))
        if not t["ok"]:
            call imap.fail(t["kind"], t["error"])
        end
        conn = smtp.connect(s["host"], s["port"], s["security"])
        try:
            call smtp.login_oauth(conn, s["user"], t["token"], s["port"])
        else:
            err = String(last_error())
            call imap.close(conn)
            Error(MailError: err.replace("MailError: ", ""))
        end
        return conn
    end
    if st["password"] == "":
        st["password"] = secret.lookup(cfg["id"])
    end
    if st["password"] == "":
        call imap.fail("nopassword", "The password is not in the keyring.")
    end
    conn = smtp.connect(s["host"], s["port"], s["security"])
    try:
        call smtp.login(conn, s["user"], st["password"])
    else:
        err = String(last_error())
        call imap.close(conn)
        Error(MailError: err.replace("MailError: ", ""))
    end
    return conn
end

# Gmail a Microsoft ukladaji zpravy odeslane pres SMTP do Odeslanych samy; kopie pres APPEND by byla dvakrat
function server_saves_sent(st):
    cfg = st["cfg"]
    prov = provider.of_account(cfg)
    if prov == "google" or prov == "microsoft":
        return True
    end
    o = cfg.get("oauth", {})
    if type(o) == "Dictionary" and String(o.get("provider", "")) in ["google", "microsoft"]:
        return True
    end
    host = smtp_settings(cfg)["host"].lower()
    for suffix in ["gmail.com", "googlemail.com", "office365.com", "outlook.com", "hotmail.com", "live.com"]:
        if host == suffix or host.endswith("." + suffix):
            return True
        end
    end
    ihost = String(cfg["imap"].get("host", "")).lower()
    if ihost.endswith("gmail.com") or ihost.endswith("office365.com") or ihost.endswith("outlook.com"):
        return True
    end
    if connected(st) and imap.has_cap(st["conn"], "X-GM-EXT-1"):
        return True
    end
    return False
end

# Schranka podle role; kdyz neni, vytvori se (jmeno pro server) a seznam schranek se obnovi
function ensure_role_box(st, role, name):
    raw = role_box(st, role)
    if raw != "":
        return raw
    end
    call imap.create(st["conn"], name)
    call refresh_mailboxes(st)
    raw = role_box(st, role)
    if raw == "":
        raw = name
    end
    return raw
end

# Zpravy s danym Message-ID ve schrance (koncepty) -> UID
function find_message_id(st, raw, mid):
    conn = st["conn"]
    if conn["selected"] != raw:
        call imap.select(conn, raw)
    end
    if mid == "" or not imap.ascii_safe(mid):
        return []
    end
    return imap.uid_search(conn, "HEADER Message-ID " + imap.quote(mid))
end

function delete_uids(st, raw, uids):
    if len(uids) == 0:
        return 0
    end
    conn = st["conn"]
    if conn["selected"] != raw:
        call imap.select(conn, raw)
    end
    set_text = imap.compress_set(uids)
    call imap.store_flags(conn, set_text, True, ["\\Deleted"])
    call imap.expunge(conn, set_text)
    return 0
end

# Po synchronizaci schranky s mistni mezipameti (napr. Koncepty otevrene v okne) uvidi okno zmenu hned
function sync_if_cached(st, raw):
    if exists(store.mailbox_dir(st["cfg"]["id"], raw) + "/state.json"):
        safe:
            call sync_mailbox(st, raw, False)
        end
    end
    return 0
end

# Kroky po odeslani nad IMAP: kopie do Odeslanych, priznak odpovedi, smazani konceptu. Hotove kroky se
# zapisou do zakazky (pri vypadku se nezopakuji).
function post_send(st, job, data):
    done = job.get("done", [])
    if "sent" not in done:
        if not server_saves_sent(st):
            raw = ensure_role_box(st, "sent", "Sent")
            uid = 0
            try:
                uid = imap.append(st["conn"], raw, ["\\Seen"], data)
            else:
                err = String(last_error())
                if imap.error_kind(err)[0] != "nobox":
                    Error(MailError: err.replace("MailError: ", ""))
                end
                call imap.create(st["conn"], raw)
                uid = imap.append(st["conn"], raw, ["\\Seen"], data)
            end
            call sync_if_cached(st, raw)
        end
        done.append("sent")
        job["done"] = done
    end
    reply = job.get("reply", {})
    if "reply" not in done and type(reply) == "Dictionary" and reply.get("account", "") == st["cfg"]["id"] and type(reply.get("uid")) == "Int" and reply["uid"] > 0:
        flag = "\\Answered"
        if reply.get("forward", False):
            flag = "$Forwarded"
        end
        safe:
            call set_flags(st, String(reply.get("mailbox", "INBOX")), [reply["uid"]], True, [flag])
        end
        done.append("reply")
        job["done"] = done
    end
    mid = String(job.get("draft_id", ""))
    if "draft" not in done and mid != "":
        raw = role_box(st, "drafts")
        if raw != "":
            call delete_uids(st, raw, find_message_id(st, raw, mid))
            call sync_if_cached(st, raw)
        end
        done.append("draft")
        job["done"] = done
    end
    return 0
end

# Adresy, na ktere uzivatel psal (doplnovani v okne): recipients.json {adresa: {"name", "count", "last"}}
function remember_recipients(job):
    path = store.base_data() + "/recipients.json"
    known = None
    if exists(path):
        safe:
            known = json.decode(readfile(path))
        end
    end
    if type(known) != "Dictionary":
        known = {}
    end
    for pair in job.get("recipients", []):
        if type(pair) != "List" or len(pair) < 2:
            continue
        end
        email = String(pair[1]).strip().lower()
        if email == "" or email.find("@") <= 0:
            continue
        end
        prev = known.get(email, {})
        if type(prev) != "Dictionary":
            prev = {}
        end
        name = String(pair[0]).strip()
        if name == "":
            name = String(prev.get("name", ""))
        end
        count = prev.get("count", 0)
        if type(count) != "Int":
            count = 0
        end
        known[email] = {"name": name, "count": count + 1, "last": now()}
    end
    call store.ensure_dir(store.base_data())
    call store.write_private(path, json.encode(known) + "\n")
    return 0
end

# Odeslani jedne zakazky: {"ok": True, "sent": True} | {"ok": True, "queued": True, ...} | {"ok": False, ...}
function deliver(job, interactive):
    id = job["id"]
    account = String(job.get("account", ""))
    if account not in svc["accounts"]:
        return finish_job_error(job, interactive, "noaccount", "The account of this message no longer exists.")
    end
    st = svc["accounts"][account]
    data = readbytes(job_path(id, ".eml"))
    rcpts = []
    for r in job.get("rcpts", []):
        rcpts.append(String(r))
    end
    if len(rcpts) == 0:
        return finish_job_error(job, interactive, "norcpt", "The message has no recipients.")
    end
    if "smtp" not in job.get("done", []):
        job["state"] = "sending"
        job["attempts"] = job["attempts"] + 1
        call save_job(job)
        err = ""
        try:
            s = smtp_settings(st["cfg"])
            conn = smtp_open(st, s)
            try:
                call smtp.send(conn, st["cfg"]["email"], rcpts, data)
            else:
                e2 = String(last_error())
                call smtp.quit(conn)
                Error(MailError: e2.replace("MailError: ", ""))
            end
            call smtp.quit(conn)
        else:
            err = String(last_error())
        end
        if err != "":
            kind = imap.error_kind(err)
            call log("outbox " + id + ": " + kind[0] + ": " + kind[1])
            if smtp.transient(kind[0]) and now() - job["created"] < OUTBOX_GIVE_UP:
                return queue_job(job, kind[0], kind[1])
            end
            return finish_job_error(job, interactive, kind[0], kind[1])
        end
        job["done"] = ["smtp"]
        job["state"] = "post"
        job["error"] = ""
        job["kind"] = ""
        call save_job(job)
        call log("outbox " + id + ": sent")
        safe:
            call remember_recipients(job)
        end
    end
    perr = ""
    try:
        call begin_op(st)
        call post_send(st, job, data)
    else:
        perr = String(last_error())
    end
    call end_op(st, perr)
    if perr != "":
        # zprava odesla; kopie do Odeslanych / priznak se zkusi pozdeji
        call log("outbox " + id + ": after sending: " + perr.replace("MailError: ", ""))
        job["next"] = now() + 60
        call save_job(job)
        call schedule_outbox(60)
    else:
        call remove_job(id)
    end
    call outbox_event()
    return {"ok": True, "sent": True}
end

function queue_job(job, kind, error):
    delay = 30
    k = 1
    while k < job["attempts"] and delay < OUTBOX_MAX_DELAY:
        delay = delay * 2
        k += 1
    end
    delay = min(delay, OUTBOX_MAX_DELAY)
    job["state"] = "queued"
    job["kind"] = kind
    job["error"] = error
    job["next"] = now() + delay
    call save_job(job)
    call schedule_outbox(delay)
    call outbox_event()
    return {"ok": True, "queued": True, "kind": kind, "error": error}
end

# Trvala chyba: pri odeslani z okna zustava zprava v okne psani (zakazka se zrusi); na pozadi zustane v Odchozi
# jako neodeslana a prijde upozorneni
function finish_job_error(job, interactive, kind, error):
    if interactive and job["attempts"] <= 1:
        call remove_job(job["id"])
        call outbox_event()
        return {"ok": False, "kind": kind, "error": error}
    end
    job["state"] = "failed"
    job["kind"] = kind
    job["error"] = error
    call save_job(job)
    call notify_failed(job, kind, error)
    call outbox_event()
    return {"ok": False, "kind": kind, "error": error, "failed": True}
end

function notify_failed(job, kind, error):
    if svc["session"] == 0:
        return 0
    end
    subject = String(job.get("subject", ""))
    if subject == "":
        subject = i18n.T("(no subject)")
    end
    body = glib.markup_escape(subject)
    if error != "":
        body = body + "\n" + glib.markup_escape(error[0:min(len(error), 160)])
    end
    target = {"outbox": job["id"]}
    actions = ["default", i18n.T("Open")]
    hints = {"category": ["s", "email"], "desktop-entry": ["s", "luxos-mail"], "x-luxos-keep": ["b", True]}
    call gio.call_async(svc["session"], "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify",
                        [i18n.T("Mail"), 0, "luxos-mail", i18n.T("A message could not be sent"), body, actions, hints, 0],
                        "(susssasa{sv}i)", 5000, on_failed_noted, target)
    return 0
end

function on_failed_noted(target, values, error):
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

function schedule_outbox(delay):
    when = now() + delay
    if svc["outbox_timer"] != 0:
        if svc["outbox_when"] <= when:
            return 0
        end
        call glib.source_remove(svc["outbox_timer"])
    end
    svc["outbox_when"] = when
    svc["outbox_timer"] = glib.timeout_add_seconds_data(max(1, delay), on_outbox_timer, 0)
    return 0
end

function on_outbox_timer(unused):
    svc["outbox_timer"] = 0
    call process_outbox(False)
    return False
end

# Zakazky na rade (force: hned vse ve fronte, napr. po pripojeni site); neodeslane s trvalou chybou ne
function process_outbox(force):
    soonest = 0
    for job in list_jobs():
        state = String(job.get("state", ""))
        if state == "failed" or (state == "new" and now() - job["created"] < 600):
            continue
        end
        # odeslana zprava, jen kopie do Odeslanych / priznak se nepovedly (ucet bez spojeni IMAP): po 48 h vzdat
        if state == "post" and now() - job["created"] > OUTBOX_GIVE_UP:
            call log("outbox " + job["id"] + ": giving up saving the sent copy")
            call remove_job(job["id"])
            continue
        end
        if not force and job["next"] > now():
            wait = job["next"] - now()
            if soonest == 0 or wait < soonest:
                soonest = wait
            end
            continue
        end
        safe:
            call deliver(job, False)
        end
    end
    if soonest > 0:
        call schedule_outbox(soonest)
    end
    return 0
end

function send_op(req):
    job = load_job(String(req.get("job", "")))
    if len(job) == 0:
        return {"ok": False, "kind": "invalid", "error": "The message to send was not found."}
    end
    if job["created"] == 0:
        job["created"] = now()
    end
    if req.get("retry", False):
        job["attempts"] = 0
        job["state"] = "queued"
        job["created"] = now()
    end
    return deliver(job, not req.get("retry", False))
end

function outbox_delete(req):
    id = String(req.get("job", ""))
    job = load_job(id)
    if len(job) > 0 and job.get("state", "") != "sending":
        call remove_job(id)
        call outbox_event()
    end
    return {"ok": True}
end

# Koncept na server (Koncepty, IMAP APPEND s \Draft); starsi verze se stejnym Message-ID se smazou
function save_draft(req):
    st = account_state(req.get("account", ""))
    path = String(req.get("path", ""))
    mid = String(req.get("message_id", ""))
    if not path.startswith(store.base_data() + "/drafts/") or path.find("/..") >= 0 or not exists(path):
        return {"ok": False, "kind": "invalid", "error": "The draft was not found."}
    end
    data = readbytes(path)
    result = {"ok": True}
    err = ""
    try:
        call begin_op(st)
        raw = ensure_role_box(st, "drafts", "Drafts")
        uid = imap.append(st["conn"], raw, ["\\Draft", "\\Seen"], data)
        uids = find_message_id(st, raw, mid)
        if uid == 0 and len(uids) > 0:
            uid = uids[len(uids) - 1]
            for u in uids:
                if u > uid:
                    uid = u
                end
            end
        end
        old = []
        for u in uids:
            if u != uid:
                old.append(u)
            end
        end
        call delete_uids(st, raw, old)
        call sync_if_cached(st, raw)
        result["uid"] = uid
        result["mailbox"] = raw
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

function delete_draft(req):
    st = account_state(req.get("account", ""))
    mid = String(req.get("message_id", ""))
    err = ""
    try:
        call begin_op(st)
        raw = role_box(st, "drafts")
        if raw != "":
            call delete_uids(st, raw, find_message_id(st, raw, mid))
            call sync_if_cached(st, raw)
        end
    else:
        err = String(last_error())
    end
    call end_op(st, err)
    if err != "":
        kind = imap.error_kind(err)
        return {"ok": False, "kind": kind[0], "error": kind[1]}
    end
    return {"ok": True}
end

# Podpis a zobrazovane jmeno uctu (okno: Nastaveni uctu)
function account_settings(req):
    st = account_state(req.get("account", ""))
    out = []
    for a in store.load_accounts():
        if a["id"] == st["cfg"]["id"]:
            if type(req.get("signature")) == "String":
                a["signature"] = req["signature"][0:4000]
            end
            if type(req.get("name")) == "String":
                a["name"] = req["name"].strip()[0:200]
            end
            st["cfg"]["signature"] = a.get("signature", "")
            st["cfg"]["name"] = a.get("name", "")
        end
        out.append(a)
    end
    call store.save_accounts(out)
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
    elif op == "oauth_start":
        return oauth_start(req)
    elif op == "oauth_cancel":
        return oauth_cancel(req)
    elif op == "oauth_providers":
        return oauth_providers(req)
    elif op == "remove_account":
        return remove_account(req)
    elif op == "reconnect":
        call reconnect_all("request")
        return {"ok": True}
    elif op == "quit":
        call glib.main_quit()
        return {"ok": True}
    elif op == "send":
        return send_op(req)
    elif op == "outbox_delete":
        return outbox_delete(req)
    elif op == "outbox_retry":
        req["retry"] = True
        return send_op(req)
    elif op == "save_draft":
        return save_draft(req)
    elif op == "delete_draft":
        return delete_draft(req)
    elif op == "account_settings":
        return account_settings(req)
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
    # neodeslane zpravy z minula (vypadek site, restart) az po pripojeni uctu
    call schedule_outbox(5 + len(svc["order"]))
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
