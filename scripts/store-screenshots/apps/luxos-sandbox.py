"""Sandbox: pripraveny sandbox s nainstalovanymi aplikacemi a instalace aplikace s podrobnostmi.

Falesny prikaz luxos-sandbox (LUXOS_SANDBOX_CLI -> _c_sandbox.py cli) jen vypisuje ukazkovy stav a vystup;
zadny skutecny sandbox, pkexec, pacstrap ani bubblewrap.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def shots(s):
    fake = os.path.join(s.tmp, "luxos-sandbox")
    with open(fake, "w") as f:
        f.write('#!/bin/sh\nexec "%s" "%s" cli "$@"\n' % (sys.executable, os.path.join(HERE, "_c_sandbox.py")))
    os.chmod(fake, 0o755)
    gui = s.src("luxos-sandbox/files/luxos-sandbox-gui")
    helper = os.path.join(HERE, "_c_sandbox.py")
    s.python_env()
    env = {"LUXOS_SANDBOX_CLI": fake}
    p = s.launch([sys.executable, helper, "gui", gui, "ready"], env=env)
    win = s.window(pid=p.pid, size=(680, 790))
    s.sleep(1.0)
    s.capture("1", win)
    s.stop()
    env["DEMO_SANDBOX_STATE"] = os.path.join(s.tmp, "installed.json")
    p = s.launch([sys.executable, helper, "gui", gui, "install"], env=env)
    win = s.window(pid=p.pid, size=(680, 790))
    s.sleep(3.0)
    s.capture("2", win)
