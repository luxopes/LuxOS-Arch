"""remote-apply.sh / remote-rollback.sh nanecisto: docasny ROOT s kopiemi konfigurace jako na serveru
a nahrazenymi prikazy (systemctl, nft, postconf, doveconf, curl, ss ...), ktere jen zapisuji, co by
se volalo. Overuje zalohu, idempotenci (druhe nasazeni nic nezdvoji), ze se tajemstvi nevypise ani
neobjevi v argumentech prikazu, --no-submission a ze navrat obnovi puvodni soubory bajt po bajtu.

    python3 -m unittest test_deploy_scripts        (LUX_ACCOUNT_SERVER_JS = skutecna kopie server.js, jinak kotvy)
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(BASE, "account-server"))
import mail_oauth_patch as patch  # noqa: E402

LOCAL_CONF = """# LuxAI virtual mailboxes. IMAP is deliberately loopback-only
listen = 127.0.0.1, ::1
auth_allow_cleartext = yes
auth_mechanisms = plain login
service imap-login {
  inet_listener imap {
    port = 143
  }
  inet_listener imaps {
    port = 0
  }
}
"""
NFT = """table inet lux_filter {
\tchain input {
\t\ttype filter hook input priority filter; policy drop;
\t\tiifname "lo" accept
\t\ttcp dport { 22, 25, 80, 443, 8085 } ct state new accept
\t\tudp dport { 443, 51820 } accept
\t}
}
"""
SYNC = """#!/bin/sh
set -eu
postfix check
systemctl reload postfix
"""
MASTER = "smtp      inet  n       -       y       -       -       smtpd\npickup    unix  n       -       y       60      1       pickup\n"
MAILBOXES = {"imap": {"host": "mail.lux-ai.cz", "port": 993, "security": "ssl"},
             "smtp": {"host": "mail.lux-ai.cz", "port": 465, "security": "ssl"},
             "mailboxes": [{"address": "info@lux-ai.cz", "display_name": "LuxAI", "emails": ["owner@personal.example"],
                            "users": [], "require_group": "luxai-admin"}]}

STUB = r'''#!/usr/bin/env python3
import json, os, re, subprocess, sys
name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
state_dir = os.environ["STUB_STATE"]
stdin = ""
if name in ("curl",) and "-K" in args:
    stdin = sys.stdin.read()
with open(os.path.join(state_dir, "calls.log"), "a") as f:
    f.write(json.dumps([name] + args) + "\n")
def flag(n):
    return os.path.exists(os.path.join(state_dir, n))
def setflag(n):
    open(os.path.join(state_dir, n), "w").close()
root = os.environ["ROOT"]
if name == "dovecot":
    print("2.4.1-4 (7d8c0e5759)")
elif name == "systemctl":
    if args[:2] == ["restart", "dovecot"]:
        setflag("dovecot")
    if args[:2] == ["reload", "postfix"]:
        setflag("postfix")
elif name == "ss":
    q = " ".join(args)
    port = q.split(":")[-1].strip()
    if port == "143":
        print("LISTEN 0 100 127.0.0.1:143 0.0.0.0:*")
    elif port == "993" and flag("dovecot"):
        print("LISTEN 0 100 0.0.0.0:993 0.0.0.0:*")
    elif port in ("465", "587") and flag("postfix") and "submission" in open(os.path.join(root, "etc/postfix/master.cf")).read():
        print("LISTEN 0 100 0.0.0.0:%s 0.0.0.0:*" % port)
elif name == "curl":
    url = args[-1]
    if url.endswith("/health"):
        print('{"ok":1}')
    elif url.endswith("/oauth/introspect"):
        ok = re.fullmatch(r'user = "lux-dovecot:[0-9a-f]{64}"\n', stdin) is not None
        print('{"active":false}' if ok else '{"error":"bad stub input"}', end="")
    elif "/api/mail/mailboxes" in url:
        print("401" if any("X-Lux-Client" in a for a in args) else "403", end="")
elif name == "openssl":
    if args and args[0] == "rand":
        os.execv("/usr/bin/openssl", ["openssl"] + args)
    sys.stdin.read()
    print("* OK [CAPABILITY IMAP4rev1 SASL-IR AUTH=PLAIN AUTH=LOGIN AUTH=XOAUTH2 AUTH=OAUTHBEARER] Dovecot ready.")
elif name == "doveconf":
    if "-h" in args:
        print("plain login xoauth2 oauthbearer")
elif name == "postconf":
    mc = os.path.join(root, "etc/postfix/master.cf")
    text = open(mc).read()
    if args and args[0] == "-M":
        svc = args[1].split("=", 1)[1]
        if svc.split()[0] not in text:
            text += svc + "\n"
    elif args and args[0] == "-P":
        for a in args[1:]:
            text += "  -o " + a.split("/", 2)[2] + "\n"
    elif args and args[0] == "-MX":
        pass
    open(mc, "w").write(text)
elif name == "postmap":
    open(args[0] + ".db", "w").write("db")
elif name == "nft":
    rules = os.path.join(state_dir, "nft.json")
    data = json.load(open(rules)) if os.path.exists(rules) else []
    if args[:2] == ["-c", "-f"]:
        pass
    elif args[:4] == ["-a", "list", "chain", "inet"]:
        for h, r in data:
            print("\t\t%s # handle %d" % (r, h))
    elif args[:2] == ["add", "rule"]:
        data.append([len(data) + 100, " ".join(args[5:])])
    elif args[:2] == ["delete", "rule"]:
        data = [x for x in data if str(x[0]) != args[-1]]
    json.dump(data, open(rules, "w"))
elif name in ("fail2ban-client", "node", "postfix", "chgrp"):
    pass
'''


def tree_snapshot(root):
    out = {}
    for d, dirs, files in os.walk(root):
        for n in files:
            p = os.path.join(d, n)
            rel = os.path.relpath(p, root)
            if rel.startswith("root/"):
                continue    # zalohy nasazeni
            with open(p, "rb") as f:
                out[rel] = f.read()
    return out


class DeployScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lux-deploy-test-")
        self.root = os.path.join(self.tmp, "root")
        self.state = os.path.join(self.tmp, "state")
        self.bin = os.path.join(self.tmp, "bin")
        for d in ("opt/lux-account", "etc/dovecot", "etc/nftables.d", "usr/local/sbin", "etc/postfix",
                  "etc/fail2ban/filter.d", "etc/fail2ban/jail.d", "etc/lux-mail/tls", "etc/systemd/system", "root"):
            os.makedirs(os.path.join(self.root, d))
        os.makedirs(self.state)
        os.makedirs(self.bin)
        src = os.environ.get("LUX_ACCOUNT_SERVER_JS", "")
        if src and os.path.isfile(src):
            shutil.copy(src, os.path.join(self.root, "opt/lux-account/server.js"))
        else:
            with open(os.path.join(self.root, "opt/lux-account/server.js"), "w") as f:
                f.write("// kotvy server.js\n" + "".join(anchor for _, anchor, _ in patch.STEPS))
        files = {"etc/dovecot/local.conf": LOCAL_CONF, "etc/nftables.d/lux-filter.nft": NFT,
                 "etc/nftables.conf": 'flush ruleset\ninclude "/etc/nftables.d/*.nft"\n',
                 "usr/local/sbin/lux-mail-sync-cert": SYNC, "etc/postfix/master.cf": MASTER,
                 "etc/postfix/main.cf": "myhostname = mail.lux-ai.cz\n", "etc/lux-mail/tls/fullchain.pem": "CERT\n",
                 "etc/lux-account-mailboxes.json": json.dumps(MAILBOXES)}
        for rel, text in files.items():
            with open(os.path.join(self.root, rel), "w") as f:
                f.write(text)
        stub = os.path.join(self.bin, "stub")
        with open(stub, "w") as f:
            f.write(STUB)
        os.chmod(stub, 0o755)
        for name in ("dovecot", "systemctl", "ss", "curl", "openssl", "doveconf", "postconf", "postmap", "postfix",
                     "fail2ban-client", "nft", "node", "chgrp"):
            os.symlink(stub, os.path.join(self.bin, name))
        self.original = tree_snapshot(self.root)
        assert len(self.original) == 9, self.original.keys()
        self.env = dict(os.environ, ROOT=self.root, STUB_STATE=self.state, PATH=self.bin + ":" + os.environ.get("PATH", "/usr/bin"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_script(self, name, *args):
        r = subprocess.run(["bash", os.path.join(BASE, name)] + list(args), env=self.env, capture_output=True, text=True, timeout=120)
        return r

    def read(self, rel):
        with open(os.path.join(self.root, rel)) as f:
            return f.read()

    def calls(self):
        with open(os.path.join(self.state, "calls.log")) as f:
            return [json.loads(l) for l in f]

    def secret(self):
        return re.search(r"^MAIL_INTROSPECTION_SECRET=([0-9a-f]{64})$", self.read("etc/lux-account-mail-oauth.env"), re.M).group(1)

    def test_apply_idempotent_and_rollback(self):
        r = self.run_script("remote-apply.sh", "20261107180000")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        secret = self.secret()
        # tajemstvi: jen v souborech 0600, nikdy ve vystupu ani v argumentech prikazu
        self.assertNotIn(secret, r.stdout + r.stderr)
        self.assertNotIn(secret, json.dumps(self.calls()))
        for rel in ("etc/lux-account-mail-oauth.env", "etc/dovecot/luxai-oauth2-secret.conf"):
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.root, rel)).st_mode), 0o600, rel)
        self.assertIn("http://lux-dovecot:%s@127.0.0.1:3020/oauth/introspect" % secret, self.read("etc/dovecot/luxai-oauth2-secret.conf"))
        self.assertIn("mail_oauth_patch", "".join(open(os.path.join(BASE, "remote-apply.sh")).read()))
        self.assertIn(patch.MARK, self.read("opt/lux-account/server.js"))
        self.assertIn("EnvironmentFile=/etc/lux-account-mail-oauth.env", self.read("etc/systemd/system/lux-account.service.d/mail-oauth.conf"))
        local = self.read("etc/dovecot/local.conf")
        self.assertEqual(local.count("!include_try luxai-oauth2.conf"), 1)
        self.assertTrue(local.startswith(LOCAL_CONF))
        self.assertEqual(self.read("etc/dovecot/luxai-oauth2.conf"), open(os.path.join(BASE, "dovecot", "luxai-oauth2.conf")).read())
        nft = self.read("etc/nftables.d/lux-filter.nft")
        self.assertIn('\t\ttcp dport { 465, 587, 993 } ct state new accept comment "luxai-mail-oauth"\n', nft)
        self.assertEqual(self.read("usr/local/sbin/lux-mail-sync-cert").count("systemctl reload dovecot"), 1)
        master = self.read("etc/postfix/master.cf")
        self.assertIn("submissions inet n - y - - smtpd", master)
        self.assertIn("smtpd_sasl_path=private/auth", master)
        self.assertIn("smtpd_tls_wrappermode=yes", master)
        self.assertEqual(self.read("etc/postfix/luxai_sender_login"), "info@lux-ai.cz info@lux-ai.cz\n")
        self.assertIn("enabled = true", self.read("etc/fail2ban/jail.d/luxai-mail.local"))
        live = [c for c in self.calls() if c[:3] == ["nft", "add", "rule"]]
        self.assertEqual(len(live), 1)
        self.assertIn("{ 465, 587, 993 }", " ".join(live[0]))
        # firewall az po sluzbach a fail2ban
        names = [" ".join(c[:3]) for c in self.calls()]
        self.assertLess(names.index("fail2ban-client reload"), names.index("nft add rule"))
        self.assertLess(names.index("systemctl restart dovecot"), names.index("nft add rule"))

        # druhe nasazeni: nic se nezdvoji, tajemstvi zustava
        r2 = self.run_script("remote-apply.sh", "20261107190000")
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertIn("already patched", r2.stdout)
        self.assertEqual(self.secret(), secret)
        self.assertEqual(self.read("etc/dovecot/local.conf").count("!include_try luxai-oauth2.conf"), 1)
        self.assertEqual(self.read("etc/nftables.d/lux-filter.nft").count("luxai-mail-oauth"), 1)
        self.assertEqual(self.read("usr/local/sbin/lux-mail-sync-cert").count("systemctl reload dovecot"), 1)
        self.assertEqual(self.read("etc/postfix/master.cf").count("submissions inet"), 1)
        self.assertEqual(len([c for c in self.calls() if c[:3] == ["nft", "add", "rule"]]), 1)

        # navrat na stav pred prvnim nasazenim
        rb = self.run_script("remote-rollback.sh", "20261107180000")
        self.assertEqual(rb.returncode, 0, rb.stdout + rb.stderr)
        after = tree_snapshot(self.root)
        # env s tajemstvim zustava (bez drop-inu se nepouzije), --purge ho smaze
        after.pop("etc/lux-account-mail-oauth.env")
        self.assertEqual(sorted(after), sorted(self.original))
        for rel, data in self.original.items():
            self.assertEqual(after[rel], data, rel)
        self.assertEqual(json.load(open(os.path.join(self.state, "nft.json"))), [])
        rb2 = self.run_script("remote-rollback.sh", "20261107180000", "--purge")
        self.assertEqual(rb2.returncode, 0, rb2.stdout + rb2.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.root, "etc/lux-account-mail-oauth.env")))

    def test_no_submission(self):
        r = self.run_script("remote-apply.sh", "20261107180000", "--no-submission")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read("etc/postfix/master.cf"), MASTER)
        self.assertFalse(os.path.exists(os.path.join(self.root, "etc/postfix/luxai_sender_login")))
        jail = self.read("etc/fail2ban/jail.d/luxai-mail.local")
        self.assertIn("[luxai-postfix-sasl]\nenabled = false", jail)
        self.assertIn("[luxai-dovecot]\nenabled = true", jail)
        self.assertIn("tcp dport { 993 } ct state new accept", self.read("etc/nftables.d/lux-filter.nft"))

    def test_stops_on_bad_anchor(self):
        with open(os.path.join(self.root, "etc/nftables.d/lux-filter.nft"), "w") as f:
            f.write("table inet lux_filter {\n}\n")
        r = self.run_script("remote-apply.sh", "20261107180000")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("firewall anchor not found", r.stderr)
        self.assertEqual([c for c in self.calls() if c[:3] == ["nft", "add", "rule"]], [])

    def test_refuses_dovecot_23(self):
        with open(os.path.join(self.bin, "dovecot"), "w") as f:
            f.write("#!/bin/sh\necho 2.3.21\n")
        os.chmod(os.path.join(self.bin, "dovecot"), 0o755)
        r = self.run_script("remote-apply.sh", "20261107180000")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Dovecot 2.4 required", r.stderr)
        self.assertEqual(tree_snapshot(self.root), self.original)


if __name__ == "__main__":
    unittest.main()
