#!/usr/bin/env python3
"""LuxOS - centrum oznameni (zvonek v liste): vychozi nastaveni xfce4-notifyd ukladaji oznameni.

    env -u DISPLAY xvfb-run -a python3 -m unittest packages/luxos-desktop/tests/test_notifyd_log.py -v

Spousti skutecny xfce4-notifyd na soukrome sbernici (dbus-run-session) s docasnym HOME a
systemovym nastavenim z files/xdg (XDG_CONFIG_DIRS) - xfconfd aktivovany sbernici tak nikdy
nesahne na skutecne nastaveni uzivatele. Jen pod xvfb-run. Bez xfce4-notifyd se preskoci.
"""
import glob
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
XDG = os.path.normpath(os.path.join(HERE, "..", "files", "xdg"))
NOTIFYD = os.environ.get("LUXOS_NOTIFYD") or next((p for p in ("/usr/lib/xfce4/notifyd/xfce4-notifyd",
                            "/usr/lib/x86_64-linux-gnu/xfce4/notifyd/xfce4-notifyd") if os.path.exists(p)), None)
# xfce4-notifyd s upravou LuxOS (packages/xfce4-notifyd) - pri testu proti neupravenemu z Archu jen puvodni chovani
PATCHED = bool(NOTIFYD) and b"x-luxos-keep" in open(NOTIFYD, "rb").read()
TOOLS = all(shutil.which(t) for t in ("dbus-run-session", "notify-send", "xfconf-query"))
UNDER_XVFB = "xvfb-run" in os.environ.get("XAUTHORITY", "")

# Odesilatele jako v LuxOS: hub (zmena casu, internet), Kalendar, Care/Ovladace (Notify pres D-Bus
# - stejne jako notify-send bez hintu transient), kriticke upozorneni na pamet; jas a hlasitost
# jsou docasna OSD (hint transient) a do seznamu nepatri.
SCRIPT = r'''
set -u
"$NOTIFYD" >"$HOME/notifyd.log" 2>&1 &
P=$!
for _ in $(seq 50); do
    gdbus call --session -d org.freedesktop.DBus -o /org/freedesktop/DBus -m org.freedesktop.DBus.NameHasOwner \
        org.freedesktop.Notifications 2>/dev/null | grep -q true && break
    sleep 0.1
done
notify-send -a LuxOS -h boolean:x-luxos-keep:true -i preferences-system-time "Tonight the clocks go back" "03:00 -> 02:00"
notify-send -a Calendar -h boolean:x-luxos-keep:true -i x-office-calendar "Dentist" "Today 10:00"
notify-send -a LuxOS -u critical -i dialog-warning "Memory is running low" "Firefox was closed"
notify-send -a LuxOS -u low "No internet connection" "body"
notify-send -a Volume -e -h int:value:40 "Volume" "40 %"
notify-send -a LuxOS -e -u low "Brightness" "50 %"
sleep 1
kill $P
wait $P 2>/dev/null
'''


@unittest.skipUnless(NOTIFYD and TOOLS and UNDER_XVFB, "chybi xfce4-notifyd / dbus-run-session, nebo neni pod xvfb-run")
class NotificationLog(unittest.TestCase):
    def run_notifyd(self, user_xml=None):
        home = tempfile.mkdtemp(prefix="luxos-notifyd-")
        cfg = os.path.join(home, ".config")
        if user_xml:
            d = os.path.join(cfg, "xfce4", "xfconf", "xfce-perchannel-xml")
            os.makedirs(d)
            with open(os.path.join(d, "xfce4-notifyd.xml"), "w") as f:
                f.write(user_xml)
        run = os.path.join(home, "run")
        os.makedirs(run, mode=0o700)
        env = {k: v for k, v in os.environ.items() if k not in ("DBUS_SESSION_BUS_ADDRESS",)}
        env.update({"HOME": home, "XDG_CONFIG_HOME": cfg, "XDG_CACHE_HOME": os.path.join(home, ".cache"),
                    "XDG_DATA_HOME": os.path.join(home, ".local", "share"), "XDG_RUNTIME_DIR": run,
                    "XDG_CONFIG_DIRS": XDG, "NOTIFYD": NOTIFYD, "NO_AT_BRIDGE": "1", "GIO_USE_VFS": "local"})
        subprocess.run(["dbus-run-session", "--", "sh", "-c", SCRIPT], env=env, capture_output=True, timeout=60)
        logs = glob.glob(os.path.join(home, ".cache", "xfce4", "notifyd", "log.sqlite"))
        if not logs:
            return []
        con = sqlite3.connect(logs[0])
        try:
            return [r[0] for r in con.execute("SELECT summary FROM notifications ORDER BY timestamp")]
        except sqlite3.Error:
            return []
        finally:
            con.close()

    def test_new_user_logs_important_notices(self):
        got = self.run_notifyd()
        if PATCHED:
            # LuxOS xfce4-notifyd: do historie jen oznameni s hintem x-luxos-keep (zmena casu, Kalendar)
            self.assertEqual(sorted(got), sorted(["Tonight the clocks go back", "Dentist"]))
        else:
            self.assertEqual(sorted(got), sorted(["Tonight the clocks go back", "Dentist", "Memory is running low",
                                                  "No internet connection"]))

    def test_existing_profile_gets_new_defaults(self):
        # profil z drivejsi verze: xfconf uz ma kanal (tema od luxos-appearance, znama aplikace),
        # ale zadne nastaveni zaznamu - vychozi hodnoty LuxOS plati po jednotlivych vlastnostech
        got = self.run_notifyd('<?xml version="1.0" encoding="UTF-8"?>\n<channel name="xfce4-notifyd" version="1.0">\n'
                               '  <property name="theme" type="string" value="WhiteSur-Dark"/>\n'
                               '  <property name="log-max-size-enabled" type="bool" value="true"/>\n'
                               '  <property name="applications" type="empty">\n'
                               '    <property name="known_applications" type="array">\n'
                               '      <value type="string" value="notify-send"/>\n    </property>\n  </property>\n</channel>\n')
        self.assertIn("Tonight the clocks go back", got)
        self.assertIn("Dentist", got)
        self.assertNotIn("Volume", got)
        self.assertNotIn("Brightness", got)

    def test_user_choice_is_kept(self):
        got = self.run_notifyd('<?xml version="1.0" encoding="UTF-8"?>\n<channel name="xfce4-notifyd" version="1.0">\n'
                               '  <property name="notification-log" type="bool" value="false"/>\n</channel>\n')
        self.assertEqual(got, [])


if __name__ == "__main__":
    unittest.main()
