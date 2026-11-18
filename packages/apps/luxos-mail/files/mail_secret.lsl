# Posta LuxOS - hesla uctu v klicence Secret Service (gnome-keyring) pres secret-tool (libsecret).
# Heslo (u uctu OAuth obnovovaci token) jde programu jen na standardni vstup, nikdy v argumentech ani v souboru.
# Atributy: service=luxos-mail account=<id uctu> (+ email, server pro prehled v aplikaci Hesla a klice).
# LUXOS_MAIL_SECRET_TOOL prepise program (testy).
load env
load luxos_glib, glib as glib

function tool():
    value = env.get("LUXOS_MAIL_SECRET_TOOL", "")
    if value != None and value != "":
        return value
    end
    path = glib.find_program_in_path("secret-tool")
    if path == "":
        return "/usr/bin/secret-tool"
    end
    return path
end

# Jeden pokus o ulozeni: True, nebo text chyby
function store_once(id, email, server, password, label):
    out = ""
    ok = True
    try:
        out = capture_input(tool(), ["store", "--label=" + label, "service", "luxos-mail", "account", id, "email", email, "server", server], password)
    else:
        ok = False
    end
    if not ok:
        return "secret-tool: " + String(last_error())
    end
    if capture_status() != 0:
        err = capture_stderr().strip()
        if err == "":
            err = "secret-tool exited with status " + String(capture_status())
        end
        return err
    end
    return True
end

# Klicenka neni na sbernici (org.freedesktop.secrets se nespustila, napr. relace bez gnome-keyring):
# zkusit ji spustit jako gnome-keyring v prihlaseni (--start: pripoji se k bezici nebo spusti novou;
# zamcenou klicenku odemkne systemovy dotaz na heslo). LUXOS_MAIL_KEYRING_DAEMON prepise program (testy).
function start_keyring():
    prog = env.get("LUXOS_MAIL_KEYRING_DAEMON", "")
    if prog == None or prog == "":
        prog = glib.find_program_in_path("gnome-keyring-daemon")
    end
    if prog == "":
        return False
    end
    ok = True
    try:
        call capture(prog, ["--start", "--components=secrets"])
    else:
        ok = False
    end
    return ok and capture_status() == 0
end

# Chyba, kterou muze vyresit spusteni klicenky (ne odmitnuti uzivatelem ani chybejici program)
function keyring_missing(err):
    e = String(err).lower()
    return e.find("org.freedesktop.secrets") >= 0 or e.find("startservicebyname") >= 0 or e.find("serviceunknown") >= 0 or e.find("was not provided by any .service") >= 0 or e.find("cannot autolaunch") >= 0 or e.find("no such interface") >= 0
end

# True = ulozeno; jinak text chyby (puvodni, anglicky - okno ukaze prelozene vysvetleni a tento text jen
# v Podrobnostech). Ucty OAuth ukladaji misto hesla obnovovaci token (label "LuxOS Mail (Google): ...").
function store(id, email, server, password, label=""):
    if label == "":
        label = "LuxOS Mail: " + email
    end
    r = store_once(id, email, server, password, label)
    if r != True and keyring_missing(r) and start_keyring():
        r = store_once(id, email, server, password, label)
    end
    return r
end

function lookup_once(id):
    out = ""
    ok = True
    try:
        out = capture(tool(), ["lookup", "service", "luxos-mail", "account", id])
    else:
        ok = False
    end
    if not ok:
        return [False, ""]
    end
    if capture_status() != 0:
        return [False, capture_stderr()]
    end
    return [True, out]
end

# Heslo, nebo "" kdyz neni (zamcena klicenka, chybi zaznam); klicenku mimo sbernici zkusi jednou spustit
function lookup(id):
    r = lookup_once(id)
    if not r[0] and keyring_missing(r[1]) and start_keyring():
        r = lookup_once(id)
    end
    if not r[0]:
        return ""
    end
    out = r[1]
    if out.endswith("\n"):
        out = out[0:len(out) - 1]
    end
    return out
end

function clear(id):
    safe:
        call capture(tool(), ["clear", "service", "luxos-mail", "account", id])
    end
    return 0
end
