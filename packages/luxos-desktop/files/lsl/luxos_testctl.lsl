# LuxOS - rizeni okna z testu (jen s LUXOS_TEST_CONTROL=1): prikazy po radcich na stdin, odpovedi na stdout.
# Testy aplikaci v LSL tak klikaji do skutecnych widgetu a ctou, co okno ukazuje (jako testy Pythonu, ktere
# sahaly primo na objekty okna). Bez promenne se nic nespusti.
#   call testctl.start(f)    f(prikaz, zbytek radku) pro prikazy aplikace
# Prikazy: dump (radek "dump {json}": viditelna okna, zda ma HeaderBar zaviraci tlacitko, popisky, tlacitka,
# prepinace, pole, stranka Gtk.Stack a pojmenovane widgety; vis = namapovany), click TEXT (tlacitko podle
# popisku nebo tooltipu, dialogy maji prednost), entry TEXT (prvni pole nejvyssiho okna), respond N (odpoved
# otevreneho dialogu), switch 0|1. Kazdy prikaz bezi az z necinnosti (kliknuti muze otevrit modalni dialog
# s vlastni smyckou) a skonci radkem "done PRIKAZ".
load env, json
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_sys as sys

state = {"handler": None, "buffer": ""}

function start(handler):
    if env.get("LUXOS_TEST_CONTROL", "") != "1":
        return False
    end
    state["handler"] = handler
    # G_IO_IN | G_IO_HUP
    call glib.fd_add_data(0, 1 | 16, on_input, 0)
    return True
end

function on_input(unused, fd, condition):
    got = sys.recv_text(0)
    if got[0] == 0:
        return False
    end
    state["buffer"] = state["buffer"] + got[1]
    cut = state["buffer"].find("\n")
    while cut >= 0:
        line = state["buffer"][:cut]
        state["buffer"] = state["buffer"][cut + 1:]
        if line.strip() != "":
            call glib.idle_add_data(run, line)
        end
        cut = state["buffer"].find("\n")
    end
    return True
end

function run(line):
    space = line.find(" ")
    command = line
    rest = ""
    if space > 0:
        command = line[:space]
        rest = line[space + 1:]
    end
    if command == "dump":
        call sys.out("dump " + json.encode(dump()) + "\n")
    elif command == "click":
        w = find_button(rest)
        if w != 0:
            call gtk.button_clicked(w)
        else:
            call sys.out("missing " + rest + "\n")
        end
    elif command == "entry":
        w = first_of(windows(), "GtkEntry")
        if w != 0:
            call gtk.entry_set_text(w, rest)
        end
    elif command == "respond":
        for win in windows():
            if is_a(win, "dialog"):
                call gtk.dialog_response(win, Int(rest))
                break
            end
        end
    elif command == "switch":
        w = first_of(windows(), "GtkSwitch")
        if w != 0:
            call gtk.switch_set_active(w, rest == "1")
        end
    elif state["handler"] != None:
        handler = state["handler"]
        call handler(command, rest)
    end
    call sys.out("done " + command + "\n")
    return False
end

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

# Typ widgetu: "dialog", "container", "button", "label", "entry", "switch", "spinner", "stack"
function is_a(widget, kind):
    unsafe:
        t = 0
        if kind == "dialog":
            t = __lsl_qbe_call0(__lsl_symbol("gtk_dialog_get_type"))
        elif kind == "container":
            t = __lsl_qbe_call0(__lsl_symbol("gtk_container_get_type"))
        elif kind == "button":
            t = __lsl_qbe_call0(__lsl_symbol("gtk_button_get_type"))
        elif kind == "label":
            t = __lsl_qbe_call0(__lsl_symbol("gtk_label_get_type"))
        elif kind == "entry":
            t = __lsl_qbe_call0(__lsl_symbol("gtk_entry_get_type"))
        elif kind == "switch":
            t = __lsl_qbe_call0(__lsl_symbol("gtk_switch_get_type"))
        elif kind == "spinner":
            t = __lsl_qbe_call0(__lsl_symbol("gtk_spinner_get_type"))
        elif kind == "stack":
            t = __lsl_qbe_call0(__lsl_symbol("gtk_stack_get_type"))
        end
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("g_type_check_instance_is_a"), ptr(widget), t)) != 0
    end
end

function type_name(widget):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_type_name_from_instance"), ptr(widget)))
    end
end

# Viditelna okna aplikace, dialogy na konci (nejvyssi posledni)
function windows():
    all = []
    unsafe:
        list = __lsl_qbe_call0(__lsl_symbol("gtk_window_list_toplevels"))
        node = list
        while node != 0:
            all.append(__lsl_qbe_load64(node))
            node = __lsl_qbe_load64(node + 8)
        end
        call __lsl_qbe_call1(__lsl_symbol("g_list_free"), list)
    end
    plain = []
    dialogs = []
    for win in all:
        if is_toplevel_shown(win):
            if is_a(win, "dialog"):
                dialogs.append(win)
            else:
                plain.append(win)
            end
        end
    end
    return plain + dialogs
end

function is_toplevel_shown(win):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gtk_widget_get_visible"), ptr(win))) != 0 and __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gtk_window_get_window_type"), ptr(win))) == 0
    end
end

# Widget je opravdu na obrazovce (skryta stranka Gtk.Stack ma visible, ale neni namapovana)
function shown(widget):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gtk_widget_get_mapped"), ptr(widget))) != 0
    end
end

function is_sensitive(widget):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gtk_widget_is_sensitive"), ptr(widget))) != 0
    end
end

function children(widget):
    if not is_a(widget, "container"):
        return []
    end
    return gtk.container_get_children(widget)
end

function walk(widget, out):
    out.append(widget)
    for child in children(widget):
        call walk(child, out)
    end
    return out
end

function first_of(wins, kind):
    for i in range(len(wins)):
        win = wins[len(wins) - 1 - i]
        for w in walk(win, []):
            if type_name(w) == kind and shown(w):
                return w
            end
        end
    end
    return 0
end

# Text widgetu: "label", "button", "name" (jmeno widgetu), "title" (titulek okna)
function text_of(widget, kind):
    unsafe:
        raw = 0
        if kind == "label":
            raw = __lsl_qbe_call1(__lsl_symbol("gtk_label_get_text"), ptr(widget))
        elif kind == "button":
            raw = __lsl_qbe_call1(__lsl_symbol("gtk_button_get_label"), ptr(widget))
        elif kind == "name":
            raw = __lsl_qbe_call1(__lsl_symbol("gtk_widget_get_name"), ptr(widget))
        elif kind == "title":
            raw = __lsl_qbe_call1(__lsl_symbol("gtk_window_get_title"), ptr(widget))
        end
        return glib.from_c(raw)
    end
end

function tooltip(widget):
    unsafe:
        return glib.take_c(__lsl_qbe_call1(__lsl_symbol("gtk_widget_get_tooltip_text"), ptr(widget)))
    end
end

function find_button(text):
    wins = windows()
    for i in range(len(wins)):
        for w in walk(wins[len(wins) - 1 - i], []):
            if is_a(w, "button") and shown(w) and (text_of(w, "button") == text or tooltip(w) == text):
                return w
            end
        end
    end
    return 0
end

function describe(w):
    item = {"t": type_name(w), "vis": shown(w), "sens": is_sensitive(w)}
    name = text_of(w, "name")
    if not name.startswith("Gtk"):
        item["name"] = name
    end
    if is_a(w, "label"):
        item["text"] = text_of(w, "label")
    elif is_a(w, "entry"):
        item["text"] = gtk.entry_get_text(w)
    elif is_a(w, "switch"):
        item["active"] = gtk.switch_get_active(w)
    elif is_a(w, "spinner"):
        item["active"] = gtk.object_get_bool(w, "active")
    elif is_a(w, "stack"):
        item["page"] = gtk.stack_get_visible_child_name(w)
    elif is_a(w, "button"):
        item["text"] = text_of(w, "button")
        item["tip"] = tooltip(w)
    elif not item.get("name"):
        return None
    end
    return item
end

# HeaderBar okna je videt a ma zaviraci tlacitko (scripts/check-titlebars.sh u aplikaci v Pythonu)
function close_button(win):
    unsafe:
        bar = __lsl_qbe_call1(__lsl_symbol("gtk_window_get_titlebar"), ptr(win))
        if bar == 0 or __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gtk_widget_get_visible"), bar)) == 0:
            return False
        end
        if __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("g_type_check_instance_is_a"), bar, __lsl_qbe_call0(__lsl_symbol("gtk_header_bar_get_type")))) == 0:
            return False
        end
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gtk_header_bar_get_show_close_button"), bar)) != 0
    end
end

function dump():
    out = []
    for win in windows():
        items = []
        for w in walk(win, []):
            item = describe(w)
            if item != None:
                items.append(item)
            end
        end
        out.append({"title": text_of(win, "title"), "dialog": is_a(win, "dialog"), "close_button": close_button(win),
            "widgets": items})
    end
    return out
end
