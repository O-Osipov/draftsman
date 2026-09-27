"""Сущности и контракты API по техническому заданию."""

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionState(str, Enum):
    IDLE = "IDLE"
    AWAITING_DIMENSIONS = "AWAITING_DIMENSIONS"
    AWAITING_FILE = "AWAITING_FILE"
    PROCESSING = "PROCESSING"


class DimensionType(str, Enum):
    LINEAR = "LINEAR"
    DIAMETER = "DIAMETER"
    DEPTH = "DEPTH"
    CHAMFER = "CHAMFER"


class Dimension(BaseModel):
    name: str = Field(min_length=1)
    value: float = Field(gt=0, allow_inf_nan=False)
    unit: Literal["мм"] = "мм"
    type: DimensionType
    tolerance: float = Field(default=0.5, gt=0, allow_inf_nan=False)


class Session(BaseModel):
    user_id: int
    state: SessionState = SessionState.IDLE
    dimensions: list[Dimension] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class Model(BaseModel):
    file_id: str
    format: Literal["STL"] = "STL"
    size_bytes: int = Field(ge=0)
    uploaded_at: datetime = Field(default_factory=utc_now)


class Match(BaseModel):
    dimension_name: str = Field(validation_alias=AliasChoices("name", "dimension_name"), serialization_alias="name")
    expected: float
    actual: float
    delta: float


class Mismatch(BaseModel):
    dimension_name: str = Field(validation_alias=AliasChoices("name", "dimension_name"), serialization_alias="name")
    expected: float
    actual: float | None
    delta: float | None


class Report(BaseModel):
    session_id: int
    matches: list[Match] = Field(default_factory=list)
    mismatches: list[Mismatch] = Field(default_factory=list)
    summary: str
    telegram_text: str = ""
    generated_at: datetime = Field(default_factory=utc_now)


class ParseRequest(BaseModel):
    user_id: int
    raw_text: str


class ParseResponse(BaseModel):
    status: Literal["ok"] = "ok"
    dimensions: list[Dimension]
    checklist: list[str]


class AnalyzeResponse(BaseModel):
    status: Literal["ok"] = "ok"
    report: Report


class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    code: str
    message: str


class AxisBounds(BaseModel):
    x: float = Field(gt=0, allow_inf_nan=False)
    y: float = Field(gt=0, allow_inf_nan=False)
    z: float = Field(gt=0, allow_inf_nan=False)


class Hole(BaseModel):
    axis: Literal["x", "y", "z"]
    center: tuple[float, float]
    diameter: float = Field(gt=0, allow_inf_nan=False)
    depth: float = Field(gt=0, allow_inf_nan=False)


class Chamfer(BaseModel):
    axis: Literal["x", "y", "z"]
    position: float = Field(allow_inf_nan=False)
    size: float = Field(gt=0, allow_inf_nan=False)
