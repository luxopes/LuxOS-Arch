"""LuxOS - spolecna prace s webkamerou (v4l2) pro Kameru a Profilovou fotku.

  scan_devices()        seznam kamer [{"path", "name"}] a pocet uzlu bez opravneni
  probe_caps(path)      vhodny format kamery (caps, je-li MJPEG, chyba)
  pick_caps(caps)       vyber formatu z nabidky (<= 1280 px, >= 20 fps, raw pred MJPEG)

Testovani bez kamery: LUXOS_CAMERA_TEST=1 (jedna testovaci kamera videotestsrc), 2 (dve),
none (zadna kamera), busy (kamera obsazena), denied (chybi opravneni).
"""
import fcntl
import glob
import os
import re
import struct

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

TEST = os.environ.get("LUXOS_CAMERA_TEST", "").strip().lower()
MAX_WIDTH = 1280            # vetsi rozliseni zbytecne zatezuje CPU (dekodovani, kresleni, kodovani)
VIDIOC_QUERYCAP = 0x80685600   # _IOR('V', 0, struct v4l2_capability), 104 bajtu
V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_DEVICE_CAPS = 0x80000000


def has(element):
    return Gst.ElementFactory.find(element) is not None


def video_nodes():
    return sorted(glob.glob("/dev/video*"), key=lambda p: int(re.sub(r"\D", "", p) or 0))


def scan_devices():
    """Vraci (kamery, pocet uzlu bez opravneni). Kamera = {"path", "name"}."""
    if TEST in ("1", "2", "busy", "denied"):
        n = 2 if TEST == "2" else 1
        return [{"path": f"test:{i}", "name": f"Test Camera {i + 1}"} for i in range(n)], 0
    if TEST == "none":
        return [], 0
    devices, denied = [], 0
    for path in video_nodes():
        try:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError:
            denied += 1
            continue
        except OSError:
            continue
        try:
            buf = bytearray(104)
            fcntl.ioctl(fd, VIDIOC_QUERYCAP, buf)
        except OSError:
            continue
        finally:
            os.close(fd)
        caps, dcaps = struct.unpack_from("<II", buf, 84)
        if not (dcaps if caps & V4L2_CAP_DEVICE_CAPS else caps) & V4L2_CAP_VIDEO_CAPTURE:
            continue   # metadatovy uzel stejne kamery
        name = bytes(buf[16:48]).split(b"\0")[0].decode(errors="replace").strip() or path
        name = name.split(":")[0].strip() or name   # UVC: "Integrated Camera: Integrated C"
        devices.append({"path": path, "name": name})
    seen = {}
    for d in devices:   # stejne nazvy odlisit cislem
        seen[d["name"]] = seen.get(d["name"], 0) + 1
        if seen[d["name"]] > 1:
            d["name"] = f"{d['name']} ({seen[d['name']]})"
    return devices, denied


def _fps(text):
    """Nejvyssi snimkova frekvence <= 30 z popisu struktury caps; (fps, "n/d" nebo None)."""
    m = re.search(r"framerate=\(fraction\)(\{[^}]*\}|\[[^\]]*\]|[0-9/]+)", text)
    if not m:
        return 0, None
    rates = [(int(n), int(d)) for n, d in re.findall(r"(\d+)/(\d+)", m.group(1)) if int(d)]
    if not rates:
        return 0, None
    if m.group(1).startswith("["):     # rozsah - frekvenci necht vyjedna v4l2src
        return min(max(n / d for n, d in rates), 30), None
    low = [r for r in rates if r[0] / r[1] <= 30.5]
    n, d = max(low or rates, key=lambda r: r[0] / r[1])
    return n / d, f"{n}/{d}"


def pick_caps(caps):
    """Z nabidky kamery vybere rozumny format: <= 1280 px, >= 20 fps, raw pred MJPEG."""
    best, best_score = None, None
    for i in range(caps.get_size()):
        s = caps.get_structure(i)
        name = s.get_name()
        if name not in ("video/x-raw", "image/jpeg"):
            continue
        ok_w, w = s.get_int("width")
        ok_h, h = s.get_int("height")
        if not (ok_w and ok_h):
            continue
        fps, rate = _fps(s.to_string())
        small = w <= MAX_WIDTH
        score = (small, fps >= 20, w * h if small else -w * h, name == "video/x-raw", fps)
        if best_score is None or score > best_score:
            text = f"{name},width={w},height={h}"
            if rate:
                text += f",framerate={rate}"
            fmt = s.get_string("format") if name == "video/x-raw" else None
            if fmt:
                text += f",format={fmt}"
            best, best_score = (text, name == "image/jpeg"), score
    return best


def probe_caps(path):
    """Otevre kameru (stav READY) a zjisti nabizene formaty. Vraci (caps, jpeg, chyba)."""
    src = Gst.ElementFactory.make("v4l2src", None)
    if src is None:
        return None, False, "missing"
    src.set_property("device", path)
    try:
        if src.set_state(Gst.State.READY) == Gst.StateChangeReturn.FAILURE:
            return None, False, "open"
        caps = src.get_static_pad("src").query_caps(None)
        picked = pick_caps(caps) if caps else None
    finally:
        src.set_state(Gst.State.NULL)
    if not picked:
        return None, False, None
    return picked[0], picked[1], None
