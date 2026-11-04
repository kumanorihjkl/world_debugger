"""Build a scene graph from segmentation detections (no LLM involved)."""

from __future__ import annotations

from app.models.scene import (
    BoundingBox,
    Relationship,
    SceneGraph,
    SceneObject,
    Zone,
)
from app.services import geometry as geo


def build_scene_graph(
    detections: list[dict],
    zones: list[Zone] | None = None,
) -> SceneGraph:
    """Convert raw detections into objects + pairwise relationships.

    Each detection: {"concept": str, "selector_id": str, "bbox": [x_min,y_min,x_max,y_max],
    "confidence": float}.
    """
    zones = zones or []
    objects: list[SceneObject] = []
    for i, det in enumerate(detections):
        x0, y0, x1, y1 = det["bbox"]
        bbox = BoundingBox(
            x_min=min(x0, x1),
            y_min=min(y0, y1),
            x_max=max(x0, x1),
            y_max=max(y0, y1),
        )
        raw_polygon = det.get("polygon")
        polygon = (
            [(float(x), float(y)) for x, y in raw_polygon]
            if isinstance(raw_polygon, list) and raw_polygon
            else None
        )
        objects.append(
            SceneObject(
                id=f"{det.get('concept', 'obj')}_{i + 1}",
                concept=str(det.get("concept", "object")),
                selector_id=str(det.get("selector_id", "")),
                bbox=bbox,
                confidence=float(det.get("confidence", 1.0)),
                centroid=geo.centroid(bbox),
                polygon=polygon,
            )
        )

    relationships: list[Relationship] = []
    for a in objects:
        for b in objects:
            if a.id == b.id:
                continue
            dist = geo.normalized_distance(a.bbox, b.bbox)
            relationships.append(
                Relationship(
                    subject_id=a.id,
                    predicate="near" if dist < 0.15 else "far",
                    object_id=b.id,
                    distance_normalized=dist,
                )
            )
            if geo.overlaps(a.bbox, b.bbox):
                relationships.append(
                    Relationship(
                        subject_id=a.id,
                        predicate="overlap",
                        object_id=b.id,
                        distance_normalized=0.0,
                    )
                )
        for zone in zones:
            if geo.bbox_inside_zone(a.bbox, zone.polygon):
                relationships.append(
                    Relationship(
                        subject_id=a.id,
                        predicate="inside_zone",
                        object_id=zone.id,
                    )
                )
    return SceneGraph(objects=objects, relationships=relationships)
