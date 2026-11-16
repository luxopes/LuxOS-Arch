"""LuxOS - testovaci vstupni zarizeni X serveru bez roota (testy posouvani).

Soukromy Xorg (/usr/lib/Xorg, ne setuid) s video ovladacem dummy (xf86-video-dummy, staci rozbaleny
balik - LUXOS_XORG_DUMMY_DIR) a vstupnim ovladacem inputtest (soucast xorg-server). Zarizeni inputtest
posilaji skutecne udalosti XI2 vcetne plynulych posunu (valuatory 2/3 s krokem 120 jako
xf86-input-libinput), takze GDK je zpracuje stejnou cestou jako touchpad a kolecko na skutecnem
hardwaru. Touchpad GDK pozna podle vlastnosti zarizeni "libinput Tapping Enabled" - test ji vytvori
(xinput set-prop), jako ji ma kazdy touchpad pres libinput.

Vlastni displej, zadne zasahy do relace uzivatele, zadny uinput ani root.
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
import ctypes
import os
import shutil
import socket
import subprocess
import tempfile
import time

XORG = "/usr/lib/Xorg"
INPUTTEST = "/usr/lib/xorg/modules/input/inputtest_drv.so"

EV_CLIENT_VERSION, EV_WAIT_FOR_SYNC, EV_MOTION, EV_PROXIMITY, EV_BUTTON, EV_KEY = range(6)
MAX_VAL = 64


class Header(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint32), ("type", ctypes.c_int32)]


class Valuators(ctypes.Structure):
    _fields_ = [("has_unaccelerated", ctypes.c_uint32), ("mask", ctypes.c_uint8 * ((MAX_VAL + 7) // 8)),
                ("valuators", ctypes.c_double * MAX_VAL), ("unaccelerated", ctypes.c_double * MAX_VAL)]


class ClientVersion(ctypes.Structure):
    _fields_ = [("header", Header), ("major", ctypes.c_uint16), ("minor", ctypes.c_uint16)]


class WaitForSync(ctypes.Structure):
    _fields_ = [("header", Header)]


class Motion(ctypes.Structure):
    _fields_ = [("header", Header), ("is_absolute", ctypes.c_uint32), ("valuators", Valuators)]


class Key(ctypes.Structure):
    _fields_ = [("header", Header), ("key_code", ctypes.c_int32), ("is_press", ctypes.c_uint32)]


class Button(ctypes.Structure):
    _fields_ = [("header", Header), ("is_absolute", ctypes.c_int32), ("button", ctypes.c_int32),
                ("is_press", ctypes.c_uint32), ("valuators", Valuators)]


CONF = """Section "ServerFlags"
    Option "AutoAddDevices" "false"
    Option "AutoAddGPU" "false"
    Option "DontVTSwitch" "true"
EndSection
Section "Files"
    ModulePath "{dummy}"
    ModulePath "/usr/lib/xorg/modules"
EndSection
Section "Device"
    Identifier "dummy"
    Driver "dummy"
    VideoRam 64000
EndSection
Section "Monitor"
    Identifier "mon"
    HorizSync 5.0 - 1000.0
    VertRefresh 5.0 - 200.0
    Modeline "1280x800" 83.46 1280 1344 1480 1680 800 801 804 828
EndSection
Section "Screen"
    Identifier "screen"
    Device "dummy"
    Monitor "mon"
    DefaultDepth 24
    SubSection "Display"
        Depth 24
        Modes "1280x800"
    EndSubSection
EndSection
Section "InputDevice"
    Identifier "LuxOS Test Touchpad"
    Driver "inputtest"
    Option "SocketPath" "{dir}/tp.sock"
    Option "DeviceType" "Pointer"
EndSection
Section "InputDevice"
    Identifier "LuxOS Test Mouse"
    Driver "inputtest"
    Option "SocketPath" "{dir}/mouse.sock"
    Option "DeviceType" "Pointer"
EndSection
Section "InputDevice"
    Identifier "LuxOS Test Keyboard"
    Driver "inputtest"
    Option "SocketPath" "{dir}/kbd.sock"
    Option "DeviceType" "Keyboard"
EndSection
Section "ServerLayout"
    Identifier "layout"
    Screen "screen"
    InputDevice "LuxOS Test Touchpad" "CorePointer"
    InputDevice "LuxOS Test Mouse" "SendCoreEvents"
    InputDevice "LuxOS Test Keyboard" "CoreKeyboard"
EndSection
"""


def dummy_dir():
    """Adresar s drivers/dummy_drv.so (system nebo rozbaleny balik xf86-video-dummy)."""
    for d in (os.environ.get("LUXOS_XORG_DUMMY_DIR", ""), "/usr/lib/xorg/modules"):
        if d and os.path.exists(os.path.join(d, "drivers", "dummy_drv.so")):
            return d
    return None


def available():
    return (os.path.exists(XORG) and os.path.exists(INPUTTEST) and dummy_dir() is not None
            and shutil.which("xinput") is not None)


class Device:
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        v = ClientVersion()
        v.header.length = ctypes.sizeof(v)
        v.header.type = EV_CLIENT_VERSION
        v.major, v.minor = 1, 1
        self.sock.sendall(bytes(v))
        self.sock.recv(64)

    def motion(self, dx=0.0, dy=0.0, scroll_x=None, scroll_y=None):
        """Relativni pohyb; scroll_* = posun valuatoru 2/3 (120 = jedna zarazka kolecka)."""
        m = Motion()
        m.header.length = ctypes.sizeof(m)
        m.header.type = EV_MOTION
        m.is_absolute = 0
        vals = {}
        if dx or dy:
            vals[0], vals[1] = float(dx), float(dy)
        if scroll_x is not None:
            vals[2] = float(scroll_x)
        if scroll_y is not None:
            vals[3] = float(scroll_y)
        for i, v in vals.items():
            m.valuators.mask[i // 8] |= 1 << (i % 8)
            m.valuators.valuators[i] = v
        self.sock.sendall(bytes(m))

    def button(self, button, press):
        b = Button()
        b.header.length = ctypes.sizeof(b)
        b.header.type = EV_BUTTON
        b.button = button
        b.is_press = 1 if press else 0
        self.sock.sendall(bytes(b))

    def key(self, keycode, press):
        """Klavesa podle kodu X (evdev + 8: 37 = Control_L)."""
        k = Key()
        k.header.length = ctypes.sizeof(k)
        k.header.type = EV_KEY
        k.key_code = keycode
        k.is_press = 1 if press else 0
        self.sock.sendall(bytes(k))

    def sync(self):
        s = WaitForSync()
        s.header.length = ctypes.sizeof(s)
        s.header.type = EV_WAIT_FOR_SYNC
        self.sock.sendall(bytes(s))
        self.sock.recv(64)

    def close(self):
        self.sock.close()


class Server:
    """Soukromy Xorg na volnem displeji; adresar dir je pod out/ (nikdy ne /tmp)."""

    def __init__(self, workdir, display_num=None):
        self.dir = workdir
        os.makedirs(os.path.join(self.dir, "empty.d"), exist_ok=True)
        # cesta k soketu ma nejvys 108 znaku: v dlouhem pracovnim adresari (git worktree) kratsi ~/LuxOS-Arch/out
        self.sockdir = self.dir
        short = os.path.expanduser("~/LuxOS-Arch/out")
        if len(self.dir) > 80 and os.path.isdir(short):
            self.sockdir = tempfile.mkdtemp(prefix="sx-", dir=short)
        with open(os.path.join(self.dir, "xorg.conf"), "w") as f:
            f.write(CONF.format(dir=self.sockdir, dummy=dummy_dir()))
        n = display_num or 140
        while os.path.exists(f"/tmp/.X11-unix/X{n}") or os.path.exists(f"/tmp/.X{n}-lock"):
            n += 1
        self.display = f":{n}"
        self.proc = subprocess.Popen(
            ["nice", "-n", "10", XORG, self.display, "-config", "xorg.conf", "-configdir", "empty.d",
             "-logfile", os.path.join(self.dir, "xorg.log"), "-nolisten", "tcp", "-noreset",
             "-novtswitch", "-sharevts", "-keeptty", "-ac"],
            cwd=self.dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "HOME": self.dir})
        try:
            self._connect(n)
        except BaseException:
            self.stop()
            raise

    def _connect(self, n):
        for _ in range(100):
            if all(os.path.exists(os.path.join(self.sockdir, s)) for s in ("tp.sock", "mouse.sock")) and \
                    os.path.exists(f"/tmp/.X11-unix/X{n}"):
                break
            if self.proc.poll() is not None:
                raise RuntimeError("Xorg failed, see " + os.path.join(self.dir, "xorg.log"))
            time.sleep(0.1)
        time.sleep(0.3)
        env = {"DISPLAY": self.display, "PATH": "/usr/bin:/bin", "HOME": self.dir}
        # touchpad: vlastnost libinput, podle ktere ho GDK pozna (GDK_SOURCE_TOUCHPAD)
        subprocess.run(["xinput", "set-prop", "--type=int", "--format=8", "LuxOS Test Touchpad",
                        "libinput Tapping Enabled", "1"], env=env, check=True, timeout=10)
        self.touchpad = Device(os.path.join(self.sockdir, "tp.sock"))
        self.mouse = Device(os.path.join(self.sockdir, "mouse.sock"))
        self.keyboard = Device(os.path.join(self.sockdir, "kbd.sock"))

    def stop(self):
        for d in (getattr(self, "touchpad", None), getattr(self, "mouse", None), getattr(self, "keyboard", None)):
            if d:
                d.close()
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if self.sockdir != self.dir:
            shutil.rmtree(self.sockdir, True)
