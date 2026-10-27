"""LuxDrop - prikazova radka: send, receive, devices, trust, id, mode (LuxDrop i LocalSend)."""
import argparse
import os
import sys
import threading
import time
import unicodedata

from . import proto, store, transfer
from .identity import Identity

try:
    sys.path.insert(0, "/usr/lib/luxos/python")
    from luxos_i18n import _  # noqa: E402
except ImportError:  # mimo LuxOS (testy)
    def _(text):
        return text

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_DECLINED, EXIT_KEY = 0, 1, 2, 3, 4


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1000.0
    return str(n)


def short_detail(text, limit=80):
    """Text od protistrany (nedůvěryhodný, v cizím jazyce) jen jako krátký jednořádkový detail."""
    text = "".join(" " if (unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp")) else c
                   for c in str(text or ""))
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def error_text(t):
    """Přeložený popis chyby přenosu podle kódu (PROTOCOL.md 9); None = kód bez vlastního textu."""
    out = getattr(t, "direction", "out") == "out"
    texts = {
        proto.E_DECLINED: _("The receiver declined.") if out else _("Declined"),
        proto.E_TIMEOUT: _("The receiver did not answer in time.") if out else _("No answer in time."),
        proto.E_BUSY: _("The receiver is busy. Try again later."),
        proto.E_NOT_TRUSTED: _("The receiver accepts files only from trusted devices."),
        proto.E_RECEIVING_OFF: _("Receiving is turned off on the receiver."),
        proto.E_TOO_LARGE: _("Too many files or too much data for the receiver."),
        proto.E_NO_SPACE: _("Not enough disk space."),
        proto.E_INVALID_OFFER: _("The items were refused as invalid (for example folders or unsafe names)."),
        proto.E_AUTH_FAILED: _("The device could not be verified."),
        proto.E_PROTO_VERSION: _("Incompatible LuxDrop version."),
        proto.E_PROTOCOL: _("Connection error."),
        proto.E_HASH_MISMATCH: _("The data was damaged on the way. Nothing was saved – try again."),
        proto.E_CANCELLED: _("Cancelled"),
        proto.E_INTERNAL: _("Internal error."),
        proto.E_KEY_MISMATCH: _("The device presented a different key than expected."),
        proto.E_SAS_REJECTED: _("Cancelled: the codes were not confirmed."),
    }
    return texts.get(getattr(t, "code", None))


def failure_text(t):
    """(hlavní text, detail): přeložený text podle kódu, zpráva protistrany / spojení jen jako detail."""
    main = error_text(t)
    detail = short_detail(getattr(t, "error", ""))
    if main is None:
        return detail or _("Connection error."), ""
    if detail.lower() in ("", str(t.code).lower(), "cancelled", "declined", "no answer"):
        detail = ""
    return main, detail


class Ctx:
    def __init__(self):
        self.identity = Identity.load_or_create()
        self.settings = store.Settings()
        self.trust = store.TrustStore()
        self.history = store.History()


_input_lock = threading.Lock()


def ask_line(prompt, abort=None):
    """Precte odpoved; kdyz abort() vrati True, vrati None (napr. druha strana uz rozhodla)."""
    import select
    with _input_lock:
        sys.stdout.write(prompt)
        sys.stdout.flush()
        while abort is not None:
            r, _w, _x = select.select([sys.stdin], [], [], 0.2)
            if r:
                break
            if abort():
                sys.stdout.write("\n")
                return None
        line = sys.stdin.readline()
        return line.strip().lower()


# --- send ---------------------------------------------------------------------

class CliSend(transfer.SendCallbacks):
    def __init__(self, remember_default=True, show_progress=True, pin=None):
        self.remember_default = remember_default
        self.show_progress = show_progress
        self.pin = pin
        self._last = 0.0

    def confirm(self, info, replied):
        print(_("Receiver: %s (ID %s)") % (info["peer_name"], info["peer_id"]))
        print(_("Verification code: %s") % proto.format_sas(info["sas"]), flush=True)
        a = ask_line(_("Does %s show the same code? [y]es and remember / [o]nly this time / [N]o: ")
                     % info["peer_name"], abort=lambda: replied.is_set() and not getattr(replied, "accepted", False))
        if a in ("y", "yes", "a", "ano"):
            return True, self.remember_default
        if a in ("o", "once"):
            return True, False
        return False, False

    def ask_pin(self, peer_name, wrong):
        if self.pin is not None and not wrong:
            return self.pin
        if wrong:
            print(_("Wrong PIN."), file=sys.stderr)
        a = ask_line(_("%s requires a PIN: ") % peer_name)
        return a or None

    def update(self, t):
        if not self.show_progress:
            return
        now = time.monotonic()
        if now - self._last < 0.5 and t.state not in ("done", "failed"):
            return
        self._last = now
        if t.state in ("preparing", "transferring"):
            pct = int(100 * t.fraction())
            label = _("Preparing") if t.state == "preparing" else _("Sending")
            sys.stderr.write("\r%s %3d %%  %s / %s   " % (label, pct, human(t.done), human(t.total)))
            sys.stderr.flush()
        elif t.state == "waiting":
            sys.stderr.write("\r" + _("Waiting for the receiver to accept…") + "          \n")


def resolve_target(ctx, target, port_override=None, timeout=3.0):
    """Vrati (host, port, ocekavany_otisk nebo None, popis)."""
    expect_key, addr = None, None
    target = target.strip()
    if not target:
        raise SystemExit(_("Device '%s' not found on the network. Use an address: luxdrop send HOST[:PORT] FILES")
                         % target)
    if "@" in target:
        expect_key, addr = target.rsplit("@", 1)
    elif any(c in target for c in ".:") or target == "localhost":
        addr = target
    else:
        expect_key = target
    expected_fp = None
    if expect_key is not None:
        hits = ctx.trust.find(expect_key)
        if len(hits) > 1:
            raise SystemExit(_("'%s' matches more trusted devices, use the ID") % expect_key)
        if hits:
            expected_fp = bytes.fromhex(hits[0][0])
        elif addr is not None:
            raise SystemExit(_("'%s' is not a trusted device (see 'luxdrop trust list')") % expect_key)
    if addr is not None:
        host, port = transfer.parse_addr(addr, port_override or proto.DEFAULT_PORT)
        return host, port, expected_fp
    # Hledani v siti podle ID nebo jmena
    found = discover(timeout, ctx.identity.id)
    for d in found:
        if (expected_fp is not None and d["id"] == proto.short_id(expected_fp)) or \
           (expected_fp is None and (d["name"].lower() == target.lower() or
                                     (len(target) >= 6 and d["id"].startswith(target.lower())))):
            return d["host"], port_override or d["port"], expected_fp
    if expected_fp is not None:
        last = ctx.trust.get(expected_fp).get("last_addr")
        if last:
            host, port = transfer.parse_addr(last)
            return host, port_override or port, expected_fp
    raise SystemExit(_("Device '%s' not found on the network. Use an address: luxdrop send HOST[:PORT] FILES")
                     % target)


def discover(timeout, own_id=None):
    try:
        from gi.repository import GLib
        from .discovery import Discovery
    except ImportError:
        return []
    loop = GLib.MainLoop()
    d = Discovery()
    if not d.browse():
        return []
    GLib.timeout_add(int(timeout * 1000), loop.quit)
    loop.run()
    d.stop()
    return d.devices(own_id)


def resolve_localsend(ctx, target, timeout=4.0):
    """LocalSend zarizeni podle adresy (overi se /register) nebo jmena (multicast)."""
    from .engine import Engine
    eng = Engine(ctx.identity, ctx.settings, ctx.trust, ctx.history, transfer.Handler(), mdns=False)
    target = target.strip()
    if any(c in target for c in ".:") or target == "localhost":
        eng.lsd = None
        d = eng.add_manual(target, localsend_proto=True, prefer_luxdrop=False)
        if d is None:
            raise SystemExit(_("No LocalSend device answers at %s") % target)
        return d
    eng.start_localsend()
    eng.sync(force=True)
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            for d in eng.devices():
                if d["name"].lower() == target.lower() or (len(target) >= 6 and d["id"].startswith(target.lower())):
                    return d
            time.sleep(0.2)
    finally:
        eng.stop()
    raise SystemExit(_("Device '%s' not found on the network. Use an address: luxdrop send HOST[:PORT] FILES")
                     % target)


def cmd_send(args):
    ctx = Ctx()
    if args.text is None and not args.files:
        print(_("Nothing to send: give files or --text"), file=sys.stderr)
        return EXIT_USAGE
    for p in args.files:
        if not os.path.lexists(p):
            print(_("File not found: %s") % p, file=sys.stderr)
            return EXIT_USAGE
    cb = CliSend(remember_default=not args.no_remember, show_progress=not args.quiet, pin=args.pin)
    t = transfer.Transfer("out")
    result = {}
    if args.localsend:
        device = resolve_localsend(ctx, args.target)
        if device["kind"] == "luxdrop":
            print(_("%s is a LuxOS computer - using the LuxDrop protocol") % device["name"], file=sys.stderr)

        def run():
            from .engine import Engine
            eng = Engine(ctx.identity, ctx.settings, ctx.trust, ctx.history, transfer.Handler(), mdns=False)
            result["t"] = eng.send(device, cb, paths=args.files or None, text=args.text, t=t)
    else:
        host, port, expected_fp = resolve_target(ctx, args.target, args.port)
        files = list(args.files)
        if args.text is not None:
            from .engine import Engine
            files.append(Engine.text_file(args.text))

        def run():
            result["t"] = transfer.send(ctx.identity, ctx.settings, ctx.trust, ctx.history, host, port,
                                        files, cb, transfer=t, expected_fp=expected_fp)

    th = threading.Thread(target=run, daemon=True)
    th.start()
    try:
        while th.is_alive():
            th.join(0.2)
    except KeyboardInterrupt:
        print("\n" + _("Cancelling…"), file=sys.stderr)
        t.cancel()
        th.join(10)
    t = result.get("t", t)
    sys.stderr.write("\n")
    for p, why in t.skipped:
        print(_("Skipped %s (%s)") % (p, why), file=sys.stderr)
    if t.state == "done":
        print(_("Sent %d item(s), %s to %s") % (len(t.items), human(t.total), t.peer_name)
              + ((" " + _("(resumed, %s were already there)") % human(t.resumed)) if t.resumed else ""))
        return EXIT_OK
    main, detail = failure_text(t)
    print(_("Transfer failed: %s (%s)") % (main, t.code), file=sys.stderr)
    if detail:
        print(_("Details: %s") % detail, file=sys.stderr)
    if t.code == proto.E_KEY_MISMATCH:
        print(_("WARNING: someone may be impersonating this device. Nothing was sent. If the device was "
                "reinstalled, remove it with 'luxdrop trust remove ID' and pair again."), file=sys.stderr)
        return EXIT_KEY
    return EXIT_DECLINED if t.state in ("declined", "cancelled") else EXIT_FAIL


# --- receive ------------------------------------------------------------------

class CliReceive(transfer.Handler):
    def ask(self, req):
        print()
        if req.message is not None:
            print(_("Message from %s:") % req.peer_name)
            print(req.message, flush=True)
            return False, False
        if req.name_clash:
            print(_("WARNING: this device uses the name of a trusted device, but a different key!"))
        print(_("%s (ID %s) wants to send you %d item(s), %s:")
              % (req.peer_name, req.peer_id, len(req.items), human(req.total)))
        for n in req.items[:10]:
            print("   " + n)
        if req.protocol == "localsend":
            print(_("Sent with LocalSend from a %s device") % req.device_type
                  + ("" if req.verified else " - " + _("identity not verified (old LocalSend version)")))
        if req.sas:
            print(_("Verification code: %s  (must be the same on the sender's screen)") % proto.format_sas(req.sas))
            a = ask_line(_("Accept? [y]es / [a]ccept and trust this device / [N]o: "), abort=req.withdrawn.is_set)
        elif req.can_trust:
            a = ask_line(_("Accept? [y]es / [a]ccept and trust this device / [N]o: "), abort=req.withdrawn.is_set)
        else:
            a = ask_line(_("Accept? [y/N]: "), abort=req.withdrawn.is_set)
        if a is None or req.withdrawn.is_set():
            print(_("The sender cancelled the request."))
            return False, False
        return a in ("y", "yes", "a", "ano"), a == "a"

    def finished(self, t):
        if t.state == "done":
            print(_("Received from %s: %s") % (t.peer_name, ", ".join(t.saved)), flush=True)
        elif t.state == "declined":
            print(_("Declined transfer from %s") % t.peer_name, flush=True)
        else:
            main, detail = failure_text(t)
            print(_("Transfer from %s failed: %s (%s)") % (t.peer_name, main, t.code), flush=True)
            if detail:
                print(_("Details: %s") % detail, flush=True)


def cmd_receive(args):
    ctx = Ctx()
    if args.mode:
        ctx.settings.set_mode(args.mode, args.minutes)
    if args.dir:
        ctx.settings.set("download_dir", os.path.abspath(args.dir))
    if args.pin is not None:
        ctx.settings.set("pin", args.pin)
    if args.no_localsend:
        ctx.settings.data["localsend"] = False  # jen pro tento beh
    if args.service:
        from .service import run_service
        return run_service(ctx, args)
    from .engine import Engine
    eng = Engine(ctx.identity, ctx.settings, ctx.trust, ctx.history, CliReceive(), bind=args.bind or "",
                 port=args.port, ls_port=args.ls_port, mdns=not args.no_mdns, multicast=not args.no_multicast)
    eng.start(browse=False)
    if eng.receiver is None:
        print(_("Cannot listen on port %d: %s") % (args.port or ctx.settings["port"], eng.errors[0][2]), file=sys.stderr)
        return EXIT_FAIL
    for kind, port, err in eng.errors:
        if kind == "avahi":
            print(_("Not visible on the network (%s); connect by address.") % err, file=sys.stderr)
        elif kind == "localsend_port":
            print(_("LocalSend receiving is not available: port %d is in use (%s)") % (port, err), file=sys.stderr)
        elif kind == "localsend_missing":
            print(_("LocalSend receiving is not available (python-pyopenssl is missing)"), file=sys.stderr)
        elif kind == "multicast":
            print(_("LocalSend devices cannot find this computer automatically (%s)") % err, file=sys.stderr)
    print(_("Receiving as \"%s\" (ID %s) on port %d, mode: %s, folder: %s")
          % (ctx.settings.name, ctx.identity.id, eng.receiver.port, ctx.settings.mode(), ctx.settings.download_dir),
          flush=True)
    if eng.ls_server:
        print(_("LocalSend: port %d, fingerprint %s") % (eng.ls_server.port, eng.ls_server.fingerprint[:16]),
              flush=True)
    try:
        while True:
            time.sleep(1)
            eng.sync()
    except KeyboardInterrupt:
        pass
    finally:
        eng.stop()
    return EXIT_OK


# --- ostatni ------------------------------------------------------------------

def cmd_devices(args):
    ctx = Ctx()
    from .engine import Engine
    eng = Engine(ctx.identity, ctx.settings, ctx.trust, ctx.history, transfer.Handler(), mdns=True)
    eng.start()  # prijem kvuli odpovedim LocalSend (POST /register); obsazene porty nevadi
    if args.scan:
        eng.scan()
    found = {}
    try:
        from gi.repository import GLib
        loop = GLib.MainLoop()
        GLib.timeout_add(int(args.timeout * 1000), loop.quit)
        loop.run()
    except ImportError:
        time.sleep(args.timeout)
    while args.scan and eng.lsd and eng.lsd.scanning:
        time.sleep(0.2)
    for d in eng.devices():
        found[d["key"]] = d
    eng.stop()
    if found:
        print(_("Nearby devices:"))
        for d in found.values():
            mark = _("trusted") if d["trusted"] else ""
            kind = "LuxOS" if d["kind"] == "luxdrop" else "LocalSend/" + d["device_type"]
            if d["kind"] == "localsend" and not d["secure"]:
                mark = _("unencrypted - not supported")
            print("  %-28s %-16s %-18s %s  %s" % (d["name"], d["id"], kind, transfer.fmt_addr(d["host"], d["port"]),
                                                  mark))
    else:
        print(_("No devices found nearby (is Avahi running?)."))
    return EXIT_OK


def cmd_trust(args):
    ctx = Ctx()
    if args.action == "remove":
        n = ctx.trust.remove(args.key or "")
        print(_("Removed %d device(s)") % n)
        return EXIT_OK if n else EXIT_FAIL
    if not ctx.trust.peers:
        print(_("No trusted devices."))
    for fp_hex, e in sorted(ctx.trust.peers.items(), key=lambda kv: kv[1].get("name", "")):
        print("%-28s %s  %s" % (e.get("name", "?"), e.get("id", fp_hex[:16]), e.get("last_addr", "")))
        print("    " + proto.format_fp(bytes.fromhex(fp_hex)))
    return EXIT_OK


def cmd_id(_args):
    ctx = Ctx()
    print(_("Name: %s") % ctx.settings.name)
    print(_("ID: %s") % ctx.identity.id)
    print(_("Fingerprint: %s") % proto.format_fp(ctx.identity.fp))
    return EXIT_OK


def cmd_mode(args):
    s = store.Settings()
    if args.mode:
        s.set_mode(args.mode, args.minutes)
    left = s.everyone_left()
    print(s.mode() + ((" (%d min)" % (left // 60 + 1)) if left else ""))
    return EXIT_OK


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmds = {"send", "receive", "devices", "trust", "id", "mode", "gui", "share", "connect", "disconnect",
            "connections", "-h", "--help"}
    if not argv or argv[0] not in cmds:
        # luxdrop [soubory...] -> graficka aplikace (Thunar, "Otevrit pomoci")
        from .gui import main as gui_main
        return gui_main([a for a in argv if a != "--"])
    if argv[0] == "gui":
        from .gui import main as gui_main
        return gui_main(argv[1:])
    try:
        from luxos_i18n import argparse_i18n      # usage:, options, chyby argparse v jazyce uzivatele
        argparse_i18n()
    except ImportError:  # mimo LuxOS (testy)
        pass
    ap = argparse.ArgumentParser(prog="luxdrop", description=_("Send files securely to nearby LuxOS computers "
                                                                "and devices with LocalSend."))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("send", help=_("send files or folders"))
    s.add_argument("target", help=_("device name, ID, HOST[:PORT] or NAME@HOST[:PORT]"))
    s.add_argument("files", nargs="*")
    s.add_argument("--port", type=int)
    s.add_argument("--localsend", action="store_true", help=_("send to a LocalSend device (phone, Windows, …)"))
    s.add_argument("--text", help=_("send a text message"))
    s.add_argument("--pin", help=_("PIN required by the receiver (LocalSend)"))
    s.add_argument("--no-remember", action="store_true", help=_("do not trust the receiver after verification"))
    s.add_argument("-q", "--quiet", action="store_true")
    r = sub.add_parser("receive", help=_("receive files in the terminal"))
    r.add_argument("--port", type=int)
    r.add_argument("--bind", help=_("listen only on this address"))
    r.add_argument("--mode", choices=store.MODES, help=_("who can send (everyone always asks first)"))
    r.add_argument("--minutes", type=int, help=_("with --mode everyone: only for this many minutes (max. 10)"))
    r.add_argument("--dir", help=_("download folder"))
    r.add_argument("--no-mdns", action="store_true", help=_("do not announce on the network"))
    r.add_argument("--ls-port", type=int, help=_("LocalSend port (default 53317)"))
    r.add_argument("--no-localsend", action="store_true", help=_("do not receive from LocalSend apps"))
    r.add_argument("--no-multicast", action="store_true", help=_("no LocalSend multicast discovery"))
    r.add_argument("--pin", help=_("require this PIN from LocalSend senders (empty = no PIN)"))
    r.add_argument("--service", action="store_true", help=argparse.SUPPRESS)
    d = sub.add_parser("devices", help=_("list nearby devices"))
    d.add_argument("--timeout", type=float, default=3.0)
    d.add_argument("--scan", action="store_true", help=_("also scan the local network (LocalSend devices without multicast)"))
    t = sub.add_parser("trust", help=_("list or remove trusted devices"))
    t.add_argument("action", choices=("list", "remove"), nargs="?", default="list")
    t.add_argument("key", nargs="?", help=_("ID or name"))
    sub.add_parser("id", help=_("show this device's name and fingerprint"))
    m = sub.add_parser("mode", help=_("show or set who can send to this computer"))
    m.add_argument("mode", nargs="?", choices=store.MODES)
    m.add_argument("--minutes", type=int, help=_("with everyone: only for this many minutes (max. 10)"))
    from . import remote_cli
    remote_cmds = remote_cli.add_parsers(sub)
    a = ap.parse_args(argv)
    fn = {"send": cmd_send, "receive": cmd_receive, "devices": cmd_devices, "trust": cmd_trust,
          "id": cmd_id, "mode": cmd_mode, **remote_cmds}[a.cmd]
    try:
        return fn(a)
    except RuntimeError as e:
        print("luxdrop: %s" % e, file=sys.stderr)
        return EXIT_FAIL
