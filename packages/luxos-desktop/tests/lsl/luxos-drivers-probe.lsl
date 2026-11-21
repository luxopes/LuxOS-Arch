# Test luxos_drivers_hub.lsl (test_luxos_drivers_hub.py): rozhodovani bez luxos-hub a bez sbernice.
#   luxos-drivers-probe eval SOUBOR   SOUBOR = {"devices": [...], "installed": [...] nebo null = databaze
#                                     v LUXOS_DRIVERS_ROOT, "ignored": "..."}; vypise JSON stavu, klice a upozorneni
#   luxos-drivers-probe should BOOT   True/False: kontrolovat v tomto startu pocitace
load json
load luxos_glib, glib as glib
load luxos_drivers_hub as drivers

if args[1] == "should":
    print String(drivers.should_check(args[2]))
else:
    data = json.decode(glib.read_text(args[2]))
    installed = drivers.installed_packages()
    if data.get("installed") != None:
        installed = {}
        for p in data["installed"]:
            installed[p] = True
        end
    end
    states = drivers.evaluate(data["devices"], installed)
    print json.encode({"states": [{"status": s["status"], "missing": s["missing"]} for s in states],
                       "key": drivers.notify_key(states), "notify": drivers.should_notify(states, data.get("ignored", ""))})
end
