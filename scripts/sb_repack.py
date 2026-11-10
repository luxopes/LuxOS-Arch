#!/usr/bin/env python3
"""LuxOS - podpis souboru EFI uvnitr hotoveho baliku (.pkg.tar.zst) bez nove stavby.

  sb_repack.py BALIK SIGNER VZOR...

Soubory baliku, jejichz cesta odpovida nekteremu VZORU (fnmatch, napr. usr/lib/modules/*/vmlinuz),
se vybali do docasneho adresare, spusti se na ne prikaz SIGNER (SIGNER SOUBOR - podepise ho na
miste, viz scripts/sb-sign.sh) a vrati se zpet. Vse ostatni zustava bajt po bajtu stejne (poradi,
vlastnik, prava, cas): upravi se jen data podepsanych souboru, jejich radek v .MTREE (size, md5,
sha256) a "size" v .PKGINFO. Novy balik nahradi puvodni atomicky; podpis GPG (BALIK.sig) uz
neplati - smaze se a balik se musi znovu podepsat (make_repo, repo-add).

Vystup: seznam podepsanych souboru; navratovy kod 0 i kdyz zadny soubor nesedi (vypise to),
1 pri chybe. Python jen pri sestaveni, v LuxOS se nespousti.
"""
import fnmatch
import gzip
import hashlib
import io
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile


def zstd_read(path):
    return subprocess.run(["zstd", "-q", "-d", "-c", path], check=True, capture_output=True).stdout


def zstd_write(data, path):
    # stejne jako makepkg (COMPRESSZST=(zstd -c -T0 --ultra -20 -)) by bylo pomale; -19 staci
    subprocess.run(["zstd", "-q", "-T0", "-19", "-c", "-o", path, "-f", "-"], input=data, check=True)


def update_mtree(raw, changed):
    """raw = gzip .MTREE; changed = {cesta: bytes} -> novy gzip .MTREE."""
    text = gzip.decompress(raw).decode()
    out = []
    for line in text.splitlines():
        name = line.split(" ", 1)[0]
        path = name[2:] if name.startswith("./") else name
        if path in changed:
            data = changed[path]
            line = re.sub(r"\bsize=\d+", f"size={len(data)}", line)
            line = re.sub(r"\bmd5digest=[0-9a-f]+", f"md5digest={hashlib.md5(data).hexdigest()}", line)
            line = re.sub(r"\bsha256digest=[0-9a-f]+", f"sha256digest={hashlib.sha256(data).hexdigest()}", line)
            if f"sha256digest={hashlib.sha256(data).hexdigest()}" not in line:
                raise SystemExit(f"sb_repack: .MTREE entry of {path} has no sha256digest")
        out.append(line)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as g:
        g.write(("\n".join(out) + "\n").encode())
    return buf.getvalue()


def update_pkginfo(raw, delta):
    text = raw.decode()
    m = re.search(r"^size = (\d+)$", text, re.M)
    if not m:
        return raw
    return text.replace(m.group(0), f"size = {int(m.group(1)) + delta}", 1).encode()


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    pkg, signer, patterns = sys.argv[1], sys.argv[2], sys.argv[3:]
    data = zstd_read(pkg)
    src = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
    members = src.getmembers()
    targets = [m for m in members if m.isfile() and any(fnmatch.fnmatchcase(m.name, p) for p in patterns)]
    if not targets:
        print(f"{os.path.basename(pkg)}: nothing to sign")
        return 0
    changed = {}
    with tempfile.TemporaryDirectory(prefix="sb-repack.") as tmp:
        for i, m in enumerate(targets):
            f = os.path.join(tmp, f"{i}.efi")
            orig = src.extractfile(m).read()
            with open(f, "wb") as out:
                out.write(orig)
            subprocess.run(shlex.split(signer) + [f], check=True)
            with open(f, "rb") as fh:
                new = fh.read()
            if new != orig:
                changed[m.name] = new
    if not changed:
        # uz podepsane - balik ani jeho podpis GPG se nemeni
        print(f"{os.path.basename(pkg)}: already signed")
        return 0
    targets = [m for m in targets if m.name in changed]
    delta = sum(len(changed[m.name]) - m.size for m in targets)
    # .PKGINFO (velikost po instalaci) je v .MTREE taky - nejdriv ji, pak .MTREE se vsemi zmenami
    info = next((m for m in members if m.name == ".PKGINFO"), None)
    if info is not None:
        new_info = update_pkginfo(src.extractfile(info).read(), delta)
        mtree_changes = dict(changed, **{".PKGINFO": new_info})
    else:
        new_info, mtree_changes = None, changed

    buf = io.BytesIO()
    # format jako makepkg (bsdtar: pax s rozsirenymi hlavickami) - tarfile zachova typy, cas i vlastnika
    dst = tarfile.open(fileobj=buf, mode="w:", format=tarfile.PAX_FORMAT)
    for m in members:
        if m.name in changed:
            body = changed[m.name]
        elif m.name == ".MTREE":
            body = update_mtree(src.extractfile(m).read(), mtree_changes)
        elif m.name == ".PKGINFO":
            body = new_info
        elif m.isfile():
            body = src.extractfile(m).read()
        else:
            dst.addfile(m)
            continue
        m.size = len(body)
        dst.addfile(m, io.BytesIO(body))
    dst.close()

    tmp_pkg = pkg + ".sb-new"
    zstd_write(buf.getvalue(), tmp_pkg)
    os.replace(tmp_pkg, pkg)
    if os.path.exists(pkg + ".sig"):
        os.unlink(pkg + ".sig")
    for name in changed:
        print(f"{os.path.basename(pkg)}: signed {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
