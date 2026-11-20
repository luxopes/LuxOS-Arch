# Test connect_data z luxos_glib: zaznam obsluhy signalu se uvolni se zanikem objektu (GCancellable
# "cancelled"), takze dlouho bezici proces (luxos-notify: obsluhy kazdeho okenka) neroste.
# Vypise "fired N" a pocet zivych zaznamu pred a po 1000 objektech.
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
