# lsl: internal-abi
# lsl: link libglib-2.0.so.0 libcairo.so.2
# LuxOS - volani C pro zamek obrazovky (luxos-lock, luxos-lock-session), at programy samy internal-abi nepotrebuji.
#
#   protect()                          proces nejde vypsat ani ladit jinym procesem uzivatele (PR_SET_DUMPABLE 0),
#                                      bez core dumpu: v pameti muze byt rozepsane heslo
#   spawn_lines(argv, envp, f, data)   program s rourou na stdin i stdout -> [pid, stdin] nebo [] pri chybe;
#                                      f(data, radek, 0) za kazdy radek stdout, po konci procesu jednou
#                                      f(data, "", status) (status jako waitpid); envp [] = prostredi tohoto procesu
#   real_name(), user_name()
#   source_pad(cr)                     zdroj cairo za okrajem opakuje krajni pixely (zvetsena tapeta bez tmaveho lemu)
#
# Pozor (internal-abi): Int 0 je tu k nerozeznani od None, proto konec vystupu hlasi "" a ne None.
load glib
load luxos_glib as lglib

PR_SET_DUMPABLE = 4
RLIMIT_CORE = 4
# G_SPAWN_DO_NOT_REAP_CHILD 2 | G_SPAWN_CLOEXEC_PIPES 256
SPAWN_FLAGS = 258

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function protect():
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("prctl"), PR_SET_DUMPABLE, 0)
        limit = __lsl_byte_zeros(16)
        call __lsl_qbe_call2(__lsl_symbol("setrlimit"), RLIMIT_CORE, lglib.data(limit))
    end
    return 0
end

# state = [handler, data, stdout, bezi, id zaznamu cteni, id zaznamu potomka, rozepsany radek, status]
function spawn_lines(argv, envp, handler, bound):
    unsafe:
        array = glib.cstr_array(argv)
        env_data = 0
        if len(envp) > 0:
            env_array = glib.cstr_array(envp)
            env_data = glib.array_data(env_array)
        end
        cells = __lsl_byte_zeros(32)
        base = lglib.data(cells)
        ok = __lsl_qbe_call11(__lsl_symbol("g_spawn_async_with_pipes"), 0, glib.array_data(array), env_data, SPAWN_FLAGS, 0, 0, base, base + 8, base + 16, 0, base + 24)
        if ok == 0:
            error = __lsl_qbe_load64(base + 24)
            if error != 0:
                call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
            end
            return []
        end
        pid = __lsl_qbe_s32(__lsl_qbe_load32(base))
        input = __lsl_qbe_s32(__lsl_qbe_load32(base + 8))
        out = __lsl_qbe_s32(__lsl_qbe_load32(base + 16))
        state = [handler, bound, out, True, 0, 0, "", 0]
        read_rec = lglib.track(lines_read, 2, state)
        child_rec = lglib.track(lines_exit, 2, state)
        state[4] = read_rec[1]
        state[5] = child_rec[1]
        # G_IO_IN 1 | G_IO_ERR 8 | G_IO_HUP 16
        call __lsl_qbe_call4(__lsl_symbol("g_unix_fd_add"), out, 25, __lsl_symbol("lsl_arch_callback_u3"), ptr(read_rec[0]))
        call __lsl_qbe_call5(__lsl_symbol("g_child_watch_add_full"), 0, pid, __lsl_symbol("lsl_arch_callback_u3"), ptr(child_rec[0]), 0)
        return [pid, input]
    end
end

function lines_read(state, handle, condition):
    unsafe:
        buffer = __lsl_byte_zeros(4096)
        n = __lsl_qbe_call3(__lsl_symbol("read"), ptr(handle), lglib.data(buffer), 4096)
        if n < 0 and lglib.interrupted():
            return True
        end
        if n > 0:
            text = state[6] + __lsl_text_from_bytes(buffer, 0, n)
            cut = text.find("\n")
            while cut >= 0:
                handler = state[0]
                call handler(state[1], text[0:cut], 0)
                text = text[cut + 1:]
                cut = text.find("\n")
            end
            state[6] = text
            return True
        end
        call __lsl_qbe_call1(__lsl_symbol("close"), ptr(handle))
    end
    state[2] = -1
    call lglib.release(state[4])
    if not state[3]:
        call lines_finish(state)
    end
    return False
end

function lines_exit(state, pid, status):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("g_spawn_close_pid"), ptr(pid))
    end
    state[3] = False
    state[7] = status
    call lglib.release(state[5])
    if state[2] == -1:
        call lines_finish(state)
    end
    return False
end

function lines_finish(state):
    handler = state[0]
    call handler(state[1], "", state[7])
    return 0
end

function real_name():
    unsafe:
        return glib.from_c(__lsl_qbe_call0(__lsl_symbol("g_get_real_name")))
    end
end

function user_name():
    unsafe:
        return glib.from_c(__lsl_qbe_call0(__lsl_symbol("g_get_user_name")))
    end
end

function source_pad(cr):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("cairo_pattern_set_extend"), __lsl_qbe_call1(__lsl_symbol("cairo_get_source"), ptr(cr)), 3)
    end
    return 0
end
