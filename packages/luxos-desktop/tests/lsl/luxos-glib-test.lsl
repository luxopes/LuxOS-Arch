# Test spawn_capture/spawn_stream z luxos_glib: vystup delsi nez jeden kus cteni (4096 B) s vicebajtovymi
# znaky na hranici kusu. Vypise zachyceny text (capture) a pak slozeny proud (stream), kazdy na radek.
load luxos_glib
load glib

result = {"stream": "", "done": 0}

function on_capture(unused, out, status):
    print(out)
    call finished()
    return 0
end

function on_stream(unused, chunk):
    if chunk == "":
        print(result["stream"])
        call finished()
        return 0
    end
    result["stream"] = result["stream"] + chunk
    return 0
end

function finished():
    result["done"] = result["done"] + 1
    if result["done"] == 2:
        call glib.main_quit()
    end
    return 0
end

# arg(0) je cesta k programu: bez prikazu konec (jinak by "sh -c" mohl spoustet sam sebe)
cmd = arg(1)
if cmd == "" or cmd == None:
    exit(2)
end
call luxos_glib.spawn_capture(["sh", "-c", cmd], on_capture, 0)
call luxos_glib.spawn_stream(["sh", "-c", cmd], on_stream, 0)
call glib.main()
