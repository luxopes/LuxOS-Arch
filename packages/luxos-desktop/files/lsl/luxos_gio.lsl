# lsl: internal-abi
# lsl: link libgio-2.0.so.0 libgobject-2.0.so.0 libglib-2.0.so.0
# LuxOS - doplnky k modulu gio LSL 0.10.6 (D-Bus) pro luxos-hub; programy nacitaji `load luxos_gio, gio as gio`.
#   call_async(bus, name, path, iface, method, values, signature, ms, f, data)   f(data, hodnoty odpovedi nebo None, chyba)
#   subscribe_data(bus, sender, iface, member, path, arg0, flags, f, data)        f(data, sender, path, iface, signal, hodnoty);
#                                                                                 arg0 a priznaky (SIGNAL_MATCH_ARG0_NAMESPACE pro MPRIS)
#   watch_name_data(bus, name, appeared, vanished, data)                          appeared(data, name, owner), vanished(data, name)
#   name_has_owner(bus, name, ms)                                                 NameHasOwner
#   inhibit_fd(bus, what, who, why, mode)                                         logind Inhibit -> fd (-1 pri chybe)
load glib, gio
load luxos_glib

SIGNAL_NONE = 0
SIGNAL_MATCH_ARG0_NAMESPACE = 2

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function cstr(text):
    unsafe:
        return __lsl_address(text) + 16
    end
end

function optional_cstr(text):
    if len(text) == 0:
        return 0
    end
    return cstr(text)
end

# ---- asynchronni volani ------------------------------------------------------------------------------------

function call_async(bus, name, path, interface, method, values, signature, timeout, handler, bound):
    unsafe:
        parameters = 0
        if len(signature) > 0:
            parameters = __lsl_qbe_call1(__lsl_symbol("g_variant_ref_sink"), ptr(gio.value_to_variant(values, signature)))
        end
        state = [handler, bound, 0]
        tracked = luxos_glib.track(async_trampoline, 2, state)
        state[2] = tracked[1]
        call __lsl_qbe_call12(__lsl_symbol("g_dbus_connection_call"), ptr(bus), cstr(name), cstr(path), cstr(interface), cstr(method), parameters, 0, 0, ptr(timeout), 0, __lsl_symbol("lsl_arch_callback_u3"), ptr(tracked[0]))
        if parameters != 0:
            call __lsl_qbe_call1(__lsl_symbol("g_variant_unref"), parameters)
        end
        return 0
    end
end

function async_trampoline(state, source, result):
    unsafe:
        cell = gio.error_cell()
        reply = __lsl_qbe_call3(__lsl_symbol("g_dbus_connection_call_finish"), ptr(source), ptr(result), glib.array_data(cell))
        handler = state[0]
        call luxos_glib.release(state[2])
        if reply == 0:
            message = ""
            error = __lsl_qbe_load64(glib.array_data(cell))
            if error != 0:
                message = glib.from_c(__lsl_qbe_load64(error + 8))
                call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
            end
            call handler(state[1], None, message)
            return 0
        end
        value = gio.variant_to_value(reply)
        call __lsl_qbe_call1(__lsl_symbol("g_variant_unref"), reply)
        call handler(state[1], value, "")
        return 0
    end
end

# ---- signaly s vazanou hodnotou, arg0 a priznaky -------------------------------------------------------------

function subscribe_data(bus, sender, interface, member, path, arg0, flags, handler, bound):
    tracked = luxos_glib.track(signal_trampoline, 6, [handler, bound])
    unsafe:
        return __lsl_qbe_call10(__lsl_symbol("g_dbus_connection_signal_subscribe"), ptr(bus), optional_cstr(sender), optional_cstr(interface), optional_cstr(member), optional_cstr(path), optional_cstr(arg0), ptr(flags), __lsl_symbol("lsl_arch_callback_u7"), ptr(tracked[0]), 0)
    end
end

function signal_trampoline(pair, connection, sender, path, interface, signal, params):
    handler = pair[0]
    call handler(pair[1], glib.from_c(sender), glib.from_c(path), glib.from_c(interface), glib.from_c(signal), gio.variant_to_value(params))
    return 0
end

# Sledovani jmena s vazanou hodnotou: appeared(data, name, owner), vanished(data, name)
function watch_name_data(bus, name, appeared, vanished, bound):
    call subscribe_data(bus, "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged", "/org/freedesktop/DBus", name, SIGNAL_NONE, vanished_trampoline, [vanished, bound])
    tracked = luxos_glib.track(appeared_trampoline, 3, [appeared, bound])
    unsafe:
        return __lsl_qbe_call7(__lsl_symbol("g_bus_watch_name_on_connection"), ptr(bus), cstr(name), 0, __lsl_symbol("lsl_arch_callback_u4"), 0, ptr(tracked[0]), 0)
    end
end

function appeared_trampoline(pair, connection, name, owner):
    handler = pair[0]
    call handler(pair[1], glib.from_c(name), glib.from_c(owner))
    return 0
end

function vanished_trampoline(pair, sender, path, interface, signal, values):
    if len(values) == 3 and values[2] == "":
        handler = pair[0]
        call handler(pair[1], values[0])
    end
    return 0
end

function name_has_owner(bus, name, timeout):
    reply = gio.call_values(bus, "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner", [name], "(s)", timeout)
    return reply[0] == True
end

# ---- logind Inhibit: popisovac souboru z odpovedi (g_dbus_connection_call_with_unix_fd_list_sync ma 13 argumentu) ----

function inhibit_fd(bus, what, who, why, mode):
    unsafe:
        message = __lsl_qbe_call4(__lsl_symbol("g_dbus_message_new_method_call"), cstr("org.freedesktop.login1"), cstr("/org/freedesktop/login1"), cstr("org.freedesktop.login1.Manager"), cstr("Inhibit"))
        body = gio.value_to_variant([what, who, why, mode], "(ssss)")
        call __lsl_qbe_call2(__lsl_symbol("g_dbus_message_set_body"), message, ptr(body))
        cell = gio.error_cell()
        reply = __lsl_qbe_call7(__lsl_symbol("g_dbus_connection_send_message_with_reply_sync"), ptr(bus), message, 0, 5000, 0, 0, glib.array_data(cell))
        call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), message)
        error = __lsl_qbe_load64(glib.array_data(cell))
        if error != 0:
            call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
            return -1
        end
        result = -1
        # G_DBUS_MESSAGE_TYPE_METHOD_RETURN = 2
        if __lsl_qbe_call1(__lsl_symbol("g_dbus_message_get_message_type"), reply) == 2:
            fds = __lsl_qbe_call1(__lsl_symbol("g_dbus_message_get_unix_fd_list"), reply)
            if fds != 0:
                result = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("g_unix_fd_list_get"), fds, 0, 0))
            end
        end
        call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), reply)
        return result
    end
end
