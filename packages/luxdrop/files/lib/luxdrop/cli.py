"""LuxDrop - prikazova radka: send, receive, devices, trust, id, mode."""
import argparse
import os
import sys
import threading
import time

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
    def __init__(self, remember_default=True, show_progress=True):
        self.remember_default = remember_default
        self.show_progress = show_progress
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


def cmd_send(args):
    ctx = Ctx()
    for p in args.files:
        if not os.path.lexists(p):
            print(_("File not found: %s") % p, file=sys.stderr)
            return EXIT_USAGE
    host, port, expected_fp = resolve_target(ctx, args.target, args.port)
    cb = CliSend(remember_default=not args.no_remember, show_progress=not args.quiet)
    t = transfer.Transfer("out")
    result = {}

    def run():
        result["t"] = transfer.send(ctx.identity, ctx.settings, ctx.trust, ctx.history, host, port,
                                    args.files, cb, transfer=t, expected_fp=expected_fp)

    th = threading.Thread(target=run, daemon=True)
    th.start()
    try:
        while th.is_alive():
            th.join(0.2)
    except KeyboardInterrupt:
        print("\n" + _("Cancelling…"), file=sys.stderr)
        t.cancel()
        th.join(10)
    sys.stderr.write("\n")
    for p, why in t.skipped:
        print(_("Skipped %s (%s)") % (p, why), file=sys.stderr)
    if t.state == "done":
        print(_("Sent %d item(s), %s to %s") % (len(t.items), human(t.total), t.peer_name)
              + ((" " + _("(resumed, %s were already there)") % human(t.resumed)) if t.resumed else ""))
        return EXIT_OK
    print(_("Transfer failed: %s (%s)") % (t.error, t.code), file=sys.stderr)
    if t.code == proto.E_KEY_MISMATCH:
        print(_("WARNING: someone may be impersonating this device. Nothing was sent. If the device was "
                "reinstalled, remove it with 'luxdrop trust remove ID' and pair again."), file=sys.stderr)
        return EXIT_KEY
    return EXIT_DECLINED if t.state in ("declined", "cancelled") else EXIT_FAIL


# --- receive ------------------------------------------------------------------

class CliReceive(transfer.Handler):
    def ask(self, req):
        print()
        if req.name_clash:
            print(_("WARNING: this device uses the name of a trusted device, but a different key!"))
        print(_("%s (ID %s) wants to send you %d item(s), %s:")
              % (req.peer_name, req.peer_id, len(req.items), human(req.total)))
        for n in req.items[:10]:
            print("   " + n)
        if req.sas:
            print(_("Verification code: %s  (must be the same on the sender's screen)") % proto.format_sas(req.sas))
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
            print(_("Transfer from %s failed: %s (%s)") % (t.peer_name, t.error, t.code), flush=True)


def cmd_receive(args):
    ctx = Ctx()
    if args.mode:
        ctx.settings.set_mode(args.mode)
    if args.dir:
        ctx.settings.set("download_dir", os.path.abspath(args.dir))
    if args.service:
        from .service import run_service
        return run_service(ctx, args)
    handler = CliReceive()
    rx = transfer.Receiver(ctx.identity, ctx.settings, ctx.trust, ctx.history, handler,
                           bind=args.bind or "", port=args.port)
    try:
        port = rx.start()
    except OSError as e:
        print(_("Cannot listen on port %d: %s") % (args.port or ctx.settings["port"], e.strerror), file=sys.stderr)
        return EXIT_FAIL
    disc = None
    if not args.no_mdns:
        try:
            from .discovery import Discovery
            disc = Discovery()
            if not disc.publish(ctx.settings.name, ctx.identity.id, port):
                print(_("Not visible on the network (%s); connect by address.") % disc.error, file=sys.stderr)
        except ImportError:
            pass
    print(_("Receiving as \"%s\" (ID %s) on port %d, mode: %s, folder: %s")
          % (ctx.settings.name, ctx.identity.id, port, ctx.settings.mode(), ctx.settings.download_dir), flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        rx.stop()
        if disc:
            disc.unpublish()
    return EXIT_OK


# --- ostatni ------------------------------------------------------------------

def cmd_devices(args):
    ctx = Ctx()
    found = discover(args.timeout, ctx.identity.id)
    trusted_ids = {e.get("id") for e in ctx.trust.peers.values()}
    if found:
        print(_("Nearby devices:"))
        for d in found:
            mark = _("trusted") if d["id"] in trusted_ids else ""
            print("  %-28s %-16s %s  %s" % (d["name"], d["id"], transfer.fmt_addr(d["host"], d["port"]), mark))
    else:
        print(_("No devices found nearby (is avahi-daemon running?)."))
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
        s.set_mode(args.mode)
    left = s.everyone_left()
    print(s.mode() + ((" (%d min)" % (left // 60 + 1)) if s.mode() == "everyone" else ""))
    return EXIT_OK


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmds = {"send", "receive", "devices", "trust", "id", "mode", "gui", "-h", "--help"}
    if not argv or argv[0] not in cmds:
        # luxdrop [soubory...] -> graficka aplikace (Thunar, "Otevrit pomoci")
        from .gui import main as gui_main
        return gui_main([a for a in argv if a != "--"])
    if argv[0] == "gui":
        from .gui import main as gui_main
        return gui_main(argv[1:])
    ap = argparse.ArgumentParser(prog="luxdrop", description=_("Send files securely between LuxOS computers."))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("send", help=_("send files or folders"))
    s.add_argument("target", help=_("device name, ID, HOST[:PORT] or NAME@HOST[:PORT]"))
    s.add_argument("files", nargs="+")
    s.add_argument("--port", type=int)
    s.add_argument("--no-remember", action="store_true", help=_("do not trust the receiver after verification"))
    s.add_argument("-q", "--quiet", action="store_true")
    r = sub.add_parser("receive", help=_("receive files in the terminal"))
    r.add_argument("--port", type=int)
    r.add_argument("--bind", help=_("listen only on this address"))
    r.add_argument("--mode", choices=store.MODES, help=_("who can send (everyone = for 10 minutes)"))
    r.add_argument("--dir", help=_("download folder"))
    r.add_argument("--no-mdns", action="store_true", help=_("do not announce on the network"))
    r.add_argument("--service", action="store_true", help=argparse.SUPPRESS)
    d = sub.add_parser("devices", help=_("list nearby devices"))
    d.add_argument("--timeout", type=float, default=3.0)
    t = sub.add_parser("trust", help=_("list or remove trusted devices"))
    t.add_argument("action", choices=("list", "remove"), nargs="?", default="list")
    t.add_argument("key", nargs="?", help=_("ID or name"))
    sub.add_parser("id", help=_("show this device's name and fingerprint"))
    m = sub.add_parser("mode", help=_("show or set who can send to this computer"))
    m.add_argument("mode", nargs="?", choices=store.MODES)
    a = ap.parse_args(argv)
    fn = {"send": cmd_send, "receive": cmd_receive, "devices": cmd_devices, "trust": cmd_trust,
          "id": cmd_id, "mode": cmd_mode}[a.cmd]
    try:
        return fn(a)
    except RuntimeError as e:
        print("luxdrop: %s" % e, file=sys.stderr)
        return EXIT_FAIL
