# LuxOS - Nastaveni > Uzivatele: ucty na pocitaci, pridani uctu (dite, rodic, host), typ uctu (spravce/standardni),
# odebrani uctu a zmena vlastniho hesla.
#
# Pres AccountsService (org.freedesktop.Accounts na systemove sbernici, `busctl`): stejne rozhrani pouziva prihlasovaci
# obrazovka i GNOME. Opravneni resi polkit (okno pro heslo spravce ukaze luxos-polkit); zmeny bezi asynchronne
# (spawn_capture), okno se pri cekani nezasekne. Heslo se hashuje v tomto procesu (luxos_crypt, yescrypt) a
# sluzbe jde jen hash - heslo se nikdy neobjevi v argumentech programu.
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_settings_ui as ui
load luxos_crypt as crypt
load luxos_launchpad_model as model
load json
load env

ACCOUNTS = "org.freedesktop.Accounts"
ACCOUNTS_PATH = "/org/freedesktop/Accounts"
USER_IFACE = "org.freedesktop.Accounts.User"
MIN_PASSWORD = 4

app = {"page": 0, "list": 0, "users": [], "me": "", "status": 0, "busy": False,
       "full": 0, "login": 0, "pw1": 0, "pw2": 0, "admin": 0, "add": 0, "my1": 0, "my2": 0,
       "login_edited": False, "confirm": ""}

# ---- AccountsService --------------------------------------------------------------------------------------

function busctl_json(args):
    out = ui.run(["busctl", "--system", "--json=short"] + args)
    if out == "":
        return None
    end
    values = []
    for line in out.split("\n"):
        if line.strip() == "":
            continue
        end
        try:
            values.append(json.decode(line))
        else:
            return None
        end
    end
    return values
end

function value(item):
    if type(item) == "Dictionary" and "data" in item:
        return item["data"]
    end
    return None
end

function read_users():
    users = []
    listed = busctl_json(["call", ACCOUNTS, ACCOUNTS_PATH, ACCOUNTS, "ListCachedUsers"])
    if listed == None or len(listed) == 0:
        return users
    end
    paths = value(listed[0])
    if type(paths) != "List" or len(paths) == 0 or type(paths[0]) != "List":
        return users
    end
    for path in paths[0]:
        props = busctl_json(["get-property", ACCOUNTS, path, USER_IFACE, "UserName", "RealName", "AccountType", "Uid",
                             "SystemAccount"])
        if props == None or len(props) < 5 or value(props[4]) == True:
            continue
        end
        users.append({"path": path, "name": String(value(props[0])), "real": String(value(props[1])),
                      "admin": value(props[2]) == 1, "uid": Int(value(props[3]))})
    end
    return users
end

# ---- zmeny (asynchronne) ----------------------------------------------------------------------------------

function status(message):
    call gtk.label_set_text(app["status"], message)
    call gtk.widget_set_visible(app["status"], message != "")
    return 0
end

function busctl(args, done, bound):
    app["busy"] = True
    call glib.spawn_capture(["busctl", "--system", "--allow-interactive-authorization=yes"] + args, done, bound)
    return 0
end

function on_changed(what, output, status_code):
    app["busy"] = False
    if status_code != 0:
        call status(i18n.T("The change was not made (cancelled or not allowed)."))
    else:
        call status(what)
    end
    call reload()
    return 0
end

function on_type(user, id):
    if id == "" or (id == "admin") == user["admin"]:
        return 0
    end
    return busctl(["call", ACCOUNTS, user["path"], USER_IFACE, "SetAccountType", "i", "1" if id == "admin" else "0"],
                  on_changed, i18n.T("Account type changed."))
end

# Odebrani ve dvou krocich: prvni klik zmeni tlacitko na "Opravdu odebrat?"
function on_remove(user, button):
    if app["confirm"] != user["name"]:
        app["confirm"] = user["name"]
        call gtk.button_set_label(button, i18n.T("Remove with files?"))
        call gtk.widget_add_class(button, "destructive-action")
        return 0
    end
    app["confirm"] = ""
    return busctl(["call", ACCOUNTS, ACCOUNTS_PATH, ACCOUNTS, "DeleteUser", "xb", String(user["uid"]), "true"],
                  on_changed, i18n.T("The user was removed."))
end

function valid_login(name):
    if len(name) == 0 or len(name) > 32:
        return False
    end
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789_-"
    if not (name[0] in "abcdefghijklmnopqrstuvwxyz_"):
        return False
    end
    for ch in name:
        if not (ch in allowed):
            return False
        end
    end
    return True
end

# "Jana Nováková" -> "jana" (prvni slovo bez diakritiky, mala pismena)
function suggest_login(full):
    words = model.fold(full).strip().split(" ")
    out = ""
    for ch in words[0] if len(words) > 0 else "":
        if ch in "abcdefghijklmnopqrstuvwxyz0123456789":
            out = out + ch
        end
    end
    if out != "" and not (out[0] in "abcdefghijklmnopqrstuvwxyz"):
        out = "u" + out
    end
    return out[0:32]
end

function on_full_changed(entry):
    if not app["login_edited"]:
        ui.state["quiet"] = True
        call gtk.entry_set_text(app["login"], suggest_login(gtk.entry_get_text(entry)))
        ui.state["quiet"] = False
    end
    return 0
end

function on_login_changed(entry):
    if not ui.state["quiet"]:
        app["login_edited"] = True
    end
    return 0
end

function exists(name):
    for u in app["users"]:
        if u["name"] == name:
            return True
        end
    end
    return False
end

function on_add(unused):
    full = gtk.entry_get_text(app["full"]).strip()
    login = gtk.entry_get_text(app["login"]).strip()
    pw = gtk.entry_get_text(app["pw1"])
    if full == "" or not valid_login(login):
        return status(i18n.T("Enter a name and a user name (small letters without accents, numbers, - and _)."))
    end
    if exists(login):
        return status(i18n.T("This user name is already taken."))
    end
    if len(pw) < MIN_PASSWORD or pw != gtk.entry_get_text(app["pw2"]):
        return status(i18n.T("The passwords are empty, too short or do not match."))
    end
    hashed = crypt.hash(pw)
    if hashed == "":
        return status(i18n.T("The password could not be prepared."))
    end
    call gtk.widget_set_sensitive(app["add"], False)
    admin = "1" if gtk.switch_get_active(app["admin"]) else "0"
    return busctl(["call", ACCOUNTS, ACCOUNTS_PATH, ACCOUNTS, "CreateUser", "ssi", login, full, admin],
                  on_created, [login, hashed])
end

# Ucet je zalozeny: heslo (jen hash) az na objekt noveho uzivatele
function on_created(job, output, status_code):
    if status_code != 0:
        app["busy"] = False
        call gtk.widget_set_sensitive(app["add"], True)
        call status(i18n.T("The user was not added (cancelled or not allowed)."))
        return 0
    end
    path = ""
    found = busctl_json(["call", ACCOUNTS, ACCOUNTS_PATH, ACCOUNTS, "FindUserByName", "s", job[0]])
    if found != None and len(found) > 0:
        v = value(found[0])
        if type(v) == "List" and len(v) > 0:
            path = String(v[0])
        elif type(v) == "String":
            path = v
        end
    end
    if path == "":
        app["busy"] = False
        call gtk.widget_set_sensitive(app["add"], True)
        call status(i18n.T("The user was added, but the password was not set."))
        call reload()
        return 0
    end
    for e in [app["full"], app["login"], app["pw1"], app["pw2"]]:
        call gtk.entry_set_text(e, "")
    end
    app["login_edited"] = False
    call gtk.widget_set_sensitive(app["add"], True)
    return busctl(["call", ACCOUNTS, path, USER_IFACE, "SetPassword", "ss", job[1], ""], on_changed,
                  i18n.T("The user was added."))
end

function on_my_password(unused):
    pw = gtk.entry_get_text(app["my1"])
    if len(pw) < MIN_PASSWORD or pw != gtk.entry_get_text(app["my2"]):
        return status(i18n.T("The passwords are empty, too short or do not match."))
    end
    hashed = crypt.hash(pw)
    if hashed == "":
        return status(i18n.T("The password could not be prepared."))
    end
    for u in app["users"]:
        if u["name"] == app["me"]:
            call gtk.entry_set_text(app["my1"], "")
            call gtk.entry_set_text(app["my2"], "")
            return busctl(["call", ACCOUNTS, u["path"], USER_IFACE, "SetPassword", "ss", hashed, ""], on_changed,
                          i18n.T("Your password was changed."))
        end
    end
    return status(i18n.T("Your account was not found."))
end

# ---- stranka ----------------------------------------------------------------------------------------------

function password_entry(placeholder):
    e = gtk.entry_new()
    call gtk.entry_set_visibility(e, False)
    call gtk.entry_set_placeholder_text(e, placeholder)
    call gtk.entry_set_width_chars(e, 22)
    return e
end

function text_entry(placeholder):
    e = gtk.entry_new()
    call gtk.entry_set_placeholder_text(e, placeholder)
    call gtk.entry_set_width_chars(e, 22)
    return e
end

function fill_list():
    g = app["list"]
    for child in gtk.container_get_children(g["box"]):
        call gtk.widget_destroy(child)
    end
    g["rows"] = 0
    if len(app["users"]) == 0:
        call ui.row(g, i18n.T("The account service is not available."), "", 0)
    end
    for u in app["users"]:
        title = u["real"] if u["real"] != "" else u["name"]
        if u["name"] == app["me"]:
            hint = u["name"] + " · " + i18n.T("You") + " · " + (i18n.T("Administrator") if u["admin"] else i18n.T("Standard"))
            call ui.row(g, title, hint, 0)
            continue
        end
        box = gtk.box_new(gtk.HORIZONTAL, 6)
        kind = ui.combo([["admin", i18n.T("Administrator")], ["standard", i18n.T("Standard")]],
                        "admin" if u["admin"] else "standard", "", on_type, u)
        remove = gtk.button_new(i18n.T("Remove"))
        call glib.connect_data(remove, "clicked", 0, on_remove, u)
        call gtk.box_pack_start(box, kind, False, False, 0)
        call gtk.box_pack_start(box, remove, False, False, 0)
        call ui.row(g, title, u["name"], box)
    end
    call gtk.widget_show_all(g["box"])
    return 0
end

function reload():
    app["users"] = read_users()
    app["confirm"] = ""
    call fill_list()
    return 0
end

function build(host):
    app["me"] = env.get("USER", "")
    page = ui.page_box()
    app["page"] = page
    app["list"] = ui.group(page, i18n.T("Users"))
    app["status"] = ui.label("", "")
    call gtk.box_pack_start(page, app["status"], False, False, 6)
    call gtk.widget_set_no_show_all(app["status"], True)

    g = ui.group(page, i18n.T("Add User"))
    app["full"] = text_entry(i18n.T("Jane Doe"))
    call gtk.connect(app["full"], "changed", on_full_changed)
    call ui.row(g, i18n.T("Full name"), "", app["full"])
    app["login"] = text_entry("jane")
    call gtk.connect(app["login"], "changed", on_login_changed)
    call ui.row(g, i18n.T("User name"), i18n.T("For signing in; small letters without accents."), app["login"])
    app["pw1"] = password_entry(i18n.T("Password"))
    call ui.row(g, i18n.T("Password"), "", app["pw1"])
    app["pw2"] = password_entry(i18n.T("Password again"))
    call ui.row(g, i18n.T("Confirm password"), "", app["pw2"])
    app["admin"] = gtk.switch_new()
    call ui.row(g, i18n.T("Administrator"), i18n.T("Can install apps and change system settings."), app["admin"])
    app["add"] = gtk.button_new(i18n.T("Add User"))
    call gtk.widget_add_class(app["add"], "suggested-action")
    call gtk.connect(app["add"], "clicked", on_add)
    call ui.row(g, "", "", app["add"])

    g2 = ui.group(page, i18n.T("My Password"))
    app["my1"] = password_entry(i18n.T("New password"))
    call ui.row(g2, i18n.T("New password"), "", app["my1"])
    app["my2"] = password_entry(i18n.T("Password again"))
    call ui.row(g2, i18n.T("Confirm new password"), "", app["my2"])
    change = gtk.button_new(i18n.T("Change Password"))
    call gtk.connect(change, "clicked", on_my_password)
    call ui.row(g2, "", "", change)
    call reload()
    return page
end

function show(host):
    if not app["busy"] and app["page"] != 0:
        call reload()
    end
    return 0
end

function test(command, rest):
    return False
end
