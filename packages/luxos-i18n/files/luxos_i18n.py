"""LuxOS - preklady pro aplikace v Pythonu: _("English") -> text v jazyce uzivatele.

Preklady jsou v /usr/share/luxos/i18n/<jazyk>.tsv (radek "anglicky<TAB>preklad"),
stejne soubory pouzivaji i skripty v bashi (/usr/lib/luxos/i18n.sh).
LUXOS_I18N_DIR prepise adresar s preklady (testy bez instalace balicku).
"""
import os

LANG = (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "en")
LANG = LANG.split("_")[0].split(".")[0].split("@")[0] or "en"
DIR = os.environ.get("LUXOS_I18N_DIR") or "/usr/share/luxos/i18n"
_TR = {}
try:
    with open(os.path.join(DIR, f"{LANG}.tsv"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or "\t" not in line:
                continue
            k, v = line.rstrip("\n").split("\t", 1)
            if v:
                _TR[k] = v
except OSError:
    pass


def _(text):
    return _TR.get(text, text)


def _keep_space(text):
    """Preklad textu s mezerami/novym radkem na krajich (argparse: "usage: ", "...%(message)s\\n")."""
    core = text.strip()
    if not core:
        return text
    i = text.index(core)
    return text[:i] + _(core) + text[i + len(core):]


def argparse_i18n():
    """Texty argparse (usage:, options, chyby) v jazyce uzivatele - volat pred vytvorenim parseru."""
    import argparse
    argparse._ = _keep_space
    argparse.ngettext = lambda one, many, n: _keep_space(one if n == 1 else many)


def print_usage(head, rows, file=None, width=0):
    """Napoveda prikazu: hlavicka + radky (syntaxe, anglicky popis). Popisy se prekladaji,
    syntaxe zustava. Radek bez popisu ("", nadpis) = nadpis sekce (prelozi se)."""
    import sys
    out = file or sys.stdout
    width = width or min(34, max(len(c) for c, d in rows if d) + 2)
    print(head, file=out)
    for cmd, desc in rows:
        if not desc:
            print("\n" + _(cmd) if cmd else "", file=out)
        elif len(cmd) + 2 > width:
            print(f"  {cmd}\n  {'':{width}}{_(desc)}", file=out)
        else:
            print(f"  {cmd:{width}}{_(desc)}", file=out)


# --- Data a cisla podle jazyka aplikace (ne podle libc locale: v systemu muze byt vygenerovane
# jen en_US.UTF-8 a GTK/strftime by pak ukazaly anglicke nazvy a americky format mezi ceskymi texty).
# Dny od pondeli, mesice ve tvaru "18. listopadu" (genitiv tam, kde ho jazyk pouziva).
_CAL = {
    "en": ("Monday Tuesday Wednesday Thursday Friday Saturday Sunday", "Mon Tue Wed Thu Fri Sat Sun",
           "January February March April May June July August September October November December",
           "{A}, {B} {d}", "{b} {d}", "{b} {d}, {Y}"),
    "cs": ("pondělí úterý středa čtvrtek pátek sobota neděle", "po út st čt pá so ne",
           "ledna února března dubna května června července srpna září října listopadu prosince",
           "{A} {d}. {B}", "{d}. {m}.", "{d}. {m}. {Y}"),
    "sk": ("pondelok utorok streda štvrtok piatok sobota nedeľa", "po ut st št pi so ne",
           "januára februára marca apríla mája júna júla augusta septembra októbra novembra decembra",
           "{A} {d}. {B}", "{d}. {m}.", "{d}. {m}. {Y}"),
    "pl": ("poniedziałek wtorek środa czwartek piątek sobota niedziela", "pon. wt. śr. czw. pt. sob. niedz.",
           "stycznia lutego marca kwietnia maja czerwca lipca sierpnia września października listopada grudnia",
           "{A}, {d} {B}", "{dd}.{mm}", "{dd}.{mm}.{Y}"),
    "uk": ("понеділок вівторок середа четвер пʼятниця субота неділя", "пн вт ср чт пт сб нд",
           "січня лютого березня квітня травня червня липня серпня вересня жовтня листопада грудня",
           "{A}, {d} {B}", "{dd}.{mm}", "{dd}.{mm}.{Y}"),
    "hu": ("hétfő kedd szerda csütörtök péntek szombat vasárnap", "H K Sze Cs P Szo V",
           "január február március április május június július augusztus szeptember október november december",
           "{B} {d}., {A}", "{mm}. {dd}.", "{Y}. {mm}. {dd}."),
    "de": ("Montag Dienstag Mittwoch Donnerstag Freitag Samstag Sonntag", "Mo. Di. Mi. Do. Fr. Sa. So.",
           "Januar Februar März April Mai Juni Juli August September Oktober November Dezember",
           "{A}, {d}. {B}", "{dd}.{mm}.", "{dd}.{mm}.{Y}"),
    "fr": ("lundi mardi mercredi jeudi vendredi samedi dimanche", "lun. mar. mer. jeu. ven. sam. dim.",
           "janvier février mars avril mai juin juillet août septembre octobre novembre décembre",
           "{A} {d} {B}", "{dd}/{mm}", "{dd}/{mm}/{Y}"),
    "es": ("lunes martes miércoles jueves viernes sábado domingo", "lun mar mié jue vie sáb dom",
           "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre",
           "{A}, {d} de {B}", "{dd}/{mm}", "{dd}/{mm}/{Y}"),
    "it": ("lunedì martedì mercoledì giovedì venerdì sabato domenica", "lun mar mer gio ven sab dom",
           "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre",
           "{A} {d} {B}", "{dd}/{mm}", "{dd}/{mm}/{Y}"),
    "pt": ("segunda-feira terça-feira quarta-feira quinta-feira sexta-feira sábado domingo",
           "seg. ter. qua. qui. sex. sáb. dom.",
           "janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro",
           "{A}, {d} de {B}", "{dd}/{mm}", "{dd}/{mm}/{Y}"),
    "nl": ("maandag dinsdag woensdag donderdag vrijdag zaterdag zondag", "ma di wo do vr za zo",
           "januari februari maart april mei juni juli augustus september oktober november december",
           "{A} {d} {B}", "{d}-{m}", "{d}-{m}-{Y}"),
    "sv": ("måndag tisdag onsdag torsdag fredag lördag söndag", "mån tis ons tors fre lör sön",
           "januari februari mars april maj juni juli augusti september oktober november december",
           "{A} {d} {B}", "{d}/{m}", "{Y}-{mm}-{dd}"),
}
_STYLE = {"long": 3, "short": 4, "full": 5}


def _cal(lang):
    return _CAL.get((lang or LANG).split("_")[0], _CAL["en"])


def _parts(t):
    """datetime/date/time.struct_time -> (rok, mesic, den, den v tydnu 0=pondeli, hodina, minuta)."""
    if hasattr(t, "tm_year"):
        return t.tm_year, t.tm_mon, t.tm_mday, t.tm_wday, t.tm_hour, t.tm_min
    return (t.year, t.month, t.day, t.weekday(), getattr(t, "hour", 0), getattr(t, "minute", 0))


def weekday_name(t, short=False, lang=None):
    return _cal(lang)[1 if short else 0].split()[_parts(t)[3]]


def format_date(t, style="long", lang=None):
    """Datum v jazyce aplikace: "long" = den v tydnu, den a mesic slovem ("středa 18. listopadu"),
    "short" = den a mesic cisly ("18. 11."), "full" = i s rokem ("18. 11. 2026")."""
    c = _cal(lang)
    y, m, d, wd, _h, _mi = _parts(t)
    month = c[2].split()[m - 1]
    return c[_STYLE.get(style, 3)].format(
        A=c[0].split()[wd], a=c[1].split()[wd], B=month, b=month[:3], d=d, m=m,
        dd=f"{d:02d}", mm=f"{m:02d}", Y=y)


def uses_24h(lang=None):
    return (lang or LANG).split("_")[0] != "en"


def format_time(t, h24=None, lang=None):
    """Cas hodiny:minuty; 24hodinovy vsude krome anglictiny (h24 to muze vynutit)."""
    h, mi = _parts(t)[4:6]
    if h24 is None:
        h24 = uses_24h(lang)
    if h24:
        return f"{h}:{mi:02d}"
    return f"{(h % 12) or 12}:{mi:02d} {'AM' if h < 12 else 'PM'}"


def decimal_separator(lang=None):
    return "." if (lang or LANG).split("_")[0] == "en" else ","


def format_number(value, digits=1, lang=None):
    """Desetinne cislo s carkou/teckou podle jazyka aplikace ("1,5" v cestine, "1.5" v anglictine)."""
    text = f"{value:.{digits}f}"
    return text.replace(".", decimal_separator(lang)) if digits > 0 else text
