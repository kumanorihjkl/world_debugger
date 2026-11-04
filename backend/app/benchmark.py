"""Benchmark harness: fixed scenarios → measured violation metrics.

Usage (from backend/):
    MOCK_META_API=true uv run python -m app.benchmark

Only reports actually measured results — never fabricate numbers.
"""

from __future__ import annotations

import os
import tempfile

if "RULES_FILE" not in os.environ:
    # Never clobber a developer's real rules file from benchmark runs.
    os.environ["RULES_FILE"] = os.path.join(
        tempfile.mkdtemp(prefix="wd-bench-rules-"), "rules.json"
    )

from fastapi.testclient import TestClient

from app.api.routes import clear_rules
from app.main import app
from app.models.scene import Zone

DOORWAY = {"id": "doorway", "name": "doorway", "polygon": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]}

SCENARIOS: list[dict] = [
    {
        "name": "demo1-violation",
        "rule_text": "Keep drinks away from laptops.",
        "image_variant": "default",
        "zones": [],
        "expect_violation": True,
    },
    {
        "name": "demo1-resolved",
        "rule_text": "Keep drinks away from laptops.",
        "image_variant": "far",
        "zones": [],
        "expect_violation": False,
    },
    {
        "name": "demo2-blocked",
        "rule_text": "Keep this doorway clear.",
        "image_variant": "default",
        "zones": [DOORWAY],
        "expect_violation": True,
    },
    {
        "name": "demo2-resolved",
        "rule_text": "Keep this doorway clear.",
        "image_variant": "empty_zone",
        "zones": [DOORWAY],
        "expect_violation": False,
    },
]


def run() -> dict:
    client = TestClient(app)
    total = len(SCENARIOS)
    detected = missed = false_positives = 0
    rows: list[dict] = []
    for sc in SCENARIOS:
        clear_rules()
        zone_objs = [Zone(**z) for z in sc["zones"]]
        cr = client.post("/api/rules/compile", json={"text": sc["rule_text"]})
        assert cr.status_code == 200, cr.text
        ar = client.post(
            "/api/analyze",
            json={
                "image_base64": "",
                "image_variant": sc["image_variant"],
                "zones": [z.model_dump() for z in zone_objs],
            },
        )
        assert ar.status_code == 200, ar.text
        # Count only violations of the compiled rule (a scenario compiles one rule).
        got = len(ar.json()["violations"]) > 0
        want = sc["expect_violation"]
        ok = got == want
        if want and got:
            detected += 1
        elif want and not got:
            missed += 1
        elif not want and got:
            false_positives += 1
        rows.append({"scenario": sc["name"], "expected": want, "got": got, "ok": ok})
    return {
        "total_scenarios": total,
        "detected_violations": detected,
        "missed_violations": missed,
        "false_positives": false_positives,
        "rows": rows,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run(), indent=2))
