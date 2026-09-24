# mskb_hid.py
#
# HID decode, hidraw/evdev discovery, and the virtual uinput keyboard.
# Stays free of config.json and systemd so probe/status can import it
# without pulling GUI or install paths.
#
# Used by: mskb_mapper.py, mskb.py (status/probe/learn)
# See also: udev/99-mskb.rules

from __future__ import annotations

import fcntl
import os
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

VID = 0x045E
PID = 0x0745
UINPUT_PATH = "/dev/uinput"

# Report 0x21 bit 0xfa1b stays high while the keyboard is awake. Report 7
# leaves vendor bit fe03 set after My Favorites release. Neither is a key.

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
