"""HTTP API schemas (request/response boundaries)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.models.dsl import VisualRule
from app.models.scene import SceneGraph, Violation, Zone


class CompileRequest(BaseModel):
    text: str = Field(min_length=1)


class CompileResponse(BaseModel):
    rule: VisualRule
    mocked: bool


class RuleListResponse(BaseModel):
    rules: list[VisualRule]


class AnalyzeRequest(BaseModel):
    image_base64: str = ""
    image_variant: str = "default"
    rule_ids: Optional[list[str]] = None
    zones: list[Zone] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    scene: SceneGraph
    violations: list[Violation]
    mocked: bool
    rule_ids: list[str] = Field(default_factory=list)
