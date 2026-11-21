# Test luxos_mpris.lsl a luxos_awake.lsl (test_luxos_awake.py) na soukrome sbernici.
#   luxos-awake-probe pure      ciste funkce: radky "ok NAZEV" / "FAIL NAZEV ..."
#   luxos-awake-probe external  "external True|False" podle LUXOS_DRM_DIR
#   luxos-awake-probe mpris     hlidac prehravacu: po kazde zmene "changed {json}"; stdin "send NAZEV METODA"
#   luxos-awake-probe awake     mpris + awake jako v luxos-hub; stdin "quit" = awake.shutdown() a konec
load json
load gio as dbus
load luxos_glib, glib as glib
load luxos_sys as sys
load luxos_mpris as mpris
load luxos_awake as awake

failures = 0
buffer = ""

function expect(name, got, want):
    global failures
    if got == want:
        print "ok " + name
    else:
        failures += 1
        print "FAIL " + name + " got " + String(got) + " want " + String(want)
    end
    return 0
end

function pure():
    st = mpris.player_state("org.mpris.MediaPlayer2.firefox.instance_1_23", {"PlaybackStatus": "Playing", "Metadata": {"xesam:title": "T", "xesam:artist": ["A", "B"]}})
    call expect("player-state", [st["app"], st["title"], st["artist"], st["playing"]], ["Firefox", "T", "A, B", True])
    players = {"org.mpris.MediaPlayer2.a": {"PlaybackStatus": "Paused", "Metadata": {"xesam:title": "x"}},
               "org.mpris.MediaPlayer2.b": {"PlaybackStatus": "Playing"},
               "org.mpris.MediaPlayer2.c": {"PlaybackStatus": "Stopped"}}
    call expect("pick-playing", mpris.pick_current(players)["bus"], "org.mpris.MediaPlayer2.b")
    players["org.mpris.MediaPlayer2.b"]["PlaybackStatus"] = "Stopped"
    call expect("pick-paused", mpris.pick_current(players)["bus"], "org.mpris.MediaPlayer2.a")
    call expect("pick-none", mpris.pick_current({"org.mpris.MediaPlayer2.c": {"PlaybackStatus": "Stopped"}}), None)

    call expect("plan-override", awake.plan_override({"lid-action-on-battery": 1, "lid-action-on-ac": 3, "inactivity-on-battery": 14, "inactivity-on-ac": 60}),
                {"lid-action-on-battery": [1, 0], "inactivity-on-ac": [60, 14]})
    call expect("plan-override-empty", awake.plan_override({"lid-action-on-battery": 0}), {})
    # 30 nastavil mezitim uzivatel
    call expect("plan-restore", awake.plan_restore({"lid-action-on-battery": 1, "inactivity-on-ac": 60}, {"lid-action-on-battery": 0, "inactivity-on-ac": 30}),
                {"lid-action-on-battery": 1})
    call expect("lid-suspend", awake.lid_sleep_action({"lid-action-on-battery": 1}, True, True, False), "Suspend")
    call expect("lid-hibernate", awake.lid_sleep_action({"lid-action-on-battery": 2}, True, True, False), "Hibernate")
    call expect("lid-open", awake.lid_sleep_action({"lid-action-on-battery": 1}, True, False, False), None)
    call expect("lid-external", awake.lid_sleep_action({"lid-action-on-battery": 1}, True, True, True), None)
    # na AC bez zmeny
    call expect("lid-ac", awake.lid_sleep_action({"lid-action-on-battery": 1}, False, True, False), None)
    return failures
end

function report():
    print "changed " + json.encode({"playing": mpris.playing(), "current": mpris.current(), "players": sorted(mpris.players.keys())})
    return 0
end

function on_input(unused, fd, condition):
    global buffer
    got = sys.recv_text(0)
    if got[0] == 0:
        call glib.main_quit()
        return False
    end
    buffer = buffer + got[1]
    cut = buffer.find("\n")
    while cut >= 0:
        words = buffer[:cut].strip().split(" ")
        buffer = buffer[cut + 1:]
        if words[0] == "send":
            call mpris.send(words[1], words[2])
        elif words[0] == "quit":
            call awake.shutdown()
            print "bye"
            call glib.main_quit()
            return False
        end
        cut = buffer.find("\n")
    end
    return True
end

mode = args[1]
if mode == "pure":
    call exit(pure())
elif mode == "external":
    print "external " + String(awake.external_monitor())
else:
    session = dbus.session_bus()
    call mpris.init(session)
    if mode == "mpris":
        call mpris.connect(report)
    else:
        call awake.init(session, dbus.system_bus())
        print "ready"
    end
    # G_IO_IN | G_IO_HUP
    call glib.fd_add_data(0, 1 | 16, on_input, 0)
    call glib.main()
end
