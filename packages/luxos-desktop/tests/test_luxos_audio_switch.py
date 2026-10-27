#!/usr/bin/env python3
"""LuxOS - automaticke prepnuti zvukoveho vystupu (luxos_audio_switch.py) proti falesnemu pactl.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_audio_switch.py -v

Falesny pactl (tests/fake-pactl/pactl) drzi stav karet a vystupu v JSON - skutecny zvuk se nemeni.
Karty odpovidaji vystupu `pactl -f json list cards` z pipewire-pulse (PulseAudio 17).
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.join(HERE, "..", "files", "python", "luxos_audio_switch.py")
FAKE = os.path.join(HERE, "fake-pactl", "pactl")

ANALOG = "output:analog-stereo+input:analog-stereo"
HDMI = "output:hdmi-stereo+input:analog-stereo"
HDMI_ONLY = "output:hdmi-stereo"


def port(desc, typ, avail, profiles):
    return {"description": desc, "type": typ, "priority": 5900, "latency_offset": "0 usec",
            "availability_group": None, "availability": avail, "properties": {}, "profiles": profiles}


def hda_card(hdmi_avail="not available", active=ANALOG):
    """Intel HDA: analogove reproduktory + HDMI v jinem profilu (typicky notebook/PC)."""
    return {
        "index": 47, "name": "alsa_card.pci-0000_00_1f.3", "driver": "alsa",
        "properties": {"object.id": "47", "device.bus": "pci", "device.description": "Built-in Audio"},
        "profiles": {
            "off": {"description": "Off", "sinks": 0, "sources": 0, "priority": 0, "available": True},
            ANALOG: {"description": "Analog Stereo Duplex", "sinks": 1, "sources": 1, "priority": 6565,
                     "available": True},
            HDMI: {"description": "Digital Stereo (HDMI) Output + Analog Stereo Input", "sinks": 1,
                   "sources": 1, "priority": 5965, "available": hdmi_avail == "available"},
            HDMI_ONLY: {"description": "Digital Stereo (HDMI) Output", "sinks": 1, "sources": 0,
                        "priority": 5900, "available": hdmi_avail == "available"},
        },
        "active_profile": active,
        "ports": {
            "analog-output-speaker": port("Speakers", "Speaker", "availability unknown", [ANALOG]),
            "analog-input-mic": port("Microphone", "Mic", "availability unknown", [ANALOG, HDMI]),
            "hdmi-output-0": port("HDMI / DisplayPort", "HDMI", hdmi_avail, [HDMI, HDMI_ONLY]),
        },
    }


def sink(name, ports, active):
    return {"name": name, "description": name, "properties": {},
            "ports": [{"name": p, "availability": "available"} for p in ports], "active_port": active}


SPK = "alsa_output.pci-0000_00_1f.3.analog-stereo"
HDMI_SINK = "alsa_output.pci-0000_00_1f.3.hdmi-stereo"
HDA_SINKS = {ANALOG: [sink(SPK, ["analog-output-speaker"], "analog-output-speaker")],
             HDMI: [sink(HDMI_SINK, ["hdmi-output-0"], "hdmi-output-0")],
             HDMI_ONLY: [sink(HDMI_SINK, ["hdmi-output-0"], "hdmi-output-0")]}


def ucm_card(hdmi_avail):
    """SOF/UCM (novejsi Intel notebooky): jeden profil HiFi, HDMI je samostatny vystup stale."""
    return {
        "index": 50, "name": "alsa_card.pci-0000_00_1f.3-platform-skl_hda_dsp_generic", "driver": "alsa",
        "properties": {"object.id": "50", "device.bus": "pci"},
        "profiles": {"HiFi": {"description": "Play HiFi quality Music", "sinks": 2, "sources": 1,
                              "priority": 8192, "available": True}},
        "active_profile": "HiFi",
        "ports": {"[Out] Speaker": port("Speaker", "Speaker", "availability unknown", ["HiFi"]),
                  "[Out] HDMI1": port("HDMI / DisplayPort 1 Output", "HDMI", hdmi_avail, ["HiFi"])},
    }


UCM_SPK = "alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Speaker__sink"
UCM_HDMI = "alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__HDMI1__sink"


def usb_card():
    return {"index": 60, "name": "alsa_card.usb-Logitech_USB_Headset-00", "driver": "alsa",
            "properties": {"object.id": "60", "device.bus": "usb"},
            "profiles": {"output:analog-stereo+input:mono-fallback": {
                "description": "Analog Stereo Output + Mono Input", "sinks": 1, "sources": 1,
                "priority": 6501, "available": True}},
            "active_profile": "output:analog-stereo+input:mono-fallback",
            "ports": {"analog-output": port("Analog Output", "Headset", "availability unknown",
                                            ["output:analog-stereo+input:mono-fallback"])}}


USB_SINK = "alsa_output.usb-Logitech_USB_Headset-00.analog-stereo"


class AudioSwitch(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="luxos-audio-switch-")
        self.addCleanup(shutil.rmtree, self.t, True)
        self.pa = os.path.join(self.t, "pa.json")
        os.makedirs(os.path.join(self.t, "run"), mode=0o700)
        self.env = dict(os.environ, FAKE_PA=self.pa, LUXOS_PACTL=FAKE, XDG_RUNTIME_DIR=os.path.join(self.t, "run"),
                        LUXOS_AUDIO_WAIT="0.5")
        self.state = {"cards": [hda_card()], "profile_sinks": {"alsa_card.pci-0000_00_1f.3": HDA_SINKS},
                      "default": SPK, "inputs": [7, 9]}
        self.write()

    def write(self):
        with open(self.pa, "w") as f:
            json.dump(self.state, f)
        if os.path.exists(self.pa + ".log"):
            os.unlink(self.pa + ".log")

    def read(self):
        with open(self.pa) as f:
            self.state = json.load(f)
        return self.state

    def log(self):
        try:
            with open(self.pa + ".log") as f:
                return [ln.strip() for ln in f if not ln.startswith(("-f json", "list short", "info"))]
        except OSError:
            return []

    def check(self):
        r = subprocess.run([sys.executable, "-I", HELPER, "check"], env=self.env, capture_output=True,
                           text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.read()

    def set_card(self, card):
        self.read()
        self.state["cards"] = [c for c in self.state["cards"] if c["name"] != card["name"]] + [card]
        self.write()

    def remove_card(self, name):
        self.read()
        self.state["cards"] = [c for c in self.state["cards"] if c["name"] != name]
        names = [s["name"] for c in self.state["cards"]
                 for s in self.state["profile_sinks"].get(c["name"], {}).get(c["active_profile"], [])]
        if self.state["default"] not in names:
            self.state["default"] = names[0]          # jako WirePlumber: zbyly vystup
        self.write()

    def hda(self):
        return copy.deepcopy(next(c for c in self.read()["cards"] if c["name"] == "alsa_card.pci-0000_00_1f.3"))

    def plug_hdmi(self):
        card = self.hda()
        card["ports"]["hdmi-output-0"]["availability"] = "available"
        card["profiles"][HDMI]["available"] = card["profiles"][HDMI_ONLY]["available"] = True
        self.set_card(card)

    def unplug_hdmi(self):
        card = self.hda()
        card["ports"]["hdmi-output-0"]["availability"] = "not available"
        card["profiles"][HDMI]["available"] = card["profiles"][HDMI_ONLY]["available"] = False
        self.set_card(card)

    def test_first_run_only_remembers(self):
        """Prihlaseni s uz pripojenym monitorem: nic se neprepina."""
        self.state["cards"] = [hda_card("available")]
        self.write()
        self.check()
        self.assertEqual(self.log(), [])
        self.assertEqual(self.state["default"], SPK)

    def test_hdmi_plug_switches_profile_default_and_streams(self):
        self.check()
        self.plug_hdmi()
        st = self.check()
        self.assertIn("set-card-profile alsa_card.pci-0000_00_1f.3 " + HDMI, self.log())  # mikrofon zustal
        self.assertEqual(st["default"], HDMI_SINK)
        self.assertEqual(st["input_sink"], {"7": HDMI_SINK, "9": HDMI_SINK})
        # dalsi udalost (zmena hlasitosti apod.) nic neopakuje
        self.write()
        self.check()
        self.assertEqual(self.log(), [])

    def test_hdmi_unplug_returns_to_speakers(self):
        self.check()
        self.plug_hdmi()
        self.check()
        self.unplug_hdmi()
        st = self.check()
        self.assertIn("set-card-profile alsa_card.pci-0000_00_1f.3 " + ANALOG, self.log())
        self.assertEqual(st["cards"][0]["active_profile"], ANALOG)
        self.assertEqual(st["default"], SPK)
        self.assertEqual(st["input_sink"]["7"], SPK)

    def test_manual_choice_is_respected(self):
        """Po automatickem prepnuti si uzivatel vybere jiny vystup: po odpojeni se nic nevraci."""
        self.state["cards"].append(usb_card())
        self.state["profile_sinks"]["alsa_card.usb-Logitech_USB_Headset-00"] = {
            "output:analog-stereo+input:mono-fallback": [sink(USB_SINK, ["analog-output"], "analog-output")]}
        self.write()
        self.check()
        self.plug_hdmi()
        self.check()
        self.read()
        self.state["default"] = USB_SINK                  # rucni volba (pavucontrol / lista)
        self.write()
        self.check()
        self.assertEqual(self.log(), [])                  # zmena vychoziho se nevraci
        self.unplug_hdmi()
        st = self.check()
        self.assertEqual(self.log(), [])
        self.assertEqual(st["default"], USB_SINK)

    def test_manual_profile_change_not_reverted(self):
        self.check()
        self.plug_hdmi()
        self.check()
        card = self.hda()
        card["active_profile"] = ANALOG                   # uzivatel vratil profil rucne
        self.set_card(card)
        self.state["default"] = SPK                       # vystup HDMI zmizel, WirePlumber vybral reproduktory
        self.write()
        self.check()
        self.unplug_hdmi()
        self.check()
        self.assertFalse([c for c in self.log() if c.startswith(("set-card-profile", "set-default-sink"))])

    def test_ucm_hdmi_sink_without_profile_change(self):
        """SOF/UCM: HDMI vystup existuje stale, pripojenim jen zmeni dostupnost portu."""
        name = "alsa_card.pci-0000_00_1f.3-platform-skl_hda_dsp_generic"
        self.state = {"cards": [ucm_card("not available")],
                      "profile_sinks": {name: {"HiFi": [sink(UCM_SPK, ["[Out] Speaker"], "[Out] Speaker"),
                                                        sink(UCM_HDMI, ["[Out] HDMI1"], "[Out] HDMI1")]}},
                      "default": UCM_SPK, "inputs": [3]}
        self.write()
        self.check()
        self.set_card(ucm_card("available"))
        st = self.check()
        self.assertFalse([c for c in self.log() if c.startswith("set-card-profile")])
        self.assertEqual(st["default"], UCM_HDMI)
        self.set_card(ucm_card("not available"))
        st = self.check()
        self.assertEqual(st["default"], UCM_SPK)

    def test_gpu_card_from_off_profile(self):
        """Samostatna karta grafiky (HDMI NVIDIA/AMD) s profilem off: zapne HDMI profil a vrati off."""
        gpu = {"index": 70, "name": "alsa_card.pci-0000_01_00.1", "driver": "alsa",
               "properties": {"object.id": "70", "device.bus": "pci"},
               "profiles": {"off": {"description": "Off", "sinks": 0, "sources": 0, "priority": 0, "available": True},
                            HDMI_ONLY: {"description": "Digital Stereo (HDMI) Output", "sinks": 1, "sources": 0,
                                        "priority": 5900, "available": False}},
               "active_profile": "off",
               "ports": {"hdmi-output-1": port("HDMI / DisplayPort 2", "HDMI", "not available", [HDMI_ONLY])}}
        gsink = "alsa_output.pci-0000_01_00.1.hdmi-stereo-extra1"
        self.state["cards"].append(gpu)
        self.state["profile_sinks"]["alsa_card.pci-0000_01_00.1"] = {
            HDMI_ONLY: [sink(gsink, ["hdmi-output-1"], "hdmi-output-1")]}
        self.write()
        self.check()
        gpu = copy.deepcopy(gpu)
        gpu["ports"]["hdmi-output-1"]["availability"] = "available"
        gpu["profiles"][HDMI_ONLY]["available"] = True
        self.set_card(gpu)
        st = self.check()
        self.assertIn("set-card-profile alsa_card.pci-0000_01_00.1 " + HDMI_ONLY, self.log())
        self.assertEqual(st["default"], gsink)
        gpu = copy.deepcopy(next(c for c in st["cards"] if c["name"] == gpu["name"]))
        gpu["ports"]["hdmi-output-1"]["availability"] = "not available"
        self.set_card(gpu)
        st = self.check()
        self.assertEqual(next(c for c in st["cards"] if c["name"] == gpu["name"])["active_profile"], "off")
        self.assertEqual(st["default"], SPK)

    def test_usb_headset_plug_and_unplug(self):
        self.check()
        self.read()
        self.state["profile_sinks"]["alsa_card.usb-Logitech_USB_Headset-00"] = {
            "output:analog-stereo+input:mono-fallback": [sink(USB_SINK, ["analog-output"], "analog-output")]}
        self.state["cards"].append(usb_card())
        self.write()
        st = self.check()
        self.assertEqual(st["default"], USB_SINK)
        self.assertEqual(st["input_sink"]["9"], USB_SINK)
        self.remove_card("alsa_card.usb-Logitech_USB_Headset-00")
        st = self.check()
        self.assertEqual(st["default"], SPK)

    def test_bluetooth_headphones(self):
        self.check()
        bt = {"index": 80, "name": "bluez_card.00_1B_66_AA_BB_CC", "driver": "module-bluez5-device.c",
              "properties": {"object.id": "80", "device.bus": "bluetooth"},
              "profiles": {"a2dp-sink": {"description": "High Fidelity Playback (A2DP Sink)", "sinks": 1,
                                         "sources": 0, "priority": 40, "available": True}},
              "active_profile": "a2dp-sink",
              "ports": {"headphone-output": port("Headphone", "Headphones", "available", ["a2dp-sink"])}}
        self.read()
        self.state["cards"].append(bt)
        self.state["profile_sinks"][bt["name"]] = {
            "a2dp-sink": [sink("bluez_output.00_1B_66_AA_BB_CC.1", ["headphone-output"], "headphone-output")]}
        self.write()
        st = self.check()
        self.assertEqual(st["default"], "bluez_output.00_1B_66_AA_BB_CC.1")

    def test_pactl_missing_is_harmless(self):
        env = dict(self.env, LUXOS_PACTL=os.path.join(self.t, "nope"))
        r = subprocess.run([sys.executable, "-I", HELPER, "check"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
