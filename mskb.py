#!/usr/bin/env python3
# mskb.py
#
# Userspace bridge for Microsoft Wireless Keyboard 2000 extra keys.
#
# The 045e:0745 transceiver exposes My Favorites on vendor HID usage
# 0xff05. hid-generic drops that page. hid-microsoft can map it to
# F14–F18, but this product ID is not in its table. This tool reads
# hidraw (a copy of the USB reports) and emits real key events or
# runs commands — the Linux equivalent of Mouse and Keyboard Center.
#
# Used by: systemd/mskb.service, mskb_gui.py
# See also: udev/99-mskb.rules, config.example.json

from __future__ import annotations

import argparse
import fcntl
import json
import os
import pwd
import select
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

VID = 0x045E
PID = 0x0745
UINPUT_PATH = "/dev/uinput"
REPO_ROOT = Path(__file__).resolve().parent

# Report 0x21 bit 0xfa1b stays high while the keyboard is awake. Report 7
# leaves vendor bit fe03 set after My Favorites release. Neither is a key.


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

# Linux evdev key codes we emit. Names match X11/GNOME shortcut recording.
KEY_CODES = {
    "F13": 183,
    "F14": 184,
    "F15": 185,
    "F16": 186,
    "F17": 187,
    "F18": 188,
    "F19": 189,
    "F20": 190,
    "F21": 191,
    "F22": 192,
    "F23": 193,
    "F24": 194,
    "PROG1": 148,
    "PROG2": 149,
    "PROG3": 202,
    "PROG4": 203,
    "CALC": 140,
    "MAIL": 155,
    "HOMEPAGE": 172,
    "WWW": 150,
    "MUTE": 113,
    "VOLUMEDOWN": 114,
    "VOLUMEUP": 115,
    "NEXTSONG": 163,
    "PREVIOUSSONG": 165,
    "PLAYPAUSE": 164,
    "STOPCD": 166,
    "ZOOMIN": 418,
    "ZOOMOUT": 419,
    "ZOOMRESET": 420,
    "CHAT": 216,
    "PHONE": 169,
    "MESSENGER": 430,
    "BOOKMARKS": 156,
    "REFRESH": 173,
    "FORWARD": 159,
    "BACK": 158,
    "SEARCH": 217,
    "COMPUTER": 157,
    "FAVORITES": 364,
}

# HID Consumer Page (0x0C) usages this keyboard is known to send.
CONSUMER = {
    0x00B5: "NEXTSONG",
    0x00B6: "PREVIOUSSONG",
    0x00B7: "STOPCD",
    0x00CD: "PLAYPAUSE",
    0x00E2: "MUTE",
    0x00E9: "VOLUMEUP",
    0x00EA: "VOLUMEDOWN",
    0x0182: "FAVORITES",  # My Favorites (star) on Wireless Keyboard 2000
    0x018A: "MAIL",
    0x0192: "CALC",
    0x0194: "COMPUTER",
    0x0196: "WWW",
    0x01A2: "BOOKMARKS",
    0x01AE: "MESSENGER",
    0x0221: "SEARCH",
    0x0223: "HOMEPAGE",
    0x0227: "REFRESH",
    0x022A: "BOOKMARKS",
    0x022D: "ZOOMRESET",
    0x022E: "ZOOMIN",
    0x022F: "ZOOMOUT",
    0x029D: "MS_OFFICE_HOME",
    0x029E: "MS_TASK_PANE",
}

# hid-microsoft maps 0xff05 bit values to F14–F18 (My Favorites 1–5).
FF05_TO_FAVORITE = {0x01: 1, 0x02: 2, 0x04: 3, 0x08: 4, 0x10: 5}
FAVORITE_TO_KEY = {1: "F14", 2: "F15", 3: "F16", 4: "F17", 5: "F18"}

EV_SYN = 0
EV_KEY = 1
SYN_REPORT = 0
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_DEV_SETUP = 0x405C5503
BUS_USB = 0x03

DEFAULT_CONFIG = {
    "_comment": (
        "Match keys from `mskb.py probe`. `key` is emitted via uinput "
        "(bind it in Zorin Settings → Keyboard). `exec` runs on press."
    ),
    "bindings": {
        "favorites_1": {"key": "F14", "exec": ""},
        "favorites_2": {"key": "F15", "exec": ""},
        "favorites_3": {"key": "F16", "exec": ""},
        "favorites_4": {"key": "F17", "exec": ""},
        "favorites_5": {"key": "F18", "exec": ""},
        "favorites_star": {"key": "F13", "exec": ""},
    },
}

# Strip order for the GUI. Defaults still list 1–5 then star to match the example JSON.
"""Favorite binding ids in strip order (star, then 1–5).
@tags: #model/favorite #model/config #subject/favorites #subject/form #type/constant
"""
FAVORITE_IDS = (
    "favorites_star",
    "favorites_1",
    "favorites_2",
    "favorites_3",
    "favorites_4",
    "favorites_5",
)
"""F13–F24 names offered as system shortcut bindings in the GUI.
@tags: #model/shortcut #model/config #subject/form #type/constant
"""
SYSTEM_SHORTCUT_KEYS = tuple(f"F{n}" for n in range(13, 25))
"""`.desktop` Exec field codes stripped before hotkey commands run.
@tags: #model/desktop #format/string #type/constant
"""
_DESKTOP_FIELD_CODES = {
    "%f",
    "%F",
    "%u",
    "%U",
    "%d",
    "%D",
    "%n",
    "%N",
    "%i",
    "%c",
    "%k",
    "%v",
    "%m",
}


@dataclass(frozen=True)
class HidrawDevice:
    path: str
    iface: str
    phys: str


@dataclass
class ParsedReport:
    report_id: int
    raw: bytes
    consumer: int = 0
    keyboard: int = 0
    ff05: int = 0
    fe03: int = 0
    fe04: int = 0
    vendor_fd: int = 0
    fa_bits: int = 0
    ids: list[str] = field(default_factory=list)


def load_key_table() -> dict[str, int]:
    """Merge compiled KEY_* names from the kernel headers when available."""
    codes = dict(KEY_CODES)
    header = Path("/usr/include/linux/input-event-codes.h")
    if not header.exists():
        return codes
    for line in header.read_text(errors="ignore").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "#define" and parts[1].startswith("KEY_"):
            name = parts[1][4:]
            try:
                codes.setdefault(name, int(parts[2], 0))
            except ValueError:
                continue
    return codes


def hidraw_devices() -> list[HidrawDevice]:
    """Find hidraw nodes for the Microsoft 045e:0745 transceiver."""
    found: list[HidrawDevice] = []
    base = Path("/sys/class/hidraw")
    if not base.exists():
        return found
    for node in sorted(base.iterdir()):
        uevent_path = node / "device" / "uevent"
        if not uevent_path.exists():
            continue
        uevent = uevent_path.read_text(errors="ignore")
        if "0000045E:00000745" not in uevent.upper():
            continue
        phys = ""
        for line in uevent.splitlines():
            if line.startswith("HID_PHYS="):
                phys = line.split("=", 1)[1]
        iface = phys.rsplit("/", 1)[-1] if phys else "?"
        found.append(HidrawDevice(path=f"/dev/{node.name}", iface=iface, phys=phys))
    return found


def evdev_devices() -> list[Path]:
    """Return /dev/input/event* nodes that belong to the transceiver."""
    devices: list[Path] = []
    sys_input = Path("/sys/class/input")
    if not sys_input.exists():
        return devices
    for event in sorted(sys_input.glob("event*")):
        uevent = event / "device" / "uevent"
        if not uevent.exists():
            continue
        text = uevent.read_text(errors="ignore")
        if "045E" in text.upper() and "0745" in text:
            devices.append(Path("/dev/input") / event.name)
    return devices


def decode_report(data: bytes) -> ParsedReport | None:
    """Decode extra-key reports. Mouse motion reports are ignored."""
    if not data:
        return None
    rid = data[0]
    parsed = ParsedReport(report_id=rid, raw=data)

    # Interface 2, report 7: consumer + keyboard + My Favorites bitfield.
    if rid == 0x07 and len(data) >= 8:
        parsed.consumer = data[1] | (data[2] << 8)
        parsed.keyboard = data[3]
        packed = data[5]
        parsed.fe03 = packed & 0x01
        parsed.fe04 = (packed >> 1) & 0x01
        parsed.ff05 = (packed >> 2) & 0x1F
        parsed.vendor_fd = data[6]
    # Interface 1, report 0x16: consumer + vendor fd usage.
    elif rid == 0x16 and len(data) >= 4:
        parsed.consumer = data[1] | (data[2] << 8)
        parsed.vendor_fd = data[3]
    # Interface 2, report 0x21: 16 vendor bits (fa10–fa1f).
    elif rid == 0x21 and len(data) >= 3:
        parsed.fa_bits = data[1] | (data[2] << 8)
    else:
        return None

    parsed.ids = _ids_for(parsed)
    if rid in (0x07, 0x16, 0x21):
        return parsed
    return parsed if parsed.ids else None


def _ids_for(parsed: ParsedReport) -> list[str]:
    # fe03/fe04 and report 0x21 are status, not keys, on 045e:0745.
    ids: list[str] = []
    if parsed.ff05:
        fav = FF05_TO_FAVORITE.get(parsed.ff05)
        if fav:
            ids.append(f"favorites_{fav}")
        ids.append(f"ff05_0x{parsed.ff05:02x}")
    if parsed.consumer:
        ids.append(f"consumer_0x{parsed.consumer:04x}")
        name = CONSUMER.get(parsed.consumer)
        if name:
            ids.append(name.lower())
            if name in ("BOOKMARKS", "FAVORITES"):
                ids.append("favorites_star")
    if parsed.keyboard:
        ids.append(f"kbd_0x{parsed.keyboard:02x}")
    if parsed.vendor_fd:
        ids.append(f"fd_0x{parsed.vendor_fd:02x}")
        if parsed.vendor_fd == 0x06:
            ids.append("chat")
        if parsed.vendor_fd == 0x07:
            ids.append("phone")
    return ids


def primary_id(parsed: ParsedReport) -> str | None:
    for item in parsed.ids:
        if item.startswith("favorites_"):
            return item
    return parsed.ids[0] if parsed.ids else None


def format_report(parsed: ParsedReport) -> str:
    parts = [f"id=0x{parsed.report_id:02x}", parsed.raw.hex(" ")]
    if parsed.consumer:
        name = CONSUMER.get(parsed.consumer, "consumer")
        parts.append(f"consumer=0x{parsed.consumer:04x}({name})")
    if parsed.keyboard:
        parts.append(f"kbd=0x{parsed.keyboard:02x}")
    if parsed.ff05:
        fav = FF05_TO_FAVORITE.get(parsed.ff05)
        label = f"favorites_{fav}" if fav else "unknown"
        parts.append(f"ff05=0x{parsed.ff05:02x}({label})")
    if parsed.vendor_fd:
        parts.append(f"fd=0x{parsed.vendor_fd:02x}")
    if parsed.fe03 or parsed.fe04:
        parts.append(f"fe03={parsed.fe03} fe04={parsed.fe04}")
    if parsed.fa_bits:
        parts.append(f"fa_bits=0x{parsed.fa_bits:04x}")
    if parsed.ids:
        parts.append("ids=" + ",".join(parsed.ids))
    return " ".join(parts)


class UInputKeyboard:
    """Minimal virtual keyboard. Wide KEY range so config can pick any code."""

    def __init__(self, name: str = "MS Keyboard 2000 extra keys") -> None:
        self.fd = os.open(UINPUT_PATH, os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        for code in range(1, 768):
            try:
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
            except OSError:
                continue
        setup = struct.pack(
            "HHHH80sI",
            BUS_USB,
            VID,
            PID,
            1,
            name.encode("utf-8"),
            0,
        )
        # struct uinput_setup may be 92 bytes (id + name[80] + ff_effects_max).
        # Fall back to the older write(uinput_user_dev) path if SETUP fails.
        try:
            fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
        except OSError:
            user_dev = struct.pack(
                "80sHHHHi" + "I" * 64 * 4,
                name.encode("utf-8"),
                BUS_USB,
                VID,
                PID,
                1,
                0,
                *([0] * 256),
            )
            os.write(self.fd, user_dev)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        time.sleep(0.2)

    def emit(self, keycode: int, pressed: bool) -> None:
        event = struct.pack("llHHi", 0, 0, EV_KEY, keycode, 1 if pressed else 0)
        syn = struct.pack("llHHi", 0, 0, EV_SYN, SYN_REPORT, 0)
        os.write(self.fd, event)
        os.write(self.fd, syn)

    def close(self) -> None:
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        finally:
            os.close(self.fd)


def load_config(path: Path) -> dict:
    if not path.exists():
        return DEFAULT_CONFIG
    with path.open() as fh:
        data = json.load(fh)
    bindings = dict(DEFAULT_CONFIG["bindings"])
    bindings.update(data.get("bindings", {}))
    data["bindings"] = bindings
    return data


def ensure_config() -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _chown_user(path.parent)
    if not path.exists():
        example = REPO_ROOT / "config.example.json"
        payload = example.read_text() if example.exists() else json.dumps(DEFAULT_CONFIG, indent=2)
        path.write_text(payload)
        _chown_user(path)
        print(f"Wrote default config: {path}")
    return path


def strip_field_codes(command: str) -> str:
    """Drop .desktop field codes and Flatpak file-forwarding from an Exec line.

    A hotkey has no URI or file list. Copying Exec as-is would leave `%U` / `@@`
    tokens that make Flatpak wait for a file that never arrives.
    @tags: #action/normalize #format/string #model/desktop #subject/desktop #type/helper
    """
    tokens: list[str] = []
    skipping_at = False
    for token in command.split():
        if skipping_at:
            if token == "@@":
                skipping_at = False
            continue
        if token == "--file-forwarding" or token in _DESKTOP_FIELD_CODES:
            continue
        if token.startswith("@@"):
            skipping_at = True
            continue
        tokens.append(token)
    return " ".join(tokens)


def kind_for_binding(binding: dict) -> str:
    """Exclusive GUI mode for a JSON binding.

    Runtime still dual-fires when both fields are set. The GUI projects that
    as Command (exec wins) so the next Apply on this key drops `key`.
    @tags: #action/normalize #model/binding #model/config #subject/form #type/helper
    """
    command = (binding.get("exec") or "").strip()
    key = (binding.get("key") or "").strip()
    if command:
        return "command"
    if key:
        return "key"
    return "none"


def binding_for_kind(kind: str, value: str = "") -> dict:
    """Build a binding with only one of `key` or `exec` set.

    Dual-fire is a mapper feature, not a GUI mode. A later checkbox can opt
    back into both fields; until then writes stay exclusive.
    @tags: #action/normalize #model/binding #model/config #subject/form #type/helper
    """
    if kind in ("command", "app"):
        return {"key": "", "exec": strip_field_codes(value)}
    if kind == "key":
        return {"key": (value or "").strip().upper(), "exec": ""}
    return {"key": "", "exec": ""}


def shortcut_key_choices(current: str = "") -> list[str]:
    """F13–F24 for the shortcut combo, plus a non-standard current value.

    Leaving an unknown name in the list keeps it selectable until the user
    picks a listed F-key. Apply then stores that choice instead.
    @tags: #model/shortcut #model/config #subject/form #type/helper
    """
    keys = list(SYSTEM_SHORTCUT_KEYS)
    current = (current or "").strip()
    if current and current.upper() not in {item.upper() for item in keys}:
        keys.append(current)
    return keys


def save_config(path: Path, config: dict) -> dict:
    """Atomically merge and write config so a crash cannot truncate the file.

    Bindings are merged, not replaced: a favorite-only GUI save keeps ids that
    `learn` added. Other top-level keys on disk are kept unless `config` sets
    them. Returns the merged document that was written.
    @tags: #action/save #action/merge #model/config #side-effect/file #side-effect/mutation
    """
    if path.exists():
        existing = load_config(path)
    else:
        existing = {
            "_comment": DEFAULT_CONFIG["_comment"],
            "bindings": dict(DEFAULT_CONFIG["bindings"]),
        }
    merged = dict(existing)
    for key, value in config.items():
        if key == "bindings":
            continue
        merged[key] = value
    bindings = dict(existing.get("bindings") or {})
    bindings.update(config.get("bindings") or {})
    merged["bindings"] = bindings
    path.parent.mkdir(parents=True, exist_ok=True)
    _chown_user(path.parent)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(merged, indent=2) + "\n")
    tmp.replace(path)
    _chown_user(path)
    return merged


def extra_hidraw_devices() -> list[HidrawDevice]:
    """Hotkeys are on interfaces 1–2. Interface 0 is the boot keyboard."""
    return [dev for dev in hidraw_devices() if dev.iface != "input0"]


def open_hidraw() -> list[tuple[int, HidrawDevice]]:
    opened: list[tuple[int, HidrawDevice]] = []
    errors: list[str] = []
    for dev in extra_hidraw_devices():
        try:
            fd = os.open(dev.path, os.O_RDONLY | os.O_NONBLOCK)
            opened.append((fd, dev))
        except OSError as exc:
            errors.append(f"{dev.path}: {exc}")
    if not opened:
        msg = "No hidraw access for 045e:0745 extra-key interfaces. Run `sudo python3 mskb.py install`, then replug the dongle."
        if errors:
            msg += "\n" + "\n".join(errors)
        raise SystemExit(msg)
    return opened


def cmd_status(_: argparse.Namespace) -> int:
    path = config_path()
    print("Receiver: Microsoft 045e:0745 (2.4GHz Transceiver v7.0)")
    print("Kernel driver: hid-generic (hid-microsoft is NOT bound — Favorites are dropped)")
    print(f"Config: {path} {'(exists)' if path.exists() else '(missing)'}")
    print("hidraw:")
    devices = hidraw_devices()
    if not devices:
        print("  (none found — is the dongle plugged in?)")
    for dev in devices:
        readable = os.access(dev.path, os.R_OK)
        extra = "" if dev.iface == "input0" else " [extra keys]"
        print(f"  {dev.path}  {dev.iface}  {'readable' if readable else 'permission denied'}{extra}")
    print("evdev:")
    for event_path in evdev_devices():
        print(f"  {event_path}  {'readable' if os.access(event_path, os.R_OK) else 'permission denied'}")
    print(f"uinput: {UINPUT_PATH}  {'writable' if os.access(UINPUT_PATH, os.W_OK) else 'permission denied'}")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Print press/release for extra keys. Ignores boot keyboard and 0x21 status bits."""
    opened = open_hidraw()
    print("Listening on extra-key interfaces. Press Favorites 1–5, star, Mail, Calc, Zoom, media.")
    print("Do not type in this terminal (Ctrl+C is enough to stop).")
    held: str | None = None
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
                if parsed is None:
                    if args.verbose and data:
                        print(f"{fds[fd].iface} raw {data.hex(' ')}")
                    continue
                if parsed.report_id == 0x21:
                    if args.verbose:
                        print(f"{fds[fd].iface} status {format_report(parsed)}")
                    continue
                if parsed.report_id not in (0x07, 0x16):
                    continue
                current = primary_id(parsed)
                if current == held:
                    continue
                if held and not current:
                    print(f"RELEASE {held}")
                    held = None
                    continue
                if current:
                    if held:
                        print(f"RELEASE {held}")
                    print(f"PRESS   {current}  {parsed.raw.hex(' ')}")
                    held = current
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        for fd, _ in opened:
            os.close(fd)
    return 0


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


def cmd_run(_: argparse.Namespace) -> int:
    config_path = ensure_config()
    config = load_config(config_path)
    bindings = config.get("bindings", {})
    key_table = load_key_table()
    opened = open_hidraw()
    uinput = UInputKeyboard()
    print(f"Mapper running. Config: {config_path}")

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


def cmd_learn(args: argparse.Namespace) -> int:
    """Capture the next extra key and print the binding id to add to config.
    @tags: #action/save #model/config #side-effect/mutation #subject/cli #type/command
    """
    opened = open_hidraw()
    target = args.name
    print(f"Press the physical key to bind as {target!r}. Ctrl+C to cancel.")
    fds = {fd: dev for fd, dev in opened}
    captured = None
    try:
        while captured is None:
            ready, _, _ = select.select(list(fds), [], [], 1.0)
            for fd in ready:
                try:
                    data = os.read(fd, 64)
                except BlockingIOError:
                    continue
                parsed = decode_report(data)
                if parsed and parsed.report_id in (0x07, 0x16) and parsed.ids:
                    captured = parsed
                    break
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 1
    finally:
        for fd, _ in opened:
            os.close(fd)

    assert captured is not None
    print(format_report(captured))
    primary = primary_id(captured) or captured.ids[0]
    print(f"Suggested config id: {primary}")
    if target:
        ensure_config()
        path = config_path()
        config = load_config(path)
        existing = config["bindings"].get(target, {"key": "", "exec": ""})
        # Keep the human name the user asked for, and also alias the raw id.
        config["bindings"][target] = existing
        if primary != target:
            config["bindings"][primary] = {"key": existing.get("key", ""), "exec": existing.get("exec", "")}
        save_config(path, config)
        print(f"Updated {path} with {target} / {primary}")
    return 0


def _install_commands() -> list[list[str]]:
    udev_src = REPO_ROOT / "udev" / "99-mskb.rules"
    hwdb_src = REPO_ROOT / "udev" / "61-mskb.hwdb"
    return [
        ["install", "-m", "644", str(udev_src), "/etc/udev/rules.d/99-mskb.rules"],
        ["install", "-m", "644", str(hwdb_src), "/etc/udev/hwdb.d/61-mskb.hwdb"],
        ["systemd-hwdb", "update"],
        ["udevadm", "control", "--reload"],
        ["udevadm", "trigger", "-s", "hidraw"],
        ["udevadm", "trigger", "-s", "input"],
    ]


def _systemctl_user(args: list[str]) -> int:
    inv = sudo_invoker()
    if inv:
        return subprocess.call(
            ["systemctl", "--user", f"--machine={inv.pw_name}@", *args]
        )
    return subprocess.call(["systemctl", "--user", *args])


def user_home() -> Path:
    """Session home, honoring $SUDO_USER the same way as the systemd unit path."""
    inv = sudo_invoker()
    return Path(inv.pw_dir) if inv else Path.home()


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


def _install_user_service() -> None:
    inv = sudo_invoker()
    home = Path(inv.pw_dir) if inv else Path.home()
    unit_dir = home / ".config/systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    _chown_user(home / ".config")
    _chown_user(home / ".config/systemd")
    _chown_user(unit_dir)
    unit = unit_dir / "mskb.service"
    python = sys.executable
    if python.startswith("/root/") or (inv and python == "/usr/bin/python3"):
        python = "/usr/bin/python3"
    unit.write_text(
        "\n".join(
            [
                "[Unit]",
                "Description=Microsoft Keyboard 2000 extra-key mapper",
                "After=graphical-session.target",
                "PartOf=graphical-session.target",
                "",
                "[Service]",
                f"ExecStart={python} {REPO_ROOT / 'mskb.py'} run",
                "Restart=on-failure",
                "RestartSec=2",
                "",
                "[Install]",
                "WantedBy=graphical-session.target",
                "",
            ]
        )
    )
    _chown_user(unit)
    rc = _systemctl_user(["daemon-reload"])
    print(f"Wrote {unit}")
    if rc != 0:
        print("systemctl --user daemon-reload failed (ok if this was sudo). Run as your user:")
        print("  systemctl --user daemon-reload")
    removed = remove_mskb_autostart()
    for path in removed:
        print(f"Removed conflicting autostart: {path}")
    enable_rc = _systemctl_user(["enable", "--now", "mskb.service"])
    if enable_rc != 0:
        print(
            "Could not enable mskb.service (ok if this was sudo without a user bus). "
            "Run as your user:"
        )
        print("  systemctl --user enable --now mskb.service")
    else:
        print("Enabled and started mskb.service")


def desktop_path() -> Path:
    """Path to the user `.desktop` launcher for the GTK favorites GUI.
    @tags: #format/path #model/desktop #scope/user #type/helper
    """
    inv = sudo_invoker()
    home = Path(inv.pw_dir) if inv else Path.home()
    return home / ".local/share/applications/mskb.desktop"


def _desktop_python() -> str:
    """Python interpreter path for `.desktop` Exec when install runs under sudo.
    @tags: #format/path #scope/user #type/helper
    """
    inv = sudo_invoker()
    python = sys.executable
    if python.startswith("/root/") or (inv and python == "/usr/bin/python3"):
        return "/usr/bin/python3"
    return python


def ensure_desktop_file() -> Path:
    """Install a user .desktop so the GUI shows up in the app grid.

    Same $SUDO_USER home as the systemd unit: sudo install must not write
    into /root/.local.
    @tags: #action/save #model/desktop #side-effect/file #side-effect/mutation #scope/user
    """
    path = desktop_path()
    share_dir = path.parent
    local_dir = share_dir.parent
    home_local = local_dir.parent
    for directory in (home_local, local_dir, share_dir):
        directory.mkdir(parents=True, exist_ok=True)
        _chown_user(directory)
    python = _desktop_python()
    path.write_text(
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=Microsoft Keyboard",
                "Comment=Assign My Favorites keys",
                f"Exec={python} {REPO_ROOT / 'mskb.py'} gui",
                "Icon=input-keyboard",
                "Terminal=false",
                "Categories=Settings;HardwareSettings;",
                "StartupNotify=true",
                "",
            ]
        )
    )
    _chown_user(path)
    return path


def cmd_install(_: argparse.Namespace) -> int:
    """Install udev/hwdb so the session user can read hidraw and map unknown consumer keys.
    @tags: #action/install #model/desktop #side-effect/file #side-effect/mutation #subject/cli #type/command
    """
    _install_user_service()
    desktop = ensure_desktop_file()
    print(f"Wrote {desktop}")
    ensure_config()
    if os.geteuid() != 0:
        print("Root is required to install udev rules. Re-run:")
        print(f"  sudo python3 {REPO_ROOT / 'mskb.py'} install")
        print("Then unplug and replug the Microsoft dongle (or reboot).")
        return 1
    for cmd in _install_commands():
        print("+", " ".join(cmd))
        subprocess.check_call(cmd)
    print("Installed udev + hwdb.")
    print(f"  python3 {REPO_ROOT / 'mskb.py'} gui")
    print(f"  python3 {REPO_ROOT / 'mskb.py'} probe")
    print("  systemctl --user enable --now mskb.service")
    return 0


def cmd_bind_driver(args: argparse.Namespace) -> int:
    """Experimental: bind hid-microsoft with MS_ERGONOMY (same as Natural 7000)."""
    if not args.yes:
        print(
            "This unbinds hid-generic from ALL 045e:0745 interfaces (keyboard AND mouse)\n"
            "and binds hid-microsoft with the MS_ERGONOMY quirk so My Favorites become F14–F18.\n"
            "Input will glitch for a second. Pass --yes to actually do it (needs root)."
        )
        return 1
    if os.geteuid() != 0:
        print("Need root: sudo python3 mskb.py bind-driver --yes")
        return 1
    subprocess.check_call(["modprobe", "hid-microsoft"])
    new_id = Path("/sys/bus/hid/drivers/microsoft/new_id")
    # bus=USB(3) vendor product version driver_data=MS_ERGONOMY(2)
    new_id.write_text("3 0x045e 0x0745 0 2")
    hid_generic = Path("/sys/bus/hid/drivers/hid-generic")
    microsoft = Path("/sys/bus/hid/drivers/microsoft")
    for dev in Path("/sys/bus/hid/devices").glob("0003:045E:0745.*"):
        name = dev.name
        unbind = hid_generic / "unbind"
        bind = microsoft / "bind"
        if (hid_generic / name).exists():
            unbind.write_text(name)
        bind.write_text(name)
        print(f"bound {name} -> microsoft")
    print("Favorites 1–5 should now appear as F14–F18 in Settings → Keyboard.")
    return 0


def cmd_gui(_: argparse.Namespace) -> int:
    """Open the favorites window. GI is imported here so probe/run stay GI-free.
    @tags: #action/launch #scope/gui #subject/cli #type/command
    """
    ensure_desktop_file()
    try:
        from mskb_gui import run_gui
    except (ImportError, ValueError, ModuleNotFoundError):
        print(
            "GTK4 / libadwaita is not available. Install:\n"
            "  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1",
            file=sys.stderr,
        )
        return 1
    return run_gui()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Microsoft Wireless Keyboard 2000 extra-key mapper for Linux"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="Show receiver, hidraw permissions, driver").set_defaults(
        func=cmd_status
    )
    probe = sub.add_parser("probe", help="Print extra-key HID reports (press keys)")
    probe.add_argument("-v", "--verbose", action="store_true", help="Show status reports and raw leftover HID")
    probe.set_defaults(func=cmd_probe)
    learn = sub.add_parser("learn", help="Capture one physical key into the config")
    learn.add_argument("name", help="Binding id, e.g. favorites_star")
    learn.set_defaults(func=cmd_learn)
    sub.add_parser("run", help="Emit key events / run commands from config").set_defaults(
        func=cmd_run
    )
    sub.add_parser("install", help="Install udev + hwdb (root)").set_defaults(func=cmd_install)
    sub.add_parser("gui", help="Assign My Favorites in a GTK window").set_defaults(func=cmd_gui)
    bind = sub.add_parser("bind-driver", help="Experimental hid-microsoft quirk bind")
    bind.add_argument("--yes", action="store_true")
    bind.set_defaults(func=cmd_bind_driver)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
