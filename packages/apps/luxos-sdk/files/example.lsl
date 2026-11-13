# SPDX-License-Identifier: MIT
load gtk
load luxui

state = {"count": 0, "status": 0}

function clicked(button):
    state["count"] += 1
    call gtk.label_set_text(state["status"], "Clicks: " + String(state["count"]))
end

function closed(widget):
    call gtk.main_quit()
end

call gtk.init()
window = luxui.window("My LuxOS app", 760, 520)
body = luxui.column(16)
call gtk.widget_set_margin(body, 32)
call gtk.container_add(window, body)
call luxui.add(body, luxui.subtitle("BUILT WITH LSL"))
call luxui.add(body, luxui.heading("Make something useful."))
call luxui.add(body, luxui.subtitle("A native window, your own code, and a small set of reusable components."))
card = luxui.card()
call luxui.add(body, card)
state["status"] = luxui.add(card, luxui.label("Clicks: 0"))
buttons = luxui.row()
call luxui.add(card, buttons)
call luxui.add(buttons, luxui.button("Try it", clicked, True))
call gtk.connect(window, "destroy", closed)
call gtk.widget_show_all(window)
call gtk.main()
