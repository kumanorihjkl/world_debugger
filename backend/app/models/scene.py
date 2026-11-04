"""Scene graph models — intermediate representation between SAM and the engine."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    x_min: float = Field(ge=0.0, le=1.0)
    y_min: float = Field(ge=0.0, le=1.0)
    x_max: float = Field(ge=0.0, le=1.0)
    y_max: float = Field(ge=0.0, le=1.0)


class SceneObject(BaseModel):
    id: str
    concept: str
    selector_id: str = ""
    bbox: BoundingBox
    confidence: float = 1.0
    centroid: tuple[float, float] = (0.0, 0.0)
    polygon: list[tuple[float, float]] | None = Field(
        default=None, description="Normalized mask contour points, if decoded"
    )


class Relationship(BaseModel):
    subject_id: str
    predicate: str
    object_id: str = ""
    distance_normalized: Optional[float] = None


class Zone(BaseModel):
    id: str
    name: str
    # Normalized polygon points [(x, y)], 0..1. Rectangles are 4-point polygons.
    polygon: list[tuple[float, float]] = Field(default_factory=list)


class SceneGraph(BaseModel):
    objects: list[SceneObject] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)


class Violation(BaseModel):
    rule_id: str
    rule_name: str
    severity: str
    message: str
    object_ids: list[str] = Field(default_factory=list)
    timestamp: float = 0.0
