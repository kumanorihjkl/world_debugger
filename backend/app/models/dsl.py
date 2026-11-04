"""Visual Rule DSL — Pydantic models with closed enums.

Muse Spark must only emit operators from the closed Operator enum so it
cannot invent unknown operators.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Operator(str, Enum):
    NEAR = "near"
    FAR_FROM = "far_from"
    OVERLAPS = "overlaps"
    INSIDE_ZONE = "inside_zone"
    OUTSIDE_ZONE = "outside_zone"
    PRESENT_FOR = "present_for"
    ABSENT_FOR = "absent_for"
    NOT_NEAR_FOR = "not_near_for"


TEMPORAL_OPERATORS = frozenset(
    {Operator.PRESENT_FOR, Operator.ABSENT_FOR, Operator.NOT_NEAR_FOR}
)

SPATIAL_OPERATORS = frozenset(
    {
        Operator.NEAR,
        Operator.FAR_FROM,
        Operator.OVERLAPS,
        Operator.INSIDE_ZONE,
        Operator.OUTSIDE_ZONE,
    }
)


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Selector(BaseModel):
    id: str = Field(description="Selector id referenced by Condition.subject/object")
    concept: str = Field(description="Human concept, e.g. 'drink'")
    sam_prompt: str = Field(
        description="Short single-object noun phrase for SAM, e.g. 'cup'. "
        "Never a compound prompt like 'cup or bottle'."
    )


class Condition(BaseModel):
    operator: Operator
    subject: str = Field(description="Selector id of the subject")
    object: Optional[str] = Field(
        default=None, description="Selector id of the object (for binary operators)"
    )
    threshold: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Image-space normalized distance threshold",
    )
    zone_id: Optional[str] = Field(default=None)
    duration_seconds: Optional[float] = Field(default=None, ge=0.0)
    requires_metric_depth: bool = Field(
        default=False,
        description="True when the user asked for real-world units we cannot measure",
    )


class VisualRule(BaseModel):
    id: str
    name: str
    original_text: str
    description: str = ""
    severity: Severity = Severity.WARNING
    selectors: list[Selector] = Field(default_factory=list)
    condition: Condition
    explanation: str = ""
