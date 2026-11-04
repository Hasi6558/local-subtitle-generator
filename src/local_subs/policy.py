"""Project review defaults, not guarantees of subtitle quality."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FormattingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_width: int = Field(default=42, ge=10, le=120)
    max_lines: int = Field(default=2, ge=1, le=10)
    min_duration_ms: int = Field(default=1000, ge=1)
    max_duration_ms: int = Field(default=7000, ge=1)
    max_cps: float = Field(default=17, gt=0, le=100)

    @model_validator(mode="after")
    def duration_order(self):
        if self.min_duration_ms > self.max_duration_ms:
            raise ValueError("Minimum cue duration cannot exceed maximum")
        return self
