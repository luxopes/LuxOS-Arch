#!/usr/bin/env python3
"""Navrat dialog s heslem -> setric (Esc): je cela obrazovka hned zase setric? back-to-saver.py RUNDIR [LIMIT_MS]

Cte diffs.log z diffcap (podil bodu mimo hodiny, ktere se lisi od posledniho snimku setrice pred
probuzenim), events.log (cas Esc) a saver.log xfce4-screensaver --debug (kdy dialog skoncil - "Dialog
finished"; dialog po Esc jeste ~0,4 s animuje do klidu). Selze, kdyz vic nez LIMIT_MS (vychozi 120 ms,
~2 snimky setrice) po skonceni dialogu jeste nektery snimek ukazuje zbytky dialogu (rozdil >= 2 %),
nebo kdyz dialog vubec nebyl videt (test by nic neoveril)."""
import datetime
import os
import re
import sys

args = [a for a in sys.argv[1:] if a != "--same-look"]
# --same-look: setric vypada jako dialog v klidu (styl desktop) - nevyzadovat, ze byl dialog videt
same_look = "--same-look" in sys.argv
run = args[0]
limit = int(args[1]) if len(args) > 1 else 120
rows, start = [], 0.0
with open(os.path.join(run, "diffs.log")) as f:
    for line in f:
        if line.startswith("# start"):
            start = float(line.split()[2])
        else:
            t, fr = line.split()
            rows.append((int(t), float(fr)))
ev = {}
with open(os.path.join(run, "events.log")) as f:
    for line in f:
        ts, name = line.split(None, 1)
        ev[name.strip()] = int((float(ts) - start) * 1000)
esc = ev.get("escape")
if esc is None or not rows:
    sys.exit("no escape event / no frames")
# konec dialogu: cas z ladiciho vypisu (mistni cas) prevedeny na ms od zacatku snimani
done = None
day = datetime.datetime.fromtimestamp(start)
with open(os.path.join(run, "saver.log"), errors="replace") as f:
    for line in f:
        m = re.search(r"\((\d\d):(\d\d):(\d\d)\.(\d\d\d)\):\s+Dialog finished", line)
        if m:
            h, mi, s, ms = (int(v) for v in m.groups())
            t = day.replace(hour=h, minute=mi, second=s, microsecond=ms * 1000).timestamp()
            ms_rel = int((t - start) * 1000)
            if ms_rel > esc - 50:
                done = ms_rel
                break
if done is None:
    sys.exit("dialog did not finish after Esc")
dialog = max((fr for t, fr in rows if ev.get("wake", 0) < t < esc), default=0.0)
after = [(t - done, fr) for t, fr in rows if t > done]
late = [(dt, fr) for dt, fr in after if dt > limit and fr >= 0.02]
clean_at = next((dt for i, (dt, fr) in enumerate(after) if all(f < 0.02 for _d, f in after[i:])), None)
print(f"dialog differs from the saver by {dialog:.1%}; dialog finished {done - esc} ms after Esc; whole screen "
      f"is the saver again {clean_at if clean_at is not None else 'never'} ms after that; {len(late)} frames "
      f"later than {limit} ms still show the dialog (worst {max((f for _d, f in late), default=0):.1%})")
sys.exit(0 if (dialog >= 0.05 or same_look) and not late and clean_at is not None else 1)
