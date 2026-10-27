#!/usr/bin/env python3
"""LuxOS - automaticke prepnuti zvukoveho vystupu na nove pripojene zarizeni (spousti luxos-hub).

luxos-hub sleduje `pactl subscribe` a pri zmene karty, serveru nebo pridani/odebrani vystupu spusti
`luxos_audio_switch.py check`. Ten porovna stav karet s minulym (soubor v $XDG_RUNTIME_DIR) a:

  * HDMI / DisplayPort (zvuk monitoru): port na karte zmeni dostupnost "not available" -> "available".
    Kdyz aktivni profil karty port neobsahuje (typicky analogovy profil, kde HDMI vystup vubec neni),
    prepne kartu na nejlepsi dostupny profil s timto portem (pokud mozno se stejnym vstupem, napr.
    output:hdmi-stereo+input:analog-stereo). Pak vystup s portem nastavi jako vychozi a presune na
    nej prehravane zvuky. pipewire-pulse (module-switch-on-connect) ani WirePlumber tohle samy
    neudelaji: analogovy profil ma vyssi prioritu a novy vystup bez zmeny profilu nevznikne.
  * USB / Bluetooth: nova karta s vystupem -> jeji vystup je vychozi (jako module-switch-on-connect).
  * Odpojeni: port neni dostupny / karta zmizela -> vrati predchozi profil a vychozi vystup.

Nebojuje s uzivatelem: kdyz si po automatickem prepnuti vybere jiny vystup (nebo jiny profil karty),
po odpojeni se nic nevraci, a dalsi prepnuti nastane az pri dalsim pripojeni. Pri prvnim spusteni
v relaci (prihlaseni) se jen ulozi vychozi stav - co uz pripojene je, se neprepina.

  luxos_audio_switch.py check     jedna kontrola (LUXOS_PACTL prepise program pactl - testy)
"""
import json
import os
import subprocess
import sys
import time

PACTL = os.environ.get("LUXOS_PACTL") or "pactl"
ENV = dict(os.environ, LC_ALL="C")      # pactl preklada "available" apod.
WAIT_SINK = float(os.environ.get("LUXOS_AUDIO_WAIT", "3"))


def state_path():
    run = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(run, "luxos-audio-switch.json")


def log(msg):
    sys.stderr.write("luxos-audio-switch: %s\n" % msg)


def pactl(*args):
    try:
        r = subprocess.run([PACTL, *args], env=ENV, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        log("pactl %s: %s" % (" ".join(args), e))
        return None
    if r.returncode != 0:
        log("pactl %s: %s" % (" ".join(args), r.stderr.strip()))
        return None
    return r.stdout


def pactl_json(*args):
    out = pactl("-f", "json", *args)
    try:
        return json.loads(out) if out else None
    except ValueError:
        return None


def is_output(name):
    n = name.lower()
    return "output" in n or n.startswith("[out]")


def is_display_port(name, port):
    text = " ".join((name, port.get("type") or "", port.get("description") or "")).lower()
    return "hdmi" in text or "displayport" in text


def card_bus(card):
    props = card.get("properties") or {}
    bus = props.get("device.bus") or ""
    if not bus and card.get("name", "").startswith("bluez_card."):
        bus = "bluetooth"
    return bus


def card_sinks(card, sinks):
    """Vystupy (sinky) karty: device.id == object.id karty, jinak podle jmena (alsa_card.X -> alsa_output.X.*)."""
    obj = str((card.get("properties") or {}).get("object.id") or "")
    key = card.get("name", "").split(".", 1)[-1]
    out = []
    for s in sinks:
        dev = str((s.get("properties") or {}).get("device.id") or "")
        if obj and dev:
            if dev == obj:
                out.append(s)
        elif key and s.get("name", "").split(".", 1)[-1].startswith(key):
            out.append(s)
    return out


def sink_with_port(card, sinks, port):
    for s in card_sinks(card, sinks):
        if any(p.get("name") == port for p in s.get("ports") or []):
            return s
    return None


def snapshot(cards):
    """{karta: {"bus":..., "ports": {port HDMI/DP: dostupnost}}}"""
    out = {}
    for c in cards:
        ports = {name: p.get("availability") or "" for name, p in (c.get("ports") or {}).items()
                 if is_output(name) and is_display_port(name, p)}
        out[c["name"]] = {"bus": card_bus(c), "ports": ports}
    return out


def best_profile(card, port):
    """Nejlepsi dostupny profil s portem; prednost ma profil se stejnym vstupem jako ten aktivni."""
    profiles = card.get("profiles") or {}
    active = card.get("active_profile") or ""
    inputs = {part for part in active.split("+") if part.startswith("input:")}
    best, key = None, None
    for name in (card.get("ports") or {}).get(port, {}).get("profiles") or []:
        info = profiles.get(name) or {}
        if not info.get("available", True) or int(info.get("sinks", 1)) < 1:
            continue
        parts = set(name.split("+"))
        k = (bool(inputs) and inputs <= parts, int(info.get("priority", 0)))
        if key is None or k > key:
            best, key = name, k
    return best


def wait_sink(card_name, finder):
    """Po zmene profilu chvili pockat na novy vystup (vznikne asynchronne)."""
    deadline = time.monotonic() + WAIT_SINK
    while True:
        cards = pactl_json("list", "cards") or []
        sinks = pactl_json("list", "sinks") or []
        card = next((c for c in cards if c.get("name") == card_name), None)
        sink = finder(card, sinks) if card else None
        if sink or time.monotonic() >= deadline:
            return sink
        time.sleep(0.2)


def make_default(sink_name):
    pactl("set-default-sink", sink_name)
    # prehravane zvuky na novy vystup (i ty, kterym nekdo vystup nastavil rucne)
    for line in (pactl("list", "short", "sink-inputs") or "").splitlines():
        idx = line.split("\t", 1)[0].strip()
        if idx.isdigit():
            pactl("move-sink-input", idx, sink_name)


def default_sink():
    info = pactl_json("info") or {}
    return info.get("default_sink_name") or ""


def switch_to_port(card, port, sinks, current):
    """Prepnout na HDMI/DP port karty; vraci zaznam pro pozdejsi navrat nebo None."""
    prev_profile = None
    active = card.get("active_profile") or ""
    sink = sink_with_port(card, sinks, port)
    if sink is None:
        # aktivni profil port nema (analogovy profil bez HDMI vystupu)
        profile = best_profile(card, port)
        if profile is None:
            log("%s: no available profile for %s" % (card["name"], port))
            return None
        if profile != active:
            if pactl("set-card-profile", card["name"], profile) is None:
                return None
            prev_profile = active
            active = profile
        sink = wait_sink(card["name"], lambda c, s: sink_with_port(c, s, port))
    if sink is None:
        log("%s: no output for %s" % (card["name"], port))
        return None
    if sink.get("active_port") != port:
        pactl("set-sink-port", sink["name"], port)
    make_default(sink["name"])
    log("%s %s -> default output %s" % (card["name"], port, sink["name"]))
    return {"card": card["name"], "port": port, "sink": sink["name"], "profile": active,
            "prev_profile": prev_profile, "prev_sink": current, "manual": False}


def switch_to_card(card, current):
    sink = wait_sink(card["name"], lambda c, s: (card_sinks(c, s) or [None])[0])
    if sink is None:
        return None
    make_default(sink["name"])
    log("%s -> default output %s" % (card["name"], sink["name"]))
    return {"card": card["name"], "port": None, "sink": sink["name"], "profile": card.get("active_profile"),
            "prev_profile": None, "prev_sink": current, "manual": False}


def restore(auto, cards, sinks):
    card = next((c for c in cards if c.get("name") == auto["card"]), None)
    if auto.get("prev_profile") and card and card.get("active_profile") == auto.get("profile"):
        pactl("set-card-profile", card["name"], auto["prev_profile"])
        wait_sink(card["name"], lambda c, s: next((x for x in s if x.get("name") == auto["prev_sink"]), None))
        sinks = pactl_json("list", "sinks") or sinks
    prev = auto.get("prev_sink")
    if prev and any(s.get("name") == prev for s in sinks):
        make_default(prev)
        log("restored default output %s" % prev)


def check():
    cards = pactl_json("list", "cards")
    sinks = pactl_json("list", "sinks")
    if cards is None or sinks is None:
        return 1
    current = default_sink()
    now = snapshot(cards)
    try:
        with open(state_path(), encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = None
    if not isinstance(state, dict) or not isinstance(state.get("cards"), dict):
        # prvni beh v relaci: jen zapamatovat, co uz pripojene je
        save({"cards": now, "auto": None, "default": current})
        return 0
    before = state["cards"]
    auto = state.get("auto")

    # uzivatel si mezitim vybral jiny vystup: jeho volba plati, nic se nevrati
    if auto and current and current != auto.get("sink"):
        auto["manual"] = True

    # odpojeni zarizeni, na ktere se automaticky prepnulo
    if auto:
        card = now.get(auto["card"])
        gone = card is None or (auto.get("port") and card["ports"].get(auto["port"]) == "not available")
        if gone:
            if not auto.get("manual"):
                restore(auto, cards, sinks)
            auto = None
            current = default_sink()

    # nove pripojene: HDMI/DP port na existujici karte, nebo nova karta USB/Bluetooth
    by_name = {c["name"]: c for c in cards}
    target = None
    for name, info in now.items():
        old = before.get(name)
        if old is None:
            if info["bus"] in ("usb", "bluetooth") and target is None:
                target = ("card", by_name[name], None)
            continue
        for port, avail in info["ports"].items():
            if avail == "available" and old["ports"].get(port) == "not available" and target is None:
                target = ("port", by_name[name], port)
    if target:
        kind, card, port = target
        new = switch_to_port(card, port, sinks, current) if kind == "port" else switch_to_card(card, current)
        if new:
            # navrat na puvodni vystup jen z prvniho automatickeho prepnuti
            if auto and not auto.get("manual"):
                new["prev_sink"] = auto.get("prev_sink") or new["prev_sink"]
            auto = new
        current = default_sink()
        cards = pactl_json("list", "cards") or cards
        now = snapshot(cards)

    save({"cards": now, "auto": auto, "default": current})
    return 0


def save(state):
    path = state_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, path)
    except OSError as e:
        log("state: %s" % e)


def main(argv):
    if len(argv) == 2 and argv[1] == "check":
        return check()
    sys.stderr.write("usage: luxos_audio_switch.py check  (used by luxos-hub)\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
