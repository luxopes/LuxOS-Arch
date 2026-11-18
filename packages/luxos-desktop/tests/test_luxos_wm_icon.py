#!/usr/bin/env python3
"""LuxOS - testy zapisu ikony okna (luxos_wm_icon.py).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_wm_icon.py -v

Obsluha chyb X (XSetErrorHandler) plati pro cely proces. Zapis _NET_WM_ICON v aplikaci GTK ji smi
zmenit jen docasne a pak vratit puvodni obsluhu GDK; nastavena funkce ctypes musi zit po celou dobu
behu (uvolnena funkce = pad aplikace pri pristi chybe X). Bez X serveru, Xlib je nahrazena.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "files", "python"))
os.environ.pop("DISPLAY", None)
import luxos_wm_icon  # noqa: E402


class FakeLib:
    def __init__(self):
        self.handler = 1234   # puvodni obsluha (GDK)
        self.calls = []

    def XOpenDisplay(self, _name):
        return 42

    def XSetErrorHandler(self, h):
        prev, self.handler = self.handler, h
        self.calls.append(h)
        return prev

    def XInternAtom(self, *_a):
        return 1

    def XChangeProperty(self, *_a):
        return 0

    def XFlush(self, _d):
        return 0

    def XCloseDisplay(self, _d):
        return 0


class X11Window:
    def get_xid(self):
        return 7


class FakeWin:
    def get_window(self):
        return X11Window()


class WriteIconTest(unittest.TestCase):
    def setUp(self):
        self.lib = FakeLib()
        self._orig = luxos_wm_icon.x11
        luxos_wm_icon.x11 = lambda: self.lib
        self._argb = luxos_wm_icon._argb
        luxos_wm_icon._argb = lambda _pb: [1, 1, 0]

    def tearDown(self):
        luxos_wm_icon.x11 = self._orig
        luxos_wm_icon._argb = self._argb

    def test_previous_handler_restored(self):
        luxos_wm_icon._write_net_wm_icon(FakeWin(), [object()])
        self.assertEqual(self.lib.handler, 1234)

    def test_installed_handler_is_module_global(self):
        luxos_wm_icon._write_net_wm_icon(FakeWin(), [object()])
        self.assertIs(self.lib.calls[0], luxos_wm_icon._IGNORE_X_ERRORS)

    def test_restored_even_on_error(self):
        def boom(*_a):
            raise RuntimeError("x")
        self.lib.XChangeProperty = boom
        with self.assertRaises(RuntimeError):
            luxos_wm_icon._write_net_wm_icon(FakeWin(), [object()])
        self.assertEqual(self.lib.handler, 1234)

    def test_handler_ignores_errors(self):
        self.assertEqual(luxos_wm_icon._IGNORE_X_ERRORS(None, None), 0)


if __name__ == "__main__":
    unittest.main()
