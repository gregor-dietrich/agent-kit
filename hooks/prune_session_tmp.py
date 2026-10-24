#!/usr/bin/env python3
"""SessionStart hook: prune this user's stale Claude Code session temp dirs.

Claude Code keeps each session's scratchpad and task outputs under
``<root>/<project-dir>/<session-id>/`` and removes none of it when the
session ends; on a tmpfs ``/tmp`` that fills the volume, and from then on
every tool call loses its output. ``<root>`` is ``claude-<uid>`` inside
``CLAUDE_CODE_TMPDIR``, else inside Bun's ``os.tmpdir()``: the first
non-empty ``TMPDIR``, ``TMP``, ``TEMP``, else ``/tmp``, joined lexically
the way Node's ``path.join`` does. A ``CLAUDE_CODE_TMPDIR`` set in a
settings file's ``env`` reaches hooks too. Python's ``tempfile`` reads the
variables in another order and probes writability, so it is not used.

That layout, the root resolution and the session registry were checked
against Claude Code 2.1.310, on Linux. On macOS the ``/var/folders/…``
``TMPDIR`` resolution is read from code, not run (tracked in #73). Under
Codex the hook resolves the root from Codex's own environment: a
``CLAUDE_CODE_TMPDIR`` set in a Claude Code settings file does not reach it.

A session dir is removed when its name is a session id, it is neither this
session nor one Claude Code's registry lists under a running pid, and
nothing in it changed for ``MAX_AGE_DAYS``, nothing on another filesystem
included. The root and each project dir are pinned by fd and opened
``O_NOFOLLOW``, and every later step works on names relative to those fds,
so no symlink inside the tree is followed and a swap after the check
redirects nothing. A root writable by group or others, or not a real
directory owned by this uid, is refused outright, and anything not shaped
like a session dir is left alone. The walk runs in a detached child, so the
hook returns at once whatever the tree's size.

Accepted risks. The registry is read only from this config dir, so a
session of another profile or namespace sharing the root is protected only
by the age threshold. A session resumed while another session's sweep runs
can lose output written in that window, which needs it to have been idle
for ``MAX_AGE_DAYS``. A registry that changes shape protects nothing,
leaving the age threshold.

Pinned by tests/hooks/test_prune_session_tmp.py.
"""

import json
import os
import re
import shutil
import stat
import time
from pathlib import Path

from hook_lib import read_payload

MAX_AGE_DAYS = 4
SESSION_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def temp_root() -> Path:
    """Claude Code's per-uid temp root, resolved the way it resolves it."""
    env = os.environ
    base = (
        env.get("CLAUDE_CODE_TMPDIR")
        or env.get("TMPDIR")
        or env.get("TMP")
        or env.get("TEMP")
        or "/tmp"
    )
    return Path(os.path.normpath(base), f"claude-{os.getuid()}")


def open_root(path: Path) -> int | None:
    """An fd on *path*, or None unless it is a safe temp root.

    Safe: an absolute real directory (never a symlink) owned by this uid
    that neither group nor others can write to.
    """
    if not path.is_absolute():
        return None
    try:
        fd = os.open(path, _DIR)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if (
            stat.S_ISDIR(st.st_mode)
            and st.st_uid == os.getuid()
            and not st.st_mode & 0o022
        ):
            return fd
    except OSError:
        pass
    os.close(fd)
    return None


def live_sessions() -> set[str]:
    """Session ids Claude Code's registry lists under a running pid.

    The registry (``sessions/<pid>.json`` in the config dir) is internal
    and may change shape; an entry it cannot read protects nothing, and the
    age threshold still does.
    """
    live: set[str] = set()
    try:
        config = os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude"
        entries = list(Path(config, "sessions").glob("*.json"))
    except (OSError, RuntimeError):
        return live
    for entry in entries:
        try:
            data = json.loads(entry.read_text(encoding="utf-8"))
            pid, session = int(data["pid"]), str(data["sessionId"])
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            OverflowError,
            RecursionError,
        ):
            continue
        try:
            os.kill(pid, 0)
        except PermissionError:
            pass  # running, under another uid
        except (OSError, OverflowError):
            continue
        live.add(session)
    return live


def _subdirs(dirfd: int) -> list[str]:
    """Names of the real (non-symlink) directories directly in *dirfd*."""
    try:
        with os.scandir(dirfd) as entries:
            return [e.name for e in entries if e.is_dir(follow_symlinks=False)]
    except OSError:
        return []


def _raise(err: OSError) -> None:
    raise err


def stale(name: str, cutoff: float) -> bool:
    """Whether nothing in the dir *name* of the cwd changed since *cutoff*.

    Judged on every entry's own mtime, itself included, because a dir's
    mtime moves only when its direct children are added or removed. Entries
    are read relative to the walk's own fds, never by path, and one on
    another filesystem (a mount) is never descended into or judged: it reads
    as fresh. So does a walk it cannot finish or that finds no directory
    (*name* swapped for a symlink), because that proves nothing.
    """
    try:
        dev = None
        for _top, dirs, files, dirfd in os.fwalk(name, onerror=_raise):
            here = os.fstat(dirfd)
            dev = here.st_dev if dev is None else dev
            if here.st_dev != dev or here.st_mtime >= cutoff:
                return False
            for entry in dirs + files:
                st = os.stat(entry, dir_fd=dirfd, follow_symlinks=False)
                if st.st_dev != dev or st.st_mtime >= cutoff:
                    return False
    except OSError:
        return False
    return dev is not None


def _unlock(name: str) -> None:
    """Give the owner rwx on every dir under *name*, so rmtree can empty it."""
    try:
        for _top, _dirs, _files, dirfd in os.fwalk(name):
            mode = stat.S_IMODE(os.fstat(dirfd).st_mode)
            if mode & 0o700 != 0o700:
                os.fchmod(dirfd, mode | 0o700)
    except OSError:
        pass  # what stays locked stays; the next sweep tries again


def prune(root_fd: int, keep: set[str], cutoff: float) -> None:
    """Remove each stale ``<root>/<project>/<session-id>`` not in *keep*.

    Each project is opened by fd and entered with ``fchdir``, so a session
    is judged and removed by its name there, whatever happens to the paths
    above it meanwhile.
    """
    for project in _subdirs(root_fd):
        try:
            project_fd = os.open(project, _DIR, dir_fd=root_fd)
        except OSError:
            continue
        try:
            os.fchdir(project_fd)
            for name in _subdirs(project_fd):
                if (
                    SESSION_ID.fullmatch(name)
                    and name not in keep
                    and stale(name, cutoff)
                ):
                    _unlock(name)
                    shutil.rmtree(name, ignore_errors=True)
        except OSError:
            continue
        finally:
            os.close(project_fd)


def main() -> None:
    current = str(read_payload().get("session_id") or "")
    root_fd = open_root(temp_root())
    if root_fd is None:
        return
    if os.fork() != 0:
        os.close(root_fd)
        return
    # Detached before the walk: the client waits for the hook's stdout to
    # close, so the child holds none of the hook's streams, and in a
    # session of its own a kill aimed at the hook's group spares it. It
    # never returns into the caller: whatever happens, it ends here.
    try:
        devnull = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(devnull, fd)
        os.close(devnull)
        os.setsid()
        cutoff = time.time() - MAX_AGE_DAYS * 86400
        prune(root_fd, {current, *live_sessions()}, cutoff)
    except Exception:  # noqa: BLE001, S110 - no one to tell; ends below
        pass
    finally:
        os._exit(0)


if __name__ == "__main__":
    main()
