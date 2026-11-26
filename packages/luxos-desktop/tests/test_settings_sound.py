#!/usr/bin/env python3
"""LuxOS - Nastaveni > Zvuk (luxos_page_sound, drive pavucontrol): zarizeni, hlasitost, ztlumeni, aplikace a
sledovani serveru. Falesny `pactl` (Python) drzi stav v souboru, zapisuje volani a umi `subscribe` (udalosti z
dalsiho souboru), takze se overuje i to, ze zmena zvenku (klavesa hlasitosti) se promitne do stranky a NEZAPISE
se zpet.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      python3 -m unittest packages/luxos-desktop/tests/test_settings_sound.py -v
"""
# LuxOS: testy GUI nikdy na skutecne obrazovce a v relaci uzivatele (scripts/luxos_testguard.py)
import os as _tg_os, sys as _tg_sys  # noqa: E401
_tg_d = _tg_os.path.dirname(_tg_os.path.abspath(__file__))
while _tg_d != "/" and not _tg_os.path.exists(_tg_os.path.join(_tg_d, "scripts", "luxos_testguard.py")):
    _tg_d = _tg_os.path.dirname(_tg_d)
if _tg_d != "/":
    _tg_sys.path.insert(0, _tg_os.path.join(_tg_d, "scripts"))
    import luxos_testguard  # noqa: E402,F401
else:
    _tg_os.environ.pop("DISPLAY", None)
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lsl_app_harness as h  # noqa: E402

FAKE_PACTL = r'''#!/usr/bin/env python3
import json, os, sys, time
state_path = os.environ["FAKE_PACTL_STATE"]
log = os.environ["FAKE_PACTL_LOG"]
a = [x for x in sys.argv[1:] if x not in ("-f", "json")]
as_json = "-f" in sys.argv
with open(log, "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\n")
if a[:1] == ["subscribe"]:
    events = state_path + ".events"
    open(events, "a").close()
    pos = os.path.getsize(events)
    while True:
        size = os.path.getsize(events)
        if size > pos:
            with open(events) as f:
                f.seek(pos)
                data = f.read()
            pos = size
            sys.stdout.write(data)
            sys.stdout.flush()
        time.sleep(0.05)
st = json.load(open(state_path))

def save():
    json.dump(st, open(state_path, "w"))

def vol(percent):
    v = int(percent * 65536 / 100)
    return {"front-left": {"value": v, "value_percent": "%d%%" % percent},
            "front-right": {"value": v, "value_percent": "%d%%" % percent}}

def dev(d):
    return {"name": d["name"], "description": d["desc"], "mute": d["mute"], "volume": vol(d["vol"]), "state": "RUNNING"}

def find(kind, name):
    key = "default_" + kind
    name = st[key] if name.startswith("@DEFAULT") else name
    return next(d for d in st[kind + "s"] if d["name"] == name)

if a == ["info"]:
    print(json.dumps({"default_sink_name": st["default_sink"], "default_source_name": st["default_source"]}))
elif a == ["list", "sinks"]:
    print(json.dumps([dev(d) for d in st["sinks"]]))
elif a == ["list", "sources"]:
    print(json.dumps([dev(d) for d in st["sources"]]))
elif a == ["list", "sink-inputs"]:
    print(json.dumps([{"index": s["id"], "mute": False, "volume": vol(s["vol"]),
                       "properties": {"application.name": s["name"]}} for s in st["streams"]]))
elif a == ["list", "short", "sink-inputs"]:
    for s in st["streams"]:
        print("%d\t1\t2\tprotocol-native\ts32le 2ch 48000Hz" % s["id"])
elif a == ["list", "short", "source-outputs"]:
    pass
elif a[0] in ("set-sink-volume", "set-source-volume"):
    find(a[0].split("-")[1], a[1])["vol"] = int(a[2].rstrip("%"))
    save()
elif a[0] in ("set-sink-mute", "set-source-mute"):
    find(a[0].split("-")[1], a[1])["mute"] = a[2] == "1"
    save()
elif a[0] in ("set-default-sink", "set-default-source"):
    st["default_" + a[0].split("-")[2]] = a[1]
    save()
elif a[0] == "set-sink-input-volume":
    next(s for s in st["streams"] if str(s["id"]) == a[1])["vol"] = int(a[2].rstrip("%"))
    save()
'''

STATE = {
    "default_sink": "alsa_output.speakers", "default_source": "alsa_input.mic",
    "sinks": [{"name": "alsa_output.speakers", "desc": "Built-in Speakers", "vol": 30, "mute": False},
              {"name": "bluez_output.headset", "desc": "Bluetooth Headset", "vol": 60, "mute": False}],
    "sources": [{"name": "alsa_input.mic", "desc": "Built-in Microphone", "vol": 80, "mute": True},
                {"name": "alsa_output.speakers.monitor", "desc": "Monitor of Built-in Speakers", "vol": 100, "mute": False}],
    "streams": [{"id": 41, "name": "Firefox", "vol": 55}],
}


def setUpModule():
    if not h.lslc_ok():
        raise unittest.SkipTest("lslc 0.11 is not installed")
    h.build("luxos-settings")


def make_env(state=None):
    tmp = Path(tempfile.mkdtemp(prefix="settings-sound-", dir=h.private_dir()))
    env = h.base_env(tmp)
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    (bin_dir / "pactl").write_text(FAKE_PACTL)
    (bin_dir / "pactl").chmod(0o755)
    (tmp / "pactl.json").write_text(json.dumps(state or STATE))
    env.update(PATH=f"{bin_dir}:{os.environ['PATH']}", FAKE_PACTL_STATE=str(tmp / "pactl.json"),
               FAKE_PACTL_LOG=str(tmp / "pactl.log"))
    return tmp, env


def writes(tmp):
    log = tmp / "pactl.log"
    lines = log.read_text().splitlines() if log.exists() else []
    return [line for line in lines if line.split(" ")[0].startswith(("set-", "move-"))]


def find(dump, kind, text):
    for i, line in enumerate(dump):
        if line == f"GtkLabel\t{text}":
            for nxt in dump[i + 1:i + 4]:
                if nxt.startswith(kind + "\t"):
                    return nxt.split("\t")[1:]
    return None


@unittest.skipUnless(h.HAVE_X11, "Xvfb, xdotool or dbus-run-session missing")
class Sound(unittest.TestCase):
    def run_app(self, script, tmp, env):
        app = h.X11App([str(h.build("luxos-settings")), "sound"], env, script, tmp=tmp)
        self.addCleanup(app.close)
        return app

    def test_page_shows_server_state(self):
        tmp, env = make_env()
        d = self.run_app(["wait 500", "dump", "quit"], tmp, env).wait_dump()
        for title in ("Output", "Input", "Applications"):
            self.assertIn("GtkLabel\t" + title, d)
        self.assertEqual(find(d, "GtkComboBoxText", "Output device"), ["alsa_output.speakers"])
        self.assertEqual(find(d, "GtkComboBoxText", "Input device"), ["alsa_input.mic"])
        self.assertEqual(find(d, "GtkScale", "Output volume"), ["30"])
        self.assertEqual(find(d, "GtkScale", "Input volume"), ["80"])
        self.assertEqual(find(d, "GtkSwitch", "Mute"), ["off"])
        self.assertEqual(find(d, "GtkSwitch", "Mute microphone"), ["on"])
        self.assertIn("GtkLabel\tFirefox", d)
        # monitor vystupu neni vstup (do seznamu vstupu nepatri)
        self.assertNotIn("Monitor of Built-in Speakers", "\n".join(d))
        self.assertEqual(writes(tmp), [], "opening the page must not change the sound")

    def test_changes_are_written(self):
        tmp, env = make_env()
        app = self.run_app(["wait 400", "slider Output volume 45", "switch Mute on", "slider Input volume 20",
                            "switch Mute microphone off", "slider Firefox 10", "wait 800", "quit"], tmp, env)
        app.wait_exit()
        log = writes(tmp)
        self.assertIn("set-sink-volume @DEFAULT_SINK@ 45%", log)
        self.assertIn("set-sink-mute @DEFAULT_SINK@ 1", log)
        self.assertIn("set-source-volume @DEFAULT_SOURCE@ 20%", log)
        self.assertIn("set-source-mute @DEFAULT_SOURCE@ 0", log)
        self.assertIn("set-sink-input-volume 41 10%", log)

    def test_output_device_moves_playing_sounds(self):
        tmp, env = make_env()
        self.run_app(["wait 400", "combo Output device bluez_output.headset", "wait 800", "dump", "quit"],
                     tmp, env).wait_exit()
        log = writes(tmp)
        self.assertIn("set-default-sink bluez_output.headset", log)
        self.assertIn("move-sink-input 41 bluez_output.headset", log)

    def test_external_change_is_shown_and_not_written_back(self):
        tmp, env = make_env()
        app = self.run_app(["wait 600", "dump", "wait 1500", "dump", "quit"], tmp, env)
        self.assertEqual(find(app.wait_dump(1), "GtkScale", "Output volume"), ["30"])
        # klavesa hlasitosti: zmena na serveru + udalost
        state = json.loads((tmp / "pactl.json").read_text())
        state["sinks"][0]["vol"] = 72
        state["sinks"][0]["mute"] = True
        state["streams"].append({"id": 42, "name": "Music Player", "vol": 90})
        (tmp / "pactl.json").write_text(json.dumps(state))
        with open(str(tmp / "pactl.json") + ".events", "a") as f:
            f.write("Event 'change' on sink #1\n")
        d = app.wait_dump(2)
        app.wait_exit()
        self.assertEqual(find(d, "GtkScale", "Output volume"), ["72"])
        self.assertEqual(find(d, "GtkSwitch", "Mute"), ["on"])
        self.assertIn("GtkLabel\tMusic Player", d)
        self.assertEqual(writes(tmp), [], "a change from outside must not be written back to the server")

    def test_without_sound_server(self):
        tmp, env = make_env()
        (tmp / "bin/pactl").write_text("#!/bin/sh\nexit 1\n")
        d = self.run_app(["wait 500", "dump", "quit"], tmp, env).wait_dump()
        self.assertIn("GtkLabel\tThe sound server is not running.", d)


if __name__ == "__main__":
    unittest.main()
