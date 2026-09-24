# Microsoft Wireless Keyboard 2000 on Linux

The extra keys are not dead hardware. The Nano transceiver (`045e:0745`,
advertised as “Microsoft 2.4GHz Transceiver v7.0”) sends them as HID reports
that Linux `hid-generic` does not turn into key events.

On Windows, Mouse and Keyboard Center talks that vendor protocol. Here
`mskb.py` reads hidraw and emits keys or runs commands.

**How to install, bind keys, and start at login:** [docs/usage.md](docs/usage.md)

Assign My Favorites in the GUI: `python3 mskb.py gui` (GTK4 / libadwaita).

## What the kernel actually sees

| Keys | HID | Kernel today |
| --- | --- | --- |
| QWERTY, modifiers | Boot keyboard, interface 0 | Works |
| Mouse | Interface 1 | Works |
| Volume, mute, play, next/prev, mail, calculator, home, zoom | Consumer page (`0x0C`) | Usually already evdev; bind in Settings |
| My Favorites 1–5 | Vendor usage `0xff05` (report id 7) | **Dropped** — mapper emits F14–F18 |
| My Favorites (star) | Consumer `0x0182` | **Dropped** — mapper id `favorites_star` (F13) |

`hid-microsoft` already maps `0xff05` → F14–F18 on older product IDs
(Natural 4000/7000). `0745` is not in that table, so the module never loads.

`sudo python3 mskb.py bind-driver --yes` adds this PID at runtime (keyboard
and mouse rebind for a moment). Do not use it together with `mskb.py run`.
The userspace mapper is the supported path; see [docs/usage.md](docs/usage.md).
