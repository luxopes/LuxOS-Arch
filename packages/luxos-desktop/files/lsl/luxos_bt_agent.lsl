# LuxOS - Bluetooth: parovani a pripojeni z telefonu i bez otevrene aplikace (misto blueman-applet);
# prepis tridy BluetoothAgent z luxos-hub. Vychozi agent BlueZ na pozadi: dialogy a kody jako v aplikaci
# luxos-bluetooth; pred parovanim bez kodu a sluzbou neduveryhodneho zarizeni se zepta.
#   call agent.watch(system_bus)   BlueZ bezi jen s adapterem (i USB pripojenym pozdeji): registrace pri objeveni
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_text as text

AGENT_PATH = "/org/luxos/bluetooth/agent"
AGENT_XML = ("<node><interface name=\"org.bluez.Agent1\">"
    + "<method name=\"Release\"/>"
    + "<method name=\"RequestPinCode\"><arg type=\"o\" direction=\"in\"/><arg type=\"s\" direction=\"out\"/></method>"
    + "<method name=\"DisplayPinCode\"><arg type=\"o\" direction=\"in\"/><arg type=\"s\" direction=\"in\"/></method>"
    + "<method name=\"RequestPasskey\"><arg type=\"o\" direction=\"in\"/><arg type=\"u\" direction=\"out\"/></method>"
    + "<method name=\"DisplayPasskey\"><arg type=\"o\" direction=\"in\"/><arg type=\"u\" direction=\"in\"/><arg type=\"q\" direction=\"in\"/></method>"
    + "<method name=\"RequestConfirmation\"><arg type=\"o\" direction=\"in\"/><arg type=\"u\" direction=\"in\"/></method>"
    + "<method name=\"RequestAuthorization\"><arg type=\"o\" direction=\"in\"/></method>"
    + "<method name=\"AuthorizeService\"><arg type=\"o\" direction=\"in\"/><arg type=\"s\" direction=\"in\"/></method>"
    + "<method name=\"Cancel\"/>"
    + "</interface></node>")
REJECTED = "org.bluez.Error.Rejected"

state = {"bus": 0, "registered": False}

function watch(bus):
    state["bus"] = bus
    call gio.watch_name(bus, "org.bluez", on_appeared, on_vanished)
    return 0
end

function on_appeared(name, owner):
    if not state["registered"]:
        ok = True
        try:
            call gio.register_object(state["bus"], AGENT_PATH, AGENT_XML, on_method)
        else:
            ok = False
            call eprint("luxos-hub: bluetooth: " + String(last_error()))
        end
        if not ok:
            return 0
        end
        state["registered"] = True
    end
    call register()
    return 0
end

function on_vanished(name):
    return 0
end

function register():
    try:
        call gio.call_values(state["bus"], "org.bluez", "/org/bluez", "org.bluez.AgentManager1", "RegisterAgent", [AGENT_PATH, "KeyboardDisplay"], "(os)", 3000)
        call gio.call_values(state["bus"], "org.bluez", "/org/bluez", "org.bluez.AgentManager1", "RequestDefaultAgent", [AGENT_PATH], "(o)", 3000)
    else:
        call eprint("luxos-hub: bluetooth agent: " + String(last_error()))
    end
    return 0
end

# [nazev zarizeni, duveryhodne]
function device(path):
    props = {}
    try:
        props = gio.get_all_properties(state["bus"], "org.bluez", path, "org.bluez.Device1")
    else:
        props = {}
    end
    name = props.get("Alias")
    if name == None or name == "":
        name = props.get("Name")
    end
    if name == None or name == "":
        name = path[text.rfind(path, "/") + 1:]
    end
    return [String(name), props.get("Trusted") == True]
end

# Dialog jako Gtk.MessageDialog aplikace luxos-bluetooth: [ok, text pole]
function dialog(primary, secondary, with_entry, with_buttons, ok_label):
    dlg = gtk.dialog_new()
    call gtk.window_set_modal(dlg, True)
    call gtk.window_set_title(dlg, "")
    call gtk.window_set_type_hint(dlg, gtk.TYPE_HINT_DIALOG)
    call gtk.window_set_position(dlg, gtk.WIN_POS_CENTER)
    area = gtk.dialog_get_content_area(dlg)
    call gtk.container_set_border_width(area, 12)
    call gtk.box_set_spacing(area, 10)
    title = gtk.label_new("")
    call gtk.label_set_markup(title, "<big><b>" + glib.markup_escape(primary) + "</b></big>")
    call gtk.label_set_line_wrap(title, True)
    call gtk.label_set_max_width_chars(title, 50)
    call gtk.box_pack_start(area, title, False, False, 0)
    body = gtk.label_new("")
    call gtk.label_set_markup(body, secondary)
    call gtk.label_set_line_wrap(body, True)
    call gtk.label_set_max_width_chars(body, 50)
    call gtk.box_pack_start(area, body, False, False, 0)
    field = 0
    if with_entry:
        field = gtk.entry_new()
        call gtk.entry_set_activates_default(field, True)
        call gtk.box_pack_start(area, field, False, False, 0)
    end
    if with_buttons:
        call gtk.dialog_add_button(dlg, i18n.T("Cancel"), gtk.RESPONSE_CANCEL)
    end
    label = ok_label
    if label == "":
        label = i18n.T("OK")
    end
    ok_button = gtk.dialog_add_button(dlg, label, gtk.RESPONSE_OK)
    call gtk.widget_add_class(ok_button, "suggested-action")
    call gtk.dialog_set_default_response(dlg, gtk.RESPONSE_OK)
    call gtk.widget_show_all(area)
    response = gtk.dialog_run(dlg)
    value = ""
    if field != 0:
        value = gtk.entry_get_text(field)
    end
    call gtk.widget_destroy(dlg)
    return [response == gtk.RESPONSE_OK, value]
end

function on_method(sender, path, interface, method, values, invocation):
    if method == "RequestAuthorization" or method == "AuthorizeService":
        info = device(values[0])
        if method == "AuthorizeService" and info[1]:
            call gio.return_value(invocation, [], "")
            return 0
        end
        question = i18n.TF("Allow “%s” to connect?", [info[0]])
        if method == "RequestAuthorization":
            question = i18n.TF("Allow “%s” to pair with this computer?", [info[0]])
        end
        answer = dialog(question, glib.markup_escape(i18n.T("Only allow devices you know.")), False, True, i18n.T("Allow"))
        if answer[0]:
            call gio.return_value(invocation, [], "")
        else:
            call gio.return_error(invocation, REJECTED, i18n.T("Rejected"))
        end
        return 0
    end
    if method == "RequestConfirmation":
        answer = dialog(i18n.T("Pair this device?"), glib.markup_escape(i18n.T("Check that the device shows this code:")) + "\n\n<big><b>" + text.pad(values[1], 6) + "</b></big>", False, True, i18n.T("Pair"))
        if answer[0]:
            call gio.return_value(invocation, [], "")
        else:
            call gio.return_error(invocation, REJECTED, i18n.T("Rejected"))
        end
    elif method == "DisplayPasskey" or method == "DisplayPinCode":
        code = String(values[1])
        if method == "DisplayPasskey":
            code = text.pad(values[1], 6)
        end
        call dialog(i18n.T("Type this code on the device"), "<big><b>" + glib.markup_escape(code) + "</b></big>\n\n" + glib.markup_escape(i18n.T("Then press Enter on it.")), False, False, "")
        call gio.return_value(invocation, [], "")
    elif method == "RequestPinCode":
        answer = dialog(i18n.T("Enter the PIN code"), glib.markup_escape(i18n.T("Usually 0000 or 1234, see the device manual.")), True, True, "")
        if answer[0] and answer[1] != "":
            call gio.return_value(invocation, [answer[1]], "(s)")
        else:
            call gio.return_error(invocation, REJECTED, i18n.T("Rejected"))
        end
    elif method == "RequestPasskey":
        answer = dialog(i18n.T("Enter the code"), glib.markup_escape(i18n.T("Code shown on the device:")), True, True, "")
        if answer[0] and text.is_digits(answer[1]):
            call gio.return_value(invocation, [Int(answer[1])], "(u)")
        else:
            call gio.return_error(invocation, REJECTED, i18n.T("Rejected"))
        end
    else:
        # Release, Cancel
        call gio.return_value(invocation, [], "")
    end
    return 0
end
