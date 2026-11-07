# Posta LuxOS - ucty a mistni mezipamet.
#   ~/.config/luxos-mail/accounts.json    ucty bez hesel (hesla jsou v klicence Secret Service)
#   ~/.local/share/luxos-mail/<ucet>/
#       mailboxes.tsv                     raw<TAB>jmeno<TAB>oddelovac<TAB>role<TAB>vybiratelna<TAB>neprectene<TAB>celkem
#       m-<hash>/state.json               uidvalidity, uidnext, highestmodseq, nejstarsi stazene UID
#       m-<hash>/index.tsv                jedna zprava na radek (nejnovejsi prvni), viz FIELDS
#       m-<hash>/bodies/<uid>.eml         cela zprava, stazena az pri otevreni
# Zapisuje jen sluzba (luxos-mail --background); okno cte. Soubory a slozky jen pro uzivatele (0600/0700).
load env, json, net
load crypto
load luxos_glib, glib as glib
load mail_bytes as mb

FIELDS = ["uid", "flags", "internal", "date", "from_name", "from_email", "to", "subject", "preview", "size", "att"]

function base_config():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.config"
    end
    return base + "/luxos-mail"
end

function base_data():
    base = env.get("XDG_DATA_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.local/share"
    end
    return base + "/luxos-mail"
end

function ensure_dir(path):
    call glib.mkdir_p(path)
    call mb.chmod(path, 448)
    return path
end

function write_private(path, text):
    call glib.write_atomic(path, text)
    call mb.chmod(path, 384)
    return 0
end

function hash_text(text):
    return crypto.hex(crypto.sha256(text))[0:16]
end

function account_id(email):
    return "a" + hash_text(email.strip().lower())[0:10]
end

# ---- ucty ---------------------------------------------------------------------------------------------------

function accounts_path():
    return base_config() + "/accounts.json"
end

function load_accounts():
    path = accounts_path()
    if not exists(path):
        return []
    end
    data = None
    safe:
        data = json.decode(readfile(path))
    end
    if type(data) != "List":
        return []
    end
    out = []
    for a in data:
        if type(a) == "Dictionary" and type(a.get("id")) == "String" and type(a.get("imap")) == "Dictionary":
            out.append(a)
        end
    end
    return out
end

function save_accounts(accounts):
    call ensure_dir(base_config())
    call write_private(accounts_path(), json.encode(accounts) + "\n")
    return 0
end

function find_account(accounts, id):
    for a in accounts:
        if a["id"] == id:
            return a
        end
    end
    return {}
end

# ---- schranky -----------------------------------------------------------------------------------------------

function account_dir(id):
    return base_data() + "/" + id
end

function mailbox_dir(id, raw):
    return account_dir(id) + "/m-" + hash_text(raw)
end

function esc(value):
    s = String(value)
    if s.find("\\") >= 0:
        s = s.replace("\\", "\\\\")
    end
    if s.find("\t") >= 0:
        s = s.replace("\t", "\\t")
    end
    if s.find("\n") >= 0:
        s = s.replace("\n", "\\n")
    end
    if s.find("\r") >= 0:
        s = s.replace("\r", "")
    end
    return s
end

function unesc(s):
    if s.find("\\") < 0:
        return s
    end
    b = net.bytes(s)
    n = len(b)
    out = ByteArray()
    i = 0
    while i < n:
        c = b[i]
        if c == 92 and i + 1 < n:
            d = b[i + 1]
            if d == 116:
                out.append(9)
            elif d == 110:
                out.append(10)
            else:
                out.append(d)
            end
            i += 2
            continue
        end
        out.append(c)
        i += 1
    end
    return net.text(out)
end

function load_mailboxes(id):
    path = account_dir(id) + "/mailboxes.tsv"
    out = []
    if not exists(path):
        return out
    end
    text = ""
    safe:
        text = readfile(path)
    end
    for line in text.split("\n"):
        if line == "":
            continue
        end
        f = line.split("\t")
        if len(f) < 7:
            continue
        end
        out.append({"raw": unesc(f[0]), "name": unesc(f[1]), "delim": unesc(f[2]), "role": f[3], "selectable": f[4] == "1",
                    "unseen": to_int(f[5]), "total": to_int(f[6])})
    end
    return out
end

function save_mailboxes(id, boxes):
    call ensure_dir(account_dir(id))
    lines = []
    for b in boxes:
        sel = "0"
        if b.get("selectable", True):
            sel = "1"
        end
        lines.append(esc(b["raw"]) + "\t" + esc(b["name"]) + "\t" + esc(b.get("delim", "")) + "\t" + b.get("role", "") + "\t" + sel + "\t" + String(b.get("unseen", 0)) + "\t" + String(b.get("total", 0)))
    end
    call write_private(account_dir(id) + "/mailboxes.tsv", "\n".join(lines) + "\n")
    return 0
end

function to_int(s):
    v = 0
    neg = False
    t = s.strip()
    if t.startswith("-"):
        neg = True
        t = t[1:]
    end
    if t == "":
        return 0
    end
    safe:
        v = Int(t)
    end
    if neg:
        return -v
    end
    return v
end

# ---- stav a index schranky --------------------------------------------------------------------------------------

function load_state(id, raw):
    path = mailbox_dir(id, raw) + "/state.json"
    st = None
    if exists(path):
        safe:
            st = json.decode(readfile(path))
        end
    end
    if type(st) != "Dictionary":
        st = {}
    end
    for key in ["uidvalidity", "uidnext", "highestmodseq", "oldest", "exists"]:
        if type(st.get(key)) != "Int":
            st[key] = 0
        end
    end
    st["raw"] = raw
    return st
end

function save_state(id, raw, st):
    d = ensure_dir(mailbox_dir(id, raw))
    call write_private(d + "/state.json", json.encode(st) + "\n")
    return 0
end

function parse_row(line):
    f = line.split("\t")
    if len(f) < 11:
        return {}
    end
    return {"uid": to_int(f[0]), "flags": f[1], "internal": to_int(f[2]), "date": to_int(f[3]), "from_name": unesc(f[4]),
            "from_email": unesc(f[5]), "to": unesc(f[6]), "subject": unesc(f[7]), "preview": unesc(f[8]), "size": to_int(f[9]),
            "att": f[10] == "1"}
end

function row_line(m):
    att = "0"
    if m.get("att", False):
        att = "1"
    end
    return String(m["uid"]) + "\t" + m.get("flags", "") + "\t" + String(m.get("internal", 0)) + "\t" + String(m.get("date", 0)) + "\t" + esc(m.get("from_name", "")) + "\t" + esc(m.get("from_email", "")) + "\t" + esc(m.get("to", "")) + "\t" + esc(m.get("subject", "")) + "\t" + esc(m.get("preview", "")) + "\t" + String(m.get("size", 0)) + "\t" + att
end

function load_index(id, raw):
    path = mailbox_dir(id, raw) + "/index.tsv"
    out = []
    if not exists(path):
        return out
    end
    text = ""
    safe:
        text = readfile(path)
    end
    for line in text.split("\n"):
        if line != "":
            m = parse_row(line)
            if len(m) > 0:
                out.append(m)
            end
        end
    end
    return out
end

# serazeni: nejnovejsi (cas doruceni, pak UID) prvni
# (sort umi jen cisla a texty: klic = cas * 2^32 + UID, obojí kladne a jedinecne)
function sort_messages(messages):
    by_key = {}
    keys = []
    for m in messages:
        t = max(0, min(m.get("internal", 0), 2147483647))
        key = t * 4294967296 + (m["uid"] & 4294967295)
        by_key[key] = m
        keys.append(key)
    end
    keys.sort()
    out = []
    i = len(keys) - 1
    while i >= 0:
        out.append(by_key[keys[i]])
        i -= 1
    end
    return out
end

function save_index(id, raw, messages):
    d = ensure_dir(mailbox_dir(id, raw))
    lines = []
    for m in messages:
        lines.append(row_line(m))
    end
    call write_private(d + "/index.tsv", "\n".join(lines) + "\n")
    return 0
end

# Priznaky v indexu jako pismena: S prectena, F s hvezdickou, A odpovezeno, D smazana
function flags_letters(flags):
    out = ""
    for f in flags:
        u = String(f).lower()
        if u == "\\seen":
            out = out + "S"
        elif u == "\\flagged":
            out = out + "F"
        elif u == "\\answered":
            out = out + "A"
        elif u == "\\deleted":
            out = out + "D"
        end
    end
    return out
end

function body_path(id, raw, uid):
    return mailbox_dir(id, raw) + "/bodies/" + String(uid) + ".eml"
end

function save_body(id, raw, uid, data):
    d = ensure_dir(mailbox_dir(id, raw) + "/bodies")
    path = d + "/" + String(uid) + ".eml"
    tmp = path + ".tmp"
    call writebytes(tmp, data)
    call mb.chmod(tmp, 384)
    call glib.rename(tmp, path)
    return path
end

function remove_tree(path):
    if glib.is_dir(path):
        for name in glib.list_dir(path):
            call remove_tree(path + "/" + name)
        end
    end
    safe:
        call remove_path(path)
    end
    return 0
end

# Smazani mezipameti schranky (zmena UIDVALIDITY)
function wipe_mailbox(id, raw):
    call remove_tree(mailbox_dir(id, raw))
    return 0
end

# Abstraktni sockety sluzby a okna; LUXOS_MAIL_INSTANCE oddeli testy od skutecne relace
function socket_name(kind):
    suffix = env.get("LUXOS_MAIL_INSTANCE", "")
    if suffix == None:
        suffix = ""
    end
    return "luxos-mail-" + kind + String(mb.getuid()) + suffix
end

# Program okna: vedle sluzby (vyvoj, testy) nebo /usr/bin/luxos-mail
function gui_binary():
    exe = ""
    safe:
        exe = glib.readlink("/proc/self/exe")
    end
    if exe.endswith(" (deleted)"):
        exe = exe[0:len(exe) - 10]
    end
    parts = exe.split("/")
    if len(parts) > 1 and not exe.startswith("/usr/lib/"):
        near = "/".join(parts[0:len(parts) - 1]) + "/luxos-mail"
        if exists(near):
            return near
        end
    end
    return "/usr/bin/luxos-mail"
end

# Program sluzby: vedle luxos-mail (vyvoj, testy) nebo /usr/lib/luxos-mail/luxos-mail-service
function service_binary():
    exe = ""
    safe:
        exe = glib.readlink("/proc/self/exe")
    end
    if exe.endswith(" (deleted)"):
        exe = exe[0:len(exe) - 10]
    end
    parts = exe.split("/")
    if len(parts) > 1:
        near = "/".join(parts[0:len(parts) - 1]) + "/luxos-mail-service"
        if exists(near):
            return near
        end
    end
    return "/usr/lib/luxos-mail/luxos-mail-service"
end
