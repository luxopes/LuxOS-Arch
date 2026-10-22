#!/usr/bin/env python3
"""LuxOS - vygeneruje nvidia-legacy.ids z README ovladace NVIDIA (Appendix A, supportedchips.html).

Pouziti (stazeny soubor se jen cte, nic se nespousti):
  curl -o supportedchips.html https://download.nvidia.com/XFree86/Linux-x86_64/<VERZE>/README/supportedchips.html
  python3 -I tools/gen-nvidia-legacy.py supportedchips.html <VERZE> > nvidia-legacy.ids

Do souboru jdou jen karty starsi nez Turing, ktere ma posledni ovladac na legacy vetvi
580.xx (Maxwell, Pascal, Volta) nebo 470.xx (Kepler). Aktualni ovladac (sekce "Current")
podporuje jen Turing a novejsi = PCI ID od 0x1e00 (luxos-hwdetect to overuje pravidlem).
"""
import html
import re
import sys

BRANCHES = ("580", "470")


def parse(text):
    """{pci_id: (vetev, nazev)} - prvni vyskyt ID (dalsi radky se lisi jen subsystemem)."""
    secs = re.split(r'<a name="(Current|legacy_[0-9.]+xx)" id="[^"]*"></a>', text)
    out = {}
    for i in range(1, len(secs), 2):
        name = secs[i]
        body = secs[i + 1].split("</table>")[0]
        branch = "open" if name == "Current" else name.split("_")[1].split(".")[0]
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
            cells = [" ".join(html.unescape(re.sub("<[^>]+>", "", c)).split())
                     for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            if len(cells) >= 2 and re.match(r"^[0-9A-F]{4}\b", cells[1]):
                out.setdefault(cells[1][:4].lower(), (branch, cells[0]))
    return out


def main(argv):
    if len(argv) != 3:
        sys.exit(__doc__.strip())
    with open(argv[1], encoding="latin-1") as f:
        ids = parse(f.read())
    current = [d for d, (b, _n) in ids.items() if b == "open"]
    if not current or min(int(d, 16) for d in current) < 0x1e00:
        sys.exit("unexpected: the current driver supports a GPU older than Turing (0x1e00) - check luxos-hwdetect")
    print(f"# LuxOS - PCI ID karet NVIDIA na legacy vetvich (vygenerovano z README ovladace {argv[2]},")
    print("# https://download.nvidia.com/XFree86/Linux-x86_64/%s/README/supportedchips.html)" % argv[2])
    print("# Format: <pci id> <vetev> <nazev>; Turing a novejsi (0x1e00+) maji aktualni ovladac nvidia-open.")
    for d in sorted(ids):
        branch, name = ids[d]
        if branch in BRANCHES:
            print(f"{d} {branch} {name}")


if __name__ == "__main__":
    main(sys.argv)
