# mskb_paths.py
#
# Repo root, config directory, and $SUDO_USER home resolution.
# Shared so install and lifecycle can find the session home without
# importing JSON binding helpers.
#
# Used by: mskb_bindings.py, mskb_lifecycle.py, mskb_install.py
# See also: mskb.py (re-exports)

from __future__ import annotations

import os
import pwd
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


def sudo_invoker() -> pwd.struct_passwd | None:
    """Return the user who invoked sudo, so install does not write into /root."""
    name = os.environ.get("SUDO_USER")
    if os.geteuid() == 0 and name and name != "root":
        return pwd.getpwnam(name)
    return None


def config_dir() -> Path:
    inv = sudo_invoker()
    if inv:
        return Path(inv.pw_dir) / ".config" / "mskb"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "mskb"
    return Path.home() / ".config" / "mskb"


def config_path() -> Path:
    return config_dir() / "config.json"


def _chown_user(path: Path) -> None:
    inv = sudo_invoker()
    if not inv:
        return
    os.chown(path, inv.pw_uid, inv.pw_gid)


def user_home() -> Path:
    """Session home, honoring $SUDO_USER the same way as the systemd unit path."""
    inv = sudo_invoker()
    return Path(inv.pw_dir) if inv else Path.home()
