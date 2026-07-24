import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Gdk, GLib, Adw


class FloatingRecorderWidget(Gtk.Window):
    def __init__(self, toggle_callback):
        super().__init__(title="AI Dictation Floating Recorder")
        self.toggle_callback = toggle_callback

        self.set_default_size(56, 56)
        self.set_resizable(False)
        self.set_decorated(False)

        # Style provider
        self.css_provider = Gtk.CssProvider()
        self._update_css(is_recording=False)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            self.css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        # Content Button
        self.button = Gtk.Button()
        self.button.set_size_request(56, 56)
        self.button.set_cursor(Gdk.Cursor.new_from_name("pointer", None))
        self.button.set_label("🎤")
        self.button.add_css_class("floating-button")

        self.button.connect("clicked", self._on_clicked)
        self.set_child(self.button)

        # Drag motion tracking
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._win_start_x = 0
        self._win_start_y = 0
        self._is_dragging = False
        self._suppress_click = False

        drag_gesture = Gtk.GestureClick.new()
        drag_gesture.set_button(Gdk.BUTTON_PRIMARY)
        drag_gesture.connect("pressed", self._on_drag_pressed)
        drag_gesture.connect("released", self._on_drag_released)
        self.button.add_controller(drag_gesture)

        motion_controller = Gtk.EventControllerMotion.new()
        motion_controller.connect("motion", self._on_drag_motion)
        self.button.add_controller(motion_controller)

    def set_recording_state(self, is_recording: bool):
        GLib.idle_add(self._update_ui_state, is_recording)

    def _update_ui_state(self, is_recording: bool):
        self.button.set_label("⏹" if is_recording else "🎤")
        self._update_css(is_recording)
        return False

    def _update_css(self, is_recording: bool):
        bg_color = "#b71c1c" if is_recording else "#212121"
        css = f"""
        window {{
            background: transparent;
        }}
        .floating-button {{
            background-color: {bg_color};
            color: white;
            font-size: 24px;
            border-radius: 28px;
            border: 2px solid rgba(255, 255, 255, 0.2);
            box-shadow: 0 4px 12px rgba(0,0,0,0.4);
        }}
        .floating-button:hover {{
            background-color: {"#d32f2f" if is_recording else "#333333"};
        }}
        """
        self.css_provider.load_from_data(css.encode("utf-8"))

    def _on_drag_pressed(self, gesture, n_press, x, y):
        self._is_dragging = True
        self._suppress_click = False
        self._drag_start_x = x
        self._drag_start_y = y

    def _on_drag_motion(self, controller, x, y):
        if not self._is_dragging:
            return
        dx = x - self._drag_start_x
        dy = y - self._drag_start_y
        if abs(dx) > 4 or abs(dy) > 4:
            self._suppress_click = True

    def _on_drag_released(self, gesture, n_press, x, y):
        self._is_dragging = False

    def _on_clicked(self, button):
        if self._suppress_click:
            self._suppress_click = False
            return
        if self.toggle_callback:
            self.toggle_callback()
