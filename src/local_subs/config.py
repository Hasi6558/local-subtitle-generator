import tomllib
from pathlib import Path
from pydantic import BaseModel, ConfigDict, field_validator, model_validator


def languages():
    from babel import Locale
    from faster_whisper.tokenizer import _LANGUAGE_CODES

    names = Locale("en").languages
    return {
        code: names.get("jv" if code == "jw" else code, code)
        for code in _LANGUAGE_CODES
    }


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_language: str = "auto"
    target_language: str = "en"
    speech_model: str = "medium"
    model_cache: Path = Path.home() / ".cache" / "local-subs" / "models"
    output_dir: Path = Path("outputs")

    @model_validator(mode="after")
    def model_language(self):
        if self.source_language == "yue" and self.speech_model != "large-v3":
            raise ValueError("Cantonese (yue) requires large-v3")
        return self

    @field_validator("source_language")
    @classmethod
    def source(cls, value):
        value = value.strip().lower()
        if value != "auto" and value not in languages():
            raise ValueError("Unsupported source language; run local-subs languages")
        return value

    @field_validator("target_language")
    @classmethod
    def target(cls, value):
        if value != "en":
            raise ValueError("Only English output (target_language=en) is supported")
        return value

    @field_validator("speech_model")
    @classmethod
    def model(cls, value):
        if value not in {
            "tiny",
            "base",
            "small",
            "medium",
            "large-v1",
            "large-v2",
            "large-v3",
        }:
            raise ValueError(
                "Choose a multilingual tiny/base/small/medium/large-v1/v2/v3 model; English-only and turbo models cannot translate"
            )
        return value


def load_settings(config=None, **overrides):
    data = tomllib.loads(config.read_text(encoding="utf-8")) if config else {}
    data.update({k: v for k, v in overrides.items() if v is not None})
    return Settings.model_validate(data)
