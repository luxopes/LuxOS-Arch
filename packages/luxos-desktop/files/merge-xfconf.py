#!/usr/bin/env python3
"""LuxOS - slouci vychozi xfconf kanaly Xfce s nastavenim LuxOS.

xfconf soubory se neslucuji (soubor s vyssi prioritou nahradi cely kanal),
proto se pri sestaveni baliku kazdy kanal LuxOS hloubkove slouci s vychozim
souborem Xfce (hodnoty LuxOS maji prednost).

U klavesovych zkratek se vychozi zkratky Xfce zkopiruji do "custom",
protoze s override=true Xfce pouziva jen "custom".

Pouziti: merge-xfconf.py <adresar-xfce> <adresar-luxos> <vystupni-adresar>
"""
import copy
import os
import sys
import xml.etree.ElementTree as ET


def child(node, name):
    for c in node.findall("property"):
        if c.get("name") == name:
            return c
    return None


def merge(base, over):
    """Slouci 'over' do 'base' (podle nazvu vlastnosti, rekurzivne)."""
    for k, v in over.attrib.items():
        base.set(k, v)
    if over.findall("value"):          # pole se nahrazuje cele
        for v in base.findall("value"):
            base.remove(v)
        for i, v in enumerate(over.findall("value")):
            base.insert(i, copy.deepcopy(v))
    for p in over.findall("property"):
        b = child(base, p.get("name"))
        if b is None:
            base.append(copy.deepcopy(p))
        else:
            merge(b, p)


def shortcuts(root):
    for section in ("commands", "xfwm4"):
        sec = child(root, section)
        if sec is None:
            continue
        default, custom = child(sec, "default"), child(sec, "custom")
        if default is None or custom is None:
            continue
        ours = {p.get("name"): p for p in custom.findall("property")}
        for p in default.findall("property"):
            if p.get("name") not in ours:
                custom.append(copy.deepcopy(p))


xfce_dir, luxos_dir, out_dir = sys.argv[1:4]
os.makedirs(out_dir, exist_ok=True)
for name in sorted(os.listdir(luxos_dir)):
    if not name.endswith(".xml"):
        continue
    ours = ET.parse(os.path.join(luxos_dir, name)).getroot()
    upstream_path = os.path.join(xfce_dir, name)
    if os.path.exists(upstream_path):
        root = ET.parse(upstream_path).getroot()
        merge(root, ours)
    else:
        root = ours
    if name == "xfce4-keyboard-shortcuts.xml":
        shortcuts(root)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(os.path.join(out_dir, name), encoding="UTF-8", xml_declaration=True)
    print(f"  {name}: {'merged' if os.path.exists(upstream_path) else 'luxos only'}")
