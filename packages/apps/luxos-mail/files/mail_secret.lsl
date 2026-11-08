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

# True = ulozeno; jinak text chyby. Ucty OAuth ukladaji misto hesla obnovovaci token (label "LuxOS Mail (Google): ...").
function store(id, email, server, password, label=""):
    if label == "":
        label = "LuxOS Mail: " + email
    end
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

# Heslo, nebo "" kdyz neni (zamcena klicenka, chybi zaznam)
function lookup(id):
    out = ""
    ok = True
    try:
        out = capture(tool(), ["lookup", "service", "luxos-mail", "account", id])
    else:
        ok = False
    end
    if not ok or capture_status() != 0:
        return ""
    end
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
