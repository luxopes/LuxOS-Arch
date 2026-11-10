# Posta LuxOS - okno psani zpravy (Nova zprava, Odpovedet, Odpovedet vsem, Preposlat, koncept, mailto:).
# Pole Od (vyber uctu), Komu/Kopie/Skryta kopie s doplnovanim adres (komu uzivatel psal + odesilatele v mistni
# poste), Predmet, text, prilohy (tlacitko, Ctrl+Shift+A nebo presunuti souboru do okna; seznam s odebranim).
# Ctrl+Enter odesle, Ctrl+S ulozi koncept, Esc/Ctrl+W zavre (s otazkou Ulozit koncept?).
# Nikdy se neztrati: rozepsana zprava se 1,5 s po kazde zmene ulozi do ~/.local/share/luxos-mail/drafts/<id>.json
# (po padu se okno pri dalsim spusteni samo obnovi) a po 30 s do slozky Koncepty na serveru (IMAP APPEND pres sluzbu,
# predchozi verze se nahradi, po odeslani smaze). Odeslani: zprava se slozi zde (mail_mime.compose), ulozi do
# Odchozi (outbox/<id>.eml + .json) a sluzba ji posle; bez site zustane v Odchozi a odejde sama pozdeji.
load env, json, net
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load crypto
load mail_bytes as mb
load mail_mime as mime
load mail_store as store
load mail_gtk as mg

LOCAL_SAVE_MS = 1500
SERVER_SAVE_S = 30
LARGE = 26214400

cs = {"host": {}, "windows": {}, "known": [], "known_at": 0, "store": 0}

function init(host):
    cs["host"] = host
    return 0
end

function host_call(name, args):
    f = cs["host"].get(name, None)
    if f == None:
        return 0
    end
    if len(args) == 0:
        return f()
    elif len(args) == 1:
        return f(args[0])
    elif len(args) == 2:
        return f(args[0], args[1])
    end
    return f(args[0], args[1], args[2])
end

function request(op, fields, ctx):
    return host_call("request", [op, fields, ctx])
end

function trace(text):
    return host_call("trace", [text])
end

function new_id():
    return crypto.hex(crypto.random_bytes(8))
end

function drafts_dir():
    return store.ensure_dir(store.base_data() + "/drafts")
end

function outbox_dir():
    return store.ensure_dir(store.base_data() + "/outbox")
end

function label(text, css):
    l = gtk.label_new(text)
    call gtk.label_set_xalign(l, 0)
    if css != "":
        for c in css.split(" "):
            call gtk.widget_add_class(l, c)
        end
    end
    return l
end

function icon(names, size):
    for n in names:
        if gtk.icon_theme_has_icon(n):
            return gtk.image_new_from_icon_name(n, size)
        end
    end
    return gtk.image_new_from_icon_name(names[0], size)
end

# ---- adresy -----------------------------------------------------------------------------------------------------

# "Jan Novak <jan@x.cz>" s uvozovkami u jmena s carkou/strednikem (aby se pole dalo znovu rozdelit)
function address_text(pair):
    name = String(pair[0]).strip()
    email = String(pair[1]).strip()
    if name == "" or name == email:
        return email
    end
    if name.find(",") >= 0 or name.find(";") >= 0 or name.find("<") >= 0 or name.find("\"") >= 0:
        name = "\"" + name.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
    end
    return name + " <" + email + ">"
end

function pairs_text(pairs):
    out = []
    for p in pairs:
        out.append(address_text(p))
    end
    return ", ".join(out)
end

function valid_email(e):
    at = e.find("@")
    if at <= 0 or e.find(" ") >= 0 or e.count("@") != 1:
        return False
    end
    domain = e[at + 1:]
    return domain.find(".") > 0 and not domain.endswith(".") and not domain.startswith(".")
end

function field_pairs(entry):
    out = []
    for p in mime.parse_addresses(gtk.entry_get_text(entry)):
        out.append([p[0], p[1].strip()])
    end
    return out
end

# Adresy pro doplnovani: komu uzivatel psal (recipients.json, nejcastejsi prvni) a odesilatele v mistni poste
function load_known():
    if cs["known_at"] != 0 and glib.now() - cs["known_at"] < 60:
        return cs["known"]
    end
    seen = {}
    ranked = []
    path = store.base_data() + "/recipients.json"
    data = None
    if exists(path):
        safe:
            data = json.decode(readfile(path))
        end
    end
    if type(data) == "Dictionary":
        keys = []
        by = {}
        for email in data.keys():
            v = data[email]
            if type(v) != "Dictionary":
                continue
            end
            count = v.get("count", 0)
            if type(count) != "Int":
                count = 0
            end
            key = (1000000 - min(count, 999999)) * 10000000000 + (9999999999 - min(v.get("last", 0), 9999999999))
            by[key] = [String(v.get("name", "")), email]
            keys.append(key)
        end
        keys.sort()
        for k in keys:
            p = by[k]
            if p[1].lower() not in seen:
                seen[p[1].lower()] = True
                ranked.append(p)
            end
        end
    end
    own = {}
    for a in store.load_accounts():
        own[a["email"].lower()] = True
        for b in store.load_mailboxes(a["id"]):
            if b["role"] in ["junk", "trash", "all", "important", "starred"]:
                continue
            end
            for m in store.load_index(a["id"], b["raw"]):
                e = m["from_email"].strip()
                if e != "" and e.lower() not in seen and e.lower().find("noreply") < 0 and e.lower().find("no-reply") < 0:
                    seen[e.lower()] = True
                    ranked.append([m["from_name"], e])
                end
                if len(ranked) > 4000:
                    break
                end
            end
        end
    end
    out = []
    for p in ranked:
        if p[1].lower() not in own:
            out.append(address_text(p))
        end
    end
    cs["known"] = out
    cs["known_at"] = glib.now()
    return out
end

function completion_store():
    s = mg.string_store_new()
    for t in load_known():
        call mg.string_store_add(s, t)
    end
    return s
end

# Zacatek posledni adresy v poli (za posledni carkou/strednikem)
function token_start(text):
    pos = -1
    i = 0
    for ch in text:
        if ch == "," or ch == ";":
            pos = i
        end
        i += 1
    end
    return pos + 1
end

function on_match(entry, completion, key, iter):
    text = gtk.entry_get_text(entry)
    k = text[token_start(text):].strip().lower()
    if len(k) < 1:
        return False
    end
    model = cs["store"]
    value = mg.tree_model_text(model, iter).lower()
    if value.startswith(k):
        return True
    end
    for w in value.replace("<", " ").replace("\"", " ").replace(".", " ").split(" "):
        if w.startswith(k):
            return True
        end
    end
    lt = value.find("<")
    return lt >= 0 and value[lt + 1:].startswith(k)
end

function on_match_selected(entry, model, iter, completion):
    text = gtk.entry_get_text(entry)
    start = token_start(text)
    prefix = text[0:start].strip()
    if prefix != "":
        prefix = prefix + " "
    end
    call gtk.entry_set_text(entry, prefix + mg.tree_model_text(model, iter) + ", ")
    call mg.entry_set_position(entry, -1)
    return True
end

function attach_completion(entry):
    if cs["store"] == 0:
        cs["store"] = completion_store()
    end
    rec = glib.track(on_match, 3, entry)
    c = mg.completion_new(entry, cs["store"], rec[0])
    call gtk.connect_data(c, "match-selected", 2, on_match_selected, entry)
    return c
end

# ---- okno ---------------------------------------------------------------------------------------------------------

function accounts():
    return store.load_accounts()
end

function account_of(id):
    for a in accounts():
        if a["id"] == id:
            return a
        end
    end
    return {}
end

function signature_block(a):
    sig = String(a.get("signature", "")).strip()
    if sig == "":
        return ""
    end
    return "-- \n" + sig
end

function grid_field(grid, row, title, widget):
    l = label(title, "dim")
    call gtk.widget_set_halign(l, gtk.ALIGN_END)
    call gtk.grid_attach(grid, l, 0, row, 1, 1)
    call gtk.widget_set_hexpand(widget, True)
    call gtk.grid_attach(grid, widget, 1, row, 1, 1)
    call gtk.accessible_name(widget, title.replace(":", ""))
    return widget
end

# opts: account, to/cc/bcc ([[jmeno, adresa]]), subject, text, cursor_top, in_reply_to, references, reply
# ({"account", "mailbox", "uid", "forward"}), attachments ([{"name", "path"}]), draft_mid (koncept na serveru),
# id (obnoveni mistniho konceptu), note (text ve stavovem radku)
function open(opts):
    accs = accounts()
    if len(accs) == 0:
        return 0
    end
    id = String(opts.get("id", ""))
    if id == "":
        id = new_id()
    end
    if id in cs["windows"] and not cs["windows"][id]["closed"]:
        call gtk.window_present(cs["windows"][id]["win"])
        return 0
    end
    account = String(opts.get("account", ""))
    if len(account_of(account)) == 0:
        account = accs[0]["id"]
    end
    win = gtk.window_new(i18n.T("New Message"))
    call gtk.window_set_wmclass(win, "luxos-mail", "luxos-mail")
    call gtk.window_set_icon_list(win, "luxos-mail")
    call gtk.window_set_default_size(win, 760, 640)
    root = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.container_add(win, root)

    bar = gtk.box_new(gtk.HORIZONTAL, 6)
    call gtk.widget_add_class(bar, "toolbar")
    send = gtk.button_new_empty()
    sb = gtk.box_new(gtk.HORIZONTAL, 6)
    call gtk.box_pack_start(sb, icon(["mail-send-symbolic", "document-send-symbolic"], 1), False, False, 0)
    call gtk.box_pack_start(sb, gtk.label_new(i18n.T("Send")), False, False, 0)
    call gtk.container_add(send, sb)
    call gtk.widget_add_class(send, "suggested-action")
    call gtk.widget_set_tooltip(send, i18n.T("Send (Ctrl+Enter)"))
    call gtk.accessible_name(send, i18n.T("Send"))
    call gtk.box_pack_start(bar, send, False, False, 0)
    attach = gtk.button_new_empty()
    call gtk.button_set_image(attach, icon(["mail-attachment-symbolic", "document-open-symbolic"], 2))
    call gtk.button_set_relief(attach, gtk.RELIEF_NONE)
    call gtk.widget_set_tooltip(attach, i18n.T("Attach Files… (Ctrl+Shift+A)"))
    call gtk.accessible_name(attach, i18n.T("Attach Files…"))
    call gtk.box_pack_start(bar, attach, False, False, 0)
    spinner = mg.spinner_new()
    call gtk.box_pack_start(bar, spinner, False, False, 4)
    status = label("", "small dim")
    call gtk.label_set_ellipsize(status, 3)
    call gtk.box_pack_start(bar, status, True, True, 0)
    discard = gtk.button_new_empty()
    call gtk.button_set_image(discard, icon(["user-trash-symbolic"], 2))
    call gtk.button_set_relief(discard, gtk.RELIEF_NONE)
    call gtk.widget_set_tooltip(discard, i18n.T("Delete Draft"))
    call gtk.accessible_name(discard, i18n.T("Delete Draft"))
    call gtk.box_pack_end(bar, discard, False, False, 0)
    call gtk.box_pack_start(root, bar, False, False, 0)

    grid = gtk.grid_new()
    call gtk.widget_add_class(grid, "compose-head")
    call gtk.grid_set_row_spacing(grid, 6)
    call gtk.grid_set_column_spacing(grid, 10)
    from_combo = gtk.combo_box_text_new()
    for a in accs:
        t = a["email"]
        if a.get("name", "") != "":
            t = a["name"] + " <" + a["email"] + ">"
        end
        call gtk.combo_box_text_append(from_combo, a["id"], t)
    end
    call mg.combo_box_set_active_id(from_combo, account)
    call grid_field(grid, 0, i18n.T("From:"), from_combo)
    to = grid_field(grid, 1, i18n.T("To:"), gtk.entry_new())
    cc = grid_field(grid, 2, i18n.T("Cc:"), gtk.entry_new())
    bcc = grid_field(grid, 3, i18n.T("Bcc:"), gtk.entry_new())
    subject = grid_field(grid, 4, i18n.T("Subject:"), gtk.entry_new())
    call gtk.box_pack_start(root, grid, False, False, 0)

    att_scroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(att_scroll, gtk.POLICY_AUTOMATIC, gtk.POLICY_NEVER)
    call gtk.widget_add_class(att_scroll, "compose-atts")
    atts_box = gtk.box_new(gtk.HORIZONTAL, 6)
    call gtk.container_add(att_scroll, atts_box)
    call gtk.widget_set_no_show_all(att_scroll, True)
    call gtk.box_pack_start(root, att_scroll, False, False, 0)
    call gtk.box_pack_start(root, gtk.separator_new(gtk.HORIZONTAL), False, False, 0)

    scroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(scroll, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    body = mg.editor_new()
    call gtk.widget_add_class(body, "compose-body")
    call mg.text_view_set_margins(body, 18, 18, 12, 18)
    call gtk.accessible_name(body, i18n.T("Message"))
    call gtk.container_add(scroll, body)
    call gtk.box_pack_start(root, scroll, True, True, 0)

    c = {"id": id, "win": win, "from": from_combo, "to": to, "cc": cc, "bcc": bcc, "subject": subject, "body": body,
         "att_scroll": att_scroll, "atts_box": atts_box, "attachments": [], "status": status, "spinner": spinner, "send": send,
         "attach": attach, "reply": opts.get("reply", {}), "in_reply_to": String(opts.get("in_reply_to", "")),
         "references": String(opts.get("references", "")), "draft_mid": String(opts.get("draft_mid", "")),
         "draft_saved": opts.get("draft_saved", False), "local_timer": 0, "server_timer": 0, "busy": False, "closed": False,
         "loading": True, "dirty": False}
    if c["draft_mid"] == "":
        c["draft_mid"] = mime.new_message_id(account_of(account).get("email", ""))
    else:
        c["draft_saved"] = True
    end
    if type(c["reply"]) != "Dictionary":
        c["reply"] = {}
    end
    cs["windows"][id] = c
    call gtk.entry_set_text(to, pairs_text(opts.get("to", [])))
    call gtk.entry_set_text(cc, pairs_text(opts.get("cc", [])))
    call gtk.entry_set_text(bcc, pairs_text(opts.get("bcc", [])))
    call gtk.entry_set_text(subject, String(opts.get("subject", "")))
    call mg.text_view_set_text(body, String(opts.get("text", "")))
    for a in opts.get("attachments", []):
        call add_attachment(c, String(a.get("path", "")), String(a.get("name", "")))
    end
    for e in [to, cc, bcc]:
        call attach_completion(e)
        call gtk.connect_data(e, "changed", 0, on_changed, c)
    end
    call gtk.connect_data(subject, "changed", 0, on_subject_changed, c)
    call gtk.connect_data(from_combo, "changed", 0, on_changed, c)
    call gtk.connect_data(mg.text_view_buffer(body), "changed", 0, on_changed, c)
    call gtk.connect_data(send, "clicked", 0, on_send_clicked, c)
    call gtk.connect_data(attach, "clicked", 0, on_attach_clicked, c)
    call gtk.connect_data(discard, "clicked", 0, on_discard_clicked, c)
    call gtk.connect_data(win, "delete-event", 1, on_delete, c)
    call gtk.connect_data(win, "key-press-event", 1, on_key, c)
    # soubory pretazene do okna (i do textu: jinak by GtkTextView vlozil adresu souboru jako text)
    call mg.drag_dest_uris(root)
    call mg.drag_dest_uris(body)
    call gtk.connect_data(root, "drag-data-received", 5, on_drop, [c, root])
    call gtk.connect_data(body, "drag-data-received", 5, on_drop, [c, body])
    call update_title(c)
    call gtk.widget_show_all(win)
    call update_attachments(c)
    note = String(opts.get("note", ""))
    if note != "":
        call set_status(c, note, False)
    end
    if gtk.entry_get_text(to).strip() == "":
        call gtk.widget_grab_focus(to)
    else:
        call gtk.widget_grab_focus(body)
        call mg.text_view_scroll_top(body)
    end
    c["loading"] = False
    if opts.get("restored", False):
        c["dirty"] = True
        call schedule_saves(c)
    end
    call trace("compose open " + id)
    return id
end

function update_title(c):
    s = gtk.entry_get_text(c["subject"]).strip()
    if s == "":
        s = i18n.T("New Message")
    end
    call gtk.window_set_title(c["win"], s)
    return 0
end

function set_status(c, text, error):
    call gtk.label_set_text(c["status"], text)
    call gtk.widget_set_class(c["status"], "error", error)
    call gtk.widget_set_class(c["status"], "dim", not error)
    if text != "":
        call trace("compose status " + text)
    end
    return 0
end

function set_busy(c, on):
    c["busy"] = on
    call mg.spinner_set(c["spinner"], on)
    for w in [c["send"], c["attach"], c["to"], c["cc"], c["bcc"], c["subject"], c["from"]]:
        call gtk.widget_set_sensitive(w, not on)
    end
    call mg.text_view_set_editable(c["body"], not on)
    return 0
end

function on_changed(c, widget):
    if c["loading"] or c["closed"]:
        return 0
    end
    c["dirty"] = True
    call schedule_saves(c)
    return 0
end

function on_subject_changed(c, entry):
    call update_title(c)
    call on_changed(c, entry)
    return 0
end

# Koncept na server po N sekundach bez zmeny (testy: LUXOS_MAIL_DRAFT_SECONDS)
function server_delay():
    v = env.get("LUXOS_MAIL_DRAFT_SECONDS", "")
    if v != None and v != "":
        n = mime.to_int(v, SERVER_SAVE_S)
        if n >= 1:
            return n
        end
    end
    return SERVER_SAVE_S
end

function schedule_saves(c):
    if c["local_timer"] == 0:
        c["local_timer"] = glib.timeout_add_data(LOCAL_SAVE_MS, on_local_timer, c)
    end
    if c["server_timer"] != 0:
        call glib.source_remove(c["server_timer"])
    end
    c["server_timer"] = glib.timeout_add_seconds_data(server_delay(), on_server_timer, c)
    return 0
end

function on_local_timer(c):
    c["local_timer"] = 0
    if not c["closed"]:
        call save_local(c, True)
    end
    return False
end

function on_server_timer(c):
    c["server_timer"] = 0
    if not c["closed"] and not c["busy"] and c["dirty"]:
        call save_server(c)
    end
    return False
end

function account_id(c):
    id = mg.combo_box_get_active_id(c["from"])
    if id == "":
        a = accounts()
        if len(a) > 0:
            id = a[0]["id"]
        end
    end
    return id
end

function state_of(c, open_flag):
    atts = []
    for a in c["attachments"]:
        atts.append({"name": a["name"], "path": a["path"]})
    end
    return {"id": c["id"], "account": account_id(c), "to": field_pairs(c["to"]), "cc": field_pairs(c["cc"]), "bcc": field_pairs(c["bcc"]),
            "subject": gtk.entry_get_text(c["subject"]), "text": mg.text_view_get_text(c["body"]), "attachments": atts,
            "reply": c["reply"], "in_reply_to": c["in_reply_to"], "references": c["references"], "draft_mid": c["draft_mid"],
            "draft_saved": c["draft_saved"], "open": open_flag, "saved": glib.now()}
end

function local_path(id, ext):
    return drafts_dir() + "/" + id + ext
end

function save_local(c, open_flag):
    st = state_of(c, open_flag)
    if not has_content_state(st):
        safe:
            call remove_path(local_path(c["id"], ".json"))
        end
        return st
    end
    call store.write_private(local_path(c["id"], ".json"), json.encode(st) + "\n")
    return st
end

function has_content_state(st):
    text = st["text"].strip()
    sig_only = text == "" or text.startswith("-- \n") or text == "--"
    return len(st["to"]) > 0 or len(st["cc"]) > 0 or len(st["bcc"]) > 0 or st["subject"].strip() != "" or not sig_only or len(st["attachments"]) > 0
end

function message_of(st, draft):
    a = account_of(st["account"])
    loaded = []
    for att in st["attachments"]:
        data = readbytes(att["path"])
        loaded.append({"name": att["name"], "data": data})
    end
    m = {"from": [String(a.get("name", "")), String(a.get("email", ""))], "to": st["to"], "cc": st["cc"], "bcc": st["bcc"],
         "subject": st["subject"], "text": st["text"], "in_reply_to": st["in_reply_to"], "references": st["references"],
         "attachments": loaded, "draft": draft}
    if draft:
        m["message_id"] = st["draft_mid"]
    end
    return m
end

# Koncept do slozky Koncepty na serveru (pres sluzbu); bez site zustane mistni kopie
function save_server(c):
    st = save_local(c, not c["closed"])
    if not has_content_state(st):
        return 0
    end
    ok = True
    data = ByteArray()
    try:
        data = mime.compose(message_of(st, True))
    else:
        ok = False
    end
    if not ok:
        return 0
    end
    path = local_path(c["id"], ".eml")
    call writebytes(path, data)
    call mb.chmod(path, 384)
    c["dirty"] = False
    call request("save_draft", {"account": st["account"], "path": path, "message_id": st["draft_mid"]}, {"compose": c["id"], "draft": True})
    return 0
end

# ---- prilohy ------------------------------------------------------------------------------------------------------

function size_text(n):
    return glib.format_size(n)
end

function add_attachment(c, path, name):
    if path == "" or not exists(path) or glib.is_dir(path):
        call set_status(c, i18n.TF("%s is not a file that can be attached.", [path]), True)
        return False
    end
    size = mb.file_size(path)
    if size < 0:
        call set_status(c, i18n.TF("%s cannot be read.", [path]), True)
        return False
    end
    for a in c["attachments"]:
        if a["path"] == path:
            return False
        end
    end
    if name == "":
        parts = path.split("/")
        name = parts[len(parts) - 1]
    end
    c["attachments"].append({"name": name, "path": path, "size": size})
    return True
end

function total_size(c):
    t = 0
    for a in c["attachments"]:
        t += a["size"]
    end
    return t
end

function update_attachments(c):
    box = c["atts_box"]
    for child in gtk.container_get_children(box):
        call gtk.widget_destroy(child)
    end
    if len(c["attachments"]) == 0:
        call gtk.widget_hide(c["att_scroll"])
        return 0
    end
    call gtk.box_pack_start(box, icon(["mail-attachment-symbolic"], 1), False, False, 0)
    for a in c["attachments"]:
        chip = gtk.box_new(gtk.HORIZONTAL, 2)
        call gtk.widget_add_class(chip, "att-chip")
        l = gtk.label_new(a["name"] + " (" + size_text(a["size"]) + ")")
        call gtk.label_set_ellipsize(l, 2)
        call gtk.label_set_max_width_chars(l, 32)
        call gtk.widget_set_tooltip(l, a["path"])
        call gtk.box_pack_start(chip, l, False, False, 0)
        x = gtk.button_new_empty()
        call gtk.button_set_image(x, icon(["window-close-symbolic"], 1))
        call gtk.button_set_relief(x, gtk.RELIEF_NONE)
        call gtk.widget_set_tooltip(x, i18n.T("Remove Attachment"))
        call gtk.accessible_name(x, i18n.TF("Remove attachment %s", [a["name"]]))
        call gtk.connect_data(x, "clicked", 0, on_remove_attachment, [c, a["path"]])
        call gtk.box_pack_start(chip, x, False, False, 0)
        call gtk.box_pack_start(box, chip, False, False, 0)
    end
    total = total_size(c)
    tl = label(i18n.TF("Total %s", [size_text(total)]), "dim small")
    if total > LARGE:
        call gtk.label_set_text(tl, i18n.TF("Total %s – many servers refuse messages over 25 MB", [size_text(total)]))
        call gtk.widget_add_class(tl, "error")
    end
    call gtk.box_pack_start(box, tl, False, False, 8)
    call gtk.widget_show_all(box)
    call gtk.widget_show(c["att_scroll"])
    return 0
end

function add_paths(c, paths):
    added = 0
    for p in paths:
        if add_attachment(c, p, ""):
            added += 1
        end
    end
    if added > 0:
        call update_attachments(c)
        call on_changed(c, c["atts_box"])
        call trace("compose attachments " + String(len(c["attachments"])))
    end
    return added
end

function on_remove_attachment(pair, button):
    c = pair[0]
    keep = []
    for a in c["attachments"]:
        if a["path"] != pair[1]:
            keep.append(a)
        end
    end
    c["attachments"] = keep
    call update_attachments(c)
    call on_changed(c, button)
    call gtk.widget_grab_focus(c["attach"])
    return 0
end

function on_attach_clicked(c, button):
    if c["busy"]:
        return 0
    end
    chooser = gtk.file_chooser_new(i18n.T("Attach Files"), 0)
    call gtk.dialog_add_button(chooser, i18n.T("Cancel"), gtk.RESPONSE_CANCEL)
    call gtk.dialog_add_button(chooser, i18n.T("Attach"), gtk.RESPONSE_OK)
    call gtk.dialog_set_default_response(chooser, gtk.RESPONSE_OK)
    call gtk.window_set_transient_for(chooser, c["win"])
    call mg.file_chooser_set_multiple(chooser, True)
    response = gtk.dialog_run(chooser)
    paths = []
    if response == gtk.RESPONSE_OK:
        paths = mg.file_chooser_get_filenames(chooser)
    end
    call gtk.widget_destroy(chooser)
    call add_paths(c, paths)
    return 0
end

function on_drop(pair, context, x, y, selection, info, time):
    c = pair[0]
    paths = mg.selection_paths(selection)
    if len(paths) > 0:
        call mg.stop_emission(pair[1], "drag-data-received")
        if not c["busy"]:
            call add_paths(c, paths)
        end
    end
    return 0
end

# ---- odeslani -----------------------------------------------------------------------------------------------------

function ask(c, title, text, buttons, default):
    d = gtk.dialog_new()
    call gtk.window_set_title(d, i18n.T("Mail"))
    call gtk.window_set_transient_for(d, c["win"])
    call gtk.window_set_modal(d, True)
    area = gtk.dialog_get_content_area(d)
    box = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.widget_add_class(box, "dialog-box")
    t = label(title, "list-title")
    call gtk.label_set_line_wrap(t, True)
    call gtk.box_pack_start(box, t, False, False, 0)
    if text != "":
        l = label(text, "")
        call gtk.label_set_line_wrap(l, True)
        call gtk.label_set_max_width_chars(l, 56)
        call gtk.box_pack_start(box, l, False, False, 0)
    end
    call gtk.box_pack_start(area, box, True, True, 0)
    for b in buttons:
        call gtk.dialog_add_button(d, b[0], b[1])
    end
    call gtk.dialog_set_default_response(d, default)
    call gtk.widget_show_all(d)
    response = gtk.dialog_run(d)
    call gtk.widget_destroy(d)
    return response
end

function do_send(c):
    if c["busy"] or c["closed"]:
        return 0
    end
    st = state_of(c, True)
    rcpts = []
    bad = []
    for p in st["to"] + st["cc"] + st["bcc"]:
        if valid_email(p[1]):
            if p[1] not in rcpts:
                rcpts.append(p[1])
            end
        else:
            bad.append(p[1])
        end
    end
    if len(bad) > 0:
        call set_status(c, i18n.TF("Check the address: %s", [", ".join(bad)]), True)
        call gtk.widget_grab_focus(c["to"])
        return 0
    end
    if len(rcpts) == 0:
        call set_status(c, i18n.T("Add at least one recipient."), True)
        call gtk.widget_grab_focus(c["to"])
        return 0
    end
    if st["subject"].strip() == "":
        r = ask(c, i18n.T("Send this message without a subject?"), "", [[i18n.T("Cancel"), gtk.RESPONSE_CANCEL], [i18n.T("Send"), gtk.RESPONSE_OK]], gtk.RESPONSE_OK)
        if r != gtk.RESPONSE_OK:
            call gtk.widget_grab_focus(c["subject"])
            return 0
        end
    end
    for a in c["attachments"]:
        if not exists(a["path"]):
            call set_status(c, i18n.TF("The attachment %s no longer exists.", [a["name"]]), True)
            return 0
        end
    end
    data = ByteArray()
    err = ""
    try:
        data = mime.compose(message_of(st, False))
    else:
        err = String(last_error())
    end
    if err != "":
        call set_status(c, i18n.T("The message could not be prepared.") + " " + err, True)
        return 0
    end
    call save_local(c, True)
    job = new_id()
    path = outbox_dir() + "/" + job + ".eml"
    call writebytes(path, data)
    call mb.chmod(path, 384)
    to_text = []
    for p in st["to"] + st["cc"]:
        to_text.append(mime.address_display(p))
    end
    draft_id = ""
    if c["draft_saved"]:
        draft_id = c["draft_mid"]
    end
    desc = {"account": st["account"], "rcpts": rcpts, "recipients": st["to"] + st["cc"] + st["bcc"], "subject": st["subject"],
            "to_text": ", ".join(to_text), "state": "new", "created": glib.now(), "reply": c["reply"], "draft_id": draft_id,
            "compose": st, "size": len(data)}
    call store.write_private(outbox_dir() + "/" + job + ".json", json.encode(desc) + "\n")
    c["job"] = job
    call set_busy(c, True)
    call set_status(c, i18n.T("Sending…"), False)
    call request("send", {"job": job}, {"compose": c["id"], "job": job})
    return 0
end

function on_send_clicked(c, button):
    call do_send(c)
    return 0
end

function account_email(id):
    return String(account_of(id).get("email", ""))
end

function server_detail(text):
    if text == "":
        return ""
    end
    return " (" + i18n.T("Server:") + " " + text + ")"
end

function error_text(kind, detail, account):
    email = account_email(account)
    if kind == "auth":
        return i18n.TF("The outgoing server did not accept the sign-in for %s.", [email]) + server_detail(detail)
    elif kind == "nopassword":
        return i18n.T("The password is not in the keyring. Enter it again in the main window.")
    elif kind == "rcpt":
        parts = detail.split("|")
        t = i18n.TF("The server refused these recipients: %s", [parts[0]])
        if len(parts) > 1:
            t = t + server_detail("|".join(parts[1:]))
        end
        return t
    elif kind == "toolarge":
        limit = mime.to_int(detail, 0)
        if limit > 0:
            return i18n.TF("The message is too large for the server (at most %s). Remove some attachments.", [size_text(limit)])
        end
        return i18n.T("The message is too large for the server. Remove some attachments.")
    elif kind == "smtp_rejected":
        return i18n.T("The outgoing server refused the message.") + server_detail(detail)
    elif kind == "smtp_noauth" or kind == "oauthonly" or kind == "nooauth":
        return i18n.T("The outgoing server does not allow this account to sign in.") + server_detail(detail)
    elif kind == "cert":
        return i18n.TF("The security certificate of the outgoing server is not valid (%s). Mail does not send to protect your password.", [detail])
    elif kind == "nostarttls" or kind == "insecure":
        return i18n.T("The outgoing server does not offer an encrypted connection. Mail does not send your password unencrypted.")
    elif kind == "smtp_utf8":
        return i18n.T("The outgoing server does not accept addresses with accented characters.")
    elif kind == "noaccount":
        return i18n.T("The account of this message no longer exists.")
    elif kind.startswith("oauth_"):
        return i18n.T("Your sign-in has expired. Sign in again in the main window, then send the message again.")
    elif kind.startswith("luxai_"):
        return i18n.T("Your LuxAI sign-in is not available. Sign in again, then send the message again.")
    end
    if detail != "":
        return i18n.T("The message could not be sent.") + server_detail(detail)
    end
    return i18n.T("The message could not be sent.")
end

function remove_local(c):
    for ext in [".json", ".eml"]:
        safe:
            call remove_path(local_path(c["id"], ext))
        end
    end
    return 0
end

function close_window(c):
    c["closed"] = True
    for key in ["local_timer", "server_timer"]:
        if c[key] != 0:
            call glib.source_remove(c[key])
            c[key] = 0
        end
    end
    if c["win"] != 0:
        call gtk.widget_destroy(c["win"])
        c["win"] = 0
    end
    call trace("compose closed " + c["id"])
    call host_call("closed", [])
    return 0
end

# Odpoved sluzby na pozadavek okna psani (mail_ui.on_reply preda ctx s "compose")
function on_reply(msg, ctx):
    c = cs["windows"].get(ctx.get("compose", ""), None)
    if c == None:
        return 0
    end
    if ctx.get("draft", False):
        if msg.get("ok", False):
            c["draft_saved"] = True
            if c["closed"]:
                call remove_local(c)
                call cs["windows"].pop(c["id"])
            else:
                call save_local(c, True)
                call set_status(c, i18n.T("Draft saved"), False)
            end
        elif not c["closed"]:
            call set_status(c, i18n.T("Draft saved on this computer"), False)
        end
        return 0
    end
    if ctx.get("op", "") != "send":
        return 0
    end
    if msg.get("ok", False) and (msg.get("sent", False) or msg.get("queued", False)):
        call remove_local(c)
        call close_window(c)
        call cs["windows"].pop(c["id"])
        call host_call("sent", [msg.get("sent", False), String(msg.get("kind", ""))])
        return 0
    end
    call set_busy(c, False)
    call set_status(c, error_text(String(msg.get("kind", "")), String(msg.get("error", "")), account_id(c)), True)
    if msg.get("kind", "") == "rcpt":
        call gtk.widget_grab_focus(c["to"])
    end
    return 0
end

# ---- zavreni ------------------------------------------------------------------------------------------------------

function discard(c):
    if c["draft_saved"]:
        call request("delete_draft", {"account": account_id(c), "message_id": c["draft_mid"]}, {"compose": c["id"], "deleted": True})
    end
    call remove_local(c)
    call close_window(c)
    call cs["windows"].pop(c["id"])
    return 0
end

# Zavreni okna: prazdne bez otazky, jinak Ulozit koncept? (Smazat / Zrusit / Ulozit). True = okno zustava.
function request_close(c):
    if c["closed"]:
        return False
    end
    if c["busy"]:
        return True
    end
    st = state_of(c, True)
    if not has_content_state(st):
        call discard(c)
        return False
    end
    if not c["dirty"] and c["draft_saved"]:
        call remove_local(c)
        call close_window(c)
        call cs["windows"].pop(c["id"])
        return False
    end
    r = ask(c, i18n.T("Save this message as a draft?"), i18n.T("You can finish it later in Drafts."),
            [[i18n.T("Delete Draft"), 2], [i18n.T("Cancel"), gtk.RESPONSE_CANCEL], [i18n.T("Save"), gtk.RESPONSE_OK]], gtk.RESPONSE_OK)
    if r == gtk.RESPONSE_OK:
        c["closed"] = True
        call save_server(c)
        # mistni kopie zustane (neodeslana na server), dokud sluzba koncept neulozi
        call store.write_private(local_path(c["id"], ".json"), json.encode(state_of_closed(c, st)) + "\n")
        call close_window(c)
        return False
    elif r == 2:
        call discard(c)
        return False
    end
    return True
end

function state_of_closed(c, st):
    st["open"] = False
    st["unsynced"] = True
    return st
end

function on_delete(c, event, win):
    return request_close(c)
end

function on_discard_clicked(c, button):
    if c["busy"]:
        return 0
    end
    st = state_of(c, True)
    if has_content_state(st):
        r = ask(c, i18n.T("Delete this message?"), i18n.T("The draft is deleted from this computer and from Drafts on the server."),
                [[i18n.T("Cancel"), gtk.RESPONSE_CANCEL], [i18n.T("Delete"), gtk.RESPONSE_OK]], gtk.RESPONSE_CANCEL)
        if r != gtk.RESPONSE_OK:
            return 0
        end
    end
    call discard(c)
    return 0
end

function on_key(c, event, win):
    key = gtk.event_key_keyval(event)
    state = gtk.event_key_state(event)
    ctrl = (state & gtk.CONTROL_MASK) != 0
    shift = (state & gtk.SHIFT_MASK) != 0
    if ctrl and (key == gtk.KEY_Return or key == 65421):
        call do_send(c)
        return True
    end
    if ctrl and shift and (key == 97 or key == 65):
        call on_attach_clicked(c, c["attach"])
        return True
    end
    if ctrl and (key == 115 or key == 83):
        if not c["busy"]:
            call save_server(c)
        end
        return True
    end
    if key == gtk.KEY_Escape or (ctrl and (key == 119 or key == 87)):
        if not request_close(c):
            return True
        end
        return True
    end
    return False
end

# ---- obnoveni po padu ---------------------------------------------------------------------------------------------

# Pri spusteni okna: rozepsane zpravy, jejichz okno bylo otevrene (pad, vypnuti), se otevrou znovu; ulozene
# koncepty, ktere se nedostaly na server (bez site), se tam zkusi poslat znovu
function restore_all():
    restored = 0
    for name in glib.list_dir(drafts_dir()):
        if not name.endswith(".json"):
            continue
        end
        id = name[0:len(name) - 5]
        st = None
        safe:
            st = json.decode(readfile(local_path(id, ".json")))
        end
        if type(st) != "Dictionary" or id in cs["windows"]:
            continue
        end
        if st.get("open", False):
            opts = st
            opts["id"] = id
            opts["restored"] = True
            opts["note"] = i18n.T("Recovered – Mail closed before this message was sent or saved.")
            call open(opts)
            restored += 1
        elif st.get("unsynced", False) and exists(local_path(id, ".eml")):
            c = {"id": id, "closed": True, "win": 0, "local_timer": 0, "server_timer": 0, "draft_saved": False}
            cs["windows"][id] = c
            call request("save_draft", {"account": String(st.get("account", "")), "path": local_path(id, ".eml"),
                                        "message_id": String(st.get("draft_mid", ""))}, {"compose": id, "draft": True})
        end
    end
    return restored
end

function open_count():
    n = 0
    for id in cs["windows"].keys():
        if not cs["windows"][id]["closed"]:
            n += 1
        end
    end
    return n
end
