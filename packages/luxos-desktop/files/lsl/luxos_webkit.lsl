# LuxOS - WebKitGTK (webkit2gtk-4.1) pro Spravu site: knihovna se nacita az za behu (dlopen), az kdyz ji
# aplikace opravdu potrebuje (karta Router) - prehled a ostatni aplikace ji nemaji v pameti.
#
#   available() -> True/False (vsechny potrebne funkce knihovny nalezeny)
#   call(nazev, argumenty...) pres fn(nazev) a __lsl_qbe_callN; ostatni funkce jsou tenke obaly
# LUXOS_WEBKIT_LIB prepise cestu ke knihovne (testy: "none" = WebKit chybi).
load env
load luxos_glib, glib as glib

# WebKitPolicyDecisionType
NAVIGATION_ACTION = 0
NEW_WINDOW_ACTION = 1
RESPONSE = 2
# WebKitLoadEvent
LOAD_COMMITTED = 2
# chyby: WEBKIT_POLICY_ERROR_FRAME_LOAD_INTERRUPTED_BY_POLICY_CHANGE, WEBKIT_NETWORK_ERROR_CANCELLED
POLICY_INTERRUPTED = 102
NETWORK_CANCELLED = 302

NAMES = ["webkit_web_context_new_ephemeral", "webkit_web_context_set_cache_model", "webkit_web_context_get_website_data_manager",
    "webkit_website_data_manager_set_tls_errors_policy", "webkit_web_context_allow_tls_certificate_for_host",
    "webkit_web_context_is_ephemeral", "webkit_web_view_new_with_context", "webkit_web_view_get_settings",
    "webkit_settings_set_enable_developer_extras", "webkit_settings_set_enable_page_cache",
    "webkit_settings_set_javascript_can_open_windows_automatically", "webkit_settings_set_hardware_acceleration_policy",
    "webkit_settings_set_enable_webgl", "webkit_settings_set_enable_media", "webkit_web_view_load_uri", "webkit_web_view_load_html",
    "webkit_web_view_go_back", "webkit_web_view_reload", "webkit_web_view_get_uri", "webkit_web_view_can_go_back",
    "webkit_web_view_get_title", "webkit_web_view_is_loading", "webkit_web_view_evaluate_javascript",
    "webkit_navigation_policy_decision_get_navigation_action", "webkit_navigation_action_get_request",
    "webkit_navigation_action_is_user_gesture", "webkit_uri_request_get_uri", "webkit_policy_decision_use",
    "webkit_policy_decision_ignore", "webkit_policy_decision_download", "webkit_response_policy_decision_is_mime_type_supported",
    "webkit_response_policy_decision_is_main_frame_main_resource", "webkit_policy_error_quark", "webkit_network_error_quark",
    "webkit_authentication_request_is_for_proxy", "webkit_authentication_request_get_host",
    "webkit_authentication_request_authenticate", "webkit_authentication_request_cancel", "webkit_credential_new",
    "webkit_credential_free", "webkit_download_set_destination", "webkit_download_get_destination"]

lib = {"tried": False, "fns": {}}

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function cstr(value):
    unsafe:
        return __lsl_address(value) + 16
    end
end

function load_library():
    if lib["tried"]:
        return len(lib["fns"]) > 0
    end
    lib["tried"] = True
    path = env.get("LUXOS_WEBKIT_LIB", "libwebkit2gtk-4.1.so.0")
    if path == "none":
        return False
    end
    unsafe:
        # RTLD_NOW | RTLD_GLOBAL (WebKit si sam dohledava sve symboly)
        handle = __lsl_qbe_call2(__lsl_symbol("dlopen"), cstr(path), 2 | 256)
    end
    if handle == 0:
        return False
    end
    found = {}
    for symbol in NAMES:
        unsafe:
            address = __lsl_qbe_call2(__lsl_symbol("dlsym"), handle, cstr(symbol))
        end
        if address == 0:
            return False
        end
        found[symbol] = address
    end
    lib["fns"] = found
    return True
end

function available():
    return load_library()
end

# adresa funkce pro __lsl_qbe_callN (icall vraci jen 32 bitu, ukazatele by se orizly)
function fn(name):
    return ptr(lib["fns"]["webkit_" + name])
end

function flag(value):
    if value:
        return 1
    end
    return 0
end

function truth(result):
    unsafe:
        return __lsl_qbe_s32(result) != 0
    end
end

# ---- kontext a pohled ---------------------------------------------------------------------------------

# Docasna relace bez cookies, mezipameti a hesel na disku; neduveryhodny certifikat = chyba
function ephemeral_context():
    unsafe:
        ctx = __lsl_qbe_call0(fn("web_context_new_ephemeral"))
        # WEBKIT_CACHE_MODEL_DOCUMENT_VIEWER
        call __lsl_qbe_call2(fn("web_context_set_cache_model"), ctx, 0)
        manager = __lsl_qbe_call1(fn("web_context_get_website_data_manager"), ctx)
        # WEBKIT_TLS_ERRORS_POLICY_FAIL
        call __lsl_qbe_call2(fn("website_data_manager_set_tls_errors_policy"), manager, 1)
        return ctx
    end
end

function is_ephemeral(ctx):
    unsafe:
        return truth(__lsl_qbe_call1(fn("web_context_is_ephemeral"), ptr(ctx)))
    end
end

function allow_certificate(ctx, cert, host):
    unsafe:
        return __lsl_qbe_call3(fn("web_context_allow_tls_certificate_for_host"), ptr(ctx), ptr(cert), cstr(host))
    end
end

# Pohled bez vyvojarskych nastroju, mezipameti stranek, oken ze skriptu, WebGL, medii a GPU (bezi i ve VM)
function view_new(ctx):
    unsafe:
        view = __lsl_qbe_call1(fn("web_view_new_with_context"), ptr(ctx))
        s = __lsl_qbe_call1(fn("web_view_get_settings"), view)
        call __lsl_qbe_call2(fn("settings_set_enable_developer_extras"), s, 0)
        call __lsl_qbe_call2(fn("settings_set_enable_page_cache"), s, 0)
        call __lsl_qbe_call2(fn("settings_set_javascript_can_open_windows_automatically"), s, 0)
        # WEBKIT_HARDWARE_ACCELERATION_POLICY_NEVER
        call __lsl_qbe_call2(fn("settings_set_hardware_acceleration_policy"), s, 2)
        call __lsl_qbe_call2(fn("settings_set_enable_webgl"), s, 0)
        call __lsl_qbe_call2(fn("settings_set_enable_media"), s, 0)
        return view
    end
end

function load_uri(view, uri):
    unsafe:
        return __lsl_qbe_call2(fn("web_view_load_uri"), ptr(view), cstr(uri))
    end
end

function load_html(view, html):
    unsafe:
        return __lsl_qbe_call3(fn("web_view_load_html"), ptr(view), cstr(html), 0)
    end
end

function go_back(view):
    unsafe:
        return __lsl_qbe_call1(fn("web_view_go_back"), ptr(view))
    end
end

function reload(view):
    unsafe:
        return __lsl_qbe_call1(fn("web_view_reload"), ptr(view))
    end
end

function uri(view):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(fn("web_view_get_uri"), ptr(view)))
    end
end

function title(view):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(fn("web_view_get_title"), ptr(view)))
    end
end

function can_go_back(view):
    unsafe:
        return truth(__lsl_qbe_call1(fn("web_view_can_go_back"), ptr(view)))
    end
end

function is_loading(view):
    unsafe:
        return truth(__lsl_qbe_call1(fn("web_view_is_loading"), ptr(view)))
    end
end

# Skript ve strance (jen testy: kliknuti na odkaz)
function run_script(view, code):
    unsafe:
        return __lsl_qbe_call8(fn("web_view_evaluate_javascript"), ptr(view), cstr(code), -1, 0, 0, 0, 0, 0)
    end
end

# ---- rozhodnuti o navigaci ---------------------------------------------------------------------------------

# [adresa, klik uzivatele] navigace
function navigation(decision):
    unsafe:
        action = __lsl_qbe_call1(fn("navigation_policy_decision_get_navigation_action"), ptr(decision))
        request = __lsl_qbe_call1(fn("navigation_action_get_request"), action)
        text = glib.from_c(__lsl_qbe_call1(fn("uri_request_get_uri"), request))
        return [text, truth(__lsl_qbe_call1(fn("navigation_action_is_user_gesture"), action))]
    end
end

function decide(decision, how):
    unsafe:
        if how == "use":
            return __lsl_qbe_call1(fn("policy_decision_use"), ptr(decision))
        elif how == "download":
            return __lsl_qbe_call1(fn("policy_decision_download"), ptr(decision))
        end
        return __lsl_qbe_call1(fn("policy_decision_ignore"), ptr(decision))
    end
end

# Odpoved, kterou WebKit neumi zobrazit, v hlavnim ramci (zaloha nastaveni routeru) = stahnout
function response_needs_download(decision):
    unsafe:
        supported = truth(__lsl_qbe_call1(fn("response_policy_decision_is_mime_type_supported"), ptr(decision)))
        main = truth(__lsl_qbe_call1(fn("response_policy_decision_is_main_frame_main_resource"), ptr(decision)))
        return not supported and main
    end
end

# GError -> [domena je chyba pravidel / site, kod, text]
function error_info(error):
    unsafe:
        domain = __lsl_qbe_load32(ptr(error)) & 4294967295
        code = __lsl_qbe_s32(__lsl_qbe_load32(ptr(error) + 4))
        message = glib.from_c(__lsl_qbe_load64(ptr(error) + 8))
        policy = __lsl_qbe_call0(fn("policy_error_quark")) & 4294967295
        network = __lsl_qbe_call0(fn("network_error_quark")) & 4294967295
        return {"policy": domain == policy, "network": domain == network, "code": code, "message": message}
    end
end

# ---- prihlaseni (HTTP Basic) ---------------------------------------------------------------------------------

function auth_is_proxy(request):
    unsafe:
        return truth(__lsl_qbe_call1(fn("authentication_request_is_for_proxy"), ptr(request)))
    end
end

function auth_host(request):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(fn("authentication_request_get_host"), ptr(request)))
    end
end

# Udaje jen pro tento pozadavek (WEBKIT_CREDENTIAL_PERSISTENCE_NONE), nic se neuklada
function authenticate(request, user, password):
    unsafe:
        credential = __lsl_qbe_call3(fn("credential_new"), cstr(user), cstr(password), 0)
        call __lsl_qbe_call2(fn("authentication_request_authenticate"), ptr(request), credential)
        call __lsl_qbe_call1(fn("credential_free"), credential)
    end
    return 0
end

function auth_cancel(request):
    unsafe:
        return __lsl_qbe_call1(fn("authentication_request_cancel"), ptr(request))
    end
end

# ---- stahovani ------------------------------------------------------------------------------------------------

function download_set_destination(download, file_uri):
    unsafe:
        return __lsl_qbe_call2(fn("download_set_destination"), ptr(download), cstr(file_uri))
    end
end

function download_destination(download):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(fn("download_get_destination"), ptr(download)))
    end
end
