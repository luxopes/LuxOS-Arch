"""Firewall (Nastaveni > Firewall): zapnuty firewall, automaticka pravidla, vlastni vyjimky a nedavno
zablokovany program. Stav dava falesny `luxos-firewall` (LUXOS_FIREWALL_CLI) - skutecny firewall se
nikdy necte ani nemeni; LUXOS_FIREWALL_RUN_DIR miri do docasne slozky (zadne sledovani /run)."""
import json
import os

STATUS = {
    "enable": True, "active": True, "trust_tailscale": False,
    "rules": [
        {"name": "LuxDrop", "port": "47923-47924", "proto": "tcp", "from": "lan"},
        {"name": "LuxDrop", "port": "53317", "proto": "tcp", "from": "lan"},
        {"name": "LuxDrop", "port": "53317", "proto": "udp", "from": "lan"},
        {"name": "Steam", "port": "27031-27036", "proto": "udp", "from": "lan"},
        {"name": "Steam", "port": "27036-27037", "proto": "tcp", "from": "lan"},
        {"name": "Printer sharing", "port": "631", "proto": "tcp", "from": "lan"},
        {"name": "Tailscale", "port": "41641", "proto": "udp", "from": "any"},
    ],
    "allow": [
        {"port": "8080", "proto": "tcp", "from": "lan", "app": "Web development server"},
        {"port": "25565", "proto": "tcp", "from": "any", "app": "Minecraft server"},
    ],
    "blocked": [
        {"port": 5432, "proto": "tcp", "app": "PostgreSQL", "src": "192.168.1.24"},
    ],
}


def launch_demo(s):
    """Spusti Firewall s falesnym luxos-firewall (i pro jine postupy, napr. Monitor systemu)."""
    fake = os.path.join(s.tmp, "fake-luxos-firewall")
    data = os.path.join(s.tmp, "firewall-status.json")
    with open(data, "w", encoding="utf-8") as f:
        json.dump(STATUS, f)
    # jen "status --json"; cokoli jineho (allow/deny/on/off) nic nedela
    with open(fake, "w", encoding="utf-8") as f:
        f.write('#!/bin/sh\n[ "$1" = status ] && exec cat "%s"\nexit 0\n' % data)
    os.chmod(fake, 0o755)
    run_dir = os.path.join(s.tmp, "run-firewall")
    os.makedirs(run_dir, exist_ok=True)
    exe = s.lslc("luxos-desktop/files/lsl/luxos-firewall-settings.lsl")
    return s.launch([exe], env={"LUXOS_FIREWALL_CLI": fake, "LUXOS_FIREWALL_RUN_DIR": run_dir})


def shots(s):
    launch_demo(s)
    win = s.window(cls="luxos-firewall-settings", size=(660, 734))
    s.capture("1", win)
    # konec stranky: vlastni vyjimky, Tailscale a nedavno zablokovany program
    for _ in range(12):
        s.click(330, 400, win, button=5, delay=0.1)
    s.sleep(0.5)
    s.capture("2", win)
