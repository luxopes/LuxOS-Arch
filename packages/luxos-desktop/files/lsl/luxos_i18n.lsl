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

# --- Data a cisla podle jazyka aplikace (stejna data jako luxos_i18n.py), ne podle libc locale:
# s vygenerovanym jen en_US by glib/strftime dal anglicke nazvy nebo cesky pevny tvar v jinem jazyce.
# Radek: dny od pondeli, zkratky dnu, mesice ("18. listopadu"), sablona long, short, full, year.
CAL = {
    "en": ["Monday Tuesday Wednesday Thursday Friday Saturday Sunday", "Mon Tue Wed Thu Fri Sat Sun", "January February March April May June July August September October November December", "{A}, {B} {d}", "{b} {d}", "{b} {d}, {Y}", "{A}, {B} {d}, {Y}"],
    "cs": ["pondělí úterý středa čtvrtek pátek sobota neděle", "po út st čt pá so ne", "ledna února března dubna května června července srpna září října listopadu prosince", "{A} {d}. {B}", "{d}. {m}.", "{d}. {m}. {Y}", "{A} {d}. {B} {Y}"],
    "sk": ["pondelok utorok streda štvrtok piatok sobota nedeľa", "po ut st št pi so ne", "januára februára marca apríla mája júna júla augusta septembra októbra novembra decembra", "{A} {d}. {B}", "{d}. {m}.", "{d}. {m}. {Y}", "{A} {d}. {B} {Y}"],
    "pl": ["poniedziałek wtorek środa czwartek piątek sobota niedziela", "pon. wt. śr. czw. pt. sob. niedz.", "stycznia lutego marca kwietnia maja czerwca lipca sierpnia września października listopada grudnia", "{A}, {d} {B}", "{dd}.{mm}", "{dd}.{mm}.{Y}", "{A}, {d} {B} {Y}"],
    "uk": ["понеділок вівторок середа четвер пʼятниця субота неділя", "пн вт ср чт пт сб нд", "січня лютого березня квітня травня червня липня серпня вересня жовтня листопада грудня", "{A}, {d} {B}", "{dd}.{mm}", "{dd}.{mm}.{Y}", "{A}, {d} {B} {Y} р."],
    "hu": ["hétfő kedd szerda csütörtök péntek szombat vasárnap", "H K Sze Cs P Szo V", "január február március április május június július augusztus szeptember október november december", "{B} {d}., {A}", "{mm}. {dd}.", "{Y}. {mm}. {dd}.", "{Y}. {B} {d}., {A}"],
    "de": ["Montag Dienstag Mittwoch Donnerstag Freitag Samstag Sonntag", "Mo. Di. Mi. Do. Fr. Sa. So.", "Januar Februar März April Mai Juni Juli August September Oktober November Dezember", "{A}, {d}. {B}", "{dd}.{mm}.", "{dd}.{mm}.{Y}", "{A}, {d}. {B} {Y}"],
    "fr": ["lundi mardi mercredi jeudi vendredi samedi dimanche", "lun. mar. mer. jeu. ven. sam. dim.", "janvier février mars avril mai juin juillet août septembre octobre novembre décembre", "{A} {d} {B}", "{dd}/{mm}", "{dd}/{mm}/{Y}", "{A} {d} {B} {Y}"],
    "es": ["lunes martes miércoles jueves viernes sábado domingo", "lun mar mié jue vie sáb dom", "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre", "{A}, {d} de {B}", "{dd}/{mm}", "{dd}/{mm}/{Y}", "{A}, {d} de {B} de {Y}"],
    "it": ["lunedì martedì mercoledì giovedì venerdì sabato domenica", "lun mar mer gio ven sab dom", "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre", "{A} {d} {B}", "{dd}/{mm}", "{dd}/{mm}/{Y}", "{A} {d} {B} {Y}"],
    "pt": ["segunda-feira terça-feira quarta-feira quinta-feira sexta-feira sábado domingo", "seg. ter. qua. qui. sex. sáb. dom.", "janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro", "{A}, {d} de {B}", "{dd}/{mm}", "{dd}/{mm}/{Y}", "{A}, {d} de {B} de {Y}"],
    "nl": ["maandag dinsdag woensdag donderdag vrijdag zaterdag zondag", "ma di wo do vr za zo", "januari februari maart april mei juni juli augustus september oktober november december", "{A} {d} {B}", "{d}-{m}", "{d}-{m}-{Y}", "{A} {d} {B} {Y}"],
    "sv": ["måndag tisdag onsdag torsdag fredag lördag söndag", "mån tis ons tors fre lör sön", "januari februari mars april maj juni juli augusti september oktober november december", "{A} {d} {B}", "{d}/{m}", "{Y}-{mm}-{dd}", "{A} {d} {B} {Y}"]
}

function cal_row():
    code = lang()
    if code in CAL:
        return CAL[code]
    end
    return CAL["en"]
end

function pad2(n):
    if n < 10:
        return "0" + String(n)
    end
    return String(n)
end

# format_date(rok, mesic, den, den_v_tydnu 0=pondeli..6=nedele, styl):
# "long" = "středa 18. listopadu", "short" = "18. 11.", "full" = "18. 11. 2026",
# "year" = "středa 18. listopadu 2026" (cele datum do bubliny)
# (luxos_glib.localtime(t) vraci [rok, mesic, den, hod, min, s, den_v_tydnu 0=pondeli, ...] -> format_tm)
function format_date(year, month, day, weekday, style):
    row = cal_row()
    tpl = row[3]
    if style == "short":
        tpl = row[4]
    elif style == "full":
        tpl = row[5]
    elif style == "year":
        tpl = row[6]
    end
    days = row[0].split(" ")
    short_days = row[1].split(" ")
    months = row[2].split(" ")
    wd = weekday % 7
    out = tpl.replace("{A}", days[wd]).replace("{a}", short_days[wd])
    out = out.replace("{B}", months[month - 1]).replace("{b}", months[month - 1][0:3])
    out = out.replace("{dd}", pad2(day)).replace("{mm}", pad2(month))
    return out.replace("{d}", String(day)).replace("{m}", String(month)).replace("{Y}", String(year))
end

function format_tm(tm, style):
    return format_date(tm[0], tm[1], tm[2], tm[6], style)
end

# Kratky den v tydnu (0=pondeli): "st", "Mi.", "Wed"
function weekday_short(weekday):
    return cal_row()[1].split(" ")[weekday % 7]
end

# Desetinny oddelovac jazyka aplikace: "1,5" v cestine, "1.5" v anglictine
function decimal_separator():
    if lang() == "en":
        return "."
    end
    return ","
end

# Cislo uz naformatovane s teckou ("1.5") -> s oddelovacem jazyka aplikace
function decimal(text):
    return text.replace(".", decimal_separator())
end
