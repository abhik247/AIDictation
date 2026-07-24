import os
import json
import threading
from typing import List
from ..models import AppSettings, RewordingPrompt


class SettingsService:
    def __init__(self):
        config_dir = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        self._folder = os.path.join(config_dir, "AIDictationApp")
        try:
            os.makedirs(self._folder, exist_ok=True)
        except OSError:
            # Fallback for read-only environments / sandboxes
            self._folder = os.path.join(os.getcwd(), ".config", "AIDictationApp")
            os.makedirs(self._folder, exist_ok=True)

        self._settings_path = os.path.join(self._folder, "settings.json")
        self._lock = threading.Lock()

    def get_default_prompts(self) -> List[RewordingPrompt]:
        return [
            RewordingPrompt(name="Rephrase", instructions="Rephrase this text cleanly.", order=0),
            RewordingPrompt(name="Shorten", instructions="Make this text shorter and more concise.", order=1),
            RewordingPrompt(name="Friendly", instructions="Rewrite this text in a friendly tone.", order=2),
            RewordingPrompt(name="Formal", instructions="Rewrite this text in a formal tone.", order=3),
            RewordingPrompt(name="Engaging", instructions="Make this text more engaging and captivating.", order=4),
            RewordingPrompt(name="Casual", instructions="Rewrite this text in a casual tone.", order=5),
            RewordingPrompt(name="Professional", instructions="Make this text professional and business-appropriate.", order=6),
            RewordingPrompt(name="Diplomatic", instructions="Rewrite this text to be polite and diplomatic.", order=7),
            RewordingPrompt(name="Exciting", instructions="Rewrite this text to be energetic and exciting.", order=8),
            RewordingPrompt(name="Detailed", instructions="Expand on this text and add illustrative details.", order=9),
        ]

    def load(self) -> AppSettings:
        if not os.path.exists(self._settings_path):
            settings = AppSettings()
            settings.rewording_prompts = self.get_default_prompts()
            return settings

        has_transcription_provider = False
        has_rewording_provider = False

        try:
            with open(self._settings_path, "r", encoding="utf-8") as f:
                raw_json = f.read()
                data = json.loads(raw_json)
                has_transcription_provider = "TranscriptionProvider" in data or "transcription_provider" in data
                has_rewording_provider = "RewordingProvider" in data or "rewording_provider" in data
                settings = AppSettings.from_dict(data)
        except Exception:
            settings = AppSettings()

        if not settings.rewording_prompts:
            settings.rewording_prompts = self.get_default_prompts()

        # Migrate old single OpenAI key if present
        if not settings.transcription_api_key and settings.openai_api_key:
            settings.transcription_api_key = settings.openai_api_key
            settings.rewording_api_key = settings.openai_api_key

        if not has_transcription_provider:
            settings.transcription_provider = settings.selected_provider

        if not has_rewording_provider:
            settings.rewording_provider = settings.selected_provider

        # Enforce valid Gemini defaults
        if not settings.gemini_transcription_model or settings.gemini_transcription_model.lower() == "gemini-3.1-pro-preview":
            settings.gemini_transcription_model = "gemini-1.5-flash"

        if not settings.gemini_rewording_model or settings.gemini_rewording_model.lower() == "gemini-3.1-pro-preview":
            settings.gemini_rewording_model = "gemini-1.5-flash"

        return settings

    def save(self, settings: AppSettings) -> None:
        with self._lock:
            try:
                data = settings.to_dict()
                tmp_path = self._settings_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, self._settings_path)
            except Exception:
                pass
