"""LuxDrop - objevovani zarizeni LocalSend: multicast UDP 224.0.0.167:53317 a /register.

* Oznameni (announce) posilame po startu a pri "Obnovit" (3x: 0,1 s / 0,5 s / 2 s).
* Na cizi oznameni odpovidame HTTPS pozadavkem POST /register na jeho port
  (s pripnutym otiskem z oznameni); kdyz selze, odpovime multicastem (announce=false).
* Zarizeni je "overene", kdyz jeho otisk potvrdil TLS certifikat (nase /register k nemu
  nebo jeho /register k nam s klientskym certifikatem).
* Prohledani site /24 (HTTP fallback) jen na vyzadani uzivatele, jen soukrome site.
"""
import concurrent.futures
import fcntl
import ipaddress
import os
import socket
import struct
import threading
import time

from . import localsend, lshttp

SIOCGIFADDR = 0x8915
SIOCGIFNETMASK = 0x891B
ANNOUNCE_DELAYS = (0.1, 0.5, 2.0)
PROBE_TIMEOUT = 2.0
SCAN_TIMEOUT = 1.0
DEVICE_TTL = 15 * 60
MAX_DEVICES = 64        # ochrana proti zahlceni seznamu podvrzenymi zarizenimi
MAX_PROBES = 16         # soucasne dotazy /register


def interfaces(include_loopback=False):
    """[(jmeno, IPv4 adresa, maska)] aktivnich rozhrani (ioctl, bez zavislosti)."""
    out = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for _idx, name in socket.if_nameindex():
            if name == "lo" and not include_loopback:
                continue
            req = struct.pack("256s", name.encode()[:15])
            try:
                addr = socket.inet_ntoa(fcntl.ioctl(s.fileno(), SIOCGIFADDR, req)[20:24])
                mask = socket.inet_ntoa(fcntl.ioctl(s.fileno(), SIOCGIFNETMASK, req)[20:24])
            except OSError:
                continue
            if addr.startswith("127.") and not include_loopback:
                continue
            out.append((name, addr, mask))
    finally:
        s.close()
    return out


def scan_targets(ifaces):
    """Adresy k prohledani: /24 kolem nasi adresy, jen soukrome site (RFC 1918, CGNAT ne)."""
    targets = []
    for _name, addr, _mask in ifaces:
        ip = ipaddress.IPv4Address(addr)
        if not ip.is_private or ip.is_loopback or ip.is_link_local:
            continue
        net = ipaddress.IPv4Network(addr + "/24", strict=False)
        targets += [str(h) for h in net.hosts() if str(h) != addr]
    return list(dict.fromkeys(targets))


class LocalSendDiscovery:
    def __init__(self, identity, info_fn, on_change=None, port=None, group=None, multicast=True,
                 loopback=False):
        self.identity = identity
        self.info_fn = info_fn          # -> nase info (alias, fingerprint, port, ...)
        self.on_change = on_change or (lambda: None)
        self.port = port or int(os.environ.get("LUXDROP_LS_MCAST_PORT", localsend.DEFAULT_PORT))
        self.group = group or os.environ.get("LUXDROP_LS_MCAST_GROUP", localsend.MULTICAST_GROUP)
        self.use_multicast = multicast
        self.loopback = loopback or bool(os.environ.get("LUXDROP_LS_LOOPBACK"))
        self.devices = {}               # otisk -> zaznam
        self.lock = threading.Lock()
        self.sock = None
        self.error = ""
        self._probing = {}              # (ip, port) -> cas posledniho pokusu
        self._stop = threading.Event()
        self.scanning = False
        self.enabled = True             # odpovidat na oznameni (prijem zapnuty)
        self._probe_sem = threading.BoundedSemaphore(MAX_PROBES)

    # --- Multicast -------------------------------------------------------------

    def start(self):
        if not self.use_multicast:
            return False
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            s.bind(("", self.port))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
            joined = 0
            for _n, addr, _m in interfaces(self.loopback):
                try:
                    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                 socket.inet_aton(self.group) + socket.inet_aton(addr))
                    joined += 1
                except OSError:
                    pass
            if not joined:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                             socket.inet_aton(self.group) + socket.inet_aton("0.0.0.0"))
            self.sock = s
        except OSError as e:
            self.error = "multicast: %s" % (e.strerror or e)
            return False
        threading.Thread(target=self._recv_loop, daemon=True, name="localsend-multicast").start()
        return True

    def stop(self):
        self._stop.set()
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _send(self, announce):
        if not self.sock:
            return
        data = localsend.encode_datagram(dict(self.info_fn(), announce=announce, announcement=announce))
        sent = False
        for _n, addr, _m in interfaces(self.loopback):
            try:
                self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(addr))
                self.sock.sendto(data, (self.group, self.port))
                sent = True
            except OSError:
                continue
        if not sent:
            try:
                self.sock.sendto(data, (self.group, self.port))
            except OSError as e:
                self.error = "multicast: %s" % (e.strerror or e)

    def announce(self):
        """Oznameni v davce (datagram se snadno ztrati)."""
        def burst():
            last = 0.0
            for d in ANNOUNCE_DELAYS:
                if self._stop.wait(d - last):
                    return
                last = d
                self._send(True)
        threading.Thread(target=burst, daemon=True).start()

    def _recv_loop(self):
        my_fp = localsend.cert_fingerprint(self.identity.cert_der)
        while not self._stop.is_set():
            try:
                data, (ip, _p) = self.sock.recvfrom(localsend.MAX_DATAGRAM)
            except OSError:
                if self._stop.is_set():
                    return
                time.sleep(0.5)
                continue
            info = localsend.parse_datagram(data)
            if info is None or info["fingerprint"] == my_fp or info["raw_fingerprint"] == my_fp:
                continue
            if info["protocol"] != "https":
                # Bez sifrovani nic neposilame ani neprijimame - jen zobrazit
                self.add(ip, info, verified=False)
                continue
            threading.Thread(target=self._answer, args=(ip, info), daemon=True).start()

    def _answer(self, ip, info):
        if not self.enabled:
            # Prijem vypnuty: neregistrovat se (neprozrazovat se), zarizeni jen zapamatovat;
            # pri odesilani se jeho otisk pripne a overi pri pripojeni
            self.add(ip, info, verified=False)
            return
        ok = self.probe(ip, info["port"], expected_fp=info["fingerprint"] or None)
        if not ok:
            self.add(ip, info, verified=False)
            if info["announce"]:
                self._send(False)  # zalozni odpoved multicastem (protokol v2.0/2.1)

    # --- HTTP (register) -------------------------------------------------------

    def probe(self, ip, port, expected_fp=None, timeout=PROBE_TIMEOUT):
        """POST /register na ip:port; pri uspechu prida overene zarizeni. Vrati True/False."""
        key = (ip, port)
        now = time.monotonic()
        with self.lock:
            if now - self._probing.get(key, 0) < 2.0:
                return True
            if len(self._probing) > 4096:
                self._probing.clear()
            self._probing[key] = now
        if not self._probe_sem.acquire(timeout=timeout):
            return False
        try:
            c = lshttp.Client(self.identity, ip, port, expected_fp=expected_fp, timeout=timeout)
            try:
                status, obj = c.request_json("POST", localsend.API + "/register", self.info_fn(), limit=65536)
            finally:
                c.close()
        except Exception:  # noqa: BLE001 - nedostupne/cizi zarizeni
            return False
        finally:
            self._probe_sem.release()
        if status != 200 or not isinstance(obj, dict):
            return False
        try:
            info = localsend.parse_info(dict(obj, port=port, protocol="https"))
        except localsend.Invalid:
            return False
        if c.fingerprint == localsend.cert_fingerprint(self.identity.cert_der):
            return False  # sami sebe
        info["fingerprint"] = c.fingerprint  # identitu urcuje certifikat, ne telo odpovedi
        self.add(ip, info, verified=True, cert_der=c.cert_der)
        return True

    def registered(self, ip, info, cert_fp, cert_der):
        """Nekdo se registroval u naseho serveru (odpoved na nase oznameni)."""
        if info["protocol"] != "https":
            self.add(ip, info, verified=False)
            return
        if cert_fp:
            self.add(ip, info, verified=True, cert_der=cert_der)
        else:
            # Starsi klient bez klientskeho certifikatu: overit dotazem na jeho server
            threading.Thread(target=self.probe, args=(ip, info["port"], info["fingerprint"] or None),
                             daemon=True).start()

    def add(self, ip, info, verified, cert_der=None):
        fp = info["fingerprint"] or ("addr:%s:%d" % (ip, info["port"]))
        spki = None
        if cert_der:
            try:
                spki = localsend.spki_fingerprint_der(cert_der)
            except Exception:  # noqa: BLE001
                spki = None
        with self.lock:
            old = self.devices.get(fp)
            if old and old["verified"] and not verified:
                old["last_seen"] = time.time()
                return
            if old is None and len(self.devices) >= MAX_DEVICES:
                return
            self.devices[fp] = {
                "name": info["alias"], "fingerprint": fp, "host": ip, "port": info["port"],
                "protocol": info["protocol"], "device_type": info["deviceType"],
                "device_model": info["deviceModel"], "version": info["version"], "verified": verified,
                "spki": spki or (old or {}).get("spki"), "luxdrop": info["luxdrop"], "last_seen": time.time(),
            }
        self.on_change()

    def list(self):
        now = time.time()
        with self.lock:
            for k in [k for k, d in self.devices.items() if now - d["last_seen"] > DEVICE_TTL]:
                del self.devices[k]
            return [dict(d) for d in self.devices.values()]

    def clear(self):
        with self.lock:
            self.devices.clear()
            self._probing.clear()
        self.on_change()

    def scan(self, targets=None, port=None, done=None):
        """Prohledani site /24 (jen na vyzadani). Bezi ve vlakne; done() na konci."""
        if self.scanning:
            return False
        self.scanning = True
        port = port or localsend.DEFAULT_PORT

        def run():
            try:
                hosts = targets if targets is not None else scan_targets(interfaces(self.loopback))
                with concurrent.futures.ThreadPoolExecutor(max_workers=48) as ex:
                    list(ex.map(lambda h: self.probe(h, port, timeout=SCAN_TIMEOUT), hosts))
            finally:
                self.scanning = False
                if done:
                    done()
        threading.Thread(target=run, daemon=True, name="localsend-scan").start()
        return True
