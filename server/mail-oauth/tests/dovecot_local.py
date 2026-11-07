"""Skutecny Dovecot 2.4 bez roota v docasne slozce pro testy (nikdy skutecny server).

Dovecot se nemusi instalovat: LUX_DOVECOT_ROOT ukazuje na rozbaleny balik (napr. dovecot-2.4.x z Archu
rozbaleny bsdtar do slozky, plus mariadb-libs a postgresql-libs kvuli knihovnam auth), jinak se pouzije
/usr. Rozbaleny balik se pripoji pres bubblewrap jako overlay na /usr/lib a /usr/bin (Dovecot ma cesty
k modulum a doveconf pevne prelozene), bez roota a jen pro procesy testu. Konfigurace napodobuje server: passwd-file + userdb static jako /etc/dovecot/conf.d, a pak
DOSLOVA vlozeny server/mail-oauth/dovecot/luxai-oauth2.conf (jen introspection_url miri na testovaci
server uctu). Verejne naslouchani (luxai-public.conf) nahrazuji testovaci porty na 127.0.0.1.
"""
import grp
import os
import pwd
import shutil
import socket
import subprocess
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SNIPPET = os.path.join(HERE, "..", "dovecot", "luxai-oauth2.conf")
def prefix():
    return os.environ.get("LUX_DOVECOT_ROOT", "") or "/"


def available():
    return os.path.isfile(os.path.join(prefix(), "usr", "bin", "dovecot"))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class LocalDovecot:
    def __init__(self, introspection_url, secret, certs, users, allow_nets="127.0.0.0/8 ::1/128"):
        self.root = tempfile.mkdtemp(prefix="lux-dovecot-test-")
        self.prefix = prefix()
        self.env = dict(os.environ)
        libs = ["/usr/lib/dovecot"]
        self.env["LD_LIBRARY_PATH"] = ":".join(libs)
        self.wrap = []
        if self.prefix != "/":
            self.wrap = ["bwrap", "--dev-bind", "/", "/", "--unshare-pid", "--die-with-parent"]
            for d in ("lib", "bin"):
                self.wrap += ["--overlay-src", "/usr/" + d, "--overlay-src", os.path.join(self.prefix, "usr", d), "--tmp-overlay", "/usr/" + d]
            self.wrap.append("--")
        self.ports = {"imap": free_port(), "imaps": free_port()}
        user = pwd.getpwuid(os.getuid()).pw_name
        group = grp.getgrgid(os.getgid()).gr_name
        with open(os.path.join(self.root, "users"), "w") as f:
            for name, password in users.items():
                f.write("%s:{PLAIN}%s\n" % (name, password))
        # doslova serverovy soubor (adresu introspekce s tajemstvim prepisuje secret soubor jako na serveru)
        with open(SNIPPET) as f:
            snippet = f.read()
        if allow_nets != "127.0.0.0/8 ::1/128":
            snippet = snippet.replace("allow_nets = 127.0.0.0/8 ::1/128", "allow_nets = " + allow_nets)
        with open(os.path.join(self.root, "luxai-oauth2.conf"), "w") as f:
            f.write(snippet)
        with open(os.path.join(self.root, "luxai-oauth2-secret.conf"), "w") as f:
            f.write("oauth2 {\n  introspection_url = %s\n}\n" % introspection_url.replace("http://", "http://lux-dovecot:%s@" % secret, 1))
        os.chmod(os.path.join(self.root, "luxai-oauth2-secret.conf"), 0o600)
        conf = """dovecot_config_version = 2.4.0
dovecot_storage_version = 2.4.0
base_dir = {root}/run
state_dir = {root}/state
log_path = {root}/dovecot.log
info_log_path = {root}/dovecot.log
debug_log_path = {root}/dovecot.log
default_internal_user = {user}
default_internal_group = {group}
default_login_user = {user}
import_environment {{
  LD_LIBRARY_PATH = {libs}
}}
protocols = imap
service anvil {{
  chroot =
}}
listen = 127.0.0.1
ssl = yes
ssl_server_cert_file = {cert}
ssl_server_key_file = {key}
ssl_min_protocol = TLSv1.2
auth_allow_cleartext = yes
auth_verbose = yes
mail_driver = maildir
mail_home = {root}/vmail/%{{user | domain}}/%{{user | username}}
mail_path = ~/Maildir
mail_inbox_path = ~/Maildir
mail_uid = {user}
mail_gid = {group}
first_valid_uid = {uid}
last_valid_uid = {uid}
first_valid_gid = {gid}
last_valid_gid = {gid}
# bez roota nejde chroot (na serveru zustava vychozi)
service imap-login {{
  chroot =
  inet_listener imap {{
    port = {imap}
  }}
  inet_listener imaps {{
    port = {imaps}
    ssl = yes
  }}
}}
# schranky jako v /etc/dovecot/local.conf na serveru
namespace inbox {{
  inbox = yes
  mailbox Drafts {{
    auto = subscribe
    special_use = \\Drafts
  }}
  mailbox Junk {{
    auto = subscribe
    special_use = \\Junk
  }}
  mailbox Sent {{
    auto = subscribe
    special_use = \\Sent
  }}
  mailbox Trash {{
    auto = subscribe
    special_use = \\Trash
  }}
}}
# jako /etc/dovecot/conf.d/auth-passwdfile.conf.ext na serveru
passdb passwd-file {{
  default_password_scheme = PLAIN
  auth_username_format = %{{user | lower}}
  passwd_file_path = {root}/users
}}
userdb static {{
  allow_all_users = yes
  fields {{
    uid = {user}
    gid = {group}
    home = {root}/vmail/%{{user | domain}}/%{{user | username}}
  }}
}}
!include luxai-oauth2.conf
""".format(root=self.root, user=user, group=group, uid=os.getuid(), gid=os.getgid(), libs=":".join(libs),
           cert=certs["cert"], key=certs["key"], imap=self.ports["imap"], imaps=self.ports["imaps"])
        self.conf = os.path.join(self.root, "dovecot.conf")
        with open(self.conf, "w") as f:
            f.write(conf)
        self.proc = None

    def doveconf(self, *args):
        return subprocess.run(self.wrap + ["/usr/bin/doveconf", "-c", self.conf] + list(args), env=self.env, capture_output=True, text=True, timeout=30)

    def start(self):
        out = self.doveconf("-n")
        if out.returncode != 0:
            raise RuntimeError("doveconf failed: " + out.stderr)
        self.proc = subprocess.Popen(self.wrap + ["/usr/bin/dovecot", "-F", "-c", self.conf], env=self.env,
                                     stdout=subprocess.DEVNULL, stderr=open(os.path.join(self.root, "master.err"), "ab"))
        end = time.time() + 15
        while time.time() < end:
            if self.proc.poll() is not None:
                raise RuntimeError("dovecot exited: " + self.log())
            try:
                socket.create_connection(("127.0.0.1", self.ports["imaps"]), 0.5).close()
                return self
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("dovecot did not listen: " + self.log())

    def log(self):
        text = ""
        for name in ("master.err", "dovecot.log"):
            try:
                with open(os.path.join(self.root, name), errors="replace") as f:
                    text += f.read()
            except OSError:
                pass
        return text

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)

    def close(self):
        self.stop()
        shutil.rmtree(self.root, ignore_errors=True)
