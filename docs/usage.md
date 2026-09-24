# Using the extra keys

How to install the mapper, assign actions, and start it at login.
This is the Linux stand-in for Windows Mouse and Keyboard Center.

Repo commands assume you are in the project directory:

```bash
cd ~/microsoft-keyboard
```

## 1. One-time install

Needs sudo once so this user can read the dongle’s hidraw nodes (`plugdev`).
`sudo` writes the systemd user unit into **your** home (`$SUDO_USER`), not `/root`.

```bash
sudo python3 mskb.py install
python3 mskb.py status
```

`status` must show hidraw `input1` and `input2` as **readable**. If they are
denied, unplug and replug the Microsoft USB dongle.

## 2. See what a physical key is called

```bash
python3 mskb.py probe
```

Press each extra key once. Do **not** type in that terminal (the probe is
listening to the keyboard). Stop with Ctrl+C.

Expected ids on this Wireless Keyboard 2000 (`045e:0745`):

| Physical key | Config id | Default `key` |
| --- | --- | --- |
| My Favorites 1–5 | `favorites_1` … `favorites_5` | F14–F18 |
| My Favorites (star) | `favorites_star` (`consumer_0x0182`) | F13 |

Volume, mute, play, mail, calculator, zoom usually already reach the desktop
as normal media keys. Bind those in Zorin Settings → Keyboard, not here.

Unknown extra key:

```bash
python3 mskb.py learn some_name
```

`probe -v` prints firmware status bits. Those are not keys.

## 3. Assign shortcuts

The default way to assign My Favorites is the GTK window:

```bash
python3 mskb.py gui
```

Needs GTK4 and libadwaita (Ubuntu 22.04+ / Zorin 18):

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```

Pick a key (star, 1–5), choose Open app, System shortcut, Command, or
Nothing, then **Apply**. That writes `~/.config/mskb/config.json` and
restarts `mskb.service` (`systemctl --user restart`, or `enable --now` if
the unit was inactive) so the binding works immediately. The header
**Restart Mapper** button does the same reload without saving. Apply also
removes any GNOME Startup Applications entry that launches `mskb.py run`
(those conflict with the systemd unit and dual-fire Favorites).

The first launch also installs a menu entry
(`~/.local/share/applications/mskb.desktop`). `sudo python3 mskb.py install`
writes the same desktop file into the session user’s home.

JSON is still the source of truth. Edit it by hand if you want; restart
the mapper afterwards (section 4).

```json
{
  "bindings": {
    "favorites_1": { "key": "", "exec": "/usr/bin/flatpak run md.obsidian.Obsidian" },
    "favorites_2": { "key": "F15", "exec": "" },
    "favorites_3": { "key": "F16", "exec": "" },
    "favorites_4": { "key": "F17", "exec": "" },
    "favorites_5": { "key": "F18", "exec": "" },
    "favorites_star": { "key": "F13", "exec": "" }
  }
}
```

| Field | Meaning |
| --- | --- |
| `key` | Virtual key via uinput. Record it in Zorin Settings → Keyboard → Shortcuts. Empty string = do not emit. |
| `exec` | Shell command on press. Empty string = do not run a command. |

The GUI writes **one** of those fields, never both. The mapper still
fires both if a hand-edited file sets them (Favorite 1 with Obsidian
**and** F14). Apply on that key in the GUI keeps `exec` and clears `key`.

`exec` is a normal command, not a `.desktop` Exec line. Do not copy
`--file-forwarding @@u %U @@` from Flatpak desktop files; there is no URI
on a hotkey. The GUI strips those tokens. Flatpak apps:

```text
/usr/bin/flatpak run md.obsidian.Obsidian
```

GNOME/Zorin path for the emitted F-keys: Settings → Keyboard → Keyboard
Shortcuts → Custom Shortcuts. The mapper must be running while you record
the key.

## 4. Run it

Foreground (debug, dies when the terminal closes):

```bash
python3 mskb.py run
```

**Supported login autostart** is the systemd user unit only. Run **once**:

```bash
systemctl --user enable --now mskb.service
```

`sudo python3 mskb.py install` writes the unit, removes conflicting GNOME
autostart entries that launch `mskb.py run`, and tries `enable --now` when
the user bus is reachable.

- `enable` — start on future graphical logins (`graphical-session.target`)
- `--now` — start immediately

This is a **user** unit, not a boot service. It starts when you reach the
desktop, which is what GUI `exec` lines need.

Check:

```bash
systemctl --user is-enabled mskb.service
systemctl --user status mskb.service
```

You want `enabled` and `active (running)`. Reload after editing the config
(or use **Apply** / **Restart Mapper** in the GUI):

```bash
systemctl --user restart mskb.service
```

### Do not use GNOME Startup Applications for the mapper

Do **not** add `mskb.py run` (or `systemctl enable`) under GNOME “Startup
Applications” / “Aplicativos iniciais”. That starts a second mapper beside
the unit; Favorites fire twice. Install and the GUI delete those conflicting
`.desktop` files automatically when they launch `mskb.py run`.

## 5. CLI reference

| Command | Role |
| --- | --- |
| `mskb.py status` | Dongle, hidraw permissions, config path |
| `mskb.py probe` | Print `PRESS` / `RELEASE` for extra keys |
| `mskb.py learn NAME` | Capture the next extra key into the config |
| `mskb.py gui` | Assign My Favorites (GTK4) |
| `mskb.py run` | Mapper (uinput + `exec`) |
| `sudo mskb.py install` | udev + hwdb + user unit + desktop entry |
| `sudo mskb.py bind-driver --yes` | Experimental: bind `hid-microsoft` (glitches mouse; do not combine with `run`) |
