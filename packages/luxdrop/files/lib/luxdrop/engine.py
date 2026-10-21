"""LuxDrop - spolecne jadro pro okno, sluzbu na pozadi i prikazovou radku.

Spousti prijem LuxDrop (TLS + SAS, LuxOS <-> LuxOS) a LocalSend (HTTPS, port 53317),
objevovani (mDNS pres Avahi + multicast LocalSend) a sjednocuje seznam zarizeni.
Pocitac LuxOS se v LocalSend oznamuje i s rozsirenim "luxdrop" - jiny LuxOS pak
pouzije bezpecnejsi protokol LuxDrop (overovaci kod, pripnute klice).
"""
import os
import threading

from . import localsend, lsdiscovery, lssend, proto, transfer


class Engine:
    def __init__(self, identity, settings, trust, history, handler, on_change=None, bind="",
                 port=None, ls_port=None, mdns=True, multicast=True):
        self.identity = identity
        self.settings = settings
        self.trust = trust
        self.history = history
        self.handler = handler
        self.on_change = on_change or (lambda: None)
        self.bind = bind
        self.port = port
        self.ls_port = ls_port
        self.use_mdns = mdns and not os.environ.get("LUXDROP_NO_MDNS")
        self.use_multicast = multicast and not os.environ.get("LUXDROP_NO_MULTICAST")
        self.receiver = None
        self.ls_server = None
        self.mdns = None
        self.lsd = None
        self.errors = []
        self.outgoing = lssend.OutgoingSessions()
        self._published = None
        self._announced = False

    # --- Start / stop ---------------------------------------------------------

    def start(self, browse=True):
        self.errors = []
        self.receiver = transfer.Receiver(self.identity, self.settings, self.trust, self.history, self.handler,
                                          bind=self.bind, port=self.port)
        try:
            self.receiver.start()
        except OSError as e:
            self.receiver = None
            self.errors.append(("luxdrop_port", self.port or self.settings["port"], e.strerror or str(e)))
        if self.settings["localsend"]:
            self.start_localsend()
        if self.use_mdns:
            try:
                from .discovery import Discovery
                self.mdns = Discovery(on_change=self.on_change)
                if browse and not self.mdns.browse():
                    self.errors.append(("avahi", 0, self.mdns.error))
            except ImportError:
                self.mdns = None
        self.sync()
        return self

    def start_localsend(self):
        if self.ls_server is None:
            try:
                from .lsserver import LocalSendServer
                srv = LocalSendServer(self.identity, self.settings, self.trust, self.history, self.handler,
                                      port=self.ls_port, bind=self.bind, info_extra=self._luxdrop_ext,
                                      on_register=self._on_register, on_cancel_received=self.outgoing.cancel)
                srv.start()
                self.ls_server = srv
            except ImportError as e:  # chybi python-pyopenssl
                self.errors.append(("localsend_missing", 0, str(e)))
            except OSError as e:
                self.errors.append(("localsend_port", self.ls_port or self.settings["localsend_port"],
                                    e.strerror or str(e)))
        if self.lsd is None:
            self.lsd = lsdiscovery.LocalSendDiscovery(self.identity, self.ls_info, on_change=self.on_change,
                                                      multicast=self.use_multicast)
            if self.use_multicast and not self.lsd.start():
                self.errors.append(("multicast", 0, self.lsd.error))

    def stop(self):
        if self.receiver:
            self.receiver.stop()
        if self.ls_server:
            self.ls_server.stop()
        if self.lsd:
            self.lsd.stop()
        if self.mdns:
            self.mdns.stop()

    # --- Zverejneni -----------------------------------------------------------

    def _luxdrop_ext(self):
        if self.receiver is None or self.settings.mode() == "off":
            return None
        return {"id": self.identity.id, "port": self.receiver.port}

    def ls_info(self):
        port = self.ls_server.port if self.ls_server else (self.ls_port or self.settings["localsend_port"])
        return localsend.my_info(self.settings.name, localsend.cert_fingerprint(self.identity.cert_der), port,
                                 luxdrop=self._luxdrop_ext())

    def receiving(self):
        return self.settings.mode() != "off"

    def sync(self, force=False):
        """Zverejneni podle aktualniho nastaveni (jmeno, rezim)."""
        self.settings.reload()
        key = (self.settings.name, self.receiving(), self.receiver.port if self.receiver else 0)
        if key == self._published and not force:
            return
        changed = self._published is not None and key[:2] != self._published[:2]
        self._published = key
        if self.mdns:
            if key[1] and self.receiver:
                self.mdns.publish(self.settings.name, self.identity.id, self.receiver.port)
            else:
                self.mdns.unpublish()
        if self.lsd:
            self.lsd.enabled = key[1]
            # Oznamujeme i pri vypnutem prijmu: ostatni se nam ozvou a my je najdeme pro odesilani
            if changed or force or not self._announced:
                self._announced = True
                self.lsd.announce()

    def refresh(self):
        """Znovu oznamit a znovu nacist zarizeni (LocalSend "Obnovit")."""
        if self.lsd:
            self.lsd.clear()
            self.lsd.announce()

    def scan(self, done=None, targets=None, port=None):
        """Prohledani mistni site /24 (jen na vyzadani)."""
        if not self.lsd:
            return False
        return self.lsd.scan(targets=targets, port=port, done=done)

    def _on_register(self, ip, info, cert_fp, cert_der):
        if self.lsd:
            self.lsd.registered(ip, info, cert_fp, cert_der)

    # --- Zarizeni -------------------------------------------------------------

    def devices(self):
        """Sjednoceny seznam: LuxOS (LuxDrop) i LocalSend, bez duplicit."""
        self.trust.reload()
        trusted_ids = {e.get("id"): fp for fp, e in self.trust.peers.items()}
        out = {}
        if self.mdns:
            for d in self.mdns.devices(self.identity.id):
                out["lux:" + d["id"]] = {
                    "key": "lux:" + d["id"], "kind": "luxdrop", "name": d["name"], "host": d["host"],
                    "port": d["port"], "id": d["id"], "device_type": "desktop", "device_model": "LuxOS",
                    "trusted": d["id"] in trusted_ids, "secure": True,
                }
        if self.lsd:
            for d in self.lsd.list():
                lux = d.get("luxdrop")
                if lux and lux["id"] != self.identity.id:
                    k = "lux:" + lux["id"]
                    if k not in out:
                        out[k] = {"key": k, "kind": "luxdrop", "name": d["name"], "host": d["host"],
                                  "port": lux["port"], "id": lux["id"], "device_type": "desktop",
                                  "device_model": "LuxOS", "trusted": lux["id"] in trusted_ids, "secure": True}
                    continue
                if lux:
                    continue
                k = "ls:" + d["fingerprint"]
                spki = d.get("spki")
                out[k] = dict(d, key=k, kind="localsend", id=d["fingerprint"][:16].lower(),
                              trusted=bool(spki) and spki.hex() in self.trust.peers,
                              secure=d["protocol"] == "https")
        return sorted(out.values(), key=lambda d: (not d["trusted"], d["name"].lower()))

    def add_manual(self, text, localsend_proto=False, prefer_luxdrop=True):
        """Zarizeni zadane adresou. LocalSend: overi se dotazem /register (vrati zaznam/None).

        prefer_luxdrop=False: i pocitac LuxOS oslovit protokolem LocalSend (luxdrop send --localsend).
        """
        host, port = transfer.parse_addr(text, localsend.DEFAULT_PORT if localsend_proto else proto.DEFAULT_PORT)
        if localsend_proto:
            if self.lsd is None:
                self.lsd = lsdiscovery.LocalSendDiscovery(self.identity, self.ls_info, on_change=self.on_change,
                                                          multicast=False)
            if not self.lsd.probe(host, port, timeout=5):
                return None
            if not prefer_luxdrop:
                for d in self.lsd.list():
                    if d["host"] == host and d["port"] == port:
                        return dict(d, key="ls:" + d["fingerprint"], kind="localsend", trusted=False,
                                    id=d["fingerprint"][:16].lower(), secure=d["protocol"] == "https")
                return None
            for d in self.devices():
                if d["host"] == host and d["port"] == port or (d["kind"] == "luxdrop" and d["host"] == host):
                    return d
            return None
        return {"key": "addr:%s" % transfer.fmt_addr(host, port), "kind": "luxdrop", "name": transfer.fmt_addr(host, port),
                "host": host, "port": port, "id": "", "device_type": "desktop", "device_model": "",
                "trusted": False, "secure": True, "manual": True}

    # --- Odesilani ------------------------------------------------------------

    def send(self, device, callbacks, paths=None, text=None, t=None):
        """Odesle (blokujici - volat ve vlakne). Vrati Transfer."""
        if device["kind"] == "localsend":
            return lssend.send(self.identity, self.settings, self.trust, self.history, device, callbacks,
                               paths=paths, text=text, transfer_obj=t, sessions=self.outgoing)
        if text is not None:
            # LuxDrop prenasi soubory - text posleme jako soubor .txt
            paths = [self.text_file(text)]
        expected = None
        if device.get("id"):
            for fp_hex, e in self.trust.peers.items():
                if e.get("id") == device["id"]:
                    expected = bytes.fromhex(fp_hex)
        t = t or transfer.Transfer("out", device["name"], device.get("id", ""))
        return transfer.send(self.identity, self.settings, self.trust, self.history, device["host"],
                             device["port"], list(paths), callbacks, transfer=t, expected_fp=expected)

    def send_async(self, device, callbacks, paths=None, text=None, done=None):
        t = transfer.Transfer("out", device["name"], device.get("id", ""))
        t.protocol = device["kind"]
        t.device_type = device.get("device_type", "desktop")

        def run():
            self.send(device, callbacks, paths=paths, text=text, t=t)
            if done:
                done(t)
        threading.Thread(target=run, daemon=True).start()
        return t

    @staticmethod
    def text_file(text):
        """Text jako docasny soubor .txt (protokol LuxDrop prenasi jen soubory)."""
        import tempfile
        import time
        d = tempfile.mkdtemp(prefix="luxdrop-text-")
        p = os.path.join(d, "Text %s.txt" % time.strftime("%Y-%m-%d %H-%M-%S"))
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p
