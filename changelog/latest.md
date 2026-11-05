## [latest]

### Added
- GTK4/libadwaita window (`mskb.py gui`) to assign My Favorites, plus a Restart Mapper header action (`92222a58dc8bdad687461a187cd8c740e27bd7a8`)
- systemd-only mapper restart: Apply/`enable --now` reload `mskb.service` and remove GNOME autostart entries that launch `mskb.py run` (`92222a58dc8bdad687461a187cd8c740e27bd7a8`)
- Mapper learns an extra key from any selected HID device as usage id `vid:pid:page:usage` (wider fields include the value); Wireless Keyboard 2000 favorite ids still match first (`a737e6082c2b22c3f9aafa9067b8b7f014cd4255`)
- GTK window lists saved keys, adds one by pressing it, and removes one (`a737e6082c2b22c3f9aafa9067b8b7f014cd4255`)
- Optional binding `label` is the title on a key card; the mapper still matches the HID id (`66ec7e29c8fe23231e25ad9e6ac8a15c28011ec3`)

### Changed
- Bindings can store optional `kind` so Open app and Command stay distinct after Apply, even when they share an executable. A file without `kind` still infers Open app when the command matches an installed app (`d4edd0f523959f6ad491bd0b35070be1e16a0866`)
- OffKeys opens at 520×680 so the first launch stays under the 720 breakpoint and stacks the keys above the form (`738d4d73bb7a86b63a65163498de0a76fb876599`)
- The window shows what each extra key does, listens with a banner, and asks before discarding unsaved edits. Restart mapper is in the window menu. The window needs libadwaita 1.5 (`f6d9b99e839fbb71fa84fcddea7673275020cb9e`)
- Bindings are nested by `vid:pid` so each keyboard has its own map; the window shows only the selected device; the mapper matches the hidraw that produced the report (`4ba865dca2bdeb1589088f075690957ffcb690cb`)
- Key chooser is a wrapping grid of cards (at most three per row); the HID id is the second line only when a custom title is set (`66ec7e29c8fe23231e25ad9e6ac8a15c28011ec3`)
- Split `mskb.py` into domain sibling modules (`mskb_paths`, `mskb_bindings`, `mskb_hid`, `mskb_mapper`, `mskb_lifecycle`, `mskb_install`) while keeping `mskb.py` as the CLI and `import mskb` facade (`ae244db4468cee59056ce9451c341f8011dc0c44`)
- Renamed `docs/usage.md` to `docs/operator.md` and reframed it as the operator guide (CLI, systemd, hidraw); README stays the end-user app guide
- Config `devices` (default `045e:0745`) chooses which receivers are opened; `save_config(..., replace_bindings=True)` lets the window remove a key (`a737e6082c2b22c3f9aafa9067b8b7f014cd4255`)
- udev grants hidraw read for every device; `udev/61-mskb.hwdb` and `bind-driver` stay on `045e:0745` (`a737e6082c2b22c3f9aafa9067b8b7f014cd4255`)
