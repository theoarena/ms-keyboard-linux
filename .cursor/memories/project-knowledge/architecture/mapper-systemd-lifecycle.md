---
summary: "Mapper lifecycle is systemd-only: Apply/Restart use restart or enable --now; GNOME autostart mskb.py run entries are removed to prevent dual-fire"
created: 2026-09-24
updated: 2026-09-24
status: resolved
category: architecture
domain: mapper-lifecycle
tags: [systemd, autostart, gui, restart]
related: [mskb.py, mskb_lifecycle.py, mskb_gui.py, docs/usage.md, mskb-public-facade.md]
---

# Mapper systemd lifecycle

Supported login autostart is only `systemctl --user enable --now mskb.service`.

Implementation lives in `mskb_lifecycle.py` (re-exported from `mskb`). Unit
tests that mock `restart_mapper` helpers must patch `mskb_lifecycle`, not only
the facade.

GNOME Startup Applications entries whose `Exec=` launches `mskb.py run` dual-fire
Favorites when the unit is also running. `remove_mskb_autostart()` deletes those
`.desktop` files. Install, Apply, and Restart Mapper all call this cleanup.

`restart_mapper()` returns `(status, reason)`:

| status | reason | meaning |
| --- | --- | --- |
| ok | restarted | unit was active; `systemctl restart` |
| ok | started | unit was inactive; `enable --now` |
| failed | permission | could not SIGTERM/SIGKILL a stray PID |
| failed | systemctl | restart/enable/start returned non-zero |
| failed | not_active | unit still inactive after the attempt |

The GUI must **not** spawn a detached `mskb.py run`. That path caused two mappers
and opaque Apply failures when systemd was disabled.

Open `mskb.py gui` as the session user, never sudo. A root GUI cannot signal a
user mapper (`permission`) and writes config/autostart as root. The header
**Restart Mapper** button calls `restart_mapper()` without saving.
