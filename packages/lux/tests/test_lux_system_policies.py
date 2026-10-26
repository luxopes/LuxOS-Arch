"""Testy zasad organizace v lux system (/etc/luxos/system.d): slouceni, zamky (mkForce), puvod, apply.

    python3 packages/lux/tests/test_lux_system_policies.py -v

Stejne prostredi jako test_lux_system.py (docasny koren, zastupne nastroje); vyhodnoceni LSL potrebuje
prikaz lsl (bez nej se testy preskoci).
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_lux_system import Base, ls, need_lsl, write  # noqa: E402

BASE_POLICY = """load config

config = {
    "policy": {"organization": "Firma s.r.o.", "name": "Základ"}
    "packages": ["libreoffice-fresh", "firefox"]
    "firewall": {"enable": config.mkForce(True)}
    "care": {"mode": config.mkForce("carefree"), "keep_snapshots": config.mkDefault(8)}
    "hostname": "firma-pc"
}
"""


class MergeTest(Base):
    """Slouceni bez lsl: Layers.put primo s oznacenymi hodnotami."""

    def org(self, name="20-org.lsl", organization="Firma", policy="Zaklad"):
        return ls.Origin("org", "/etc/luxos/system.d/" + name, organization, policy)

    def force(self, v):
        return {"__lux_policy": "force", "value": v}

    def default(self, v):
        return {"__lux_policy": "default", "value": v}

    def test_priorities(self):
        lay = ls.Layers()
        org, local = self.org(), ls.Origin("local", "/etc/luxos/system.lsl")
        lay.put((), {"hostname": "org-pc", "timezone": self.default("Europe/Prague"),
                     "care": {"mode": self.force("classic"), "snapshots": True}}, ls.LV_ORG, org)
        lay.put((), {"hostname": "my-pc", "timezone": "Europe/Vienna", "care": {"snapshots": False}},
                ls.LV_LOCAL, local)
        self.assertEqual(lay.errors, [])
        self.assertEqual(lay.value["hostname"], "my-pc")          # lokalni soubor ma prednost
        self.assertEqual(lay.value["timezone"], "Europe/Vienna")   # mkDefault = jen doporuceni
        self.assertEqual(lay.value["care"], {"mode": "classic", "snapshots": False})
        self.assertEqual([o.kind for o in lay.origins(("hostname",))], ["local"])
        self.assertEqual(lay.origins(("care", "mode")), [org])

    def test_locked_value_cannot_be_changed_locally(self):
        lay = ls.Layers()
        lay.put((), {"firewall": {"enable": self.force(True)}}, ls.LV_ORG, self.org())
        lay.put((), {"firewall": {"enable": True}}, ls.LV_LOCAL, ls.Origin("local", "/x"))
        self.assertEqual(lay.errors, [])                             # stejna hodnota je v poradku
        lay.put((), {"firewall": {"enable": False}}, ls.LV_LOCAL, ls.Origin("local", "/x"))
        self.assertEqual(len(lay.errors), 1)
        self.assertIn("firewall.enable", lay.errors[0])
        self.assertIn("Firma", lay.errors[0])
        self.assertTrue(lay.value["firewall"]["enable"])

    def test_forced_subtree_locks_unlisted_keys(self):
        lay = ls.Layers()
        lay.put((), {"firewall": self.force({"enable": True})}, ls.LV_ORG, self.org())
        lay.put((), {"firewall": {"allow": ["22/tcp"]}}, ls.LV_LOCAL, ls.Origin("local", "/x"))
        self.assertEqual(len(lay.errors), 1)
        self.assertNotIn("allow", lay.value["firewall"])
        self.assertEqual([p for p, _i, _o in lay.lock_list()], ["firewall"])

    def test_lists_are_joined_and_forced_items_locked(self):
        lay = ls.Layers()
        org, local = self.org(), ls.Origin("local", "/x")
        lay.put((), {"packages": self.force(["firefox"]), "services": {"enable": self.force(["sshd"])}},
                ls.LV_ORG, org)
        lay.put((), {"packages": ["vim", "firefox"], "services": {"disable": ["sshd"]}}, ls.LV_LOCAL, local)
        lay.check_conflicts()
        self.assertEqual(lay.value["packages"], ["firefox", "vim"])
        self.assertEqual(lay.local_items(("packages",), lay.value["packages"]), ["firefox", "vim"])
        self.assertEqual(len(lay.errors), 1)                          # zamcene zapnuti nelze lokalne vypnout
        self.assertIn("services.disable", lay.errors[0])
        self.assertEqual(lay.origins(("packages",), "vim"), [local])

    def test_two_policies(self):
        lay = ls.Layers()
        a, b = self.org("20-base.lsl", policy="Zaklad"), self.org("30-ucetni.lsl", policy="Ucetni")
        lay.put((), {"hostname": "a", "care": {"mode": self.force("carefree")}}, ls.LV_ORG, a)
        lay.put((), {"hostname": "b", "care": {"mode": self.force("classic")}}, ls.LV_ORG, b)
        self.assertEqual(lay.value["hostname"], "b")                  # vyssi cislo prepise nizsi
        self.assertEqual(len(lay.errors), 1)                          # dva ruzne mkForce = chyba
        self.assertIn("Zaklad", lay.errors[0])
        self.assertIn("Ucetni", lay.errors[0])

    def test_org_packages_are_not_tracked_for_removal(self):
        lay = ls.Layers()
        lay.put((), {"packages": ["libreoffice-fresh"]}, ls.LV_ORG, self.org())
        lay.put((), {"packages": ["vim"]}, ls.LV_LOCAL, ls.Origin("local", "/x"))
        self.assertEqual(lay.local_items(("packages",), ["libreoffice-fresh", "vim"]), ["vim"])


@need_lsl
class PolicyFilesTest(Base):
    def policy(self, name, body, mode=0o644):
        path = os.path.join(self.root, "etc/luxos/system.d", name)
        write(path, body, mode)
        return path

    def test_force_survives_lsl_and_line_numbers(self):
        self.policy("20-org-base.lsl", BASE_POLICY)
        local = self.lsl_file('load config\nconfig = {"hostname": "my-pc", "care": {"keep_snapshots": 3}}\n')
        cfg = ls.load(local)
        self.assertEqual(cfg["hostname"], "my-pc")
        self.assertEqual(cfg["care"], {"mode": "carefree", "keep_snapshots": 3})
        self.assertEqual(cfg["firewall"], {"enable": True})
        self.assertEqual(cfg["packages"], ["libreoffice-fresh", "firefox"])
        self.assertEqual(ls.LAYERS.fragments[0][0].organization, "Firma s.r.o.")
        # chyba ve fragmentu ukazuje puvodni cislo radku a cestu fragmentu
        bad = self.policy("30-bad.lsl", 'load config\n\nconfig = {"packages": ["a", "b",]}\n')
        with self.assertRaises(ls.UserError) as cm:
            ls.load(local)
        self.assertIn(bad, str(cm.exception))
        self.assertNotIn("lux_policy_force", str(cm.exception))

    def test_local_override_of_locked_value_fails(self):
        self.policy("20-org-base.lsl", BASE_POLICY)
        local = self.lsl_file('load config\nconfig = {"firewall": {"enable": False}}\n')
        rc, out = self.main("check", local)
        self.assertEqual(rc, 1)
        self.assertIn("firewall.enable", out)
        self.assertIn("Firma s.r.o.", out)
        rc, out = self.main("check", local, "--no-policies")
        self.assertEqual(rc, 0, out)

    def test_only_policies_without_local_file(self):
        self.policy("20-org-base.lsl", BASE_POLICY)
        rc, out = self.main("plan", os.path.join(self.root, "etc/luxos/system.lsl"))
        self.assertEqual(rc, 0, out)
        self.assertEqual(json.loads(out)["hostname"], "firma-pc")

    def test_writable_policy_is_refused(self):
        self.policy("20-org-base.lsl", BASE_POLICY, 0o666)
        local = self.lsl_file('load config\nconfig = {}\n')
        rc, out = self.main("check", local)
        self.assertEqual(rc, 1)
        self.assertIn("other users than root", out)

    def test_bad_names_ignored(self):
        self.policy("org.lsl", 'load config\nconfig = {"hostname": "x"}\n')
        local = self.lsl_file('load config\nconfig = {"hostname": "mine"}\n')
        self.assertEqual(ls.load(local)["hostname"], "mine")

    def test_show_origin_and_locks(self):
        self.policy("20-org-base.lsl", BASE_POLICY)
        local = self.lsl_file('load config\nconfig = {"packages": ["vim"]}\n')
        rc, out = self.main("show", "--origin", local)
        self.assertEqual(rc, 0, out)
        self.assertIn("firewall.enable = true", out)
        self.assertIn("Firma s.r.o.", out)
        self.assertIn("locked", out)
        self.assertRegex(out, r'packages\[\] = "vim"  ← local file')
        rc, out = self.main("show", "--origin", "--json", local)
        data = json.loads(out)
        locked = [i["path"] for i in data["items"] if i["locked"]]
        self.assertIn("firewall.enable", locked)
        rc, out = self.main("locks", local)
        self.assertEqual(rc, 0)
        self.assertIn("firewall", out)
        self.assertIn("care.mode", out)

    def test_diff_shows_origin_and_apply_records_policies(self):
        self.policy("20-org-base.lsl", BASE_POLICY)
        write(self.fake + "/repo", "htop\nlibreoffice-fresh\nufw\n")
        local = self.lsl_file('load config\nconfig = {"packages": ["vim", "base", "lux", "linux-zen", "ufw"]}\n')
        rc, out = self.main("diff", local)
        self.assertEqual(rc, 0, out)
        self.assertIn("install: libreoffice-fresh", out)
        self.assertIn("[Firma s.r.o.", out)
        self.assertIn("Organization policies:", out)
        rc, out = self.main("diff", "--json", local)
        changes = json.loads(out)["changes"]
        inst = [c for c in changes if c["text"].startswith("install")][0]
        self.assertIn("origin", inst)
        rc, out = self.main("apply", "-y", "--no-snapshot", local)
        self.assertEqual(rc, 0, out)
        with open(os.path.join(self.root, "var/lib/lux/system/applied.json")) as f:
            applied = json.load(f)
        # balicek ze zasady se po odchodu z organizace neodinstaluje (neni v lokalnim seznamu)
        self.assertNotIn("libreoffice-fresh", applied["packages"])
        self.assertIn("vim", applied["packages"])
        self.assertEqual(len(applied["policies"]), 1)
        with open(os.path.join(self.root, "var/lib/lux/system/policy.json")) as f:
            pol = json.load(f)
        self.assertIn("firewall", [x["path"] for x in pol["locks"]] + [x["path"].split(".")[0] for x in pol["locks"]])
        self.assertEqual(oct(os.stat(os.path.join(self.root, "var/lib/lux/system/policy.json")).st_mode & 0o777), "0o644")
        hist = os.listdir(os.path.join(self.root, "var/lib/lux/system/history"))
        self.assertTrue(any(h.endswith(".d") for h in hist))
        # odchod z organizace: fragment smazan -> nic se neodinstaluje
        os.unlink(os.path.join(self.root, "etc/luxos/system.d/20-org-base.lsl"))
        write(self.fake + "/explicit", "base\nlinux-zen\nlux\nvim\nufw\nlibreoffice-fresh\n")
        open(self.log, "w").close()
        rc, out = self.main("diff", local)
        self.assertNotIn("libreoffice-fresh", out.split("remove:")[-1] if "remove:" in out else "")
        self.assertNotIn("remove: libreoffice-fresh", out)

    def test_domain_key(self):
        norm, errors = ls.normalize({"domain": {"admins": ["Domain Admins", "IT"], "offline_days": 30,
                                                "admin_offline_days": 7}})
        self.assertEqual(errors, [])
        _n, errors = ls.normalize({"domain": {"admins": ["bad\ngroup"], "offline_days": 500,
                                              "admin_offline_days": 9, "x": 1}})
        self.assertEqual(len(errors), 3)
        # bez pripojeni k domene -> srozumitelna chyba
        with self.assertRaises(ls.UserError) as cm:
            ls.compute(norm, ls.State(), {})
        self.assertIn("lux domain join", str(cm.exception))
        write(os.path.join(self.root, "var/lib/luxos/domain/state.json"),
              json.dumps({"joined": True, "admin_groups": ["domain admins", "Old"], "offline_days": 30,
                          "admin_offline_days": 3}))
        with open(os.path.join(self.bin, "lux")) as f:
            write(os.path.join(self.bin, "lux-domain"), f.read(), 0o755)
        plan = ls.compute(norm, ls.State(), {})
        texts = self.texts(plan)
        self.assertIn("domain + administrators: add domain group IT", texts)
        self.assertIn("domain - administrators: remove domain group Old", texts)
        self.assertEqual(len([t for t in texts if "Domain Admins" in t]), 0)   # bez ohledu na velikost pismen
        self.assertIn("domain ~ administrator rights offline: 3 → 7 days", texts)
        for c in plan.changes:
            c.action()
        self.assertIn("lux-domain admins add IT", self.calls())
        self.assertIn("lux-domain set admin-offline-days 7", self.calls())


if __name__ == "__main__":
    unittest.main()
