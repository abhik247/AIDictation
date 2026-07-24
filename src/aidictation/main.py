import sys
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Gio, Adw

from .ui.main_window import MainWindow


class AIDictationApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="com.github.abhik247.AIDictation",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.win = None

    def do_activate(self):
        if not self.win:
            self.win = MainWindow(self)
        self.win.present()


def main(argv=None):
    if argv is None:
        argv = sys.argv

    app = AIDictationApplication()
    return app.run(argv)


if __name__ == "__main__":
    sys.exit(main())
