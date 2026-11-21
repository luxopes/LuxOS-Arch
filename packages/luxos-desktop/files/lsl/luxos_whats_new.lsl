# LuxOS - Co je noveho bez GTK: novinky z /usr/share/luxos/whats-new/<verze>.json, videna verze, jazyk textu.
# Oddelene od luxos-whats-new.lsl kvuli testum bez displeje (tests/lsl/luxos-whats-new-test.lsl).
#
#   load_notes(slozka) -> {verze: data}      chybne soubory a soubory bez polozek se preskoci
#   pending(notes, videna, aktualni)         verze s novinkami seen < verze <= current, nejnovejsi prvni
#   newer(a, b)                              razeni verzi 0.9.10 > 0.9.9
#   lang_codes(), tr(hodnota, jazyky)        {"en": .., "cs": ..}: prvni dostupny jazyk, jinak prvni text
#   symbolic_file_ok(cesta)                  opravdu jednobarevna (symbolicka) ikona
#   current_version(soubor), read_seen(soubor), mark_seen(soubor, verze)
load env, json
load luxos_glib, glib as glib
load luxos_text as text

function parts(version):
    return version.replace("-", ".").split(".")
end

# -1 / 0 / 1 jako porovnani seznamu cisel (cisla ciselne, ostatni jako text)
function compare(a, b):
    pa = parts(a)
    pb = parts(b)
    for i in range(min(len(pa), len(pb))):
        x = pa[i]
        y = pb[i]
        if text.is_digits(x) and text.is_digits(y):
            if Int(x) != Int(y):
                return -1 if Int(x) < Int(y) else 1
            end
        elif x != y:
            return -1 if x < y else 1
        end
    end
    if len(pa) == len(pb):
        return 0
    end
    return -1 if len(pa) < len(pb) else 1
end

function newer(a, b):
    return compare(a, b) > 0
end

# Nejnovejsi prvni
function by_version(versions):
    out = []
    for v in versions:
        i = len(out)
        out.append(v)
        while i > 0 and newer(v, out[i - 1]):
            out[i] = out[i - 1]
            i -= 1
        end
        out[i] = v
    end
    return out
end

function load_notes(folder):
    notes = {}
    for name in glib.list_dir(folder):
        if not name.endswith(".json"):
            continue
        end
        data = None
        safe:
            data = json.decode(glib.read_text(folder + "/" + name))
        end
        if type(data) == "Dictionary" and len(data.get("items", [])) > 0:
            version = String(data.get("version", ""))
            if version == "" or version == "None":
                version = name[0:len(name) - 5]
            end
            notes[version] = data
        end
    end
    return notes
end

function pending(notes, seen, current):
    out = []
    for v in notes.keys():
        if compare(v, current) <= 0 and (seen == "" or newer(v, seen)):
            out.append(v)
        end
    end
    return by_version(out)
end

function lang_codes():
    lang = env.get("LANGUAGE", "").split(":")[0]
    for name in ["LC_ALL", "LC_MESSAGES", "LANG"]:
        if lang == "":
            lang = env.get(name, "")
        end
    end
    if lang == "":
        lang = "en"
    end
    lang = lang.split(".")[0]
    return [lang, lang.split("_")[0], "en"]
end

function tr(value, langs):
    if type(value) == "String":
        return value
    end
    if type(value) == "Dictionary":
        for code in langs:
            if value.get(code, "") != "":
                return value[code]
            end
        end
        for key in value.keys():
            return String(value[key])
        end
    end
    return ""
end

# WhiteSur ma pod nazvem *-symbolic.svg v apps/scalable odkazy na barevne ikony aplikaci (mark-location-symbolic
# -> preferences-system-search.svg); GTK je prebarvi jednou barvou a z barevne ikony zbude plny ctverec
function symbolic_file_ok(path):
    if path == "" or path == None:
        return False
    end
    real = glib.realpath(path)
    if real == "":
        return False
    end
    base = real[text.rfind(real, "/") + 1:]
    if base.endswith(".symbolic.png") or base.endswith("-symbolic.svg") or base.endswith("-symbolic-rtl.svg"):
        return True
    end
    if not base.endswith(".svg"):
        return False
    end
    svg = glib.read_text(real)
    if svg == "":
        return False
    end
    if len(svg) > 200000:
        svg = svg[0:200000]
    end
    return svg.find("Gradient") < 0 and svg.find("<image") < 0
end

function current_version(path):
    for line in glib.read_text(path).split("\n"):
        if line.startswith("VERSION="):
            return line[8:].strip().replace("\"", "")
        end
    end
    return ""
end

function read_seen(path):
    return glib.read_text(path).strip()
end

function mark_seen(path, version):
    if version == "":
        return 0
    end
    call glib.mkdir_p(path[0:text.rfind(path, "/")])
    return glib.write_atomic(path, version + "\n")
end
