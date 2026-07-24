from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


class ApiProvider(str, Enum):
    OpenAI = "OpenAI"
    Gemini = "Gemini"


@dataclass
class RewordingPrompt:
    name: str = ""
    instructions: str = ""
    apply_automatically: bool = False
    order: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "instructions": self.instructions,
            "apply_automatically": self.apply_automatically,
            "order": self.order,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RewordingPrompt":
        return cls(
            name=data.get("name") or data.get("Name") or "",
            instructions=data.get("instructions") or data.get("Instructions") or "",
            apply_automatically=bool(data.get("apply_automatically") if "apply_automatically" in data else data.get("ApplyAutomatically", False)),
            order=int(data.get("order") if "order" in data else data.get("Order", 0)),
        )


@dataclass
class AppSettings:
    selected_provider: str = ApiProvider.OpenAI.value
    transcription_provider: str = ApiProvider.OpenAI.value
    rewording_provider: str = ApiProvider.OpenAI.value

    # OpenAI Settings
    transcription_api_key: str = ""
    transcription_host: str = "https://api.openai.com/v1"
    transcription_model: str = "whisper-1"

    rewording_api_key: str = ""
    rewording_host: str = "https://api.openai.com/v1"
    rewording_model: str = "gpt-4o-mini"

    # Gemini Settings
    gemini_api_key: str = ""
    gemini_host: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_transcription_model: str = "gemini-1.5-flash"
    gemini_rewording_model: str = "gemini-1.5-flash"

    # General Settings
    input_language: str = "English"
    always_on_top: bool = False
    launch_at_startup: bool = False
    keep_running_in_background: bool = False

    rewording_prompts: List[RewordingPrompt] = field(default_factory=list)

    # Legacy field for compatibility migration
    openai_api_key: str = ""

    def to_dict(self) -> dict:
        return {
            "SelectedProvider": self.selected_provider,
            "TranscriptionProvider": self.transcription_provider,
            "RewordingProvider": self.rewording_provider,
            "TranscriptionApiKey": self.transcription_api_key,
            "TranscriptionHost": self.transcription_host,
            "TranscriptionModel": self.transcription_model,
            "RewordingApiKey": self.rewording_api_key,
            "RewordingHost": self.rewording_host,
            "RewordingModel": self.rewording_model,
            "GeminiApiKey": self.gemini_api_key,
            "GeminiHost": self.gemini_host,
            "GeminiTranscriptionModel": self.gemini_transcription_model,
            "GeminiRewordingModel": self.gemini_rewording_model,
            "InputLanguage": self.input_language,
            "AlwaysOnTop": self.always_on_top,
            "LaunchAtStartup": self.launch_at_startup,
            "KeepRunningInBackground": self.keep_running_in_background,
            "RewordingPrompts": [p.to_dict() for p in self.rewording_prompts],
            "OpenAIApiKey": self.openai_api_key,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        prompts_raw = data.get("RewordingPrompts") or data.get("rewording_prompts") or []
        prompts = [RewordingPrompt.from_dict(p) for p in prompts_raw]

        return cls(
            selected_provider=data.get("SelectedProvider") or data.get("selected_provider") or ApiProvider.OpenAI.value,
            transcription_provider=data.get("TranscriptionProvider") or data.get("transcription_provider") or ApiProvider.OpenAI.value,
            rewording_provider=data.get("RewordingProvider") or data.get("rewording_provider") or ApiProvider.OpenAI.value,
            transcription_api_key=data.get("TranscriptionApiKey") or data.get("transcription_api_key") or "",
            transcription_host=data.get("TranscriptionHost") or data.get("transcription_host") or "https://api.openai.com/v1",
            transcription_model=data.get("TranscriptionModel") or data.get("transcription_model") or "whisper-1",
            rewording_api_key=data.get("RewordingApiKey") or data.get("rewording_api_key") or "",
            rewording_host=data.get("RewordingHost") or data.get("rewording_host") or "https://api.openai.com/v1",
            rewording_model=data.get("RewordingModel") or data.get("rewording_model") or "gpt-4o-mini",
            gemini_api_key=data.get("GeminiApiKey") or data.get("gemini_api_key") or "",
            gemini_host=data.get("GeminiHost") or data.get("gemini_host") or "https://generativelanguage.googleapis.com/v1beta/openai/",
            gemini_transcription_model=data.get("GeminiTranscriptionModel") or data.get("gemini_transcription_model") or "gemini-1.5-flash",
            gemini_rewording_model=data.get("GeminiRewordingModel") or data.get("gemini_rewording_model") or "gemini-1.5-flash",
            input_language=data.get("InputLanguage") or data.get("input_language") or "English",
            always_on_top=bool(data.get("AlwaysOnTop") if "AlwaysOnTop" in data else data.get("always_on_top", False)),
            launch_at_startup=bool(data.get("LaunchAtStartup") if "LaunchAtStartup" in data else data.get("launch_at_startup", False)),
            keep_running_in_background=bool(data.get("KeepRunningInBackground") if "KeepRunningInBackground" in data else data.get("keep_running_in_background", False)),
            rewording_prompts=prompts,
            openai_api_key=data.get("OpenAIApiKey") or data.get("openai_api_key") or "",
        )
