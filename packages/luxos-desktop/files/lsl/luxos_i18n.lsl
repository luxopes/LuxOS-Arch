# LuxOS - preklady pro programy v LSL: T("English") -> text v jazyce uzivatele,
# TF("English %s", [hodnota]) navic dosadi %s/%d (a %% -> %) jako printf v bashi.
# Stejna data jako i18n.sh a luxos_i18n.py: /usr/share/luxos/i18n/<jazyk>.tsv
# (radek "anglicky<TAB>preklad"; komentare # a prazdne preklady se preskoci).
# LUXOS_I18N_DIR prepise adresar s preklady (testy bez instalace balicku).
# Tabulka se cte az pri prvnim prekladu a hleda se v ni primo (memmem), bez slovniku.
load env
load luxos_sys

table = None     # "\n" + obsah TSV; "" = anglictina nebo soubor chybi

function lang():
    for name in ["LC_ALL", "LC_MESSAGES", "LANG"]:
        value = env.get(name, "")
        if value != "":
            for sep in ["_", ".", "@"]:
                cut = value.find(sep)
                if cut >= 0:
                    value = value[0:cut]
                end
            end
            return value
        end
    end
    return "en"
end

function load_table():
    global table
    table = ""
    code = lang()
    if code == "en":
        return None
    end
    path = env.get("LUXOS_I18N_DIR", "")
    if path == "":
        path = "/usr/share/luxos/i18n"
    end
    path = path + "/" + code + ".tsv"
    if exists(path):
        safe:
            table = "\n" + readfile(path)
        end
    end
    return None
end

function T(text):
    if table == None:
        call load_table()
    end
    if table == "":
        return text
    end
    found = luxos_sys.tsv_lookup(table, text)
    # koncove tabulatory jako awk v i18n.sh; prazdny preklad = anglicky text
    while found.endswith("\t"):
        found = found[0:len(found) - 1]
    end
    if found == "" or text.startswith("#"):
        return text
    end
    return found
end

# Dosazeni hodnot za %s a %d v poradi, %% je %; jine sekvence zustavaji
function format(template, values):
    out = ""
    index = 0
    used = 0
    while index < len(template):
        ch = template[index]
        if ch == "%" and index + 1 < len(template):
            code = template[index + 1]
            if code == "%":
                out = out + "%"
                index += 2
                continue
            elif code == "s" or code == "d":
                if used < len(values):
                    out = out + String(values[used])
                end
                used += 1
                index += 2
                continue
            end
        end
        out = out + ch
        index += 1
    end
    return out
end

function TF(text, values):
    return format(T(text), values)
end
