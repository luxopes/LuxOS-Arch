"""Filtry fail2ban pro postu LuxAI proti skutecnym radkum logu Dovecotu 2.4 (z mistniho behu
test_dovecot_oauth / dovecot_local) a radkum Postfixu ve formatu journalu na serveru:

    LUX_FAIL2BAN_ROOT=/rozbaleny/fail2ban python3 -m unittest test_fail2ban

(fail2ban z Archu rozbaleny bsdtar; jinak se pouzije fail2ban-regex ze systemu.)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILTERS = os.path.join(HERE, "..", "fail2ban")
P = "Nov  7 18:42:37 mail dovecot[941]: "
Q = "Nov  7 18:42:37 mail postfix/submissions/smtpd[2001]: "
R = "Nov  7 18:42:37 mail postfix/submission/smtpd[2002]: "

# skutecne radky Dovecotu 2.4.5 (mistni beh; ve journalu serveru bez "Info: ", jako zde)
DOVECOT_BAD = [
    P + "imap-login: Login aborted: Logged out (auth failed, 1 attempts in 4 secs) (auth_failed): user=<info@lux-ai.cz>, method=XOAUTH2, rip=203.0.113.7, lip=185.183.156.25, TLS, session=<V+DqQLNfKNh/AAAB>",
    P + "imap-login: Login aborted: Connection closed: read(size=935) failed: Connection reset by peer (auth failed, 1 attempts in 7 secs) (auth_failed): user=<info@lux-ai.cz>, method=OAUTHBEARER, rip=203.0.113.8, lip=185.183.156.25, TLS, session=<l8cvQbNfYN1/AAAB>",
    P + "imap-login: Info: Login aborted: Connection closed (auth failed, 1 attempts in 10 secs) (auth_failed): user=<info@lux-ai.cz>, method=PLAIN, rip=2001:db8::5, lip=2a03:4000:1d:b17:e4ed:d6ff:fe70:5233, TLS, session=<ZS2TQbNfaN1/AAAB>",
    # Dovecot 2.3 (pro jistotu po pripadnem navratu verze)
    P + "imap-login: Aborted login (auth failed, 3 attempts in 12 secs): user=<x@lux-ai.cz>, method=PLAIN, rip=203.0.113.9, lip=185.183.156.25, TLS, session=<abc>",
]
DOVECOT_OK = [
    P + "imap-login: Logged in: user=<info@lux-ai.cz>, method=OAUTHBEARER, rip=203.0.113.10, lip=185.183.156.25, mpid=1234, TLS, session=<x>",
    P + "imap-login: Login aborted: Connection closed (disconnected during TLS handshake) (tls_handshake_not_finished): user=<>, rip=203.0.113.11, lip=185.183.156.25, TLS handshaking: Connection closed, session=<y>",
    P + "auth(info@lux-ai.cz,203.0.113.12,sasl:xoauth2)<V+Dq>: oauth2 failed: Introspection failed: Provided token is not valid",
]
POSTFIX_BAD = [
    Q + "warning: unknown[203.0.113.20]: SASL XOAUTH2 authentication failed: eyJzdGF0dXMiOiI0MDEifQ==",
    R + "warning: client.example[203.0.113.21]: SASL PLAIN authentication failed: UGFzc3dvcmQ6",
    Q + "warning: unknown[2001:db8::22]: SASL OAUTHBEARER authentication failed: ",
]
POSTFIX_OK = [
    Q + "warning: unknown[203.0.113.30]: SASL XOAUTH2 authentication failed: Connection lost to authentication server",
    "Nov  7 18:42:37 mail postfix/smtpd[2003]: warning: unknown[203.0.113.31]: SASL PLAIN authentication failed: x",
    Q + "connect from unknown[203.0.113.32]",
]


def regex_tool():
    root = os.environ.get("LUX_FAIL2BAN_ROOT", "")
    if root:
        tool = os.path.join(root, "usr", "bin", "fail2ban-regex")
        site = [os.path.join(root, "usr", "lib", d, "site-packages") for d in os.listdir(os.path.join(root, "usr", "lib")) if d.startswith("python3")]
        return [sys.executable, tool], {"PYTHONPATH": ":".join(site)}
    if shutil.which("fail2ban-regex"):
        return ["fail2ban-regex"], {}
    return None, None


@unittest.skipUnless(regex_tool()[0], "needs fail2ban-regex (LUX_FAIL2BAN_ROOT or system)")
class Fail2banFilterTest(unittest.TestCase):
    def run_filter(self, name, lines):
        cmd, extra = regex_tool()
        tmp = tempfile.mkdtemp(prefix="lux-f2b-")
        try:
            # filtr potrebuje common.conf z fail2ban; zkopirovat filtr vedle nej
            root = os.environ.get("LUX_FAIL2BAN_ROOT", "")
            conf = os.path.join(root, "etc", "fail2ban") if root else "/etc/fail2ban"
            shutil.copytree(conf, os.path.join(tmp, "fail2ban"))
            shutil.copy(os.path.join(FILTERS, name + ".conf"), os.path.join(tmp, "fail2ban", "filter.d", name + ".conf"))
            log = os.path.join(tmp, "test.log")
            with open(log, "w") as f:
                f.write("\n".join(lines) + "\n")
            env = dict(os.environ)
            env.update(extra)
            out = subprocess.run(cmd + ["--config", os.path.join(tmp, "fail2ban"), "--print-all-matched", "-v", log,
                                        os.path.join(tmp, "fail2ban", "filter.d", name + ".conf")],
                                 capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr + out.stdout)
            return out.stdout
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def matched(self, text):
        for line in text.splitlines():
            if line.startswith("Lines:"):
                # "Lines: 7 lines, 0 ignored, 4 matched, 3 missed"
                parts = line.replace(",", "").split()
                return int(parts[parts.index("matched") - 1])
        raise AssertionError(text)

    def test_dovecot_filter(self):
        out = self.run_filter("luxai-dovecot", DOVECOT_BAD + DOVECOT_OK)
        self.assertEqual(self.matched(out), len(DOVECOT_BAD), out)
        for ip in ("203.0.113.7", "203.0.113.8", "2001:db8::5", "203.0.113.9"):
            self.assertIn(ip, out)
        for ip in ("203.0.113.10", "203.0.113.11", "203.0.113.12"):
            self.assertNotIn(ip + " ", out.split("|- Matched line(s):")[-1] if "Matched" in out else out)

    def test_postfix_filter(self):
        out = self.run_filter("luxai-postfix-sasl", POSTFIX_BAD + POSTFIX_OK)
        self.assertEqual(self.matched(out), len(POSTFIX_BAD), out)


if __name__ == "__main__":
    unittest.main()
