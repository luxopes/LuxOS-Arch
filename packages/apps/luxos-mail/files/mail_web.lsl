# lsl: internal-abi
# lsl: link libgdk-3.so.0 libgobject-2.0.so.0 libglib-2.0.so.0
# Posta LuxOS - zobrazeni zpravy ve WebKitGTK (webkit2gtk-4.1, v LuxOS uz je kvuli sprave routeru a yad).
# Zamceny rezim: bez JavaScriptu, zasuvnych modulu, WebGL, medii, mistniho uloziste a cookies (docasny kontext
# bez dat na disku), bez navigace uvnitr (odkazy jdou do systemoveho prohlizece pres obsluhu decide-policy).
# Sit blokuje uz HTML pripravene v mail_html (vzdalene adresy odstranene, Content-Security-Policy); tady jen
# nastaveni pohledu. Nazvy = funkce WebKitGTK bez webkit_.
#   view_new()                      novy pohled se zamcenym nastavenim
#   load_html(pohled, html)         nacteni dokumentu (zakladni adresa about:blank)
#   decision_uri(rozhodnuti, typ)   [adresa, kliknuti] navigace z decide-policy (typ 0 navigace, 1 nove okno)
#   decision_use / decision_ignore, zoom_get / zoom_set, find / find_next / find_previous / find_finish, print_dialog,
#   hit_link (odkaz pod mysi), set_background, available() (knihovna se nacita az za behu, dlopen)
load luxos_glib, glib as glib

BASE = "about:blank"
CONTEXT = [0]
# knihovna se nacita az za behu (dlopen): linker LuxIR knihovnu WebKitu (98 MB) neprecte a Posta bez ni
# zobrazi zpravu aspon jako text
LIB = [0, False]
SYMS = {}

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

function library():
    unsafe:
        if not LIB[1]:
            LIB[1] = True
            LIB[0] = __lsl_qbe_call2(__lsl_symbol("dlopen"), cstr("libwebkit2gtk-4.1.so.0"), 1)
        end
        return ptr(LIB[0])
    end
end

function available():
    return library() != 0
end

function sym(name):
    unsafe:
        if name in SYMS:
            return SYMS[name]
        end
        h = library()
        p = 0
        if h != 0:
            p = __lsl_qbe_call2(__lsl_symbol("dlsym"), h, cstr(name))
        end
        if p == 0:
            Error(MailError: "webkit|missing " + name)
        end
        SYMS[name] = p
        return p
    end
end

function context():
    unsafe:
        if ptr(CONTEXT[0]) != 0:
            return CONTEXT[0]
        end
        ctx = __lsl_qbe_call0(ptr(sym("webkit_web_context_new_ephemeral")))
        # WEBKIT_CACHE_MODEL_DOCUMENT_VIEWER: nejmensi pamet, zadna mezipamet stranek
        call __lsl_qbe_call2(ptr(sym("webkit_web_context_set_cache_model")), ctx, 0)
        CONTEXT[0] = ctx
        return ctx
    end
end

function view_new():
    unsafe:
        view = __lsl_qbe_call1(ptr(sym("webkit_web_view_new_with_context")), ptr(context()))
        s = __lsl_qbe_call1(ptr(sym("webkit_web_view_get_settings")), view)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_enable_javascript")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_enable_javascript_markup")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_javascript_can_open_windows_automatically")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_javascript_can_access_clipboard")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_enable_plugins")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_enable_java")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_enable_webgl")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_enable_webaudio")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_enable_media")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_enable_media_stream")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_enable_mediasource")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_enable_html5_local_storage")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_enable_html5_database")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_enable_offline_web_application_cache")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_enable_page_cache")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_enable_developer_extras")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_enable_hyperlink_auditing")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_enable_dns_prefetching")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_enable_site_specific_quirks")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_enable_back_forward_navigation_gestures")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_allow_modal_dialogs")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_allow_top_navigation_to_data_urls")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_allow_file_access_from_file_urls")), s, 0)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_allow_universal_access_from_file_urls")), s, 0)
        # obrazky jen z data: (vlozene cid: a nahledy priloh); vzdalene zakazuje CSP v dokumentu
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_auto_load_images")), s, 1)
        call __lsl_qbe_call2(ptr(sym("webkit_settings_set_default_charset")), s, cstr("utf-8"))
        return view
    end
end

function load_html(view, html):
    unsafe:
        return __lsl_qbe_call3(ptr(sym("webkit_web_view_load_html")), ptr(view), cstr(html), cstr(BASE))
    end
end

# decide-policy: [adresa, druh] - druh "load" (nase nacteni dokumentu, kotva), "click" (odkaz, nove okno),
# "other" (cokoli jineho: zakazat), "response" (odpoved na povolene nacteni)
function decision_uri(decision, kind):
    unsafe:
        k = ptr(kind)
        if k == 2:
            return ["", "response"]
        end
        action = __lsl_qbe_call1(ptr(sym("webkit_navigation_policy_decision_get_navigation_action")), ptr(decision))
        if action == 0:
            return ["", "other"]
        end
        req = __lsl_qbe_call1(ptr(sym("webkit_navigation_action_get_request")), action)
        uri = ""
        if req != 0:
            uri = glib.from_c(__lsl_qbe_call1(ptr(sym("webkit_uri_request_get_uri")), req))
        end
        nav = __lsl_qbe_s32(__lsl_qbe_call1(ptr(sym("webkit_navigation_action_get_navigation_type")), action))
        if k == 1 or nav == 0:
            if uri == BASE or uri.startswith(BASE + "#"):
                return [uri, "load"]
            end
            return [uri, "click"]
        end
        if uri == BASE or uri.startswith(BASE + "#"):
            return [uri, "load"]
        end
        return [uri, "other"]
    end
end

function decision_use(decision):
    unsafe:
        return __lsl_qbe_call1(ptr(sym("webkit_policy_decision_use")), ptr(decision))
    end
end

function decision_ignore(decision):
    unsafe:
        return __lsl_qbe_call1(ptr(sym("webkit_policy_decision_ignore")), ptr(decision))
    end
end

function zoom_get(view):
    unsafe:
        return __lsl_qbe_fcall1(ptr(sym("webkit_web_view_get_zoom_level")), ptr(view))
    end
end

function zoom_set(view, level):
    unsafe:
        return __lsl_qbe_call2(ptr(sym("webkit_web_view_set_zoom_level")), ptr(view), Float(level))
    end
end

function finder(view):
    unsafe:
        return __lsl_qbe_call1(ptr(sym("webkit_web_view_get_find_controller")), ptr(view))
    end
end

# WEBKIT_FIND_OPTIONS_CASE_INSENSITIVE 1 | WRAP_AROUND 16
function find(view, text):
    unsafe:
        return __lsl_qbe_call4(ptr(sym("webkit_find_controller_search")), ptr(finder(view)), cstr(text), 17, 1000)
    end
end

function find_next(view):
    unsafe:
        return __lsl_qbe_call1(ptr(sym("webkit_find_controller_search_next")), ptr(finder(view)))
    end
end

function find_previous(view):
    unsafe:
        return __lsl_qbe_call1(ptr(sym("webkit_find_controller_search_previous")), ptr(finder(view)))
    end
end

function find_finish(view):
    unsafe:
        return __lsl_qbe_call1(ptr(sym("webkit_find_controller_search_finish")), ptr(finder(view)))
    end
end

function print_dialog(view, parent):
    unsafe:
        op = __lsl_qbe_call1(ptr(sym("webkit_print_operation_new")), ptr(view))
        call __lsl_qbe_call2(ptr(sym("webkit_print_operation_run_dialog")), op, ptr(parent))
        call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), op)
        return 0
    end
end

# Odkaz pod mysi (signal mouse-target-changed): adresa nebo ""
function hit_link(hit):
    unsafe:
        if ptr(hit) == 0:
            return ""
        end
        if __lsl_qbe_call1(ptr(sym("webkit_hit_test_result_context_is_link")), ptr(hit)) == 0:
            return ""
        end
        return glib.from_c(__lsl_qbe_call1(ptr(sym("webkit_hit_test_result_get_link_uri")), ptr(hit)))
    end
end

# Barva pozadi pred nactenim dokumentu (zadne bile bliknuti v tmavem vzhledu), "#rrggbb"
function set_background(view, color):
    unsafe:
        rgba = __lsl_byte_zeros(32)
        p = __lsl_qbe_load64(__lsl_address(rgba) + 24)
        if __lsl_qbe_call2(__lsl_symbol("gdk_rgba_parse"), p, cstr(color)) != 0:
            call __lsl_qbe_call2(ptr(sym("webkit_web_view_set_background_color")), ptr(view), p)
        end
        return 0
    end
end
