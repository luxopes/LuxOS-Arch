#!/usr/bin/env python3
"""Timeline of a session-sim run: analyze.py RUNDIR  -> exit 1 if any black frame after the greeter appeared."""
import os
import sys

run = sys.argv[1]
frames, start = [], 0.0
with open(os.path.join(run, "frames.log")) as f:
    for line in f:
        if line.startswith("# start"):
            start = float(line.split()[2])
            continue
        t, fr, luma = line.split()
        frames.append((int(t), float(fr), float(luma)))
events = []
if os.path.exists(os.path.join(run, "events.log")):
    with open(os.path.join(run, "events.log")) as f:
        for line in f:
            ts, name = line.split(None, 1)
            events.append((int((float(ts) - start) * 1000), name.strip()))
first = next((i for i, fr in enumerate(frames) if fr[1] < 0.98), len(frames))
frames = frames[first:]
timeline = [(t, "event", n) for t, n in events]
prev = None
black = dark = 0
for t, fr, luma in frames:
    cls = "BLACK" if fr >= 0.98 else ("dark" if fr >= 0.25 else "ok")
    black += cls == "BLACK"
    dark += cls == "dark"
    key = (cls, int(luma // 15))
    if key != prev:
        timeline.append((t, "frame", f"{cls:5s} black={fr:.3f} luma={luma:.0f}"))
        prev = key
for t, kind, txt in sorted(timeline):
    print(f"{t:6d} ms  {'>>' if kind == 'event' else '  '} {txt}")
print(f"frames after greeter: {len(frames)}, fully black: {black}, mostly black (>=25%): {dark}")
sys.exit(1 if black or dark else 0)
