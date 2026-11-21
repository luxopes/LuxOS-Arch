"""LuxOS - Firefox v testovacim displeji: docasny profil s vychozimi volbami LuxOS (files/firefox/luxos.js
jako user.js), dlouha stranka, ktera kazdou zmenu window.scrollY vypise pres dump() na stdout. Radky se
oznaci casem prijeti (monotonni ms), takze test vidi, jestli stranka jede i po posledni udalosti.
"""
import os
import re
import shutil
import subprocess
import threading
import time

PAGE = ("<!doctype html><html><head><title>scrolltest</title></head><body style='margin:0'>"
        + "".join(f"<p style='height:30px;margin:0'>Row {i}</p>" for i in range(1500))
        + "<script>addEventListener('scroll', () => dump('SCROLL ' + scrollY + '\\n'));"
          "addEventListener('load', () => setTimeout(() => dump('READY\\n'), 1500));</script></body></html>")

# malo procesu (jeden obsahovy, bez fission): testy bezi ve scope s TasksMax=300 a pocita se kazde vlakno
PREFS = """user_pref("browser.dom.window.dump.enabled", true);
user_pref("dom.ipc.processCount", 1);
user_pref("fission.autostart", false);
user_pref("dom.ipc.processPrelaunch.enabled", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("app.update.disabledForTesting", true);
user_pref("browser.tabs.warnOnClose", false);
user_pref("sidebar.revamp", false);
user_pref("browser.toolbars.bookmarks.visibility", "never");
"""


def firefox():
    return shutil.which("firefox")


class Firefox:
    def __init__(self, home, env, luxos_js):
        self.lines = []
        profile = os.path.join(home, "ffprofile")
        os.makedirs(profile, exist_ok=True)
        with open(luxos_js) as f:
            luxos = re.sub(r"^pref\(", "user_pref(", f.read(), flags=re.M)
        with open(os.path.join(profile, "user.js"), "w") as f:
            f.write(luxos + PREFS)
        page = os.path.join(home, "page.html")
        with open(page, "w") as f:
            f.write(PAGE)
        self.ready = threading.Event()
        self.proc = subprocess.Popen(
            [firefox(), "--no-remote", "--profile", profile, "--new-instance", "--width", "800", "--height", "700",
             "file://" + page], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        for line in self.proc.stdout:
            t = time.monotonic() * 1000
            if line.startswith("READY"):
                self.ready.set()
            elif line.startswith("SCROLL "):
                try:
                    self.lines.append((t, float(line.split()[1])))
                except ValueError:
                    pass

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc.stdout.close()
