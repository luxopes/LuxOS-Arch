# Testovaci okno GTK pro test_luxos_wl.py: luxos-wl-window APP_ID TITULEK [barva] [--maximize] [--entry]
# S --entry vypisuje obsah pole po kazde zmene ("text: ..."), pri zavreni "closed".
load glib, gtk
load luxos_sys

app_id = arg(1)
title = arg(2)
color = "#3a6ea5"
maximize = False
with_entry = False
announced = False
index = 3
while index < arg_count():
    if arg(index) == "--maximize":
        maximize = True
    elif arg(index) == "--entry":
        with_entry = True
    else:
        color = arg(index)
    end
    index += 1
end

# radek jednim write(): okna spustena Dockem sdileji jeho stdout a print zapisuje text a konec radku zvlast
# (dve okna zavrena naraz daval "closedclosed")
function say(text):
    call luxos_sys.out(text + "\n")
    return 0
end

function changed(entry):
    call say("text: " + gtk.entry_get_text(entry))
    return 0
end

# "shown" az po namapovani a prvnim vykresleni (snimky obrazovky v testu)
function drawn(cr, widget):
    global announced
    if not announced:
        announced = True
        call say("shown")
    end
    return False
end

function destroyed(widget):
    call say("closed")
    call gtk.main_quit()
    return 0
end

call glib.set_prgname(app_id)
call gtk.init()
call gtk.css_load("window { background: " + color + "; } entry { min-height: 24px; }")
window = gtk.window_new(title)
call gtk.window_set_default_size(window, 320, 200)
call glib.signal_connect(window, "destroy", destroyed, 0)
if with_entry:
    entry = gtk.entry_new()
    call glib.signal_connect(entry, "changed", changed, 0)
    call gtk.container_add(window, entry)
end
if maximize:
    call gtk.window_maximize(window)
end
call glib.signal_connect(window, "draw", drawn, 1)
call gtk.widget_show_all(window)
call gtk.main()
