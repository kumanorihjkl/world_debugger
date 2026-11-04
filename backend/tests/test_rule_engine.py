"""Rule engine tests: violation, no violation, resolved transition."""

from app.models.dsl import Condition, Operator, Selector, Severity, VisualRule
from app.models.scene import Zone
from app.services import rule_engine
from app.services.scene_graph import build_scene_graph

DRINK_RULE = VisualRule(
    id="rule-test",
    name="Spill risk",
    original_text="Keep drinks away from laptops.",
    severity=Severity.WARNING,
    selectors=[
        Selector(id="drink", concept="drink", sam_prompt="cup"),
        Selector(id="laptop", concept="laptop", sam_prompt="laptop"),
    ],
    condition=Condition(operator=Operator.FAR_FROM, subject="drink", object="laptop"),
)


def _scene(detections: list[dict]) -> object:
    return build_scene_graph(detections)


def test_spatial_violation_when_close() -> None:
    scene = _scene(
        [
            {"concept": "cup", "selector_id": "drink", "bbox": [0.10, 0.45, 0.30, 0.65]},
            {"concept": "laptop", "selector_id": "laptop", "bbox": [0.32, 0.45, 0.55, 0.70]},
        ]
    )
    violations = rule_engine.evaluate_rules([DRINK_RULE], scene)  # type: ignore[arg-type]
    assert len(violations) == 1
    assert "too close" in violations[0].message


def test_no_violation_when_far() -> None:
    scene = _scene(
        [
            {"concept": "cup", "selector_id": "drink", "bbox": [0.78, 0.10, 0.93, 0.35]},
            {"concept": "laptop", "selector_id": "laptop", "bbox": [0.10, 0.45, 0.45, 0.85]},
        ]
    )
    violations = rule_engine.evaluate_rules([DRINK_RULE], scene)  # type: ignore[arg-type]
    assert violations == []


def test_resolved_transition() -> None:
    close = _scene(
        [
            {"concept": "cup", "selector_id": "drink", "bbox": [0.10, 0.45, 0.30, 0.65]},
            {"concept": "laptop", "selector_id": "laptop", "bbox": [0.32, 0.45, 0.55, 0.70]},
        ]
    )
    far = _scene(
        [
            {"concept": "cup", "selector_id": "drink", "bbox": [0.78, 0.10, 0.93, 0.35]},
            {"concept": "laptop", "selector_id": "laptop", "bbox": [0.10, 0.45, 0.45, 0.85]},
        ]
    )
    assert len(rule_engine.evaluate_rules([DRINK_RULE], close)) == 1  # type: ignore[arg-type]
    assert rule_engine.evaluate_rules([DRINK_RULE], far) == []  # type: ignore[arg-type]


def test_zone_rule_blocked_and_resolved() -> None:
    rule = VisualRule(
        id="rule-zone",
        name="Blocked access",
        original_text="Keep this doorway clear.",
        severity=Severity.WARNING,
        selectors=[Selector(id="object", concept="object", sam_prompt="cardboard box")],
        condition=Condition(operator=Operator.OUTSIDE_ZONE, subject="object", zone_id="doorway"),
    )
    zone = Zone(id="doorway", name="doorway", polygon=[(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)])
    blocked = _scene([{"concept": "box", "selector_id": "object", "bbox": [0.4, 0.4, 0.5, 0.5]}])
    clear = _scene([{"concept": "box", "selector_id": "object", "bbox": [0.0, 0.0, 0.1, 0.1]}])
    assert len(rule_engine.evaluate_rules([rule], blocked, [zone])) == 1  # type: ignore[arg-type]
    assert rule_engine.evaluate_rules([rule], clear, [zone]) == []  # type: ignore[arg-type]


def test_presence_ban_fires_immediately() -> None:
    rule = VisualRule(
        id="rule-ban",
        name="No purple objects",
        original_text="no purple objects.",
        severity=Severity.WARNING,
        selectors=[Selector(id="sel_purple", concept="purple objects", sam_prompt="purple object")],
        condition=Condition(operator=Operator.PRESENT_FOR, subject="sel_purple"),
    )
    scene = _scene(
        [{"concept": "purple object", "selector_id": "sel_purple", "bbox": [0.3, 0.3, 0.6, 0.8]}]
    )
    violation = rule_engine.evaluate_rule(rule, scene, now=1000.0)  # type: ignore[arg-type]
    assert violation is not None
    assert "present" in violation.message
    empty = _scene([])
    assert rule_engine.evaluate_rule(rule, empty, now=1000.0) is None  # type: ignore[arg-type]


def test_temporal_present_for() -> None:
    rule_engine.reset_tracker()
    tracker = rule_engine.Tracker()
    rule = VisualRule(
        id="rule-temp",
        name="Unattended object",
        original_text="Warn me if this object is left unattended for 10 seconds.",
        severity=Severity.WARNING,
        selectors=[Selector(id="object", concept="bag", sam_prompt="bag")],
        condition=Condition(operator=Operator.PRESENT_FOR, subject="object", duration_seconds=10.0),
    )
    scene = _scene([{"concept": "bag", "selector_id": "object", "bbox": [0.2, 0.5, 0.45, 0.85]}])
    assert rule_engine.evaluate_rule(rule, scene, now=1000.0, tracker=tracker) is None  # type: ignore[arg-type]
    violation = rule_engine.evaluate_rule(rule, scene, now=1011.0, tracker=tracker)  # type: ignore[arg-type]
    assert violation is not None
    assert "unattended" in violation.message


def _unattended_rule() -> VisualRule:
    return VisualRule(
        id="rule-not-near",
        name="Laptop left unattended",
        original_text="Warn me if a laptop is left unattended for more than 10 seconds.",
        severity=Severity.WARNING,
        selectors=[
            Selector(id="laptop", concept="laptop", sam_prompt="laptop"),
            Selector(id="person", concept="person", sam_prompt="person"),
        ],
        condition=Condition(
            operator=Operator.NOT_NEAR_FOR, subject="laptop", object="person", duration_seconds=10.0
        ),
    )


def test_not_near_for_fires_when_object_absent() -> None:
    rule = _unattended_rule()
    tracker = rule_engine.Tracker()
    laptop_only = _scene([{"concept": "laptop", "selector_id": "laptop", "bbox": [0.5, 0.4, 1.0, 0.6]}])
    assert rule_engine.evaluate_rule(rule, laptop_only, now=1000.0, tracker=tracker) is None  # type: ignore[arg-type]
    violation = rule_engine.evaluate_rule(rule, laptop_only, now=1011.0, tracker=tracker)  # type: ignore[arg-type]
    assert violation is not None
    assert "not been near" in violation.message


def test_not_near_for_resets_when_near() -> None:
    rule = _unattended_rule()
    tracker = rule_engine.Tracker()
    laptop_only = _scene([{"concept": "laptop", "selector_id": "laptop", "bbox": [0.5, 0.4, 1.0, 0.6]}])
    laptop_with_person = _scene(
        [
            {"concept": "laptop", "selector_id": "laptop", "bbox": [0.5, 0.4, 1.0, 0.6]},
            {"concept": "person", "selector_id": "person", "bbox": [0.45, 0.35, 0.65, 0.75]},
        ]
    )
    assert rule_engine.evaluate_rule(rule, laptop_only, now=1000.0, tracker=tracker) is None  # type: ignore[arg-type]
    assert rule_engine.evaluate_rule(rule, laptop_with_person, now=1005.0, tracker=tracker) is None  # type: ignore[arg-type]
    assert rule_engine.evaluate_rule(rule, laptop_only, now=1012.0, tracker=tracker) is None  # type: ignore[arg-type]
    violation = rule_engine.evaluate_rule(rule, laptop_only, now=1016.0, tracker=tracker)  # type: ignore[arg-type]
    assert violation is not None
