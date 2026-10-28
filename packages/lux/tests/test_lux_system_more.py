"""Testy dalsich oblasti lux system: sit (NetworkManager), tiskarny (CUPS), napajeni (logind, profily),
zavadec (cas nabidky, vychozi polozka), ovladace, jazykove formaty, konzole, zamceni po spatnych heslech,
vychozi nastaveni novych uzivatelu, repozitare (jen kontrola), init --auto/--refresh a lux system fix.

    python3 packages/lux/tests/test_lux_system_more.py -v

Stejne prostredi jako test_lux_system.py: docasny koren (LUX_SYSTEM_ROOT), vsechny nastroje (nmcli,
lpadmin, bootctl, powerprofilesctl, systemctl ...) jsou zastupne skripty, ktere jen zapisi argumenty.
Skutecny system, sit ani tiskarny se nikdy nemeni.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_lux_system import Base, ls, need_lsl, write  # noqa: E402

I18N = os.path.join(HERE, "..", "..", "luxos-i18n", "files")
HOME_UUID = "11111111-1111-1111-1111-111111111111"
OFFICE_UUID = "22222222-2222-2222-2222-222222222222"
VPN_UUID = "33333333-3333-3333-3333-333333333333"

HOME_WIFI = f"""[connection]
id=Domácí Wi-Fi
uuid={HOME_UUID}
type=wifi

[wifi]
mode=infrastructure
ssid=Novakovi

[wifi-security]
key-mgmt=wpa-psk
psk=SECRET-PSK-123

[ipv4]
method=auto

[ipv6]
addr-gen-mode=default
method=auto

[proxy]
"""

OFFICE = f"""[connection]
id=Kancelar
uuid={OFFICE_UUID}
type=ethernet
autoconnect=false
interface-name=enp3s0

[ethernet]

[ipv4]
address1=192.168.10.5/24,192.168.10.1
dns=192.168.10.1;1.1.1.1;
method=manual

[ipv6]
method=disabled

[proxy]
method=auto
pac-url=http://proxy.firma.cz/proxy.pac
"""

VPN = f"""[connection]
id=Firma VPN
uuid={VPN_UUID}
type=vpn
autoconnect=false

[vpn]
service-type=org.freedesktop.NetworkManager.openvpn
password-flags=1

[vpn-secrets]
password=VPN-SECRET-456
"""


def efi(value):
    return b"\x07\x00\x00\x00" + value.encode("utf-16-le") + b"\x00\x00"


class More(Base):
    def setUp(self):
        super().setUp()
        r, f = self.root, self.fake
        nm = r + ls.NM_DIR
        write(nm + "/Domaci.nmconnection", HOME_WIFI, 0o600)
        write(nm + "/Kancelar.nmconnection", OFFICE, 0o600)
        write(nm + "/vpn.nmconnection", VPN, 0o600)
        write(f + "/active", HOME_UUID + "\n")
        write(f + "/cups", "device for HP_LaserJet: ipp://hp.local/ipp/print\n"
                           "device for Stitky: usb://Brother/QL-700?serial=1\n")
        write(f + "/cups_default", "HP_LaserJet")
        write(f + "/lpoptions_HP_LaserJet", "copies=1 printer-is-shared=false "
                                            "printer-make-and-model='HP LaserJet Pro M404 - IPP Everywhere'\n")
        write(f + "/lpoptions_Stitky", "printer-is-shared=true printer-make-and-model='Brother QL-700 CUPS'\n")
        write(f + "/lpinfo", "everywhere IPP Everywhere\n"
                             "brother/ql700.ppd Brother QL-700 CUPS\n"
                             "drv:///sample.drv/generic.ppd Generic PostScript Printer\n")
        write(r + "/etc/systemd/logind.conf", "[Login]\n#HandleLidSwitch=suspend\n")
        write(r + "/usr/lib/systemd/logind.conf.d/10-vendor.conf", "[Login]\nHandleLidSwitch=lock\n")
        write(r + "/etc/systemd/logind.conf.d/20-admin.conf", "[Login]\nIdleAction=suspend\nIdleActionSec=45min\n")
        write(r + ls.PPD_STATE, "[State]\nCpuDriver=amd_pstate\nProfile=balanced\n")
        write(r + "/boot/loader/loader.conf", "default luxos.conf\ntimeout 0\nconsole-mode max\neditor no\n")
        os.makedirs(r + ls.EFIVARS, exist_ok=True)
        with open(f"{r}{ls.EFIVARS}/LoaderConfigTimeout-{ls.EFI_LOADER_GUID}", "wb") as fh:
            fh.write(efi("3"))
        write(r + "/boot/loader/entries/auto-windows.conf", "title Windows\n")
        write(r + ls.FAILLOCK_CONF, "# Configuration for locking the user\n# deny = 3\ndeny = 20\n"
                                    "fail_interval = 30\n# unlock_time = 600\nunlock_time = 60\n")
        write(r + ls.VCONSOLE_CONF, "KEYMAP=cz-qwertz\n")
        write(r + ls.SCHED_CONF, "# LuxOS\nSCHEDULER=lavd\nARGS=\n")
        write(r + ls.LUX_CONF, "# lux\naur                 on            # komunita\nflatpak  off\n"
                               "repo luxos\n    server  https://example.org/$repo\nrepo core\n"
                               "    mirrors  /etc/lux/mirrorlist\ninclude  /etc/lux/conf.d/*.conf\n")
        write(r + "/etc/lux/conf.d/extra.conf", "repo extra\n    mirrors  /etc/lux/mirrorlist\n")
        write(f + "/explicit", "base\nlinux-zen\nlux\nfirefox\nvim\nufw\nnvidia-open-dkms\nsamsung-unified-driver\n")
        write(f + "/drivers_repo", "samsung-unified-driver\nbrother-hll2350dw\n")
        write(f + "/repo", "htop\nneovim\nlibfoo\nflatpak\nufw\nbrother-hll2350dw\n")

    def show(self):
        rc, text = self.main("show")
        self.assertEqual(rc, 0, text)
        return text


class StateMoreTest(More):
    def test_reads_new_areas(self):
        st = ls.State()
        cons = st.connections()
        self.assertEqual(sorted(cons), ["Domácí Wi-Fi", "Firma VPN", "Kancelar"])
        home = cons["Domácí Wi-Fi"]
        self.assertEqual((home["type"], home["ssid"], home["security"], home["autoconnect"]),
                         ("wifi", "Novakovi", "wpa-psk", True))
        self.assertNotIn("SECRET", json.dumps(cons))           # hesla se nikdy nectou do stavu
        off = cons["Kancelar"]
        self.assertEqual(off["ipv4"], {"method": "manual", "addresses": ["192.168.10.5/24"],
                                       "gateway": "192.168.10.1", "dns": ["192.168.10.1", "1.1.1.1"]})
        self.assertEqual((off["autoconnect"], off["interface"], off["proxy"]),
                         (False, "enp3s0", "http://proxy.firma.cz/proxy.pac"))
        self.assertEqual(st.active_connections(), {HOME_UUID})
        pr = st.printers()
        self.assertEqual(pr["default"], "HP_LaserJet")
        self.assertEqual(pr["queues"]["HP_LaserJet"], {"uri": "ipp://hp.local/ipp/print", "model": "everywhere",
                                                       "shared": False})
        self.assertEqual(pr["queues"]["Stitky"]["model"], "Brother QL-700 CUPS")
        self.assertEqual(st.power(), {"lid": "lock", "lid_on_power": "lock", "suspend_after_minutes": 45,
                                      "profile": "balanced"})
        bt = st.boot_settings()
        self.assertEqual((bt["timeout"], bt["default"]), (3, "luxos"))     # EFI promenna ma prednost
        self.assertEqual(st.faillock(), {"deny": 20, "fail_interval": 30, "unlock_time": 60})
        self.assertEqual(st.console(), {"keymap": "cz-qwertz"})
        self.assertEqual(st.formats(), {"LC_TIME": "cs_CZ.UTF-8"})
        self.assertEqual(st.drivers(), {"nvidia-open-dkms", "samsung-unified-driver"})
        self.assertEqual(st.repos(), {"list": ["luxos", "core", "extra"], "community": True,
                                      "review_build_scripts": True, "flatpak_updates": False, "channel": "stable"})
        self.assertEqual(st.new_users(), {})

    def test_cups_not_running(self):
        os.unlink(self.fake + "/cups")
        self.assertIsNone(ls.State().printers())

    def test_network_unreadable_without_root(self):
        os.chmod(self.root + ls.NM_DIR, 0)
        try:
            if os.access(self.root + ls.NM_DIR, os.R_OK):
                self.skipTest("running as root")
            self.assertIsNone(ls.State().connections())
        finally:
            os.chmod(self.root + ls.NM_DIR, 0o700)

    def test_new_lux_conf_format(self):
        """Tabulky ([repo.JMENO], klic = hodnota) - novy format lux.conf se cte stejnou funkci."""
        write(self.root + ls.LUX_CONF, "[packages]\naur = false\nreview-pkgbuild = true\n\n[repo.luxos]\n"
                                       "server = \"https://example.org\"\n\n[repo.core]\nmirrors = \"x\"\n")
        self.assertEqual(ls.lux_conf_settings(), {"list": ["luxos", "core"], "community": False,
                                                  "review_build_scripts": True, "flatpak_updates": True, "channel": "stable"})


class NormalizeMoreTest(More):
    def test_secrets_refused(self):
        _c, errors = ls.normalize({"network": {"connections": {"Home": {"type": "wifi", "ssid": "x", "psk": "abc"}}},
                                   "users": {"anna": {"password": "x"}}})
        text = "\n".join(errors)
        self.assertIn("never write Wi-Fi or VPN passwords into the file", text)
        self.assertIn("never write passwords into the file", text)

    def test_errors(self):
        _c, errors = ls.normalize({
            "network": {"connections": {"A": {"ipv4": {"method": "manual", "dns": ["1.1.1.999"]}},
                                        "B": {"type": "ethernet", "ssid": "x"}}},
            "printers": {"queues": {"bad name": {}, "P": {"uri": "not a uri"}}},
            "power": {"lid": "explode", "suspend_after_minutes": -1, "profile": "turbo"},
            "boot": {"default": "luxos-snapshot-2026", "timeout": 999},
            "security": {"faillock": {"deny": 0, "unlock_time": 60, "x": 1}},
            "new_users": {"theme": "pink", "wallpaper": "relative.jpg", "dock": ["firefox", "bad id!"]},
            "formats": {"LC_TIME": "xx_YY.UTF-8", "LC_FOO": "cs_CZ.UTF-8"},
            "drivers": ["vim"], "packages": ["vim"],
            "repos": {"list": ["luxos"], "mirrors": True},
        })
        text = "\n".join(errors)
        for needle in ('"manual" needs "addresses"', '"1.1.1.999" is not a valid IP address',
                       '"ssid" and "security" belong only to Wi-Fi', '"bad name" is not a valid printer name',
                       '"not a uri" is not a valid printer address', "power.lid: must be one of",
                       "power.suspend_after_minutes: must be between 0 and 1440", "power.profile: must be one of",
                       "boot.default: must be \"luxos\"", "boot.timeout: must be between 0 and 300",
                       "security.faillock.deny: must be between 1 and 1000", 'unknown setting "x"',
                       "new_users.theme: must be one of", "new_users.wallpaper: must be the full path",
                       '"bad id!" is not a valid app ID', 'formats.LC_TIME: unknown language setting',
                       'unknown setting "LC_FOO"', "vim is both in packages and drivers", 'unknown setting "mirrors"'):
            self.assertIn(needle, text)

    def test_shortcuts(self):
        cfg, errors = ls.normalize({"network": {"connections": {"Home": {"ipv4": "auto"}}},
                                    "new_users": {"dock": ["firefox", "trash"], "browser": "firefox"}})
        self.assertEqual(errors, [])
        self.assertEqual(cfg["network"]["connections"]["Home"], {"ipv4": {"method": "auto"}})
        self.assertEqual(cfg["new_users"], {"dock": ["firefox.desktop", "trash"], "browser": "firefox.desktop"})


class PlanMoreTest(More):
    def test_network(self):
        plan = self.plan({"network": {"connections": {
            "Kancelar": {"autoconnect": True, "ipv4": {"method": "manual", "addresses": ["192.168.10.6/24"],
                                                       "gateway": "192.168.10.1", "dns": ["192.168.10.1", "1.1.1.1"]},
                         "proxy": ""},
            "Domácí Wi-Fi": {"ipv6": {"method": "disabled"}},
            "Chata": {"type": "wifi", "ssid": "Chata", "security": "sae"},
        }}}, applied={"connections": ["Firma VPN", "Domácí Wi-Fi", "Kancelar"]})
        texts = self.texts(plan)
        self.assertIn("network + add connection Chata (Wi-Fi Chata)", texts)
        self.assertIn("network ~ change connection Kancelar: connection.autoconnect yes, ipv4.addresses "
                      "192.168.10.6/24, proxy.method none, proxy.pac-url ", texts)
        self.assertIn("network - delete connection Firma VPN", texts)
        home = [c for c in plan.changes if c.target == "Domácí Wi-Fi"][0]
        self.assertTrue(home.risky)                       # pouzivane pripojeni: zvlast potvrzeni
        self.assertIn("in use", home.text)
        self.assertFalse([c for c in plan.changes if c.target == "Kancelar"][0].risky)
        add = [c for c in plan.changes if c.target == "Chata"][0]
        add.action()
        call = self.calls()[-1]
        self.assertIn("connection add type wifi con-name Chata 802-11-wireless.ssid Chata "
                      "802-11-wireless-security.key-mgmt sae", call)
        self.assertNotIn("psk", call)
        self.assertTrue(any("password is not in the file" in n for n in plan.notes))

    def test_active_connection_not_deleted_without_force(self):
        cfg, _e = ls.normalize({"network": {"connections": {}}})
        plan = ls.compute(cfg, ls.State(), {"connections": ["Domácí Wi-Fi"]})
        self.assertEqual(self.texts(plan), [])
        self.assertEqual(plan.kept_connections, ["Domácí Wi-Fi"])
        self.assertTrue(any("is in use and was kept" in n for n in plan.notes))
        plan = ls.compute(cfg, ls.State(), {"connections": ["Domácí Wi-Fi"]}, force=True)
        self.assertEqual(self.texts(plan), ["network - delete connection Domácí Wi-Fi"])
        self.assertTrue(plan.changes[0].risky)

    def test_network_creation_limits(self):
        for c, msg in (({"type": "vpn"}, "only Wi-Fi and Ethernet"), ({"type": "wifi"}, "needs \"ssid\""),
                       ({"ssid": "Firma", "security": "wpa-eap"}, "enterprise Wi-Fi")):
            cfg, errors = ls.normalize({"network": {"connections": {"New": c}}})
            self.assertEqual(errors, [])
            with self.assertRaises(ls.UserError) as cm:
                ls.compute(cfg, ls.State(), {})
            self.assertIn(msg, str(cm.exception))

    def test_printers(self):
        plan = self.plan({"printers": {"default": "Stitky", "queues": {
            "HP_LaserJet": {"uri": "ipp://hp.local/ipp/print", "model": "everywhere", "shared": True},
            "Novy": {"uri": "socket://10.0.0.9", "model": "Generic PostScript Printer"},
        }}}, applied={"printers": ["HP_LaserJet", "Stitky", "Stara"]})
        self.assertEqual(self.texts(plan), [
            "printers ~ printer HP_LaserJet: shared: True",
            "printers + add printer Novy (socket://10.0.0.9)",
            "printers ~ default printer: HP_LaserJet → Stitky",
            "printers - remove printer Stitky",
        ])
        for c in plan.changes:
            c.action()
        self.assertEqual(self.calls(), [
            "lpadmin -p HP_LaserJet -o printer-is-shared=true",
            "lpadmin -p Novy -E -v socket://10.0.0.9 -m drv:///sample.drv/generic.ppd -o printer-is-shared=false",
            "lpadmin -d Stitky", "lpadmin -x Stitky"])
        cfg, _e = ls.normalize({"printers": {"queues": {"X": {"uri": "ipp://x", "model": "Nonexistent 3000"}}}})
        with self.assertRaises(ls.UserError) as cm:
            ls.compute(cfg, ls.State(), {})
        self.assertIn("the driver \"Nonexistent 3000\" is not installed", str(cm.exception))

    def test_printers_without_cups(self):
        os.unlink(self.fake + "/cups")
        plan = self.plan({"printers": {"queues": {"X": {"uri": "ipp://x"}}}})
        self.assertEqual(self.texts(plan), [])
        self.assertTrue(any("CUPS" in w for w in plan.warnings))

    def test_power(self):
        plan = self.plan({"power": {"lid": "suspend", "lid_on_power": "ignore", "suspend_after_minutes": 0,
                                    "profile": "power-saver"}})
        self.assertEqual(self.texts(plan), [
            "power ~ lid: lock → suspend, lid_on_power: lock → ignore, suspend_after_minutes: 45 → 0",
            "power ~ power profile: balanced → power-saver"])
        for c in plan.changes:
            c.action()
        with open(self.root + ls.LOGIND_DROPIN) as f:
            text = f.read()
        self.assertIn("[Login]\nHandleLidSwitch=suspend\nHandleLidSwitchExternalPower=ignore\nIdleAction=ignore\n", text)
        self.assertEqual(self.calls(), ["systemctl kill --signal=SIGHUP systemd-logind.service",
                                        "powerprofilesctl set power-saver"])
        self.assertEqual(ls.State().power()["suspend_after_minutes"], 0)
        # Sporic baterie meni profil sam - jen poznamka
        write(self.root + ls.POWERSAVER_MARK, "")
        plan = self.plan({"power": {"profile": "performance"}})
        self.assertEqual(self.texts(plan), [])
        self.assertTrue(any("Battery Saver" in n for n in plan.notes))

    def test_boot_sdboot(self):
        plan = self.plan({"boot": {"timeout": 5, "default": "auto-windows"}})
        self.assertEqual(self.texts(plan), ["boot ~ boot menu shown for: 3 → 5 s",
                                            "boot ~ default boot entry: luxos → auto-windows"])
        for c in plan.changes:
            c.action()
        self.assertEqual(self.calls(), ["bootctl set-timeout 5", "bootctl set-default auto-windows"])
        with open(self.root + "/boot/loader/loader.conf") as f:
            self.assertIn("default luxos.conf", f.read())     # loader.conf (LuxOS Care) se nemeni
        with open(f"{self.root}{ls.EFIVARS}/LoaderEntryDefault-{ls.EFI_LOADER_GUID}", "wb") as fh:
            fh.write(efi("auto-windows"))
        plan = self.plan({"boot": {"default": "luxos"}})
        plan.changes[0].action()
        self.assertEqual(self.calls()[-1], "bootctl set-default ")   # prazdne = zpet na loader.conf (luxos*)
        cfg, _e = ls.normalize({"boot": {"default": "nonexistent"}})
        with self.assertRaises(ls.UserError):
            ls.compute(cfg, ls.State(), {})

    def test_boot_grub(self):
        import shutil
        shutil.rmtree(self.root + "/boot/loader")
        write(self.root + "/boot/grub/grub.cfg", "x")
        write(self.root + "/etc/default/grub", 'GRUB_TIMEOUT=5\nGRUB_DEFAULT=0\nGRUB_CMDLINE_LINUX_DEFAULT="quiet"\n')
        plan = self.plan({"boot": {"timeout": 2, "default": "luxos"}})
        self.assertEqual(self.texts(plan), ["boot ~ boot menu shown for: 5 → 2 s"])
        plan.changes[0].action()
        with open(self.root + "/etc/default/grub") as f:
            self.assertIn("GRUB_TIMEOUT=2\nGRUB_DEFAULT=0\n", f.read())
        self.assertIn("grub-mkconfig -o /boot/grub/grub.cfg", self.calls())

    def test_drivers(self):
        plan = self.plan({"packages": ["base", "linux-zen", "lux", "firefox", "vim", "ufw"],
                          "drivers": ["nvidia-open-dkms", "brother-hll2350dw"]},
                         applied={"drivers": ["samsung-unified-driver", "nvidia-open-dkms"]})
        self.assertEqual(self.texts(plan), ["drivers + install: brother-hll2350dw",
                                            "drivers - remove: samsung-unified-driver"])
        # bez seznamu "drivers" zustavaji ovladace, jak jsou (ani remove_unlisted je neodebere)
        plan = self.plan({"packages": ["base", "linux-zen", "lux", "firefox", "vim", "ufw"], "remove_unlisted": True})
        self.assertEqual(self.texts(plan), [])

    def test_formats_console_faillock_new_users(self):
        plan = self.plan({"formats": {"LC_TIME": None, "LC_PAPER": "cs_CZ.UTF-8"},
                          "console": {"keymap": "us", "font": "ter-v20n"},
                          "security": {"faillock": {"deny": 20, "unlock_time": 120}},
                          "new_users": {"theme": "auto", "dock": ["firefox", "thunar", "trash"],
                                        "browser": "firefox", "lock_after_minutes": 5}})
        self.assertEqual(self.texts(plan), [
            "system ~ formats: LC_TIME: cs_CZ.UTF-8 → as the language, LC_PAPER: - → cs_CZ.UTF-8",
            "system ~ console: keymap: cz-qwertz → us, font: - → ter-v20n  (after a restart)",
            "security ~ sign-in lockout: unlock_time: 60 → 120",
            "new_users ~ theme: - → auto, dock: - → firefox.desktop thunar.desktop trash, "
            "browser: - → firefox.desktop, lock_after_minutes: - → 5"])
        for c in plan.changes:
            c.action()
        with open(self.root + "/etc/locale.conf") as f:
            self.assertEqual(f.read(), "LANG=en_US.UTF-8\nLC_PAPER=cs_CZ.UTF-8\n")
        with open(self.root + "/etc/locale.gen") as f:
            self.assertIn("\ncs_CZ.UTF-8 UTF-8\n", "\n" + f.read())
        with open(self.root + ls.VCONSOLE_CONF) as f:
            self.assertEqual(f.read(), "KEYMAP=us\nFONT=ter-v20n\n")
        with open(self.root + ls.FAILLOCK_CONF) as f:
            text = f.read()
        self.assertIn("# Configuration for locking the user\n# deny = 3\ndeny = 20\n", text)   # komentare zustanou
        self.assertIn("unlock_time = 120\n", text)
        with open(self.root + ls.NEW_USERS_CONF) as f:
            text = f.read()
        self.assertIn("THEME=auto\nDOCK=firefox.desktop thunar.desktop trash\nBROWSER=firefox.desktop\nLOCK_AFTER=5\n",
                      text)
        self.assertEqual(ls.State().new_users(), {"theme": "auto", "dock": ["firefox.desktop", "thunar.desktop", "trash"],
                                                  "browser": "firefox.desktop", "lock_after_minutes": 5})
        plan = self.plan({"new_users": {"theme": None}})
        plan.changes[0].action()
        with open(self.root + ls.NEW_USERS_CONF) as f:
            self.assertNotIn("THEME=", f.read())

    def test_scheduler(self):
        plan = self.plan({"kernel": {"scheduler": "default"}}, applied={"kernel_params": ["quiet", "splash"]})
        # jen planovac: parametry jadra se nespravuji (ani neodebiraji)
        self.assertEqual(self.texts(plan), ["kernel ~ process scheduler: lavd → default"])
        plan.changes[0].action()
        self.assertEqual(self.calls(), ["luxos-care scheduler default"])
        _c, errors = ls.normalize({"kernel": {"scheduler": "bfs"}})
        self.assertIn("kernel.scheduler: must be one of: lavd, default", "\n".join(errors))
        os.unlink(self.root + ls.SCHED_CONF)
        cfg, _e = ls.normalize({"kernel": {"scheduler": "lavd"}})
        with self.assertRaises(ls.UserError):
            ls.compute(cfg, ls.State(), {})

    def test_update_channel(self):
        """updates.channel: jediny klic, ktery lux system v /etc/lux/lux.conf meni (pres lux-config)."""
        write(self.root + "/etc/lux/mirrorlist", "https://mirror.example/$repo/os/$arch\n")
        plan = self.plan({"updates": {"channel": "stable"}})
        self.assertEqual(self.texts(plan), [])
        plan = self.plan({"updates": {"channel": "staging"}})
        self.assertEqual(self.texts(plan), ["updates ~ update channel: stable → staging"])
        plan.changes[0].action()
        with open(self.root + ls.LUX_CONF, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("channel staging\n", text)            # stary format zustal starym formatem
        self.assertIn("aur                 on            # komunita\n", text)
        self.assertEqual(ls.State().repos()["channel"], "staging")
        self.assertEqual(self.texts(self.plan({"updates": {"channel": "staging"}})), [])
        _c, errors = ls.normalize({"updates": {"channel": "beta", "chanel": "x"}})
        self.assertIn("updates.channel: must be \"stable\" or \"staging\"", "\n".join(errors))
        self.assertTrue(any("unknown setting \"chanel\"" in e for e in errors))

    def test_repos_are_only_checked(self):
        plan = self.plan({"repos": {"list": ["luxos", "core", "extra"], "community": False, "flatpak_updates": False}})
        self.assertEqual(self.texts(plan), [])
        self.assertTrue(any("repos.community differs" in w and "does not change" in w for w in plan.warnings))


@need_lsl
class GenerateMoreTest(More):
    def test_show_then_diff_is_empty(self):
        text = self.show()
        for secret in ("SECRET-PSK-123", "VPN-SECRET-456", "$6$", "psk=", "\"password_hash\": \""):
            self.assertNotIn(secret, text)
        self.assertIn("password: kept by the system", text)
        self.assertIn('"Domácí Wi-Fi": {', text)
        self.assertIn('"drivers": ["nvidia-open-dkms", "samsung-unified-driver"]', text)
        self.assertNotIn('"nvidia-open-dkms", "ufw"', text)                     # ovladace ne v packages
        self.assertIn('"model": "everywhere"', text)
        self.assertIn('# "theme": "dark"', text)                                 # priklad, ne nastaveni
        self.assertIn("means \"leave it as it is\"", text)
        path = self.lsl_file(text)
        cfg = ls.load(path)
        self.assertEqual(cfg["boot"], {"timeout": 3, "default": "luxos"})
        self.assertEqual(cfg["kernel"], {"params": ["quiet", "splash"], "scheduler": "lavd"})
        self.assertEqual(cfg["security"], {"faillock": {"deny": 20, "fail_interval": 30, "unlock_time": 60}})
        self.assertEqual(cfg["network"]["connections"]["Kancelar"]["proxy"], "http://proxy.firma.cz/proxy.pac")
        plan = ls.compute(cfg, ls.State(), {})
        self.assertEqual(self.texts(plan), [])
        self.assertEqual(plan.warnings, [])
        rc, out = self.main("diff", path)
        self.assertEqual(rc, 0, out)
        self.assertIn("already matches", out)

    def test_comments_in_system_language(self):
        write(self.root + "/etc/locale.conf", "LANG=cs_CZ.UTF-8\n")
        os.environ["LUXOS_I18N_DIR"] = I18N
        try:
            text = self.show()
        finally:
            os.environ.pop("LUXOS_I18N_DIR")
        self.assertIn("ponech, jak je", text)
        self.assertIn("heslo: uchovává systém", text)
        cfg = ls.load(self.lsl_file(text))
        self.assertEqual(cfg["locale"], "cs_CZ.UTF-8")

    def test_init_auto_and_refresh(self):
        path = self.root + ls.CONFIG
        rc, out = self.main("init", "--auto")
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.isfile(path))
        with open(self.root + ls.APPLIED) as f:
            applied = json.load(f)
        self.assertEqual(applied["connections"], ["Domácí Wi-Fi", "Firma VPN", "Kancelar"])
        self.assertIn("samsung-unified-driver", applied["drivers"])
        os.unlink(path)
        rc, out = self.main("init", "--auto")       # jednorazove: smazany soubor se znovu nevytvori
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(path))
        rc, out = self.main("init", "--refresh")    # OEM po Pruvodci: soubor chybi -> vytvori
        self.assertEqual(rc, 0, out)
        write(self.root + "/etc/hostname", "majitel-pc\n")
        rc, out = self.main("init", "--refresh")    # needitovany -> znovu ze systemu
        self.assertEqual(rc, 0, out)
        with open(path) as f:
            text = f.read()
        self.assertIn('"majitel-pc"', text)
        write(path, text + "# vlastni poznamka\n")
        rc, out = self.main("init", "--refresh")    # upraveny -> zustava
        self.assertEqual(rc, 0, out)
        self.assertIn("stays as it is", out)
        with open(path) as f:
            self.assertIn("# vlastni poznamka", f.read())

    def test_init_auto_skips_oem_preparation(self):
        write(self.root + ls.OEM_CONF, "OEM=1\nOEM_USER=oem\n")
        rc, out = self.main("init", "--auto")
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(self.root + ls.CONFIG))
        write(self.root + ls.OEM_DONE, "")
        rc, out = self.main("init", "--auto")
        self.assertTrue(os.path.exists(self.root + ls.CONFIG))

    def test_fix_and_network_in_use(self):
        rc, out = self.main("init")
        self.assertEqual(rc, 0, out)
        path = self.root + ls.CONFIG
        # drift: nekdo zmenil cas nabidky a profil napajeni; v souboru se zmeni pouzivane pripojeni
        with open(f"{self.root}{ls.EFIVARS}/LoaderConfigTimeout-{ls.EFI_LOADER_GUID}", "wb") as fh:
            fh.write(efi("10"))
        write(self.root + ls.PPD_STATE, "[State]\nProfile=performance\n")
        with open(path) as f:
            text = f.read()
        old = '"ssid": "Novakovi"'
        self.assertIn(old, text)
        write(path, text.replace(old, '"ssid": "Novakovi-5G"'))
        open(self.log, "w").close()
        rc, out = self.main("fix", "-y")
        self.assertEqual(rc, 0, out)
        self.assertIn("Repair", out)
        self.assertIn("network connection in use", out)
        self.assertIn("--force", out)
        calls = self.calls()
        self.assertEqual(calls[0], "luxos-care snapshot --kind system")
        self.assertIn("powerprofilesctl set balanced", calls)
        self.assertIn("bootctl set-timeout 3", calls)
        self.assertFalse([c for c in calls if c.startswith("nmcli")], calls)   # pouzivane pripojeni bez --force ne
        open(self.log, "w").close()
        rc, out = self.main("fix", "-y", "--force")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"nmcli connection modify {HOME_UUID} 802-11-wireless.ssid Novakovi-5G", self.calls())


if __name__ == "__main__":
    unittest.main()
