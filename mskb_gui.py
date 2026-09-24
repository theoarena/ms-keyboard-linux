# mskb_gui.py
#
# GTK4/libadwaita window to assign actions to My Favorites keys.
# Writes the same config.json the mapper reads, then restarts the user unit.
# Lives in a separate module so `probe`/`run` never import GI.
#
# ComboRows stay siblings in one PreferencesGroup (shown/hidden) because a
# ComboRow is a ListBoxRow and cannot live inside a Stack that is also a row.

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, Gtk  # noqa: E402

import mskb  # noqa: E402

ACTION_LABELS = ("Open app", "System shortcut", "Command", "Nothing")
ACTION_KINDS = ("app", "key", "command", "none")
FAVORITE_LABELS = {
    "favorites_star": "★",
    "favorites_1": "1",
    "favorites_2": "2",
    "favorites_3": "3",
    "favorites_4": "4",
    "favorites_5": "5",
}
FAVORITE_A11Y = {
    "favorites_star": "Favorite star",
    "favorites_1": "Favorite 1",
    "favorites_2": "Favorite 2",
    "favorites_3": "Favorite 3",
    "favorites_4": "Favorite 4",
    "favorites_5": "Favorite 5",
}


def _installed_apps() -> list[tuple[str, str]]:
    """List visible desktop apps as (display name, stripped Exec command).
    @tags: #action/normalize #model/desktop #subject/form #type/helper
    """
    seen: set[str] = set()
    apps: list[tuple[str, str]] = []
    for info in Gio.AppInfo.get_all():
        if not info.should_show():
            continue
        name = info.get_display_name() or info.get_name() or ""
        raw = info.get_commandline() or info.get_executable() or ""
        command = mskb.strip_field_codes(raw)
        if not name or not command or command in seen:
            continue
        seen.add(command)
        apps.append((name, command))
    apps.sort(key=lambda item: item[0].casefold())
    return apps


def _fill_combo(row: Adw.ComboRow, items: list[str], searchable: bool = False) -> None:
    """Populate a ComboRow model from string labels.
    @tags: #subject/form #side-effect/mutation #type/helper
    """
    row.set_model(Gtk.StringList.new(items))
    row.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
    if searchable and hasattr(row, "set_enable_search"):
        row.set_enable_search(True)


def _copy_bindings(bindings: dict[str, dict]) -> dict[str, dict]:
    """Shallow-copy binding dicts for dirty-state comparison.
    @tags: #model/binding #model/config #type/helper
    """
    return {key: dict(value) for key, value in bindings.items()}


class FavoritesWindow(Adw.ApplicationWindow):
    """GTK window to edit My Favorites bindings and apply to config.json.
    @tags: #model/config #scope/gui #subject/favorites #subject/form #type/window
    """

    def __init__(self, app: Adw.Application) -> None:
        """Build strip, form, and load initial favorite binding.
        @tags: #model/config #scope/gui #subject/form #type/window
        """
        super().__init__(application=app, title="Microsoft Keyboard")
        self.set_default_size(560, 480)
        self.set_icon_name("input-keyboard")

        self._syncing = False
        self.config_path = mskb.ensure_config()
        loaded = mskb.load_config(self.config_path)
        self.working = {
            key_id: dict(loaded.get("bindings", {}).get(key_id, {"key": "", "exec": ""}))
            for key_id in mskb.FAVORITE_IDS
        }
        self.original = _copy_bindings(self.working)
        self.current_id = mskb.FAVORITE_IDS[0]
        self.apps = _installed_apps()
        self._app_commands = [command for _, command in self.apps]
        self._key_choices = list(mskb.SYSTEM_SHORTCUT_KEYS)
        self._toggles: list[Gtk.ToggleButton] = []

        overlay = Adw.ToastOverlay()
        self.overlay = overlay
        self.set_content(overlay)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        overlay.set_child(root)

        header = Adw.HeaderBar()
        header.set_title_widget(
            Adw.WindowTitle(title="Microsoft Keyboard", subtitle="My Favorites")
        )
        self.restart_btn = Gtk.Button()
        self.restart_btn.set_icon_name("view-refresh-symbolic")
        self.restart_btn.set_tooltip_text("Restart Mapper")
        self.restart_btn.update_property(
            [Gtk.AccessibleProperty.LABEL], ["Restart Mapper"]
        )
        self.restart_btn.connect("clicked", self._on_restart_mapper)
        header.pack_start(self.restart_btn)

        self.apply_btn = Gtk.Button(label="Apply")
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.set_sensitive(False)
        self.apply_btn.set_receives_default(True)
        self.apply_btn.connect("clicked", self._on_apply)
        header.pack_end(self.apply_btn)
        root.append(header)
        self.set_default_widget(self.apply_btn)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        root.append(scrolled)

        clamp = Adw.Clamp(maximum_size=500, tightening_threshold=400)
        scrolled.set_child(clamp)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        inner.set_margin_top(24)
        inner.set_margin_bottom(24)
        inner.set_margin_start(12)
        inner.set_margin_end(12)
        clamp.set_child(inner)

        inner.append(self._build_strip())
        inner.append(self._build_form())

        self._load_form()
        self._update_dirty()

    def _build_strip(self) -> Gtk.Box:
        """Favorite star/1–5 toggle strip.
        @tags: #model/favorite #subject/favorites #subject/form #type/window
        """
        strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        strip.add_css_class("linked")
        strip.set_halign(Gtk.Align.CENTER)
        strip.set_valign(Gtk.Align.CENTER)
        group_leader: Gtk.ToggleButton | None = None
        for key_id in mskb.FAVORITE_IDS:
            button = Gtk.ToggleButton(label=FAVORITE_LABELS[key_id])
            button.set_tooltip_text(FAVORITE_A11Y[key_id])
            button.update_property(
                [Gtk.AccessibleProperty.LABEL], [FAVORITE_A11Y[key_id]]
            )
            if group_leader is None:
                group_leader = button
            else:
                button.set_group(group_leader)
            button.connect("toggled", self._on_favorite_toggled, key_id)
            strip.append(button)
            self._toggles.append(button)
        self._toggles[0].set_active(True)
        return strip

    def _build_form(self) -> Adw.PreferencesGroup:
        """Action type and value rows (app, shortcut, command).
        @tags: #model/binding #subject/form #type/window
        """
        group = Adw.PreferencesGroup()

        self.action_row = Adw.ComboRow(title="Action")
        _fill_combo(self.action_row, list(ACTION_LABELS))
        self.action_row.connect("notify::selected", self._on_form_changed)
        group.add(self.action_row)

        self.app_row = Adw.ComboRow(title="Application")
        if self.apps:
            _fill_combo(self.app_row, [name for name, _ in self.apps], searchable=True)
        else:
            _fill_combo(self.app_row, ["No applications"])
            self.app_row.set_sensitive(False)
        self.app_row.connect("notify::selected", self._on_form_changed)
        group.add(self.app_row)

        self.key_row = Adw.ComboRow(title="Shortcut")
        _fill_combo(self.key_row, self._key_choices)
        self.key_row.connect("notify::selected", self._on_form_changed)
        group.add(self.key_row)

        self.command_row = Adw.EntryRow(title="Command")
        self.command_row.connect("changed", self._on_form_changed)
        group.add(self.command_row)
        return group

    def _on_favorite_toggled(self, button: Gtk.ToggleButton, key_id: str) -> None:
        """Switch the edited favorite and persist the previous form to working state.
        @tags: #model/favorite #side-effect/mutation #subject/form #type/window
        """
        if self._syncing:
            return
        if not button.get_active():
            if not any(item.get_active() for item in self._toggles):
                self._syncing = True
                button.set_active(True)
                self._syncing = False
            return
        if key_id == self.current_id:
            return
        self._write_form_to_working()
        self.current_id = key_id
        self._load_form()

    def _on_form_changed(self, *_args) -> None:
        """React to form edits: sync working bindings and dirty state.
        @tags: #side-effect/mutation #subject/form #type/window
        """
        if self._syncing:
            return
        self._write_form_to_working()
        self._show_value_rows(self._selected_kind())
        self._update_dirty()

    def _selected_kind(self) -> str:
        """Map action combo selection to binding kind id.
        @tags: #action/normalize #model/binding #subject/form #type/helper
        """
        index = int(self.action_row.get_selected())
        if index < 0 or index >= len(ACTION_KINDS):
            return "none"
        return ACTION_KINDS[index]

    def _app_index_for(self, command: str) -> int | None:
        """Resolve installed-app combo index for a stored exec command.
        @tags: #action/normalize #model/desktop #subject/form #type/helper
        """
        stripped = mskb.strip_field_codes(command)
        for index, stored in enumerate(self._app_commands):
            if stored == stripped:
                return index
        return None

    def _kind_for_form(self, binding: dict) -> str:
        """Classify binding for the action combo, treating known exec as Open app.
        @tags: #action/normalize #model/binding #subject/form #type/helper
        """
        kind = mskb.kind_for_binding(binding)
        if kind == "command" and self._app_index_for(binding.get("exec") or "") is not None:
            return "app"
        return kind

    def _load_form(self) -> None:
        """Populate form widgets from the current favorite working binding.
        @tags: #model/binding #model/config #side-effect/mutation #subject/form #type/window
        """
        binding = self.working[self.current_id]
        kind = self._kind_for_form(binding)
        exec_val = binding.get("exec") or ""
        key_val = binding.get("key") or ""

        self._syncing = True
        self.action_row.set_selected(ACTION_KINDS.index(kind))

        if self.apps:
            app_index = self._app_index_for(exec_val)
            self.app_row.set_selected(0 if app_index is None else app_index)

        choices = mskb.shortcut_key_choices(key_val)
        if choices != self._key_choices:
            self._key_choices = choices
            _fill_combo(self.key_row, self._key_choices)
        selected_key = 0
        target = key_val.strip()
        if target:
            for index, name in enumerate(self._key_choices):
                if name.upper() == target.upper():
                    selected_key = index
                    break
        self.key_row.set_selected(selected_key)
        self.command_row.set_text(exec_val)
        self._syncing = False
        self._show_value_rows(kind)

    def _show_value_rows(self, kind: str) -> None:
        """Show app, shortcut, or command row for the selected action kind.
        @tags: #subject/form #side-effect/mutation #type/window
        """
        self.app_row.set_visible(kind == "app")
        self.key_row.set_visible(kind == "key")
        self.command_row.set_visible(kind == "command")

    def _combo_string(self, row: Adw.ComboRow, fallback: list[str]) -> str:
        """Read the selected label from a ComboRow model.
        @tags: #subject/form #type/helper
        """
        selected = int(row.get_selected())
        if selected < 0 or selected >= len(fallback):
            return ""
        return fallback[selected]

    def _write_form_to_working(self) -> None:
        """Persist the visible form into working bindings for current_id.
        @tags: #action/normalize #model/binding #side-effect/mutation #subject/form #type/window
        """
        kind = self._selected_kind()
        if kind == "app":
            value = self._combo_string(self.app_row, self._app_commands)
        elif kind == "key":
            value = self._combo_string(self.key_row, self._key_choices)
        elif kind == "command":
            value = self.command_row.get_text()
        else:
            value = ""
        self.working[self.current_id] = mskb.binding_for_kind(kind, value)

    def _update_dirty(self) -> None:
        """Enable Apply when working bindings differ from last saved snapshot.
        @tags: #side-effect/mutation #subject/form #type/window
        """
        dirty = self.working != self.original
        self.apply_btn.set_sensitive(dirty)

    def _toast(self, title: str, timeout: int = 5) -> None:
        """Show a transient status toast on the window overlay.
        @tags: #side-effect/mutation #subject/form #type/window
        """
        toast = Adw.Toast(title=title)
        toast.set_timeout(timeout)
        self.overlay.add_toast(toast)

    def _reload_mapper(self, *, after_save: bool) -> None:
        """Restart the systemd mapper and toast status/reason.
        @tags: #side-effect/process #subject/form #type/window
        """
        status, reason = mskb.restart_mapper()
        if status == "ok":
            if after_save:
                self._toast("Favorites updated")
            else:
                self._toast(mskb.mapper_status_message(status, reason))
            return
        detail = mskb.mapper_status_message(status, reason)
        if after_save:
            self._toast(f"Favorites saved. {detail}", timeout=8)
        else:
            self._toast(detail, timeout=8)

    def _on_restart_mapper(self, *_args) -> None:
        """Header action: reload mapper without rewriting config.
        @tags: #side-effect/process #subject/form #type/window
        """
        self._reload_mapper(after_save=False)

    def _on_apply(self, *_args) -> None:
        """Save favorites to config and restart the mapper.
        @tags: #action/save #model/config #side-effect/file #side-effect/mutation #side-effect/process #subject/form #type/window
        """
        if not self.apply_btn.get_sensitive():
            return
        self._write_form_to_working()
        try:
            mskb.save_config(self.config_path, {"bindings": dict(self.working)})
        except OSError:
            self._toast("Could not save favorites.")
            return
        self.original = _copy_bindings(self.working)
        self._update_dirty()
        self._reload_mapper(after_save=True)


class FavoritesApp(Adw.Application):
    """Adw application entry for the favorites configuration window.
    @tags: #scope/gui #subject/favorites #type/window
    """

    def __init__(self) -> None:
        super().__init__(application_id="dev.mskb.Favorites")
        self.connect("activate", self._on_activate)

    def _on_activate(self, _app: Adw.Application) -> None:
        """Present the main FavoritesWindow on application activate.
        @tags: #action/launch #scope/gui #type/window
        """
        window = self.props.active_window
        if window is None:
            window = FavoritesWindow(self)
        window.present()


def run_gui() -> int:
    """Run the GTK main loop for the favorites UI.
    @tags: #action/launch #scope/gui #subject/form #type/command
    """
    app = FavoritesApp()
    return app.run(["mskb"])
