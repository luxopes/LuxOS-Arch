# Posta LuxOS - data a cisla podle jazyka aplikace (luxos_i18n.lang()), ne podle libc locale: v systemu muze
# byt vygenerovane jen en_US.UTF-8 a strftime by pak v ceske Poste ukazal "Sunday" a "11/16/26".
# Stejna data jako format_date v luxos_i18n.py (luxos-i18n). Dny od pondeli, mesice v genitivu ("16. listopadu").
# LUXOS_MAIL_NOW prepise "ted" (testy seznamu zprav: Dnes, Vcera, den v tydnu).
load env
load luxos_glib, glib as glib
load luxos_i18n as i18n
load mail_mime as mime

# jazyk: [dny, kratke dny, mesice, dlouhe datum, kratke datum, datum s rokem]
CAL = {
    "en": ["Monday Tuesday Wednesday Thursday Friday Saturday Sunday", "Mon Tue Wed Thu Fri Sat Sun",
           "January February March April May June July August September October November December",
           "{A}, {B} {d}", "{b} {d}", "{b} {d}, {Y}"],
    "cs": ["pondělí úterý středa čtvrtek pátek sobota neděle", "po út st čt pá so ne",
           "ledna února března dubna května června července srpna září října listopadu prosince",
           "{A} {d}. {B}", "{d}. {m}.", "{d}. {m}. {Y}"],
    "sk": ["pondelok utorok streda štvrtok piatok sobota nedeľa", "po ut st št pi so ne",
           "januára februára marca apríla mája júna júla augusta septembra októbra novembra decembra",
           "{A} {d}. {B}", "{d}. {m}.", "{d}. {m}. {Y}"],
    "pl": ["poniedziałek wtorek środa czwartek piątek sobota niedziela", "pon. wt. śr. czw. pt. sob. niedz.",
           "stycznia lutego marca kwietnia maja czerwca lipca sierpnia września października listopada grudnia",
           "{A}, {d} {B}", "{dd}.{mm}", "{dd}.{mm}.{Y}"],
    "uk": ["понеділок вівторок середа четвер пʼятниця субота неділя", "пн вт ср чт пт сб нд",
           "січня лютого березня квітня травня червня липня серпня вересня жовтня листопада грудня",
           "{A}, {d} {B}", "{dd}.{mm}", "{dd}.{mm}.{Y}"],
    "hu": ["hétfő kedd szerda csütörtök péntek szombat vasárnap", "H K Sze Cs P Szo V",
           "január február március április május június július augusztus szeptember október november december",
           "{B} {d}., {A}", "{mm}. {dd}.", "{Y}. {mm}. {dd}."],
    "de": ["Montag Dienstag Mittwoch Donnerstag Freitag Samstag Sonntag", "Mo. Di. Mi. Do. Fr. Sa. So.",
           "Januar Februar März April Mai Juni Juli August September Oktober November Dezember",
           "{A}, {d}. {B}", "{dd}.{mm}.", "{dd}.{mm}.{Y}"],
    "fr": ["lundi mardi mercredi jeudi vendredi samedi dimanche", "lun. mar. mer. jeu. ven. sam. dim.",
           "janvier février mars avril mai juin juillet août septembre octobre novembre décembre",
           "{A} {d} {B}", "{dd}/{mm}", "{dd}/{mm}/{Y}"],
    "es": ["lunes martes miércoles jueves viernes sábado domingo", "lun mar mié jue vie sáb dom",
           "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre",
           "{A}, {d} de {B}", "{dd}/{mm}", "{dd}/{mm}/{Y}"],
    "it": ["lunedì martedì mercoledì giovedì venerdì sabato domenica", "lun mar mer gio ven sab dom",
           "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre",
           "{A} {d} {B}", "{dd}/{mm}", "{dd}/{mm}/{Y}"],
    "pt": ["segunda-feira terça-feira quarta-feira quinta-feira sexta-feira sábado domingo", "seg. ter. qua. qui. sex. sáb. dom.",
           "janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro",
           "{A}, {d} de {B}", "{dd}/{mm}", "{dd}/{mm}/{Y}"],
    "nl": ["maandag dinsdag woensdag donderdag vrijdag zaterdag zondag", "ma di wo do vr za zo",
           "januari februari maart april mei juni juli augustus september oktober november december",
           "{A} {d} {B}", "{d}-{m}", "{d}-{m}-{Y}"],
    "sv": ["måndag tisdag onsdag torsdag fredag lördag söndag", "mån tis ons tors fre lör sön",
           "januari februari mars april maj juni juli augusti september oktober november december",
           "{A} {d} {B}", "{d}/{m}", "{Y}-{mm}-{dd}"]
}

function lang():
    code = i18n.lang()
    if CAL.get(code, None) == None:
        return "en"
    end
    return code
end

function cal():
    return CAL[lang()]
end

function two(n):
    if n < 10:
        return "0" + String(n)
    end
    return String(n)
end

# "ted" (unix cas); testy mohou prepsat
function now():
    value = env.get("LUXOS_MAIL_NOW", "")
    if value != None and value != "":
        n = mime.to_int(value, 0)
        if n > 0:
            return n
        end
    end
    return glib.now()
end

# lt = glib.localtime(t): [rok, mesic, den, hodina, minuta, sekunda, den v tydnu (0 = pondeli), ...]
function weekday(t, short=False):
    lt = glib.localtime(t)
    i = 0
    if short:
        i = 1
    end
    return cal()[i].split(" ")[lt[6]]
end

# style: "long" = den v tydnu, den a mesic slovem; "short" = den a mesic cisly; "full" = i s rokem
function date(t, style="short"):
    c = cal()
    lt = glib.localtime(t)
    month = c[2].split(" ")[lt[1] - 1]
    pattern = c[4]
    if style == "long":
        pattern = c[3]
    elif style == "full":
        pattern = c[5]
    end
    out = pattern.replace("{A}", c[0].split(" ")[lt[6]]).replace("{B}", month).replace("{b}", month[0:3])
    out = out.replace("{dd}", two(lt[2])).replace("{mm}", two(lt[1])).replace("{d}", String(lt[2])).replace("{m}", String(lt[1]))
    return out.replace("{Y}", String(lt[0]))
end

# hodiny:minuty; 24hodinovy cas vsude krome anglictiny
function time(t):
    lt = glib.localtime(t)
    h = lt[3]
    if lang() != "en":
        return String(h) + ":" + two(lt[4])
    end
    h12 = h % 12
    if h12 == 0:
        h12 = 12
    end
    suffix = "AM"
    if h >= 12:
        suffix = "PM"
    end
    return String(h12) + ":" + two(lt[4]) + " " + suffix
end

# Datum a cas v hlavicce zpravy a v citaci odpovedi: "ne 16. 11. 2026 10:00", "Sun Nov 16, 2026 10:00 AM"
function date_time(t):
    if lang() == "hu":
        # madarstina: den v tydnu az za datem ("2026. 11. 22., V 11:00")
        return date(t, "full") + ", " + weekday(t, True) + " " + time(t)
    end
    return weekday(t, True) + " " + date(t, "full") + " " + time(t)
end

function day_number(t):
    lt = glib.localtime(t)
    return mime.days_from_civil(lt[0], lt[1], lt[2])
end

# Datum v seznamu zprav: dnes cas, vcera "Vcera", tento tyden den v tydnu, letos den a mesic, jinak i s rokem
function list_date(t):
    if t <= 0:
        return ""
    end
    n = now()
    diff = day_number(n) - day_number(t)
    if diff == 0:
        return time(t)
    elif diff == 1:
        return i18n.T("Yesterday")
    elif diff > 1 and diff < 7:
        return weekday(t, False)
    end
    if glib.localtime(n)[0] == glib.localtime(t)[0] and diff >= 0:
        return date(t, "short")
    end
    return date(t, "full")
end

# Desetinny oddelovac podle jazyka aplikace: "1.5 MB" (libc C/en_US) -> "1,5 MB" v cestine
function decimal_text(text):
    if lang() == "en":
        return text.replace(",", ".")
    end
    return text.replace(".", ",")
end

# Velikost souboru (g_format_size) s oddelovacem podle jazyka aplikace
function size(n):
    return decimal_text(glib.format_size(n))
end
