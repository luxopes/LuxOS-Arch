"""Bezi uvnitr testovaci VM jako root (test_luxwm_libinput_vm.py): luxwm na backendu headless + libinput
se skutecnymi zarizenimi libinput - mysi QEMU (USB, VMMouse) a touchpad a druha mys z /dev/uinput.

  python3 libinput_guest.py ADRESAR    ADRESAR s luxwm, luxwm-msg a libluxcomp.so.0

Vypise jeden radek JSON s odpovedmi get_input po jednotlivych krocich.
"""
import fcntl
import glob
import json
import os
import socket
import struct
import subprocess
import sys
import time

EV_SYN, EV_KEY, EV_REL, EV_ABS = 0, 1, 2, 3
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_RELBIT, UI_SET_ABSBIT, UI_SET_PROPBIT = 0x40045564, 0x40045565, 0x40045566, 0x40045567, 0x4004556e
UI_DEV_SETUP, UI_ABS_SETUP, UI_DEV_CREATE, UI_DEV_DESTROY = 0x405c5503, 0x401c5504, 0x5501, 0x5502
BUS_USB, BUS_I2C = 0x03, 0x18
TOUCHPAD = "LuxOS Test Touchpad"
MOUSE = "LuxOS Test Mouse"


def uinput(name, bus, keys, rels=(), absinfo=(), props=()):
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    for ev, codes, op in ((EV_KEY, keys, UI_SET_KEYBIT), (EV_REL, rels, UI_SET_RELBIT),
                          (EV_ABS, [a[0] for a in absinfo], UI_SET_ABSBIT)):
        if codes:
            fcntl.ioctl(fd, UI_SET_EVBIT, ev)
            for code in codes:
                fcntl.ioctl(fd, op, code)
    for prop in props:
        fcntl.ioctl(fd, UI_SET_PROPBIT, prop)
    for code, lo, hi, res in absinfo:
        fcntl.ioctl(fd, UI_ABS_SETUP, struct.pack("HH6i", code, 0, 0, lo, hi, 0, 0, res))
    fcntl.ioctl(fd, UI_DEV_SETUP, struct.pack("4H80sI", bus, 0x1234, 0x5678, 1, name.encode(), 0))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    return fd


def touchpad():
    # clickpad (INPUT_PROP_BUTTONPAD) se dvema prsty: libinput nabidne klepnuti, metody kliknuti i posouvani
    keys = [0x110, 0x145, 0x14a, 0x14d, 0x14e]   # BTN_LEFT, TOOL_FINGER, TOUCH, TOOL_DOUBLETAP, TOOL_TRIPLETAP
    axes = [(0x00, 0, 4000, 40), (0x01, 0, 2400, 40), (0x2f, 0, 4, 0), (0x35, 0, 4000, 40), (0x36, 0, 2400, 40),
            (0x39, 0, 65535, 0)]
    return uinput(TOUCHPAD, BUS_I2C, keys, absinfo=axes, props=[0x00, 0x02])


def mouse():
    return uinput(MOUSE, BUS_USB, [0x110, 0x111, 0x112], rels=[0x00, 0x01, 0x08])


class Luxwm:
    def __init__(self, bindir):
        self.base = "/run/luxos-input-test"
        subprocess.run(["rm", "-rf", self.base])
        self.run = os.path.join(self.base, "run")
        self.cfg = os.path.join(self.base, "config")
        os.makedirs(self.run, mode=0o700)
        os.makedirs(os.path.join(self.cfg, "luxwm"))
        system = os.path.join(self.base, "system.conf")
        with open(system, "w") as f:
            f.write("xwayland = no\nworkspaces = 1\n")
        env = {"PATH": "/usr/bin", "HOME": "/root", "XDG_RUNTIME_DIR": self.run, "XDG_CONFIG_HOME": self.cfg,
               "LD_LIBRARY_PATH": bindir, "LUXWM_SYSTEM_CONFIG": system, "WLR_BACKENDS": "headless,libinput",
               "LIBSEAT_BACKEND": "noop", "WLR_RENDERER": "pixman", "LUXWM_TRACE": "1"}
        self.log = open(os.path.join(self.base, "luxwm.log"), "w")
        self.proc = subprocess.Popen([os.path.join(bindir, "luxwm")], env=env, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 20
        while not glob.glob(os.path.join(self.run, "luxwm-*.sock")):
            if time.monotonic() > deadline or self.proc.poll() is not None:
                raise RuntimeError("luxwm did not start: " + open(self.log.name).read()[-2000:])
            time.sleep(0.1)
        self.sock = glob.glob(os.path.join(self.run, "luxwm-*.sock"))[0]

    def conf(self, text):
        with open(os.path.join(self.cfg, "luxwm", "luxwm.conf"), "w") as f:
            f.write(text)

    def request(self, cmd):
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(10)
        s.connect(self.sock)
        s.sendall((json.dumps({"id": 1, "cmd": cmd}) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
        s.close()
        return json.loads(data)

    def stop(self):
        self.proc.terminate()
        self.proc.wait(10)
        return open(self.log.name).read()


def settle():
    # udev a libinput potrebuji chvili na nove zarizeni
    time.sleep(1.5)


def main():
    bindir = sys.argv[1]
    out = {}
    pad = touchpad()
    settle()
    wm = Luxwm(bindir)
    try:
        settle()
        out["defaults"] = wm.request("get_input")
        wm.conf("mouse_speed = -50\nmouse_accel = flat\nmouse_natural_scroll = yes\nmouse_left_handed = yes\n"
                "mouse_middle_emulation = yes\ntouchpad_speed = 30\ntouchpad_natural_scroll = yes\ntouchpad_tap = yes\n"
                "touchpad_tap_drag = no\ntouchpad_disable_while_typing = no\ntouchpad_click_method = clickfinger\n"
                "touchpad_scroll_method = edge\n")
        wm.request("reload")
        out["configured"] = wm.request("get_input")
        # pripojeni za behu dostane nastaveni sveho druhu
        extra = mouse()
        settle()
        out["hotplug"] = wm.request("get_input")
        # smazane polozky vraci vychozi hodnoty zarizeni
        wm.conf("mouse_speed = 20\ntouchpad_natural_scroll = yes\n")
        wm.request("reload")
        out["reloaded"] = wm.request("get_input")
        fcntl.ioctl(extra, UI_DEV_DESTROY)
        os.close(extra)
        settle()
        out["unplugged"] = wm.request("get_input")
    finally:
        out["log"] = wm.stop()[-4000:]
        fcntl.ioctl(pad, UI_DEV_DESTROY)
    print(json.dumps(out))


main()
