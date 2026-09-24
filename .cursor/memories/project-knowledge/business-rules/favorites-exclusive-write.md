---
summary: "GUI exclusive-write: each favorite stores either key or exec, never both; dual-fire loads as command and Apply on that key drops key"
created: 2026-09-24
category: business-rules
domain: favorites-bindings
tags: [config, exclusive-mode, gtk-gui]
related: [mskb.py, mskb_gui.py, docs/usage.md]
---

# Exclusive write for My Favorites

The JSON contract is unchanged: each binding is `{ "key": "...", "exec": "..." }`.
The mapper still dual-fires when both fields are set (`_handle_report`).

The GTK GUI (`mskb.py gui`) is a write-time projection onto that contract:

| Mode | Written fields |
| --- | --- |
| Open app / Command | `exec` set, `key` cleared |
| System shortcut | `key` set (F13–F24, or a non-standard current value until changed), `exec` cleared |
| Nothing | both `""` |

Load rule: if `exec` is non-empty, the row is Command/App even when `key` is also set
(today's Obsidian+F14 example). The next Apply on that key drops `key`. Unedited
dual-fire rows stay on disk until that key is changed.

`save_config` merges bindings, so ids added by `learn` survive a favorite-only GUI save.
Writes are atomic (`config.json.tmp` then replace).

Ceiling: a checkbox could restore dual-fire later. Do not add fields to JSON for modes.
