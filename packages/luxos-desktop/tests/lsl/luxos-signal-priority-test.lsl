# Test luxos_glib.unix_signal_add: programy s `load luxos_glib, glib as glib` dostanou zdroj signalu
# s prioritou DEFAULT jako udalosti GDK (ne HIGH ze standardni knihovny), a obsluha signalu probehne.
# Vypise "priority N" a "handled".
load luxos_glib, glib as glib

SIGUSR1 = 10

function on_usr1():
    print "handled"
    call glib.main_quit()
    return False
end

id = glib.unix_signal_add(SIGUSR1, on_usr1)
unsafe:
    source = __lsl_qbe_call2(__lsl_symbol("g_main_context_find_source_by_id"), 0, __lsl_unbox_int(id))
    print "priority", __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("g_source_get_priority"), source))
    call __lsl_qbe_call2(__lsl_symbol("kill"), __lsl_qbe_call0(__lsl_symbol("getpid")), SIGUSR1)
end
call glib.timeout_add(5000, glib.main_quit)
call glib.main()
