# Funkce luxos_xrandr.lsl a geometrie luxos_displays.lsl pro testy v Pythonu (test_luxos_displays.py,
# test_luxos_arrange.py, test_luxos_mirror.py): luxos-xrandr-probe FUNKCE JSON_POLE_ARGUMENTU -> JSON vysledku.
load json
load luxos_xrandr as xr
load luxos_displays as dw

function call_named(name, a):
    if name == "parse":
        return xr.parse(a[0])
    elif name == "current_mode":
        return xr.current_mode(a[0])
    elif name == "preferred_mode":
        return xr.preferred_mode(a[0])
    elif name == "find_mode":
        return xr.find_mode(a[0], a[1])
    elif name == "resolution_choices":
        return xr.resolution_choices(a[0])
    elif name == "fmt_rate":
        return xr.fmt_rate(a[0])
    elif name == "fmt_mode":
        return xr.fmt_mode(a[0])
    elif name == "best_rate":
        return xr.best_rate(a[0], a[1])
    elif name == "edid_id":
        return xr.edid_id(a[0])
    elif name == "edid_name":
        return xr.edid_name(a[0])
    elif name == "output_key":
        return xr.output_key(a[0])
    elif name == "set_key":
        return xr.set_key(a[0])
    elif name == "entry_for":
        return xr.entry_for(a[0], a[1], a[2], a[3])
    elif name == "output_args":
        return xr.output_args(a[0], a[1])
    elif name == "all_output_args":
        return xr.all_output_args(a[0], a[1])
    elif name == "load":
        return xr.load(a[0])
    elif name == "load_layouts":
        return xr.load_layouts(a[0])
    elif name == "load_modes":
        return xr.load_modes(a[0])
    elif name == "save":
        return xr.save(a[0], a[1], a[2], a[3])
    elif name == "text_size_index":
        return xr.text_size_index(a[0])
    elif name == "read_dpi":
        return xr.read_dpi()
    elif name == "set_text_size":
        return xr.set_text_size(a[0])
    elif name == "is_scaled":
        return xr.is_scaled(a[0])
    elif name == "unscale_args":
        return xr.unscale_args(a[0])
    elif name == "rate_cap_target":
        return xr.rate_cap_target(a[0])
    elif name == "rect_size":
        return xr.rect_size(a[0], a[1])
    elif name == "find_layout":
        return xr.find_layout(a[0], a[1])
    elif name == "make_layout":
        return xr.make_layout(a[0], a[1], a[2], a[3])
    elif name == "mode_for":
        return xr.mode_for(a[0], a[1])
    elif name == "with_mode":
        return xr.with_mode(a[0], a[1], a[2])
    elif name == "common_mode":
        return xr.common_mode(a[0], a[1])
    elif name == "mirror_rate":
        return xr.mirror_rate(a[0], a[1])
    elif name == "mirror_plan":
        return xr.mirror_plan(a[0], a[1], a[2], a[3])
    elif name == "plan":
        return xr.plan(a[0], a[1], a[2], a[3])
    elif name == "matches":
        return xr.matches(a[0], a[1])
    elif name == "current_rects":
        return xr.current_rects(a[0])
    elif name == "overlaps":
        return dw.overlaps(a[0], a[1])
    elif name == "touches":
        return dw.touches(a[0], a[1])
    elif name == "valid":
        return dw.valid(a[0])
    elif name == "drop":
        return dw.drop(a[0], a[1], a[2], a[3], a[4], a[5])
    elif name == "settle":
        return dw.settle(a[0], a[1], a[2], a[3])
    end
    print "unknown function " + name
    exit(2)
end

print json.encode(call_named(args[1], json.decode(args[2])))
