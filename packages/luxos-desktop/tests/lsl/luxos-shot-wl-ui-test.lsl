# Testy logiky Wayland UI bez pripojeni ke skutecne relaci.
load json
load cairo
load luxos_shot_wl as ui
load luxos_shot_base as base

ui.S["frames"] = [{"output": 1, "geo": [-640, 0, 640, 480], "w": 640, "h": 480}, {"output": 2, "geo": [0, 0, 1280, 800], "w": 1280, "h": 800}]
ui.S["opts"] = base.defaults()
cmd = arg(1)
if cmd == "norm":
    ui.OV["sel"] = json.decode(arg(2))
    print json.encode(ui.norm_sel())
elif cmd == "reset":
    ui.S["toolbar"] = True
    ui.S["opts"]["selection"] = json.decode(arg(2))
    ui.S["opts"]["remember"] = arg(3) == "1"
    call ui.reset("portion")
    print json.encode(ui.OV["sel"])
elif cmd == "drag":
    ui.S["toolbar"] = True
    ui.OV["drag_rect"] = json.decode(arg(2))
    ui.OV["drag"] = json.decode(arg(3))
    ui.OV["drag_kind"] = arg(4)
    call ui.drag_selection(Int(arg(5)), Int(arg(6)))
    print json.encode(ui.norm_sel())
elif cmd == "windows":
    call ui.windows_reply(json.decode(arg(2)))
    print json.encode([ui.OV["spatial"], ui.window_at(Int(arg(3)), Int(arg(4)))])
elif cmd == "actions":
    ui.TH["path"] = arg(2)
    ui.TH["copied"] = arg(3) == "1"
    print json.encode(ui.thumb_actions())
elif cmd == "selection_image":
    ui.S["toolbar"] = True
    ui.OV["sel"] = [200, 150, 400, 300]
    img = cairo.image_surface_create(cairo.FORMAT_ARGB32, 1280, 800)
    cr = cairo.create(img)
    call cairo.set_source_rgb(cr, 0.7, 0.7, 0.7)
    call cairo.paint(cr)
    call ui.draw_selection(cr, {"geo": [0, 0, 1280, 800]}, 1280, 800)
    print cairo.surface_write_to_png(img, arg(2))
    call cairo.destroy(cr)
    call cairo.surface_destroy(img)
end
