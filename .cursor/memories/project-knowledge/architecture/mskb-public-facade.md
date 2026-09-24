---
summary: "mskb.py is the public CLI/import facade; domain code lives in sibling modules — never add a mskb/ package beside mskb.py"
created: 2026-09-24
category: architecture
domain: module-layout
tags: [mskb, facade, imports, systemd]
related: [mskb.py, mskb_bindings.py, mskb_hid.py, mskb_mapper.py, mskb_lifecycle.py, mskb_install.py, mskb_paths.py, mskb_gui.py]
---

# mskb.py public facade

`python3 mskb.py` and `import mskb` are the public surface. systemd
`ExecStart`, the app-grid `.desktop`, README install, and tests all
point at this file.

Domain code lives in sibling modules in the repo root:

| Module | Responsibility |
| --- | --- |
| `mskb_paths.py` | `REPO_ROOT`, sudo home, config path |
| `mskb_bindings.py` | config.json + exclusive GUI write helpers |
| `mskb_hid.py` | HID decode, hidraw/evdev, uinput |
| `mskb_mapper.py` | `run` loop (dual-fire) |
| `mskb_lifecycle.py` | autostart cleanup, `restart_mapper` |
| `mskb_install.py` | udev, user unit, `.desktop`, bind-driver |

Do **not** create a package directory named `mskb/`. It cannot coexist
with `mskb.py`: `import mskb` becomes ambiguous and breaks the GUI and
tests.

`cmd_gui` keeps the lazy `from mskb_gui import run_gui` so `probe`/`run`
never load GI. `mskb_bindings` and `mskb_lifecycle` must not import
`mskb_hid`. Locked by `tests/test_import_boundary.py`.

When mocking internals of `restart_mapper`, patch `mskb_lifecycle`
(where the names are resolved), not only the `mskb` re-exports.
