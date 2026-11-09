"""LuxOS - tisk a skenovani: spolecne funkce pro pomocnika (root) a aplikaci Tiskarny a skenery.

Jen cista logika bez vedlejsich efektu (cteni vystupu avahi-browse a lpinfo, nazvy front,
volba ovladace, uprava nsswitch.conf) - testy v tests/test_luxos_printing.py.
"""
import json
import os
import re
import urllib.parse

# Formaty, ktere umi CUPS posilat tiskarne bez ovladace (IPP Everywhere, AirPrint, Mopria)
DRIVERLESS_PDL = ("image/pwg-raster", "image/urf", "application/pdf")
PRINTER_TYPES = ("_ipp._tcp", "_ipps._tcp")
SCANNER_TYPES = ("_uscan._tcp", "_uscans._tcp")


def avahi_unescape(s):
    """avahi-browse -p escapuje znaky jako \\032 (desitkove) a \\. """
    return re.sub(r"\\(\d{3}|.)", lambda m: chr(int(m.group(1))) if m.group(1).isdigit() else m.group(1), s)


def parse_txt(s):
    """'"a=b" "c=d"' -> {"a": "b", "c": "d"} (klice malymi pismeny)."""
    out = {}
    for item in re.findall(r'"((?:[^"\\]|\\.)*)"', s):
        item = avahi_unescape(item)
        k, _sep, v = item.partition("=")
        if k:
            out.setdefault(k.lower(), v)
    return out


def parse_avahi(text):
    """Vyresene zaznamy z `avahi-browse -p -r -k`: radky '=;iface;proto;name;type;domain;host;addr;port;txt'."""
    out = []
    for line in text.splitlines():
        if not line.startswith("="):
            continue
        f = line.split(";", 9)
        if len(f) < 10:
            continue
        try:
            port = int(f[8])
        except ValueError:
            continue
        out.append({"iface": f[1], "proto": f[2], "name": avahi_unescape(f[3]), "type": f[4], "domain": f[5],
                    "host": f[6], "address": f[7], "port": port, "txt": parse_txt(f[9])})
    return out


def dnssd_uri(name, stype, uuid=None, domain="local"):
    """URI ve tvaru, jaky pouziva CUPS: odolne vuci zmene IP adresy tiskarny."""
    uri = f"dnssd://{urllib.parse.quote(name, safe='')}.{stype}.{domain}/"
    if uuid:
        uri += f"?uuid={uuid}"
    return uri


def uri_uuid(uri):
    m = re.search(r"[?&]uuid=([0-9a-fA-F-]{8,})", uri or "")
    return m.group(1).lower() if m else None


def uri_service_name(uri):
    """dnssd://Nazev._ipp._tcp.local/ -> 'Nazev'."""
    if not (uri or "").startswith("dnssd://"):
        return None
    host = urllib.parse.unquote(uri[8:].split("/", 1)[0])
    m = re.match(r"(.*)\._ipps?\._tcp\.", host)
    return m.group(1) if m else None


def is_driverless(txt):
    pdl = txt.get("pdl", "").lower()
    return any(p in pdl for p in DRIVERLESS_PDL) or bool(txt.get("urf"))


def device_key(svc):
    uuid = (svc["txt"].get("uuid") or "").lower()
    return f"uuid:{uuid}" if uuid else f"dnssd:{svc['name']}"


def group_printers(services):
    """Jedna polozka na tiskarnu (stejna tiskarna chodi pres _ipp i _ipps, IPv4 i IPv6, vic rozhrani).

    Pripojeni pres USB (ipp-usb) se ohlasuje na rozhrani lo.
    """
    out = {}
    for s in services:
        if s["type"] not in PRINTER_TYPES:
            continue
        key = device_key(s)
        p = out.setdefault(key, {"key": key, "name": s["name"], "uuid": s["txt"].get("uuid", "").lower() or None,
                                 "model": s["txt"].get("ty") or s["name"], "types": set(), "usb": False,
                                 "txt": s["txt"], "addrs": []})
        p["types"].add(s["type"])
        if s["iface"] == "lo":
            p["usb"] = True
        p["addrs"].append((s["type"], s["address"], s["port"], s["txt"].get("rp", "ipp/print")))
    for p in out.values():
        # _ipp ma prednost (sifrovane _ipps jen kdyz jine neni)
        stype = "_ipp._tcp" if "_ipp._tcp" in p["types"] else "_ipps._tcp"
        p["uri"] = dnssd_uri(p["name"], stype, p["uuid"])
        p["driverless"] = is_driverless(p["txt"])
        # IPv4 a lo napred: rychlejsi a spolehlivejsi pro primy dotaz na stav
        p["addrs"].sort(key=lambda a: (a[0] != "_ipp._tcp", ":" in a[1]))
    return out


def group_scanners(services):
    out = {}
    for s in services:
        if s["type"] not in SCANNER_TYPES:
            continue
        uuid = (s["txt"].get("uuid") or "").lower()
        key = f"uuid:{uuid}" if uuid else f"escl:{s['name']}"
        model = s["txt"].get("ty") or s["name"]
        out.setdefault(key, {"key": key, "name": s["name"], "model": model, "usb": s["iface"] == "lo"})
    return out


def friendly_name(name):
    """Nazev sluzby bez technickych pripon: 'HP LaserJet M110w (A1B2C3)' / '... @ host' / '[serial]'."""
    n = re.sub(r"\s*@\s*\S+$", "", name or "").strip()
    n = re.sub(r"\s*[\[(][0-9A-Fa-f:]{4,}[\])]$", "", n).strip()
    return n or (name or "Printer")


def queue_name(text, existing):
    """Nazev fronty CUPS: jen [A-Za-z0-9_-], bez kolize s existujicimi (bez ohledu na velikost pismen)."""
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", friendly_name(text)).strip("_-")[:100] or "Printer"
    taken = {e.lower() for e in existing}
    name, i = base, 2
    while name.lower() in taken:
        name, i = f"{base}_{i}", i + 1
    return name


# ---- klasicke USB tiskarny (bez IPP) ----

def parse_lpinfo(text, head):
    """Bloky z `lpinfo -l -v` (head='Device') nebo `lpinfo -l -m` (head='Model')."""
    out, cur = [], None
    for line in text.splitlines():
        if line.startswith(head + ":"):
            cur = {}
            out.append(cur)
            line = line[len(head) + 1:]
        if cur is None or "=" not in line:
            continue
        k, _sep, v = line.strip().partition(" = ")
        if k and _sep:
            cur[k.strip()] = v.strip()
        elif line.strip().endswith(" ="):
            cur[line.strip()[:-2].strip()] = ""
    return out


def parse_device_id(s):
    d = {}
    for part in (s or "").split(";"):
        k, _sep, v = part.partition(":")
        k = k.strip().upper()
        k = {"MANUFACTURER": "MFG", "MODEL": "MDL", "COMMAND SET": "CMD", "DESCRIPTION": "DES"}.get(k, k)
        if k and v.strip():
            d.setdefault(k, v.strip())
    return d


def norm_mfg(m):
    m = (m or "").strip().lower()
    return {"hewlett-packard": "hp", "hewlett packard": "hp", "kyocera mita": "kyocera", "fuji xerox": "xerox",
            "konica minolta": "minolta"}.get(m, m)


def norm_mdl(mfg, mdl):
    mfg = norm_mfg(mfg)
    m = re.sub(r"[\s_-]+", " ", (mdl or "").lower()).strip()
    for prefix in (mfg + " ", "hewlett-packard ", "hp "):
        if m.startswith(prefix):
            m = m[len(prefix):]
    return re.sub(r"\s+series$", "", m).strip()


def driver_package(mfg):
    """Balik s ovladacem, ktery se doinstaluje, kdyz zadny nainstalovany nepasuje."""
    return "hplip" if norm_mfg(mfg) == "hp" else "gutenprint"


# Ovladace vyrobcu z AUR: LuxOS je overuje a stavi do repozitare [luxos-drivers] (drivers/ v LuxOS),
# pomocnik je pak nainstaluje sam. Kdyz v repozitari nejsou (stary lux.conf, bez internetu), muze
# ho uzivatel sestavit pres lux z AUR (nikdy jako root).
# Samsung SPL/QPDL (napr. Xpress M2020/M2026, ML-2160): oficialni Samsung Unified Linux Driver.
AUR_DRIVERS = {"samsung": "samsung-unified-driver-printer"}
DRIVERS_INDEX = "/usr/share/luxos/drivers-index.json"
DRIVERS_INDEX_PACKAGE = "luxos-drivers-index"


def aur_driver(device_id):
    """Balik z AUR pro tiskarnu bez ovladace v repozitarich (nebo None)."""
    return AUR_DRIVERS.get(norm_mfg(parse_device_id(device_id).get("MFG")))


def load_drivers_index(path=DRIVERS_INDEX):
    """Mapa model -> balik z [luxos-drivers] (balik luxos-drivers-index); chybi = {}."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and data.get("format") == 1 else {}


def verified_driver(device_id, index):
    """Overeny ovladac z [luxos-drivers] pro tiskarnu (presny model, u Samsungu i rada), jinak None."""
    dev = parse_device_id(device_id)
    mfg, mdl = norm_mfg(dev.get("MFG")), norm_mdl(dev.get("MFG"), dev.get("MDL"))
    if not mfg or not mdl:
        return None
    compact = re.sub(r"[^a-z0-9]", "", mdl)       # "MFC-L2710DW series" = "MFCL2710DW" z PPD
    family = None
    fam = _family(mfg, mdl)
    for e in index.get("printers", []):
        if norm_mfg(e.get("mfg")) != mfg:
            continue
        m = norm_mdl(e.get("mfg"), e.get("mdl"))
        if re.sub(r"[^a-z0-9]", "", m) == compact:
            return e.get("package")
        if fam and family is None and _family(mfg, m) == fam:
            family = e.get("package")
    return family


def _family(mfg, mdl):
    """Samsung: model rady ("xpress m2026") -> zaklad rady ("m202"), PPD ULD je pro "M2020 Series"."""
    if mfg != "samsung":
        return None
    m = re.fullmatch(r"(?:xpress )?([a-z]+ ?\d{3})\d[a-z]*", mdl)
    return m.group(1).replace(" ", "") if m else None


def _ppd_rank(ppd):
    name, mm = ppd.get("name", ""), ppd.get("make-and-model", "").lower()
    r = 0
    if "hpcups" in mm:
        r += 3                          # HP: vlastni ovladac je nejlepsi
    elif "gutenprint" in mm:
        r += 2
    if "requires proprietary plugin" in mm:
        r -= 4                          # potrebuje rucne stazeny plugin HP - jen kdyz nic jineho
    if "hpijs" in mm or "foomatic" in mm:
        r -= 1
    if name.startswith("drv:///"):
        r += 1                          # stejny ovladac bez kopie PPD na disku
    if name.endswith("/expert"):
        r -= 1                          # gutenprint: "simplified" varianta je pro bezne uzivatele
    return r


def _cmd_mismatch(ppd, device_id):
    """Ovladac pro jiny jazyk tiskarny, nez jaky hlasi (Canon: CARPS2 vs UFR II LT/LIPSLX)."""
    cmd = parse_device_id(device_id).get("CMD", "").upper()
    mm = ppd.get("make-and-model", "").upper()
    return bool(cmd) and "CARPS" in mm and "CARPS" not in cmd


def pick_ppd(models, device_id):
    """Nejlepsi ovladac pro zarizeni (models = parse_lpinfo(lpinfo -l -m, 'Model'))."""
    dev = parse_device_id(device_id)
    mfg, mdl = norm_mfg(dev.get("MFG")), norm_mdl(dev.get("MFG"), dev.get("MDL"))
    if not mdl:
        return None
    best = None
    for ppd in models:
        pid = parse_device_id(ppd.get("device-id"))
        score = 0
        if pid.get("MDL") and norm_mdl(pid.get("MFG"), pid["MDL"]) == mdl and \
                (not pid.get("MFG") or norm_mfg(pid["MFG"]) == mfg):
            score = 100
        else:
            mm = re.sub(r"[\s_-]+", " ", ppd.get("make-and-model", "").lower())
            mm = re.split(r",| - | cups| foomatic", mm)[0].strip()
            if norm_mdl(mfg, mm) == mdl and (mm.startswith(mfg + " ") or mfg == "hp" and mm.startswith("hp ")):
                score = 80
            elif mm.startswith(mfg + " ") and re.fullmatch(re.escape(mdl) + r" series [a-z0-9 ]+",
                                                         norm_mdl(mfg, mm.removesuffix(" series"))):
                score = 70              # vyrobce pridava jazyk tiskarny: "Canon MF4100 Series UFRII LT"
            elif mm.startswith(mfg + " ") and _family(mfg, mdl) and \
                    re.fullmatch(re.escape(_family(mfg, mdl)) + "0", norm_mdl(mfg, mm).replace(" ", "")):
                score = 60              # Samsung ULD: jedno PPD pro celou radu (M2026 -> "M2020 Series")
        if not score:
            continue
        # oba zpusoby shody urcuji stejny model - rozhoduje kvalita ovladace, pak presnost shody
        cand = (_ppd_rank(ppd) - (5 if _cmd_mismatch(ppd, device_id) else 0), score, ppd["name"])
        if best is None or cand[:2] > best[:2]:
            best = cand
    return best[2] if best else None


def generic_ppd(device_id):
    """Obecny ovladac podle jazyka tiskarny, kdyz konkretni neexistuje."""
    cmd = [c.strip().upper() for c in parse_device_id(device_id).get("CMD", "").split(",")]
    if "PWGRASTER" in cmd:
        return "drv:///cupsfilters.drv/pwgrast.ppd"     # URF (AirPrint) neni PWG raster - jen pres IPP
    if any(c in ("POSTSCRIPT", "PS", "BR-SCRIPT3", "PS3") or c.startswith("POSTSCRIPT") for c in cmd):
        return "drv:///sample.drv/generic.ppd"
    if "PCLXL" in cmd or "PCL6" in cmd or "PCL 6" in cmd:
        return "lsb/usr/cupsfilters/pxlmono.ppd"
    if "PCL" in cmd or "PCL5" in cmd or "PCL5E" in cmd:
        return "drv:///sample.drv/laserjet.ppd"
    return None


def is_camera(dev, typ=""):
    """Kamera notebooku (SANE backend v4l) neni skener - v seznamech skeneru se neukazuje."""
    return (dev or "").lower().startswith(("v4l:", "v4l2:")) or \
        (typ or "").strip().lower() in ("webcam", "video camera", "camera")


def scanner_conn(dev, name=""):
    """Pripojeni skeneru podle SANE id: network | usb | "" (aplikace prelozi).

    airscan/escl na localhost nebo s "USB" v nazvu je ipp-usb (USB skener se ohlasuje jako sitovy);
    hpaio:/net/, epson2:net:, net: (saned) jsou sitove, *usb* je USB."""
    d = (dev or "").lower()
    if d.startswith(("airscan:", "escl:")):
        local = any(h in d for h in ("localhost", "127.0.0.1", "[::1]"))
        return "usb" if local or "usb" in (name or "").lower() else "network"
    if "usb" in d:
        return "usb"
    if d.startswith("net:") or ":net:" in d or "/net/" in d:
        return "network"
    return ""


def scanner_kind(dev, typ="", name=""):
    """Druh skeneru jako anglicky text k prekladu (aplikace ho prozene _()), nebo "".

    Typ ze `scanimage` (%t) je volny text backendu: airscan "eSCL network scanner" / "WSD network
    scanner", pixma "multifunction peripheral", hpaio "all-in-one", genesys "flatbed scanner"…
    Drive se ukazoval jen s velkym pocatecnim pismenem ("Escl network scanner")."""
    d = (dev or "").lower()
    t = re.sub(r"[\s_-]+", " ", (typ or "").strip().lower())
    if d.startswith(("airscan:e", "escl:")) or "escl" in t or "airscan" in t:
        return ("Scanner (eSCL/AirScan)" if scanner_conn(dev, name) == "usb"
                else "Network scanner (eSCL/AirScan)")
    if d.startswith("airscan:w") or "wsd" in t:
        return "Network scanner (WSD)"
    if not t:
        return ""
    for keys, label in ((("multi function", "multifunction", "all in one", "mfp"), "Multi-function peripheral"),
                        (("flatbed",), "Flatbed scanner"),
                        (("sheetfed", "sheet fed", "adf", "document"), "Sheet-fed scanner"),
                        (("film", "slide", "negative"), "Film scanner"),
                        (("handheld", "hand held"), "Handheld scanner"),
                        (("virtual",), "Virtual device")):
        if any(k in t for k in keys):
            return label
    return "Scanner"


def usb_serial(uri):
    m = re.search(r"[?&]serial=([^&]+)", uri or "")
    return urllib.parse.unquote(m.group(1)) if m else None


# ---- stav tiskarny pro uzivatele ----

# printer-state-reasons -> (text, vazne) ; pripony -error/-warning/-report se odstrani
REASONS = [
    (("media-jam",), "Paper jam", True),
    (("media-empty", "media-needed", "input-tray-missing"), "Out of paper", True),
    (("toner-empty", "marker-supply-empty", "marker-waste-full"), "Out of ink or toner", True),
    (("door-open", "cover-open", "interlock-open"), "A cover is open", True),
    (("offline", "shutdown", "timed-out"), "Offline", True),
    (("connecting-to-device",), "Connecting…", False),
    (("toner-low", "marker-supply-low", "media-low", "marker-waste-almost-full"), "Ink, toner or paper is low", False),
]


def reason_text(reasons):
    """Nejdulezitejsi duvod ze seznamu printer-state-reasons -> (anglicky text, vazne) nebo (None, False)."""
    clean = {re.sub(r"-(error|warning|report)$", "", r) for r in reasons or () if r and r != "none"}
    for keys, text, serious in REASONS:
        if clean & set(keys):
            return text, serious
    return None, False


# ---- nsswitch.conf: mDNS (*.local) pro tiskarny a skenery ----

def nsswitch_add_mdns(text):
    """Do radku hosts: prida 'mdns_minimal [NOTFOUND=return]' pred resolve/dns. Ostatni beze zmeny.

    Vrati novy text, nebo None, kdyz uprava neni potreba (mdns uz tam je, radek chybi).
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*hosts\s*:)(.*)$", line)
        if not m:
            continue
        if re.search(r"\bmdns(4|6)?(_minimal)?\b", m.group(2)):
            return None
        words = m.group(2).split()
        pos = next((j for j, w in enumerate(words) if w in ("resolve", "dns")), len(words))
        words[pos:pos] = ["mdns_minimal", "[NOTFOUND=return]"]
        lines[i] = m.group(1) + " " + " ".join(words)
        return "\n".join(lines)
    return None


# ---- skener: volby ze `scanimage -A` ----

def parse_scan_options(text):
    """{'mode': (['Color','Gray'], 'Color'), 'resolution': ([75,150,300] nebo (min, max), 300), ...}"""
    opts = {}
    for line in text.splitlines():
        m = re.match(r"^\s+--?([a-z][\w-]*)\s+(.*?)\s*\[(.*)\]\s*$", line)
        if not m:
            continue
        name, spec, cur = m.group(1), m.group(2), m.group(3)
        if name == "resolution":
            spec = re.sub(r"dpi.*$", "", spec)
            r = re.match(r"^(\d+)\.\.(\d+)", spec)
            if r:
                vals = (int(r.group(1)), int(r.group(2)))
            else:
                vals = [int(float(v)) for v in spec.split("|") if re.match(r"^\d+(\.\d+)?$", v)]
            try:
                cur = int(float(cur))
            except ValueError:
                cur = None
            opts[name] = (vals, cur)
        elif "|" in spec or name in ("mode", "source"):
            opts[name] = ([v for v in spec.split("|") if v], cur)
    return opts


def nearest_resolution(spec, want):
    if not spec:
        return want
    if isinstance(spec, tuple):
        return max(spec[0], min(spec[1], want))
    return min(spec, key=lambda v: (abs(v - want), -v))


def pick_mode(modes, kind):
    """kind: color | gray -> skutecny nazev rezimu backendu (Color/Gray/'24bit Color'...)."""
    pats = {"color": r"colou?r|rgb", "gray": r"gr[ae]y"}[kind]
    for m in modes or ():
        if re.search(pats, m, re.I):
            return m
    return None


# ---- naplne z tiskarny (IPP printer-supply, PWG 5100.13) ----

COLORANTS = {"black": "#202020", "cyan": "#00a6e0", "magenta": "#e0007a", "yellow": "#f5d000",
             "light-cyan": "#7fd3f0", "light-magenta": "#f07fbd", "photo-black": "#202020", "matte-black": "#303030",
             "gray": "#808080", "light-gray": "#b0b0b0"}


def parse_printer_supply(values, descriptions=()):
    """printer-supply ('index=1;class=supplyThatIsConsumed;type=toner;maxcapacity=100;level=75;colorantname=black;')
    -> [(nazev, procento, barva)]; jen spotrebni material se znamou urovni (ne odpadni nadobky)."""
    if isinstance(values, (str, bytes)):
        values = [values]
    if isinstance(descriptions, str):
        descriptions = [descriptions]
    out = []
    for i, v in enumerate(values or ()):
        if isinstance(v, bytes):
            v = v.decode("utf-8", "replace")
        f = dict(p.split("=", 1) for p in v.split(";") if "=" in p)
        if f.get("class", "supplyThatIsConsumed") != "supplyThatIsConsumed":
            continue
        try:
            level, cap = int(f.get("level", -1)), int(f.get("maxcapacity", 100))
        except ValueError:
            continue
        if level < 0 or cap <= 0:
            continue
        colorant = f.get("colorantname", "").lower()
        name = descriptions[i] if i < len(descriptions) and descriptions[i] else \
            (colorant.replace("-", " ").capitalize() or f.get("type", "Supply"))
        out.append((name, min(100, round(level * 100 / cap)), COLORANTS.get(colorant, "#888888")))
    return out


# ---- primy dotaz na tiskarnu (ipptool z CUPS; pycups neumi octetString v printer-supply) ----

IPPTOOL_TEST = """{
  OPERATION Get-Printer-Attributes
  GROUP operation-attributes-tag
  ATTR charset attributes-charset utf-8
  ATTR naturalLanguage attributes-natural-language en
  ATTR uri printer-uri $uri
  ATTR keyword requested-attributes printer-state,printer-state-reasons,marker-names,marker-levels,marker-colors,printer-supply,printer-supply-description
  STATUS successful-ok
}
"""


def parse_ipptool(text):
    """Vystup `ipptool -tv` -> {atribut: [hodnoty]} (jen odpoved, ne dotaz)."""
    out, resp = {}, False
    for line in text.splitlines():
        if re.match(r"^\s+status-code = ", line):
            resp = True
            continue
        m = re.match(r"^\s+([a-z][\w-]*) \(([^)]*)\) = (.*)$", line)
        if not (resp and m):
            continue
        name, typ, val = m.groups()
        vals = val.split(",") if typ.startswith("1setOf") else [val]
        if "integer" in typ or typ.endswith("enum"):
            try:
                vals = [int(v) for v in vals]
            except ValueError:
                pass
        out[name] = vals
    # printer-supply: carky oddeluji hodnoty, ale hodnoty samy carky nemaji (klic=hodnota;)
    return out


# ---- odpojena / vypnuta tiskarna: chovani front a samo-obnoveni (luxos-printing-helper autoresume) ----
#
# CUPS frontu pozastavi (printer-state stopped), kdyz backend skonci chybou: u politiky stop-printer
# (vychozi v CUPS i na Archu) po kazde chybe, u ostatnich politik po navratovem kodu STOP (napr.
# "unrecoverable USB error", tiskarna uz neexistuje). udev-configure-printer (system-config-printer)
# frontu USB tiskarny pri odpojeni pozastavi se zpravou "Unplugged or turned off". Sam ji pak uz
# NIKDY znovu nepovoli - tiskarna se po pripojeni tvarila odpojena a ulohy jen cekaly.

# Schemata primo pripojenych tiskaren (USB, paralelni, seriove; Canon cnusbufr2:, gutenprint53+usb:)
LOCAL_SCHEMES = ("usb", "parallel", "serial", "cnusbufr2")


def uri_scheme(uri):
    return uri.split(":", 1)[0].lower() if uri and ":" in uri else ""


def is_local_uri(uri):
    """Tiskarna pripojena kabelem k tomuto pocitaci (ne sit)."""
    s = uri_scheme(uri)
    if s in LOCAL_SCHEMES or "usb" in s:
        return True
    return (uri or "").lower().startswith(("hp:/usb/", "hpfax:/usb/"))


def error_policy(uri, usb=False):
    """printer-error-policy pro frontu, kterou zaklada LuxOS.

    USB (klasicke i ipp-usb): retry-current-job - po chybe (kabel vytazen nebo tiskarna vypnuta behem
    tisku) se uloha hned spusti znovu a backend usb / dnssd pak sam ceka, az se tiskarna objevi
    ("Waiting for printer to become available"). Fronta se nezastavi a uloha se neztrati; retry-job
    by ji po JobRetryLimit (5) x JobRetryInterval (300 s) zahodil, stop-printer frontu zastavi.
    Sit: retry-job - backend ipp na vypnutou tiskarnu ceka sam (contimeout 7 dni), chyba je tedy
    skutecna chyba tiskarny a omezeny pocet pokusu nezpusobi nekonecnou smycku."""
    return "retry-current-job" if usb or is_local_uri(uri) else "retry-job"


# Zpravy (printer-state-message), se kterymi CUPS nebo udev-configure-printer frontu zastavi, protoze
# tiskarna nebyla k dispozici. Jen takove fronty se po pripojeni tiskarny povoli samy; frontu
# pozastavenou uzivatelem ("Paused", vlastni duvod) nechame - na to je tlacitko Obnovit.
DEVICE_GONE = ("unplugged or turned off", "printer stopped due to backend errors",
               "waiting for printer to become available", "unable to locate printer",
               "the printer is not responding", "unable to send data to printer",
               "there was an unrecoverable usb error", "unable to open device",
               "unable to connect to printer", "the printer may not exist or is unavailable",
               "connection refused", "no route to host")
DEVICE_GONE_REASONS = {"offline", "connecting-to-device", "timed-out"}


def _clean_reasons(reasons):
    return {re.sub(r"-(error|warning|report)$", "", r) for r in reasons or () if r and r != "none"}


def paused_for_device(message, reasons=()):
    """Fronta byla zastavena kvuli nedostupne tiskarne (ne uzivatelem)."""
    m = (message or "").strip().lower()
    if m:
        return any(p in m for p in DEVICE_GONE)
    return bool(_clean_reasons(reasons) & DEVICE_GONE_REASONS)


def waiting_for_device(message):
    """Backend ceka na tiskarnu (usb: "Waiting for printer to become available.", ipp: "Unable to locate…")."""
    m = (message or "").lower()
    return any(p in m for p in ("waiting for printer to become available", "unable to locate printer",
                                "the printer is not responding"))


def parse_lpstat_p(text):
    """`LC_ALL=C lpstat -l -p` -> {fronta: {"state": idle|printing|stopped|holding, "message", "reasons", "info"}}."""
    out, cur, first = {}, None, False
    for line in text.splitlines():
        m = re.match(r"^printer (\S+) (?:is (idle|holding new jobs)\.|now printing \S+\.|(disabled) since)", line)
        if m:
            state = "stopped" if m.group(3) else "printing" if not m.group(2) else \
                ("holding" if m.group(2).startswith("holding") else "idle")
            cur = out[m.group(1)] = {"state": state, "message": "", "reasons": [], "info": ""}
            first = True
            continue
        if cur is None or not line.startswith("\t"):
            continue
        s = line[1:].rstrip()
        if first and not s.startswith(("Form mounted:", "Description: ", "Alerts: ")) and s != "reason unknown":
            cur["message"] = s.strip()      # zprava je hned za hlavickou (muze obsahovat i dvojtecku)
        first = False
        if s.startswith("Alerts: "):
            cur["reasons"] = [r for r in s[8:].split() if r != "none"]
        elif s.startswith("Description: "):
            cur["info"] = s[13:].strip()
    return out


def parse_lpstat_a(text):
    """`LC_ALL=C lpstat -a` -> {fronta: prijima ulohy}."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^(\S+) (not )?accepting requests since ", line)
        if m and "/" not in m.group(1):
            out[m.group(1)] = not m.group(2)
    return out


def parse_lpstat_jobs(text):
    """`LC_ALL=C lpstat -l -o` -> [{"id", "queue", "user", "status", "reasons"}]."""
    out, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^(\S+)-(\d+)\s+(\S+)\s+\d+\s", line)
        if m:
            cur = {"id": int(m.group(2)), "queue": m.group(1), "user": m.group(3), "status": "", "reasons": []}
            out.append(cur)
            continue
        s = line.strip()
        if cur is None or not s:
            continue
        if s.startswith("Status: "):
            cur["status"] = s[8:]
        elif s.startswith("Alerts: "):
            cur["reasons"] = [r for r in s[8:].split() if r != "none"]
    return out


def job_held_by_user(job):
    """Uloha pozdrzena uzivatelem nebo aplikaci (ne kvuli tiskarne) - necheka na tiskarnu."""
    r = set(job.get("reasons") or ())
    return "resources-are-not-ready" not in r and bool(r & {
        "job-hold-until-specified", "cups-held-for-authentication", "job-held-for-review",
        "account-info-needed", "account-closed", "account-limit-reached", "account-authorization-failed"})


def parse_printers_conf(text):
    """/etc/cups/printers.conf (cte jen root) -> {fronta: {"uri", "stopped", "message", "accepting", "policy"}}.

    Jen pro levnou kontrolu, kdyz cupsd nebezi (bez probuzeni CUPS pres cups.socket)."""
    out, cur = {}, None
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"^<(?:Default)?Printer (\S+)>$", s)
        if m:
            cur = out[m.group(1)] = {"uri": "", "stopped": False, "message": "", "accepting": True,
                                     "policy": "stop-printer"}
            continue
        if s.startswith("</"):
            cur = None
            continue
        if cur is None:
            continue
        k, _sep, v = s.partition(" ")
        if k == "DeviceURI":
            cur["uri"] = v.strip()
        elif k == "State":
            cur["stopped"] = v.strip().lower() == "stopped"
        elif k == "StateMessage":
            cur["message"] = v.strip()
        elif k == "Accepting":
            cur["accepting"] = v.strip().lower() != "no"
        elif k == "ErrorPolicy":
            cur["policy"] = v.strip()
    return out


def _usb_norm(s):
    s = re.sub(r"[^a-z0-9]", "", (s or "").lower())
    return s.removesuffix("series")


def usb_printer_devices(base="/sys/bus/usb/devices"):
    """Pripojena USB zarizeni s rozhranim tiskarny (trida 07): [{"serial", "manufacturer", "product"}].

    Jen cteni sysfs (bez CUPS a bez probouzeni tiskarny)."""
    out = []
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for d in names:
        if ":" not in d:
            continue
        try:
            with open(os.path.join(base, d, "bInterfaceClass")) as f:
                if f.read().strip() != "07":
                    continue
        except OSError:
            continue
        parent = os.path.join(base, d.split(":", 1)[0])
        info = {}
        for k in ("serial", "manufacturer", "product"):
            try:
                with open(os.path.join(parent, k)) as f:
                    info[k] = f.read().strip()
            except OSError:
                info[k] = ""
        if info not in out:
            out.append(info)
    return out


def usb_present(uri, devices):
    """Je tiskarna z usb:// URI pripojena? True / False / None (nelze poznat bez CUPS).

    devices = usb_printer_devices(). Shoda podle serioveho cisla; bez nej podle vyrobce a modelu
    (usb://Canon/MF4100%20Series), ten ale v USB popisu byt nemusi -> None."""
    serial = usb_serial(uri)
    if serial:
        return any(d.get("serial") == serial for d in devices)
    if not devices:
        return False
    path = urllib.parse.unquote((uri or "").split("://", 1)[-1].split("?", 1)[0])
    make, _sep, model = path.partition("/")
    for d in devices:
        if _usb_norm(d.get("manufacturer")) == _usb_norm(make) and _usb_norm(d.get("product")) == _usb_norm(model):
            return True
    return None


def printer_condition(state, message, reasons, accepting, local, online, jobs):
    """Stav fronty kvuli pripojeni tiskarny: (klic, ukazat tlacitko Obnovit).

    state: idle | printing | stopped | holding (nebo IPP 3/4/5), local: tiskarna na USB, online:
    True / False / None (nevime), jobs: pocet cekajicich uloh. Klic:
      unplugged       USB tiskarna neni pripojena
      unplugged_auto  USB tiskarna neni pripojena a uloha ceka - vytiskne se sama po pripojeni
      offline         sitova tiskarna je vypnuta
      offline_auto    sitova tiskarna je vypnuta a uloha ceka - vytiskne se sama
      paused          pozastaveno z jineho duvodu (uzivatel, chyba ovladace) -> Obnovit
      None            nic z toho (pripravena, tiskne, papir... resi aplikace)
    """
    stopped = state in ("stopped", 5)
    device_pause = stopped and paused_for_device(message, reasons)
    absent = online is False or (online is None and (waiting_for_device(message) or device_pause))
    if absent:
        key = ("unplugged" if local else "offline") + ("_auto" if jobs or device_pause else "")
        # pozastaveno kvuli odpojeni se po pripojeni povoli samo; Obnovit jen pri jinem duvodu
        return key, (stopped or not accepting) and not device_pause
    if stopped or not accepting:
        return "paused", True
    return None, False
