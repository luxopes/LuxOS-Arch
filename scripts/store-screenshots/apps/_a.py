"""Spolecne pomucky postupu skupiny a (LuxAI, Lux Code, LSL IDE, Posta, Ucet LuxAI, Telefon, Co je noveho,
Zpetna vazba). Soubor zacina "_", takze neni postup aplikace.

Programy v Pythonu z luxos-desktop / luxos-account vkladaji na zacatek sys.path /usr/lib/luxos/python;
run_python() proto nejdriv nacte moduly z pracovni kopie (luxai_account, luxos_i18n ...) a teprve pak
spusti program - pouziji se moduly ze zdroju, ne nainstalovane.
"""
import hashlib
import json
import os
import subprocess
import sys
import tarfile

LAUNCHER = r'''
import os, runpy, sys
paths = %(paths)r
for p in reversed(paths):
    sys.path.insert(0, p)
for m in %(modules)r:
    __import__(m)
sys.argv = [%(script)r] + %(args)r
runpy.run_path(%(script)r, run_name="__main__")
'''


def run_python(s, rel, *args, paths=(), modules=(), env=None):
    """Program v Pythonu ze zdroju (packages/<rel>); moduly `modules` se nactou z pracovni kopie
    (paths = slozky v packages/ + spolecne moduly LuxOS) jeste pred programem."""
    e = s.python_env(*paths)
    launcher = os.path.join(s.tmp, "launch-%s.py" % os.path.basename(rel).replace(".", "_"))
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"paths": e["PYTHONPATH"].split(":"), "modules": list(modules),
                            "script": s.src(rel), "args": list(args)})
    return s.launch([sys.executable, "-I", launcher], env=env)


def no_real_avatar(s):
    """Profilova fotka: nikdy skutecna fotka uzivatele z AccountsService (luxos_avatar)."""
    s.env["LUXOS_ACCOUNTS_FAKE"] = os.path.join(s.tmp, "no-accounts-icon")


def demo_account(s, origin, name="Alex Morgan", email="alex@example.com", username="alex"):
    """~/.config/luxai/account.json ukazkoveho uctu proti mistnimu falesnemu serveru."""
    user = {"id": "u-demo", "email": email, "displayName": name, "username": username}
    data = {"version": 1, "origin": origin, "sessionToken": "demo-session-token", "user": user,
            "client": "luxos", "updatedAt": "2026-11-07T10:00:00+0100"}
    path = s.write(".config/luxai/account.json", json.dumps(data, indent=1), 0o600)
    os.chmod(os.path.dirname(path), 0o700)
    return path


def cache_dir(s):
    """Mezipamet prelozenych programu mezi behy (klic = hash zdroju); na disku v out/ jako docasna
    data snimkovani, ne v /tmp (tmpfs)."""
    d = os.path.join(s.repo, "out", "store-screenshots", "build-cache")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def file_hash(*paths):
    h = hashlib.sha256()
    for p in paths:
        with open(p, "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:16]


def extract(s, rel, dest_name):
    """Zdrojovy archiv packages/<rel> rozbalit do s.tmp/<dest_name> -> slozka <pkg>-<ver>."""
    dest = os.path.join(s.tmp, dest_name)
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(s.src(rel)) as t:
        t.extractall(dest, filter="data")
    subdirs = [d for d in os.listdir(dest) if os.path.isdir(os.path.join(dest, d))]
    return os.path.join(dest, subdirs[0]) if len(subdirs) == 1 else dest


def build_cached(s, key, out_name, build):
    """build(out_path) jen kdyz v mezipameti neni program pro dany klic (hash zdroju)."""
    d = os.path.join(cache_dir(s), key)
    out = os.path.join(d, out_name)
    if not os.path.exists(out):
        os.makedirs(d, exist_ok=True)
        tmp = out + ".part"
        build(tmp)
        os.chmod(tmp, 0o755)
        os.replace(tmp, out)
    return out


def run(cmd, cwd=None, env=None, timeout=900):
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError("%s failed: %s" % (" ".join(cmd), (r.stdout + r.stderr)[-3000:]))
    return r.stdout


def fake_tool(s, name, script):
    """Falesny pomocny program (shell skript) v s.tmp/fake-bin -> cesta."""
    d = os.path.join(s.tmp, "fake-bin")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\n" + script)
    os.chmod(path, 0o755)
    return path


# Maly ukazkovy projekt LSL (LSL IDE, Lux Code): nakupni seznam ve dvou souborech
MAIN = '''# Shopping list - a small LSL demo project
load basket

function main():
    items = [
        basket.item("Apples", 6, 45),
        basket.item("Bread", 1, 210),
        basket.item("Coffee beans", 2, 790),
        basket.item("Milk", 2, 115)
    ]
    print "Shopping list"
    print "-------------"
    for item in items:
        print l"{item["name"]} x{item["qty"]}: {basket.money(basket.cost(item))}"
    end
    total = basket.total(items)
    print l"Total: {basket.money(total)}"
    if total > 2000:
        print "Free delivery!"
    end
end

call main()
'''

BASKET = '''# Basket helpers: prices are in cents

function item(name, qty, price):
    return {"name": name, "qty": qty, "price": price}
end

function cost(item):
    return item["qty"] * item["price"]
end

function total(items):
    sum = 0
    for item in items:
        sum += cost(item)
    end
    return sum
end

function money(cents):
    rest = String(cents % 100)
    if len(rest) < 2:
        rest = "0" + rest
    end
    return "$" + String(cents // 100) + "." + rest
end
'''

README = "# Shopping list\n\nA small LSL demo: `lsl main.lsl` prints the list and the total.\n"


def demo_lsl_project(s):
    """~/Projects/shopping-list -> cesta k main.lsl."""
    s.write("Projects/shopping-list/basket.lsl", BASKET)
    s.write("Projects/shopping-list/README.md", README)
    return s.write("Projects/shopping-list/main.lsl", MAIN)
