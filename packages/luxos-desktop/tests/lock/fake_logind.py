#!/usr/bin/env python3
"""Napodobeny logind pro test_luxos_lock.py na soukrome sbernici (nikdy na systemove).

    fake_logind.py ADRESA_SBERNICE

Manager: GetSession, GetSessionByPID, Inhibit (vraci konec roury; zavreni = uvolneni inhibitoru),
signal PrepareForSleep. Session /org/freedesktop/login1/session/_31: SetLockedHint, signaly Lock a Unlock.
Prikazy na stdin (radek): sleep, resume, lock, unlock. Na stdout radky "UDALOST cas_ms" (CLOCK_MONOTONIC):
ready, inhibit WHAT MODE, inhibitor-released, locked-hint True|False, sent PRIKAZ.
"""
import os
import sys
import time

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

SESSION = "/org/freedesktop/login1/session/_31"


def say(*parts):
    print(*parts, int(time.monotonic() * 1000), flush=True)


class Session(dbus.service.Object):
    @dbus.service.method("org.freedesktop.login1.Session", in_signature="b")
    def SetLockedHint(self, on):
        say("locked-hint", bool(on))

    @dbus.service.signal("org.freedesktop.login1.Session")
    def Lock(self):
        pass

    @dbus.service.signal("org.freedesktop.login1.Session")
    def Unlock(self):
        pass


class Manager(dbus.service.Object):
    @dbus.service.method("org.freedesktop.login1.Manager", in_signature="s", out_signature="o")
    def GetSession(self, sid):
        return SESSION

    @dbus.service.method("org.freedesktop.login1.Manager", in_signature="u", out_signature="o")
    def GetSessionByPID(self, pid):
        return SESSION

    @dbus.service.method("org.freedesktop.login1.Manager", in_signature="ssss", out_signature="h")
    def Inhibit(self, what, who, why, mode):
        read, write = os.pipe()
        say("inhibit", what, mode)

        def gone(fd, cond):
            say("inhibitor-released")
            os.close(fd)
            return False
        GLib.io_add_watch(read, GLib.IO_HUP | GLib.IO_ERR, gone)
        reply = dbus.types.UnixFd(write)
        os.close(write)
        return reply

    @dbus.service.signal("org.freedesktop.login1.Manager", signature="b")
    def PrepareForSleep(self, start):
        pass


def main():
    DBusGMainLoop(set_as_default=True)
    bus = dbus.bus.BusConnection(sys.argv[1])
    name = dbus.service.BusName("org.freedesktop.login1", bus)
    manager = Manager(bus, "/org/freedesktop/login1")
    session = Session(bus, SESSION)
    commands = {"sleep": lambda: manager.PrepareForSleep(True), "resume": lambda: manager.PrepareForSleep(False),
                "lock": session.Lock, "unlock": session.Unlock}

    def command(fd, cond):
        line = sys.stdin.readline()
        if not line:
            loop.quit()
            return False
        word = line.strip()
        if word in commands:
            commands[word]()
            say("sent", word)
        return True
    GLib.io_add_watch(sys.stdin.fileno(), GLib.IO_IN | GLib.IO_HUP, command)
    loop = GLib.MainLoop()
    say("ready")
    loop.run()
    del name


if __name__ == "__main__":
    main()
