# Test luxos_power_model.lsl bez displeje a sbernice (test_luxos_power_app.py): radky "ok NAZEV" / "FAIL NAZEV ..."
load luxos_power_model as m

failures = 0

function expect(name, got, want):
    global failures
    if got == want:
        print "ok " + name
    else:
        failures += 1
        print "FAIL " + name + " got " + String(got) + " want " + String(want)
    end
    return 0
end

function values(points):
    return [p[1] for p in points if p != None]
end

# dve baterie: stav, procenta a cas za obe (DisplayDevice), kapacity soucet, Capacity prvni baterie pryc
bat0 = {"Type": 2, "PowerSupply": True, "Percentage": 10.0, "State": 3, "EnergyFull": 20.0, "EnergyFullDesign": 25.0, "Capacity": 80.0}
bat1 = {"Type": 2, "PowerSupply": True, "Percentage": 90.0, "State": 2, "EnergyFull": 40.0, "EnergyFullDesign": 50.0}
disp = {"Type": 2, "Percentage": 63.3, "State": 2, "TimeToEmpty": 7200}
info = m.combine(bat0, disp, [bat0, bat1])
call expect("two-state", [info["Percentage"], info["State"], info["TimeToEmpty"]], [63.3, 2, 7200])
call expect("two-energy", [info["EnergyFull"], info["EnergyFullDesign"]], [60.0, 75.0])
call expect("two-no-capacity", "Capacity" in info, False)
# prazdna a "brzy se bude vybijet" baterie bezi na baterii, ne "Pripojeno, nenabiji se"
for st in [2, 3, 6]:
    call expect("on-battery-" + String(st), m.status_text({"State": st}).startswith("On battery"), True)
end
call expect("pending-charge", m.status_text({"State": 5}), "Plugged in, not charging")
call expect("charging-left", m.status_text({"State": 1, "TimeToFull": 3900}), "Charging · full in 1 h 5 min")
call expect("discharging-left", m.status_text({"State": 2, "TimeToEmpty": 1500}), "On battery · about 25 min left")
call expect("full", m.status_text({"State": 4}), "Fully charged")

# graf: zaznam "unknown" (0 % pri startu) neni vybiti, mezi zaznamy plati posledni hodnota
raw = [[1000, 98.0, 1], [1100, 100.0, 4], [5000, 0.0, 0], [5000, 100.0, 4]]
pts = m.clean_history(raw, "charge", {"Percentage": 100.0, "State": 4}, 9000, 7200, 0)
call expect("unknown-no-zero", 0.0 in values(pts), False)
call expect("unknown-breaks", None in pts, True)
call expect("unknown-until-now", pts[len(pts) - 1], [9000, 100.0, 4])
call expect("unknown-min", min(values(pts)) >= 98.0, True)
# zaznamy mimo poradi se seradi jako n-tice
pts = m.clean_history([[1100, 100.0, 4], [1000, 98.0, 1]], "charge", {}, 2000, 7200, 0)
call expect("sorted", pts[0], [1000, 98.0, 1])

# nabijecka, 100 % uz dva dny: posledni zaznam je starsi nez 24 h - cela cara na 100 %
now = 1000000
pts = m.clean_history([[now - 200000, 95.0, 1], [now - 127000, 100.0, 4]], "charge", {"Percentage": 100.0, "State": 4}, now, 7200, 86400)
call expect("old-first", pts[0], [now - 86400, 100.0, 4])
call expect("old-last", pts[len(pts) - 1], [now, 100.0, 4])
call expect("old-window", len([p for p in pts if p == None or p[0] < now - 86400]), 0)

raw = [[now - 90000, 50.0, 1], [now - 50000, 40.0, 1], [now - 40000, 0.0, 0], [now - 40000, 70.0, 1]]
pts = m.clean_history(raw, "charge", {"Percentage": 80.0, "State": 1}, now, 7200, 86400)
call expect("clip-first", pts[0], [now - 86400, 50.0, 1])
call expect("clip-break", None in pts, True)
call expect("clip-last", pts[len(pts) - 1], [now, 80.0, 1])

# uspani/vypnuti pri vybijeni: zadna sikma cara
pts = m.clean_history([[0, 80.0, 2], [600, 79.0, 2], [20000, 60.0, 2]], "charge", {"Percentage": 60.0, "State": 2}, 20100, 7200, 0)
call expect("gap-breaks", None in pts, True)
# spotreba bere EnergyRate
pts = m.clean_history([[0, 5.0, 2]], "rate", {"EnergyRate": 7.5, "Percentage": 50.0, "State": 2}, 100, 7200, 0)
call expect("rate-now", pts[len(pts) - 1], [100, 7.5, 2])

# upower vraci surove zaznamy jen pri points vetsim nez jejich pocet (0 = nic)
call expect("history-points", m.HISTORY_POINTS > 10000 and m.HISTORY_LOOKBACK >= 2 * 86400, True)

call expect("duration", [m.fmt_duration(0), m.fmt_duration(59), m.fmt_duration(600), m.fmt_duration(7260)], ["", "0 min", "10 min", "2 h 1 min"])
call expect("fixed", [m.fixed1(7.8), m.fixed1(52.44), m.fixed0(64.0), m.fixed0(87.6)], ["7.8", "52.4", "64", "88"])
call expect("cycles-upower", m.charge_cycles({"ChargeCycles": 12}, "/nonexistent"), 12)
call expect("cycles-none", m.charge_cycles({"ChargeCycles": -1}, "/nonexistent"), 0)
call expect("demo", [m.demo_info(False)["ChargeCycles"], m.demo_info(True)["State"], len(m.demo_history("charge", now))], [212, 4, 240])

if failures > 0:
    exit(1)
end
