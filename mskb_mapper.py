# mskb_mapper.py
#
# Runtime loop for `mskb.py run`: read hidraw, emit uinput keys, run exec.
# Dual-fire when both key and exec are set stays here; the GUI never
# writes that shape.
#
# Used by: mskb.py (cmd_run)
# See also: mskb_hid.py, mskb_bindings.py

from __future__ import annotations

import os
import select
import subprocess
from typing import Iterable

from mskb_bindings import ensure_config, load_config
from mskb_hid import (
    FAVORITE_TO_KEY,
    FF05_TO_FAVORITE,
    ParsedReport,
    UInputKeyboard,
    decode_report,
    load_key_table,
    open_hidraw,
)
from mskb_paths import config_path


def _run_exec(command: str) -> None:
    if not command.strip():
        return
    subprocess.Popen(
        command,
        shell=True,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _binding_for(ids: Iterable[str], bindings: dict) -> tuple[str, dict] | None:
    for key_id in ids:
        if key_id in bindings:
            return key_id, bindings[key_id]
    return None


def cmd_run(_: object) -> int:
    path = ensure_config()
    config = load_config(path)
    bindings = config.get("bindings", {})
    key_table = load_key_table()
    opened = open_hidraw()
    uinput = UInputKeyboard()
    print(f"Mapper running. Config: {path}")

    active: dict[str, str] = {}
    seen_unbound: set[str] = set()
    fds = {fd: dev for fd, dev in opened}
    try:
        while True:
            ready, _, _ = select.select(list(fds), [], [], 1.0)
            for fd in ready:
                try:
                    data = os.read(fd, 64)
                except BlockingIOError:
                    continue
                parsed = decode_report(data)
                if parsed is None or parsed.report_id == 0x21:
                    continue
                _handle_report(parsed, bindings, key_table, uinput, active, seen_unbound)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        for name, key in list(active.items()):
            code = key_table.get(key.upper())
            if code:
                uinput.emit(code, False)
            active.pop(name, None)
        uinput.close()
        for fd, _ in opened:
            os.close(fd)
    return 0


def _release_active(
    uinput: UInputKeyboard,
    key_table: dict[str, int],
    active: dict[str, str],
    keep: str | None = None,
) -> None:
    for name, key in list(active.items()):
        if keep is not None and name == keep:
            continue
        code = key_table.get(key.upper()) if key else None
        if code:
            uinput.emit(code, False)
        active.pop(name, None)


def _handle_report(
    parsed: ParsedReport,
    bindings: dict,
    key_table: dict[str, int],
    uinput: UInputKeyboard,
    active: dict[str, str],
    seen_unbound: set[str],
) -> None:
    # Empty extra-key report = all of those keys released.
    if not parsed.ids:
        if parsed.report_id in (0x07, 0x16):
            _release_active(uinput, key_table, active)
        return

    matched = _binding_for(parsed.ids, bindings)
    if not matched and parsed.ff05 in FF05_TO_FAVORITE:
        fav = FF05_TO_FAVORITE[parsed.ff05]
        matched = (f"favorites_{fav}", {"key": FAVORITE_TO_KEY[fav], "exec": ""})
    if not matched:
        token = ",".join(parsed.ids)
        if token not in seen_unbound:
            seen_unbound.add(token)
            print(f"unbound: {token}  (add this id to {config_path()})")
        return

    name, binding = matched
    _release_active(uinput, key_table, active, keep=name)
    key_name = (binding.get("key") or "").strip().upper()
    command = binding.get("exec") or ""

    if name in active:
        return
    if command:
        _run_exec(command)
    if key_name:
        code = key_table.get(key_name)
        if code is None:
            print(f"unknown key name {key_name!r} for {name}")
            return
        uinput.emit(code, True)
        active[name] = key_name
        return
    if command:
        active[name] = ""
        return
    print(f"{name} has empty key and exec")
