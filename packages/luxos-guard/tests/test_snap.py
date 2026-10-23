"""Lux Guard - snimky /home: uchovavani, podpora btrfs, obnova souboru (bez rootu, bez btrfs)."""
import datetime
import os
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


def test_restore_dry_run(tmp_path):
    snap = tmp_path / "snap"
    make_tree(snap, {"a": b"1", "d/b": b"2"})
    home = tmp_path / "home"
    home.mkdir()
    assert S.restore(str(snap), str(home), dry_run=True) == (2, 0)
    assert os.listdir(home) == []


def test_user_snapshot_dir():
    assert S.user_snapshot_dir("/home/.luxos-guard-snapshots/x", "/home/anna") == "/home/.luxos-guard-snapshots/x/anna"
