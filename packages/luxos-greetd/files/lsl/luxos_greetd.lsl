# lsl: internal-abi
# LuxOS - klient IPC greetd (https://man.sr.ht/~kennylevinsen/greetd/): zpravy JSON s delkou (u32, poradi bajtu
# hostitele) na socketu UNIX z promenne GREETD_SOCK. Pozadavky create_session, post_auth_message_response,
# start_session a cancel_session; odpovedi success, error, auth_message. PAM bezi v greetd, ne v greeteru.
#
#   connect(cesta)              popisovac nebo -1
#   send(fd, hodnota)           zprava (slovnik -> JSON); False kdyz spojeni skoncilo
#   watch(fd, f)                f(odpoved) za kazdou celou odpoved (slovnik), f(None) pri konci spojeni
#   close(fd)
load json
load luxos_glib as lglib

AF_UNIX = 1
SOCK_STREAM_CLOEXEC = 524289
MAX_FRAME = 1048576

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

function connect(path):
    unsafe:
        fd = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("socket"), AF_UNIX, SOCK_STREAM_CLOEXEC, 0))
        if fd < 0:
            return -1
        end
        length = __lsl_qbe_call1(__lsl_symbol("strlen"), cstr(path))
        if length > 107:
            call __lsl_qbe_call1(__lsl_symbol("close"), fd)
            return -1
        end
        address = __lsl_byte_zeros(110)
        base = lglib.data(address)
        call __lsl_qbe_store32(base, AF_UNIX)
        call __lsl_qbe_call3(__lsl_symbol("memcpy"), base + 2, cstr(path), length)
        if __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("connect"), fd, base, 2 + length + 1)) != 0:
            call __lsl_qbe_call1(__lsl_symbol("close"), fd)
            return -1
        end
        return fd
    end
end

function send(fd, value):
    text = json.encode(value)
    unsafe:
        n = __lsl_qbe_call1(__lsl_symbol("strlen"), cstr(text))
        frame = __lsl_byte_zeros(n + 4)
        base = lglib.data(frame)
        call __lsl_qbe_store32(base, n)
        call __lsl_qbe_call3(__lsl_symbol("memcpy"), base + 4, cstr(text), n)
        sent = 0
        while sent < n + 4:
            # MSG_NOSIGNAL: greetd skoncil = False, ne SIGPIPE
            w = __lsl_qbe_s32(__lsl_qbe_call4(__lsl_symbol("send"), ptr(fd), base + sent, n + 4 - sent, 16384))
            if w < 0:
                if lglib.interrupted():
                    continue
                end
                return False
            end
            sent += w
        end
    end
    return True
end

# state = [obsluha, prijata data (ByteArray), pocet bajtu]
function watch(fd, handler):
    unsafe:
        buffer = __lsl_byte_zeros(4096)
    end
    state = [handler, buffer, 0]
    # G_IO_IN 1 | G_IO_ERR 8 | G_IO_HUP 16
    call lglib.fd_add_data(fd, 25, on_readable, state)
    return 0
end

function on_readable(state, fd, condition):
    unsafe:
        chunk = __lsl_byte_zeros(16384)
        n = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("read"), ptr(fd), lglib.data(chunk), 16384))
        if n < 0 and lglib.interrupted():
            return True
        end
        if n <= 0:
            handler = state[0]
            call handler(None)
            return False
        end
        buffer = state[1]
        have = state[2]
        if have + n > len(buffer):
            grown = __lsl_byte_zeros(max(len(buffer) * 2, have + n))
            call __lsl_byte_copy(grown, buffer, 0, 0, have)
            buffer = grown
            state[1] = buffer
        end
        call __lsl_byte_copy(buffer, chunk, have, 0, n)
        have += n
        while have >= 4:
            size = __lsl_qbe_load32(lglib.data(buffer)) & 4294967295
            if size > MAX_FRAME:
                handler = state[0]
                call handler(None)
                return False
            end
            if have < 4 + size:
                break
            end
            text = __lsl_text_from_bytes(buffer, 4, size)
            rest = have - 4 - size
            if rest > 0:
                left = __lsl_byte_zeros(max(4096, rest))
                call __lsl_byte_copy(left, buffer, 0, 4 + size, rest)
                buffer = left
                state[1] = buffer
            end
            have = rest
            state[2] = have
            reply = None
            safe:
                reply = json.decode(text)
            end
            handler = state[0]
            call handler(reply)
        end
        state[2] = have
        return True
    end
end

function close(fd):
    unsafe:
        if ptr(fd) >= 0:
            call __lsl_qbe_call1(__lsl_symbol("close"), ptr(fd))
        end
    end
    return 0
end
