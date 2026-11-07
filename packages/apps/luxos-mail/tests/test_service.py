"""Sluzba luxos-mail-service proti testovacimu serveru IMAP s TLS (CA duveryhodna jen v testu):
pridani uctu, heslo jen v soukrome klicence, mezipamet, IDLE -> upozorneni, priznaky, Kos, QRESYNC,
STARTTLS, spatne heslo bez opakovani, neplatny certifikat bez odeslani hesla, znovupripojeni,
pocet neprectenych v Docku a akce Otevrit. Vse ve vlastni sbernici D-Bus a docasnem HOME.
"""
import glob
import json
import os
import socket
import subprocess
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mailtest as mt  # noqa: E402


def cache_dir(s, account):
    return os.path.join(s.env["XDG_DATA_HOME"], "luxos-mail", account)


def inbox_rows(s, account):
    for d in glob.glob(os.path.join(cache_dir(s, account), "m-*")):
        with open(os.path.join(d, "state.json")) as f:
            if json.load(f).get("raw") == "INBOX":
                with open(os.path.join(d, "index.tsv")) as g:
                    return [line.split("\t") for line in g.read().split("\n") if line]
    return []


class ServiceTest(unittest.TestCase):
    qresync = False

    def setUp(self):
        self.s = mt.Session()
        self.server = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES, qresync=self.qresync)
        self.c = self.s.start_service()

    def tearDown(self):
        try:
            self.c.call("quit")
        except OSError:
            pass
        self.server.stop()
        self.s.close()

    def add(self, **kw):
        req = mt.account_request(self.server, **kw)
        return self.c.call("add_account", **req)

    def auth_attempts(self):
        return [l for l in self.server.control("log")["log"] if " AUTHENTICATE " in l or " LOGIN " in l]

    def test_add_account_cache_and_keyring(self):
        r = self.add()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["state"], "online", self.s.service_log())
        acc = r["account"]
        self.assertEqual(self.s.secret_lookup(acc), mt.PASSWORD)
        with open(os.path.join(self.s.env["XDG_CONFIG_HOME"], "luxos-mail", "accounts.json")) as f:
            accounts = json.load(f)
        self.assertEqual(accounts[0]["imap"]["host"], "localhost")
        self.assertNotIn("password", json.dumps(accounts))
        # heslo nikde v souborech (konfigurace, mezipamet)
        for root, dirs, files in os.walk(self.s.home):
            for name in files:
                with open(os.path.join(root, name), "rb") as f:
                    self.assertNotIn(mt.PASSWORD.encode(), f.read(), name)
        # slozky a soubory Posty jen pro uzivatele
        for base in (os.path.join(self.s.env["XDG_CONFIG_HOME"], "luxos-mail"), cache_dir(self.s, acc)):
            for root, dirs, files in os.walk(base):
                self.assertEqual(os.stat(root).st_mode & 0o077, 0, root)
                for name in files:
                    self.assertEqual(os.stat(os.path.join(root, name)).st_mode & 0o077, 0, name)
        rows = inbox_rows(self.s, acc)
        self.assertEqual(len(rows), 9)
        subjects = {r[7] for r in rows}
        self.assertIn("Příliš žluťoučký kůň", subjects)
        self.assertIn("Зустріч у п'ятницю", subjects)
        att = [r for r in rows if r[7] == "Smlouva k podpisu"][0]
        self.assertEqual(att[10], "1")
        self.assertEqual(att[8], "V příloze posílám smlouvu.")
        # zadne upozorneni za zpravy, ktere uz ve schrance byly
        time.sleep(0.5)
        self.assertEqual(self.s.notifications(), [])
        # SPECIAL-USE ma prednost pred jmenem: "Odeslané" neni druha schranka Odeslane
        with open(os.path.join(cache_dir(self.s, acc), "mailboxes.tsv")) as f:
            roles = [line.split("\t")[3] for line in f.read().split("\n") if line]
        self.assertEqual(roles.count("sent"), 1)

    def test_idle_notification_flags_and_expunge(self):
        acc = self.add()["account"]
        self.assertTrue(mt.wait_for(lambda: self.server.control("sessions")["sessions"] >= 1, 5))
        time.sleep(0.3)
        t0 = time.time()
        self.server.control("deliver INBOX " + os.path.join(mt.FIXTURES, "de-alternative.eml"))
        self.assertTrue(mt.wait_for(lambda: len(self.s.notifications()) == 1, 5), self.s.service_log())
        self.assertLess(time.time() - t0, 5)
        n = self.s.notifications()[0]
        self.assertEqual(n["summary"], "Nová pošta od Jürgen Müller")
        self.assertTrue(n["body"].startswith("Grüße aus München"))
        self.assertEqual(n["actions"], ["default", "Otevřít"])
        self.assertEqual(n["icon"], "luxos-mail")
        # uz prectena zprava (z jineho klienta) upozorneni nedela
        self.server.control("deliver INBOX " + os.path.join(mt.FIXTURES, "flowed.eml") + " \\Seen")
        self.assertTrue(mt.wait_for(lambda: len(inbox_rows(self.s, acc)) == 11, 5))
        time.sleep(0.5)
        self.assertEqual(len(self.s.notifications()), 1)
        # priznak zmeneny jinde (webmail) se projevi pres IDLE
        self.server.control("flags INBOX 1 \\Seen \\Flagged")
        self.assertTrue(mt.wait_for(lambda: [r for r in inbox_rows(self.s, acc) if r[0] == "1"][0][1] in ("SF", "FS"), 5))
        # smazana jinde
        self.server.control("expunge INBOX 2")
        self.assertTrue(mt.wait_for(lambda: not [r for r in inbox_rows(self.s, acc) if r[0] == "2"], 5))
        # vic novych zprav najednou -> jedno souhrnne upozorneni
        for name in ("cs-iso88592-qp.eml", "uk-koi8u-base64.eml", "html-only.eml", "mixed-attachment.eml"):
            self.server.control("deliver INBOX " + os.path.join(mt.FIXTURES, name))
        self.assertTrue(mt.wait_for(lambda: len(self.s.notifications()) >= 2, 6))
        time.sleep(1.0)
        later = self.s.notifications()[1:]
        # 4 zpravy najednou (> 3): jedno souhrnne upozorneni
        self.assertEqual(len(later), 1, later)
        self.assertEqual(later[0]["summary"], "Nové zprávy: 4")

    def test_body_flags_trash(self):
        acc = self.add()["account"]
        r = self.c.call("body", account=acc, mailbox="INBOX", uid=6)
        self.assertTrue(r["ok"], r)
        with open(r["path"], "rb") as f, open(os.path.join(mt.FIXTURES, sorted(n for n in os.listdir(mt.FIXTURES) if n.endswith(".eml"))[5]), "rb") as g:
            self.assertEqual(f.read(), g.read())
        self.assertEqual(os.stat(r["path"]).st_mode & 0o777, 0o600)
        # BODY.PEEK: stazeni neoznaci zpravu jako prectenou
        self.assertNotIn("\\Seen", self.server.control("dump")["boxes"]["INBOX"][5]["flags"])
        r = self.c.call("flags", account=acc, mailbox="INBOX", uids=[2, 3], add=True, flags=["\\Seen"])
        self.assertTrue(r["ok"])
        boxes = self.server.control("dump")["boxes"]
        self.assertEqual([m["flags"] for m in boxes["INBOX"] if m["uid"] in (2, 3)], [["\\Seen"], ["\\Seen"]])
        self.assertEqual({r[0]: r[1] for r in inbox_rows(self.s, acc)}["2"], "S")
        r = self.c.call("flags", account=acc, mailbox="INBOX", uids=[2], add=False, flags=["\\Seen"])
        self.assertEqual({r[0]: r[1] for r in inbox_rows(self.s, acc)}["2"], "")
        r = self.c.call("trash", account=acc, mailbox="INBOX", uids=[4])
        self.assertEqual(r.get("deleted"), "moved")
        boxes = self.server.control("dump")["boxes"]
        self.assertNotIn(4, [m["uid"] for m in boxes["INBOX"]])
        self.assertEqual(len(boxes["Trash"]), 1)
        # v Kosi: smazat natrvalo
        r = self.c.call("sync", account=acc, mailbox="Trash")
        self.assertTrue(r["ok"], r)
        r = self.c.call("trash", account=acc, mailbox="Trash", uids=[1])
        self.assertEqual(r.get("deleted"), "deleted")
        self.assertEqual(self.server.control("dump")["boxes"]["Trash"], [])
        # obsah zustava v mezipameti i bez spojeni (offline)
        self.server.stop()
        r = self.c.call("body", account=acc, mailbox="INBOX", uid=7)
        self.assertFalse(r["ok"])
        self.assertIn(r["kind"], ("connect", "closed", "timeout"))
        self.assertTrue(os.path.exists(os.path.join(glob.glob(os.path.join(cache_dir(self.s, acc), "m-*", "bodies"))[0], "6.eml")))

    def test_wrong_password_is_not_retried(self):
        r = self.add(password="spatne")
        self.assertFalse(r["ok"])
        self.assertEqual(r["kind"], "auth")
        self.assertEqual(len(self.auth_attempts()), 1)
        self.assertFalse(os.path.exists(os.path.join(self.s.env["XDG_CONFIG_HOME"], "luxos-mail", "accounts.json")))
        # spravne heslo, pak heslo zmenene na serveru (webmail): jedno odmitnuti, dalsi akce okna server nezkousi
        acc = self.add()["account"]
        self.server.control("password jine-heslo")
        before = len(self.auth_attempts())
        self.c.call("reconnect")
        st = self.c.call("status")["accounts"][0]
        self.assertEqual((st["state"], st["kind"]), ("error", "auth"))
        for i in range(3):
            r = self.c.call("sync", account=acc, mailbox="INBOX")
            self.assertEqual(r["kind"], "auth")
        time.sleep(6)   # zadne opakovani po case (backoff se na spatne heslo nepouziva)
        self.assertEqual(len(self.auth_attempts()), before + 1)
        # nove heslo: overi se, ulozi do klicenky a ucet se pripoji
        r = self.c.call("set_password", account=acc, password="jine-heslo")
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.s.secret_lookup(acc), "jine-heslo")
        self.assertEqual(self.c.call("status")["accounts"][0]["state"], "online")

    def test_invalid_certificate_never_sends_password(self):
        bad = mt.FakeServer(self.s.root, self.s.certs, bad=True)
        try:
            req = mt.account_request(bad)
            r = self.c.call("add_account", **req)
            self.assertFalse(r["ok"])
            self.assertEqual(r["kind"], "cert")
            self.assertIn("certificate", r["error"])
            self.assertEqual([l for l in bad.control("log")["log"] if "LOGIN" in l or "AUTHENTICATE" in l], [])
        finally:
            bad.stop()

    def test_unencrypted_refused(self):
        req = mt.account_request(self.server)
        req["imap"]["security"] = "none"
        r = self.c.call("add_account", **req)
        self.assertFalse(r["ok"])
        self.assertEqual(r["kind"], "insecure")

    def test_starttls(self):
        r = self.add(security="starttls")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["state"], "online")
        log = self.server.control("log")["log"]
        self.assertIn("STARTTLS", " ".join(log))
        # prihlaseni az po STARTTLS
        self.assertLess([i for i, l in enumerate(log) if "STARTTLS" in l][0], [i for i, l in enumerate(log) if "AUTHENTICATE" in l][0])

    def test_reconnect_after_server_restart(self):
        acc = self.add()["account"]
        ports = self.server.ports
        self.c.events.clear()
        self.server.stop()
        self.assertTrue(self.c.wait_event(lambda e: e.get("event") == "status" and e.get("state") == "offline", 10), self.s.service_log())
        self.server = mt.FakeServer(self.s.root, self.s.certs, seed=mt.FIXTURES, ports=ports)
        self.c.events.clear()
        self.assertTrue(self.c.wait_event(lambda e: e.get("event") == "status" and e.get("state") == "online", 20), self.s.service_log())
        self.assertTrue(mt.wait_for(lambda: self.server.control("sessions")["sessions"] >= 1, 5))

    def test_badge_and_open_action(self):
        mon = subprocess.Popen(["dbus-monitor", "--session", "interface='com.canonical.Unity.LauncherEntry'"], env=self.s.env,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            # okno (zastupny socket) dostane pozadavek "open" z akce upozorneni
            ui = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            ui.bind("\0luxos-mail-ui-%d%s" % (os.getuid(), self.s.env["LUXOS_MAIL_INSTANCE"]))
            ui.listen(1)
            ui.settimeout(10)
            acc = self.add()["account"]
            self.server.control("deliver INBOX " + os.path.join(mt.FIXTURES, "cs-iso88592-qp.eml"))
            self.assertTrue(mt.wait_for(lambda: len(self.s.notifications()) == 1, 5))
            nid = self.s.notifications()[0]["id"]
            with open(self.s.notify_log + ".invoke", "w") as f:
                f.write(str(nid))
            conn, _ = ui.accept()
            data = conn.recv(4096).decode()
            req = json.loads(data.split("\n")[0])
            self.assertEqual(req["op"], "open")
            self.assertEqual(req["account"], acc)
            self.assertEqual(req["mailbox"], "INBOX")
            self.assertEqual(req["uid"], "10")
            conn.close()
            ui.close()
        finally:
            time.sleep(0.3)
            mon.terminate()
            out = mon.communicate(timeout=5)[0].decode()
        self.assertIn("application://luxos-mail.desktop", out)
        self.assertIn("count", out)


class QresyncServiceTest(ServiceTest):
    """Stejne testy se serverem s QRESYNC (VANISHED misto EXPUNGE, zmeny pri SELECT)."""
    qresync = True

    def test_qresync_enabled(self):
        self.add()
        log = self.server.control("log")["log"]
        self.assertIn("ENABLE QRESYNC", " ".join(log))


if __name__ == "__main__":
    unittest.main()
