# Testovaci lista na vrstve (test_luxos_wl.py): luxos-layer-test [vyska] [barva]
# Ukotvena nahore pres celou sirku, vyhradni zona = vyska. Vypise stav vazby a "mapped" po zobrazeni.
load luxos_layer as layer
load luxos_wl as wl
load glib, gtk

height = 32
color = "#ff0000"
if arg_count() > 1:
    height = Int(arg(1))
end
if arg_count() > 2:
    color = arg(2)
end

function event(kind, handle, a, b):
    if kind == wl.TOPLEVEL_NEW:
        print "toplevel " + wl.toplevel_app_id(handle)
    end
    return 0
end

function mapped(event, widget):
    print "mapped"
    return 0
end

call gtk.init()
print "supported " + String(layer.is_supported())
print "protocol " + String(layer.protocol_version())
print "monitors " + String(len(layer.monitors()))
call gtk.css_load("window { background: " + color + "; }")
window = gtk.window_new("luxos-layer-test")
call layer.init_for_window(window)
call layer.set_namespace(window, "luxos-test-bar")
call layer.set_layer(window, layer.LAYER_TOP)
call layer.set_anchors(window, [layer.EDGE_TOP, layer.EDGE_LEFT, layer.EDGE_RIGHT])
call layer.set_keyboard_mode(window, layer.KEYBOARD_NONE)
call layer.auto_exclusive_zone_enable(window)
call gtk.widget_set_size_request(window, -1, height)
print "layer " + String(layer.is_layer_window(window)) + " " + String(layer.get_layer(window)) + " " + layer.get_namespace(window)
print "anchors " + String(layer.get_anchor(window, layer.EDGE_TOP)) + " " + String(layer.get_anchor(window, layer.EDGE_BOTTOM))
print "auto-zone " + String(layer.auto_exclusive_zone_is_enabled(window))
call glib.signal_connect(window, "map-event", mapped, 1)
call gtk.widget_show_all(window)
# jedno spojeni: protokoly luxos_wl na soketu GDK
if wl.available():
    call wl.on_event(event)
    print "attach " + String(wl.attach(layer.wl_display()))
    print "outputs " + String(len(wl.outputs()))
end
call gtk.main()
