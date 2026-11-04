"""File-backed rule store (JSON). Survives backend restarts; no database."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from app.models.dsl import VisualRule

DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "rules.json"


def store_path() -> Path:
    override = os.environ.get("RULES_FILE", "")
    return Path(override) if override else DEFAULT_PATH


def load_rules(path: Path | None = None) -> dict[str, VisualRule]:
    """Load rules from JSON file. Missing/corrupt files yield {} (never crash)."""
    target = path or store_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, list):
        return {}
    rules: dict[str, VisualRule] = {}
    for item in raw:
        try:
            rule = VisualRule.model_validate(item)
        except ValidationError:
            continue
        rules[rule.id] = rule
    return rules


def save_rules(rules: dict[str, VisualRule], path: Path | None = None) -> None:
    """Atomically write rules to JSON file (tmp + rename)."""
    target = path or store_path()
    payload = [rule.model_dump(mode="json") for rule in rules.values()]
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".rules", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, target)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
