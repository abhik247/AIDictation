import os
import sys
import time
import shutil
import subprocess
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Gdk, GLib, GObject, Adw

from ..models import AppSettings, RewordingPrompt, ApiProvider
from ..services.settings_service import SettingsService
from ..services.startup_service import StartupRegistrationService
from ..services.audio_recorder import AudioRecorder
from ..services.openai_service import OpenAIService
from ..services.reword_service import RewordService
from .floating_widget import FloatingRecorderWidget


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="AI Dictation")
        self.set_default_size(700, 750)

        self._settings_service = SettingsService()
        self._startup_service = StartupRegistrationService()
        self.settings: AppSettings = self._settings_service.load()

        self._recorder = AudioRecorder()
        self._openai_service = OpenAIService()
        self._reword_service = RewordService()

        # State fields
        self.recording_state = 0  # 0: Idle, 1: Recording, 2: Recorded
        self.is_paused = False
        self.audio_level = 0.0
        self._smoothed_level = 0.0
        self.recording_time_str = "00:00"

        # Undo / Redo history
        self._undo_stack = [""]
        self._undo_index = 0
        self._is_updating_from_undo = False
        self._debounce_timer_id = None

        # Floating recorder widget
        self._floating_widget = None

        # Wire recorder callbacks
        self._recorder.audio_level_changed = self._on_audio_level_changed
        self._recorder.recording_duration_changed = self._on_recording_duration_changed

        self._build_ui()
        self._apply_settings_to_ui()
        self._setup_shortcuts()

        # Connect window close handler
        self.connect("close-request", self._on_close_requested)

    def _build_ui(self):
        self.toast_overlay = Adw.ToastOverlay()

        # Navigation stack to handle Main View, Settings View, API Settings, Prompts Customization
        self.nav_stack = Gtk.Stack()
        self.nav_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)

        # 1. Main View
        self.main_view = self._build_main_view()
        self.nav_stack.add_named(self.main_view, "main")

        # 2. General Settings View
        self.settings_view = self._build_settings_view()
        self.nav_stack.add_named(self.settings_view, "settings")

        # 3. API Settings View
        self.api_settings_view = self._build_api_settings_view()
        self.nav_stack.add_named(self.api_settings_view, "api_settings")

        # 4. Customize Prompts View
        self.prompts_view = self._build_prompts_view()
        self.nav_stack.add_named(self.prompts_view, "prompts")

        self.toast_overlay.set_child(self.nav_stack)
        self.set_content(self.toast_overlay)

    def _build_main_view(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(18)
        box.set_margin_end(18)

        # Header Bar
        header_bar = Adw.HeaderBar()
        title_widget = Adw.WindowTitle(title="AI Dictation", subtitle="Voice transcription powered by AI")
        header_bar.set_title_widget(title_widget)

        # Language Combo Dropdown
        self.lang_model = Gtk.StringList.new(["English", "Bengali (bn-IN)", "Hindi"])
        self.lang_dropdown = Gtk.DropDown.new(self.lang_model, None)
        self.lang_dropdown.set_selected(0)
        self.lang_dropdown.connect("notify::selected", self._on_language_changed)
        header_bar.pack_end(self.lang_dropdown)

        # Settings Gear Button
        settings_btn = Gtk.Button(icon_name="emblem-system-symbolic")
        settings_btn.set_tooltip_text("Settings")
        settings_btn.connect("clicked", lambda _: self.nav_stack.set_visible_child_name("settings"))
        header_bar.pack_end(settings_btn)

        box.append(header_bar)

        # Mic Level Label & Progress Bar
        mic_label = Gtk.Label(label="Microphone Level", xalign=0)
        mic_label.add_css_class("heading")
        box.append(mic_label)

        self.level_progress = Gtk.ProgressBar()
        self.level_progress.set_fraction(0.0)
        box.append(self.level_progress)

        # Transcript Header Label
        transcript_label = Gtk.Label(label="Transcript", xalign=0)
        transcript_label.add_css_class("heading")
        box.append(transcript_label)

        # Multiline Transcript Text View
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        self.transcript_buffer = Gtk.TextBuffer()
        self.transcript_buffer.connect("changed", self._on_transcript_text_changed)

        self.transcript_view = Gtk.TextView(buffer=self.transcript_buffer)
        self.transcript_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.transcript_view.set_left_margin(12)
        self.transcript_view.set_right_margin(12)
        self.transcript_view.set_top_margin(12)
        self.transcript_view.set_bottom_margin(12)
        scrolled.set_child(self.transcript_view)

        box.append(scrolled)

        # Action Buttons Row 1: Recording & Rewording controls
        controls_box_1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        # Idle State: Record Button
        self.record_button = Gtk.Button(label="🎤 Record")
        self.record_button.add_css_class("suggested-action")
        self.record_button.add_css_class("pill")
        self.record_button.set_size_request(130, 45)
        self.record_button.connect("clicked", self._on_record_clicked)
        controls_box_1.append(self.record_button)

        # Recording State: Trash, Send, Pause buttons
        self.recording_controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.recording_controls_box.set_visible(False)

        # Trash button
        trash_btn = Gtk.Button(label="🗑")
        trash_btn.set_tooltip_text("Discard")
        trash_btn.connect("clicked", self._on_trash_clicked)
        self.recording_controls_box.append(trash_btn)

        # Send button
        self.send_btn_label = Gtk.Label(label="➤ Send 00:00")
        self.send_btn = Gtk.Button()
        self.send_btn.set_child(self.send_btn_label)
        self.send_btn.add_css_class("suggested-action")
        self.send_btn.connect("clicked", lambda _: self._send_for_transcription(insert_into_app=False))
        self.recording_controls_box.append(self.send_btn)

        # Pause / Resume button
        self.pause_btn = Gtk.Button(label="⏸")
        self.pause_btn.set_tooltip_text("Pause / Resume")
        self.pause_btn.connect("clicked", self._on_pause_clicked)
        self.recording_controls_box.append(self.pause_btn)

        controls_box_1.append(self.recording_controls_box)

        # Undo / Redo
        self.undo_btn = Gtk.Button(icon_name="edit-undo-symbolic")
        self.undo_btn.set_tooltip_text("Undo")
        self.undo_btn.set_sensitive(False)
        self.undo_btn.connect("clicked", self._on_undo_clicked)
        controls_box_1.append(self.undo_btn)

        self.redo_btn = Gtk.Button(icon_name="edit-redo-symbolic")
        self.redo_btn.set_tooltip_text("Redo")
        self.redo_btn.set_sensitive(False)
        self.redo_btn.connect("clicked", self._on_redo_clicked)
        controls_box_1.append(self.redo_btn)

        # Reword Menu Button with Popover
        self.reword_popover = Gtk.Popover()
        self.reword_menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.reword_menu_box.set_margin_top(8)
        self.reword_menu_box.set_margin_bottom(8)
        self.reword_menu_box.set_margin_start(8)
        self.reword_menu_box.set_margin_end(8)
        self.reword_popover.set_child(self.reword_menu_box)

        self.reword_btn = Gtk.MenuButton(label="Reword")
        self.reword_btn.set_popover(self.reword_popover)
        controls_box_1.append(self.reword_btn)

        box.append(controls_box_1)

        # Action Buttons Row 2: Insert, Copy, Select All, Clear All
        controls_box_2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        insert_btn = Gtk.Button(label="Insert")
        insert_btn.add_css_class("accent")
        insert_btn.connect("clicked", self._on_insert_clicked)
        controls_box_2.append(insert_btn)

        copy_btn = Gtk.Button(label="Copy")
        copy_btn.connect("clicked", self._on_copy_clicked)
        controls_box_2.append(copy_btn)

        select_all_btn = Gtk.Button(label="Select All")
        select_all_btn.connect("clicked", self._on_select_all_clicked)
        controls_box_2.append(select_all_btn)

        clear_all_btn = Gtk.Button(label="Clear All")
        clear_all_btn.connect("clicked", self._on_clear_all_clicked)
        controls_box_2.append(clear_all_btn)

        box.append(controls_box_2)

        return box

    def _build_settings_view(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        header_bar = Adw.HeaderBar()
        title_widget = Adw.WindowTitle(title="Settings")
        header_bar.set_title_widget(title_widget)

        back_btn = Gtk.Button(icon_name="go-previous-symbolic")
        back_btn.set_tooltip_text("Back")
        back_btn.connect("clicked", lambda _: self.nav_stack.set_visible_child_name("main"))
        header_bar.pack_start(back_btn)

        box.append(header_bar)

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="General Preferences")

        # Always on top
        self.always_on_top_row = Adw.SwitchRow(title="Always on top")
        self.always_on_top_row.connect("notify::active", self._on_always_on_top_toggled)
        group.add(self.always_on_top_row)

        # Launch at startup
        self.launch_startup_row = Adw.SwitchRow(title="Launch at startup")
        self.launch_startup_row.connect("notify::active", self._on_launch_startup_toggled)
        group.add(self.launch_startup_row)

        # Keep running in background
        self.background_row = Adw.SwitchRow(title="Keep running in background")
        self.background_row.connect("notify::active", self._on_background_toggled)
        group.add(self.background_row)

        page.add(group)

        group_nav = Adw.PreferencesGroup(title="Configuration")

        api_btn_row = Adw.ActionRow(title="API Settings")
        api_btn_row.set_activatable(True)
        api_btn_row.connect("activated", lambda _: self.nav_stack.set_visible_child_name("api_settings"))
        group_nav.add(api_btn_row)

        prompts_btn_row = Adw.ActionRow(title="Customize Rewording Prompts")
        prompts_btn_row.set_activatable(True)
        prompts_btn_row.connect("activated", lambda _: self.nav_stack.set_visible_child_name("prompts"))
        group_nav.add(prompts_btn_row)

        page.add(group_nav)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(page)
        scrolled.set_vexpand(True)
        box.append(scrolled)

        return box

    def _build_api_settings_view(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        header_bar = Adw.HeaderBar()
        title_widget = Adw.WindowTitle(title="API Settings")
        header_bar.set_title_widget(title_widget)

        back_btn = Gtk.Button(icon_name="go-previous-symbolic")
        back_btn.set_tooltip_text("Back")
        back_btn.connect("clicked", lambda _: self.nav_stack.set_visible_child_name("settings"))
        header_bar.pack_start(back_btn)

        box.append(header_bar)

        page = Adw.PreferencesPage()

        # --- Transcription Group ---
        trans_group = Adw.PreferencesGroup(title="Transcription Settings")

        self.trans_provider_model = Gtk.StringList.new(["OpenAI", "Gemini"])
        self.trans_provider_row = Adw.ComboRow(title="Provider", model=self.trans_provider_model)
        self.trans_provider_row.connect("notify::selected", self._on_trans_provider_changed)
        trans_group.add(self.trans_provider_row)

        self.trans_key_row = Adw.EntryRow(title="API Key")
        self.trans_host_row = Adw.EntryRow(title="Host")
        self.trans_model_row = Adw.EntryRow(title="Model")

        trans_group.add(self.trans_key_row)
        trans_group.add(self.trans_host_row)
        trans_group.add(self.trans_model_row)

        page.add(trans_group)

        # --- Rewording Group ---
        reword_group = Adw.PreferencesGroup(title="Rewording Settings")

        self.reword_provider_model = Gtk.StringList.new(["OpenAI", "Gemini"])
        self.reword_provider_row = Adw.ComboRow(title="Provider", model=self.reword_provider_model)
        self.reword_provider_row.connect("notify::selected", self._on_reword_provider_changed)
        reword_group.add(self.reword_provider_row)

        self.reword_key_row = Adw.EntryRow(title="API Key")
        self.reword_host_row = Adw.EntryRow(title="Host")
        self.reword_model_row = Adw.EntryRow(title="Model")

        reword_group.add(self.reword_key_row)
        reword_group.add(self.reword_host_row)
        reword_group.add(self.reword_model_row)

        page.add(reword_group)

        # Save Button
        save_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        save_btn_box.set_margin_top(12)
        save_btn_box.set_margin_bottom(12)
        save_btn_box.set_margin_start(18)
        save_btn_box.set_margin_end(18)

        save_api_btn = Gtk.Button(label="Save API Settings")
        save_api_btn.add_css_class("suggested-action")
        save_api_btn.set_hexpand(True)
        save_api_btn.connect("clicked", self._save_api_settings)
        save_btn_box.append(save_api_btn)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(page)
        scrolled.set_vexpand(True)

        box.append(scrolled)
        box.append(save_btn_box)

        return box

    def _build_prompts_view(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        header_bar = Adw.HeaderBar()
        title_widget = Adw.WindowTitle(title="Customize Rewording Prompts")
        header_bar.set_title_widget(title_widget)

        back_btn = Gtk.Button(icon_name="go-previous-symbolic")
        back_btn.set_tooltip_text("Back")
        back_btn.connect("clicked", lambda _: self.nav_stack.set_visible_child_name("settings"))
        header_bar.pack_start(back_btn)

        box.append(header_bar)

        top_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        top_box.set_margin_start(18)
        top_box.set_margin_end(18)

        add_prompt_btn = Gtk.Button(label="Add New Prompt")
        add_prompt_btn.add_css_class("suggested-action")
        add_prompt_btn.set_hexpand(True)
        add_prompt_btn.connect("clicked", self._on_add_prompt_clicked)
        top_box.append(add_prompt_btn)

        box.append(top_box)

        self.prompts_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.prompts_list_box.set_margin_start(18)
        self.prompts_list_box.set_margin_end(18)
        self.prompts_list_box.set_margin_bottom(18)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(self.prompts_list_box)
        scrolled.set_vexpand(True)
        box.append(scrolled)

        bottom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        bottom_box.set_margin_start(18)
        bottom_box.set_margin_end(18)
        bottom_box.set_margin_bottom(12)

        save_prompts_btn = Gtk.Button(label="Save Manual Edits")
        save_prompts_btn.add_css_class("suggested-action")
        save_prompts_btn.set_hexpand(True)
        save_prompts_btn.connect("clicked", self._save_prompts)
        bottom_box.append(save_prompts_btn)

        box.append(bottom_box)

        return box

    def _apply_settings_to_ui(self):
        # General Settings
        self.always_on_top_row.set_active(self.settings.always_on_top)
        self.launch_startup_row.set_active(self.settings.launch_at_startup)
        self.background_row.set_active(self.settings.keep_running_in_background)

        # Language dropdown selection
        if self.settings.input_language == "Bengali (bn-IN)":
            self.lang_dropdown.set_selected(1)
        elif self.settings.input_language == "Hindi":
            self.lang_dropdown.set_selected(2)
        else:
            self.lang_dropdown.set_selected(0)

        # Provider selections
        trans_idx = 1 if self.settings.transcription_provider == ApiProvider.Gemini.value else 0
        self.trans_provider_row.set_selected(trans_idx)

        reword_idx = 1 if self.settings.rewording_provider == ApiProvider.Gemini.value else 0
        self.reword_provider_row.set_selected(reword_idx)

        self._update_api_fields_display()
        self._refresh_reword_menu()
        self._refresh_prompts_ui_list()

    def _update_api_fields_display(self):
        if self.trans_provider_row.get_selected() == 1:  # Gemini
            self.trans_key_row.set_text(self.settings.gemini_api_key)
            self.trans_host_row.set_text(self.settings.gemini_host)
            self.trans_model_row.set_text(self.settings.gemini_transcription_model)
        else:  # OpenAI
            self.trans_key_row.set_text(self.settings.transcription_api_key)
            self.trans_host_row.set_text(self.settings.transcription_host)
            self.trans_model_row.set_text(self.settings.transcription_model)

        if self.reword_provider_row.get_selected() == 1:  # Gemini
            self.reword_key_row.set_text(self.settings.gemini_api_key)
            self.reword_host_row.set_text(self.settings.gemini_host)
            self.reword_model_row.set_text(self.settings.gemini_rewording_model)
        else:  # OpenAI
            self.reword_key_row.set_text(self.settings.rewording_api_key)
            self.reword_host_row.set_text(self.settings.rewording_host)
            self.reword_model_row.set_text(self.settings.rewording_model)

    def _on_trans_provider_changed(self, row, pspec):
        self._update_api_fields_display()

    def _on_reword_provider_changed(self, row, pspec):
        self._update_api_fields_display()

    def _save_api_settings(self, btn):
        if self.trans_provider_row.get_selected() == 1:  # Gemini
            self.settings.transcription_provider = ApiProvider.Gemini.value
            self.settings.gemini_api_key = self.trans_key_row.get_text()
            self.settings.gemini_host = self.trans_host_row.get_text()
            self.settings.gemini_transcription_model = self.trans_model_row.get_text()
        else:
            self.settings.transcription_provider = ApiProvider.OpenAI.value
            self.settings.transcription_api_key = self.trans_key_row.get_text()
            self.settings.transcription_host = self.trans_host_row.get_text()
            self.settings.transcription_model = self.trans_model_row.get_text()

        if self.reword_provider_row.get_selected() == 1:  # Gemini
            self.settings.rewording_provider = ApiProvider.Gemini.value
            self.settings.gemini_api_key = self.reword_key_row.get_text()
            self.settings.gemini_host = self.reword_host_row.get_text()
            self.settings.gemini_rewording_model = self.reword_model_row.get_text()
        else:
            self.settings.rewording_provider = ApiProvider.OpenAI.value
            self.settings.rewording_api_key = self.reword_key_row.get_text()
            self.settings.rewording_host = self.reword_host_row.get_text()
            self.settings.rewording_model = self.reword_model_row.get_text()

        self._settings_service.save(self.settings)
        self.show_toast("API settings saved!")

    def _refresh_reword_menu(self):
        # Clear popover children
        child = self.reword_menu_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.reword_menu_box.remove(child)
            child = next_child

        lbl = Gtk.Label(label="Apply Rewording", xalign=0)
        lbl.add_css_class("heading")
        self.reword_menu_box.append(lbl)

        grid = Gtk.FlowBox()
        grid.set_selection_mode(Gtk.SelectionMode.NONE)
        grid.set_max_children_per_line(3)

        for prompt in self.settings.rewording_prompts:
            btn = Gtk.Button(label=prompt.name)
            btn.connect("clicked", lambda b, p=prompt: self._apply_reword_prompt(p))
            grid.append(btn)

        self.reword_menu_box.append(grid)

    def _refresh_prompts_ui_list(self):
        child = self.prompts_list_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.prompts_list_box.remove(child)
            child = next_child

        for i, prompt in enumerate(self.settings.rewording_prompts):
            frame = Gtk.Frame()
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card.set_margin_top(10)
            card.set_margin_bottom(10)
            card.set_margin_start(10)
            card.set_margin_end(10)

            # Row 0: Name entry + Move up/down/delete buttons
            row0 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

            name_entry = Gtk.Entry(text=prompt.name)
            name_entry.set_hexpand(True)
            name_entry.connect("changed", lambda e, p=prompt: self._update_prompt_attr(p, "name", e.get_text()))
            row0.append(name_entry)

            if i > 0:
                up_btn = Gtk.Button(icon_name="go-up-symbolic")
                up_btn.set_tooltip_text("Move Up")
                up_btn.connect("clicked", lambda _, idx=i: self._move_prompt(idx, -1))
                row0.append(up_btn)

            if i < len(self.settings.rewording_prompts) - 1:
                down_btn = Gtk.Button(icon_name="go-down-symbolic")
                down_btn.set_tooltip_text("Move Down")
                down_btn.connect("clicked", lambda _, idx=i: self._move_prompt(idx, 1))
                row0.append(down_btn)

            del_btn = Gtk.Button(icon_name="user-trash-symbolic")
            del_btn.set_tooltip_text("Delete")
            del_btn.connect("clicked", lambda _, idx=i: self._delete_prompt(idx))
            row0.append(del_btn)

            card.append(row0)

            # Row 1: Instructions text view
            inst_entry = Gtk.Entry(text=prompt.instructions)
            inst_entry.set_placeholder_text("Rewording Instructions")
            inst_entry.connect("changed", lambda e, p=prompt: self._update_prompt_attr(p, "instructions", e.get_text()))
            card.append(inst_entry)

            # Row 2: Auto apply switch
            switch_row = Adw.SwitchRow(title="Apply Automatically")
            switch_row.set_active(prompt.apply_automatically)
            switch_row.connect("notify::active", lambda s, ps, p=prompt: self._on_auto_apply_toggled(p, s.get_active()))
            card.append(switch_row)

            frame.set_child(card)
            self.prompts_list_box.append(frame)

    def _update_prompt_attr(self, prompt: RewordingPrompt, attr: str, val):
        setattr(prompt, attr, val)

    def _on_auto_apply_toggled(self, prompt: RewordingPrompt, active: bool):
        if active and not prompt.apply_automatically:
            # Check if any other prompt is already set to auto-apply
            other = next((p for p in self.settings.rewording_prompts if p.apply_automatically and p != prompt), None)
            if other:
                self.show_toast(f'Cannot apply automatically. Currently "{other.name}" is enabled.')
                GLib.idle_add(self._refresh_prompts_ui_list)
                return
        prompt.apply_automatically = active
        self._settings_service.save(self.settings)

    def _on_add_prompt_clicked(self, btn):
        new_prompt = RewordingPrompt(
            name="New Prompt",
            instructions="Instructions here",
            order=len(self.settings.rewording_prompts),
            apply_automatically=False,
        )
        self.settings.rewording_prompts.append(new_prompt)
        self._save_prompts()
        self._refresh_prompts_ui_list()

    def _move_prompt(self, index: int, delta: int):
        target = index + delta
        if 0 <= target < len(self.settings.rewording_prompts):
            prompts = self.settings.rewording_prompts
            prompts[index], prompts[target] = prompts[target], prompts[index]
            self._save_prompts()
            self._refresh_prompts_ui_list()

    def _delete_prompt(self, index: int):
        if 0 <= index < len(self.settings.rewording_prompts):
            self.settings.rewording_prompts.pop(index)
            self._save_prompts()
            self._refresh_prompts_ui_list()

    def _save_prompts(self, btn=None):
        for i, p in enumerate(self.settings.rewording_prompts):
            p.order = i
        self._settings_service.save(self.settings)
        self._refresh_reword_menu()
        self.show_toast("Prompts saved!")

    def _on_language_changed(self, dropdown, pspec):
        selected_idx = dropdown.get_selected()
        languages = ["English", "Bengali (bn-IN)", "Hindi"]
        if 0 <= selected_idx < len(languages):
            self.settings.input_language = languages[selected_idx]
            self._settings_service.save(self.settings)

            if self.settings.input_language == "Bengali (bn-IN)":
                self.record_button.set_label("🎤 রেকর্ড")
            elif self.settings.input_language == "Hindi":
                self.record_button.set_label("🎤 रिकॉर्ड")
            else:
                self.record_button.set_label("🎤 Record")

    def _on_always_on_top_toggled(self, row, pspec):
        is_active = row.get_active()
        self.settings.always_on_top = is_active
        self._settings_service.save(self.settings)
        # Set GTK Window Keep Above
        if is_active:
            self.set_keep_above(True)
        else:
            self.set_keep_above(False)

    def _on_launch_startup_toggled(self, row, pspec):
        is_active = row.get_active()
        updated = self._startup_service.set_enabled(is_active)
        if not updated:
            self.show_toast("Could not update launch-at-startup setting.")
            row.set_active(not is_active)
            return
        self.settings.launch_at_startup = is_active
        self._settings_service.save(self.settings)

    def _on_background_toggled(self, row, pspec):
        self.settings.keep_running_in_background = row.get_active()
        self._settings_service.save(self.settings)

    def _on_audio_level_changed(self, level: float):
        GLib.idle_add(self._update_audio_level_ui, level)

    def _update_audio_level_ui(self, level: float):
        target = level * 100.0
        self._smoothed_level = (self._smoothed_level * 0.7) + (target * 0.3)
        self.level_progress.set_fraction(min(1.0, self._smoothed_level / 100.0))
        return False

    def _on_recording_duration_changed(self, duration_secs: float):
        mins = int(duration_secs // 60)
        secs = int(duration_secs % 60)
        s = f"{mins:02d}:{secs:02d}"
        GLib.idle_add(self._update_duration_ui, s)

    def _update_duration_ui(self, duration_str: str):
        self.recording_time_str = duration_str
        self.send_btn_label.set_label(f"➤ Send {duration_str}")
        return False

    def _on_record_clicked(self, btn):
        if self.recording_state == 0:  # Idle
            try:
                self._recorder.start_recording()
                self.is_paused = False
                self.recording_state = 1  # Recording
                self.record_button.set_visible(False)
                self.recording_controls_box.set_visible(True)
                if self._floating_widget:
                    self._floating_widget.set_recording_state(True)
            except Exception as e:
                self.show_toast(f"Error starting recording: {e}")

    def _on_pause_clicked(self, btn):
        if self.recording_state != 1:
            return
        self._recorder.pause_recording()
        self.is_paused = self._recorder.is_paused
        self.pause_btn.set_label("▶" if self.is_paused else "⏸")

    def _on_trash_clicked(self, btn):
        if self._recorder.is_recording:
            self._recorder.stop_recording()
        self._recorder.delete_file()

        self.is_paused = False
        self.recording_state = 0
        self.record_button.set_visible(True)
        self.recording_controls_box.set_visible(False)
        self.send_btn_label.set_label("➤ Send 00:00")
        self.level_progress.set_fraction(0.0)
        if self._floating_widget:
            self._floating_widget.set_recording_state(False)

    def _send_for_transcription(self, insert_into_app: bool = False):
        if self.recording_state != 1:
            return

        self.is_paused = False
        self._recorder.stop_recording()
        self.recording_state = 2  # Recorded

        # Execute transcription in background thread
        import threading
        t = threading.Thread(target=self._transcribe_task, args=(self._recorder.output_file_path, insert_into_app), daemon=True)
        t.start()

    def _transcribe_task(self, path: str, insert_into_app: bool):
        time.sleep(0.3)
        if not path or not os.path.exists(path):
            GLib.idle_add(self._on_transcribed_received, "\n[Error: audio file not found.]\n", insert_into_app)
            return

        try:
            lang_code = "bn" if "Bengali" in self.settings.input_language else ("hi" if "Hindi" in self.settings.input_language else "en")

            # Transcription Config
            if self.settings.transcription_provider == ApiProvider.Gemini.value:
                t_key, t_host, t_model = self.settings.gemini_api_key, self.settings.gemini_host, self.settings.gemini_transcription_model
            else:
                t_key, t_host, t_model = self.settings.transcription_api_key, self.settings.transcription_host, self.settings.transcription_model

            text = self._openai_service.transcribe_audio(path, t_key, t_host, t_model, lang_code)

            # Reword Config for Auto-apply Prompts
            if self.settings.rewording_provider == ApiProvider.Gemini.value:
                r_key, r_host, r_model = self.settings.gemini_api_key, self.settings.gemini_host, self.settings.gemini_rewording_model
            else:
                r_key, r_host, r_model = self.settings.rewording_api_key, self.settings.rewording_host, self.settings.rewording_model

            for prompt in self.settings.rewording_prompts:
                if prompt.apply_automatically:
                    try:
                        text = self._reword_service.reword(text, r_key, r_host, r_model, self.settings.input_language, prompt.instructions)
                    except Exception as ex:
                        text += f"\n[Error applying prompt '{prompt.name}': {ex}]\n"

            GLib.idle_add(self._on_transcribed_received, text, insert_into_app)
        except Exception as ex:
            GLib.idle_add(self._on_transcribed_received, f"\n[Error transcribing: {ex}]\n", False)
        finally:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

    def _on_transcribed_received(self, text: str, insert_into_app: bool):
        bounds = self.transcript_buffer.get_selection_bounds()
        if bounds:
            start_iter, end_iter = bounds
            self.transcript_buffer.delete(start_iter, end_iter)

        cursor_position = self.transcript_buffer.get_property("cursor-position")

        if cursor_position > 0:
            current_text = self.transcript_buffer.get_text(
                self.transcript_buffer.get_start_iter(),
                self.transcript_buffer.get_end_iter(),
                True,
            )
            if current_text and not current_text[-1].isspace():
                text = " " + text

        self.transcript_buffer.insert_at_cursor(text)

        self.recording_state = 0
        self.record_button.set_visible(True)
        self.recording_controls_box.set_visible(False)
        self.send_btn_label.set_label("➤ Send 00:00")
        self.level_progress.set_fraction(0.0)

        if self._floating_widget:
            self._floating_widget.set_recording_state(False)

        if insert_into_app and text.strip():
            self._insert_text_into_active_app(text)

        return False

    def _apply_reword_prompt(self, prompt: RewordingPrompt):
        self.reword_popover.popdown()

        bounds = self.transcript_buffer.get_selection_bounds()
        if bounds:
            original = self.transcript_buffer.get_text(bounds[0], bounds[1], True)
        else:
            original = self.transcript_buffer.get_text(
                self.transcript_buffer.get_start_iter(),
                self.transcript_buffer.get_end_iter(),
                True,
            )

        if not original or not original.strip():
            return

        import threading
        t = threading.Thread(target=self._reword_task, args=(original, prompt.instructions, bool(bounds)), daemon=True)
        t.start()

    def _reword_task(self, original: str, instructions: str, has_selection: bool):
        try:
            if self.settings.rewording_provider == ApiProvider.Gemini.value:
                r_key, r_host, r_model = self.settings.gemini_api_key, self.settings.gemini_host, self.settings.gemini_rewording_model
            else:
                r_key, r_host, r_model = self.settings.rewording_api_key, self.settings.rewording_host, self.settings.rewording_model

            improved = self._reword_service.reword(original, r_key, r_host, r_model, self.settings.input_language, instructions)
            GLib.idle_add(self._on_reword_received, improved, has_selection)
        except Exception as ex:
            GLib.idle_add(self.show_toast, f"Reword error: {ex}")

    def _on_reword_received(self, improved: str, has_selection: bool):
        if has_selection:
            bounds = self.transcript_buffer.get_selection_bounds()
            if bounds:
                self.transcript_buffer.delete(bounds[0], bounds[1])
                self.transcript_buffer.insert_at_cursor(improved)
        else:
            self.transcript_buffer.set_text(improved)
        return False

    def _on_transcript_text_changed(self, buffer):
        if self._is_updating_from_undo:
            return

        current_text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)

        if self._debounce_timer_id is not None:
            GLib.source_remove(self._debounce_timer_id)
            self._debounce_timer_id = None

        self._debounce_timer_id = GLib.timeout_add(400, self._push_undo_stack, current_text)

    def _push_undo_stack(self, text: str):
        self._debounce_timer_id = None
        if self._undo_stack and self._undo_stack[self._undo_index] == text:
            return False

        if self._undo_index < len(self._undo_stack) - 1:
            self._undo_stack = self._undo_stack[: self._undo_index + 1]

        self._undo_stack.append(text)
        if len(self._undo_stack) > 101:
            self._undo_stack.pop(0)
        else:
            self._undo_index += 1

        self.undo_btn.set_sensitive(self._undo_index > 0)
        self.redo_btn.set_sensitive(self._undo_index < len(self._undo_stack) - 1)
        return False

    def _on_undo_clicked(self, btn):
        if self._undo_index > 0:
            self._is_updating_from_undo = True
            self._undo_index -= 1
            text = self._undo_stack[self._undo_index]
            self.transcript_buffer.set_text(text)
            self._is_updating_from_undo = False

            self.undo_btn.set_sensitive(self._undo_index > 0)
            self.redo_btn.set_sensitive(self._undo_index < len(self._undo_stack) - 1)

    def _on_redo_clicked(self, btn):
        if self._undo_index < len(self._undo_stack) - 1:
            self._is_updating_from_undo = True
            self._undo_index += 1
            text = self._undo_stack[self._undo_index]
            self.transcript_buffer.set_text(text)
            self._is_updating_from_undo = False

            self.undo_btn.set_sensitive(self._undo_index > 0)
            self.redo_btn.set_sensitive(self._undo_index < len(self._undo_stack) - 1)

    def _on_copy_clicked(self, btn):
        bounds = self.transcript_buffer.get_selection_bounds()
        if bounds:
            text = self.transcript_buffer.get_text(bounds[0], bounds[1], True)
        else:
            text = self.transcript_buffer.get_text(self.transcript_buffer.get_start_iter(), self.transcript_buffer.get_end_iter(), True)

        if text:
            Gdk.Display.get_default().get_clipboard().set(text)
            self.show_toast("Copied to clipboard!")

    def _on_select_all_clicked(self, btn):
        start = self.transcript_buffer.get_start_iter()
        end = self.transcript_buffer.get_end_iter()
        self.transcript_buffer.select_range(start, end)
        self.transcript_view.grab_focus()

    def _on_clear_all_clicked(self, btn):
        self.transcript_buffer.set_text("")

    def _on_insert_clicked(self, btn):
        bounds = self.transcript_buffer.get_selection_bounds()
        if bounds:
            text = self.transcript_buffer.get_text(bounds[0], bounds[1], True)
        else:
            text = self.transcript_buffer.get_text(self.transcript_buffer.get_start_iter(), self.transcript_buffer.get_end_iter(), True)

        if text and text.strip():
            self._insert_text_into_active_app(text)

    def _insert_text_into_active_app(self, text: str):
        # 1. Copy to clipboard
        Gdk.Display.get_default().get_clipboard().set(text)

        # 2. Minimize window
        self.minimize()

        # 3. Paste via wl-copy or xdotool/ydotool/wtype if present
        def perform_paste():
            try:
                subprocess.run(["wl-copy", text], check=False)
            except Exception:
                pass

            wtype = shutil.which("wtype")
            xdotool = shutil.which("xdotool")
            ydotool = shutil.which("ydotool")
            if wtype:
                subprocess.run([wtype, "-M", "ctrl", "-k", "v", "-m", "ctrl"], check=False)
            elif xdotool:
                subprocess.run([xdotool, "key", "ctrl+v"], check=False)
            elif ydotool:
                subprocess.run([ydotool, "key", "29:1", "47:1", "47:0", "29:0"], check=False)
            return False

        GLib.timeout_add(400, perform_paste)

    def execute_recording_toggle(self):
        if self.recording_state == 1:
            self._send_for_transcription(insert_into_app=True)
        else:
            self._on_record_clicked(None)

    def _setup_shortcuts(self):
        # Setup shortcut <Ctrl><Shift>D for toggle recording
        trigger = Gtk.ShortcutTrigger.parse_string("<Ctrl><Shift>d")
        action = Gtk.CallbackAction.new(lambda *args: (self.execute_recording_toggle(), True)[1])
        shortcut = Gtk.Shortcut.new(trigger, action)

        controller = Gtk.ShortcutController.new()
        controller.add_shortcut(shortcut)
        self.add_controller(controller)

    def show_toast(self, message: str):
        toast = Adw.Toast.new(message)
        if hasattr(self, "toast_overlay"):
            self.toast_overlay.add_toast(toast)
        print(f"[AIDictation] {message}")

    def _on_close_requested(self, window):
        if self.settings.keep_running_in_background:
            self.hide()
            if not self._floating_widget:
                self._floating_widget = FloatingRecorderWidget(self.execute_recording_toggle)
            self._floating_widget.show()
            return True
        return False
