#!/usr/bin/env python3
"""LuxOS - laborator AD: zapne/vypne sitovou kartu VM (QMP set_link), test offline prihlaseni.

  vmlink.py ADRESAR_VM NETDEV on|off      napr. vmlink.py out/test-ad/client net1 off
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.environ["LUXOS_VM_DIR"] = sys.argv[1]
import vmctl  # noqa: E402

vmctl.T = sys.argv[1]
vmctl.qmp("set_link", {"name": sys.argv[2], "up": sys.argv[3] == "on"})
print(sys.argv[2], sys.argv[3])
