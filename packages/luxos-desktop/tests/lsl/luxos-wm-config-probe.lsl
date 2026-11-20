# Testy luxos_wm_config (test_luxwm_ipc.py): overrides USER DEFAULTS LUXWM_CONF | import | save GENERAL KEYS
# (JSON, null = smazat) | normalize ZKRATKA
load json
load luxos_wm_config as cfg

cmd = args[1]
if cmd == "overrides":
    result = cfg.xfce_overrides(readfile(args[2]), readfile(args[3]), cfg.parse(readfile(args[4]))["keys"])
    print json.encode({"keys": result[0], "skipped": result[1]})
elif cmd == "import":
    print cfg.import_xfce()
elif cmd == "save":
    call cfg.save(json.decode(args[2]), json.decode(args[3]))
elif cmd == "normalize":
    print cfg.normalize(args[2])
end
