# LuxOS - Nastaveni > Otisk prstu (drive luxos-fingerprint): pridani a odebrani otisku pro prihlaseni, zamek, sudo
# a polkit.
#
# Mluvi s fprintd pres D-Bus (net.reactivated.Fprint) - prubeh snimani ukazuje primo na strance. Prihlasovani
# otiskem zapina luxos-fingerprint-pam (hook spravce baliku po instalaci fprintd). Odchod ze stranky nebo zavreni
# okna zastavi snimani a uvolni ctecku (jinak by ji ostatni aplikace nemohly pouzit).
# LUXOS_FPRINT_BUS=session nebo adresa unix:...: fprintd na session / vlastni sbernici (testy s napodobenou sluzbou).
load env, cairo, math, json
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_gio, gio as gio
load luxos_i18n as i18n
load luxos_settings_ui as ui

NAME = "net.reactivated.Fprint"
MANAGER = "/net/reactivated/Fprint/Manager"
IFACE_MANAGER = "net.reactivated.Fprint.Manager"
IFACE_DEVICE = "net.reactivated.Fprint.Device"
ERR = "net.reactivated.Fprint.Error."
# Sluzba fprintd se spousti pres D-Bus aktivaci - bez tohoto souboru neni nainstalovana
SERVICE_FILE = "/usr/share/dbus-1/system-services/net.reactivated.Fprint.service"
CALL_TIMEOUT = 25000
AUTH_TIMEOUT = 2147483647    # Claim/Delete muze cekat na heslo v okne polkitu

FINGERS = [["right-index-finger", "Right index finger"], ["left-index-finger", "Left index finger"],
    ["right-thumb", "Right thumb"], ["left-thumb", "Left thumb"],
    ["right-middle-finger", "Right middle finger"], ["left-middle-finger", "Left middle finger"],
    ["right-ring-finger", "Right ring finger"], ["left-ring-finger", "Left ring finger"],
    ["right-little-finger", "Right little finger"], ["left-little-finger", "Left little finger"]]

# Vysledky EnrollStatus -> [text, konec, chyba]
ENROLL = {"enroll-stage-passed": ["Lift your finger, then touch the sensor again", False, False],
    "enroll-retry-scan": ["Didn't catch that. Touch the sensor again.", False, True],
    "enroll-swipe-too-short": ["Swipe was too short. Try again.", False, True],
    "enroll-finger-not-centered": ["Center your finger on the sensor and try again.", False, True],
    "enroll-remove-and-retry": ["Lift your finger and try again.", False, True],
    "enroll-completed": ["Fingerprint added", True, False],
    "enroll-failed": ["The reader could not read your finger well enough. Clean the sensor and your finger, then click Try Again.", True, True],
    "enroll-data-full": ["The reader cannot store more fingerprints. Remove one first.", True, True],
    "enroll-duplicate": ["This fingerprint is already added.", True, True],
    "enroll-disconnected": ["The fingerprint reader was disconnected.", True, True],
    "enroll-unknown-error": ["Something went wrong. Try again.", True, True]}

CSS = ".fp-title { font-size: 18px; font-weight: 700; }\n.fp-status { font-size: 13px; }\n.fp-status.error { color: #e0443e; }\n"

fp = {"bus": 0, "dev": "", "props": {}, "claimed": False, "sub": 0, "gen": 0}
fv = {"window": 0, "page": 0, "css": 0, "stack": 0, "enrolled": [], "finger": "", "passed": 0, "busy": False, "enrolling": False,
      "progress": 0.0, "error": False, "msg_action": None, "rows": 0}

# ---- texty ---------------------------------------------------------------------------------------------------

function finger_label(key):
    for item in FINGERS:
        if item[0] == key:
            return i18n.T(item[1])
        end
    end
    return i18n.T(key.replace("-", " ").capitalize())
end

# Text pro vysledek EnrollStatus: [text, konec, chyba]
function enroll_message(result, swipe):
    known = result in ENROLL
    entry = ENROLL.get(result, ["Something went wrong. Try again.", True, True])
    text = entry[0]
    if result == "enroll-stage-passed" and swipe:
        text = "Swipe your finger again"
    end
    text = i18n.T(text)
    if result == "enroll-unknown-error" or result == "enroll-failed" or not known:
        # technicky duvod od ctecky (libfprint)
        text = text + "\n(" + result + ")"
    end
    return [text, entry[1], entry[2]]
end

# Srozumitelny text pro chybu volani fprintd
function error_message(error):
    name = gio.remote_error(error)
    if name == ERR + "PermissionDenied" or name == "org.freedesktop.DBus.Error.AccessDenied":
        return i18n.T("You are not allowed to change fingerprints.")
    end
    if name == ERR + "AlreadyInUse":
        return i18n.T("The fingerprint reader is being used by another app. Try again later.")
    end
    if name == ERR + "NoSuchDevice" or name == ERR + "Internal" or name.find("NoSuchDevice") >= 0:
        return i18n.T("The fingerprint reader is not available.")
    end
    if name == ERR + "PrintsNotDeleted":
        return i18n.T("Could not remove the fingerprint.")
    end
    # neznama chyba: k obecne vete technicky duvod (podle nej jde chybu najit a opravit)
    detail = ""
    if name != "":
        parts = name.split(".")
        detail = parts[len(parts) - 1]
    end
    msg = error.strip()
    if msg != "" and msg.find(detail) < 0:
        if detail != "":
            detail = detail + ": " + msg
        else:
            detail = msg
        end
    elif msg != "":
        detail = msg
    end
    if detail != "":
        return i18n.T("Something went wrong. Try again.") + "\n(" + detail + ")"
    end
    return i18n.T("Something went wrong. Try again.")
end

# ---- fprintd (asynchronne; f(data, odpoved, chyba)) --------------------------------------------------------

function fcall(path, interface, method, values, signature, timeout, handler, data):
    call gio.call_interactive(fp["bus"], NAME, path, interface, method, values, signature, timeout, handler, data)
end

function reader_name():
    name = fp["props"].get("name", "")
    if name == "" or name == None:
        return i18n.T("Fingerprint reader")
    end
    return String(name)
end

function stages():
    n = fp["props"].get("num-enroll-stages", -1)
    if n == None or n == 0:
        return -1
    end
    return Int(n)
end

function swipe():
    return fp["props"].get("scan-type", "") == "swipe"
end

# Najde vychozi ctecku a nacte jeji vlastnosti
function open_reader():
    call fcall(MANAGER, IFACE_MANAGER, "GetDefaultDevice", [], "", CALL_TIMEOUT, on_device, 0)
end

function on_device(unused, reply, error):
    if error != "":
        if gio.remote_error(error).endswith("NoSuchDevice"):
            call no_reader(True)
        else:
            call open_failed(error)
        end
        return 0
    end
    fp["dev"] = reply[0]
    call fcall(fp["dev"], "org.freedesktop.DBus.Properties", "GetAll", [IFACE_DEVICE], "(s)", CALL_TIMEOUT, on_props, 0)
    return 0
end

function on_props(unused, reply, error):
    fp["props"] = {}
    if error == "":
        fp["props"] = reply[0]
    end
    call gtk.label_set_text(fv["reader_label"], reader_name())
    call refresh(0)
    return 0
end

# Uvolni ctecku (jen zabranou) a pak after(value)
function release(after, value):
    if not fp["claimed"]:
        call after(value)
        return 0
    end
    fp["claimed"] = False
    call fcall(fp["dev"], IFACE_DEVICE, "Release", [], "", CALL_TIMEOUT, on_released, [after, value])
end

function on_released(next, reply, error):
    handler = next[0]
    call handler(next[1])
    return 0
end

function nothing(value):
    return 0
end

# Claim -> metoda -> Release (zarizeni se uvolni i pri chybe); jen odebirani otisku
function with_claim(method, values, signature):
    call fcall(fp["dev"], IFACE_DEVICE, "Claim", [""], "(s)", AUTH_TIMEOUT, on_claimed_for, [method, values, signature])
end

function on_claimed_for(job, reply, error):
    if error != "":
        call remove_failed(error)
        return 0
    end
    fp["claimed"] = True
    call fcall(fp["dev"], IFACE_DEVICE, job[0], job[1], job[2], AUTH_TIMEOUT, on_deleted, 0)
    return 0
end

function on_deleted(unused, reply, error):
    if error != "":
        call release(remove_failed, error)
    else:
        call release(removed, 0)
    end
    return 0
end

# Claim + EnrollStart; signaly EnrollStatus jdou do on_enroll_status
function enroll_start(finger):
    fp["sub"] = gio.subscribe_data(fp["bus"], NAME, IFACE_DEVICE, "EnrollStatus", fp["dev"], "", 0, on_enroll_signal, 0)
    # zvysi ho enroll_stop: Claim, ktery dobehne po Zrusit, nesmi zacit snimat
    fp["gen"] += 1
    call fcall(fp["dev"], IFACE_DEVICE, "Claim", [""], "(s)", AUTH_TIMEOUT, on_enroll_claimed, [finger, fp["gen"]])
end

function on_enroll_claimed(job, reply, error):
    current = job[1] == fp["gen"]
    if error != "":
        if current:
            call unsubscribe()
            call enroll_failed(error)
        end
        return 0
    end
    fp["claimed"] = True
    if not current:
        # Zrusit behem Claim (okno polkitu): ctecku hned uvolnit, nesnimat
        call release(nothing, 0)
        return 0
    end
    call fcall(fp["dev"], IFACE_DEVICE, "EnrollStart", [job[0]], "(s)", AUTH_TIMEOUT, on_enroll_started, 0)
    return 0
end

function on_enroll_started(unused, reply, error):
    if error != "":
        call unsubscribe()
        call release(enroll_failed, error)
    end
    return 0
end

function on_enroll_signal(unused, sender, path, interface, signal, values):
    call on_enroll_status(values[0], values[1])
    return 0
end

function enroll_stop(after):
    fp["gen"] += 1
    call unsubscribe()
    if not fp["claimed"]:
        call after(0)
        return 0
    end
    call fcall(fp["dev"], IFACE_DEVICE, "EnrollStop", [], "", CALL_TIMEOUT, on_enroll_stopped, after)
end

function on_enroll_stopped(after, reply, error):
    call release(after, 0)
    return 0
end

function unsubscribe():
    if fp["sub"] != 0:
        call gio.unsubscribe(fp["bus"], fp["sub"])
        fp["sub"] = 0
    end
end

# ---- kresba otisku: hrebinky se postupne obarvuji podle prubehu snimani (0..1) ----------------------------------

function set_ridges(progress, error):
    fv["progress"] = max(0.0, min(1.0, Float(progress)))
    fv["error"] = error
    call gtk.widget_queue_draw(fv["ridges"])
end

function on_draw(unused, cr, widget):
    w = Float(gtk.widget_get_allocated_width(widget))
    h = Float(gtk.widget_get_allocated_height(widget))
    s = min(w, h)
    fg = gtk.widget_get_color(widget, 0)
    n = 7
    lit = math.round_half_even_int(fv["progress"] * n)
    # zaoblene konce
    call cairo.set_line_cap(cr, 1)
    call cairo.set_line_width(cr, s * 0.035)
    for i in range(n):
        r = s * (0.08 + i * 0.058)
        # otevreny oblouk dole (jako konecek prstu), kazdy hrebinek trochu jinak
        gap = 0.55 + 0.12 * (i % 3)
        if i < lit and fv["error"]:
            call cairo.set_source_rgba(cr, 0.88, 0.27, 0.24, 1.0)
        elif i < lit:
            call cairo.set_source_rgba(cr, 0.20, 0.52, 0.98, 1.0)
        else:
            call cairo.set_source_rgba(cr, fg[0], fg[1], fg[2], 0.22)
        end
        # elipsa vyssi nez sirsi - tvar konecku prstu
        call cairo.save(cr)
        call cairo.translate(cr, w / 2, h / 2 + s * 0.04)
        call cairo.scale(cr, 0.8, 1.0)
        call cairo.arc(cr, 0.0, 0.0, r, math.PI / 2 + gap, math.PI / 2 - gap + 2 * math.PI)
        call cairo.restore(cr)
        call cairo.stroke(cr)
    end
    return False
end

# ---- okno -------------------------------------------------------------------------------------------------------

function label(text, css):
    l = gtk.label_new(text)
    if css != "":
        call gtk.widget_add_class(l, css)
    end
    return l
end

function centered(css, chars):
    l = label("", css)
    call gtk.label_set_line_wrap(l, True)
    call gtk.label_set_justify(l, gtk.JUSTIFY_CENTER)
    call gtk.label_set_max_width_chars(l, chars)
    return l
end

function button(text, css, handler):
    b = gtk.button_new(text)
    if css != "":
        call gtk.widget_add_class(b, css)
    end
    call gtk.connect_data(b, "clicked", 0, handler, 0)
    return b
end

function build_message():
    page = gtk.box_new(gtk.VERTICAL, 10)
    call gtk.widget_set_margin(page, 30)
    call gtk.widget_set_valign(page, gtk.ALIGN_CENTER)
    fv["msg_icon"] = gtk.image_new()
    call gtk.image_set_pixel_size(fv["msg_icon"], 64)
    fv["msg_spinner"] = gtk.spinner_new()
    call gtk.widget_set_size_request(fv["msg_spinner"], 32, 32)
    fv["msg_title"] = centered("fp-title", 40)
    call gtk.widget_set_name(fv["msg_title"], "msg-title")
    fv["msg_text"] = centered("dim-label", 48)
    call gtk.widget_set_name(fv["msg_text"], "msg-text")
    fv["msg_button"] = button("", "", on_msg_button)
    call gtk.widget_set_halign(fv["msg_button"], gtk.ALIGN_CENTER)
    call gtk.widget_set_margins(fv["msg_button"], 0, 0, 8, 0)
    for key in ["msg_icon", "msg_spinner", "msg_title", "msg_text", "msg_button"]:
        call gtk.box_pack_start(page, fv[key], False, False, 0)
    end
    call gtk.stack_add_named(fv["stack"], page, "message")
end

function build_main():
    page = gtk.box_new(gtk.VERTICAL, 0)
    top = gtk.box_new(gtk.HORIZONTAL, 14)
    icon = gtk.image_new_from_icon_name("luxos-fingerprint", gtk.ICON_DIALOG)
    call gtk.image_set_pixel_size(icon, 56)
    call gtk.box_pack_start(top, icon, False, False, 0)
    texts = gtk.box_new(gtk.VERTICAL, 2)
    call gtk.widget_set_valign(texts, gtk.ALIGN_CENTER)
    intro = label(i18n.T("Use your fingerprint to log in, unlock the screen and approve administrator actions. Your password always works too."), "")
    call gtk.label_set_xalign(intro, 0)
    call gtk.label_set_line_wrap(intro, True)
    call gtk.label_set_max_width_chars(intro, 50)
    call gtk.box_pack_start(texts, intro, False, False, 0)
    fv["reader_label"] = label("", "hint")
    call gtk.widget_set_name(fv["reader_label"], "reader-label")
    call gtk.label_set_xalign(fv["reader_label"], 0)
    call gtk.box_pack_start(texts, fv["reader_label"], False, False, 0)
    call gtk.box_pack_start(top, texts, True, True, 0)
    call gtk.box_pack_start(page, top, False, False, 0)

    title = label(i18n.T("Fingerprints"), "group-title")
    call gtk.label_set_xalign(title, 0)
    call gtk.box_pack_start(page, title, False, False, 0)
    fv["group"] = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(fv["group"], "group")
    call gtk.box_pack_start(page, fv["group"], False, False, 0)
    fv["status"] = label("", "fp-status")
    call gtk.widget_set_name(fv["status"], "status")
    call gtk.label_set_xalign(fv["status"], 0)
    call gtk.label_set_line_wrap(fv["status"], True)
    call gtk.widget_set_margins(fv["status"], 4, 0, 8, 0)
    # prazdny stav nedela mezeru nad tlacitky
    call gtk.widget_set_no_show_all(fv["status"], True)
    call gtk.box_pack_start(page, fv["status"], False, False, 0)

    bar = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_margins(bar, 0, 0, 14, 0)
    fv["add_btn"] = button(i18n.T("Add Fingerprint…"), "suggested-action", on_add)
    call gtk.box_pack_start(bar, fv["add_btn"], False, False, 0)
    fv["remove_all_btn"] = button(i18n.T("Remove All"), "", on_remove_all)
    call gtk.box_pack_end(bar, fv["remove_all_btn"], False, False, 0)
    call gtk.box_pack_start(page, bar, False, False, 0)
    call gtk.stack_add_named(fv["stack"], page, "main")
end

function build_enroll():
    page = gtk.box_new(gtk.VERTICAL, 10)
    call gtk.widget_set_margin(page, 26)
    call gtk.widget_set_valign(page, gtk.ALIGN_CENTER)
    fv["enroll_title"] = label("", "fp-title")
    call gtk.widget_set_name(fv["enroll_title"], "enroll-title")
    call gtk.box_pack_start(page, fv["enroll_title"], False, False, 0)
    fv["ridges"] = gtk.drawing_area_new()
    call gtk.widget_set_size_request(fv["ridges"], 150, 150)
    call gtk.widget_set_halign(fv["ridges"], gtk.ALIGN_CENTER)
    call gtk.connect_data(fv["ridges"], "draw", 1, on_draw, 0)
    call gtk.box_pack_start(page, fv["ridges"], False, False, 6)
    fv["enroll_status"] = centered("fp-status", 44)
    call gtk.widget_set_name(fv["enroll_status"], "enroll-status")
    call gtk.box_pack_start(page, fv["enroll_status"], False, False, 0)
    fv["enroll_count"] = label("", "hint")
    call gtk.widget_set_name(fv["enroll_count"], "enroll-count")
    call gtk.box_pack_start(page, fv["enroll_count"], False, False, 0)
    bar = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_halign(bar, gtk.ALIGN_CENTER)
    call gtk.widget_set_margins(bar, 0, 0, 10, 0)
    fv["enroll_cancel"] = button(i18n.T("Cancel"), "", on_enroll_cancel)
    # Po neuspesnem pridani: znovu stejny prst (bez navratu na seznam a volby prstu)
    fv["enroll_retry"] = button(i18n.T("Try Again"), "suggested-action", on_retry)
    call gtk.widget_set_no_show_all(fv["enroll_retry"], True)
    fv["enroll_done"] = button(i18n.T("Done"), "suggested-action", on_done)
    for key in ["enroll_cancel", "enroll_retry", "enroll_done"]:
        call gtk.box_pack_start(bar, fv[key], False, False, 0)
    end
    call gtk.box_pack_start(page, bar, False, False, 0)
    call gtk.stack_add_named(fv["stack"], page, "enroll")
end

function show_message(icon, title, text, button_text, action, spinner):
    call gtk.image_set_from_icon_name(fv["msg_icon"], icon, gtk.ICON_DIALOG)
    call gtk.image_set_pixel_size(fv["msg_icon"], 64)
    call gtk.widget_set_visible(fv["msg_icon"], not spinner)
    call gtk.widget_set_visible(fv["msg_spinner"], spinner)
    call gtk.spinner_set(fv["msg_spinner"], spinner)
    call gtk.label_set_text(fv["msg_title"], title)
    call gtk.label_set_text(fv["msg_text"], text)
    call gtk.widget_set_visible(fv["msg_text"], text != "")
    call gtk.button_set_label(fv["msg_button"], button_text)
    call gtk.widget_set_visible(fv["msg_button"], button_text != "")
    fv["msg_action"] = action
    call gtk.stack_set_visible_child_name(fv["stack"], "message")
end

function on_msg_button(unused, b):
    if fv["msg_action"] != None:
        action = fv["msg_action"]
        call action()
    end
    return 0
end

function set_status(text, error):
    call gtk.label_set_text(fv["status"], text)
    call gtk.widget_set_visible(fv["status"], text != "")
    call gtk.widget_set_class(fv["status"], "error", error)
end

# ---- prubeh -------------------------------------------------------------------------------------------------------

function start(unused):
    want = env.get("LUXOS_FPRINT_BUS", "")
    if want == "" and not exists(SERVICE_FILE):
        call no_reader(False)
        return False
    end
    try:
        if want.startswith("unix:"):
            fp["bus"] = gio.bus_for_address(want)
        elif want == "session":
            fp["bus"] = gio.session_bus()
        else:
            fp["bus"] = gio.system_bus()
        end
    else:
        call eprint("luxos-fingerprint: " + String(last_error()))
        call no_reader(False)
        return False
    end
    call open_reader()
    return False
end

function open_failed(error):
    call eprint("luxos-fingerprint: " + error)
    name = gio.remote_error(error)
    if name == "org.freedesktop.DBus.Error.ServiceUnknown" or name == "org.freedesktop.DBus.Error.NameHasNoOwner":
        call no_reader(False)
    else:
        call show_message("dialog-error-symbolic", i18n.T("The fingerprint reader is not available."), error_message(error), i18n.T("Try Again"), retry, False)
    end
end

function retry():
    call show_message("content-loading-symbolic", i18n.T("Looking for a fingerprint reader…"), "", "", None, True)
    if fp["bus"] != 0:
        call open_reader()
    else:
        call start(0)
    end
end

function no_reader(installed):
    text = i18n.T("Fingerprint support is not installed. Drivers installs it automatically when your computer has a supported fingerprint reader.")
    if installed:
        text = i18n.T("This computer has no supported fingerprint reader. If you connect one, open Drivers to set it up.")
    end
    if glib.find_program_in_path("luxos-drivers") != "":
        call show_message("luxos-fingerprint", i18n.T("No fingerprint reader found"), text, i18n.T("Open Drivers"), open_drivers, False)
    else:
        call show_message("luxos-fingerprint", i18n.T("No fingerprint reader found"), text, "", None, False)
    end
end

function open_drivers():
    call glib.spawn([glib.find_program_in_path("luxos-drivers")])
end

function refresh(unused):
    call fcall(fp["dev"], IFACE_DEVICE, "ListEnrolledFingers", [""], "(s)", CALL_TIMEOUT, on_listed, 0)
    return 0
end

function on_listed(unused, reply, error):
    if error != "" and not gio.remote_error(error).endswith("NoEnrolledPrints"):
        fv["enrolled"] = []
        call fill()
        call set_status(error_message(error), True)
        return 0
    end
    fv["enrolled"] = [] if error != "" else reply[0]
    call fill()
    call set_status("", False)
    return 0
end

function add_row(title, widget):
    box = gtk.box_new(gtk.HORIZONTAL, 12)
    call gtk.widget_add_class(box, "row")
    if fv["rows"] > 0:
        call gtk.widget_add_class(box, "row-sep")
    end
    text = gtk.label_new(title)
    call gtk.widget_set_name(text, "finger-row")
    call gtk.label_set_xalign(text, 0)
    call gtk.box_pack_start(box, text, True, True, 0)
    if widget != 0:
        call gtk.widget_set_valign(widget, gtk.ALIGN_CENTER)
        call gtk.box_pack_end(box, widget, False, False, 0)
    end
    call gtk.box_pack_start(fv["group"], box, False, False, 0)
    call gtk.widget_show_all(box)
    fv["rows"] += 1
end

function free_fingers():
    return [item[0] for item in FINGERS if not (item[0] in fv["enrolled"])]
end

function fill():
    for child in gtk.container_get_children(fv["group"]):
        call gtk.widget_destroy(child)
    end
    fv["rows"] = 0
    if len(fv["enrolled"]) == 0:
        call add_row(i18n.T("No fingerprints added yet."), 0)
    end
    known = [item[0] for item in FINGERS]
    ordered = [f for f in known if f in fv["enrolled"]] + [f for f in fv["enrolled"] if not (f in known)]
    for finger in ordered:
        b = gtk.button_new(i18n.T("Remove"))
        call gtk.connect_data(b, "clicked", 0, on_remove, finger)
        call add_row(finger_label(finger), b)
    end
    call gtk.widget_set_sensitive(fv["add_btn"], len(free_fingers()) > 0 and not fv["busy"])
    call gtk.widget_set_visible(fv["remove_all_btn"], len(fv["enrolled"]) > 1)
    call gtk.widget_set_sensitive(fv["remove_all_btn"], not fv["busy"])
    call gtk.stack_set_visible_child_name(fv["stack"], "main")
end

function set_busy(on):
    fv["busy"] = on
    call gtk.widget_set_sensitive(fv["group"], not on)
    call gtk.widget_set_sensitive(fv["add_btn"], not on)
    call gtk.widget_set_sensitive(fv["remove_all_btn"], not on)
end

# ---- odebrani ------------------------------------------------------------------------------------------------------

function on_remove(finger, b):
    if not confirm(i18n.TF("Remove the fingerprint “%s”?", [finger_label(finger)]), i18n.T("You will no longer be able to use this finger to log in.")):
        return 0
    end
    call set_busy(True)
    call set_status(i18n.T("Removing…"), False)
    call with_claim("DeleteEnrolledFinger", [finger], "(s)")
    return 0
end

function on_remove_all(unused, b):
    if not confirm(i18n.T("Remove all fingerprints?"), i18n.T("You will need your password to log in.")):
        return 0
    end
    call set_busy(True)
    call set_status(i18n.T("Removing…"), False)
    call with_claim("DeleteEnrolledFingers2", [], "")
    return 0
end

function removed(unused):
    call set_busy(False)
    call refresh(0)
end

function remove_failed(error):
    call eprint("luxos-fingerprint: " + error)
    call set_busy(False)
    call set_status(error_message(error), True)
end

# Dotaz jako Gtk.MessageDialog: tucny nadpis, vysvetleni, Zrusit (vychozi) a Odebrat
function confirm(title, text):
    dialog = gtk.dialog_new()
    call gtk.window_set_title(dialog, "")
    call gtk.window_set_transient_for(dialog, fv["window"])
    call gtk.window_set_modal(dialog, True)
    area = gtk.dialog_get_content_area(dialog)
    call gtk.container_set_border_width(area, 12)
    call gtk.box_set_spacing(area, 10)
    head = gtk.label_new("")
    call gtk.label_set_markup(head, "<big><b>" + glib.markup_escape(title) + "</b></big>")
    call gtk.label_set_line_wrap(head, True)
    call gtk.label_set_max_width_chars(head, 50)
    call gtk.box_pack_start(area, head, False, False, 0)
    body = gtk.label_new(text)
    call gtk.label_set_line_wrap(body, True)
    call gtk.label_set_max_width_chars(body, 50)
    call gtk.box_pack_start(area, body, False, False, 0)
    call gtk.dialog_add_button(dialog, i18n.T("Cancel"), gtk.RESPONSE_CANCEL)
    ok = gtk.dialog_add_button(dialog, i18n.T("Remove"), gtk.RESPONSE_OK)
    call gtk.widget_add_class(ok, "destructive-action")
    call gtk.dialog_set_default_response(dialog, gtk.RESPONSE_CANCEL)
    call gtk.widget_show_all(area)
    response = gtk.dialog_run(dialog)
    call gtk.widget_destroy(dialog)
    return response == gtk.RESPONSE_OK
end

# ---- pridani --------------------------------------------------------------------------------------------------------

function on_add(unused, b):
    free = free_fingers()
    if len(free) == 0:
        return 0
    end
    dialog = gtk.dialog_new_header()
    call gtk.window_set_title(dialog, i18n.T("Add Fingerprint"))
    call gtk.window_set_transient_for(dialog, fv["window"])
    call gtk.window_set_modal(dialog, True)
    call gtk.dialog_add_button(dialog, i18n.T("Cancel"), gtk.RESPONSE_CANCEL)
    go = gtk.dialog_add_button(dialog, i18n.T("Continue"), gtk.RESPONSE_OK)
    call gtk.widget_add_class(go, "suggested-action")
    call gtk.dialog_set_default_response(dialog, gtk.RESPONSE_OK)
    box = gtk.dialog_get_content_area(dialog)
    call gtk.box_set_spacing(box, 10)
    call gtk.container_set_border_width(box, 18)
    question = gtk.label_new(i18n.T("Which finger do you want to add?"))
    call gtk.label_set_xalign(question, 0)
    call gtk.box_pack_start(box, question, False, False, 0)
    combo = gtk.combo_box_text_new()
    for key in free:
        call gtk.combo_box_text_append(combo, key, finger_label(key))
    end
    call gtk.combo_box_set_active(combo, 0)
    call gtk.box_pack_start(box, combo, False, False, 0)
    fv["finger_combo"] = combo
    call gtk.widget_show_all(dialog)
    response = gtk.dialog_run(dialog)
    index = gtk.combo_box_get_active(combo)
    call gtk.widget_destroy(dialog)
    fv["finger_combo"] = 0
    if response == gtk.RESPONSE_OK and index >= 0:
        call enroll(free[index])
    end
    return 0
end

function enroll(finger):
    fv["finger"] = finger
    fv["passed"] = 0
    call gtk.label_set_text(fv["enroll_title"], finger_label(finger))
    call set_ridges(0, False)
    if swipe():
        call set_enroll_status(i18n.T("Swipe your finger across the sensor."), False)
    else:
        call set_enroll_status(i18n.T("Place your finger on the sensor, then lift it."), False)
    end
    call gtk.label_set_text(fv["enroll_count"], "")
    call gtk.button_set_label(fv["enroll_cancel"], i18n.T("Cancel"))
    call gtk.widget_set_visible(fv["enroll_cancel"], True)
    call gtk.widget_set_sensitive(fv["enroll_cancel"], True)
    call gtk.widget_set_visible(fv["enroll_done"], False)
    call gtk.widget_set_visible(fv["enroll_retry"], False)
    call gtk.stack_set_visible_child_name(fv["stack"], "enroll")
    fv["enrolling"] = True
    call enroll_start(finger)
end

function set_enroll_status(text, error):
    call gtk.label_set_text(fv["enroll_status"], text)
    call gtk.widget_set_class(fv["enroll_status"], "error", error)
end

function on_enroll_status(result, done):
    message = enroll_message(result, swipe())
    finished = message[1] or done
    error = message[2]
    if result == "enroll-stage-passed":
        fv["passed"] += 1
    end
    n = stages()
    progress = 0.0
    if result == "enroll-completed":
        progress = 1.0
    elif n > 0:
        progress = min(Float(fv["passed"]) / n, 0.95)
        call gtk.label_set_text(fv["enroll_count"], i18n.TF("Step %d of %d", [min(fv["passed"] + 1, n), n]))
    else:
        progress = min(fv["passed"] * 0.12, 0.9)
    end
    call set_ridges(progress, error and finished)
    call set_enroll_status(message[0], error)
    if finished:
        ok = result == "enroll-completed"
        fv["enrolling"] = False
        call gtk.label_set_text(fv["enroll_count"], "")
        call gtk.button_set_label(fv["enroll_cancel"], i18n.T("Back"))
        call gtk.widget_set_visible(fv["enroll_cancel"], not ok)
        call gtk.widget_set_visible(fv["enroll_done"], ok)
        # Zkusit znovu az po uvolneni ctecky (jinak by nove pridani narazilo na AlreadyInUse)
        again = not ok and result != "enroll-data-full" and result != "enroll-duplicate"
        call gtk.widget_set_visible(fv["enroll_retry"], again)
        call gtk.widget_set_sensitive(fv["enroll_retry"], False)
        call enroll_stop(retry_ready)
    end
end

function retry_ready(unused):
    call gtk.widget_set_sensitive(fv["enroll_retry"], True)
end

function enroll_failed(error):
    call eprint("luxos-fingerprint: " + error)
    fv["enrolling"] = False
    call set_ridges(0, False)
    call set_enroll_status(error_message(error), True)
    call gtk.button_set_label(fv["enroll_cancel"], i18n.T("Back"))
    # ctecka uz je uvolnena (enroll_start pri chybe vola release)
    call gtk.widget_set_visible(fv["enroll_retry"], True)
    call gtk.widget_set_sensitive(fv["enroll_retry"], True)
end

function on_retry(unused, b):
    call enroll(fv["finger"])
    return 0
end

function on_done(unused, b):
    call refresh(0)
    return 0
end

function on_enroll_cancel(unused, b):
    call gtk.button_set_label(fv["enroll_cancel"], i18n.T("Cancel"))
    if fv["enrolling"]:
        fv["enrolling"] = False
        call gtk.widget_set_sensitive(fv["enroll_cancel"], False)
        call enroll_stop(refresh)
    else:
        call refresh(0)
    end
    return 0
end

# ---- stranka v okne Nastaveni -------------------------------------------------------------------------------------

function build(host):
    fv["window"] = host["window"]
    if fv["css"] == 0:
        fv["css"] = gtk.css_load(CSS)
    end
    page = ui.page_box()
    fv["page"] = page
    fv["stack"] = gtk.stack_new(False)
    call gtk.box_pack_start(page, fv["stack"], True, True, 0)
    call build_message()
    call build_main()
    call build_enroll()
    call gtk.widget_show_all(fv["stack"])
    call show_message("content-loading-symbolic", i18n.T("Looking for a fingerprint reader…"), "", "", None, True)
    call glib.idle_add_data(start, 0)
    return page
end

# Odchod ze stranky i zavreni okna: snimani zastavit a ctecku uvolnit hned (synchronne - po zavreni okna proces
# konci a asynchronni volani by uz neodeslo)
function leave(host):
    fp["gen"] += 1
    call unsubscribe()
    if fp["bus"] == 0 or fp["dev"] == "":
        return 0
    end
    if fp["claimed"]:
        fp["claimed"] = False
        if fv["enrolling"]:
            safe:
                call gio.call_values(fp["bus"], NAME, fp["dev"], IFACE_DEVICE, "EnrollStop", [], "", 3000)
            end
        end
        safe:
            call gio.call_values(fp["bus"], NAME, fp["dev"], IFACE_DEVICE, "Release", [], "", 3000)
        end
    end
    if fv["enrolling"] or gtk.stack_get_visible_child_name(fv["stack"]) == "enroll":
        # po navratu na stranku seznam otisku, ne rozpracovane pridavani
        fv["enrolling"] = False
        call fill()
    end
    return 0
end

# ---- testy (LUXOS_TEST_CONTROL=1, luxos-settings preda prikazy, ktere nezna) -----------------------------------
# "state" patri oknu Nastaveni, stav stranky je "page-state"

function test(command, rest):
    if command == "enroll":
        call enroll(rest)
    elif command == "remove":
        call on_remove(rest, 0)
    elif command == "page-state":
        print "page-state " + json.encode({"page": gtk.stack_get_visible_child_name(fv["stack"]), "passed": fv["passed"],
            "progress": fv["progress"], "ridges_error": fv["error"], "busy": fv["busy"], "enrolling": fv["enrolling"],
            "status_error": gtk.widget_has_class(fv["status"], "error"),
            "enroll_error": gtk.widget_has_class(fv["enroll_status"], "error"), "claimed": fp["claimed"],
            "status": gtk.label_get_text(fv["enroll_status"]), "count": gtk.label_get_text(fv["enroll_count"])})
    elif command == "message":
        parts = rest.split(" ")
        print "message " + json.encode(enroll_message(parts[0], len(parts) > 1 and parts[1] == "swipe"))
    elif command == "finger":
        print "finger " + finger_label(rest)
    elif command == "close":
        call gtk.window_close(fv["window"])
    else:
        return False
    end
    return True
end
