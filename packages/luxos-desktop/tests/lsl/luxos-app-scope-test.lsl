# Spousteni aplikaci ze sluzby shellu (test_luxos_app_scope.py): luxos_apps.launch, launch_uri a luxos_glib.spawn_app
# po dvojicich argumentu, kazda vypise "ok" nebo "fail".
#   luxos-app-scope-test launch SOUBOR.desktop | uri URI | spawn PROGRAM ...
load luxos_glib as lglib
load luxos_apps as apps

index = 1
while index + 1 < arg_count():
    what = arg(index)
    value = arg(index + 1)
    if what == "launch":
        ok = apps.launch(apps.find(value))
    elif what == "uri":
        ok = apps.launch_uri(value)
    else:
        ok = lglib.spawn_app([value]) != 0
    end
    print "ok" if ok else "fail"
    index += 2
end
