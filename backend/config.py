"""Проверяемая конфигурация из config.yaml."""

from functools import lru_cache
from pathlib import Path
import re

from pydantic import BaseModel, Field, field_validator
import yaml

from backend.models import DimensionType

ROOT = Path(__file__).resolve().parent.parent


class DimensionRule(BaseModel):
    pattern: str
    type: DimensionType

    @field_validator("pattern")
    @classmethod
    def valid_regex(cls, pattern: str) -> str:
        re.compile(pattern)
        return pattern


class Settings(BaseModel):
    dimension_types: list[DimensionRule] = Field(min_length=1)
    tolerance_mm: float = Field(gt=0)
    max_text_length: int = Field(gt=0)
    max_dimensions: int = Field(gt=0)
    max_file_size_mb: int = Field(gt=0)
    timeout_sec: int = Field(gt=0)
    max_concurrent_requests: int = Field(gt=0)
    report_max_chars: int = Field(gt=0, le=4000)

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    with (ROOT / "config.yaml").open(encoding="utf-8") as stream:
        return Settings.model_validate(yaml.safe_load(stream))
