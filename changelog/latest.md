## [latest]

### Added
- GTK4/libadwaita window (`mskb.py gui`) to assign My Favorites, plus a Restart Mapper header action (`92222a58dc8bdad687461a187cd8c740e27bd7a8`)
- systemd-only mapper restart: Apply/`enable --now` reload `mskb.service` and remove GNOME autostart entries that launch `mskb.py run` (`92222a58dc8bdad687461a187cd8c740e27bd7a8`)

### Changed
- Split `mskb.py` into domain sibling modules (`mskb_paths`, `mskb_bindings`, `mskb_hid`, `mskb_mapper`, `mskb_lifecycle`, `mskb_install`) while keeping `mskb.py` as the CLI and `import mskb` facade (`ae244db4468cee59056ce9451c341f8011dc0c44`)
