import os
import sys

AUTOSTART_DIR = os.path.expanduser("~/.config/autostart")
DESKTOP_FILE = os.path.join(AUTOSTART_DIR, "com.github.abhik247.AIDictation.desktop")

DESKTOP_ENTRY_TEMPLATE = """[Desktop Entry]
Type=Application
Name=AI Dictation
Comment=Voice transcription powered by AI
Exec={exec_path}
Icon=com.github.abhik247.AIDictation
Terminal=false
Categories=Utility;Audio;
X-GNOME-Autostart-enabled=true
"""


class StartupRegistrationService:
    def is_enabled(self) -> bool:
        return os.path.exists(DESKTOP_FILE)

    def set_enabled(self, enabled: bool) -> bool:
        try:
            if enabled:
                os.makedirs(AUTOSTART_DIR, exist_ok=True)
                exec_path = sys.executable + " -m aidictation.main" if getattr(sys, 'frozen', False) else "aidictation"
                content = DESKTOP_ENTRY_TEMPLATE.format(exec_path=exec_path)
                with open(DESKTOP_FILE, "w", encoding="utf-8") as f:
                    f.write(content)
            else:
                if os.path.exists(DESKTOP_FILE):
                    os.remove(DESKTOP_FILE)
            return True
        except Exception:
            return False
