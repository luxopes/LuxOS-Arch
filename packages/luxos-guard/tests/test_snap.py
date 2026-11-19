"""Lux Guard - snimky /home: uchovavani, podpora btrfs, obnova souboru (bez rootu, bez btrfs)."""
import datetime
import os
import shutil
import types

import luxos_guard_snap as S

T0 = datetime.datetime(2026, 10, 23, 12, 0)


def test_retention_hourly_then_daily():
    times = [T0 - datetime.timedelta(hours=h) for h in range(0, 24 * 10)]
    gone = set(S.to_prune(times, T0))
    keep = sorted(set(times) - gone)
    # poslednich 24 h vsechny, pak jeden za den (nejnovejsi), starsi nez 7 dni nic
    assert all(t in keep for t in times if T0 - t <= datetime.timedelta(hours=24))
    older = [t for t in keep if T0 - t > datetime.timedelta(hours=24)]
    assert len({t.date() for t in older}) == len(older)
    assert all(T0 - t <= datetime.timedelta(days=7) for t in keep)
    old_all = [t for t in times if datetime.timedelta(hours=24) < T0 - t <= datetime.timedelta(days=7)]
    assert all(t == max(x for x in old_all if x.date() == t.date()) for t in older)
    assert len(keep) <= 25 + 7


def test_retention_low_disk_keeps_two_newest():
    times = [T0 - datetime.timedelta(hours=h) for h in range(10)]
    gone = S.to_prune(times, T0, free_ok=False)
    assert sorted(set(times) - set(gone)) == sorted(times)[-2:]


def test_parse_and_list(tmp_path):
    root = tmp_path / ".luxos-guard-snapshots"
    for n in ("2026-10-23_10-00", "2026-10-22_09-00", "junk", "2026-13-01_00-00"):
        (root / n).mkdir(parents=True)
    snaps = S.list_snapshots(str(tmp_path))
    assert [t.strftime(S.NAME_FMT) for t, _p in snaps] == ["2026-10-22_09-00", "2026-10-23_10-00"]


def test_supported_and_fs_type(tmp_path):
    mi = tmp_path / "mi"
    mi.write_text("22 1 0:21 /@ / rw - btrfs /dev/vda2 rw\n23 22 0:22 /@home /home rw - btrfs /dev/vda2 rw\n")
    assert S.fs_type("/home/anna", str(mi)) == "btrfs"
    mi.write_text("22 1 8:2 / / rw - ext4 /dev/sda2 rw\n")
    assert S.fs_type("/home", str(mi)) == "ext4"
    assert not S.supported("/home", str(mi))


def test_take_runs_btrfs(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(S, "supported", lambda home=None: True)
    monkeypatch.setattr(os, "lstat", lambda p, _o=os.lstat: types.SimpleNamespace(
        st_mode=0o40755, st_uid=0) if p.endswith(".luxos-guard-snapshots") else _o(p))

    def run(cmd):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=0, stderr="")
    dest = S.take(str(tmp_path), T0, run=run)
    assert dest.endswith("/.luxos-guard-snapshots/2026-10-23_12-00")
    assert calls == [["btrfs", "subvolume", "snapshot", "-r", str(tmp_path), dest]]


def make_tree(base, files):
    for rel, data in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def test_restore_missing_and_overwrite(tmp_path):
    snap = tmp_path / "snap" / "anna"
    home = tmp_path / "home" / "anna"
    make_tree(snap, {"Documents/a.txt": b"A", "Documents/b.txt": b"B", "Pictures/p.jpg": b"P",
                     ".cache/x": b"C"})
    os.symlink("Documents/a.txt", snap / "link")
    # ransomware: a.txt zasifrovany, b.txt smazany, novy soubor vznikl pozdeji
    make_tree(home, {"Documents/a.txt": b"ENCRYPTED!", "Documents/new.txt": b"N"})
    done, kept = S.restore(str(snap), str(home), skip_top=(".cache",))
    assert (home / "Documents/b.txt").read_bytes() == b"B"
    assert (home / "Pictures/p.jpg").read_bytes() == b"P"
    assert (home / "Documents/a.txt").read_bytes() == b"ENCRYPTED!"     # bez --overwrite nemeni
    assert os.readlink(home / "link") == "Documents/a.txt"
    assert not (home / ".cache").exists()
    done, kept = S.restore(str(snap), str(home), overwrite=True)
    assert (home / "Documents/a.txt").read_bytes() == b"A"
    assert (home / "Documents/new.txt").read_bytes() == b"N"             # novejsi zustava
    # jeden soubor
    (home / "Pictures/p.jpg").unlink()
    assert S.restore(str(snap / "Pictures/p.jpg"), str(home / "Pictures/p.jpg")) == (1, 0)


def test_restore_overwrite_keeps_current_versions(tmp_path):
    """Obnova s prepsanim: soucasna verze (treba upravena po snimku) se presune do zalohy, neztrati se."""
    snap = tmp_path / "snap"
    home = tmp_path / "home"
    make_tree(snap, {"Documents/a.txt": b"OLD", "b.txt": b"B", "same.txt": b"S"})
    make_tree(home, {"Documents/a.txt": b"EDITED TODAY", "b.txt": b"CHANGED", "new.txt": b"N"})
    shutil.copy2(snap / "same.txt", home / "same.txt")
    backup = S.before_restore_dir(str(home), now=1_800_000_000)
    assert backup.startswith(str(home / ".local/share/luxos-guard/before-restore/"))
    done, kept = S.restore(str(snap), str(home), overwrite=True, backup=backup)
    assert (home / "Documents/a.txt").read_bytes() == b"OLD"
    with open(os.path.join(backup, "Documents/a.txt"), "rb") as f:
        assert f.read() == b"EDITED TODAY"
    with open(os.path.join(backup, "b.txt"), "rb") as f:
        assert f.read() == b"CHANGED"
    assert not os.path.exists(os.path.join(backup, "same.txt"))       # beze zmeny: nic k zaloze
    assert (home / "new.txt").read_bytes() == b"N"
    assert done == 2
    # jeden soubor
    (home / "b.txt").write_bytes(b"AGAIN")
    b2 = str(tmp_path / "b2" / "b.txt")          # u jednoho souboru je zaloha primo cesta souboru
    assert S.restore(str(snap / "b.txt"), str(home / "b.txt"), overwrite=True, backup=b2) == (1, 0)
    with open(b2, "rb") as f:
        assert f.read() == b"AGAIN"


def test_restore_overwrite_backup_failure_keeps_file(tmp_path):
    """Kdyz zalohu nejde vytvorit, soubor se neprepise (zadna ztrata)."""
    snap = tmp_path / "snap"
    home = tmp_path / "home"
    make_tree(snap, {"a.txt": b"OLD"})
    make_tree(home, {"a.txt": b"NEW"})
    blocker = tmp_path / "blocker"
    blocker.write_text("x")                       # zaloha "uvnitr souboru" = chyba
    assert S.restore(str(snap), str(home), overwrite=True, backup=str(blocker / "b")) == (0, 1)
    assert (home / "a.txt").read_bytes() == b"NEW"


def test_restore_dry_run(tmp_path):
    snap = tmp_path / "snap"
    make_tree(snap, {"a": b"1", "d/b": b"2"})
    home = tmp_path / "home"
    home.mkdir()
    assert S.restore(str(snap), str(home), dry_run=True) == (2, 0)
    assert os.listdir(home) == []


def test_user_snapshot_dir():
    assert S.user_snapshot_dir("/home/.luxos-guard-snapshots/x", "/home/anna") == "/home/.luxos-guard-snapshots/x/anna"


def _cli():
    import importlib.machinery
    import importlib.util
    path = os.path.join(os.path.dirname(__file__), "..", "files", "luxos-guard")
    loader = importlib.machinery.SourceFileLoader("lg_cli_snap", path)
    cli = importlib.util.module_from_spec(importlib.util.spec_from_loader("lg_cli_snap", loader))
    loader.exec_module(cli)
    return cli


def test_snapshot_failure_still_prunes(monkeypatch):
    """Plny disk: snimek selze (ENOSPC), stare snimky se presto uklidi - drzi smazane soubory."""
    import pytest
    cli = _cli()
    pruned = []

    def full():
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(cli.snap, "supported", lambda: True)
    monkeypatch.setattr(cli.snap, "take", full)
    monkeypatch.setattr(cli.snap, "prune", lambda: pruned.append(1) or ["/home/.luxos-guard-snapshots/old"])
    with pytest.raises(SystemExit) as e:
        cli.cmd_snapshot([])
    assert e.value.code == 1 and pruned == [1]


def test_restore_backup_keeps_paths_and_crosses_filesystems(tmp_path, monkeypatch):
    """Dva stejnojmenne soubory z ruznych slozek se v zaloze neprepisou; presun pres hranici
    souborovych systemu (EXDEV) soubor zazalohuje, nepreskoci ho."""
    snap = tmp_path / "snap"
    home = tmp_path / "home"
    make_tree(snap, {"A/notes.txt": b"oldA", "B/notes.txt": b"oldB"})
    make_tree(home, {"A/notes.txt": b"newA!", "B/notes.txt": b"newB!"})
    real_rename = os.rename

    def no_cross(a, b):
        if "before" in str(b):
            raise OSError(18, "Invalid cross-device link")
        return real_rename(a, b)
    monkeypatch.setattr(os, "rename", no_cross)
    stamp = tmp_path / "before"
    for d in ("A", "B"):
        backup = os.path.join(stamp, d, "notes.txt")
        assert S.restore(str(snap / d / "notes.txt"), str(home / d / "notes.txt"), overwrite=True,
                         backup=backup) == (1, 0)
    assert (stamp / "A/notes.txt").read_bytes() == b"newA!"
    assert (stamp / "B/notes.txt").read_bytes() == b"newB!"
    assert (home / "A/notes.txt").read_bytes() == b"oldA"
