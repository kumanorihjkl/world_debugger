"""Compiler schema tests (mock) + API tests with mock Meta API."""

import os

os.environ["MOCK_META_API"] = "true"

from fastapi.testclient import TestClient

from app.api.routes import clear_rules
from app.main import app
from app.models.dsl import Operator
from app.services import rule_compiler

client = TestClient(app)


def test_compile_valid_spatial_rule() -> None:
    rule, mocked = rule_compiler.compile_rule("Keep drinks away from laptops.")
    assert mocked is True
    assert rule.condition.operator == Operator.FAR_FROM
    prompts = [s.sam_prompt for s in rule.selectors]
    assert "laptop" in prompts
    # No compound prompts like "cup or bottle"
    assert all(" or " not in p for p in prompts)


def test_compile_zone_rule() -> None:
    rule, _ = rule_compiler.compile_rule("Keep this doorway clear.")
    assert rule.condition.operator == Operator.OUTSIDE_ZONE


def test_compile_invalid_rule_raises() -> None:
    import pytest

    from app.services.meta_client import MetaAPIError

    with pytest.raises(MetaAPIError):
        rule_compiler.compile_rule("Make it sparkle beautifully forever.")


def test_compile_empty_raises() -> None:
    import pytest

    from app.services.meta_client import MetaAPIError

    with pytest.raises(MetaAPIError):
        rule_compiler.compile_rule("   ")


def test_metric_units_flagged_not_estimated() -> None:
    rule, _ = rule_compiler.compile_rule("Keep drinks at least 30 cm away from laptops.")
    assert rule.condition.requires_metric_depth is True


def test_api_compile_and_analyze_flow() -> None:
    clear_rules()
    resp = client.post("/api/rules/compile", json={"text": "Keep drinks away from laptops."})
    assert resp.status_code == 200, resp.text
    assert resp.json()["mocked"] is True

    resp = client.post("/api/analyze", json={"image_base64": "", "image_variant": "default"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["scene"]["objects"]) >= 2
    assert len(body["violations"]) == 1  # cup near laptop in default fixture

    resp = client.post("/api/analyze", json={"image_base64": "", "image_variant": "far"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["violations"] == []  # drink moved away -> resolved


def test_api_health() -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
