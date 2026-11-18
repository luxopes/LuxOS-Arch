# LuxOS - karta matneho skla (material widgetu na plose) pro obdelnik obrazovky do PNG.
# Pro okna, ktera nekresli GTK: Hledani (rofi) ma obrazek jako pozadi okna (background-image).
#
#   luxos-glass-image X Y SIRKA VYSKA light|dark VYSTUP.png [POLOMER]
#     light = svetle sklo s tmavym textem, dark = tmave sklo s bilym textem
# Kod 0 = obrazek zapsan, 1 = bez tapety (program pak pouzije sve pozadi), 2 = spatne argumenty.
load env
load luxos_gtk, gtk as gtk
load luxos_glass as glass

function main():
    if arg(6) == None or (arg(5) != "light" and arg(5) != "dark"):
        call sys_usage()
        return 2
    end
    x = Int(arg(1))
    y = Int(arg(2))
    w = Int(arg(3))
    h = Int(arg(4))
    if w < 2 or h < 2:
        call sys_usage()
        return 2
    end
    radius = 0
    if arg(7) != None:
        radius = Int(arg(7))
    end
    call gtk.init()
    if glass.panel_png(arg(6), x, y, w, h, radius, arg(5) == "light"):
        return 0
    end
    return 1
end

function sys_usage():
    print "Usage: luxos-glass-image X Y WIDTH HEIGHT light|dark OUTPUT.png [RADIUS]"
    return 0
end

call exit(main())
