"""Deterministic rule engine over the scene graph + lightweight tracker.

No LLM calls here. Temporal operators (`present_for`, `absent_for`,
`not_near_for`) use a small IoU/nearest-neighbor tracker keyed by concept so
P3 cannot destabilize the P0/P1 spatial path.
"""

from __future__ import annotations

import time

from app.models.dsl import Operator, VisualRule
from app.models.scene import SceneGraph, SceneObject, Violation, Zone
from app.services import geometry as geo

DEFAULT_FAR_FROM_THRESHOLD = 0.15
DEFAULT_NEAR_THRESHOLD = 0.15
ZONE_OVERLAP_THRESHOLD = 0.15


def _objects_for_selector(
    scene: SceneGraph, selector_id: str, concept_by_selector: dict[str, str]
) -> list[SceneObject]:
    concept = (concept_by_selector.get(selector_id) or selector_id).lower()
    out = []
    for obj in scene.objects:
        if obj.selector_id == selector_id:
            out.append(obj)
        elif concept and (concept in obj.concept.lower() or obj.concept.lower() in concept):
            out.append(obj)
    return out


class Tracker:
    """Nearest-neighbor tracker across snapshots, keyed by concept."""

    def __init__(self) -> None:
        # track_id -> {"concept": str, "bbox": BoundingBox, "last_seen": float,
        #              "first_seen": float, "last_pos": tuple}
        self.tracks: dict[str, dict] = {}
        self._next_id = 1

    def update(self, objects: list[SceneObject], now: float | None = None) -> dict[str, str]:
        """Match objects to tracks. Returns {object_id: track_id}."""
        now = time.time() if now is None else now
        mapping: dict[str, str] = {}
        used: set[str] = set()
        for obj in sorted(objects, key=lambda o: o.id):
            best_id, best_iou = None, 0.25
            for tid, track in self.tracks.items():
                if tid in used or track["concept"] != obj.concept:
                    continue
                score = geo.iou(track["bbox"], obj.bbox)
                if score < 0.05:
                    ax, ay = track["last_pos"]
                    bx, by = geo.centroid(obj.bbox)
                    dist = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
                    score = max(0.0, 0.2 - dist)
                if score > best_iou:
                    best_id, best_iou = tid, score
            if best_id is None:
                best_id = f"track-{self._next_id}"
                self._next_id += 1
                self.tracks[best_id] = {
                    "concept": obj.concept,
                    "bbox": obj.bbox,
                    "last_seen": now,
                    "first_seen": now,
                    "last_pos": geo.centroid(obj.bbox),
                }
            else:
                track = self.tracks[best_id]
                track["bbox"] = obj.bbox
                track["last_seen"] = now
                track["last_pos"] = geo.centroid(obj.bbox)
            used.add(best_id)
            mapping[obj.id] = best_id
        return mapping

    def present_duration(self, track_id: str, now: float) -> float:
        track = self.tracks.get(track_id)
        if not track:
            return 0.0
        return max(0.0, now - track["first_seen"])

    def prune(self, now: float, max_age_s: float = 60.0) -> None:
        stale = [tid for tid, t in self.tracks.items() if now - t["last_seen"] > max_age_s]
        for tid in stale:
            del self.tracks[tid]


_tracker = Tracker()


def get_tracker() -> Tracker:
    return _tracker


def reset_tracker() -> None:
    _tracker.tracks.clear()
    _tracker._next_id = 1


def _min_pair_distance(
    subjects: list[SceneObject], objects: list[SceneObject]
) -> tuple[float, SceneObject | None, SceneObject | None]:
    best = float("inf")
    pair: tuple[SceneObject | None, SceneObject | None] = (None, None)
    for s in subjects:
        for o in objects:
            if s.id == o.id:
                continue
            d = geo.normalized_distance(s.bbox, o.bbox)
            if d < best:
                best, pair = d, (s, o)
    return best, pair[0], pair[1]


def evaluate_rule(
    rule: VisualRule,
    scene: SceneGraph,
    zones: list[Zone] | None = None,
    now: float | None = None,
    tracker: Tracker | None = None,
) -> Violation | None:
    """Evaluate one rule. Returns a Violation or None (no violation)."""
    zones = zones or []
    now = time.time() if now is None else now
    tracker = tracker or _tracker
    cond = rule.condition
    concepts = {s.id: s.concept for s in rule.selectors}
    subjects = _objects_for_selector(scene, cond.subject, concepts)

    if cond.requires_metric_depth:
        return Violation(
            rule_id=rule.id,
            rule_name=rule.name,
            severity=rule.severity.value,
            message="This rule needs metric depth, which this MVP cannot measure.",
            object_ids=[o.id for o in subjects],
            timestamp=now,
        )

    if cond.operator == Operator.FAR_FROM:
        objects = _objects_for_selector(scene, cond.object or "", concepts)
        if not subjects or not objects:
            return None
        threshold = cond.threshold or DEFAULT_FAR_FROM_THRESHOLD
        dist, s, o = _min_pair_distance(subjects, objects)
        if dist < threshold and s is not None and o is not None:
            return Violation(
                rule_id=rule.id,
                rule_name=rule.name,
                severity=rule.severity.value,
                message=f"A {s.concept} is too close to a {o.concept}.",
                object_ids=[s.id, o.id],
                timestamp=now,
            )
        return None

    if cond.operator == Operator.NEAR:
        objects = _objects_for_selector(scene, cond.object or "", concepts)
        if not subjects or not objects:
            return None
        threshold = cond.threshold or DEFAULT_NEAR_THRESHOLD
        dist, s, o = _min_pair_distance(subjects, objects)
        if dist < threshold and s is not None and o is not None:
            return Violation(
                rule_id=rule.id,
                rule_name=rule.name,
                severity=rule.severity.value,
                message=f"A {s.concept} is near a {o.concept}.",
                object_ids=[s.id, o.id],
                timestamp=now,
            )
        return None

    if cond.operator == Operator.OVERLAPS:
        objects = _objects_for_selector(scene, cond.object or "", concepts)
        for s in subjects:
            for o in objects:
                if s.id != o.id and geo.overlaps(s.bbox, o.bbox):
                    return Violation(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        severity=rule.severity.value,
                        message=f"A {s.concept} overlaps a {o.concept}.",
                        object_ids=[s.id, o.id],
                        timestamp=now,
                    )
        return None

    if cond.operator in (Operator.INSIDE_ZONE, Operator.OUTSIDE_ZONE):
        zone = next((z for z in zones if z.id == cond.zone_id or z.name == cond.zone_id), None)
        if zone is None:
            return Violation(
                rule_id=rule.id,
                rule_name=rule.name,
                severity=rule.severity.value,
                message=f"Zone '{cond.zone_id}' is not defined. Draw it on the camera view.",
                object_ids=[],
                timestamp=now,
            )
        inside = [
            s
            for s in subjects
            if geo.bbox_inside_zone(s.bbox, zone.polygon)
            or geo.bbox_zone_overlap_ratio(s.bbox, zone.polygon) >= ZONE_OVERLAP_THRESHOLD
        ]
        if cond.operator == Operator.OUTSIDE_ZONE and inside:
            s = inside[0]
            return Violation(
                rule_id=rule.id,
                rule_name=rule.name,
                severity=rule.severity.value,
                message=f"Blocked access: a {s.concept} is inside the {zone.name} zone.",
                object_ids=[s.id for s in inside],
                timestamp=now,
            )
        if cond.operator == Operator.INSIDE_ZONE and subjects and not inside:
            return Violation(
                rule_id=rule.id,
                rule_name=rule.name,
                severity=rule.severity.value,
                message=f"A {subjects[0].concept} left the {zone.name} zone.",
                object_ids=[subjects[0].id],
                timestamp=now,
            )
        return None

    if cond.operator == Operator.PRESENT_FOR:
        if subjects and not cond.duration_seconds:
            # Ban on mere presence: fire as soon as anything is visible.
            s = subjects[0]
            return Violation(
                rule_id=rule.id,
                rule_name=rule.name,
                severity=rule.severity.value,
                message=f"A {s.concept} is present.",
                object_ids=[s.id for s in subjects],
                timestamp=now,
            )
        duration = cond.duration_seconds or 10.0
        mapping = tracker.update(scene.objects, now)
        for s in subjects:
            tid = mapping.get(s.id)
            if tid and tracker.present_duration(tid, now) >= duration:
                return Violation(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    severity=rule.severity.value,
                    message=f"A {s.concept} was left unattended for {duration:g}s.",
                    object_ids=[s.id],
                    timestamp=now,
                )
        return None

    if cond.operator == Operator.ABSENT_FOR:
        if subjects:
            tracker.update(scene.objects, now)
            return None
        duration = cond.duration_seconds or 10.0
        # No subject visible: check how long tracks of that concept are stale.
        concept = (concepts.get(cond.subject) or cond.subject).lower()
        for track in tracker.tracks.values():
            if track["concept"].lower() == concept and now - track["last_seen"] >= duration:
                return Violation(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    severity=rule.severity.value,
                    message=f"A {concept} has been absent for {duration:g}s.",
                    object_ids=[],
                    timestamp=now,
                )
        tracker.update(scene.objects, now)
        return None

    if cond.operator == Operator.NOT_NEAR_FOR:
        objects = _objects_for_selector(scene, cond.object or "", concepts)
        duration = cond.duration_seconds or 10.0
        mapping = tracker.update(scene.objects, now)
        if not subjects:
            return None
        threshold = cond.threshold or DEFAULT_FAR_FROM_THRESHOLD
        dist, s, _ = _min_pair_distance(subjects, objects)
        if dist < threshold and s is not None:
            # Near right now: stamp the contact time and keep waiting.
            tid = mapping.get(s.id)
            if tid and tid in tracker.tracks:
                tracker.tracks[tid]["last_near"] = now
            return None
        object_concept = concepts.get(cond.object or "") or cond.object or "object"
        for s in subjects:
            tid = mapping.get(s.id)
            track = tracker.tracks.get(tid) if tid else None
            if not track:
                continue
            anchor = track.get("last_near", track["first_seen"])
            if now - anchor >= duration:
                return Violation(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    severity=rule.severity.value,
                    message=f"A {s.concept} has not been near a {object_concept} for {duration:g}s.",
                    object_ids=[s.id],
                    timestamp=now,
                )
        return None

    return None


def evaluate_rules(
    rules: list[VisualRule],
    scene: SceneGraph,
    zones: list[Zone] | None = None,
    now: float | None = None,
) -> list[Violation]:
    violations: list[Violation] = []
    for rule in rules:
        result = evaluate_rule(rule, scene, zones, now)
        if result is not None:
            violations.append(result)
    return violations
