"""LuxOS - Skener: logika aplikace luxos-scan bez GTK (testy v tests/test_luxos_scan.py).

Seznam skeneru a skenovani pres `scanimage` (SANE), volby Dokument/Fotka, srozumitelne chyby misto
hlasek SANE, nazvy souboru a vicestrankove PDF (vlastni maly zapisovac: stranky jako JPEG/DCTDecode,
zadna dalsi zavislost).
"""
import datetime
import os
import re
import signal
import subprocess

import luxos_printing as lp

LIST_FORMAT = "%d\t%v\t%m\t%t%n"


# ---- seznam skeneru ----

def parse_devices(text):
    """Vystup `scanimage -f LIST_FORMAT` -> [{id, name, type, conn}] serazene podle nazvu.

    Stejny skener pres vic backendu (airscan eSCL/WSD, vlastni ovladac) jen jednou: eSCL ma prednost,
    WSD je posledni moznost. conn: network | usb | "" (aplikace prelozi).
    """
    best = {}
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) < 4 or not f[0].strip():
            continue
        dev, vendor, model, typ = (x.strip() for x in f[:4])
        if lp.is_camera(dev, typ):
            continue
        name = model if model.lower().startswith(vendor.lower()) else f"{vendor} {model}".strip()
        name = lp.friendly_name(name or dev)
        prio = 0 if dev.startswith("airscan:e") else 2 if dev.startswith("airscan:w") else 1
        conn = "network" if dev.startswith("airscan:") else "usb" if "usb" in dev.lower() else ""
        if dev.startswith("airscan:") and ("localhost" in dev.lower() or "usb" in name.lower()):
            conn = "usb"            # ipp-usb: USB skener se ohlasuje jako sitovy na localhost
        key = name.lower()
        if key not in best or prio < best[key][0]:
            best[key] = (prio, {"id": dev, "name": name, "type": typ, "conn": conn})
    return [v[1] for v in sorted(best.values(), key=lambda v: v[1]["name"].lower())]


def list_devices(timeout=90):
    """[{id, name, type, conn}]; OSError, kdyz scanimage chybi."""
    r = subprocess.run(["scanimage", "-f", LIST_FORMAT], capture_output=True, text=True, timeout=timeout)
    return parse_devices(r.stdout)


def probe_options(dev, timeout=60):
    """Volby skeneru ze `scanimage -A` (rezimy, rozliseni, zdroje). Chyba -> ScanError."""
    try:
        r = subprocess.run(["scanimage", "-d", dev, "-A"], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise ScanError("timeout", "scanimage -A: timeout") from e
    opts = lp.parse_scan_options(r.stdout)
    if r.returncode != 0 and not opts:
        raise ScanError(error_kind(r.stderr), r.stderr.strip())
    return opts


# ---- zdroje papiru ----

def source_kind(src):
    """'Flatbed' -> flatbed, 'ADF'/'Automatic Document Feeder' -> adf, 'ADF Duplex' -> duplex."""
    s = (src or "").lower()
    if "duplex" in s or "both" in s:
        return "duplex"
    if "adf" in s or "feeder" in s or "automatic" in s or s.startswith("adf"):
        return "adf"
    if "flatbed" in s or "platen" in s or "glass" in s:
        return "flatbed"
    return None


def sources(opts):
    """[(hodnota pro --source, druh)] - prazdne, kdyz skener nema na vyber."""
    vals = (opts.get("source") or ([], None))[0]
    return [(v, source_kind(v)) for v in vals] if len(vals) > 1 else []


# ---- volby skenovani ----

KINDS = {"document": 300, "photo": 600}


def scan_settings(opts, kind, color, source=None):
    """(argumenty scanimage bez -d, dpi, zesvetlit_pozadi).

    kind: document (300 dpi) | photo (600 dpi); color: True = barevne, False = cernobile (odstiny sedi).
    Cernobily dokument se navic zesvetli (bile pozadi, syte pismo).
    """
    args = []
    modes = (opts.get("mode") or ([], None))[0]
    m = lp.pick_mode(modes, "color" if color else "gray") or (lp.pick_mode(modes, "gray") if color else None) \
        or lp.pick_mode(modes, "color")
    if m:
        args += ["--mode", m]
    res = opts.get("resolution")
    dpi = lp.nearest_resolution(res[0] if res else None, KINDS.get(kind, 300))
    if res:
        args += ["--resolution", str(dpi)]
    if source:
        args += ["--source", source]
    return args, dpi, kind == "document" and not color


# ---- chyby ----

# (druh, vzory v hlasce scanimage) - poradi = priorita
ERROR_PATTERNS = [
    ("cancelled", r"operation was cancel+ed|cancel+ed"),
    ("busy", r"device busy|resource busy|in use"),
    ("jammed", r"jammed|paper jam"),
    ("no_paper", r"out of documents|no more documents|feeder (is )?empty|no paper"),
    ("cover_open", r"cover (is )?open|door (is )?open"),
    ("denied", r"access to resource has been denied|permission denied"),
    ("memory", r"out of memory|insufficient memory|no space left"),
    ("not_found", r"invalid argument|no such device|no scanners were identified|failed to open|"
                  r"no sane devices|not found"),
    ("io", r"error during device i/o|i/o error|timed? ?out|connection|eof|broken pipe"),
    ("missing", r"no such file or directory: '?scanimage|scanimage: not found"),
]

ERRORS = {
    "busy": ("The scanner is busy",
             "Another app or computer is using it right now. Wait a moment and try again."),
    "jammed": ("The paper is jammed",
               "Open the document feeder, carefully remove the paper and try again."),
    "no_paper": ("The document feeder is empty",
                 "Put the pages in the document feeder, or choose the glass as the source."),
    "cover_open": ("The scanner cover is open", "Close the cover and try again."),
    "denied": ("The scanner cannot be used",
               "Your user account is not allowed to use this scanner. Log out and log in again."),
    "memory": ("Not enough memory or disk space",
               "Close some apps or free up disk space, or scan with lower quality."),
    "not_found": ("The scanner does not respond",
                  "Make sure it is turned on and connected with a USB cable or to the same Wi‑Fi network."),
    "io": ("The connection to the scanner was lost",
           "Check the cable or Wi‑Fi connection, turn the scanner off and on again and try once more."),
    "timeout": ("The scanner does not respond",
                "Make sure it is turned on and connected with a USB cable or to the same Wi‑Fi network."),
    "missing": ("Scanning support is not installed",
                "Install the luxos-printing package from the Store."),
    "cancelled": ("Scanning was cancelled", ""),
    "unknown": ("Something went wrong while scanning", "Turn the scanner off and on again and try once more."),
}


def error_kind(text):
    t = (text or "").lower()
    for kind, pat in ERROR_PATTERNS:
        if re.search(pat, t):
            return kind
    return "unknown"


def error_message(kind):
    """(anglicky nadpis, anglicka rada) - aplikace prelozi pres _()."""
    return ERRORS.get(kind, ERRORS["unknown"])


def clean_stderr(text):
    """Hlaska scanimage bez radku s prubehem (pro rozbalovaci Podrobnosti)."""
    t = re.sub(r"Progress: [\d.]+%\s*", "", text or "")
    return "\n".join(line for line in t.splitlines() if line.strip()).strip()


class ScanError(Exception):
    def __init__(self, kind, details=""):
        super().__init__(details or kind)
        self.kind = kind
        self.details = details


# ---- skenovani ----

class Scan:
    """Jedno spusteni scanimage. run() blokuje - aplikace ho vola ve vlakne, cancel() z hlavniho vlakna.

    batch=True (podavac): vsechny listy z podavace do souboru out_dir/page-NNN.pnm.
    """

    def __init__(self, dev, args, out_dir, batch=False, start=1):
        self.dev, self.args, self.out_dir, self.batch, self.start = dev, list(args), out_dir, batch, start
        self.proc = None
        self.cancelled = False

    def command(self):
        cmd = ["scanimage", "-d", self.dev, *self.args, "--format=pnm", "-p"]
        if self.batch:
            cmd += [f"--batch={os.path.join(self.out_dir, 'page-%03d.pnm')}", f"--batch-start={self.start}"]
        else:
            cmd += ["-o", os.path.join(self.out_dir, f"page-{self.start:03d}.pnm")]
        return cmd

    def run(self, progress=None):
        """Vrati seznam naskenovanych souboru, jinak ScanError."""
        try:
            self.proc = subprocess.Popen(self.command(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                         start_new_session=True)
        except OSError as e:
            raise ScanError("missing", str(e)) from e
        err, buf = b"", b""
        while True:
            ch = os.read(self.proc.stderr.fileno(), 512)     # vrati hned, co je k dispozici
            if not ch:
                break
            buf = (buf + ch)[-256:]
            err = (err + ch)[-8192:]
            m = re.findall(rb"Progress: ([\d.]+)%", buf)
            if m and progress:
                progress(min(1.0, float(m[-1]) / 100))
        rc = self.proc.wait()
        self.proc.stderr.close()
        self.proc = None
        text = clean_stderr(err.decode(errors="replace"))
        files = self.collect()
        if self.cancelled:
            for f in files:
                _unlink(f)
            raise ScanError("cancelled", text)
        if self.batch and files:
            return files            # podavac dosel: posledni list hlasi "out of documents", to neni chyba
        if rc == 0 and files:
            return files
        for f in files:
            _unlink(f)
        raise ScanError(error_kind(text) if text else "unknown", text or f"scanimage: exit status {rc}")

    def collect(self):
        out = []
        n = self.start
        while True:
            p = os.path.join(self.out_dir, f"page-{n:03d}.pnm")
            if not (os.path.exists(p) and os.path.getsize(p) > 0):
                if os.path.exists(p):
                    _unlink(p)
                break
            if not pnm_complete(p):
                _unlink(p)          # nedokonceny list (zaseknuty papir, preruseni)
                break
            out.append(p)
            n += 1
            if not self.batch:
                break
        return out

    def cancel(self):
        self.cancelled = True
        p = self.proc
        if p and p.poll() is None:
            try:
                p.send_signal(signal.SIGTERM)    # scanimage zavola sane_cancel a skonci
            except OSError:
                pass

    def kill(self):
        p = self.proc
        if p and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


# ---- PNM ----

def pnm_header(raw):
    """(typ, sirka, vyska, maxval, offset dat) pro P4/P5/P6, jinak None."""
    tokens, pos = [], 0
    need = 3 if raw[:2] == b"P4" else 4
    rx = re.compile(rb"\s*(?:#[^\n]*\n\s*)*(\S+)")
    while len(tokens) < need:
        m = rx.match(raw, pos)
        if not m:
            return None
        tokens.append(m.group(1))
        pos = m.end()
    if tokens[0] not in (b"P4", b"P5", b"P6"):
        return None
    try:
        w, h = int(tokens[1]), int(tokens[2])
        maxval = int(tokens[3]) if need == 4 else 1
    except ValueError:
        return None
    return tokens[0].decode(), w, h, maxval, pos + 1


def pnm_complete(path):
    """Ma soubor tolik dat, kolik hlasi hlavicka? (preruseny sken = kratsi soubor)."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(512)
    except OSError:
        return False
    h = pnm_header(head)
    if not h:
        return False
    typ, w, hh, maxval, off = h
    if typ == "P4":
        need = (w + 7) // 8 * hh
    else:
        need = w * hh * (3 if typ == "P6" else 1) * (2 if maxval > 255 else 1)
    return size >= off + need


def whiten(path):
    """Cernobily dokument: bile pozadi, syte pismo (prosta krivka urovni; jen 8bit P5/P6)."""
    with open(path, "rb") as f:
        raw = f.read()
    h = pnm_header(raw)
    if not h or h[0] == "P4" or h[3] != 255:
        return False
    lo, hi = 60, 205
    table = bytes(0 if v <= lo else 255 if v >= hi else int((v - lo) * 255 / (hi - lo)) for v in range(256))
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(raw[:h[4]] + raw[h[4]:].translate(table))
    os.replace(tmp, path)
    return True


# ---- ulozeni ----

def documents_dir(xdg_documents=None, home=None):
    """Slozka Dokumenty podle XDG (xdg-user-dir DOCUMENTS); kdyz chybi nebo je to domovska slozka -> ~/Documents."""
    home = home or os.path.expanduser("~")
    d = xdg_documents
    if not d or os.path.normpath(d) == os.path.normpath(home):
        d = os.path.join(home, "Documents")
    return d


def base_name(template="Scan %s", now=None):
    """'Scan 2026-10-22 14.03' (sablona je uz prelozena, napr. 'Sken %s')."""
    now = now or datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d %H.%M")
    name = template % stamp if "%s" in template else f"{template} {stamp}"
    return name.replace("/", "-")


def unique_path(folder, base, ext):
    p = os.path.join(folder, f"{base}.{ext}")
    i = 2
    while os.path.exists(p):
        p = os.path.join(folder, f"{base} ({i}).{ext}")
        i += 1
    return p


def image_paths(folder, base, ext, count):
    """Cesty pro obrazky po strankach: 'Scan ….jpg' nebo 'Scan … - 1.jpg', 'Scan … - 2.jpg'."""
    if count == 1:
        return [unique_path(folder, base, ext)]
    out = []
    for i in range(count):
        out.append(unique_path(folder, f"{base} - {i + 1}", ext))
    return out


def jpeg_info(data):
    """(sirka, vyska, pocet slozek) z hlavicky SOF JPEGu; ValueError pro neplatna data."""
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            i += 1 if marker == 0xFF else 2
            continue
        seglen = int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if i + 10 > len(data):
                break
            h = int.from_bytes(data[i + 5:i + 7], "big")
            w = int.from_bytes(data[i + 7:i + 9], "big")
            return w, h, data[i + 9]
        if marker == 0xDA:
            break
        i += 2 + seglen
    raise ValueError("JPEG without a frame header")


def _pdf_str(s):
    """Retezec PDF: ASCII primo, jinak UTF-16BE s BOM (diakritika v nazvu)."""
    try:
        s.encode("ascii")
        return b"(" + s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode() + b")"
    except UnicodeEncodeError:
        return b"<FEFF" + s.encode("utf-16-be").hex().upper().encode() + b">"


def write_pdf(path, pages, title="", creator="LuxOS Scanner"):
    """Vicestrankove PDF: pages = [(jpeg bytes, dpi)], kazda stranka presne velikosti skenu.

    Zapisuje do path.part a az na konci prejmenuje - nedokoncene PDF nikdy nevznikne.
    """
    if not pages:
        raise ValueError("no pages")
    objs = []            # obsah objektu 1..n (bez "n 0 obj")
    n_pages = len(pages)
    # 1 katalog, 2 strom stranek, 3 info, pak na stranku: page, image, content
    kids = [4 + i * 3 for i in range(n_pages)]
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) +
                b"] /Count %d >>" % n_pages)
    info = b"<< /Producer " + _pdf_str(creator) + b" /Creator " + _pdf_str(creator)
    if title:
        info += b" /Title " + _pdf_str(title)
    info += b" /CreationDate " + _pdf_str(datetime.datetime.now().strftime("D:%Y%m%d%H%M%S")) + b" >>"
    objs.append(info)
    streams = {}
    for i, (jpeg, dpi) in enumerate(pages):
        w, h, comps = jpeg_info(jpeg)
        dpi = dpi or 300
        wpt, hpt = w * 72 / dpi, h * 72 / dpi
        page_no, img_no, cont_no = kids[i], kids[i] + 1, kids[i] + 2
        space = {1: b"/DeviceGray", 4: b"/DeviceCMYK"}.get(comps, b"/DeviceRGB")
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] " % (wpt, hpt) +
                    b"/Resources << /XObject << /Im0 %d 0 R >> >> /Contents %d 0 R >>" % (img_no, cont_no))
        decode = b" /Decode [1 0 1 0 1 0 1 0]" if comps == 4 else b""
        objs.append(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace " % (w, h) + space +
                    b" /BitsPerComponent 8 /Filter /DCTDecode" + decode + b" /Length %d >>" % len(jpeg))
        streams[img_no] = jpeg
        content = b"q %.2f 0 0 %.2f 0 0 cm /Im0 Do Q" % (wpt, hpt)
        objs.append(b"<< /Length %d >>" % len(content))
        streams[cont_no] = content
    tmp = path + ".part"
    try:
        with open(tmp, "wb") as f:
            f.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
            offsets = []
            for no, body in enumerate(objs, 1):
                offsets.append(f.tell())
                f.write(b"%d 0 obj\n" % no + body)
                if no in streams:
                    f.write(b"\nstream\n" + streams[no] + b"\nendstream")
                f.write(b"\nendobj\n")
            xref = f.tell()
            f.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
            for off in offsets:
                f.write(b"%010d 00000 n \n" % off)
            f.write(b"trailer\n<< /Size %d /Root 1 0 R /Info 3 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                    % (len(objs) + 1, xref))
        os.replace(tmp, path)
    except BaseException:
        _unlink(tmp)
        raise
    return path
