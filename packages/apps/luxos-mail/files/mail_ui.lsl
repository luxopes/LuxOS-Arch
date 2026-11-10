# Posta LuxOS - okno ve tri sloupcich jako Posta v macOS: schranky, seznam zprav, zprava.
# Mezipamet cte primo ze souboru (spusteni bez cekani na sit, offline prohlizeni), o sit zada sluzbu
# `luxos-mail --background` (socket "luxos-mail-<uid>"; kdyz nebezi, okno ji spusti).
# Jedna instance okna: dalsi spusteni (--open z upozorneni, mailto:) preda pozadavek pres socket
# "luxos-mail-ui-<uid>" a skonci.
# Klavesnice: sipky v seznamech, Enter = text zpravy, Delete = do Kose, Ctrl+Shift+U = prectena/neprectena,
# Ctrl+F = filtr seznamu (Esc zrusi; ve zprave hledani v textu), F5 / Ctrl+Shift+N = stahnout postu, Ctrl+N = nova zprava,
# Ctrl+R = odpovedet, Ctrl+Shift+R = odpovedet vsem, Ctrl+Shift+F = preposlat, Ctrl+P = tisk, Ctrl+plus/minus/0 =
# velikost textu zpravy, Ctrl+Q/W = zavrit.
# Zprava se zobrazuje ve WebKitGTK (mail_web) jako bezpecny dokument z mail_html: HTML zpravy s rozvrzenim a obrazky
# z priloh, prosty text s odkazy a citacemi; odkazy jdou do prohlizece (mailto: do okna psani), vzdalene obrazky az
# po "Nacist obrazky" (nebo vzdy od odesilatele). Bez WebKitu zustava text v GtkTextView.
# Psani zprav: mail_compose (okno psani, koncepty, Odchozi).
# Prvni spusteni s uctem LuxAI v systemu: "Pokracovat jako <jmeno>" nabidne schranky na serveru LuxAI
# (pridani jednim kliknutim, bez hesla - token uctu LuxAI); "Pouzit jiny ucet" otevre bezne pridani
# s predvyplnenym registracnim e-mailem.
# Velci poskytovatele (Google, Microsoft, Yahoo, iCloud, Seznam ...): pri pridani uctu napoveda, jake heslo
# zadat (heslo aplikace) s tlacitkem na stranku poskytovatele; chyby prihlaseni s duvodem od serveru.
# Pole hesla maji tlacitko oka (zobrazit/skryt heslo, Tab + mezernik). F10 = nabidka.
# Prihlaseni u poskytovatele (mail_oauth): kdyz ma poskytovatel (Google, Microsoft) vyplnene client ID, pridani
# uctu ukaze jedno hlavni tlacitko "Prihlasit se Googlem" (prohlizec, bez hesla v Poste); pole hesla je az pod
# "Pouzit radeji heslo aplikace". Bez client ID zustava napoveda k heslu aplikace. Po prihlaseni se okno Posty
# samo vrati do popredi; vyprsene prihlaseni ukaze klidny pruh "Prihlasit se znovu".
load env, json, net
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_sys
load luxos_i18n as i18n
load mail_bytes as mb
load mail_mime as mime
load mail_store as store
load mail_gtk as mg
load mail_luxai as luxai
load mail_provider as provider
load mail_oauth as oauth
load mail_html as mhtml
load mail_web as web
load mail_compose as compose

CSS = ".toolbar { padding: 6px 8px; border-bottom: 1px solid alpha(currentColor, 0.10); }\n.toolbar button { min-height: 26px; padding: 2px 8px; }\n.sidebar, .sidebar list { background-color: alpha(currentColor, 0.035); }\n.sidebar row { padding: 4px 10px; border-radius: 6px; margin: 0 6px; }\n.side-header { font-size: 11px; font-weight: 700; opacity: 0.55; margin: 12px 4px 2px 4px; }\n.side-count { font-size: 11px; opacity: 0.6; }\n.side-error { color: #d9534f; }\n.list-head { padding: 10px 14px 6px 14px; }\n.list-title { font-weight: 700; font-size: 15px; }\n.dim { opacity: 0.6; }\n.small { font-size: 11px; }\n.msg-row { padding: 8px 12px 8px 6px; border-bottom: 1px solid alpha(currentColor, 0.07); }\n.sender { font-size: 13px; }\n.sender.unread { font-weight: 700; }\n.subject { font-size: 12.5px; }\n.preview { font-size: 12px; opacity: 0.6; }\n.unread-dot { color: @theme_selected_bg_color; font-size: 11px; min-width: 14px; }\n.flagged { color: #e6a700; }\n.banner { padding: 8px 14px; background-color: alpha(#e6a700, 0.18); }\n.banner.error { background-color: alpha(#d9534f, 0.18); }\n.msg-head { padding: 16px 22px 10px 22px; border-bottom: 1px solid alpha(currentColor, 0.08); }\n.msg-subject { font-size: 18px; font-weight: 700; }\n.msg-from { font-weight: 600; }\n.att-bar { padding: 8px 22px; border-bottom: 1px solid alpha(currentColor, 0.08); }\n.att { padding: 2px 10px; border-radius: 12px; }\n.body { font-size: 13.5px; }\n.empty { font-size: 16px; opacity: 0.45; }\n.welcome-title { font-size: 22px; font-weight: 700; }\n.dialog-box { padding: 20px 24px; }\n.error { color: #d9534f; }\n.compose-head { padding: 10px 16px 8px 16px; }\n.compose-atts { padding: 4px 14px; }\n.att-chip { padding: 0 2px 0 10px; border-radius: 12px; background-color: alpha(currentColor, 0.07); }\n.compose-body { font-size: 13.5px; }\n.view-bar { padding: 6px 22px; border-bottom: 1px solid alpha(currentColor, 0.08); background-color: alpha(@theme_selected_bg_color, 0.10); }\n.link-status { padding: 2px 8px; margin: 6px; border-radius: 6px; background-color: alpha(@theme_bg_color, 0.95); border: 1px solid alpha(currentColor, 0.15); font-size: 11.5px; }\n.outbox-failed { color: #d9534f; }\n"

ROLE_ORDER = {"inbox": 0, "drafts": 2, "sent": 3, "archive": 4, "junk": 5, "trash": 6, "": 9, "starred": 10, "important": 10, "all": 11}
# Gmail: pohledy na tytez zpravy - v levem sloupci az po "Dalsi"
HIDDEN_ROLES = ["all", "important", "starred"]
ROLE_ICONS = {"outbox": ["mail-outbox-symbolic", "mail-send-symbolic"], "inbox": ["mail-inbox-symbolic", "mail-unread-symbolic"], "sent": ["mail-sent-symbolic", "mail-send-symbolic"],
              "drafts": ["document-edit-symbolic", "text-editor-symbolic"], "trash": ["user-trash-symbolic", "user-trash-symbolic"],
              "junk": ["mail-mark-junk-symbolic", "dialog-warning-symbolic"], "archive": ["mail-archive-symbolic", "folder-documents-symbolic"],
              "all": ["mail-archive-symbolic", "folder-documents-symbolic"], "starred": ["starred-symbolic", "emblem-favorite-symbolic"],
              "important": ["mail-mark-important-symbolic", "emblem-important-symbolic"],
              "": ["folder-symbolic", "folder-symbolic"]}
# radku seznamu najednou (dalsi pri posunu dolu): rychlejsi spusteni a mene widgetu
PAGE = 25
PRIVACY_URL = "https://luxos.lux-ai.cz/privacy/#google-user-data"
PRIVACY_URL_CS = "https://luxos.lux-ai.cz/cs/privacy/#google-user-data"

ui = {"window": 0, "outer": 0, "sidebar": 0, "list": 0, "list_scroll": 0, "view": 0, "text": 0, "text_scroll": 0,
      "h_from": 0, "h_to": 0, "h_cc": 0, "h_date": 0, "h_subject": 0, "h_note": 0, "att_bar": 0, "att_box": 0,
      "search": 0, "banner": 0, "banner_label": 0, "banner_button": 0, "list_title": 0, "list_sub": 0, "spinner": 0,
      "read_button": 0, "delete_button": 0,
      "accounts": [], "side_rows": [], "current": {"account": "", "raw": "", "role": "", "name": ""},
      "rows": [], "shown": [], "built": 0, "row_index": {}, "widgets": {}, "selected": 0, "building": False, "filter": "",
      "svc_fd": -1, "svc_buf": ByteArray(), "next_id": 1, "pending": {}, "outbox": [], "status": {}, "connecting": False,
      "tries": 0, "message": {}, "body": ByteArray(), "body_uid": 0, "open_target": {}, "ui_listen": -1, "dlg": {},
      "started": 0, "ready_logged": False, "older_row": 0, "welcome_button": 0,
      "welcome_luxai": 0, "luxai_button": 0, "luxai_sub": 0, "luxdlg": {}, "luxai_busy": False, "more": {}, "menu_button": 0,
      "web": 0, "body_stack": 0, "images_bar": 0, "images_label": 0, "images_always": 0, "find_bar": 0, "find_entry": 0,
      "link_status": 0, "zoom": 1.0, "view_remote": False, "reply_buttons": [], "jobs": {}, "outbox_note": 0}

function log(message):
    return eprint("luxos-mail: " + message)
end

# Stav okna pro testy (LUXOS_MAIL_UI_TRACE = soubor; jinak nic)
function trace(text):
    path = env.get("LUXOS_MAIL_UI_TRACE", "")
    if path != None and path != "":
        safe:
            call appendfile(path, text + "\n")
        end
    end
    return 0
end

function self_exe():
    path = ""
    safe:
        path = glib.readlink("/proc/self/exe")
    end
    if path.endswith(" (deleted)"):
        path = path[0:len(path) - 10]
    end
    if path == "":
        path = "luxos-mail"
    end
    return path
end

# ---- spojeni se sluzbou -----------------------------------------------------------------------------------------

function service_socket():
    return store.socket_name("")
end

function svc_connect():
    fd = luxos_sys.unix_connect(service_socket())
    if fd < 0:
        return False
    end
    ui["svc_fd"] = fd
    ui["svc_buf"] = ByteArray()
    ui["connecting"] = False
    ui["tries"] = 0
    call glib.fd_add_data(fd, 1 + 8 + 16, on_svc_data, fd)
    queued = ui["outbox"]
    ui["outbox"] = []
    call request("hello", {}, {})
    for msg in queued:
        call mb.send(fd, json.encode(msg) + "\n")
    end
    return True
end

function ensure_service():
    if ui["svc_fd"] >= 0 or ui["connecting"]:
        return 0
    end
    if svc_connect():
        return 0
    end
    ui["connecting"] = True
    ui["tries"] = 0
    call glib.spawn_quiet([store.service_binary()])
    call glib.timeout_add(150, on_svc_retry)
    return 0
end

function on_svc_retry():
    if svc_connect():
        return False
    end
    ui["tries"] = ui["tries"] + 1
    if ui["tries"] > 60:
        ui["connecting"] = False
        call log("the background service did not start")
        return False
    end
    return True
end

function request(op, fields, ctx):
    id = ui["next_id"]
    ui["next_id"] = id + 1
    msg = {}
    for k in fields.keys():
        msg[k] = fields[k]
    end
    msg["id"] = id
    msg["op"] = op
    c = {}
    for k in ctx.keys():
        c[k] = ctx[k]
    end
    c["op"] = op
    ui["pending"][id] = c
    if ui["svc_fd"] < 0:
        ui["outbox"].append(msg)
        call ensure_service()
        return id
    end
    if not mb.send(ui["svc_fd"], json.encode(msg) + "\n"):
        call svc_lost()
        ui["outbox"].append(msg)
        call ensure_service()
    end
    return id
end

function svc_lost():
    if ui["svc_fd"] >= 0:
        call luxos_sys.close(ui["svc_fd"])
    end
    ui["svc_fd"] = -1
    return 0
end

function on_svc_data(fd, handle, condition):
    if ui["svc_fd"] != fd:
        return False
    end
    data = mb.recv(fd, 262144)
    if data == False:
        return True
    end
    if len(data) == 0:
        call svc_lost()
        # sluzba skoncila (aktualizace, chyba): znovu spustit, cekajici pozadavky selhaly
        for id in list_keys(ui["pending"]):
            ctx = ui["pending"].pop(id)
            call on_reply({"ok": False, "kind": "service", "error": i18n.T("The mail service stopped.")}, ctx)
        end
        call glib.timeout_add(1000, on_svc_restart)
        return False
    end
    ui["svc_buf"] = mb.concat(ui["svc_buf"], data)
    loop:
        buf = ui["svc_buf"]
        nl = mb.find_byte(buf, 10, 0, len(buf))
        if nl < 0:
            break
        end
        line = net.text(buf, 0, nl)
        ui["svc_buf"] = mb.sub(buf, nl + 1, len(buf))
        msg = None
        safe:
            msg = json.decode(line)
        end
        if type(msg) != "Dictionary":
            continue
        end
        if "event" in msg:
            call on_event(msg)
            continue
        end
        id = msg.get("id", 0)
        if id in ui["pending"]:
            ctx = ui["pending"].pop(id)
            call on_reply(msg, ctx)
        end
    end
    return True
end

function on_svc_restart():
    call ensure_service()
    return False
end

function list_keys(d):
    out = []
    for k in d.keys():
        out.append(k)
    end
    return out
end

# ---- pomucky --------------------------------------------------------------------------------------------------

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

function tool_button(names, tooltip, handler):
    b = gtk.button_new_empty()
    call gtk.button_set_image(b, icon(names, 2))
    call gtk.button_set_relief(b, gtk.RELIEF_NONE)
    call gtk.widget_set_tooltip(b, tooltip)
    call gtk.accessible_name(b, tooltip)
    call gtk.connect(b, "clicked", handler)
    return b
end

function clear_container(box):
    for child in gtk.container_get_children(box):
        call gtk.widget_destroy(child)
    end
    return 0
end

function account(id):
    for a in ui["accounts"]:
        if a["id"] == id:
            return a
        end
    end
    return {}
end

function role_name(role, name, delim):
    if role == "inbox":
        return i18n.T("Inbox")
    elif role == "sent":
        return i18n.T("Sent")
    elif role == "drafts":
        return i18n.T("Drafts")
    elif role == "trash":
        return i18n.T("Trash")
    elif role == "junk":
        return i18n.T("Junk")
    elif role == "archive":
        return i18n.T("Archive")
    elif role == "all":
        return i18n.T("All Mail")
    elif role == "starred":
        return i18n.T("Starred")
    elif role == "important":
        return i18n.T("Important")
    end
    leaf = name
    if delim != "":
        p = leaf.find(delim)
        while p >= 0:
            leaf = leaf[p + len(delim):]
            p = leaf.find(delim)
        end
    end
    return leaf
end

function size_text(n):
    return glib.format_size(n)
end

function day_number(t):
    lt = glib.localtime(t)
    return mime.days_from_civil(lt[0], lt[1], lt[2])
end

function short_date(t):
    if t <= 0:
        return ""
    end
    diff = day_number(glib.now()) - day_number(t)
    if diff == 0:
        return glib.format_unix(t, "%H:%M")
    elif diff == 1:
        return i18n.T("Yesterday")
    elif diff > 1 and diff < 7:
        return glib.format_unix(t, "%A")
    end
    return glib.format_unix(t, "%x")
end

function long_date(t):
    if t <= 0:
        return ""
    end
    return glib.format_unix(t, "%x %H:%M")
end

function addresses_text(list):
    out = []
    for a in list:
        out.append(mime.address_full(a))
    end
    return ", ".join(out)
end

# ---- okno -----------------------------------------------------------------------------------------------------

function build_window():
    win = gtk.window_new(i18n.T("Mail"))
    ui["window"] = win
    call gtk.window_set_wmclass(win, "luxos-mail", "luxos-mail")
    call gtk.window_set_icon_list(win, "luxos-mail")
    call gtk.window_set_default_size(win, 1180, 740)
    root = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.container_add(win, root)

    bar = gtk.box_new(gtk.HORIZONTAL, 4)
    call gtk.widget_add_class(bar, "toolbar")
    call gtk.box_pack_start(bar, tool_button(["mail-send-receive-symbolic", "view-refresh-symbolic"], i18n.T("Get Mail (F5)"), on_refresh_clicked), False, False, 0)
    call gtk.box_pack_start(bar, tool_button(["mail-message-new-symbolic", "document-new-symbolic"], i18n.T("New Message (Ctrl+N)"), on_compose_clicked), False, False, 0)
    call gtk.box_pack_start(bar, gtk.separator_new(gtk.VERTICAL), False, False, 6)
    rb = tool_button(["mail-unread-symbolic", "mail-read-symbolic"], i18n.T("Mark as Read/Unread (Ctrl+Shift+U)"), on_read_clicked)
    ui["read_button"] = rb
    call gtk.box_pack_start(bar, rb, False, False, 0)
    db = tool_button(["user-trash-symbolic"], i18n.T("Move to Trash (Delete)"), on_delete_clicked)
    ui["delete_button"] = db
    call gtk.box_pack_start(bar, db, False, False, 0)
    call gtk.box_pack_start(bar, gtk.separator_new(gtk.VERTICAL), False, False, 6)
    r1 = tool_button(["mail-reply-sender-symbolic", "mail-reply-symbolic"], i18n.T("Reply (Ctrl+R)"), on_reply_clicked)
    r2 = tool_button(["mail-reply-all-symbolic"], i18n.T("Reply All (Ctrl+Shift+R)"), on_reply_all_clicked)
    r3 = tool_button(["mail-forward-symbolic"], i18n.T("Forward (Ctrl+Shift+F)"), on_forward_clicked)
    for b in [r1, r2, r3]:
        call gtk.box_pack_start(bar, b, False, False, 0)
    end
    ui["reply_buttons"] = [r1, r2, r3]
    spinner = mg.spinner_new()
    ui["spinner"] = spinner
    call gtk.box_pack_start(bar, spinner, False, False, 8)
    search = gtk.search_entry_new()
    call gtk.entry_set_placeholder_text(search, i18n.T("Filter (Ctrl+F)"))
    call gtk.entry_set_width_chars(search, 26)
    call gtk.connect(search, "search-changed", on_search)
    ui["search"] = search
    call gtk.box_pack_end(bar, search, False, False, 0)
    menu_button = tool_button(["open-menu-symbolic"], i18n.T("Menu (F10)"), on_menu_clicked)
    ui["menu_button"] = menu_button
    call gtk.box_pack_end(bar, menu_button, False, False, 4)
    call gtk.box_pack_start(root, bar, False, False, 0)

    stack = mg.stack_new()
    ui["outer"] = stack
    call gtk.box_pack_start(root, stack, True, True, 0)

    # uvitani bez uctu
    welcome = gtk.box_new(gtk.VERTICAL, 12)
    call gtk.widget_set_valign(welcome, gtk.ALIGN_CENTER)
    call gtk.widget_set_halign(welcome, gtk.ALIGN_CENTER)
    image = gtk.image_new_from_icon_name("luxos-mail", 6)
    call gtk.image_set_pixel_size(image, 96)
    call gtk.box_pack_start(welcome, image, False, False, 0)
    wt = gtk.label_new(i18n.T("Welcome to Mail"))
    call gtk.widget_add_class(wt, "welcome-title")
    call gtk.box_pack_start(welcome, wt, False, False, 0)
    ws = gtk.label_new(i18n.T("Add your email account to read your mail and get notified about new messages."))
    call gtk.widget_add_class(ws, "dim")
    call gtk.label_set_line_wrap(ws, True)
    call gtk.label_set_max_width_chars(ws, 50)
    call gtk.label_set_justify(ws, 2)
    call gtk.box_pack_start(welcome, ws, False, False, 0)
    # ucet LuxAI tohoto pocitace (zobrazi update_welcome)
    lbox = gtk.box_new(gtk.VERTICAL, 4)
    call gtk.widget_set_no_show_all(lbox, True)
    lb = gtk.button_new(i18n.T("Continue"))
    call gtk.widget_add_class(lb, "suggested-action")
    call gtk.widget_set_halign(lb, gtk.ALIGN_CENTER)
    call gtk.connect(lb, "clicked", on_luxai_clicked)
    call gtk.box_pack_start(lbox, lb, False, False, 0)
    lsub = gtk.label_new("")
    call gtk.widget_add_class(lsub, "dim")
    call gtk.widget_add_class(lsub, "small")
    call gtk.box_pack_start(lbox, lsub, False, False, 0)
    call gtk.box_pack_start(welcome, lbox, False, False, 8)
    ui["welcome_luxai"] = lbox
    ui["luxai_button"] = lb
    ui["luxai_sub"] = lsub
    add = gtk.button_new(i18n.T("Add Account…"))
    call gtk.widget_set_halign(add, gtk.ALIGN_CENTER)
    call gtk.connect(add, "clicked", on_welcome_add_clicked)
    call gtk.box_pack_start(welcome, add, False, False, 4)
    call gtk.widget_set_can_default(add, True)
    ui["welcome_button"] = add
    call mg.stack_add(stack, welcome, "welcome")

    mainp = mg.paned_new(gtk.HORIZONTAL)
    call mg.stack_add(stack, mainp, "main")
    side_scroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(side_scroll, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    call gtk.widget_add_class(side_scroll, "sidebar")
    side = gtk.list_box_new()
    call gtk.list_box_set_selection_mode(side, 1)
    call gtk.connect(side, "row-selected", on_side_selected)
    call gtk.connect(side, "row-activated", on_side_activated)
    ui["sidebar"] = side
    call gtk.container_add(side_scroll, side)
    call gtk.widget_set_size_request(side_scroll, 180, -1)
    call mg.paned_pack1(mainp, side_scroll, False, False)

    right = mg.paned_new(gtk.HORIZONTAL)
    call mg.paned_pack2(mainp, right, True, False)
    call mg.paned_set_position(mainp, 220)

    column = gtk.box_new(gtk.VERTICAL, 0)
    head = gtk.box_new(gtk.VERTICAL, 2)
    call gtk.widget_add_class(head, "list-head")
    lt = label("", "list-title")
    call gtk.label_set_ellipsize(lt, 3)
    ui["list_title"] = lt
    ls = label("", "dim small")
    ui["list_sub"] = ls
    call gtk.box_pack_start(head, lt, False, False, 0)
    call gtk.box_pack_start(head, ls, False, False, 0)
    call gtk.box_pack_start(column, head, False, False, 0)
    banner = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_add_class(banner, "banner")
    bl = label("", "small")
    call gtk.label_set_line_wrap(bl, True)
    ui["banner_label"] = bl
    call gtk.box_pack_start(banner, bl, True, True, 0)
    bb = gtk.button_new(i18n.T("Try Again"))
    call gtk.widget_set_valign(bb, gtk.ALIGN_CENTER)
    call gtk.connect(bb, "clicked", on_banner_clicked)
    ui["banner_button"] = bb
    call gtk.box_pack_end(banner, bb, False, False, 0)
    call gtk.widget_set_no_show_all(banner, True)
    ui["banner"] = banner
    call gtk.box_pack_start(column, banner, False, False, 0)
    scroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(scroll, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    ui["list_scroll"] = scroll
    call glib.signal_connect(scroll, "edge-reached", on_edge, 1)
    mlist = gtk.list_box_new()
    call gtk.list_box_set_selection_mode(mlist, 1)
    call mg.list_box_set_activate_on_single_click(mlist, False)
    call gtk.connect(mlist, "row-selected", on_message_selected)
    call gtk.connect(mlist, "row-activated", on_message_activated)
    empty = gtk.label_new(i18n.T("No messages"))
    call gtk.widget_add_class(empty, "empty")
    call gtk.widget_show(empty)
    call mg.list_box_set_placeholder(mlist, empty)
    ui["list"] = mlist
    call gtk.container_add(scroll, mlist)
    call gtk.box_pack_start(column, scroll, True, True, 0)
    call gtk.widget_set_size_request(column, 280, -1)
    call mg.paned_pack1(right, column, False, False)
    call mg.paned_set_position(right, 390)

    view = mg.stack_new()
    ui["view"] = view
    nothing = gtk.label_new(i18n.T("No Message Selected"))
    call gtk.widget_add_class(nothing, "empty")
    call mg.stack_add(view, nothing, "empty")
    page = gtk.box_new(gtk.VERTICAL, 0)
    mh = gtk.box_new(gtk.VERTICAL, 3)
    call gtk.widget_add_class(mh, "msg-head")
    subj = label("", "msg-subject")
    call gtk.label_set_line_wrap(subj, True)
    call gtk.label_set_selectable(subj, True)
    ui["h_subject"] = subj
    call gtk.box_pack_start(mh, subj, False, False, 4)
    top = gtk.box_new(gtk.HORIZONTAL, 8)
    hf = label("", "msg-from")
    call gtk.label_set_selectable(hf, True)
    call gtk.label_set_ellipsize(hf, 3)
    ui["h_from"] = hf
    call gtk.box_pack_start(top, hf, True, True, 0)
    hd = label("", "dim small")
    ui["h_date"] = hd
    call gtk.box_pack_end(top, hd, False, False, 0)
    call gtk.box_pack_start(mh, top, False, False, 0)
    ht = label("", "dim small")
    call gtk.label_set_selectable(ht, True)
    call gtk.label_set_line_wrap(ht, True)
    ui["h_to"] = ht
    call gtk.box_pack_start(mh, ht, False, False, 0)
    hc = label("", "dim small")
    call gtk.label_set_selectable(hc, True)
    call gtk.label_set_line_wrap(hc, True)
    call gtk.widget_set_no_show_all(hc, True)
    ui["h_cc"] = hc
    call gtk.box_pack_start(mh, hc, False, False, 0)
    hn = label("", "dim small")
    call gtk.widget_set_no_show_all(hn, True)
    ui["h_note"] = hn
    call gtk.box_pack_start(mh, hn, False, False, 0)
    call gtk.box_pack_start(page, mh, False, False, 0)
    att_bar = gtk.box_new(gtk.HORIZONTAL, 6)
    call gtk.widget_add_class(att_bar, "att-bar")
    call gtk.widget_set_no_show_all(att_bar, True)
    ui["att_bar"] = att_bar
    call gtk.box_pack_start(page, att_bar, False, False, 0)
    # vzdalene obrazky skryte: Nacist obrazky / Vzdy od odesilatele
    ib = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_add_class(ib, "view-bar")
    il = label(i18n.T("Remote images are hidden to protect your privacy."), "small")
    call gtk.label_set_line_wrap(il, True)
    call gtk.box_pack_start(ib, il, True, True, 0)
    ui["images_label"] = il
    lb = gtk.button_new(i18n.T("Load Images"))
    call gtk.connect(lb, "clicked", on_load_images)
    call gtk.box_pack_end(ib, lb, False, False, 0)
    ab = gtk.button_new(i18n.T("Always"))
    call gtk.button_set_relief(ab, gtk.RELIEF_NONE)
    call gtk.connect(ab, "clicked", on_always_images)
    ui["images_always"] = ab
    call gtk.box_pack_end(ib, ab, False, False, 0)
    call gtk.widget_set_no_show_all(ib, True)
    ui["images_bar"] = ib
    call gtk.box_pack_start(page, ib, False, False, 0)
    # hledani v textu zpravy (Ctrl+F ve zprave)
    fb = gtk.box_new(gtk.HORIZONTAL, 4)
    call gtk.widget_add_class(fb, "view-bar")
    fe = gtk.search_entry_new()
    call gtk.entry_set_placeholder_text(fe, i18n.T("Find in Message"))
    call gtk.entry_set_width_chars(fe, 28)
    call gtk.accessible_name(fe, i18n.T("Find in Message"))
    call gtk.connect(fe, "search-changed", on_find_changed)
    call gtk.connect(fe, "activate", on_find_next)
    ui["find_entry"] = fe
    call gtk.box_pack_start(fb, fe, False, False, 0)
    call gtk.box_pack_start(fb, tool_button(["go-up-symbolic"], i18n.T("Previous (Shift+Enter)"), on_find_prev), False, False, 0)
    call gtk.box_pack_start(fb, tool_button(["go-down-symbolic"], i18n.T("Next (Enter)"), on_find_next), False, False, 0)
    call gtk.box_pack_end(fb, tool_button(["window-close-symbolic"], i18n.T("Close (Esc)"), on_find_close), False, False, 0)
    call gtk.widget_set_no_show_all(fb, True)
    ui["find_bar"] = fb
    call gtk.box_pack_start(page, fb, False, False, 0)
    body_stack = mg.stack_new()
    ui["body_stack"] = body_stack
    ts = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(ts, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    ui["text_scroll"] = ts
    tv = mg.text_view_new()
    call gtk.widget_add_class(tv, "body")
    call mg.text_view_set_margins(tv, 22, 22, 14, 22)
    ui["text"] = tv
    call gtk.container_add(ts, tv)
    call mg.stack_add(body_stack, ts, "text")
    call gtk.box_pack_start(page, body_stack, True, True, 0)
    call mg.stack_add(view, page, "message")
    call mg.paned_pack2(right, view, True, False)

    call gtk.connect(win, "key-press-event", on_key)
    call gtk.connect(win, "delete-event", on_delete_event)
    return win
end

# ---- schranky (levy sloupec) ----------------------------------------------------------------------------------------

function sorted_boxes(boxes):
    # klic textem (sort umi jen cisla a texty): poradi role, pak cesta (podslozky za nadrazenou)
    by_key = {}
    keys = []
    for b in boxes:
        if b["raw"] == "INBOX" and b["role"] == "":
            b["role"] = "inbox"
        end
        key = String(ROLE_ORDER.get(b["role"], 9)) + "\t" + b["name"].lower() + "\t" + b["raw"]
        by_key[key] = b
        keys.append(key)
    end
    keys.sort()
    out = []
    for k in keys:
        out.append(by_key[k])
    end
    return out
end

# Odsazeni podslozky: pocet zobrazenych nadrazenych schranek (Gmail "[Gmail]/Important" pod skrytou
# "[Gmail]" (\Noselect) neodsazovat)
function box_depth(b, shown):
    if b["delim"] == "" or b["role"] != "":
        return 0
    end
    parts = b["raw"].split(b["delim"])
    depth = 0
    prefix = ""
    for i in range(len(parts) - 1):
        if i == 0:
            prefix = parts[0]
        else:
            prefix = prefix + b["delim"] + parts[i]
        end
        if prefix in shown and prefix != "INBOX":
            depth += 1
        end
    end
    return depth
end

function side_row_widget(b, account_id, depth=0):
    box = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_margins(box, 2 + depth * 14, 2, 2, 2)
    call gtk.box_pack_start(box, icon(ROLE_ICONS.get(b["role"], ROLE_ICONS[""]), 1), False, False, 0)
    name = label(role_name(b["role"], b["name"], b["delim"]), "")
    call gtk.label_set_ellipsize(name, 3)
    call gtk.box_pack_start(box, name, True, True, 0)
    if b.get("unseen", 0) > 0 and b["role"] != "trash" and b["role"] != "junk" and b["role"] != "sent" and b["role"] != "drafts":
        call gtk.box_pack_end(box, label(String(b["unseen"]), "side-count"), False, False, 0)
    end
    return box
end

function build_sidebar():
    ui["building"] = True
    side = ui["sidebar"]
    call clear_container(side)
    rows = []
    selected = -1
    cur = ui["current"]
    jobs = outbox_jobs()
    if len(jobs) > 0:
        failed = 0
        for j in jobs:
            if j.get("state", "") == "failed":
                failed += 1
            end
        end
        ob = {"raw": "__outbox__", "name": i18n.T("Outbox"), "delim": "", "role": "outbox", "unseen": len(jobs)}
        w = side_row_widget(ob, "")
        if failed > 0:
            warn = icon(["dialog-warning-symbolic"], 1)
            call gtk.widget_add_class(warn, "side-error")
            call gtk.widget_set_tooltip(warn, i18n.T("Some messages could not be sent."))
            call gtk.box_pack_end(w, warn, False, False, 0)
        end
        call gtk.list_box_insert(side, w, -1)
        if cur["raw"] == "__outbox__":
            selected = 0
        end
        rows.append({"account": "", "raw": "__outbox__", "role": "outbox", "name": i18n.T("Outbox"), "unseen": len(jobs), "total": len(jobs)})
    end
    for a in ui["accounts"]:
        title = a.get("name", "")
        if title == "":
            title = a["email"]
        end
        head = gtk.box_new(gtk.HORIZONTAL, 6)
        hl = label(title.upper(), "side-header")
        call gtk.label_set_ellipsize(hl, 3)
        call gtk.box_pack_start(head, hl, True, True, 0)
        st = ui["status"].get(a["id"], {})
        if st.get("state", "") == "error" or (st.get("state", "") == "offline" and st.get("kind", "") != ""):
            warn = icon(["dialog-warning-symbolic"], 1)
            call gtk.widget_add_class(warn, "side-error")
            call gtk.widget_set_tooltip(warn, error_text(st))
            call gtk.box_pack_end(head, warn, False, False, 0)
        end
        call gtk.list_box_insert(side, head, -1)
        r = mg.list_box_get_row_at_index(side, len(rows))
        call mg.list_box_row_set_selectable(r, False)
        call mg.list_box_row_set_activatable(r, False)
        rows.append({"header": a["id"]})
        boxes = sorted_boxes(store.load_mailboxes(a["id"]))
        shown = {}
        hidden = []
        for b in boxes:
            if b.get("selectable", True):
                shown[b["raw"]] = True
                if b["role"] in HIDDEN_ROLES:
                    hidden.append(b)
                end
            end
        end
        if cur["account"] == a["id"] and cur.get("role", "") in HIDDEN_ROLES:
            ui["more"][a["id"]] = True
        end
        more = ui["more"].get(a["id"], False)
        for b in boxes:
            if not b.get("selectable", True) or (b["role"] in HIDDEN_ROLES and not more):
                continue
            end
            call gtk.list_box_insert(side, side_row_widget(b, a["id"], box_depth(b, shown)), -1)
            if cur["account"] == a["id"] and cur["raw"] == b["raw"]:
                selected = len(rows)
            end
            rows.append({"account": a["id"], "raw": b["raw"], "role": b["role"], "name": role_name(b["role"], b["name"], b["delim"]), "unseen": b.get("unseen", 0), "total": b.get("total", 0)})
        end
        if len(hidden) > 0:
            # "Dalsi" / "Mene": Enter nebo klepnuti (radek se nevybira, jen aktivuje)
            mb_box = gtk.box_new(gtk.HORIZONTAL, 8)
            call gtk.widget_set_margins(mb_box, 2, 2, 2, 2)
            arrow = ["pan-end-symbolic", "go-next-symbolic"]
            text = i18n.T("More")
            if more:
                arrow = ["pan-down-symbolic", "go-down-symbolic"]
                text = i18n.T("Less")
            end
            call gtk.box_pack_start(mb_box, icon(arrow, 1), False, False, 0)
            ml = label(text, "dim")
            call gtk.box_pack_start(mb_box, ml, True, True, 0)
            call gtk.widget_set_tooltip(mb_box, i18n.T("All Mail, Starred and Important (Gmail)"))
            call gtk.list_box_insert(side, mb_box, -1)
            r = mg.list_box_get_row_at_index(side, len(rows))
            call mg.list_box_row_set_selectable(r, False)
            rows.append({"more": a["id"]})
        end
        if len(rows) == 1 or rows[len(rows) - 1].get("header", "") == a["id"]:
            # ucet jeste bez seznamu schranek (prvni synchronizace): aspon Dorucena posta
            b = {"raw": "INBOX", "name": "INBOX", "delim": "", "role": "inbox", "unseen": 0}
            call gtk.list_box_insert(side, side_row_widget(b, a["id"]), -1)
            if cur["account"] == a["id"] and cur["raw"] == "INBOX":
                selected = len(rows)
            end
            rows.append({"account": a["id"], "raw": "INBOX", "role": "inbox", "name": i18n.T("Inbox"), "unseen": 0, "total": 0})
        end
    end
    ui["side_rows"] = rows
    call gtk.widget_show_all(side)
    if selected >= 0:
        call mg.list_box_select_row(side, mg.list_box_get_row_at_index(side, selected))
    end
    ui["building"] = False
    return selected
end

function on_side_activated(row, box):
    if row == 0:
        return 0
    end
    index = gtk.list_box_row_get_index(row)
    if index < 0 or index >= len(ui["side_rows"]):
        return 0
    end
    item = ui["side_rows"][index]
    if "more" in item:
        id = item["more"]
        ui["more"][id] = not ui["more"].get(id, False)
        if not ui["more"][id] and ui["current"]["account"] == id and ui["current"].get("role", "") in HIDDEN_ROLES:
            ui["more"][id] = True                  # otevrena skryta schranka zustava videt
        end
        call build_sidebar()
        # fokus zpet na radek Dalsi/Mene (klavesnice)
        i = 0
        for it in ui["side_rows"]:
            if it.get("more", "") == id:
                r = mg.list_box_get_row_at_index(ui["sidebar"], i)
                if r != 0:
                    call gtk.widget_grab_focus(r)
                end
            end
            i += 1
        end
    end
    return 0
end

function on_side_selected(row, box):
    if ui["building"] or row == 0:
        return 0
    end
    index = gtk.list_box_row_get_index(row)
    if index < 0 or index >= len(ui["side_rows"]):
        return 0
    end
    item = ui["side_rows"][index]
    if "header" in item or "more" in item:
        return 0
    end
    call open_mailbox(item["account"], item["raw"], 0)
    return 0
end

function select_side(account_id, raw):
    i = 0
    for item in ui["side_rows"]:
        if item.get("account", "") == account_id and item.get("raw", "") == raw:
            ui["building"] = True
            call mg.list_box_select_row(ui["sidebar"], mg.list_box_get_row_at_index(ui["sidebar"], i))
            ui["building"] = False
            return True
        end
        i += 1
    end
    return False
end

# ---- seznam zprav ---------------------------------------------------------------------------------------------

function current_item():
    cur = ui["current"]
    for item in ui["side_rows"]:
        if item.get("account", "") == cur["account"] and item.get("raw", "") == cur["raw"]:
            return item
        end
    end
    return {}
end

function open_mailbox(account_id, raw, uid):
    role = ""
    name = raw
    for item in ui["side_rows"]:
        if item.get("account", "") == account_id and item.get("raw", "") == raw:
            role = item["role"]
            name = item["name"]
        end
    end
    if raw == "__outbox__":
        role = "outbox"
        name = i18n.T("Outbox")
    end
    ui["current"] = {"account": account_id, "raw": raw, "role": role, "name": name}
    ui["selected"] = 0
    call gtk.entry_set_text(ui["search"], "")
    ui["filter"] = ""
    call load_rows()
    call build_list(uid)
    call update_banner()
    call mg.stack_show(ui["view"], "empty")
    if uid > 0:
        call select_uid(uid)
    end
    if raw == "__outbox__":
        return 0
    end
    call set_busy(True)
    call request("sync", {"account": account_id, "mailbox": raw}, {"account": account_id, "mailbox": raw})
    return 0
end

function load_rows():
    cur = ui["current"]
    if cur["raw"] == "__outbox__":
        ui["rows"] = outbox_rows()
    elif cur["account"] == "":
        ui["rows"] = []
    else:
        ui["rows"] = store.load_index(cur["account"], cur["raw"])
    end
    call apply_filter()
    return 0
end

function apply_filter():
    f = ui["filter"].lower()
    if f == "":
        ui["shown"] = ui["rows"]
        return 0
    end
    out = []
    for m in ui["rows"]:
        hay = (m["from_name"] + " " + m["from_email"] + " " + m["subject"] + " " + m["preview"] + " " + m["to"]).lower()
        if hay.find(f) >= 0:
            out.append(m)
        end
    end
    ui["shown"] = out
    return 0
end

function update_title():
    item = current_item()
    name = ui["current"]["name"]
    unread = 0
    for m in ui["rows"]:
        if m["flags"].find("S") < 0:
            unread += 1
        end
    end
    call gtk.label_set_text(ui["list_title"], name)
    if name == "":
        call gtk.window_set_title(ui["window"], i18n.T("Mail"))
    end
    a = account(ui["current"]["account"])
    sub = a.get("email", "")
    if unread > 0:
        sub = i18n.TF("Unread: %d", [unread]) + " · " + sub
    end
    if ui["filter"] != "":
        sub = i18n.TF("%d found", [len(ui["shown"])]) + " · " + sub
    end
    call gtk.label_set_text(ui["list_sub"], sub)
    if name != "":
        call gtk.window_set_title(ui["window"], name + " – " + i18n.T("Mail"))
    end
    return 0
end

function message_row(m):
    unread = m["flags"].find("S") < 0
    outer = gtk.box_new(gtk.HORIZONTAL, 4)
    call gtk.widget_add_class(outer, "msg-row")
    dot_text = " "
    if unread:
        dot_text = "●"
    end
    dot = gtk.label_new(dot_text)
    call gtk.widget_add_class(dot, "unread-dot")
    call gtk.widget_set_valign(dot, gtk.ALIGN_START)
    call gtk.box_pack_start(outer, dot, False, False, 0)
    col = gtk.box_new(gtk.VERTICAL, 2)
    top = gtk.box_new(gtk.HORIZONTAL, 6)
    who = m["from_name"]
    if who == "":
        who = m["from_email"]
    end
    role = ui["current"]["role"]
    if (role == "sent" or role == "drafts" or role == "outbox") and m["to"] != "":
        who = i18n.TF("To: %s", [m["to"]])
    end
    sender = label(who, "sender")
    if unread:
        call gtk.widget_add_class(sender, "unread")
    end
    call gtk.label_set_ellipsize(sender, 3)
    call gtk.box_pack_start(top, sender, True, True, 0)
    if m["flags"].find("F") >= 0:
        call gtk.box_pack_end(top, label("★", "flagged"), False, False, 0)
    end
    call gtk.box_pack_end(top, label(short_date(m["internal"]), "dim small"), False, False, 0)
    if m["att"]:
        call gtk.box_pack_end(top, icon(["mail-attachment-symbolic"], 1), False, False, 0)
    end
    call gtk.box_pack_start(col, top, False, False, 0)
    subject = m["subject"]
    if subject == "":
        subject = i18n.T("(no subject)")
    end
    sl = label(subject, "subject")
    call gtk.label_set_ellipsize(sl, 3)
    call gtk.box_pack_start(col, sl, False, False, 0)
    if m["preview"] != "":
        pl = label(m["preview"], "preview")
        call gtk.label_set_line_wrap(pl, True)
        call mg.label_set_lines(pl, 2)
        call gtk.label_set_ellipsize(pl, 3)
        call gtk.label_set_width_chars(pl, 20)
        call gtk.label_set_max_width_chars(pl, 60)
        call gtk.box_pack_start(col, pl, False, False, 0)
    end
    call gtk.box_pack_start(outer, col, True, True, 0)
    ui["widgets"][m["uid"]] = [dot, sender]
    return outer
end

# Seznam od zacatku (prvnich PAGE zprav, dalsi pri posunu dolu); vybere zpravu uid (0 = zadnou)
function build_list(uid):
    ui["building"] = True
    mlist = ui["list"]
    call clear_container(mlist)
    ui["row_index"] = {}
    ui["widgets"] = {}
    ui["built"] = 0
    ui["older_row"] = 0
    need = PAGE
    if uid > 0:
        i = 0
        for m in ui["shown"]:
            if m["uid"] == uid:
                need = max(PAGE, i + 20)
                break
            end
            i += 1
        end
    end
    call extend_list(need)
    ui["building"] = False
    call update_title()
    return 0
end

function extend_list(count):
    mlist = ui["list"]
    if ui["older_row"] != 0:
        call gtk.widget_destroy(ui["older_row"])
        ui["older_row"] = 0
    end
    start = ui["built"]
    stop = min(len(ui["shown"]), start + count)
    i = start
    while i < stop:
        m = ui["shown"][i]
        call gtk.list_box_insert(mlist, message_row(m), -1)
        row = mg.list_box_get_row_at_index(mlist, i)
        ui["row_index"][row] = m["uid"]
        i += 1
    end
    ui["built"] = stop
    if stop >= len(ui["shown"]) and ui["filter"] == "" and ui["current"]["account"] != "":
        st = store.load_state(ui["current"]["account"], ui["current"]["raw"])
        if st.get("oldest", 0) > 1 and st.get("exists", 0) > len(ui["rows"]):
            b = gtk.button_new(i18n.T("Load Older Messages"))
            call gtk.button_set_relief(b, gtk.RELIEF_NONE)
            call gtk.connect(b, "clicked", on_older_clicked)
            call gtk.list_box_insert(mlist, b, -1)
            row = mg.list_box_get_row_at_index(mlist, stop)
            call mg.list_box_row_set_selectable(row, False)
            ui["older_row"] = row
        end
    end
    call gtk.widget_show_all(mlist)
    return 0
end

function on_edge(position, scrolled):
    # GTK_POS_BOTTOM = 3
    if position == 3 and ui["built"] < len(ui["shown"]):
        call extend_list(PAGE)
    end
    return 0
end

function on_older_clicked(button):
    call gtk.widget_set_sensitive(button, False)
    call set_busy(True)
    cur = ui["current"]
    call request("older", {"account": cur["account"], "mailbox": cur["raw"]}, {"account": cur["account"], "mailbox": cur["raw"]})
    return 0
end

function row_for_uid(uid):
    for row in ui["row_index"].keys():
        if ui["row_index"][row] == uid:
            return row
        end
    end
    return 0
end

function select_uid(uid, focus=True):
    row = row_for_uid(uid)
    if row == 0:
        i = 0
        for m in ui["shown"]:
            if m["uid"] == uid:
                call extend_list(i + 10 - ui["built"])
                row = row_for_uid(uid)
                break
            end
            i += 1
        end
    end
    if row != 0:
        call mg.list_box_select_row(ui["list"], row)
        if focus:
            call gtk.widget_grab_focus(row)
        end
        return True
    end
    return False
end

function find_row(uid):
    for m in ui["rows"]:
        if m["uid"] == uid:
            return m
        end
    end
    return {}
end

function on_message_selected(row, box):
    if ui["building"]:
        return 0
    end
    if row == 0 or row not in ui["row_index"]:
        ui["selected"] = 0
        call mg.stack_show(ui["view"], "empty")
        return 0
    end
    uid = ui["row_index"][row]
    if uid == ui["selected"]:
        return 0
    end
    ui["selected"] = uid
    call show_message(find_row(uid))
    return 0
end

function on_message_activated(row, box):
    role = ui["current"]["role"]
    if role == "drafts" and message_shown():
        call edit_draft()
        return 0
    end
    if ui["current"]["raw"] == "__outbox__":
        call outbox_edit()
        return 0
    end
    if ui["web"] != 0 and message_shown():
        call web_focus()
    else:
        call gtk.widget_grab_focus(ui["text"])
    end
    return 0
end

# ---- zobrazeni zpravy -------------------------------------------------------------------------------------------

function show_headers(subject, sender, to, cc, date):
    if subject == "":
        subject = i18n.T("(no subject)")
    end
    call gtk.label_set_text(ui["h_subject"], subject)
    call gtk.label_set_text(ui["h_from"], sender)
    call gtk.label_set_text(ui["h_date"], long_date(date))
    if to != "":
        call gtk.label_set_text(ui["h_to"], i18n.T("To:") + " " + to)
    else:
        call gtk.label_set_text(ui["h_to"], "")
    end
    if cc != "":
        call gtk.label_set_text(ui["h_cc"], i18n.T("Cc:") + " " + cc)
        call gtk.widget_show(ui["h_cc"])
    else:
        call gtk.widget_hide(ui["h_cc"])
    end
    return 0
end

function show_message(m):
    if len(m) == 0:
        return 0
    end
    cur = ui["current"]
    call mg.stack_show(ui["view"], "message")
    sender = m["from_name"]
    if m["from_email"] != "":
        if sender != "":
            sender = sender + " <" + m["from_email"] + ">"
        else:
            sender = m["from_email"]
        end
    end
    call show_headers(m["subject"], sender, m["to"], "", m["date"])
    call gtk.widget_hide(ui["h_note"])
    call clear_container(ui["att_bar"])
    call gtk.widget_hide(ui["att_bar"])
    ui["view_remote"] = False
    ui["message"] = {}
    call trace("show " + m["subject"])
    if cur["raw"] == "__outbox__":
        call show_outbox_banner()
        job = outbox_job()
        if len(job) > 0:
            call render_body(m["uid"], outbox_dir() + "/" + job["id"] + ".eml")
        end
        return 0
    end
    path = store.body_path(cur["account"], cur["raw"], m["uid"])
    if exists(path):
        call render_body(m["uid"], path)
    else:
        call mg.text_view_set_text(ui["text"], i18n.T("Loading…"))
        call set_busy(True)
        call request("body", {"account": cur["account"], "mailbox": cur["raw"], "uid": m["uid"]}, {"account": cur["account"], "mailbox": cur["raw"], "uid": m["uid"]})
    end
    if m["flags"].find("S") < 0:
        call set_read(m, True)
    end
    return 0
end

function render_body(uid, path):
    data = ByteArray()
    r = {}
    ok = True
    try:
        data = readbytes(path)
        r = mime.render(data)
    else:
        ok = False
    end
    if not ok:
        call mg.text_view_set_text(ui["text"], i18n.T("This message could not be displayed."))
        return 0
    end
    ui["body"] = data
    ui["body_uid"] = uid
    ui["message"] = r
    sender = ""
    if len(r["from"]) > 0:
        sender = mime.address_full(r["from"][0])
    end
    date = r["date"]
    if date == 0:
        date = find_row(uid).get("date", 0)
    end
    call show_headers(r["subject"], sender, addresses_text(r["to"]), addresses_text(r["cc"]), date)
    text = r["text"]
    if text.strip() == "":
        text = i18n.T("(This message has no text.)")
    end
    call gtk.widget_hide(ui["h_note"])
    if r["html"] and ui["web"] == 0 and (env.get("LUXOS_MAIL_NO_WEBKIT", "") != "" or not web.available()):
        call gtk.label_set_text(ui["h_note"], i18n.T("This message was formatted as a web page; Mail shows its text. Images and remote content are not loaded."))
        call gtk.widget_show(ui["h_note"])
    end
    call show_body(data, r, text)
    bar = ui["att_bar"]
    call clear_container(bar)
    if len(r["attachments"]) > 0:
        # no_show_all na liste: show_all by deti preskocil, ukazat kazde zvlast
        clip = icon(["mail-attachment-symbolic"], 1)
        call gtk.box_pack_start(bar, clip, False, False, 0)
        call gtk.widget_show(clip)
        for a in r["attachments"]:
            b = gtk.button_new(a["name"] + " (" + size_text(a["size"]) + ")")
            call gtk.widget_add_class(b, "att")
            call gtk.widget_set_tooltip(b, i18n.T("Open or save the attachment"))
            call gtk.connect_data(b, "clicked", 0, on_attachment_menu, a)
            call gtk.box_pack_start(bar, b, False, False, 0)
            call gtk.widget_show_all(b)
        end
        call gtk.widget_show(bar)
    else:
        call gtk.widget_hide(bar)
    end
    return 0
end

function downloads_dir():
    d = glib.user_special_dir(2)
    if d == "":
        d = glib.home_dir() + "/Downloads"
    end
    return d
end

function safe_name(name):
    n = name.replace("/", "-").replace("\\", "-").strip()
    if n == "" or n == "." or n == "..":
        n = "attachment"
    end
    return n
end

# Priloha: nabidka Otevrit / Ulozit jako...
function on_attachment_menu(a, button):
    menu = gtk.menu_new()
    item = gtk.menu_item_new(i18n.T("Open"))
    call gtk.connect_data(item, "activate", 0, on_attachment_open, a)
    call gtk.menu_append(menu, item)
    item = gtk.menu_item_new(i18n.T("Save As…"))
    call gtk.connect_data(item, "activate", 0, on_attachment_save, a)
    call gtk.menu_append(menu, item)
    call gtk.widget_show_all(menu)
    call gtk.menu_attach(menu, button)
    call mg.menu_popup_below(menu, button)
    call mg.menu_shell_select_first(menu)
    return 0
end

# Otevrit prilohu: do soukrome docasne slozky (~/.cache/luxos-mail/open, 0700/0600), pak vychozi aplikace
function on_attachment_open(a, item):
    base = env.get("XDG_CACHE_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.cache"
    end
    d = store.ensure_dir(store.ensure_dir(base + "/luxos-mail") + "/open")
    path = d + "/" + safe_name(a["name"])
    ok = True
    try:
        call writebytes(path, mime.part_bytes(ui["body"], a["path"]))
        call mb.chmod(path, 384)
    else:
        ok = False
    end
    if not ok:
        call message_box(i18n.T("The attachment could not be opened."), String(last_error()))
        return 0
    end
    call open_file(path)
    return 0
end

function open_file(path):
    log_path = env.get("LUXOS_MAIL_OPEN_URL_LOG", "")
    if log_path != None and log_path != "":
        safe:
            call appendfile(log_path, "file://" + path + "\n")
        end
        return 0
    end
    call glib.spawn_quiet(["xdg-open", path])
    return 0
end

function on_attachment_save(a, item):
    call on_attachment_clicked(a, item)
    return 0
end

function on_attachment_clicked(a, button):
    chooser = gtk.file_chooser_new(i18n.T("Save Attachment"), 1)
    call gtk.dialog_add_button(chooser, i18n.T("Cancel"), gtk.RESPONSE_CANCEL)
    call gtk.dialog_add_button(chooser, i18n.T("Save"), gtk.RESPONSE_OK)
    call gtk.dialog_set_default_response(chooser, gtk.RESPONSE_OK)
    call gtk.window_set_transient_for(chooser, ui["window"])
    call gtk.file_chooser_set_overwrite_confirm(chooser, True)
    call gtk.file_chooser_set_folder(chooser, downloads_dir())
    call gtk.file_chooser_set_name(chooser, safe_name(a["name"]))
    response = gtk.dialog_run(chooser)
    path = ""
    if response == gtk.RESPONSE_OK:
        path = gtk.file_chooser_get_filename(chooser)
    end
    call gtk.widget_destroy(chooser)
    if path == "":
        return 0
    end
    ok = True
    try:
        call writebytes(path, mime.part_bytes(ui["body"], a["path"]))
    else:
        ok = False
    end
    if not ok:
        call message_box(i18n.T("The attachment could not be saved."), String(last_error()))
    end
    return 0
end


# ---- zobrazeni tela zpravy (WebKit) ------------------------------------------------------------------------------

function dark_theme():
    t = env.get("GTK_THEME", "")
    if t != None and t != "":
        return t.lower().find("dark") >= 0
    end
    name = ""
    safe:
        name = gtk.settings_theme_name()
    end
    if name.lower().find("dark") >= 0:
        return True
    end
    dark = False
    safe:
        dark = gtk.settings_prefer_dark()
    end
    return dark == True
end

function remote_path():
    return store.base_config() + "/remote-images.json"
end

function remote_senders():
    data = None
    if exists(remote_path()):
        safe:
            data = json.decode(readfile(remote_path()))
        end
    end
    if type(data) != "Dictionary" or type(data.get("senders")) != "List":
        return []
    end
    return data["senders"]
end

function message_sender(r):
    if len(r.get("from", [])) > 0:
        return String(r["from"][0][1]).strip().lower()
    end
    return ""
end

function ensure_web():
    if ui["web"] != 0:
        return True
    end
    if env.get("LUXOS_MAIL_NO_WEBKIT", "") != "" or not web.available():
        return False
    end
    ok = True
    v = 0
    try:
        v = web.view_new()
    else:
        ok = False
        call log("WebKitGTK is not available: " + String(last_error()))
    end
    if not ok:
        return False
    end
    ui["web"] = v
    call gtk.accessible_name(v, i18n.T("Message"))
    # WebKit si pri nacteni bere fokus: sipky by pak posouvaly zpravu misto vyberu dalsi zpravy v seznamu.
    # Fokus jen po Enter v seznamu nebo klepnuti do zpravy.
    call gtk.widget_set_can_focus(v, False)
    call gtk.connect(v, "button-press-event", on_web_button)
    call glib.signal_connect(v, "decide-policy", on_web_policy, 2)
    call glib.signal_connect(v, "mouse-target-changed", on_web_hover, 2)
    overlay = gtk.overlay_new()
    call gtk.container_add(overlay, v)
    st = label("", "link-status")
    call gtk.label_set_ellipsize(st, 3)
    call gtk.label_set_max_width_chars(st, 90)
    call gtk.widget_set_halign(st, gtk.ALIGN_START)
    call gtk.widget_set_valign(st, gtk.ALIGN_END)
    call gtk.widget_set_no_show_all(st, True)
    call gtk.overlay_add_overlay(overlay, st)
    call mg.overlay_pass_through(overlay, st)
    ui["link_status"] = st
    call mg.stack_add(ui["body_stack"], overlay, "web")
    call gtk.widget_show_all(overlay)
    return True
end

# Telo zpravy: bezpecny dokument ve WebKitu (vzdalene obrazky jen s povolenim), bez WebKitu text
function show_body(data, r, text):
    if not ensure_web():
        call mg.stack_show(ui["body_stack"], "text")
        call mg.text_view_set_text(ui["text"], text)
        call mg.text_view_scroll_top(ui["text"])
        call mg.adjustment_set_value(mg.scrolled_vadjustment(ui["text_scroll"]), 0)
        call gtk.widget_hide(ui["images_bar"])
        return 0
    end
    if not body_has_focus():
        call gtk.widget_set_can_focus(ui["web"], False)
    end
    sender = message_sender(r)
    allowed = ui["view_remote"] or (sender != "" and sender in remote_senders())
    dark = dark_theme()
    doc = {}
    ok = True
    try:
        doc = mhtml.document(data, {"remote": allowed, "dark": dark})
    else:
        ok = False
        call log("message view: " + String(last_error()))
    end
    if not ok:
        doc = {"html": "<!DOCTYPE html><html><head><meta charset=\"utf-8\"></head><body><pre>" + mhtml.esc(text) + "</pre></body></html>", "remote": 0, "paper": False}
    end
    bg = mhtml.PALETTE_LIGHT["bg"]
    if dark and not doc.get("paper", False):
        bg = mhtml.PALETTE_DARK["bg"]
    end
    call web.set_background(ui["web"], bg)
    call web.load_html(ui["web"], doc["html"])
    call web.zoom_set(ui["web"], ui["zoom"])
    call mg.stack_show(ui["body_stack"], "web")
    call gtk.widget_hide(ui["link_status"])
    if doc.get("remote", 0) > 0 and not allowed:
        call gtk.label_set_text(ui["images_label"], i18n.T("Remote images are hidden to protect your privacy."))
        if sender != "":
            call gtk.button_set_label(ui["images_always"], i18n.TF("Always from %s", [sender]))
            call gtk.widget_show(ui["images_always"])
        else:
            call gtk.widget_hide(ui["images_always"])
        end
        call gtk.widget_show_all(ui["images_bar"])
        if sender == "":
            call gtk.widget_hide(ui["images_always"])
        end
    else:
        call gtk.widget_hide(ui["images_bar"])
    end
    call trace("view remote=" + String(doc.get("remote", 0)) + " allowed=" + String(allowed) + " dark=" + String(dark))
    return 0
end

function on_load_images(button):
    ui["view_remote"] = True
    if len(ui["message"]) > 0:
        call show_body(ui["body"], ui["message"], ui["message"].get("text", ""))
    end
    return 0
end

function on_always_images(button):
    sender = message_sender(ui["message"])
    if sender != "":
        senders = remote_senders()
        if sender not in senders:
            senders.append(sender)
        end
        call store.ensure_dir(store.base_config())
        call store.write_private(remote_path(), json.encode({"senders": senders}) + "\n")
    end
    call on_load_images(button)
    return 0
end

# Navigace ve WebKitu: nase nacteni dokumentu povolit, odkaz do prohlizece / okna psani, vse ostatni zakazat
function on_web_policy(decision, kind, view):
    r = web.decision_uri(decision, kind)
    if r[1] == "load" or r[1] == "response":
        call web.decision_use(decision)
        return True
    end
    call web.decision_ignore(decision)
    if r[1] == "click" and r[0] != "":
        call open_link(r[0])
    end
    return True
end

function web_focus():
    if ui["web"] != 0:
        call gtk.widget_set_can_focus(ui["web"], True)
        call gtk.widget_grab_focus(ui["web"])
    end
    return 0
end

function on_web_button(event, view):
    call gtk.widget_set_can_focus(view, True)
    call gtk.widget_grab_focus(view)
    return False
end

function on_web_hover(hit, modifiers, view):
    uri = web.hit_link(hit)
    st = ui["link_status"]
    if uri == "":
        call gtk.widget_hide(st)
    else:
        call gtk.label_set_text(st, uri)
        call gtk.widget_show(st)
    end
    return 0
end

# Odkaz ze zpravy: http(s) do prohlizece, mailto: do okna psani, tel: vychozi aplikace
function open_link(uri):
    low = uri.lower()
    call trace("link " + uri)
    if low.startswith("mailto:"):
        call compose_mailto(uri)
        return 0
    end
    if not (low.startswith("http://") or low.startswith("https://") or low.startswith("tel:")):
        return 0
    end
    log_path = env.get("LUXOS_MAIL_OPEN_URL_LOG", "")
    if log_path != None and log_path != "":
        safe:
            call appendfile(log_path, uri + "\n")
        end
        return 0
    end
    call glib.spawn_quiet(["xdg-open", uri])
    return 0
end

function message_shown():
    return ui["selected"] != 0 and len(ui["message"]) > 0
end

function find_open():
    if ui["web"] == 0 or not message_shown():
        return 0
    end
    call gtk.widget_show_all(ui["find_bar"])
    call gtk.widget_grab_focus(ui["find_entry"])
    return 0
end

function on_find_changed(entry):
    t = gtk.entry_get_text(entry)
    if ui["web"] == 0:
        return 0
    end
    if t == "":
        call web.find_finish(ui["web"])
    else:
        call web.find(ui["web"], t)
    end
    return 0
end

function on_find_next(widget):
    if ui["web"] != 0 and gtk.entry_get_text(ui["find_entry"]) != "":
        call web.find_next(ui["web"])
    end
    return 0
end

function on_find_prev(widget):
    if ui["web"] != 0 and gtk.entry_get_text(ui["find_entry"]) != "":
        call web.find_previous(ui["web"])
    end
    return 0
end

function on_find_close(widget):
    if ui["web"] != 0:
        call web.find_finish(ui["web"])
        call web_focus()
    end
    call gtk.entry_set_text(ui["find_entry"], "")
    call gtk.widget_hide(ui["find_bar"])
    return 0
end

function zoom_by(step):
    if ui["web"] == 0:
        return 0
    end
    if step == 0:
        ui["zoom"] = 1.0
    else:
        ui["zoom"] = max(0.5, min(3.0, ui["zoom"] + step))
    end
    call web.zoom_set(ui["web"], ui["zoom"])
    return 0
end

function print_message():
    if ui["web"] != 0 and message_shown():
        call web.print_dialog(ui["web"], ui["window"])
    end
    return 0
end

function body_has_focus():
    focus = mg.window_get_focus(ui["window"])
    return focus != 0 and (focus == ui["web"] or focus == ui["text"])
end

# ---- psani: nova zprava, odpoved, preposlani, koncept, mailto: -------------------------------------------------------

function compose_host():
    return {"request": request, "trace": trace, "sent": on_compose_sent, "closed": on_compose_closed}
end

function on_compose_sent(sent, kind):
    call trace("compose sent=" + String(sent) + " " + kind)
    call build_sidebar()
    return 0
end

function on_compose_closed():
    if ui.get("hidden", False) and compose.open_count() == 0:
        call gtk.main_quit()
    end
    return 0
end

function own_addresses():
    out = []
    for a in ui["accounts"]:
        out.append(a["email"].lower())
    end
    return out
end

function default_account():
    cur = ui["current"]["account"]
    if cur != "":
        return cur
    end
    if len(ui["accounts"]) > 0:
        return ui["accounts"][0]["id"]
    end
    return ""
end

function sig_text(id):
    sig = compose.signature_block(account(id))
    if sig == "":
        return ""
    end
    return "\n\n" + sig
end

function new_message(to):
    if len(ui["accounts"]) == 0:
        call open_add_dialog("", "")
        return 0
    end
    id = default_account()
    call compose.open({"account": id, "to": to, "text": sig_text(id)})
    return 0
end

# mailto:adresa?subject=...&cc=...&body=... (RFC 6068)
function compose_mailto(uri):
    rest = uri
    if rest.lower().startswith("mailto:"):
        rest = rest[7:]
    end
    query = ""
    q = rest.find("?")
    if q >= 0:
        query = rest[q + 1:]
        rest = rest[0:q]
    end
    to = mime.parse_addresses(pct(rest))
    fields = {}
    for pair in query.split("&"):
        eq = pair.find("=")
        if eq > 0:
            fields[pair[0:eq].lower()] = pct(pair[eq + 1:])
        end
    end
    if "to" in fields:
        to = to + mime.parse_addresses(fields["to"])
    end
    if len(ui["accounts"]) == 0:
        call open_add_dialog("", i18n.TF("Add your email account to write to %s.", [pct(rest)]))
        return 0
    end
    id = default_account()
    call compose.open({"account": id, "to": to, "cc": mime.parse_addresses(fields.get("cc", "")), "bcc": mime.parse_addresses(fields.get("bcc", "")),
                       "subject": fields.get("subject", ""), "text": fields.get("body", "") + sig_text(id)})
    return 0
end

function pct(s):
    b = mime.percent_decode(s.replace("+", "%2B"))
    return mime.decode_text(b, 0, len(b), "utf-8")
end

function selected_message():
    m = find_row(ui["selected"])
    if len(m) == 0:
        return [{}, {}]
    end
    r = {}
    if ui["body_uid"] == m["uid"] and len(ui["message"]) > 0:
        r = ui["message"]
    end
    return [m, r]
end

function remove_own(pairs, own, seen):
    out = []
    for p in pairs:
        e = String(p[1]).strip().lower()
        if e == "" or e in own or e in seen:
            continue
        end
        seen[e] = True
        out.append(p)
    end
    return out
end

# Odpoved (all: i ostatnim prijemcum) nebo preposlani vybrane zpravy
function reply_to_selected(kind):
    cur = ui["current"]
    if cur["raw"] == "__outbox__" or cur["account"] == "":
        return 0
    end
    sel = selected_message()
    m = sel[0]
    r = sel[1]
    if len(m) == 0:
        return 0
    end
    if kind == "forward" and len(r) == 0:
        call message_box(i18n.T("The message is still downloading."), i18n.T("Try again when the message is shown."))
        return 0
    end
    own = own_addresses()
    sender = [m["from_name"], m["from_email"]]
    if len(r) > 0 and len(r["from"]) > 0:
        sender = r["from"][0]
    end
    subject = m["subject"]
    date = m["date"]
    text = ""
    to_list = []
    cc_list = []
    if len(r) > 0:
        subject = r["subject"]
        if r["date"] != 0:
            date = r["date"]
        end
        text = r["text"]
        to_list = r["to"]
        cc_list = r["cc"]
    end
    sig = compose.signature_block(account(cur["account"]))
    opts = {"account": cur["account"], "reply": {"account": cur["account"], "mailbox": cur["raw"], "uid": m["uid"]}}
    if kind == "forward":
        lines = ["---------- " + i18n.T("Forwarded message") + " ----------", i18n.T("From:") + " " + mime.address_full(sender),
                 i18n.T("Date:") + " " + long_date(date), i18n.T("Subject:") + " " + subject]
        if len(to_list) > 0:
            lines.append(i18n.T("To:") + " " + addresses_text(to_list))
        end
        if len(cc_list) > 0:
            lines.append(i18n.T("Cc:") + " " + addresses_text(cc_list))
        end
        body = "\n\n"
        if sig != "":
            body = body + sig + "\n\n"
        end
        opts["text"] = body + "\n".join(lines) + "\n\n" + text
        opts["subject"] = mime.forward_subject(subject)
        opts["attachments"] = extract_attachments(r["attachments"])
        opts["reply"]["forward"] = True
        call compose.open(opts)
        return 0
    end
    seen = {}
    to = []
    if String(sender[1]).lower() in own:
        # odpoved na vlastni zpravu (Odeslane): puvodnim prijemcum
        to = remove_own(to_list, own, seen)
        if kind == "all":
            opts["cc"] = remove_own(cc_list, own, seen)
        end
    else:
        rt = []
        if len(r) > 0:
            rt = r.get("reply_to", [])
        end
        if len(rt) == 0:
            rt = [sender]
        end
        to = remove_own(rt, [], seen)
        if kind == "all":
            opts["cc"] = remove_own(to_list + cc_list, own, seen)
        end
    end
    opts["to"] = to
    opts["subject"] = mime.reply_subject(subject)
    who = sender[0]
    if who == "":
        who = sender[1]
    end
    body = "\n\n"
    if sig != "":
        body = body + sig + "\n\n"
    end
    if text != "":
        body = body + i18n.TF("On %s, %s wrote:", [long_date(date), who]) + "\n" + mime.quote_text(text) + "\n"
    end
    opts["text"] = body
    if len(r) > 0:
        opts["in_reply_to"] = r["message_id"]
        opts["references"] = mime.thread_references(r.get("references", ""), r["message_id"])
    end
    call compose.open(opts)
    return 0
end

# Prilohy puvodni zpravy (preposlani, koncept) do soukrome slozky konceptu
function extract_attachments(list):
    out = []
    if len(list) == 0:
        return out
    end
    d = store.ensure_dir(store.ensure_dir(store.base_data() + "/drafts") + "/files-" + mime.random_hex(6))
    for a in list:
        path = d + "/" + safe_name(a["name"])
        safe:
            call writebytes(path, mime.part_bytes(ui["body"], a["path"]))
            call mb.chmod(path, 384)
            out.append({"name": a["name"], "path": path})
        end
    end
    return out
end

# Koncept ze slozky Koncepty: do okna psani (ulozeni ho na serveru nahradi, odeslani smaze)
function edit_draft():
    sel = selected_message()
    r = sel[1]
    if len(r) == 0:
        return 0
    end
    hs = mime.parse_message(ui["body"])["headers"]
    bcc = mime.parse_addresses(mime.decode_words(mime.header(hs, "bcc")))
    acc = ui["current"]["account"]
    call compose.open({"account": acc, "to": r["to"], "cc": r["cc"], "bcc": bcc, "subject": r["subject"], "text": r["text"],
                       "attachments": extract_attachments(r["attachments"]), "draft_mid": r["message_id"],
                       "in_reply_to": r.get("in_reply_to", ""), "references": r.get("references", "")})
    return 0
end

function on_reply_clicked(button):
    call reply_to_selected("reply")
    return 0
end

function on_reply_all_clicked(button):
    call reply_to_selected("all")
    return 0
end

function on_forward_clicked(button):
    call reply_to_selected("forward")
    return 0
end

# ---- Odchozi ------------------------------------------------------------------------------------------------------

function outbox_dir():
    return store.base_data() + "/outbox"
end

function outbox_jobs():
    out = []
    if not glib.is_dir(outbox_dir()):
        return out
    end
    by = {}
    keys = []
    for name in glib.list_dir(outbox_dir()):
        if not name.endswith(".json"):
            continue
        end
        id = name[0:len(name) - 5]
        job = None
        safe:
            job = json.decode(readfile(outbox_dir() + "/" + name))
        end
        if type(job) != "Dictionary" or not exists(outbox_dir() + "/" + id + ".eml"):
            continue
        end
        # uz odeslana (sluzba jen dokoncuje kopii do Odeslanych): v Odchozi neukazovat
        if job.get("state", "") == "post":
            continue
        end
        job["id"] = id
        created = job.get("created", 0)
        if type(created) != "Int":
            created = 0
        end
        key = created * 1000 + len(keys)
        by[key] = job
        keys.append(key)
    end
    keys.sort()
    i = len(keys) - 1
    while i >= 0:
        out.append(by[keys[i]])
        i -= 1
    end
    return out
end

function job_state_text(job):
    state = String(job.get("state", ""))
    if state == "failed":
        return i18n.T("Not sent") + ": " + compose.error_text(String(job.get("kind", "")), String(job.get("error", "")), String(job.get("account", "")))
    elif state == "sending":
        return i18n.T("Sending…")
    end
    return i18n.T("Waiting to be sent – Mail tries again automatically.")
end

function outbox_rows():
    rows = []
    ui["jobs"] = {}
    uid = 1
    for job in outbox_jobs():
        ui["jobs"][uid] = job
        created = job.get("created", 0)
        if type(created) != "Int":
            created = 0
        end
        flags = "S"
        if job.get("state", "") == "failed":
            flags = "SF"
        end
        rows.append({"uid": uid, "flags": flags, "internal": created, "date": created, "from_name": "", "from_email": "",
                     "to": String(job.get("to_text", "")), "subject": String(job.get("subject", "")), "preview": job_state_text(job),
                     "size": 0, "att": False})
        uid += 1
    end
    return rows
end

function outbox_job():
    return ui["jobs"].get(ui["selected"], {})
end

function outbox_retry():
    job = outbox_job()
    if len(job) > 0:
        call set_busy(True)
        call request("outbox_retry", {"job": job["id"]}, {})
    end
    return 0
end

function outbox_edit():
    job = outbox_job()
    st = job.get("compose", {})
    if len(job) == 0 or type(st) != "Dictionary" or len(st) == 0:
        return 0
    end
    opts = st
    opts.pop("id", None)
    opts["draft_saved"] = False
    call compose.open(opts)
    call request("outbox_delete", {"job": job["id"]}, {})
    return 0
end

function outbox_delete():
    job = outbox_job()
    if len(job) == 0:
        return 0
    end
    if confirm(i18n.T("Delete this unsent message?"), i18n.T("It is removed from the Outbox and will not be sent."), i18n.T("Delete")):
        call request("outbox_delete", {"job": job["id"]}, {})
    end
    return 0
end

function show_outbox_banner():
    job = outbox_job()
    if len(job) == 0:
        call gtk.widget_hide(ui["banner"])
        return 0
    end
    call gtk.label_set_text(ui["banner_label"], job_state_text(job))
    call trace("outbox banner " + job_state_text(job))
    if job.get("state", "") == "failed":
        call gtk.button_set_label(ui["banner_button"], i18n.T("Send Again"))
    else:
        call gtk.button_set_label(ui["banner_button"], i18n.T("Send Now"))
    end
    call gtk.widget_set_class(ui["banner"], "error", job.get("state", "") == "failed")
    call gtk.widget_show(ui["banner_label"])
    call gtk.widget_show_all(ui["banner_button"])
    call gtk.widget_show(ui["banner"])
    return 0
end

# ---- podpis ---------------------------------------------------------------------------------------------------------

function on_menu_signature(id, item):
    a = account(id)
    d = gtk.dialog_new()
    call gtk.window_set_title(d, i18n.T("Signature"))
    call gtk.window_set_transient_for(d, ui["window"])
    call gtk.window_set_modal(d, True)
    call gtk.window_set_default_size(d, 460, 260)
    area = gtk.dialog_get_content_area(d)
    box = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.widget_add_class(box, "dialog-box")
    call gtk.box_pack_start(box, label(i18n.TF("Signature for %s", [a.get("email", "")]), "list-title"), False, False, 0)
    hint = label(i18n.T("Added to new messages, replies and forwards, below the line “-- ”."), "dim small")
    call gtk.label_set_line_wrap(hint, True)
    call gtk.box_pack_start(box, hint, False, False, 0)
    sc = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(sc, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    call gtk.widget_set_size_request(sc, -1, 120)
    tv = mg.editor_new()
    call mg.text_view_set_margins(tv, 8, 8, 6, 6)
    call gtk.accessible_name(tv, i18n.T("Signature"))
    call mg.text_view_set_text(tv, String(a.get("signature", "")))
    call gtk.container_add(sc, tv)
    call gtk.box_pack_start(box, sc, True, True, 0)
    call gtk.box_pack_start(area, box, True, True, 0)
    call gtk.dialog_add_button(d, i18n.T("Cancel"), gtk.RESPONSE_CANCEL)
    call gtk.dialog_add_button(d, i18n.T("Save"), gtk.RESPONSE_OK)
    call gtk.widget_show_all(d)
    call gtk.widget_grab_focus(tv)
    response = gtk.dialog_run(d)
    text = mg.text_view_get_text(tv)
    call gtk.widget_destroy(d)
    if response == gtk.RESPONSE_OK:
        call request("account_settings", {"account": id, "signature": text.strip()}, {})
    end
    return 0
end

# ---- akce ---------------------------------------------------------------------------------------------------

function set_busy(on):
    call mg.spinner_set(ui["spinner"], on)
    return 0
end

function set_read(m, read):
    cur = ui["current"]
    if cur["raw"] == "__outbox__":
        return 0
    end
    f = m["flags"].replace("S", "")
    if read:
        f = f + "S"
    end
    m["flags"] = f
    if m["uid"] in ui["widgets"]:
        w = ui["widgets"][m["uid"]]
        if read:
            call gtk.label_set_text(w[0], " ")
            call gtk.widget_remove_class(w[1], "unread")
        else:
            call gtk.label_set_text(w[0], "●")
            call gtk.widget_add_class(w[1], "unread")
        end
    end
    call update_title()
    call request("flags", {"account": cur["account"], "mailbox": cur["raw"], "uids": [m["uid"]], "add": read, "flags": ["\\Seen"]}, {"account": cur["account"], "mailbox": cur["raw"]})
    return 0
end

function toggle_read():
    m = find_row(ui["selected"])
    if len(m) == 0:
        return 0
    end
    call set_read(m, m["flags"].find("S") < 0)
    return 0
end

function delete_selected():
    uid = ui["selected"]
    if uid == 0:
        return 0
    end
    cur = ui["current"]
    if cur["raw"] == "__outbox__":
        call outbox_delete()
        return 0
    end
    if cur["role"] == "trash":
        if not confirm(i18n.T("Delete this message permanently?"), i18n.T("It is already in the Trash. This cannot be undone."), i18n.T("Delete")):
            return 0
        end
    end
    # dalsi zprava v seznamu dostane vyber
    index = -1
    i = 0
    for m in ui["shown"]:
        if m["uid"] == uid:
            index = i
        end
        i += 1
    end
    rows = []
    for m in ui["rows"]:
        if m["uid"] != uid:
            rows.append(m)
        end
    end
    ui["rows"] = rows
    call apply_filter()
    nxt = 0
    if index >= 0 and len(ui["shown"]) > 0:
        nxt = ui["shown"][min(index, len(ui["shown"]) - 1)]["uid"]
    end
    ui["selected"] = 0
    call build_list(nxt)
    if nxt > 0:
        call select_uid(nxt)
    else:
        call mg.stack_show(ui["view"], "empty")
    end
    call request("trash", {"account": cur["account"], "mailbox": cur["raw"], "uids": [uid]}, {"account": cur["account"], "mailbox": cur["raw"]})
    return 0
end

function refresh():
    cur = ui["current"]
    if cur["raw"] == "__outbox__":
        call reload_current(ui["selected"])
        return 0
    end
    if cur["account"] == "":
        return 0
    end
    call set_busy(True)
    call request("mailboxes", {"account": cur["account"]}, {"account": cur["account"]})
    call request("sync", {"account": cur["account"], "mailbox": cur["raw"]}, {"account": cur["account"], "mailbox": cur["raw"]})
    return 0
end

function on_refresh_clicked(button):
    call refresh()
    return 0
end

function on_compose_clicked(button):
    call new_message([])
    return 0
end

function on_read_clicked(button):
    call toggle_read()
    return 0
end

function on_delete_clicked(button):
    call delete_selected()
    return 0
end

function on_search(entry):
    ui["filter"] = gtk.entry_get_text(entry).strip()
    call apply_filter()
    keep = ui["selected"]
    call build_list(keep)
    if keep > 0 and not select_uid(keep, False):
        # vybrana zprava filtru neodpovida: prazdny nahled misto zpravy mimo seznam
        ui["selected"] = 0
        call mg.stack_show(ui["view"], "empty")
    end
    return 0
end

function on_key(event, window):
    key = gtk.event_key_keyval(event)
    state = gtk.event_key_state(event)
    ctrl = (state & gtk.CONTROL_MASK) != 0
    shift = (state & gtk.SHIFT_MASK) != 0
    focus = mg.window_get_focus(window)
    in_entry = mg.is_entry(focus)
    if ctrl and not shift and (key == 102 or key == 70):
        if body_has_focus() or focus == ui["find_entry"]:
            call find_open()
        else:
            call gtk.widget_grab_focus(ui["search"])
        end
        return True
    end
    if key == 65474 or (ctrl and shift and (key == 110 or key == 78)):
        call refresh()
        return True
    end
    if ctrl and (key == 114 or key == 82):
        if shift:
            call reply_to_selected("all")
        else:
            call reply_to_selected("reply")
        end
        return True
    end
    if ctrl and shift and (key == 102 or key == 70):
        call reply_to_selected("forward")
        return True
    end
    if ctrl and not shift and (key == 110 or key == 78):
        call new_message([])
        return True
    end
    if ctrl and (key == 112 or key == 80):
        call print_message()
        return True
    end
    if ctrl and (key == 43 or key == 61 or key == 65451):
        call zoom_by(0.1)
        return True
    end
    if ctrl and (key == 45 or key == 65453):
        call zoom_by(-0.1)
        return True
    end
    if ctrl and (key == 48 or key == 65456):
        call zoom_by(0)
        return True
    end
    if key == 65472 and gtk.widget_get_visible(ui["find_bar"]):
        if shift:
            call on_find_prev(0)
        else:
            call on_find_next(0)
        end
        return True
    end
    if focus == ui["find_entry"] and key == gtk.KEY_Escape:
        call on_find_close(0)
        return True
    end
    if focus == ui["find_entry"] and shift and key == gtk.KEY_Return:
        call on_find_prev(0)
        return True
    end
    if ctrl and (key == 113 or key == 81 or key == 119 or key == 87):
        call quit()
        return True
    end
    if key == 65479 and not ctrl:                       # F10: nabidka (Pridat ucet ...)
        call on_menu_clicked(ui["menu_button"])
        return True
    end
    if ctrl and shift and (key == 117 or key == 85):
        call toggle_read()
        return True
    end
    if key == gtk.KEY_Delete and not in_entry:
        call delete_selected()
        return True
    end
    if key == gtk.KEY_Escape and focus == ui["search"]:
        call gtk.entry_set_text(ui["search"], "")
        row = mg.list_box_get_selected_row(ui["list"])
        if row != 0:
            call gtk.widget_grab_focus(row)
        else:
            call gtk.widget_grab_focus(ui["list"])
        end
        return True
    end
    if (key == gtk.KEY_Down or key == gtk.KEY_Return) and focus == ui["search"]:
        row = mg.list_box_get_row_at_index(ui["list"], 0)
        if row != 0:
            call mg.list_box_select_row(ui["list"], row)
            call gtk.widget_grab_focus(row)
        end
        return True
    end
    return False
end

function quit():
    if compose.open_count() > 0:
        # rozepsane zpravy: hlavni okno se skryje, Posta skonci az se zavrenim posledniho okna psani
        ui["hidden"] = True
        call gtk.widget_hide(ui["window"])
        return 0
    end
    call gtk.main_quit()
    return 0
end

function on_delete_event(event, window):
    call quit()
    return True
end

# ---- banner stavu uctu ------------------------------------------------------------------------------------------

function error_text(st):
    kind = st.get("kind", "")
    detail = st.get("error", "")
    a = account(st.get("account", ""))
    s = a.get("imap", {})
    host = String(s.get("host", ""))
    if a.get("auth", "") == "luxai" and (kind == "auth" or kind.startswith("luxai_") or kind == "nooauth"):
        return luxai_error_text(kind, detail, a.get("email", ""))
    end
    if a.get("auth", "") == "oauth" and (kind == "auth" or kind.startswith("oauth_") or kind == "nooauth" or kind == "connect" or kind == "notconnected"):
        return oauth_account_text(a, kind, detail)
    end
    if kind == "auth" or kind == "oauthonly":
        t = i18n.TF("The server rejected the password for %s.", [a.get("email", "")])
        extra = provider_auth_text(provider.of_account(a), kind)
        if extra != "":
            t = t + " " + extra
        end
        return t
    elif kind == "nopassword":
        return i18n.T("The password is not in the keyring. Enter it again.")
    elif kind == "cert":
        return i18n.TF("The security certificate of %s is not valid (%s). Mail does not connect to protect your password.", [host, detail])
    elif kind == "connect" or kind == "timeout" or kind == "closed":
        return i18n.TF("Cannot reach %s. Showing saved messages.", [host])
    elif kind == "nostarttls" or kind == "insecure":
        return i18n.TF("%s does not offer an encrypted connection. Mail does not send your password unencrypted.", [host])
    end
    if detail != "":
        return detail
    end
    return i18n.T("Offline – showing saved messages.")
end

function update_banner():
    if ui["current"]["raw"] == "__outbox__":
        call show_outbox_banner()
        return 0
    end
    st = ui["status"].get(ui["current"]["account"], {})
    state = st.get("state", "")
    if state == "error" or (state == "offline" and st.get("kind", "") != ""):
        btext = error_text(st)
        call gtk.label_set_text(ui["banner_label"], btext)
        call trace("banner " + btext)
        kind = st.get("kind", "")
        luxai_account = account(st.get("account", "")).get("auth", "") == "luxai"
        oauth_account = account(st.get("account", "")).get("auth", "") == "oauth"
        if luxai_account and (kind == "luxai_session" or kind == "luxai_signedout"):
            call gtk.button_set_label(ui["banner_button"], i18n.T("Sign In…"))
        elif oauth_account and oauth_needs_sign_in(kind):
            call gtk.button_set_label(ui["banner_button"], i18n.T("Sign In Again…"))
        elif (kind == "auth" or kind == "nopassword") and not luxai_account:
            call gtk.button_set_label(ui["banner_button"], i18n.T("Enter Password…"))
        else:
            call gtk.button_set_label(ui["banner_button"], i18n.T("Try Again"))
        end
        # vyprsene prihlaseni u poskytovatele je bezna vec (zmena hesla, 7 dni v testovacim rezimu Google):
        # klidny zluty pruh, ne cervena chyba
        call gtk.widget_set_class(ui["banner"], "error", (state == "error" or kind == "cert") and kind != "oauth_expired")
        call gtk.widget_show(ui["banner_label"])
        call gtk.widget_show_all(ui["banner_button"])
        call gtk.widget_show(ui["banner"])
    else:
        call gtk.widget_hide(ui["banner"])
    end
    return 0
end

function on_banner_clicked(button):
    if ui["current"]["raw"] == "__outbox__":
        call outbox_retry()
        return 0
    end
    st = ui["status"].get(ui["current"]["account"], {})
    kind = st.get("kind", "")
    id = ui["current"]["account"]
    if account(id).get("auth", "") == "oauth":
        if oauth_needs_sign_in(kind):
            call oauth_sign_in_again(id)
        elif st.get("state", "") == "error":
            call set_busy(True)
            call request("retry_account", {"account": id}, {"account": id})
        else:
            call request("reconnect", {}, {})
        end
        return 0
    end
    if account(id).get("auth", "") == "luxai":
        if kind == "luxai_session" or kind == "luxai_signedout":
            call luxai_login("retry", id)
        elif st.get("state", "") == "error":
            # jeden novy pokus (zamitnuty token se sam neopakuje)
            call set_busy(True)
            call request("retry_account", {"account": id}, {"account": id})
        else:
            call request("reconnect", {}, {})
        end
        return 0
    end
    if kind == "auth" or kind == "nopassword":
        call password_dialog(ui["current"]["account"])
    else:
        call request("reconnect", {}, {})
    end
    return 0
end

# ---- udalosti a odpovedi sluzby ------------------------------------------------------------------------------------

function reload_accounts():
    ui["accounts"] = store.load_accounts()
    if len(ui["accounts"]) == 0:
        call mg.stack_show(ui["outer"], "welcome")
        call gtk.window_set_title(ui["window"], i18n.T("Mail"))
        call update_welcome()
    else:
        call mg.stack_show(ui["outer"], "main")
    end
    return 0
end

function reload_current(keep_uid):
    # radek s fokusem se pri prestaveni seznamu znici: fokus pak vratit na vybranou zpravu (jinak sipky
    # po synchronizaci na pozadi nic nedelaji)
    focus = mg.window_get_focus(ui["window"])
    list_focus = focus != 0 and (focus in ui["row_index"] or focus == ui["list"])
    call load_rows()
    adj = mg.scrolled_vadjustment(ui["list_scroll"])
    pos = mg.adjustment_get_value(adj)
    shown = max(PAGE, ui["built"])
    call build_list(0)
    if ui["built"] < shown:
        call extend_list(shown - ui["built"])
    end
    if keep_uid > 0:
        row = row_for_uid(keep_uid)
        if row != 0:
            ui["building"] = True
            call mg.list_box_select_row(ui["list"], row)
            ui["building"] = False
            if list_focus:
                call gtk.widget_grab_focus(row)
            end
        else:
            ui["selected"] = 0
            call mg.stack_show(ui["view"], "empty")
        end
    end
    call mg.adjustment_set_value(adj, pos)
    return 0
end

function on_event(msg):
    ev = msg["event"]
    if ev == "changed":
        if msg.get("account", "") == ui["current"]["account"] and msg.get("mailbox", "") == ui["current"]["raw"]:
            call reload_current(ui["selected"])
        end
        call build_sidebar()
    elif ev == "status":
        ui["status"][msg.get("account", "")] = msg
        call update_banner()
        call build_sidebar()
    elif ev == "oauth_done":
        call on_oauth_done(msg)
    elif ev == "outbox":
        call build_sidebar()
        if ui["current"]["raw"] == "__outbox__":
            call reload_current(ui["selected"])
            call show_outbox_banner()
        end
    end
    return 0
end

function on_reply(msg, ctx):
    op = ctx["op"]
    ok = msg.get("ok", False)
    if "compose" in ctx:
        call compose.on_reply(msg, ctx)
        return 0
    end
    if op == "account_settings":
        call reload_accounts()
        return 0
    end
    if op == "outbox_retry" or op == "outbox_delete":
        call set_busy(False)
        call build_sidebar()
        if ui["current"]["raw"] == "__outbox__":
            call reload_current(0)
            ui["selected"] = 0
            call mg.stack_show(ui["view"], "empty")
            call show_outbox_banner()
        end
        return 0
    end
    if op == "hello":
        for st in msg.get("accounts", []):
            ui["status"][st["account"]] = st
        end
        call update_banner()
        call build_sidebar()
    elif op == "sync" or op == "older" or op == "mailboxes":
        call set_busy(False)
        if op == "mailboxes" and ok:
            call build_sidebar()
        end
        if op == "older" and ctx.get("account", "") == ui["current"]["account"] and ctx.get("mailbox", "") == ui["current"]["raw"]:
            call reload_current(ui["selected"])
        end
    elif op == "body":
        call set_busy(False)
        if ctx["account"] == ui["current"]["account"] and ctx["mailbox"] == ui["current"]["raw"] and ctx["uid"] == ui["selected"]:
            if ok:
                call render_body(ctx["uid"], msg["path"])
            else:
                text = i18n.T("This message is not available offline.")
                if msg.get("kind", "") == "gone":
                    text = i18n.T("The message no longer exists on the server.")
                end
                call mg.text_view_set_text(ui["text"], text + "\n\n" + msg.get("error", ""))
            end
        end
    elif op == "flags" or op == "trash":
        if not ok:
            call log(op + ": " + msg.get("error", ""))
            if ctx.get("account", "") == ui["current"]["account"] and ctx.get("mailbox", "") == ui["current"]["raw"]:
                call reload_current(ui["selected"])
            end
        end
    elif op == "add_account":
        call on_account_added(msg)
    elif op == "set_password":
        call on_password_set(msg)
    elif op == "luxai_mailboxes":
        call on_luxai_mailboxes(msg, ctx)
    elif op == "add_luxai_account":
        call on_luxai_added(msg)
    elif op == "oauth_start":
        call on_oauth_started(msg, ctx)
    elif op == "retry_account":
        call set_busy(False)
    elif op == "remove_account":
        call reload_accounts()
        ui["current"] = {"account": "", "raw": "", "role": "", "name": ""}
        call select_first_inbox()
    end
    return 0
end

function open_outbox():
    call build_sidebar()
    call open_mailbox("", "__outbox__", 0)
    call select_side("", "__outbox__")
    call gtk.window_present(ui["window"])
    return 0
end

function select_first_inbox():
    selected = build_sidebar()
    if selected >= 0:
        return 0
    end
    if len(ui["accounts"]) == 0:
        ui["rows"] = []
        ui["shown"] = []
        call build_list(0)
        return 0
    end
    call open_mailbox(ui["accounts"][0]["id"], "INBOX", 0)
    call select_side(ui["accounts"][0]["id"], "INBOX")
    return 0
end

# ---- dialogy ----------------------------------------------------------------------------------------------------

function message_box(title, text):
    d = gtk.dialog_new()
    call gtk.window_set_title(d, i18n.T("Mail"))
    call gtk.window_set_transient_for(d, ui["window"])
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
        call gtk.label_set_max_width_chars(l, 60)
        call gtk.label_set_selectable(l, True)
        call gtk.box_pack_start(box, l, False, False, 0)
    end
    call gtk.box_pack_start(area, box, True, True, 0)
    call gtk.dialog_add_button(d, i18n.T("Close"), gtk.RESPONSE_OK)
    call gtk.widget_show_all(d)
    call gtk.dialog_run(d)
    call gtk.widget_destroy(d)
    return 0
end

function confirm(title, text, action):
    d = gtk.dialog_new()
    call gtk.window_set_title(d, i18n.T("Mail"))
    call gtk.window_set_transient_for(d, ui["window"])
    call gtk.window_set_modal(d, True)
    area = gtk.dialog_get_content_area(d)
    box = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.widget_add_class(box, "dialog-box")
    t = label(title, "list-title")
    call gtk.box_pack_start(box, t, False, False, 0)
    l = label(text, "")
    call gtk.label_set_line_wrap(l, True)
    call gtk.box_pack_start(box, l, False, False, 0)
    call gtk.box_pack_start(area, box, True, True, 0)
    call gtk.dialog_add_button(d, i18n.T("Cancel"), gtk.RESPONSE_CANCEL)
    call gtk.dialog_add_button(d, action, gtk.RESPONSE_OK)
    call gtk.widget_show_all(d)
    response = gtk.dialog_run(d)
    call gtk.widget_destroy(d)
    return response == gtk.RESPONSE_OK
end

function mailto_address(uri):
    a = uri
    if a.lower().startswith("mailto:"):
        a = a[7:]
    end
    q = a.find("?")
    if q >= 0:
        a = a[0:q]
    end
    return mime.decode_text(mime.percent_decode(a), 0, len(mime.percent_decode(a)), "utf-8")
end

# ---- nabidka ----------------------------------------------------------------------------------------------------

function on_menu_clicked(button):
    menu = gtk.menu_new()
    item = gtk.menu_item_new(i18n.T("Add Account…"))
    call gtk.connect(item, "activate", on_add_account_clicked)
    call gtk.menu_append(menu, item)
    if len(luxai.account_user()) > 0:
        item = gtk.menu_item_new(i18n.T("Add LuxAI Mailbox…"))
        call gtk.connect(item, "activate", on_luxai_clicked)
        call gtk.menu_append(menu, item)
    end
    cur = ui["current"]["account"]
    if cur != "":
        a = account(cur)
        if a.get("auth", "") == "oauth":
            item = gtk.menu_item_new(i18n.TF("Sign In Again to %s…", [a.get("email", "")]))
            call gtk.connect_data(item, "activate", 0, on_menu_sign_in_again, cur)
            call gtk.menu_append(menu, item)
        elif a.get("auth", "") != "luxai":
            item = gtk.menu_item_new(i18n.TF("Change Password for %s…", [a.get("email", "")]))
            call gtk.connect_data(item, "activate", 0, on_menu_password, cur)
            call gtk.menu_append(menu, item)
        end
        item = gtk.menu_item_new(i18n.TF("Signature for %s…", [a.get("email", "")]))
        call gtk.connect_data(item, "activate", 0, on_menu_signature, cur)
        call gtk.menu_append(menu, item)
        item = gtk.menu_item_new(i18n.TF("Remove %s…", [a.get("email", "")]))
        call gtk.connect_data(item, "activate", 0, on_menu_remove, cur)
        call gtk.menu_append(menu, item)
    end
    call gtk.menu_append(menu, gtk.separator_menu_item_new())
    item = gtk.menu_item_new(i18n.T("Keyboard Shortcuts"))
    call gtk.connect(item, "activate", on_menu_shortcuts)
    call gtk.menu_append(menu, item)
    call gtk.widget_show_all(menu)
    call gtk.menu_attach(menu, ui["menu_button"])
    call mg.menu_popup_below(menu, ui["menu_button"])
    # klavesnice: prvni polozka vybrana (sipky, Enter)
    call mg.menu_shell_select_first(menu)
    return 0
end

function on_menu_password(id, item):
    call password_dialog(id)
    return 0
end

function on_menu_sign_in_again(id, item):
    call oauth_sign_in_again(id)
    return 0
end

# Text potvrzeni odebrani: u uctu OAuth neni heslo, ale prihlaseni (a u Googlu se pristup Posty i odvola)
function remove_text(a):
    if a.get("auth", "") == "oauth":
        p = oauth.provider(String(a.get("provider", "")))
        if len(p) > 0 and p.get("revoke_url", "") != "":
            return i18n.TF("Saved messages and the sign-in are removed from this computer, and Mail’s access to your %s account is revoked. Nothing is deleted on the server.", [p["name"]])
        end
        return i18n.T("Saved messages and the sign-in are removed from this computer. Nothing is deleted on the server.")
    end
    return i18n.T("Saved messages and the password are removed from this computer. Nothing is deleted on the server.")
end

function on_menu_remove(id, item):
    a = account(id)
    if confirm(i18n.TF("Remove %s?", [a.get("email", "")]), remove_text(a), i18n.T("Remove")):
        call request("remove_account", {"account": id}, {})
    end
    return 0
end

function on_menu_shortcuts(item):
    text = "↑ ↓\t" + i18n.T("Previous / next message") + "\nEnter\t" + i18n.T("Read the message text") + "\nDelete\t" + i18n.T("Move to Trash") + "\nCtrl+Shift+U\t" + i18n.T("Mark as read / unread") + "\nCtrl+F\t" + i18n.T("Filter the message list; in the message: find in the text") + "\nF5, Ctrl+Shift+N\t" + i18n.T("Get mail") + "\nCtrl+N\t" + i18n.T("New message") + "\nCtrl+R\t" + i18n.T("Reply") + "\nCtrl+Shift+R\t" + i18n.T("Reply all") + "\nCtrl+Shift+F\t" + i18n.T("Forward") + "\nCtrl+Enter\t" + i18n.T("Send (in the message window)") + "\nCtrl+P\t" + i18n.T("Print") + "\nCtrl+ +/−/0\t" + i18n.T("Text size of the message") + "\nCtrl+Q\t" + i18n.T("Close Mail")
    call message_box(i18n.T("Keyboard Shortcuts"), text)
    return 0
end

# ---- pridani uctu -------------------------------------------------------------------------------------------------

function field(grid, row, title, widget):
    l = label(title, "")
    call gtk.widget_set_halign(l, gtk.ALIGN_END)
    call gtk.grid_attach(grid, l, 0, row, 1, 1)
    call gtk.widget_set_hexpand(widget, True)
    call gtk.grid_attach(grid, widget, 1, row, 1, 1)
    return widget
end

function security_combo(value):
    c = gtk.combo_box_text_new()
    call gtk.combo_box_text_append(c, "ssl", "SSL/TLS")
    call gtk.combo_box_text_append(c, "starttls", "STARTTLS")
    call mg.combo_box_set_active_id(c, value)
    return c
end

# ---- heslo: tlacitko oka a napoveda poskytovatele ------------------------------------------------------------

# Pole hesla s tlacitkem oka (zobrazit/skryt); vraci [radek, pole, oko]. Tlacitko je v poradi Tab hned za
# polem (mezernik prepne), popisek pro ctecku obrazovky a tooltip. Heslo se nikam nezapisuje.
function password_entry():
    row = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_add_class(row, "linked")
    entry = gtk.entry_new()
    call gtk.entry_set_visibility(entry, False)
    call mg.entry_set_input_purpose(entry, 8)
    call gtk.widget_set_hexpand(entry, True)
    call gtk.box_pack_start(row, entry, True, True, 0)
    eye = mg.toggle_button_new_empty()
    call gtk.box_pack_start(row, eye, False, False, 0)
    call update_eye(eye, False)
    call gtk.connect_data(eye, "toggled", 0, on_eye_toggled, entry)
    return [row, entry, eye]
end

function update_eye(eye, visible):
    tip = i18n.T("Show password")
    names = ["view-reveal-symbolic", "view-visible-symbolic"]
    if visible:
        tip = i18n.T("Hide password")
        names = ["view-conceal-symbolic", "view-hidden-symbolic"]
    end
    call gtk.button_set_image(eye, icon(names, 1))
    call gtk.widget_set_tooltip(eye, tip)
    call gtk.accessible_name(eye, tip)
    return 0
end

function on_eye_toggled(entry, eye):
    visible = gtk.toggle_button_get_active(eye)
    call gtk.entry_set_visibility(entry, visible)
    call update_eye(eye, visible)
    return 0
end

# Napoveda k heslu u znameho poskytovatele: [text, popisek tlacitka, adresa]; prazdny text = nic
function provider_hint(id, domain):
    p = provider.info(id)
    if len(p) == 0:
        return ["", "", ""]
    end
    if id == "google":
        text = i18n.T("Google requires an app password: turn on 2-Step Verification for your Google account, then create an app password and enter it here instead of your normal password.")
        if provider.workspace(id, domain):
            text = text + " " + i18n.T("If your organization manages the account, its administrator must allow app passwords.")
        end
        return [text, i18n.T("Create App Password"), p["url"]]
    elif id == "microsoft":
        return [i18n.T("Microsoft no longer accepts passwords from mail apps for Outlook.com, Hotmail, Live and Microsoft 365 mailboxes – only “Sign in with Microsoft”, which Mail does not support yet. Until then, read this mailbox in Outlook on the web."), i18n.T("Open Outlook on the Web"), p["webmail"]]
    elif id == "yahoo" or id == "aol":
        return [i18n.TF("%s requires an app password: open the account security settings, create an app password for Mail and enter it here instead of your normal password.", [p["name"]]), i18n.T("Create App Password"), p["url"]]
    elif id == "icloud":
        return [i18n.T("iCloud Mail requires an app-specific password: turn on two-factor authentication for your Apple Account, then in Sign-In and Security choose App-Specific Passwords, create one and enter it here."), i18n.T("Create App Password"), p["url"]]
    elif id == "seznam":
        return [i18n.T("Seznam: use your normal password. With two-factor authentication turned on, create an app password in your Seznam account security settings instead. If signing in fails, allow IMAP access in the mail settings."), i18n.T("Open Seznam Account"), p["url"]]
    elif id == "centrum":
        return [i18n.T("Centrum, Atlas and Volný: use your normal password. If signing in fails, check in the webmail settings that access by mail apps (IMAP) is allowed for your mailbox."), i18n.T("Open Webmail"), p["webmail"]]
    elif id == "gmx":
        return [i18n.T("GMX and WEB.DE: first allow access by mail apps (POP3/IMAP) in the webmail settings, then use your normal password."), i18n.T("Open Webmail"), p["webmail"]]
    end
    return ["", "", ""]
end

# Napoveda do okna: box [text, tlacitko]; vraci {"box", "label", "button", "url", "id"}
function hint_widgets():
    box = gtk.box_new(gtk.VERTICAL, 6)
    call gtk.widget_add_class(box, "provider-hint")
    call gtk.widget_set_no_show_all(box, True)
    l = label("", "small")
    call gtk.label_set_line_wrap(l, True)
    call gtk.label_set_max_width_chars(l, 56)
    call gtk.box_pack_start(box, l, False, False, 0)
    b = gtk.button_new("")
    call gtk.widget_set_halign(b, gtk.ALIGN_START)
    call gtk.box_pack_start(box, b, False, False, 0)
    h = {"box": box, "label": l, "button": b, "url": "", "id": ""}
    call gtk.connect_data(b, "clicked", 0, on_hint_button, h)
    return h
end

function show_hint(h, id, domain):
    hint = provider_hint(id, domain)
    h["id"] = id
    h["url"] = hint[2]
    if hint[0] == "":
        call gtk.widget_hide(h["box"])
        return 0
    end
    call gtk.label_set_text(h["label"], hint[0])
    call gtk.button_set_label(h["button"], hint[1])
    call gtk.widget_set_tooltip(h["button"], hint[2])
    call gtk.widget_show(h["label"])
    if hint[2] != "":
        call gtk.widget_show(h["button"])
    else:
        call gtk.widget_hide(h["button"])
    end
    call gtk.widget_show(h["box"])
    return 0
end

function on_hint_button(h, button):
    call open_url(h["url"])
    return 0
end

# Otevreni stranky poskytovatele v prohlizeci (testy: LUXOS_MAIL_OPEN_URL_LOG = soubor misto prohlizece)
function open_url(url):
    # jen HTTPS (testovaci poskytovatel OAuth na http://127.0.0.1 - jen tento pocitac)
    if url == "" or not (url.startswith("https://") or url.startswith("http://127.0.0.1:")):
        return 0
    end
    log_path = env.get("LUXOS_MAIL_OPEN_URL_LOG", "")
    if log_path != None and log_path != "":
        safe:
            prev = ""
            if exists(log_path):
                prev = readfile(log_path)
            end
            call writefile(log_path, prev + url + "\n")
        end
        return 0
    end
    call glib.spawn_quiet(["xdg-open", url])
    return 0
end

# ---- prihlaseni u poskytovatele (OAuth2 v prohlizeci) ------------------------------------------------------------

# Blok v okne pridani uctu: text, hlavni tlacitko "Prihlasit se Googlem", odkaz "Pouzit radeji heslo aplikace".
# Tlacitko jen s textem (vlastni neutralni vzhled, zadna loga poskytovatelu).
function oauth_widgets():
    box = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.widget_set_no_show_all(box, True)
    l = label("", "small")
    call gtk.label_set_line_wrap(l, True)
    call gtk.label_set_max_width_chars(l, 56)
    call gtk.box_pack_start(box, l, False, False, 0)
    # viditelne upozorneni pred souhlasem u poskytovatele (zasady Google API Services User Data Policy):
    # k cemu Posta pristup pouzije a ze data zustavaji jen v tomto pocitaci
    use = label(i18n.T("Mail uses this access only to download, show and organize your mail on this computer. Your mail and the sign-in stay on this computer and are never sent to LuxOS or anyone else."), "dim small")
    call gtk.label_set_line_wrap(use, True)
    call gtk.label_set_max_width_chars(use, 56)
    call gtk.box_pack_start(box, use, False, False, 0)
    b = gtk.button_new("")
    call gtk.widget_add_class(b, "suggested-action")
    call gtk.box_pack_start(box, b, False, False, 0)
    row = gtk.box_new(gtk.HORIZONTAL, 8)
    alt = gtk.button_new(i18n.T("Use an app password instead"))
    call gtk.button_set_relief(alt, gtk.RELIEF_NONE)
    call gtk.box_pack_start(row, alt, False, False, 0)
    privacy = gtk.button_new(i18n.T("Privacy Policy"))
    call gtk.button_set_relief(privacy, gtk.RELIEF_NONE)
    call gtk.box_pack_end(row, privacy, False, False, 0)
    call gtk.box_pack_start(box, row, False, False, 0)
    w = {"box": box, "label": l, "use": use, "button": b, "alt": alt, "privacy": privacy}
    call gtk.connect(b, "clicked", on_oauth_clicked)
    call gtk.connect(alt, "clicked", on_use_password)
    call gtk.connect(privacy, "clicked", on_privacy_clicked)
    return w
end

# Zasady ochrany soukromi LuxOS (oddil o datech z Google a dalsich poskytovatelu) v prohlizeci
function privacy_url():
    if i18n.lang() == "cs":
        return PRIVACY_URL_CS
    end
    return PRIVACY_URL
end

function on_privacy_clicked(button):
    call open_url(privacy_url())
    return 0
end

# Rezim okna podle poskytovatele: s client ID tlacitko "Prihlasit se ..." (heslo skryte), jinak heslo
function update_auth_mode():
    d = ui["dlg"]
    if len(d) == 0:
        return 0
    end
    p = {}
    if d["provider"] != "" and not d["use_password"]:
        p = oauth.available(d["provider"])
    end
    d["oauth"] = p
    mode = "password"
    if len(p) > 0:
        mode = "oauth"
    end
    call trace("auth-mode " + d["provider"] + " " + mode)
    w = d["signin"]
    if len(p) > 0:
        call gtk.label_set_text(w["label"], i18n.TF("Sign in with your %s account in your web browser. Mail never sees your password.", [p["name"]]))
        call gtk.button_set_label(w["button"], i18n.TF("Sign in with %s", [p["name"]]))
        call gtk.widget_set_no_show_all(w["box"], False)
        call gtk.widget_show_all(w["box"])
        # Microsoft nema heslo aplikace pro IMAP: jen prihlaseni u poskytovatele
        call gtk.widget_set_visible(w["alt"], provider.info(d["provider"]).get("auth", "") == "app_password")
        call gtk.widget_hide(d["pw_row"])
        call gtk.widget_hide(d["pw_label"])
        call gtk.widget_hide(d["hint"]["box"])
        call gtk.widget_hide(d["details"])
        call gtk.widget_hide(d["manual"])
        call gtk.widget_hide(d["ok"])
    else:
        call gtk.widget_hide(w["box"])
        call gtk.widget_show(d["pw_row"])
        call gtk.widget_show(d["pw_label"])
        call gtk.widget_show(d["ok"])
        if d["stage"] == "start":
            call gtk.widget_show(d["manual"])
        else:
            call gtk.widget_show(d["details"])
        end
    end
    return 0
end

function on_use_password(button):
    d = ui["dlg"]
    if len(d) == 0:
        return 0
    end
    call cancel_flow(d)
    call dlg_busy(False)
    call dlg_message("", False)
    d["use_password"] = True
    call update_auth_mode()
    call show_hint(d["hint"], d["provider"], provider.domain_of(gtk.entry_get_text(d["email"])))
    call gtk.widget_grab_focus(d["password"])
    return 0
end

function on_oauth_clicked(button):
    call oauth_begin()
    return 0
end

function oauth_begin():
    d = ui["dlg"]
    if len(d) == 0 or len(d["oauth"]) == 0:
        return 0
    end
    email = gtk.entry_get_text(d["email"]).strip()
    call dlg_busy(True)
    call gtk.widget_set_sensitive(d["signin"]["button"], False)
    call dlg_message(i18n.T("Opening the web browser…"), False)
    d["flow_req"] = request("oauth_start", {"provider": d["oauth"]["id"], "email": email, "name": gtk.entry_get_text(d["name"]).strip()},
                            {"dialog": True})
    return 0
end

function cancel_flow(d):
    if len(d) > 0 and d.get("flow", "") != "":
        call request("oauth_cancel", {"flow": d["flow"]}, {})
        d["flow"] = ""
    end
    return 0
end

# Znovu prihlasit ucet OAuth (vyprsene prihlaseni); vysledek prijde jako udalost oauth_done
function oauth_sign_in_again(id):
    a = account(id)
    p = String(a.get("oauth", {}).get("provider", ""))
    if len(oauth.available(p)) == 0:
        call message_box(i18n.T("Signing in failed"), oauth_kind_text("oauth_config", "", oauth.provider(p).get("name", p), a.get("email", "")))
        return 0
    end
    ui["reauth"] = id
    call request("oauth_start", {"provider": p, "account": id}, {"account": id})
    return 0
end

function on_oauth_started(msg, ctx):
    d = ui["dlg"]
    if ctx.get("dialog", False):
        if len(d) == 0:
            # okno pridani uz je zavrene: prihlaseni zrusit
            if msg.get("ok", False):
                call request("oauth_cancel", {"flow": msg["flow"]}, {})
            end
            return 0
        end
        if not msg.get("ok", False):
            call dlg_busy(False)
            call gtk.widget_set_sensitive(d["signin"]["button"], True)
            call dlg_message(oauth_kind_text(msg.get("kind", ""), msg.get("error", ""), d["oauth"].get("name", ""), ""), True)
            return 0
        end
        d["flow"] = msg["flow"]
        call open_url(msg["url"])
        # znovu kliknout = nove prihlaseni (zavreny panel prohlizece; stare se zrusi)
        call gtk.widget_set_sensitive(d["signin"]["button"], True)
        call dlg_message(i18n.T("Continue in your web browser. Mail adds the account as soon as you have signed in."), False)
        return 0
    end
    if not msg.get("ok", False):
        a = account(ctx.get("account", ""))
        call message_box(i18n.T("Signing in failed"), oauth_kind_text(msg.get("kind", ""), msg.get("error", ""), oauth.provider(String(a.get("oauth", {}).get("provider", ""))).get("name", ""), a.get("email", "")))
        return 0
    end
    ui["reauth_flow"] = msg["flow"]
    call open_url(msg["url"])
    return 0
end

# Okno Posty do popredi (po prihlaseni v prohlizeci je v popredi prohlizec)
function raise_window():
    call gtk.window_present_with_time(ui["window"], gtk.x11_server_time(ui["window"]))
    return 0
end

function on_oauth_done(msg):
    d = ui["dlg"]
    name = oauth.provider(msg.get("provider", "")).get("name", msg.get("provider", ""))
    if len(d) > 0 and d.get("flow", "") != "" and d["flow"] == msg.get("flow", ""):
        d["flow"] = ""
        call dlg_busy(False)
        call gtk.widget_set_sensitive(d["signin"]["button"], True)
        if msg.get("ok", False):
            w = d["window"]
            ui["dlg"] = {}
            call gtk.widget_destroy(w)
            call show_new_account(msg.get("account", ""))
            call raise_window()
        else:
            call raise_window()
            call gtk.window_present(d["window"])
            call dlg_message(oauth_kind_text(msg.get("kind", ""), msg.get("error", ""), name, msg.get("email", "")), True)
        end
        return 0
    end
    if ui.get("reauth_flow", "") != "" and ui["reauth_flow"] == msg.get("flow", ""):
        ui["reauth_flow"] = ""
        call raise_window()
        if not msg.get("ok", False):
            a = account(ui.get("reauth", ""))
            call message_box(i18n.T("Signing in failed"), oauth_kind_text(msg.get("kind", ""), msg.get("error", ""), name, a.get("email", "")))
        end
    end
    return 0
end

function oauth_needs_sign_in(kind):
    return kind == "oauth_expired" or kind == "auth" or kind == "oauth_config" or kind == "oauth_failed"
end

# Text chyby prihlaseni u poskytovatele (okno pridani, Prihlasit se znovu)
function oauth_kind_text(kind, detail, name, email):
    if kind == "oauth_denied":
        return i18n.TF("Signing in with %s was cancelled in the browser.", [name])
    elif kind == "oauth_timeout":
        return i18n.T("Signing in in the browser did not finish in time. Try again.")
    elif kind == "oauth_config":
        return i18n.TF("Signing in with %s is not set up on this computer.", [name])
    elif kind == "oauth_other_account":
        return i18n.TF("You signed in as %s in the browser, but this account is %s. Sign in with the same account.", [detail, email])
    elif kind == "oauth_listen":
        return i18n.T("Mail could not prepare signing in on this computer.") + server_reason(detail)
    elif kind == "connect":
        return i18n.TF("Cannot reach %s. Check your internet connection.", [name])
    elif kind == "auth" or kind == "nooauth":
        return i18n.TF("The mail server did not accept the %s sign-in.", [name]) + server_reason(detail)
    elif kind == "notconnected":
        # Microsoft prijal token, ale schranku neotevrel ani po zachrane ve sluzbe (jina adresa, token jen pro
        # Outlook, jiny server): zbyva nastaveni uctu u Microsoftu
        if name == "Microsoft":
            return i18n.T("Microsoft accepted the sign-in, but did not open the mailbox for Mail. On outlook.com open Settings, Mail, Forwarding and IMAP, turn on \"Let devices and apps use IMAP\" and save. If Microsoft asks you to confirm the sign-in at account.live.com/activity, choose \"This was me\". Then try again.") + server_reason(detail)
        end
        return i18n.TF("%s accepted the sign-in, but the mail server did not open the mailbox. Try again later.", [name]) + server_reason(detail)
    elif kind == "keyring":
        return i18n.T("The sign-in could not be saved in the keyring.") + " " + detail
    elif kind == "cert" or kind == "timeout" or kind == "closed":
        return kind_text({"kind": kind, "error": detail}, name)
    end
    return i18n.TF("Signing in with %s failed.", [name]) + server_reason(detail)
end

# Text pruhu u uctu OAuth
function oauth_account_text(a, kind, detail):
    name = oauth.provider(String(a.get("oauth", {}).get("provider", ""))).get("name", "")
    email = a.get("email", "")
    if kind == "oauth_expired":
        return i18n.TF("Your %s sign-in for %s has expired. Sign in again to keep getting new mail.", [name, email])
    elif kind == "auth":
        return i18n.TF("%s did not accept the sign-in for %s. Sign in again.", [name, email]) + server_reason(detail)
    elif kind == "oauth_config":
        return oauth_kind_text(kind, detail, name, email)
    elif kind == "oauth_server" or kind == "connect":
        return i18n.TF("Cannot reach %s to renew the sign-in. Mail tries again later.", [name])
    end
    return oauth_kind_text(kind, detail, name, email)
end

function on_oauth_config(unused, output, status):
    call update_auth_mode()
    return 0
end

# [radek, port, zabezpeceni]: "993  Zabezpeceni [SSL/TLS]"
function port_security_row(value):
    row = gtk.box_new(gtk.HORIZONTAL, 10)
    port = gtk.entry_new()
    call gtk.entry_set_width_chars(port, 6)
    call gtk.box_pack_start(row, port, False, False, 0)
    call gtk.box_pack_start(row, label(i18n.T("Security"), ""), False, False, 0)
    combo = security_combo(value)
    call gtk.widget_set_hexpand(combo, True)
    call gtk.box_pack_start(row, combo, True, True, 0)
    return [row, port, combo]
end

function on_add_account_clicked(widget):
    return open_add_dialog("", "")
end

# Uvitani: s uctem LuxAI predvyplni registracni e-mail (bezne pridani: heslo, automaticke nalezeni)
function on_welcome_add_clicked(widget):
    u = luxai.account_user()
    return open_add_dialog(u.get("email", ""), "")
end

# prefill = e-mail predem, note = vysvetleni nad poli (napr. ucet LuxAI nema schranku na serveru LuxAI)
function open_add_dialog(prefill, note):
    if len(ui["dlg"]) > 0:
        call gtk.window_present(ui["dlg"]["window"])
        return 0
    end
    win = gtk.window_new(i18n.T("Add Account"))
    call gtk.window_set_transient_for(win, ui["window"])
    call gtk.window_set_modal(win, True)
    call gtk.window_set_default_size(win, 460, -1)
    call gtk.window_set_resizable(win, False)
    # okno roste (nastaveni serveru, napoveda, chyba): drzet uprostred, aby tlacitka nezmizela pod okrajem
    call gtk.window_set_position(win, gtk.WIN_POS_CENTER_ALWAYS)
    call gtk.window_set_icon_list(win, "luxos-mail")
    box = gtk.box_new(gtk.VERTICAL, 10)
    call gtk.widget_add_class(box, "dialog-box")
    call gtk.box_pack_start(box, label(i18n.T("Add an Email Account"), "list-title"), False, False, 0)
    hint_text = i18n.T("Mail finds the server settings for most providers automatically.")
    if note != "":
        hint_text = note + "\n" + hint_text
    end
    hint = label(hint_text, "dim small")
    call gtk.label_set_line_wrap(hint, True)
    call gtk.box_pack_start(box, hint, False, False, 0)
    grid = gtk.grid_new()
    call gtk.grid_set_row_spacing(grid, 8)
    call gtk.grid_set_column_spacing(grid, 10)
    name = field(grid, 0, i18n.T("Your name"), gtk.entry_new())
    call gtk.entry_set_placeholder_text(name, i18n.T("Optional"))
    email = field(grid, 1, i18n.T("Email"), gtk.entry_new())
    call gtk.entry_set_placeholder_text(email, "name@example.com")
    call mg.entry_set_input_purpose(email, 5)
    pw = password_entry()
    # popisek zvlast: v rezimu "Prihlasit se ..." se skryva s polem
    pw_label = label(i18n.T("Password"), "")
    call gtk.widget_set_halign(pw_label, gtk.ALIGN_END)
    call gtk.grid_attach(grid, pw_label, 0, 2, 1, 1)
    call gtk.widget_set_hexpand(pw[0], True)
    call gtk.grid_attach(grid, pw[0], 1, 2, 1, 1)
    password = pw[1]
    call gtk.box_pack_start(box, grid, False, False, 0)
    hint = hint_widgets()
    call gtk.box_pack_start(box, hint["box"], False, False, 0)
    signin = oauth_widgets()
    call gtk.box_pack_start(box, signin["box"], False, False, 0)

    # nastaveni serveru (po hledani)
    details = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.widget_set_no_show_all(details, True)
    found = label("", "dim small")
    call gtk.label_set_line_wrap(found, True)
    call gtk.box_pack_start(details, found, False, False, 0)
    g2 = gtk.grid_new()
    call gtk.grid_set_row_spacing(g2, 8)
    call gtk.grid_set_column_spacing(g2, 10)
    # port a zabezpeceni na jednom radku (okno se vejde i na nizsi obrazovku i s napovedou a chybou)
    host = field(g2, 0, i18n.T("Incoming server (IMAP)"), gtk.entry_new())
    ps = port_security_row("ssl")
    call field(g2, 1, i18n.T("Port"), ps[0])
    port = ps[1]
    sec = ps[2]
    user = field(g2, 2, i18n.T("User name"), gtk.entry_new())
    shost = field(g2, 3, i18n.T("Outgoing server (SMTP)"), gtk.entry_new())
    ps = port_security_row("starttls")
    call field(g2, 4, i18n.T("Port"), ps[0])
    sport = ps[1]
    ssec = ps[2]
    call gtk.box_pack_start(details, g2, False, False, 0)
    call gtk.box_pack_start(box, details, False, False, 0)

    status = gtk.box_new(gtk.HORIZONTAL, 8)
    spinner = mg.spinner_new()
    call gtk.box_pack_start(status, spinner, False, False, 0)
    message = label("", "small")
    call gtk.label_set_line_wrap(message, True)
    call gtk.label_set_max_width_chars(message, 52)
    call gtk.box_pack_start(status, message, True, True, 0)
    call gtk.box_pack_start(box, status, False, False, 0)

    buttons = gtk.box_new(gtk.HORIZONTAL, 8)
    manual = gtk.button_new(i18n.T("Configure Manually"))
    call gtk.button_set_relief(manual, gtk.RELIEF_NONE)
    call gtk.connect(manual, "clicked", on_dlg_manual)
    call gtk.box_pack_start(buttons, manual, False, False, 0)
    ok = gtk.button_new(i18n.T("Continue"))
    call gtk.widget_add_class(ok, "suggested-action")
    call gtk.connect(ok, "clicked", on_dlg_ok)
    call gtk.box_pack_end(buttons, ok, False, False, 0)
    cancel = gtk.button_new(i18n.T("Cancel"))
    call gtk.connect(cancel, "clicked", on_dlg_cancel)
    call gtk.box_pack_end(buttons, cancel, False, False, 0)
    call gtk.box_pack_start(box, buttons, False, False, 6)
    call gtk.container_add(win, box)
    ui["dlg"] = {"window": win, "name": name, "email": email, "password": password, "details": details, "found": found,
                 "host": host, "port": port, "sec": sec, "user": user, "shost": shost, "sport": sport, "ssec": ssec,
                 "spinner": spinner, "message": message, "ok": ok, "manual": manual, "stage": "start", "busy": False, "smtp": {},
                 "eye": pw[2], "hint": hint, "provider": "", "email_text": "", "pw_row": pw[0], "pw_label": pw_label,
                 "signin": signin, "oauth": {}, "use_password": False, "flow": "", "flow_req": 0}
    call gtk.connect(email, "activate", on_dlg_activate)
    call gtk.connect(email, "changed", on_dlg_email_changed)
    call gtk.connect(password, "activate", on_dlg_activate)
    call gtk.connect(win, "delete-event", on_dlg_delete)
    call gtk.widget_show_all(win)
    if prefill != "":
        call gtk.entry_set_text(email, prefill)
        call on_dlg_email_changed(email)
        if len(ui["dlg"]["oauth"]) > 0:
            call gtk.widget_grab_focus(signin["button"])
        else:
            call gtk.widget_grab_focus(password)
        end
    else:
        call gtk.widget_grab_focus(email)
    end
    # client ID z luxos.lux-ai.cz (bez noveho baliku), nejvys jednou denne, na pozadi
    if oauth.remote_due():
        call glib.spawn_capture([self_exe(), "--oauth-config"], on_oauth_config, 0)
    end
    return 0
end

# Napoveda hned podle domeny (bez site); po hledani serveru i podle MX (Google Workspace, Microsoft 365).
# Jina adresa po nalezeni serveru: znovu hledat (nastaveni patrila puvodni adrese).
function on_dlg_email_changed(entry):
    d = ui["dlg"]
    if len(d) == 0:
        return 0
    end
    email = gtk.entry_get_text(d["email"]).strip()
    if email == d["email_text"]:
        return 0
    end
    d["email_text"] = email
    domain = provider.domain_of(email)
    id = provider.by_domain(domain)
    if d["stage"] != "start" and not d["busy"]:
        call gtk.widget_hide(d["details"])
        call gtk.widget_show(d["manual"])
        call gtk.button_set_label(d["ok"], i18n.T("Continue"))
        call dlg_message("", False)
        d["stage"] = "start"
    end
    d["provider"] = id
    d["use_password"] = False
    call show_hint(d["hint"], id, domain)
    call update_auth_mode()
    return 0
end

function dlg_message(text, error):
    d = ui["dlg"]
    call gtk.label_set_text(d["message"], text)
    call gtk.widget_set_class(d["message"], "error", error)
    return 0
end

function dlg_busy(on):
    d = ui["dlg"]
    d["busy"] = on
    call mg.spinner_set(d["spinner"], on)
    call gtk.widget_set_sensitive(d["ok"], not on)
    return 0
end

function on_dlg_activate(entry):
    call on_dlg_ok(entry)
    return 0
end

function on_dlg_delete(event, window):
    call cancel_flow(ui["dlg"])
    ui["dlg"] = {}
    return False
end

function on_dlg_cancel(button):
    w = ui["dlg"]["window"]
    call cancel_flow(ui["dlg"])
    ui["dlg"] = {}
    call gtk.widget_destroy(w)
    return 0
end

function show_details(info):
    d = ui["dlg"]
    imap = info.get("imap", {})
    smtp = info.get("smtp", {})
    email = gtk.entry_get_text(d["email"]).strip()
    call gtk.entry_set_text(d["host"], String(imap.get("host", "")))
    call gtk.entry_set_text(d["port"], String(imap.get("port", 993)))
    call mg.combo_box_set_active_id(d["sec"], String(imap.get("security", "ssl")))
    u = String(imap.get("user", ""))
    if u == "":
        u = email
    end
    call gtk.entry_set_text(d["user"], u)
    call gtk.entry_set_text(d["shost"], String(smtp.get("host", "")))
    sp = smtp.get("port", 587)
    call gtk.entry_set_text(d["sport"], String(sp))
    call mg.combo_box_set_active_id(d["ssec"], String(smtp.get("security", "starttls")))
    # no_show_all chrani box jen pri otevreni okna; widget_show_all na nem s no_show_all nic neukaze
    # (pole serveru by zustala skryta - ani rucni nastaveni by neslo upravit)
    call gtk.widget_set_no_show_all(d["details"], False)
    call gtk.widget_show_all(d["details"])
    call gtk.widget_hide(d["manual"])
    call gtk.button_set_label(d["ok"], i18n.T("Sign In"))
    d["stage"] = "details"
    return 0
end

function on_dlg_manual(button):
    domain = ""
    email = gtk.entry_get_text(ui["dlg"]["email"]).strip()
    at = email.find("@")
    if at >= 0:
        domain = email[at + 1:]
    end
    call show_details({"imap": {"host": "mail." + domain, "port": 993, "security": "ssl", "user": email}, "smtp": {"host": "mail." + domain, "port": 587, "security": "starttls"}})
    call gtk.label_set_text(ui["dlg"]["found"], i18n.T("Enter the server settings from your email provider."))
    call gtk.widget_show(ui["dlg"]["found"])
    return 0
end

function on_dlg_ok(button):
    d = ui["dlg"]
    if len(d) == 0 or d["busy"]:
        return 0
    end
    email = gtk.entry_get_text(d["email"]).strip()
    password = gtk.entry_get_text(d["password"])
    if email.find("@") <= 0 or email.find(".") < 0:
        call dlg_message(i18n.T("Enter a valid email address."), True)
        return 0
    end
    if len(d["oauth"]) > 0:
        call oauth_begin()
        return 0
    end
    # neznamy poskytovatel: hledat i bez hesla (Google Workspace / Microsoft 365 na vlastni domene se pozna
    # az podle MX a pak staci "Prihlasit se ...")
    if password == "" and not (d["stage"] == "start" and d["provider"] == ""):
        call dlg_message(i18n.T("Enter your password."), True)
        call gtk.widget_grab_focus(d["password"])
        return 0
    end
    if d["stage"] == "start":
        call dlg_busy(True)
        call dlg_message(i18n.T("Looking up the server settings…"), False)
        call glib.spawn_capture([self_exe(), "--discover", email], on_discovered, email)
        return 0
    end
    port = mime.to_int(gtk.entry_get_text(d["port"]), 993)
    sport = mime.to_int(gtk.entry_get_text(d["sport"]), 587)
    sec = gtk.combo_box_text_get_active_text(d["sec"])
    security = "ssl"
    if sec == "STARTTLS":
        security = "starttls"
    end
    ssec = "starttls"
    if gtk.combo_box_text_get_active_text(d["ssec"]) == "SSL/TLS":
        ssec = "ssl"
    end
    host = gtk.entry_get_text(d["host"]).strip()
    if host == "":
        call dlg_message(i18n.T("Enter the incoming server."), True)
        return 0
    end
    call dlg_busy(True)
    call dlg_message(i18n.TF("Signing in to %s…", [host]), False)
    req = {"email": email, "name": gtk.entry_get_text(d["name"]).strip(), "password": password,
           "imap": {"host": host, "port": port, "security": security, "user": gtk.entry_get_text(d["user"]).strip()},
           "smtp": {"host": gtk.entry_get_text(d["shost"]).strip(), "port": sport, "security": ssec, "user": gtk.entry_get_text(d["user"]).strip()}}
    prov = d["provider"]
    if prov == "":
        prov = provider.detect(provider.domain_of(email), host, [])
    end
    req["provider"] = prov
    call request("add_account", req, {"email": email})
    return 0
end

function on_discovered(email, output, status):
    d = ui["dlg"]
    if len(d) == 0:
        return 0
    end
    call dlg_busy(False)
    if gtk.entry_get_text(d["email"]).strip() != email:
        # adresa se behem hledani zmenila: vysledek patri jine adrese
        call dlg_message("", False)
        return 0
    end
    info = None
    safe:
        info = json.decode(output)
    end
    if type(info) != "Dictionary":
        info = {"error": "notfound", "imap": {}, "smtp": {}}
    end
    source = info.get("source", "")
    if info.get("error", "") == "cert":
        call show_details(info)
        call gtk.label_set_text(d["found"], "")
        call dlg_message(i18n.TF("The security certificate of %s is not valid (%s). Mail does not connect to protect your password. Check the server name with your provider.", [String(info["imap"].get("host", "")), String(info.get("cert_error", ""))]), True)
        return 0
    end
    if len(info.get("imap", {})) == 0:
        call on_dlg_manual(0)
        call dlg_message(i18n.T("The server settings were not found automatically. Enter them below."), True)
        return 0
    end
    call show_details(info)
    prov = String(info.get("provider", ""))
    if prov != "" and len(provider.info(prov)) > 0:
        d["provider"] = prov
        call show_hint(d["hint"], prov, provider.domain_of(email))
    end
    call update_auth_mode()
    text = ""
    if source == "autoconfig":
        text = i18n.T("Settings provided by your email provider.")
    elif source == "ispdb" or source == "ispdb-mx":
        text = i18n.T("Settings found in the Thunderbird provider database.")
    elif source == "srv":
        text = i18n.T("Settings found in the DNS records of your domain.")
    else:
        text = i18n.T("Settings guessed from your address – please check them.")
    end
    call gtk.label_set_text(d["found"], text)
    call gtk.widget_show(d["found"])
    call dlg_message("", False)
    if len(d["oauth"]) == 0 and gtk.entry_get_text(d["password"]) == "":
        call dlg_message(i18n.T("Enter your password."), False)
        call gtk.widget_grab_focus(d["password"])
    end
    return 0
end

# Odmitnute heslo u znameho poskytovatele: co udelat (heslo aplikace, OAuth jeste neni); "" = obecny text
function provider_auth_text(id, kind):
    p = provider.info(id)
    if len(p) == 0:
        return ""
    end
    if kind == "oauthonly" or p["auth"] == "oauth":
        if len(oauth.available(id)) > 0:
            return i18n.TF("%s accepts only “Sign in with %s”, not a password.", [p["name"], p["name"]])
        end
        return i18n.TF("%s accepts only “Sign in with %s” (OAuth), not a password. Mail does not support it yet – use the webmail for now.", [p["name"], p["name"]])
    end
    if p["auth"] == "app_password":
        if id == "google":
            return i18n.T("Google did not accept the password. Google accepts only an app password here, not your normal Google password: turn on 2-Step Verification and create an app password.")
        end
        return i18n.TF("%s did not accept the password. Use an app password, not your normal password.", [p["name"]])
    end
    return ""
end

# Duvod od serveru do zavorky (sluzba ho uz ocistila od ridicich znaku; tady jen zkraceni)
function server_reason(detail):
    d = String(detail).strip()
    if d == "":
        return ""
    end
    if len(d) > 300:
        d = d[0:297] + "..."
    end
    return " (" + i18n.T("Server:") + " " + d + ")"
end

function kind_text(msg, host, prov=""):
    kind = msg.get("kind", "")
    detail = msg.get("error", "")
    if kind == "auth" or kind == "oauthonly":
        t = provider_auth_text(prov, kind)
        if t == "" and kind == "oauthonly":
            return i18n.TF("%s does not accept passwords from mail apps, only sign-in with a token (OAuth), which Mail does not support for this provider yet.", [host])
        end
        if t == "":
            t = i18n.T("The email address or password is not correct.")
        end
        return t + server_reason(detail)
    elif kind == "cert":
        return i18n.TF("The security certificate of %s is not valid (%s). Mail does not connect to protect your password.", [host, detail])
    elif kind == "connect":
        return i18n.TF("Cannot connect to %s. Check the server name and port.", [host])
    elif kind == "timeout":
        return i18n.TF("%s did not answer in time.", [host])
    elif kind == "nostarttls" or kind == "insecure":
        return i18n.TF("%s does not offer an encrypted connection. Mail does not send your password unencrypted.", [host])
    elif kind == "keyring":
        return i18n.T("The password could not be saved in the keyring.") + " " + detail
    elif kind == "protocol":
        return i18n.T("This is not an IMAP server.") + " " + detail
    elif kind.startswith("luxai_") or kind == "nooauth" or kind == "unavailable":
        return luxai_error_text(kind, detail, "")
    elif kind == "closed":
        return i18n.TF("%s closed the connection.", [host]) + server_reason(detail)
    elif kind == "no" or kind == "error" or kind == "invalid":
        return i18n.T("Signing in failed.") + server_reason(detail)
    end
    if detail == "":
        return i18n.T("Signing in failed.")
    end
    return detail
end

function on_account_added(msg):
    d = ui["dlg"]
    if len(d) == 0:
        call reload_accounts()
        call build_sidebar()
        return 0
    end
    call dlg_busy(False)
    if not msg.get("ok", False):
        prov = d["provider"]
        if prov == "":
            prov = provider.detect(provider.domain_of(gtk.entry_get_text(d["email"])), gtk.entry_get_text(d["host"]).strip(), [])
        end
        call dlg_message(kind_text(msg, gtk.entry_get_text(d["host"]).strip(), prov), True)
        if (msg.get("kind", "") == "auth" or msg.get("kind", "") == "oauthonly") and prov != "":
            call show_hint(d["hint"], prov, provider.domain_of(gtk.entry_get_text(d["email"])))
        end
        return 0
    end
    w = d["window"]
    ui["dlg"] = {}
    call gtk.widget_destroy(w)
    call show_new_account(msg.get("account", ""))
    return 0
end

function show_new_account(id):
    call reload_accounts()
    ui["current"] = {"account": id, "raw": "INBOX", "role": "inbox", "name": i18n.T("Inbox")}
    call build_sidebar()
    call open_mailbox(id, "INBOX", 0)
    call select_side(id, "INBOX")
    return 0
end

# ---- ucet LuxAI: schranky na serveru LuxAI ---------------------------------------------------------------------

function update_welcome():
    if ui["welcome_luxai"] == 0:
        return 0
    end
    u = luxai.account_user()
    if len(u) > 0:
        call gtk.button_set_label(ui["luxai_button"], i18n.TF("Continue as %s", [u["name"]]))
        sub = i18n.T("LuxAI account")
        if u["email"] != "" and u["email"] != u["name"]:
            sub = u["email"] + " · " + sub
        end
        call gtk.label_set_text(ui["luxai_sub"], sub)
        call gtk.widget_show(ui["luxai_button"])
        call gtk.widget_show(ui["luxai_sub"])
        call gtk.widget_show(ui["welcome_luxai"])
        call gtk.button_set_label(ui["welcome_button"], i18n.T("Use Another Account…"))
        call gtk.widget_grab_focus(ui["luxai_button"])
    else:
        call gtk.widget_hide(ui["welcome_luxai"])
        call gtk.button_set_label(ui["welcome_button"], i18n.T("Add Account…"))
        call gtk.widget_grab_focus(ui["welcome_button"])
    end
    return 0
end

function luxai_error_text(kind, detail, address):
    if kind == "luxai_session":
        return i18n.T("Your LuxAI sign-in has expired. Sign in to your LuxAI account again.")
    elif kind == "luxai_signedout":
        return i18n.T("No LuxAI account is signed in on this computer.")
    elif kind == "luxai_denied":
        if address != "":
            return i18n.TF("Your LuxAI account no longer has access to %s.", [address])
        end
        return i18n.T("Your LuxAI account has no access to this mailbox.")
    elif kind == "luxai_rate":
        return i18n.T("Too many requests to LuxAI. Try again in a minute.")
    elif kind == "luxai_server":
        return i18n.T("The LuxAI server is not available right now.") + " (" + detail + ")"
    elif kind == "nooauth":
        return i18n.T("The mail server does not support signing in with a LuxAI account.")
    elif kind == "unavailable":
        return i18n.T("The mail server cannot verify the sign-in right now. Mail tries again later.")
    elif kind == "auth":
        return i18n.TF("The mail server did not accept the LuxAI sign-in for %s.", [address])
    elif kind == "connect":
        return i18n.T("Cannot reach the LuxAI server. Check your internet connection.")
    end
    return detail
end

function on_luxai_clicked(widget):
    return luxai_start()
end

function luxai_start():
    if ui["luxai_busy"]:
        return 0
    end
    ui["luxai_busy"] = True
    call set_busy(True)
    if ui["luxai_button"] != 0:
        call gtk.widget_set_sensitive(ui["luxai_button"], False)
    end
    call request("luxai_mailboxes", {}, {})
    return 0
end

function on_luxai_mailboxes(msg, ctx):
    ui["luxai_busy"] = False
    call set_busy(False)
    if ui["luxai_button"] != 0:
        call gtk.widget_set_sensitive(ui["luxai_button"], True)
    end
    u = luxai.account_user()
    if not msg.get("ok", False):
        kind = msg.get("kind", "")
        if kind == "luxai_session" or kind == "luxai_signedout":
            if confirm(i18n.T("Sign In to LuxAI"), luxai_error_text(kind, "", ""), i18n.T("Sign In…")):
                call luxai_login("mailboxes", "")
            end
        else:
            call message_box(i18n.T("LuxAI Mailboxes"), luxai_error_text(kind, msg.get("error", ""), ""))
        end
        return 0
    end
    boxes = msg.get("mailboxes", [])
    if len(boxes) == 0:
        # ucet nema schranku na serveru LuxAI: bezne pridani s registracnim e-mailem
        call open_add_dialog(u.get("email", ""), i18n.T("Your LuxAI account has no mailbox on the LuxAI server. Add your email account – its address is already filled in."))
        return 0
    end
    call luxai_dialog(boxes, u)
    return 0
end

function luxai_dialog(boxes, u):
    if len(ui["luxdlg"]) > 0:
        call gtk.widget_destroy(ui["luxdlg"]["window"])
        ui["luxdlg"] = {}
    end
    win = gtk.window_new(i18n.T("LuxAI Mailboxes"))
    call gtk.window_set_transient_for(win, ui["window"])
    call gtk.window_set_modal(win, True)
    call gtk.window_set_default_size(win, 460, -1)
    call gtk.window_set_resizable(win, False)
    call gtk.window_set_position(win, gtk.WIN_POS_CENTER_ON_PARENT)
    call gtk.window_set_icon_list(win, "luxos-mail")
    box = gtk.box_new(gtk.VERTICAL, 10)
    call gtk.widget_add_class(box, "dialog-box")
    call gtk.box_pack_start(box, label(i18n.TF("Mailboxes of %s", [u.get("name", "")]), "list-title"), False, False, 0)
    hint = label(i18n.T("Mail signs in with your LuxAI account – no password is needed."), "dim small")
    call gtk.label_set_line_wrap(hint, True)
    call gtk.box_pack_start(box, hint, False, False, 0)
    buttons = {}
    added = []
    first = 0
    for m in boxes:
        row = gtk.box_new(gtk.HORIZONTAL, 10)
        text = gtk.box_new(gtk.VERTICAL, 2)
        call gtk.box_pack_start(text, label(m["address"], "msg-from"), False, False, 0)
        if m.get("display_name", "") != "":
            call gtk.box_pack_start(text, label(m["display_name"], "dim small"), False, False, 0)
        end
        call gtk.box_pack_start(row, text, True, True, 0)
        b = gtk.button_new(i18n.T("Add"))
        if m.get("added", False):
            added.append(m["address"])
            call gtk.button_set_label(b, i18n.T("Added"))
            call gtk.widget_set_sensitive(b, False)
        else:
            call gtk.widget_add_class(b, "suggested-action")
            call gtk.connect_data(b, "clicked", 0, on_luxai_add, m["address"])
            if first == 0:
                first = b
            end
        end
        call gtk.widget_set_valign(b, gtk.ALIGN_CENTER)
        call gtk.box_pack_end(row, b, False, False, 0)
        buttons[m["address"]] = b
        call gtk.box_pack_start(box, row, False, False, 2)
    end
    status = gtk.box_new(gtk.HORIZONTAL, 8)
    spinner = mg.spinner_new()
    call gtk.box_pack_start(status, spinner, False, False, 0)
    message = label("", "small")
    call gtk.label_set_line_wrap(message, True)
    call gtk.label_set_max_width_chars(message, 52)
    call gtk.box_pack_start(status, message, True, True, 0)
    call gtk.box_pack_start(box, status, False, False, 0)
    bar = gtk.box_new(gtk.HORIZONTAL, 8)
    other = gtk.button_new(i18n.T("Use Another Account…"))
    call gtk.button_set_relief(other, gtk.RELIEF_NONE)
    call gtk.connect(other, "clicked", on_luxai_other)
    call gtk.box_pack_start(bar, other, False, False, 0)
    close = gtk.button_new(i18n.T("Close"))
    call gtk.connect(close, "clicked", on_luxai_close)
    call gtk.box_pack_end(bar, close, False, False, 0)
    call gtk.box_pack_start(box, bar, False, False, 6)
    call gtk.container_add(win, box)
    ui["luxdlg"] = {"window": win, "message": message, "spinner": spinner, "busy": False, "buttons": buttons, "added": added, "email": u.get("email", "")}
    call gtk.connect(win, "delete-event", on_luxdlg_delete)
    call gtk.widget_show_all(win)
    if first != 0:
        call gtk.widget_grab_focus(first)
    else:
        call gtk.widget_grab_focus(close)
    end
    return 0
end

function on_luxdlg_delete(event, window):
    ui["luxdlg"] = {}
    return False
end

function on_luxai_close(button):
    if len(ui["luxdlg"]) > 0:
        w = ui["luxdlg"]["window"]
        ui["luxdlg"] = {}
        call gtk.widget_destroy(w)
    end
    return 0
end

function on_luxai_other(button):
    email = ui["luxdlg"].get("email", "")
    call on_luxai_close(button)
    call open_add_dialog(email, "")
    return 0
end

function on_luxai_add(address, button):
    d = ui["luxdlg"]
    if len(d) == 0 or d["busy"]:
        return 0
    end
    d["busy"] = True
    call mg.spinner_set(d["spinner"], True)
    for key in d["buttons"].keys():
        call gtk.widget_set_sensitive(d["buttons"][key], False)
    end
    call gtk.label_set_text(d["message"], i18n.TF("Signing in to %s…", [address]))
    call gtk.widget_set_class(d["message"], "error", False)
    call request("add_luxai_account", {"address": address}, {"address": address})
    return 0
end

function on_luxai_added(msg):
    d = ui["luxdlg"]
    if not msg.get("ok", False):
        text = luxai_error_text(msg.get("kind", ""), msg.get("error", ""), "")
        if msg.get("kind", "") in ["cert", "connect", "timeout", "closed", "tls", "protocol"]:
            text = kind_text(msg, "")
        end
        if len(d) == 0:
            call message_box(i18n.T("Signing in failed"), text)
            return 0
        end
        d["busy"] = False
        call mg.spinner_set(d["spinner"], False)
        for key in d["buttons"].keys():
            if key not in d["added"]:
                call gtk.widget_set_sensitive(d["buttons"][key], True)
            end
        end
        call gtk.label_set_text(d["message"], text)
        call gtk.widget_set_class(d["message"], "error", True)
        if msg.get("kind", "") == "luxai_session" or msg.get("kind", "") == "luxai_signedout":
            call on_luxai_close(0)
            call luxai_login("mailboxes", "")
        end
        return 0
    end
    if len(d) > 0:
        call on_luxai_close(0)
    end
    call show_new_account(msg.get("account", ""))
    return 0
end

# Prihlaseni k uctu LuxAI (luxos-account login); po uspechu dalsi krok: "mailboxes" = znovu nabidka schranek,
# "retry" = znovu pripojit ucet
function account_tool():
    value = env.get("LUXOS_MAIL_ACCOUNT_TOOL", "")
    if value != None and value != "":
        return value
    end
    return glib.find_program_in_path("luxos-account")
end

function luxai_login(next, id):
    tool = account_tool()
    if tool == "":
        call message_box(i18n.T("Sign In to LuxAI"), i18n.T("The LuxAI Account app (luxos-account) is not installed."))
        return 0
    end
    pid = glib.spawn_capture([tool, "login"], on_luxai_login_done, [next, id])
    if pid == 0:
        call log("luxos-account login could not be started")
    end
    return 0
end

function on_luxai_login_done(ctx, output, status):
    if status != 0 or len(luxai.account_user()) == 0:
        call update_welcome()
        return 0
    end
    if len(ui["accounts"]) == 0:
        call update_welcome()
    end
    if ctx[0] == "mailboxes":
        call luxai_start()
    elif ctx[0] == "retry":
        call set_busy(True)
        call request("retry_account", {"account": ctx[1]}, {"account": ctx[1]})
    end
    return 0
end

# ---- nove heslo ---------------------------------------------------------------------------------------------------

function password_dialog(id):
    a = account(id)
    if len(a) == 0:
        return 0
    end
    d = gtk.dialog_new()
    call gtk.window_set_title(d, i18n.T("Password"))
    call gtk.window_set_transient_for(d, ui["window"])
    call gtk.window_set_modal(d, True)
    area = gtk.dialog_get_content_area(d)
    box = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.widget_add_class(box, "dialog-box")
    call gtk.box_pack_start(box, label(i18n.TF("Password for %s", [a["email"]]), "list-title"), False, False, 0)
    hint = hint_widgets()
    call gtk.box_pack_start(box, hint["box"], False, False, 0)
    pw = password_entry()
    entry = pw[1]
    call gtk.entry_set_activates_default(entry, True)
    call gtk.box_pack_start(box, pw[0], False, False, 0)
    call gtk.box_pack_start(area, box, True, True, 0)
    call gtk.dialog_add_button(d, i18n.T("Cancel"), gtk.RESPONSE_CANCEL)
    call gtk.dialog_add_button(d, i18n.T("Sign In"), gtk.RESPONSE_OK)
    call gtk.dialog_set_default_response(d, gtk.RESPONSE_OK)
    call gtk.widget_show_all(d)
    call show_hint(hint, provider.of_account(a), provider.domain_of(a.get("email", "")))
    call gtk.widget_grab_focus(entry)
    response = gtk.dialog_run(d)
    password = gtk.entry_get_text(entry)
    call gtk.widget_destroy(d)
    if response == gtk.RESPONSE_OK and password != "":
        call set_busy(True)
        call request("set_password", {"account": id, "password": password}, {"account": id})
    end
    return 0
end

function on_password_set(msg):
    call set_busy(False)
    if not msg.get("ok", False):
        a = account(ui["current"]["account"])
        call message_box(i18n.T("Signing in failed"), kind_text(msg, String(a.get("imap", {}).get("host", "")), provider.of_account(a)))
    end
    return 0
end

# ---- jedna instance okna -------------------------------------------------------------------------------------------

function ui_socket():
    return store.socket_name("ui-")
end

function handle_ui_request(req):
    op = req.get("op", "")
    if op == "open":
        call open_target(req)
    elif op == "mailto":
        call gtk.window_present(ui["window"])
        call compose_mailto(String(req.get("uri", "mailto:" + req.get("address", ""))))
    elif op == "outbox":
        call open_outbox()
    end
    call gtk.window_present(ui["window"])
    return 0
end

function open_target(req):
    id = req.get("account", "")
    raw = req.get("mailbox", "INBOX")
    uid = mime.to_int(String(req.get("uid", "0")), 0)
    if len(account(id)) == 0:
        call reload_accounts()
    end
    if not select_side(id, raw):
        call build_sidebar()
        call select_side(id, raw)
    end
    call open_mailbox(id, raw, uid)
    call gtk.window_present(ui["window"])
    return 0
end

function on_ui_accept(unused, fd, condition):
    loop:
        conn = luxos_sys.unix_accept(ui["ui_listen"])
        if conn < 0:
            break
        end
        if luxos_sys.peer_uid(conn) != mb.getuid():
            call luxos_sys.close(conn)
            continue
        end
        call glib.fd_add_data(conn, 1 + 8 + 16, on_ui_data, {"fd": conn, "buf": ByteArray()})
    end
    return True
end

function on_ui_data(client, fd, condition):
    data = mb.recv(client["fd"], 65536)
    if data == False:
        return True
    end
    if len(data) == 0:
        call luxos_sys.close(client["fd"])
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
            call handle_ui_request(req)
        end
    end
    return True
end

# Bezi uz okno? Preda mu pozadavek a vrati True
function hand_over(req):
    fd = luxos_sys.unix_connect(ui_socket())
    if fd < 0:
        return False
    end
    call mb.send(fd, json.encode(req) + "\n")
    call luxos_sys.close(fd)
    return True
end

function on_first_idle():
    if not ui["ready_logged"]:
        ui["ready_logged"] = True
        path = env.get("LUXOS_MAIL_READY_FILE", "")
        if path != None and path != "":
            safe:
                call writefile(path, String(mb.monotonic_ms() - ui["started"]) + "\n")
            end
        end
    end
    return False
end

function main(argv):
    ui["started"] = mb.monotonic_ms()
    req = {"op": "present"}
    if len(argv) >= 5 and argv[1] == "--open":
        req = {"op": "open", "account": argv[2], "mailbox": argv[3], "uid": argv[4]}
    elif len(argv) >= 2 and argv[1].lower().startswith("mailto:"):
        req = {"op": "mailto", "address": mailto_address(argv[1]), "uri": argv[1]}
    elif len(argv) >= 2 and argv[1] == "--outbox":
        req = {"op": "outbox"}
    end
    if hand_over(req):
        return 0
    end
    call glib.set_prgname("luxos-mail")
    call glib.set_application_name(i18n.T("Mail"))
    call gtk.init()
    call gtk.css_load(CSS)
    listen = luxos_sys.unix_listen(ui_socket())
    if listen >= 0:
        ui["ui_listen"] = listen
        call glib.fd_add_data(listen, 1, on_ui_accept, 0)
    end
    call build_window()
    call gtk.widget_show_all(ui["window"])
    call gtk.widget_hide(ui["banner"])
    # GtkStack prepne jen na viditelnou stranku: az po show_all
    call reload_accounts()
    if req["op"] == "open":
        call open_target(req)
    else:
        call select_first_inbox()
    end
    call ensure_service()
    call glib.idle_add(on_first_idle)
    call compose.init(compose_host())
    # rozepsane zpravy po padu / vypnuti se otevrou znovu
    call compose.restore_all()
    if req["op"] == "mailto":
        call compose_mailto(req["uri"])
    elif req["op"] == "outbox":
        call open_outbox()
    end
    call gtk.main()
    return 0
end
