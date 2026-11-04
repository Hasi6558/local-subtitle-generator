import tomllib
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from local_subs.policy import FormattingPolicy


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
    device: Literal["auto", "cpu", "cuda"] = "cpu"
    compute_type: str | None = None
    vad: bool = True
    beam_size: int = Field(default=5, ge=1, le=20)
    detection_threshold: float = Field(default=0.7, gt=0, le=1)
    detection_attempts: int = Field(default=3, ge=1, le=10)
    chunk_seconds: int = Field(default=300, ge=5, le=900)
    overlap_seconds: int = Field(default=5, ge=0, le=30)
    formatting: FormattingPolicy = Field(default_factory=FormattingPolicy)

    @model_validator(mode="after")
    def model_language(self):
        if self.overlap_seconds * 2 >= self.chunk_seconds:
            raise ValueError("Overlap must be less than half the chunk duration")
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
