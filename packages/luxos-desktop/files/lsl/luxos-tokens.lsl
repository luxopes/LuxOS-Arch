# LuxOS - vystupy z luxos_tokens.lsl pri sestaveni baliku (a pro testy):
#   luxos-tokens css light|dark          CSS GTK 3 pro klienty shellu na stdout
#   luxos-tokens labwc ADRESAR light|dark tema luxwm: ADRESAR/themerc a tlacitka semaforu (SVG)
#   luxos-tokens rc light|dark           cast <theme> do rc.xml luxwm na stdout
#   luxos-tokens json                    vsechny hodnoty jako JSON (testy, nastroje v C)
load json
load luxos_tokens as tokens

function usage():
    print "usage: luxos-tokens css|rc light|dark | labwc DIR light|dark | json"
    exit(2)
end

function is_dark(mode):
    if mode != "light" and mode != "dark":
        call usage()
    end
    return mode == "dark"
end

if len(args) < 2:
    call usage()
end
cmd = args[1]
if cmd == "css" and len(args) == 3:
    printr tokens.gtk3_css(is_dark(args[2]))
elif cmd == "rc" and len(args) == 3:
    printr tokens.labwc_rc(is_dark(args[2]))
elif cmd == "labwc" and len(args) == 4:
    dark = is_dark(args[3])
    dir = args[2]
    if not exists(dir):
        call mkdir(dir)
    end
    call writefile(dir + "/themerc", tokens.labwc_themerc(dark))
    buttons = tokens.labwc_buttons(dark)
    for name in sorted(buttons.keys()):
        call writefile(dir + "/" + name, buttons[name])
    end
elif cmd == "json" and len(args) == 2:
    print json.encode({"colors": tokens.COLORS, "light": tokens.LIGHT, "dark": tokens.DARK, "radius": tokens.RADIUS,
                       "space": tokens.SPACE, "font": tokens.FONT, "weight": tokens.WEIGHT, "shadow": tokens.SHADOW,
                       "window_shadow": tokens.WINDOW_SHADOW, "motion": tokens.MOTION, "curves": tokens.CURVES,
                       "glass": tokens.GLASS, "window_glass": tokens.WINDOW_GLASS, "ink": tokens.INK, "bar": tokens.BAR})
else:
    call usage()
end
