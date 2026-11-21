# lsl: link libglib-2.0.so.0
# LuxOS - regularni vyrazy pro programy v LSL (GRegex z GLib, PCRE2 se syntaxi jako Python re: (?<!...),
# (?:...), \d, \w, zpetne odkazy \1). Pro aplikace prepsane z Pythonu (luxos-feedback, luxos-portal-check).
#   search(vzor, text, caseless) -> [cela shoda, skupina 1, ...] nebo None
#   sub(vzor, text, nahrada) -> text s nahrazenymi shodami (nahrada: \1 = skupina, \\ = zpetne lomitko)
#   escape(text) -> text jako doslovny vzor
# Neplatny vzor je chyba programu (ValueError), ne vstupu.
load glib

CASELESS = 1

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

function compile(pattern, flags):
    unsafe:
        cell = __lsl_byte_zeros(8)
        regex = __lsl_qbe_call4(__lsl_symbol("g_regex_new"), cstr(pattern), ptr(flags), 0, __lsl_qbe_load64(__lsl_address(cell) + 24))
        if regex == 0:
            err = __lsl_qbe_load64(__lsl_qbe_load64(__lsl_address(cell) + 24))
            message = glib.from_c(__lsl_qbe_load64(err + 8))
            call __lsl_qbe_call1(__lsl_symbol("g_error_free"), err)
            Error(ValueError: "regex " + pattern + ": " + message)
        end
        return regex
    end
end

function search(pattern, text, caseless):
    flags = 0
    if caseless:
        flags = CASELESS
    end
    regex = compile(pattern, flags)
    out = None
    unsafe:
        cell = __lsl_byte_zeros(8)
        where = __lsl_qbe_load64(__lsl_address(cell) + 24)
        if __lsl_qbe_s32(__lsl_qbe_call4(__lsl_symbol("g_regex_match"), regex, cstr(text), 0, where)) != 0:
            info = __lsl_qbe_load64(where)
            out = []
            count = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("g_match_info_get_match_count"), info))
            for i in range(count):
                out.append(glib.take_c(__lsl_qbe_call2(__lsl_symbol("g_match_info_fetch"), info, i)))
            end
            # skupiny bez shody na konci GRegex nepocita (Python dava None, tady "")
            groups = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("g_regex_get_capture_count"), regex))
            while len(out) < groups + 1:
                out.append("")
            end
        end
        call __lsl_qbe_call1(__lsl_symbol("g_match_info_free"), __lsl_qbe_load64(where))
        call __lsl_qbe_call1(__lsl_symbol("g_regex_unref"), regex)
    end
    return out
end

function sub(pattern, text, replacement):
    regex = compile(pattern, 0)
    result = text
    unsafe:
        cell = __lsl_byte_zeros(8)
        raw = __lsl_qbe_call7(__lsl_symbol("g_regex_replace"), regex, cstr(text), -1, 0, cstr(replacement), 0, __lsl_qbe_load64(__lsl_address(cell) + 24))
        call __lsl_qbe_call1(__lsl_symbol("g_regex_unref"), regex)
        if raw == 0:
            err = __lsl_qbe_load64(__lsl_qbe_load64(__lsl_address(cell) + 24))
            message = glib.from_c(__lsl_qbe_load64(err + 8))
            call __lsl_qbe_call1(__lsl_symbol("g_error_free"), err)
            Error(ValueError: "regex " + pattern + ": " + message)
        end
        result = glib.take_c(raw)
    end
    return result
end

function escape(text):
    unsafe:
        return glib.take_c(__lsl_qbe_call2(__lsl_symbol("g_regex_escape_string"), cstr(text), -1))
    end
end
