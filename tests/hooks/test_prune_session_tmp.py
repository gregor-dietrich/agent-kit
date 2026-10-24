"""Behavioral pin for the session temp pruner (``hooks/``).

Run in process against a fake temp root: what it removes, and everything it
must leave alone. main() runs here with the fork patched away, so every
assertion is deterministic; the registered command, its detached child and
the Python floor are pinned end to end in test_hooks_json.py.
"""

import io
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

import prune_session_tmp as pst

_OLD = time.time() - 30 * 86400
_CUTOFF = time.time() - pst.MAX_AGE_DAYS * 86400
_IDS = [f"{n:08x}-abcd-4ef0-8abc-0123456789ab" for n in range(3)]


def _prune(root: Path, keep: set[str]) -> None:
    """prune() on *root*; it changes directory, so the cwd is put back."""
    fd, cwd = os.open(root, os.O_RDONLY | os.O_DIRECTORY), os.getcwd()
    try:
        pst.prune(fd, keep, _CUTOFF)
    finally:
        os.chdir(cwd)
        os.close(fd)


def _session(root: Path, name: str, project: str = "-proj") -> Path:
    """A session dir with a nested file, every entry dated 30 days back."""
    session = root / project / name
    (session / "tasks").mkdir(parents=True)
    (session / "tasks" / "a.output").write_text("x", encoding="utf-8")
    for path in [*session.rglob("*"), session]:
        os.utime(path, (_OLD, _OLD), follow_symlinks=False)
    return session


def test_a_stale_session_is_removed(tmp_path: Path) -> None:
    session = _session(tmp_path, _IDS[0])
    _prune(tmp_path, set())
    assert not session.exists()
    assert (tmp_path / "-proj").is_dir()


def test_one_fresh_file_deep_inside_keeps_the_session(tmp_path: Path) -> None:
    session = _session(tmp_path, _IDS[0])
    (session / "tasks" / "a.output").touch()
    # Writing a file in place leaves every directory's mtime old.
    os.utime(session / "tasks", (_OLD, _OLD))
    _prune(tmp_path, set())
    assert session.is_dir()


def test_a_kept_session_survives_however_old(tmp_path: Path) -> None:
    session = _session(tmp_path, _IDS[0])
    _prune(tmp_path, {_IDS[0]})
    assert session.is_dir()


@pytest.mark.parametrize(
    "name", ["bash-edit-diff", "notes", _IDS[0].upper(), _IDS[0] + "x"]
)
def test_what_is_not_a_session_id_is_left_alone(
    tmp_path: Path, name: str
) -> None:
    other = _session(tmp_path, name)
    _prune(tmp_path, set())
    assert other.is_dir()


def test_symlinks_are_never_followed(tmp_path: Path) -> None:
    root, outside = tmp_path / "root", tmp_path / "outside"
    target = _session(outside, _IDS[0])
    # A session-shaped link, a linked project dir, and a link inside a
    # session that is itself removed: none may reach the target.
    (root / "-proj").mkdir(parents=True)
    (root / "-proj" / _IDS[1]).symlink_to(target)
    (root / "-linked").symlink_to(outside / "-proj")
    inner = _session(root, _IDS[2])
    (inner / "out").symlink_to(target)
    os.utime(inner / "out", (_OLD, _OLD), follow_symlinks=False)
    os.utime(inner, (_OLD, _OLD))
    _prune(root, set())
    assert not inner.exists()
    assert (root / "-proj" / _IDS[1]).is_symlink()
    assert (target / "tasks" / "a.output").is_file()


def test_an_unfinished_walk_reads_as_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _session(tmp_path, _IDS[0])
    monkeypatch.chdir(session.parent)
    assert pst.stale(_IDS[0], _CUTOFF)
    assert not pst.stale("missing", _CUTOFF)
    (session.parent / "link").symlink_to(session)
    assert not pst.stale("link", _CUTOFF)


def _registry(config: Path, sessions: dict[str, object]) -> None:
    (config / "sessions").mkdir(parents=True)
    for i, (session, pid) in enumerate(sessions.items()):
        entry = {"pid": pid, "sessionId": session}
        (config / "sessions" / f"{i}.json").write_text(
            json.dumps(entry), encoding="utf-8"
        )
    (config / "sessions" / "torn.json").write_text("{", encoding="utf-8")


def test_only_a_running_pid_marks_its_session_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dead = subprocess.Popen(["true"])
    dead.wait()
    _registry(tmp_path, {_IDS[0]: os.getpid(), _IDS[1]: dead.pid, _IDS[2]: "x"})
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert pst.live_sessions() == {_IDS[0]}


def test_a_running_pid_of_another_uid_still_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(pid: int, sig: int) -> None:
        raise PermissionError(pid, sig)

    _registry(tmp_path, {_IDS[0]: 4242})
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(pst.os, "kill", refused)
    assert pst.live_sessions() == {_IDS[0]}


def test_the_registry_defaults_to_the_home_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _registry(tmp_path / ".claude", {_IDS[0]: os.getpid()})
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert pst.live_sessions() == {_IDS[0]}


@pytest.mark.parametrize(
    ("env", "base"),
    [
        ({"CLAUDE_CODE_TMPDIR": "/c", "TMPDIR": "/t"}, "/c"),
        ({"CLAUDE_CODE_TMPDIR": "", "TMPDIR": "/t/"}, "/t"),
        ({"TMPDIR": "", "TMP": "/m", "TEMP": "/e"}, "/m"),
        ({"TEMP": "/e"}, "/e"),
        ({"TMPDIR": "/a/b/../c"}, "/a/c"),
        ({}, "/tmp"),
    ],
)
def test_the_root_resolves_as_claude_code_resolves_it(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], base: str
) -> None:
    for key in ("CLAUDE_CODE_TMPDIR", "TMPDIR", "TMP", "TEMP"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert pst.temp_root() == Path(base, f"claude-{os.getuid()}")


def _main(
    monkeypatch: pytest.MonkeyPatch,
    base: Path,
    uid: int | None = None,
    session: str = "x",
    config: Path | None = None,
) -> None:
    """Run main() on *base* as the detached child, minus the detaching.

    The fork reports "child", setsid and the std-stream dup2 are no-ops
    (they would take the test runner's own streams), and the child's
    ``os._exit`` raises SystemExit, which is the one way out main() has.
    """

    def leave(code: int) -> None:
        raise SystemExit(code)

    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", str(base))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config or base / "no-config"))
    monkeypatch.setattr(pst.os, "fork", lambda: 0)
    monkeypatch.setattr(pst.os, "setsid", lambda: 0)
    monkeypatch.setattr(pst.os, "dup2", lambda *_: 0)
    monkeypatch.setattr(pst.os, "_exit", leave)
    if uid is not None:
        monkeypatch.setattr(pst.os, "getuid", lambda: uid)
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"session_id": session}))
    )
    cwd = os.getcwd()
    try:
        with pytest.raises(SystemExit) as ended:
            pst.main()
    finally:
        os.chdir(cwd)
    assert ended.value.code == 0


def _main_refuses(
    monkeypatch: pytest.MonkeyPatch, base: Path, uid: int
) -> None:
    """Run main() on *base*; it must return without forking."""

    def no_fork() -> int:
        raise AssertionError("forked on a refused root")

    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", str(base))
    monkeypatch.setattr(pst.os, "getuid", lambda: uid)
    monkeypatch.setattr(pst.os, "fork", no_fork)
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id": "x"}'))
    pst.main()


def _root(tmp_path: Path, mode: int = 0o700) -> Path:
    root = tmp_path / f"claude-{os.getuid()}"
    root.mkdir(mode=mode)
    root.chmod(mode)
    return root


def test_a_root_owned_by_another_uid_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid = os.getuid() + 1
    session = _session(tmp_path / f"claude-{uid}", _IDS[0])
    _main_refuses(monkeypatch, tmp_path, uid)
    assert session.is_dir()


def test_a_symlinked_or_missing_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid = os.getuid()
    session = _session(tmp_path / "real", _IDS[0])
    (tmp_path / f"claude-{uid}").symlink_to(tmp_path / "real")
    _main_refuses(monkeypatch, tmp_path, uid)
    _main_refuses(monkeypatch, tmp_path / "missing", uid)
    assert session.is_dir()


def test_a_relative_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    session = _session(tmp_path / "rel" / f"claude-{os.getuid()}", _IDS[0])
    _main_refuses(monkeypatch, Path("rel"), os.getuid())
    assert session.is_dir()


@pytest.mark.parametrize("mode", [0o775, 0o757, 0o770, 0o707])
def test_a_root_others_can_write_to_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: int
) -> None:
    root = _root(tmp_path, mode)
    session = _session(root, _IDS[0])
    _main_refuses(monkeypatch, tmp_path, os.getuid())
    assert session.is_dir()


def test_main_keeps_the_current_and_the_registered_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    _registry(tmp_path / "config", {_IDS[1]: os.getpid()})
    current, registered, gone = (_session(root, i) for i in _IDS)
    _main(monkeypatch, tmp_path, session=_IDS[0], config=tmp_path / "config")
    assert current.is_dir()
    assert registered.is_dir()
    assert not gone.exists()


def test_main_removes_a_stale_session_under_a_clean_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    session = _session(root, _IDS[0])
    _main(monkeypatch, tmp_path)
    assert not session.exists()
    assert (root / "-proj").is_dir()


def test_a_session_dir_that_is_fresh_only_in_a_subdir_mtime_is_kept(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, _IDS[0])
    now = time.time()
    # The file and the session dir are old; only the subdir itself is new.
    os.utime(session / "tasks", (now, now))
    _prune(tmp_path, set())
    assert session.is_dir()


def test_a_session_id_named_file_is_left_alone(tmp_path: Path) -> None:
    (tmp_path / "-proj").mkdir()
    file = tmp_path / "-proj" / _IDS[0]
    file.write_text("x", encoding="utf-8")
    os.utime(file, (_OLD, _OLD))
    _prune(tmp_path, set())
    assert file.read_text(encoding="utf-8") == "x"


def test_a_bad_registry_entry_does_not_stop_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _registry(tmp_path, {_IDS[0]: os.getpid(), _IDS[1]: 99999999999999999999})
    for text in ('{"pid": 1e999, "sessionId": "x"}', "[" * 100000, "[]"):
        (tmp_path / "sessions" / f"bad{len(text)}.json").write_text(
            text, encoding="utf-8"
        )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert pst.live_sessions() == {_IDS[0]}


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_an_unreadable_registry_entry_does_not_stop_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _registry(tmp_path, {_IDS[0]: os.getpid(), _IDS[1]: os.getpid()})
    (tmp_path / "sessions" / "0.json").chmod(0)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert pst.live_sessions() == {_IDS[1]}


def test_no_home_means_no_registry_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_home() -> Path:
        raise RuntimeError("no home")

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(pst.Path, "home", no_home)
    assert pst.live_sessions() == set()


def test_a_read_only_subdirectory_does_not_keep_the_session(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, _IDS[0])
    locked = session / "tasks"
    locked.chmod(0o555)
    os.utime(locked, (_OLD, _OLD))
    _prune(tmp_path, set())
    assert not session.exists()


def test_an_entry_on_another_device_keeps_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _session(tmp_path, _IDS[0])
    monkeypatch.chdir(session.parent)
    assert pst.stale(_IDS[0], _CUTOFF)
    real = os.stat

    def mounted(path: object, **kw: object) -> os.stat_result:
        st = real(path, **kw)  # type: ignore[arg-type]
        if path == "tasks":
            st = os.stat_result((*st[:2], st.st_dev + 1, *st[3:]))
        return st

    monkeypatch.setattr(pst.os, "stat", mounted)
    assert not pst.stale(_IDS[0], _CUTOFF)


def _swap_in_stale(
    monkeypatch: pytest.MonkeyPatch, swap: Callable[[], None], when: str
) -> None:
    """Run *swap* inside stale(), before or after it judges."""
    real = pst.stale

    def swapping(name: str, cutoff: float) -> bool:
        if when == "before":
            swap()
        verdict = real(name, cutoff)
        if when == "after":
            swap()
        return verdict

    monkeypatch.setattr(pst, "stale", swapping)


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("swapped", ["session", "project"])
def test_a_dir_swapped_for_a_symlink_deletes_nothing_outside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, swapped: str, when: str
) -> None:
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir(mode=0o700)
    session = _session(root, _IDS[0])
    target = _session(outside, _IDS[0])
    victim = session if swapped == "session" else session.parent

    def swap() -> None:
        # The root's own copy of the dir goes; a link to the outside one
        # takes its name.
        victim.rename(root / "moved")
        victim.symlink_to(target if swapped == "session" else target.parent)

    _swap_in_stale(monkeypatch, swap, when)
    _prune(root, set())
    assert (target / "tasks" / "a.output").is_file()


def test_the_parent_returns_at_once_and_prunes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _session(_root(tmp_path), _IDS[0])
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", str(tmp_path))
    monkeypatch.setattr(pst.os, "fork", lambda: 4242)
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id": "x"}'))
    pst.main()
    assert session.is_dir()


def test_a_failing_sweep_still_ends_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object) -> None:
        raise RuntimeError("boom")

    session = _session(_root(tmp_path), _IDS[0])
    monkeypatch.setattr(pst, "prune", broken)
    _main(monkeypatch, tmp_path)
    assert session.is_dir()


def test_a_root_that_cannot_be_inspected_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(fd: int) -> os.stat_result:
        raise OSError(fd)

    monkeypatch.setattr(pst.os, "fstat", broken)
    assert pst.open_root(_root(tmp_path)) is None


def test_what_is_not_a_listable_dir_has_no_subdirs(tmp_path: Path) -> None:
    (tmp_path / "f").write_text("x", encoding="utf-8")
    fd = os.open(tmp_path / "f", os.O_RDONLY)
    try:
        assert pst._subdirs(fd) == []
    finally:
        os.close(fd)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any dir")
def test_an_unreadable_project_is_skipped_and_the_rest_pruned(
    tmp_path: Path,
) -> None:
    locked = _session(tmp_path, _IDS[0])
    other = _session(tmp_path, _IDS[1], project="-other")
    locked.parent.chmod(0)
    try:
        _prune(tmp_path, set())
    finally:
        locked.parent.chmod(0o700)
    assert locked.is_dir()
    assert not other.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any dir")
def test_a_walk_that_cannot_read_a_subdir_reads_as_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _session(tmp_path, _IDS[0])
    monkeypatch.chdir(session.parent)
    (session / "tasks").chmod(0)
    try:
        assert not pst.stale(_IDS[0], _CUTOFF)
    finally:
        (session / "tasks").chmod(0o700)


@pytest.mark.skipif(os.geteuid() == 0, reason="root empties a read-only dir")
def test_a_session_that_will_not_unlock_is_left_without_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(*_: object) -> None:
        raise PermissionError

    session = _session(tmp_path, _IDS[0])
    (session / "tasks").chmod(0o555)
    os.utime(session / "tasks", (_OLD, _OLD))
    monkeypatch.setattr(pst.os, "fchmod", denied)
    try:
        _prune(tmp_path, set())
        assert (session / "tasks" / "a.output").is_file()
    finally:
        (session / "tasks").chmod(0o700)
