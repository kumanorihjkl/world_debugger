"""Rule store tests: roundtrip persistence and corrupt-file tolerance."""

from app.models.dsl import Condition, Operator, Selector, Severity, VisualRule
from app.services import rule_store


def _rule() -> VisualRule:
    return VisualRule(
        id="rule-persist",
        name="Spill risk",
        original_text="Keep drinks away from laptops.",
        severity=Severity.WARNING,
        selectors=[
            Selector(id="drink", concept="drink", sam_prompt="cup"),
            Selector(id="laptop", concept="laptop", sam_prompt="laptop"),
        ],
        condition=Condition(operator=Operator.FAR_FROM, subject="drink", object="laptop"),
    )


def test_save_load_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    target = tmp_path / "rules.json"
    rule_store.save_rules({"rule-persist": _rule()}, target)
    loaded = rule_store.load_rules(target)
    assert list(loaded.keys()) == ["rule-persist"]
    assert loaded["rule-persist"].condition.operator == Operator.FAR_FROM


def test_missing_file_loads_empty(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert rule_store.load_rules(tmp_path / "nope.json") == {}


def test_corrupt_file_loads_empty(tmp_path) -> None:  # type: ignore[no-untyped-def]
    target = tmp_path / "rules.json"
    target.write_text("{not json", encoding="utf-8")
    assert rule_store.load_rules(target) == {}
    target.write_text('[{"id": "broken"}]', encoding="utf-8")
    assert rule_store.load_rules(target) == {}
