"""QR kod Wi-Fi: QR kod pripojene site s odkrytym ukazkovym heslem (ikona oka).

Falesny nmcli (LUXOS_NMCLI, jako tests/test_luxos_wifi_qr.py): sit "Home-WiFi" s ukazkovym heslem,
LUXOS_PKEXEC na neskodny skript - na skutecnou sit ani ulozena hesla se nesahne."""
import os

FAKE_NMCLI = r'''#!/usr/bin/env python3
import sys
args = sys.argv[1:]
if args[-2:] == ["show", "--active"]:
    print("loopback:lo-uuid:lo:lo")
    print("802-11-wireless:uuid-home:wlan0:Home-WiFi")
    sys.exit(0)
if "connection" in args and "uuid" in args:
    print("802-11-wireless.ssid:Home-WiFi")
    print("802-11-wireless.hidden:no")
    print("802-11-wireless-security.key-mgmt:wpa-psk")
    print("802-11-wireless-security.psk:" + ("sunny-garden-42" if "--show-secrets" in args else ""))
    print("802-11-wireless-security.wep-key0:")
    sys.exit(0)
sys.exit(2)
'''


def shots(s):
    nmcli = os.path.join(s.tmp, "nmcli")
    with open(nmcli, "w", encoding="utf-8") as f:
        f.write(FAKE_NMCLI)
    os.chmod(nmcli, 0o755)
    pkexec = os.path.join(s.tmp, "pkexec")
    with open(pkexec, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\nexit 126\n")
    os.chmod(pkexec, 0o755)
    env = {"LUXOS_NMCLI": nmcli, "LUXOS_PKEXEC": pkexec, "LUXOS_CAMERA_TEST": "1"}
    p = s.launch_python("luxos-desktop/files/bin/luxos-wifi-qr", env=env)
    win = s.window(pid=p.pid, size=None)
    s.sleep(1)
    # heslo odkryte (ikona oka v poli Heslo)
    s.click(320, 494, win)
    s.capture("1", win)
