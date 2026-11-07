"""Spolecne pomucky testu Posty LuxOS: soukrome prostredi (HOME, XDG_*, D-Bus, klicenka),
testovaci CA (duveryhodna jen v testu pres SSL_CERT_FILE), testovaci server IMAP a klient sluzby.

Nikdy se nepripojuje ke skutecne schrance ani ke skutecne relaci uzivatele.
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
USER = "tester@example.test"
PASSWORD = "heslo-123 žluť"


def binary():
    path = os.environ.get("LUXOS_MAIL_BIN", "")
    if path:
        return path
    raise RuntimeError("set LUXOS_MAIL_BIN to the compiled luxos-mail")


def run_bin(args, env=None, input=None, timeout=30):
    return subprocess.run([binary()] + args, capture_output=True, env=env, input=input, timeout=timeout)


def make_certs(directory, hostname="localhost"):
    """CA + certifikat serveru podepsany CA, a zvlast certifikat podepsany sam sebou (neduveryhodny)."""
    def openssl(*args):
        subprocess.run(["openssl"] + list(args), check=True, capture_output=True)
    ca_key = os.path.join(directory, "ca.key")
    ca = os.path.join(directory, "ca.pem")
    openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", ca_key, "-out", ca, "-days", "2",
            "-subj", "/CN=LuxOS Mail Test CA")
    key = os.path.join(directory, "server.key")
    csr = os.path.join(directory, "server.csr")
    cert = os.path.join(directory, "server.pem")
    ext = os.path.join(directory, "ext.cnf")
    with open(ext, "w") as f:
        f.write("subjectAltName=DNS:%s,IP:127.0.0.1\n" % hostname)
    openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", csr, "-subj", "/CN=" + hostname)
    openssl("x509", "-req", "-in", csr, "-CA", ca, "-CAkey", ca_key, "-CAcreateserial", "-out", cert, "-days", "2",
            "-extfile", ext)
    bad_key = os.path.join(directory, "bad.key")
    bad = os.path.join(directory, "bad.pem")
    openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", bad_key, "-out", bad, "-days", "2",
            "-subj", "/CN=" + hostname, "-addext", "subjectAltName=DNS:%s" % hostname)
    return {"ca": ca, "cert": cert, "key": key, "bad_cert": bad, "bad_key": bad_key}


def wait_for(predicate, timeout=10.0, step=0.05):
    end = time.time() + timeout
    while time.time() < end:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return predicate()


class FakeServer:
    def __init__(self, workdir, certs, seed=None, qresync=False, bad=False, ports=None, oauth="", sasl_ir=True, dovecot_flags=False):
        self.ready = os.path.join(workdir, "server-%d.json" % int(time.time() * 1000))
        args = [sys.executable, os.path.join(HERE, "fake_imap.py"), "--cert", certs["bad_cert" if bad else "cert"],
                "--key", certs["bad_key" if bad else "key"], "--ready", self.ready, "--user", USER, "--password", PASSWORD]
        if seed:
            args += ["--seed", seed]
        if qresync:
            args.append("--qresync")
        if ports:
            args += ["--port", str(ports["tls"]), "--starttls-port", str(ports["starttls"])]
        if oauth:
            args += ["--oauth", oauth]
        if not sasl_ir:
            args.append("--no-sasl-ir")
        if dovecot_flags:
            args.append("--dovecot-flags")
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if not wait_for(lambda: os.path.exists(self.ready), 10):
            raise RuntimeError("fake IMAP server did not start: " + self.proc.stderr.read().decode())
        with open(self.ready) as f:
            self.ports = json.load(f)

    def control(self, line):
        with socket.create_connection(("127.0.0.1", self.ports["control"]), timeout=10) as s:
            s.sendall((line + "\n").encode())
            data = b""
            while not data.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
        return json.loads(data)

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class Session:
    """Soukrome prostredi: docasny HOME, XDG_RUNTIME_DIR (700), vlastni D-Bus relace a gnome-keyring."""

    def __init__(self, keyring=True, notifications=True):
        self.root = tempfile.mkdtemp(prefix="luxos-mail-test-")
        self.home = os.path.join(self.root, "home")
        self.run = os.path.join(self.root, "run")
        os.makedirs(self.home)
        os.makedirs(self.run)
        os.chmod(self.run, 0o700)
        self.certs = make_certs(self.root)
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XAUTHORITY", "SSH_AUTH_SOCK", "GNOME_KEYRING_CONTROL")}
        env.update({"HOME": self.home, "XDG_RUNTIME_DIR": self.run, "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
                    "XDG_DATA_HOME": os.path.join(self.home, ".local/share"), "XDG_CACHE_HOME": os.path.join(self.home, ".cache"),
                    "SSL_CERT_FILE": self.certs["ca"], "LANG": "cs_CZ.UTF-8", "LUXOS_MAIL_NO_SYSTEM_BUS": "1",
                    "NO_AT_BRIDGE": "1", "GTK_USE_PORTAL": "0", "GIO_USE_VFS": "local",
                    "LUXOS_MAIL_INSTANCE": "-test%d" % os.getpid(),
                    "LUXOS_I18N_DIR": os.path.join(HERE, "..", "..", "..", "luxos-i18n", "files")})
        if not os.path.isdir(env["LUXOS_I18N_DIR"]):
            env["LUXOS_I18N_DIR"] = os.path.join(HERE, "..", "..", "luxos-i18n", "files")
        self.env = env
        self.procs = []
        self.notify_log = os.path.join(self.root, "notifications.jsonl")
        # vlastni sbernice relace
        p = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"], stdout=subprocess.PIPE, env=env)
        self.procs.append(p)
        address = p.stdout.readline().decode().strip()
        self.env["DBUS_SESSION_BUS_ADDRESS"] = address
        if keyring:
            # odemcena klicenka "login" s testovacim heslem (stdin), jen komponenta secrets
            k = subprocess.run(["gnome-keyring-daemon", "--unlock", "--components=secrets", "--daemonize"],
                               input=b"test-keyring\n", capture_output=True, env=self.env, timeout=20)
            for line in k.stdout.decode().splitlines():
                if "=" in line:
                    name, value = line.split("=", 1)
                    self.env[name] = value
                    if name == "GNOME_KEYRING_PID":
                        self.keyring_pid = int(value)
        if notifications:
            n = subprocess.Popen([sys.executable, os.path.join(HERE, "fake_notifyd.py"), self.notify_log], env=self.env,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            n.stdout.readline()
            self.procs.append(n)
        self.service = None

    def start_service(self):
        log = open(os.path.join(self.root, "service.log"), "ab")
        self.service = subprocess.Popen([binary(), "--background"], env=self.env, stdout=log, stderr=log)
        self.procs.append(self.service)
        sock = None
        end = time.time() + 10
        while time.time() < end:
            try:
                sock = Client(self)
                break
            except OSError:
                time.sleep(0.05)
        if sock is None:
            raise RuntimeError("service did not start")
        return sock

    def service_log(self):
        try:
            with open(os.path.join(self.root, "service.log"), errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    def notifications(self):
        out = []
        if os.path.exists(self.notify_log):
            with open(self.notify_log) as f:
                for line in f:
                    out.append(json.loads(line))
        return out

    def secret_lookup(self, account):
        r = subprocess.run(["secret-tool", "lookup", "service", "luxos-mail", "account", account], capture_output=True, env=self.env, timeout=10)
        return r.stdout.decode()

    def close(self):
        for p in reversed(self.procs):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
        pid = getattr(self, "keyring_pid", 0)
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        shutil.rmtree(self.root, ignore_errors=True)


class Client:
    """Klient sluzby luxos-mail (abstraktni socket UNIX), jako okno."""

    def __init__(self, session):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect("\0luxos-mail-%d%s" % (os.getuid(), session.env.get("LUXOS_MAIL_INSTANCE", "")))
        self.sock.settimeout(60)
        self.buf = b""
        self.next = 1
        self.events = []

    def _line(self):
        while b"\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("service closed the connection")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line)

    def call(self, op, **fields):
        rid = self.next
        self.next += 1
        msg = dict(fields)
        msg["id"] = rid
        msg["op"] = op
        self.sock.sendall((json.dumps(msg) + "\n").encode())
        while True:
            m = self._line()
            if "event" in m:
                self.events.append(m)
                continue
            if m.get("id") == rid:
                return m

    def wait_event(self, predicate, timeout=10):
        end = time.time() + timeout
        for e in self.events:
            if predicate(e):
                return e
        self.sock.settimeout(0.2)
        try:
            while time.time() < end:
                try:
                    m = self._line()
                except socket.timeout:
                    continue
                if "event" in m:
                    self.events.append(m)
                    if predicate(m):
                        return m
        finally:
            self.sock.settimeout(60)
        return None

    def close(self):
        self.sock.close()


def account_request(server, security="ssl", password=PASSWORD):
    port = server.ports["tls"] if security == "ssl" else server.ports["starttls"]
    return {"email": USER, "name": "Tester", "password": password,
            "imap": {"host": "localhost", "port": port, "security": security, "user": USER},
            "smtp": {"host": "localhost", "port": 587, "security": "starttls"}}
