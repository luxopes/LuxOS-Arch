"""LuxOS - tisk a skenovani: spolecne funkce pro pomocnika (root) a aplikaci Tiskarny a skenery.

Jen cista logika bez vedlejsich efektu (cteni vystupu avahi-browse a lpinfo, nazvy front,
volba ovladace, uprava nsswitch.conf) - testy v tests/test_luxos_printing.py.
"""
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
        if not score:
            continue
        # oba zpusoby shody urcuji stejny model - rozhoduje kvalita ovladace, pak presnost shody
        cand = (_ppd_rank(ppd), score, ppd["name"])
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
