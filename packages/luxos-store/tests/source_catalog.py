"""Katalog aplikaci LuxOS ze zdrojovych .desktop v repozitari (testy bez sestavenych baliku).

Do katalogu jdou jen .desktop, ktere PKGBUILD instaluje do /usr/share/applications (jako v hotovem
balicku); .desktop aplikaci z [luxos-apps] jsou v archivech zdroju (packages/apps/*/*.tar.gz).
Proprietarni soucasti (LuxAI, Lux Code, LSL IDE, luxos-domain) maji ve verejnem repozitari jen zastupnou
slozku: PROPRIETARY (repo=, pkgnames=) a store/ s kopii .desktop (jen ty, ktere balik instaluje do
/usr/share/applications) a metainfo pro Obchod. S LUXOS_PRIVATE_DIR se misto nich pouziji zdroje ze soukromeho
repozitare luxos-private.
"""
import glob
import os
import re
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGES = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(PACKAGES, "luxos-store", "files"))
import luxos_app_catalog  # noqa: E402

PRIVATE = os.environ.get("LUXOS_PRIVATE_DIR")


def _marker(path):
    """PROPRIETARY -> {"repo": ..., "pkgnames": [...]}"""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.rstrip("\n").split("=", 1)
                out[k] = v
    return {"repo": out.get("repo", "luxos"), "pkgnames": out.get("pkgnames", "").split()}


def _proprietary_stubs(have):
    """Zastupne slozky proprietarnich soucasti (bez PKGBUILD) pro baliky, ktere nejsou v `have`."""
    pkgs = []
    for marker in sorted(glob.glob(os.path.join(PACKAGES, "*", "PROPRIETARY")) +
                         glob.glob(os.path.join(PACKAGES, "apps", "*", "PROPRIETARY"))):
        d = os.path.dirname(marker)
        info = _marker(marker)
        if os.path.exists(os.path.join(d, "PKGBUILD")) or not info["pkgnames"] or info["pkgnames"][0] in have:
            continue
        desktop = {os.path.basename(f)[:-8]: open(f, encoding="utf-8").read()
                   for f in glob.glob(os.path.join(d, "store", "*.desktop"))}
        metainfo = {os.path.basename(f): open(f, encoding="utf-8").read()
                    for f in glob.glob(os.path.join(d, "store", "*.metainfo.xml"))}
        pkgs.append({"name": info["pkgnames"][0], "repo": info["repo"], "version": "1.0.0-1", "depends": [],
                     "desktop": desktop, "metainfo": metainfo})
    return pkgs


def _installed_to_applications(pkgbuild, path):
    """PKGBUILD instaluje .desktop do usr/share/applications (podle jmena nebo cele slozky applications/)."""
    name = os.path.basename(path)
    if os.path.basename(os.path.dirname(path)) == "applications" and \
            re.search(r'usr/share/applications"\s+"\$f"/applications/\*\.desktop', pkgbuild):
        return True
    return f"usr/share/applications/{name}" in pkgbuild


def source_packages():
    pkgs = []
    roots = [PACKAGES] + ([os.path.join(PRIVATE, "packages")] if PRIVATE else [])
    for pkgbuild_path in sorted(p for r in roots for p in glob.glob(os.path.join(r, "*", "PKGBUILD")) +
                                glob.glob(os.path.join(r, "apps", "*", "PKGBUILD"))):
        d = os.path.dirname(pkgbuild_path)
        pkgbuild = open(pkgbuild_path, encoding="utf-8").read()
        m = re.search(r"^pkgname=(\S+)", pkgbuild, re.M)
        if not m:
            continue
        name = m.group(1).strip("'\"")
        repo = "luxos-apps" if os.path.basename(os.path.dirname(d)) == "apps" else "luxos"
        desktop = {}
        for f in glob.glob(os.path.join(d, "**", "*.desktop"), recursive=True):
            if "/tests/" in f:
                continue
            if _installed_to_applications(pkgbuild, f):
                desktop[os.path.basename(f)[:-8]] = open(f, encoding="utf-8").read()
        for tgz in glob.glob(os.path.join(d, "*.tar.gz")):
            with tarfile.open(tgz) as tar:
                for mem in tar.getmembers():
                    base = os.path.basename(mem.name)
                    if mem.isfile() and base.endswith(".desktop") and f"usr/share/applications/{base}" in pkgbuild:
                        desktop[base[:-8]] = tar.extractfile(mem).read().decode("utf-8")
        # popisy pro Obchod: metainfo/*.metainfo.xml, ktere PKGBUILD instaluje do usr/share/metainfo
        metainfo = {}
        installs = re.search(r'usr/share/metainfo"\s+"\$(f|startdir)"/metainfo/\*\.metainfo\.xml', pkgbuild)
        for f in glob.glob(os.path.join(d, "**", "metainfo", "*.metainfo.xml"), recursive=True):
            explicit = f"usr/share/metainfo/{os.path.basename(f)}" in pkgbuild
            if (installs or explicit) and "/tests/" not in f:
                metainfo[os.path.basename(f)] = open(f, encoding="utf-8").read()
        m = re.search(r"^depends=\((.*?)\)", re.sub(r"#[^\n]*", "", pkgbuild), re.M | re.S)
        body = m.group(1) if m else ""
        deps = re.findall(r"[A-Za-z0-9@._+-]+(?:[<>=][^\s'\"]*)?", body)
        pkgs.append({"name": name, "repo": repo, "version": "1.0.0-1", "depends": deps, "desktop": desktop,
                     "metainfo": metainfo})
    return pkgs + _proprietary_stubs({p["name"] for p in pkgs})


def source_catalog():
    return luxos_app_catalog.build_catalog(source_packages())


if __name__ == "__main__":
    for a in source_catalog()["apps"]:
        print(a.get("featured", ""), a["id"], a["package"], a["name"], "|", a["summary"], a["categories"],
              "system" if a.get("system") else "")
