# mskb_lifecycle.py
#
# systemd-only mapper restart: clean GNOME autostart that would launch
# mskb.py run, stop stray PIDs, then restart or enable --now the unit.
# Never spawn a second detached mapper — that dual-fires Favorites.
#
# Used by: mskb_gui.py (via mskb), mskb_install.py
# See also: mskb_paths.py

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from mskb_paths import sudo_invoker, user_home


def _systemctl_user(args: list[str]) -> int:
    inv = sudo_invoker()
    if inv:
        return subprocess.call(
            ["systemctl", "--user", f"--machine={inv.pw_name}@", *args]
        )
    return subprocess.call(["systemctl", "--user", *args])


def autostart_dir() -> Path:
    return user_home() / ".config" / "autostart"


def desktop_launches_mapper_run(text: str) -> bool:
    """True when a .desktop Exec line starts `mskb.py run` (not gui/probe)."""
    for line in text.splitlines():
        if not line.startswith("Exec="):
            continue
        parts = line[5:].split()
        has_script = any(part == "mskb.py" or part.endswith("/mskb.py") for part in parts)
        if has_script and "run" in parts:
            return True
    return False


def remove_mskb_autostart(directory: Path | None = None) -> list[Path]:
    """Delete GNOME autostart entries that launch `mskb.py run`.

    systemd is the only supported login path. A second mapper dual-fires Favorites.
    """
    base = directory if directory is not None else autostart_dir()
    removed: list[Path] = []
    if not base.is_dir():
        return removed
    for path in sorted(base.glob("*.desktop")):
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        if not desktop_launches_mapper_run(text):
            continue
        try:
            path.unlink()
        except OSError:
            continue
        removed.append(path)
    return removed


def _cmdline_is_mapper_run(cmdline: bytes) -> bool:
    """True when a process cmdline is `… mskb.py run` (not gui/probe/learn)."""
    parts = [part.decode(errors="ignore") for part in cmdline.split(b"\0") if part]
    if "run" not in parts:
        return False
    return any(part == "mskb.py" or part.endswith("/mskb.py") for part in parts)


def mapper_run_pids() -> list[int]:
    """PIDs of live `mskb.py run` processes (stray autostart or the unit itself)."""
    found: list[int] = []
    proc = Path("/proc")
    if not proc.exists():
        return found
    self_pid = os.getpid()
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == self_pid:
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except (OSError, PermissionError):
            continue
        if _cmdline_is_mapper_run(cmdline):
            found.append(pid)
    return sorted(found)


def _stop_mapper_pids(pids: list[int], timeout: float = 2.0) -> bool:
    """SIGTERM mapper PIDs and wait briefly so hidraw/uinput can be released.

    Returns True when every PID is gone. Permission errors count as failure so
    Apply does not leave an unkilled stray beside the systemd unit.
    """
    blocked = False
    for pid in pids:
        try:
            os.kill(pid, 15)  # SIGTERM
        except ProcessLookupError:
            continue
        except PermissionError:
            blocked = True
    if blocked:
        return False
    deadline = time.time() + timeout
    remaining = set(pids)
    while remaining and time.time() < deadline:
        for pid in list(remaining):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                remaining.discard(pid)
            except PermissionError:
                return False
        if remaining:
            time.sleep(0.05)
    for pid in list(remaining):
        try:
            os.kill(pid, 9)  # SIGKILL last resort
        except ProcessLookupError:
            remaining.discard(pid)
        except PermissionError:
            return False
    for pid in list(remaining):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            remaining.discard(pid)
        except PermissionError:
            return False
    return not remaining


def mapper_status_message(status: str, reason: str) -> str:
    """English toast/CLI line for a restart_mapper result."""
    if status == "ok":
        if reason == "started":
            return "Mapper started"
        return "Mapper restarted"
    if reason == "permission":
        return "Could not restart the mapper (permission denied)."
    if reason == "systemctl":
        return "Could not restart the mapper (systemctl failed)."
    if reason == "not_active":
        return "Could not restart the mapper (service not active)."
    return "Could not restart the mapper."


def restart_mapper() -> tuple[str, str]:
    """Ensure the systemd user mapper is the only one running with fresh config.

    Cleans conflicting GNOME autostart entries, stops stray `mskb.py run` PIDs
    when the unit is inactive, then `systemctl --user restart` or `enable --now`.
    Never spawns a second detached mapper — that was the dual-fire path.

    Returns (status, reason):
      ok + restarted | started
      failed + permission | systemctl | not_active
    """
    remove_mskb_autostart()

    was_active = _systemctl_user(["is-active", "--quiet", "mskb.service"]) == 0
    pids = mapper_run_pids()

    # Strays only when the unit is not managing the process. An active unit is
    # restarted via systemctl so systemd keeps track of the main PID.
    if pids and not was_active:
        if not _stop_mapper_pids(pids):
            return "failed", "permission"

    if was_active:
        if _systemctl_user(["restart", "mskb.service"]) != 0:
            return "failed", "systemctl"
        reason = "restarted"
    else:
        if _systemctl_user(["enable", "--now", "mskb.service"]) != 0:
            return "failed", "systemctl"
        reason = "started"

    # If a leftover autostart process survived beside the unit, Favorites dual-fire.
    extras = mapper_run_pids()
    if len(extras) > 1:
        if not _stop_mapper_pids(extras):
            return "failed", "permission"
        if _systemctl_user(["start", "mskb.service"]) != 0:
            return "failed", "systemctl"

    if _systemctl_user(["is-active", "--quiet", "mskb.service"]) != 0:
        return "failed", "not_active"
    return "ok", reason
