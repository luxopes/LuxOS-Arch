# lsl: link libcrypt.so.2
# LuxOS - hash hesla pro /etc/shadow (libxcrypt, vychozi metoda systemu - yescrypt "$y$"). Heslo se hashuje
# v procesu a sluzbe (AccountsService SetPassword) jde jen hash: nikdy v argumentech jineho programu (/proc).
#
#   hash(password) -> "$y$..." nebo "" pri chybe

function cstr(value):
    unsafe:
        return __lsl_address(value) + 16
    end
end

function from_c(address):
    if address == 0:
        return ""
    end
    unsafe:
        out = ""
        i = 0
        while True:
            b = __lsl_qbe_load8(address + i) & 255
            if b == 0:
                break
            end
            out = out + chr(b)
            i += 1
        end
        return out
    end
end

function hash(password):
    unsafe:
        # crypt_gensalt(NULL, 0, NULL, 0): vychozi metoda a pocet kol, sul z /dev/urandom
        salt = __lsl_qbe_call4(__lsl_symbol("crypt_gensalt"), 0, 0, 0, 0)
        if salt == 0:
            return ""
        end
        setting = from_c(salt)
        result = __lsl_qbe_call2(__lsl_symbol("crypt"), cstr(password), cstr(setting))
    end
    out = from_c(result)
    # chyba: "*0"/"*1" nebo NULL
    if out == "" or out.startswith("*"):
        return ""
    end
    return out
end
