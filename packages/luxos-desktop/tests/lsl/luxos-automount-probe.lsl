# Test luxos_automount.lsl (test_settings_system.py): automount jako v luxos-backdrop, ale bez plochy, proti
# falesnemu UDisks2 na soukrome systemove sbernici (DBUS_SYSTEM_BUS_ADDRESS). Vypise "ready True|False".
load glib
load luxos_sys as sys
load luxos_automount as automount

call sys.out("ready " + String(automount.start()) + "\n")
call glib.main()
