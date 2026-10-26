"""LuxDrop - prikazy pro soubory jineho pocitace: share, connect, disconnect, connections."""
import os
import signal
import subprocess
import sys
import threading
import time

from . import proto, remote, transfer
from .cli import EXIT_DECLINED, EXIT_FAIL, EXIT_KEY, EXIT_OK, EXIT_USAGE, Ctx, _, ask_line

SERVICE = "luxdrop-files.service"


def _systemctl(*args):
    if os.environ.get("LUXDROP_NO_SYSTEMD"):
        return
    try:
        subprocess.run(["systemctl", "--user"] + list(args), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        pass


def set_sharing(on):
    """Zapne/vypne sdileni (nastaveni + uzivatelska sluzba); vrati Shares."""
    shares = remote.Shares()
    shares.set_enabled(on)
    if on:
        _systemctl("enable", "--now", SERVICE)
    else:
        _systemctl("disable", "--now", SERVICE)
    return shares


# --- share ---------------------------------------------------------------------

class TerminalAsker:
    """Dotaz na pristup v terminalu (luxdrop share serve bez --service)."""

    def __call__(self, req):
        print()
        if req.name_clash:
            print(_("WARNING: this device uses the name of a trusted device, but a different key!"))
        print((_("“%s” wants to access and change your shared folders") if req.want_write
               else _("“%s” wants to access your shared folders")) % req.peer_name + " (ID %s)" % req.peer_id)
        if req.sas:
            print(_("Verification code: %s") % proto.format_sas(req.sas))
        a = ask_line(_("Allow? [o]nce / [a]lways / [N]o: "), abort=req.withdrawn.is_set)
        if a is None or req.withdrawn.is_set():
            print(_("The other computer cancelled the request."))
            return "deny", False
        decision = {"o": "once", "once": "once", "a": "always", "always": "always"}.get(a, "deny")
        write = False
        if decision != "deny" and req.want_write:
            w = ask_line(_("Also allow changes (copy in, rename and delete files)? [y/N]: "),
                         abort=req.withdrawn.is_set)
            write = w in ("y", "yes", "a", "ano")
        return decision, write


def serve(args):
    ctx = Ctx()
    shares = remote.Shares()
    if not shares.enabled:
        print(_("Sharing is turned off. Turn it on with: luxdrop share on"), file=sys.stderr)
        return EXIT_OK if args.service else EXIT_FAIL
    if remote.sftp_server_path() is None:
        print(_("sftp-server (openssh) is not installed"), file=sys.stderr)
        return EXIT_FAIL
    loop = None
    if args.service:
        from gi.repository import GLib
        from .service import Notifier, gtk_available
        from .remote_ui import ServiceAsker
        try:
            notifier = Notifier()
        except GLib.Error:
            notifier = None
        asker = ServiceAsker(notifier, gtk_available())
        loop = GLib.MainLoop()
    else:
        asker = TerminalAsker()
    server = remote.FileServer(ctx.identity, ctx.settings, ctx.trust, shares, remote.Access(), asker,
                               bind=args.bind or "", port=args.port)
    try:
        server.start()
    except OSError as e:
        print(_("Cannot listen on port %d: %s") % (args.port or remote.FILES_PORT, e.strerror or e), file=sys.stderr)
        return EXIT_FAIL
    disc = None
    published = None
    if not args.no_mdns and not os.environ.get("LUXDROP_NO_MDNS"):
        try:
            from .discovery import Discovery
            disc = Discovery(service_type=remote.SERVICE_TYPE)
        except ImportError:
            disc = None
    names = ", ".join(f["name"] for f in shares.folders()) or "-"
    print(_("Sharing as \"%s\" (ID %s) on port %d: %s") % (ctx.settings.name, ctx.identity.id, server.port, names),
          flush=True)
    stop = threading.Event()

    def tick():
        nonlocal published
        ctx.settings.reload()
        server.check()
        if not server.shares.enabled:
            stop.set()
            if loop is not None:
                loop.quit()
            return False
        if disc is not None and published != ctx.settings.name:
            if disc.publish(ctx.settings.name, ctx.identity.id, server.port):
                published = ctx.settings.name
        return True

    tick()
    if loop is not None:
        from gi.repository import GLib
        GLib.timeout_add_seconds(3, tick)
        for sig in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda *_a: (loop.quit(), False)[1])
        loop.run()
    else:
        try:
            while not stop.wait(2):
                tick()
        except KeyboardInterrupt:
            pass
    server.stop()
    if disc is not None:
        disc.unpublish()
    return EXIT_OK


def cmd_share(args):
    if args.action == "serve":
        return serve(args)
    shares = remote.Shares()
    access = remote.Access()
    if args.action == "on":
        shares = set_sharing(True)
        print(_("Sharing is on: %s") % (", ".join(f["path"] for f in shares.folders()) or "-"))
        return EXIT_OK
    if args.action == "off":
        set_sharing(False)
        print(_("Sharing is off."))
        return EXIT_OK
    if args.action == "add":
        if not args.arg:
            return EXIT_USAGE
        try:
            real, home = remote.check_share_path(args.arg)
            if home and not args.yes:
                print(_("Share your whole home folder? Hidden files and folders (settings, keys, passwords) are "
                        "never shared."))
                if ask_line(_("Share the home folder? [y/N]: ")) not in ("y", "yes", "a", "ano"):
                    return EXIT_DECLINED
            shares.add(real, allow_home=True)
        except remote.ShareError:
            print("luxdrop: %s (%s)" % (_("Only folders in your home folder or on external drives can be shared, "
                                          "not hidden folders."), args.arg), file=sys.stderr)
            return EXIT_FAIL
        print(_("Shared: %s") % real)
        return EXIT_OK
    if args.action == "remove":
        n = shares.remove(args.arg or "")
        print(_("Removed %d folder(s)") % n)
        return EXIT_OK if n else EXIT_FAIL
    if args.action in ("forget", "allow-write", "read-only"):
        if not args.arg:
            return EXIT_USAGE
        if args.action == "forget":
            n = access.remove(args.arg)
        else:
            n = access.set_write(args.arg, args.action == "allow-write")
        print(_("Changed %d device(s)") % n)
        return EXIT_OK if n else EXIT_FAIL
    # status
    print(_("Sharing: %s") % (_("on") if shares.enabled else _("off")))
    for f in shares.folders():
        print("  %-20s %s" % (f["name"], f["path"]))
    if not shares.folders():
        print("  " + _("No shared folders."))
    print(_("Computers with access:"))
    if not access.peers:
        print("  " + _("None (every connection is asked first)."))
    for fp_hex, e in sorted(access.peers.items(), key=lambda kv: kv[1].get("name", "")):
        print("  %-28s %s  %s" % (e.get("name", "?"), e.get("id", fp_hex[:16]),
                                  _("can change files") if e.get("write") else _("read-only")))
    return EXIT_OK


# --- connect -------------------------------------------------------------------------

class CliConnect(remote.ConnectCallbacks):
    def status(self, state, info):
        if state == "connecting":
            print(_("Connecting to %s…") % transfer.fmt_addr(info["host"], info["port"]), file=sys.stderr)
        elif state == "waiting":
            print(_("Waiting for “%s” to allow access…") % info["peer_name"], file=sys.stderr)

    def confirm(self, info, replied):
        print(_("Verification code: %s") % proto.format_sas(info["sas"]), flush=True)
        a = ask_line(_("Does %s show the same code? [y]es and remember / [o]nly this time / [N]o: ")
                     % info["peer_name"], abort=lambda: replied.is_set() and not getattr(replied, "accepted", False))
        if a in ("y", "yes", "a", "ano"):
            return True, True
        if a in ("o", "once"):
            return True, False
        return False, False


def resolve(ctx, target, port_override=None, timeout=3.0):
    """Vrati (host, port, ocekavany otisk nebo None)."""
    target = target.strip()
    expected = None
    key, addr = target, None
    if "@" in target:
        key, addr = target.rsplit("@", 1)
    elif any(c in target for c in ".:") or target == "localhost":
        key, addr = None, target
    if key is not None:
        hits = ctx.trust.find(key)
        if len(hits) > 1:
            raise SystemExit(_("'%s' matches more trusted devices, use the ID") % key)
        if hits:
            expected = bytes.fromhex(hits[0][0])
        elif addr is not None:
            raise SystemExit(_("'%s' is not a trusted device (see 'luxdrop trust list')") % key)
    if addr is not None:
        host, port = transfer.parse_addr(addr, remote.FILES_PORT)
        return host, port_override or port, expected
    try:
        from gi.repository import GLib
        from .discovery import Discovery
        loop = GLib.MainLoop()
        d = Discovery(service_type=remote.SERVICE_TYPE)
        found = []
        if d.browse():
            GLib.timeout_add(int(timeout * 1000), loop.quit)
            loop.run()
            found = d.devices(ctx.identity.id)
        d.stop()
    except ImportError:
        found = []
    for dev in found:
        if (expected is not None and dev["id"] == proto.short_id(expected)) or \
                dev["name"].lower() == target.lower() or (len(target) >= 6 and dev["id"].startswith(target.lower())):
            if expected is None:
                for fp_hex, e in ctx.trust.peers.items():
                    if e.get("id") == dev["id"]:
                        expected = bytes.fromhex(fp_hex)
            return dev["host"], port_override or dev["port"], expected
    if expected is not None:
        last = (ctx.trust.get(expected) or {}).get("last_addr")
        if last:
            host, _p = transfer.parse_addr(last)
            return host, port_override or remote.FILES_PORT, expected
    raise SystemExit(_("Computer '%s' not found on the network. Use its address: luxdrop connect HOST") % target)


def cmd_connect(args):
    if not args.target:
        from .remote_ui import main
        return main(args.write)
    ctx = Ctx()
    host, port, expected = resolve(ctx, args.target, args.port)
    try:
        conn = remote.connect(ctx.identity, ctx.settings, ctx.trust, host, port, args.write, CliConnect(),
                              expected_fp=expected)
    except proto.ProtocolError as e:
        from_ui = {proto.E_DECLINED: EXIT_DECLINED, proto.E_SAS_REJECTED: EXIT_DECLINED, proto.E_KEY_MISMATCH: EXIT_KEY}
        print(_("Cannot connect: %s (%s)") % (e.message, e.code), file=sys.stderr)
        return from_ui.get(e.code, EXIT_FAIL)
    except OSError as e:
        print(_("Cannot connect: %s") % (e.strerror or e), file=sys.stderr)
        return EXIT_FAIL
    m = remote.Mount(conn)
    try:
        path = m.start()
    except (RuntimeError, OSError) as e:
        print("luxdrop: %s" % e, file=sys.stderr)
        return EXIT_FAIL
    print(_("Connected to %s (%s): %s") % (conn.peer_name, _("can change files") if conn.write else _("read-only"),
                                           path), flush=True)
    if not args.no_open:
        threading.Thread(target=remote.open_side_by_side, args=(path,), daemon=True).start()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_a: stop.set())
    try:
        m.wait(stop)
    finally:
        m.close()
    print(_("Disconnected from %s") % conn.peer_name, flush=True)
    return EXIT_OK


def cmd_disconnect(args):
    n = remote.disconnect(None if args.all or not args.name else args.name)
    deadline = time.monotonic() + 5
    while n and remote.connections() and time.monotonic() < deadline and (args.all or not args.name):
        time.sleep(0.2)
    print(_("Disconnected %d computer(s)") % n)
    return EXIT_OK if n else EXIT_FAIL


def cmd_connections(_args):
    items = remote.connections()
    if not items:
        print(_("Not connected to any computer."))
    for e in items:
        print("%-24s %-16s %-16s %s" % (e.get("peer", e["name"]), e.get("peer_id", ""),
                                        _("can change files") if e.get("write") else _("read-only"), e["path"]))
    return EXIT_OK


def add_parsers(sub):
    s = sub.add_parser("share", help=_("share folders with other LuxOS computers"))
    s.add_argument("action", nargs="?", default="status",
                   choices=("status", "on", "off", "add", "remove", "forget", "allow-write", "read-only", "serve"))
    s.add_argument("arg", nargs="?", help=_("folder (add/remove) or device ID/name (forget/allow-write/read-only)"))
    s.add_argument("--yes", action="store_true", help=_("do not ask before sharing the home folder"))
    s.add_argument("--port", type=int)
    s.add_argument("--bind", help=_("listen only on this address"))
    s.add_argument("--no-mdns", action="store_true", help=_("do not announce on the network"))
    s.add_argument("--service", action="store_true", help=argparse_suppress())
    c = sub.add_parser("connect", help=_("open the shared folders of another LuxOS computer in Files"))
    c.add_argument("target", nargs="?",
                   help=_("computer name, ID, HOST[:PORT] or NAME@HOST[:PORT]; without it a window opens"))
    c.add_argument("--write", action="store_true", help=_("ask for permission to change files"))
    c.add_argument("--port", type=int)
    c.add_argument("--no-open", action="store_true", help=_("do not open a Files window"))
    d = sub.add_parser("disconnect", help=_("disconnect from another computer"))
    d.add_argument("name", nargs="?")
    d.add_argument("--all", action="store_true")
    sub.add_parser("connections", help=_("list connected computers"))
    return {"share": cmd_share, "connect": cmd_connect, "disconnect": cmd_disconnect, "connections": cmd_connections}


def argparse_suppress():
    import argparse
    return argparse.SUPPRESS
