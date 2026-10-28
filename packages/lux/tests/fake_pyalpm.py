"""Napodobenina pyalpm pro testy lux_alpm (bez libalpm, bez rootu, vse v pameti).

Chova se jako rozhrani pyalpm, ktere lux_alpm pouziva: Handle, databaze, balicky, transakce
a callbacky (dlcb ve tvaru pyalpm >= 0.10: soubor, udalost, data). Neovuje skutecne chovani
libalpm (podpisy, hooky, konflikty souboru) - to je nutne overit na LuxOS.
"""
import os
import re


class error(Exception):
    pass


PKG_REASON_EXPLICIT = 0
PKG_REASON_DEPEND = 1


def _split(v):
    epoch, _, rest = v.rpartition(":") if ":" in v else ("0", "", v)
    ver, _, rel = rest.rpartition("-") if "-" in rest else (rest, "", "")
    return int(epoch or 0), ver, rel


def _cmp_part(a, b):
    pa = re.findall(r"\d+|[a-zA-Z]+", a)
    pb = re.findall(r"\d+|[a-zA-Z]+", b)
    for x, y in zip(pa, pb):
        if x.isdigit() and y.isdigit():
            if int(x) != int(y):
                return 1 if int(x) > int(y) else -1
        elif x != y:
            return 1 if x > y else -1
    return (len(pa) > len(pb)) - (len(pa) < len(pb))


def vercmp(a, b):
    ea, va, ra = _split(a)
    eb, vb, rb = _split(b)
    if ea != eb:
        return 1 if ea > eb else -1
    c = _cmp_part(va, vb)
    if c:
        return c
    if ra and rb:
        return _cmp_part(ra, rb)
    return 0


def _dep_name(dep):
    return re.split(r"[<>=]", dep, 1)[0]


def find_satisfier(pkgs, dep):
    name = _dep_name(dep)
    for p in pkgs:
        if p.name == name or any(_dep_name(x) == name for x in p.provides):
            return p
    return None


def sync_newversion(pkg, dbs):
    for db in dbs:
        p = db.get_pkg(pkg.name)
        if p is not None and vercmp(p.version, pkg.version) > 0:
            return p
    return None


class Package:
    def __init__(self, name, version, desc="", depends=(), provides=(), groups=(), isize=1000000,
                 size=500000, reason=0, files=(), optdepends=(), db=None, replaces=(), conflicts=()):
        self.name = name
        self.version = version
        self.desc = desc
        self.url = f"https://example.org/{name}"
        self.licenses = ["MIT"]
        self.groups = list(groups)
        self.provides = list(provides)
        self.depends = list(depends)
        self.optdepends = list(optdepends)
        self.conflicts = list(conflicts)
        self.replaces = list(replaces)
        self.isize = isize
        self.size = size
        self.download_size = size
        self.reason = reason
        self.files = [(f, 0, 0o644) for f in files]
        self.installdate = 1700000000
        self.builddate = 1690000000
        self.packager = "LuxOS Team"
        self.db = db
        self.filename = f"{name}-{version}-x86_64.pkg.tar.zst"
        self._localdb = None

    def compute_requiredby(self):
        if self._localdb is None:
            return []
        return [p.name for p in self._localdb.pkgcache
                if any(_dep_name(d) in ([self.name] + [_dep_name(x) for x in self.provides]) for d in p.depends)]

    def compute_optionalfor(self):
        if self._localdb is None:
            return []
        return [p.name for p in self._localdb.pkgcache
                if any(_dep_name(d.split(":")[0]) == self.name for d in p.optdepends)]

    def copy_for_local(self, localdb, reason):
        p = Package(self.name, self.version, self.desc, self.depends, self.provides, self.groups, self.isize,
                    self.size, reason, [f[0] for f in self.files], self.optdepends, localdb)
        p._localdb = localdb
        return p


class DB:
    def __init__(self, name, pkgs=(), siglevel=0):
        self.name = name
        self.siglevel = siglevel
        self.servers = []
        self.pkgcache = []
        self.updated = 0
        self.update_errors = []
        for p in pkgs:
            self.add(p)

    def add(self, p):
        p.db = self
        if self.name == "local":
            p._localdb = self
        self.pkgcache = [x for x in self.pkgcache if x.name != p.name] + [p]

    def get_pkg(self, name):
        return next((p for p in self.pkgcache if p.name == name), None)

    def search(self, *terms):
        rx = [re.compile(t, re.I) for t in terms]
        return [p for p in self.pkgcache if all(r.search(p.name) or r.search(p.desc or "") for r in rx)]

    def read_grp(self, name):
        members = [p for p in self.pkgcache if name in p.groups]
        return (name, members) if members else None

    def update(self, force):
        if self.update_errors:
            raise self.update_errors.pop(0)
        self.updated += 1
        return True


class Handle:
    def __init__(self, root, dbpath):
        self.root = root
        self.dbpath = dbpath
        self.local = DB("local")
        self.sync = []
        self.cachedirs = []
        self.hookdirs = ["/usr/share/libalpm/hooks/"]
        self.gpgdir = ""
        self.logfile = ""
        self.arch = ""
        self.dlcb = self.progresscb = self.eventcb = self.logcb = self.questioncb = None
        self.commit_errors = []
        self.commit_questions = []    # otazky libalpm pred chybou commitu (napr. poskozeny balik)       # vyjimky, ktere vyhodi dalsi commit (testy chyb a opakovani)
        self.prepare_errors = []
        # hooky libalpm jako je posila pyalpm 0.12: jen typ udalosti ("unknown event") a pred
        # spustenim ladici log 'executing "<Exec>"'; None = puvodni zjednodusene udalosti
        self.pre_hooks = []
        self.post_hooks = None
        self.transactions = []
        self.locked = False

    def register_syncdb(self, name, siglevel):
        db = DB(name, siglevel=siglevel)
        self.sync.append(db)
        return db

    def get_localdb(self):
        return self.local

    def get_syncdbs(self):
        return list(self.sync)

    def load_pkg(self, path, siglevel=None):
        m = re.match(r"(.+)-([^-]+-[^-]+)-[^-]+\.pkg\.tar", path.rsplit("/", 1)[-1])
        if not m:
            raise error("could not find or read package")
        return Package(m.group(1), m.group(2), "local file")

    def init_transaction(self, **flags):
        if self.locked:
            raise error("unable to lock database", 10, None)
        t = Transaction(self, flags)
        self.transactions.append(t)
        self.locked = True
        return t


class Transaction:
    def __init__(self, h, flags):
        self.h = h
        self.flags = flags
        self.add = []
        self.remove = []
        self.to_add = []
        self.to_remove = []
        self.committed = False
        self.released = False

    def add_pkg(self, p):
        self.add.append(p)

    def remove_pkg(self, p):
        self.remove.append(p)

    def sysupgrade(self, downgrade):
        h = self.h
        replaced = set()
        # nahrazeni jako libalpm (sync.c check_replacers): balik z repozitare, ktery v "replaces" uvadi
        # nainstalovany balik (a sam nainstalovany neni) - otazka ALPM_QUESTION_REPLACE_PKG (2)
        for db in h.sync:
            for new in db.pkgcache:
                if h.local.get_pkg(new.name) is not None:
                    continue
                for old in list(h.local.pkgcache):
                    if old.name in replaced or not any(_dep_name(r) == old.name for r in new.replaces):
                        continue
                    if not (h.questioncb and h.questioncb(2, old.name, new.name, db.name)):
                        continue
                    replaced.add(old.name)
                    if old not in self.remove:
                        self.remove.append(old)
                    if new not in self.add:
                        self.add.append(new)
        for p in h.local.pkgcache:
            if p.name in replaced:
                continue
            n = sync_newversion(p, h.sync)
            if n is not None and n not in self.add:
                self.add.append(n)

    def prepare(self):
        if self.h.prepare_errors:
            raise self.h.prepare_errors.pop(0)
        local = self.h.local
        seen = {p.name for p in self.add}
        queue = list(self.add)
        self.to_add = list(self.add)
        while queue:
            p = queue.pop(0)
            for d in p.depends:
                if find_satisfier(local.pkgcache, d) or find_satisfier(self.to_add, d):
                    continue
                dep = None
                for db in self.h.sync:
                    dep = find_satisfier(db.pkgcache, d)
                    if dep:
                        break
                if dep is None:
                    raise error("could not satisfy dependencies", 30, [(p.name, d)])
                if dep.name not in seen:
                    seen.add(dep.name)
                    self.to_add.append(dep)
                    queue.append(dep)
        self.deps = [p for p in self.to_add if p not in self.add]
        rem = list(self.remove)
        if self.flags.get("recurse"):
            names = {p.name for p in rem}
            changed = True
            while changed:
                changed = False
                for p in local.pkgcache:
                    if p.name in names or p.reason != PKG_REASON_DEPEND:
                        continue
                    req = [r for r in p.compute_requiredby() if r not in names]
                    users = [x for x in local.pkgcache if x.name in names and
                             any(_dep_name(d) == p.name for d in x.depends)]
                    if users and not req:
                        rem.append(p)
                        names.add(p.name)
                        changed = True
        self.to_remove = rem

    def commit(self):
        h = self.h
        if self.h.commit_errors:
            err = self.h.commit_errors.pop(0)
            if h.commit_questions and h.questioncb:
                h.questioncb(*h.commit_questions.pop(0))
            if h.dlcb:
                h.dlcb(self.to_add[0].filename if self.to_add else "x", 0, (False,))
            if h.logcb:
                h.logcb(1, getattr(h, "commit_log", None) or
                        "failed retrieving file 'x.pkg.tar.zst' from mirror.example : Connection timed out")
            raise err
        if h.dlcb:
            for p in self.to_add:
                if p.download_size:
                    h.dlcb(p.filename, 0, (False,))
                    h.dlcb(p.filename, 1, (p.download_size // 2, p.download_size))
                    h.dlcb(p.filename, 1, (p.download_size, p.download_size))
                    h.dlcb(p.filename, 3, (p.download_size, 0))
        if self.flags.get("downloadonly"):
            self.committed = True
            return
        # hooky a skriptlety libalpm dedi prostredi procesu (PATH s nastroji jadra)
        self.env_path = os.environ.get("PATH")
        if h.progresscb:
            for i in range(1, len(self.to_add) + 1):
                h.progresscb("", 100, len(self.to_add), i)
        self.run_hooks(h, h.pre_hooks)
        ops = self.to_remove + self.to_add
        n = len(ops)
        for i, p in enumerate(ops, 1):
            if h.progresscb:
                h.progresscb(p.name, 0, n, i)
                h.progresscb(p.name, 100, n, i)
            if p in self.to_remove:
                h.local.pkgcache = [x for x in h.local.pkgcache if x.name != p.name]
            else:
                old = h.local.get_pkg(p.name)
                reason = old.reason if old else (PKG_REASON_DEPEND if p in self.deps or self.flags.get("alldeps")
                                                 else PKG_REASON_EXPLICIT)
                h.local.add(p.copy_for_local(h.local, reason))
        if h.post_hooks is not None:
            self.run_hooks(h, h.post_hooks)
        elif h.eventcb:
            h.eventcb(34, "")
            h.eventcb(36, "Updating icon theme caches...")
            h.eventcb(17, "==> A reboot is recommended")
        self.committed = True

    @staticmethod
    def run_hooks(h, cmds):
        if not cmds or not h.eventcb:
            return
        h.eventcb(34, "unknown event")
        for cmd in cmds:
            h.eventcb(36, "unknown event")
            if h.logcb:
                h.logcb(4, f'executing "{cmd}" under chroot "/"\n')
            h.eventcb(37, "unknown event")
        h.eventcb(35, "unknown event")

    def interrupt(self):
        pass

    def release(self):
        self.released = True
        self.h.locked = False
