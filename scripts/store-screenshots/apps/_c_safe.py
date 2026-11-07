#!/usr/bin/env python3
"""Trezor pro snimky Obchodu: okno ze zdroju nad falesnym stavem (zadne /safe, helper ani pkexec).

Spousti postup luxos-safe.py. Stav okna se ridi soubory v $DEMO_SAFE: "mountinfo" (zamceno/odemceno
jako /proc/self/mountinfo) a "vault/gocryptfs.conf" (Trezor existuje). Vse, co by sahalo na system
(luxos-safe-helper, gocryptfs, fusermount, Soubory, oznameni), je nahrazene nicim.

    _c_safe.py PATH_TO_luxos-safe
"""
import importlib.machinery
import importlib.util
import os
import sys

DEMO = os.environ["DEMO_SAFE"]


def main():
    loader = importlib.machinery.SourceFileLoader("luxos_safe_demo", sys.argv[1])
    spec = importlib.util.spec_from_loader("luxos_safe_demo", loader)
    safe = importlib.util.module_from_spec(spec)
    loader.exec_module(safe)
    safe.USER = "anna"
    safe.MOUNT = "/safe/anna"
    safe.VAULT = os.path.join(DEMO, "vault")
    safe.CONF_FILE = os.path.join(safe.VAULT, "gocryptfs.conf")
    safe.MOUNTINFO = os.path.join(DEMO, "mountinfo")
    safe.RECOVERED = os.path.join(DEMO, "recovered")
    safe.HELPER = "/nonexistent/luxos-safe-helper"
    nothing = lambda *a, **k: None  # noqa: E731
    for name in ("run_helper", "notify", "open_folder", "add_bookmark", "trust_launcher", "stop_gpg_agents"):
        setattr(safe, name, nothing)
    safe.can_upgrade = lambda: False
    safe.unlock = lambda pw: "demo"
    safe.lock = lambda mode="manual": "demo"
    safe.create = lambda pw: "demo"
    safe.master_key = lambda pw: (None, "demo")
    safe.recover_plaintext = lambda: []
    sys.exit(safe.gui("main"))


if __name__ == "__main__":
    main()
