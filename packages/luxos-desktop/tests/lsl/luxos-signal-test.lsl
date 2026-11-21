# Test connect_data z luxos_glib: zaznam obsluhy signalu se uvolni se zanikem objektu (GCancellable
# "cancelled"), takze dlouho bezici proces (luxos-notify: obsluhy kazdeho okenka) neroste.
# Vypise "fired N" a pocet zivych zaznamu pred a po 1000 objektech. Totez pro zdroje hlavni smycky
# (timeout_add_data): 1000 skoncenych vracenim False a 1000 odebranych glib.source_remove -> "sources N A B".
load luxos_glib
load glib

fired = [0]

function on_cancelled(count, obj):
    count[0] = count[0] + 1
    return 0
end

function alive():
    return glib.record_count() + len(luxos_glib.live)
end

function round():
    unsafe:
        c = __lsl_qbe_call0(__lsl_symbol("g_cancellable_new"))
        call luxos_glib.connect_data(c, "cancelled", 0, on_cancelled, fired)
        call __lsl_qbe_call1(__lsl_symbol("g_cancellable_cancel"), c)
        call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), c)
    end
    return 0
end

call round()
before = alive()
for i in range(1000):
    call round()
end
print "fired", fired[0]
print "alive", before, alive()

ticks = [0]

function on_tick(count):
    count[0] = count[0] + 1
    return False
end

function on_never(unused):
    return True
end

ids = []
for i in range(1000):
    call luxos_glib.timeout_add_data(0, on_tick, ticks)
    ids.append(luxos_glib.timeout_add_data(60000, on_never, 0))
end
for id in ids:
    call glib.source_remove(id)
end
while ticks[0] < 1000:
    call glib.pump()
end
print "sources", ticks[0], before, alive()
