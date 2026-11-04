"""Natural language → VisualRule compiler.

Production path: Muse Spark (`muse-spark-1.3`) with Structured Output, using
the Pydantic DSL model as the response schema (no hand-rolled JSON parsing).

Mock path (`MOCK_META_API=true`): deterministic keyword compiler + fixtures
so development costs nothing. Mock output is labeled as mock and must never
be presented as real AI output in production UI.
"""

from __future__ import annotations

import re
import uuid

from pydantic import ValidationError

from app.config import settings
from app.models.dsl import Condition, Operator, Selector, Severity, VisualRule
from app.services.meta_client import MetaAPIError, MetaClient, call_with_retry

SYSTEM_PROMPT = """You compile physical-world monitoring rules into a VisualRule DSL.
Rules:
- Use only these operators: near, far_from, overlaps, inside_zone, outside_zone, present_for, absent_for, not_near_for.
- Each selector gets ONE short single-object noun phrase as sam_prompt (e.g. 'cup', 'laptop'). Never compound prompts like 'cup or bottle'; split them into separate selectors.
- Distances are image-space normalized (0..1). Never invent metric measurements.
- If the user asks for real-world units (cm, meters, inches), set requires_metric_depth=true.
- For a ban on mere presence ("no X", "alert if any X is present"), use present_for with duration_seconds 0 (omit duration only when the user names a time span).
- Respond with the VisualRule JSON object only.
"""


def _compile_spatial_drink_laptop(text: str) -> VisualRule | None:
    if not re.search(r"drink|cup|bottle|beverage|coffee", text, re.I):
        return None
    if not re.search(r"laptop|computer|notebook|macbook|pc\b", text, re.I):
        return None
    if not re.search(r"away|far|separate|keep.*dist|not.*near|spill", text, re.I):
        return None
    return VisualRule(
        id=f"rule-{uuid.uuid4().hex[:8]}",
        name="Spill risk",
        original_text=text,
        description="Keep drinks away from laptops.",
        severity=Severity.WARNING,
        selectors=[
            Selector(id="drink", concept="drink", sam_prompt="cup"),
            Selector(id="drink_alt", concept="drink", sam_prompt="bottle"),
            Selector(id="laptop", concept="laptop", sam_prompt="laptop"),
        ],
        condition=Condition(operator=Operator.FAR_FROM, subject="drink", object="laptop"),
        explanation="A drink too close to a laptop is a spill risk.",
    )


def _compile_zone_clear(text: str) -> VisualRule | None:
    m = re.search(r"keep\s+(?:this\s+)?(\w+)?\s*(doorway|zone|area|entrance|path|walkway)\s*clear", text, re.I)
    if not m:
        if not re.search(r"clear|blocked|blocking|keep.*free|don't.*block", text, re.I):
            return None
    zone_word = (m.group(1) or m.group(2) or "zone") if m else "zone"
    zone_word = zone_word.strip().lower() or "zone"
    return VisualRule(
        id=f"rule-{uuid.uuid4().hex[:8]}",
        name="Blocked access",
        original_text=text,
        description=f"Keep the {zone_word} zone clear.",
        severity=Severity.WARNING,
        selectors=[
            Selector(id="object", concept="object", sam_prompt="cardboard box"),
        ],
        condition=Condition(operator=Operator.OUTSIDE_ZONE, subject="object", zone_id=zone_word),
        explanation=f"Any object inside the {zone_word} zone blocks access.",
    )


def _compile_unattended(text: str) -> VisualRule | None:
    if not re.search(r"unattended|left|alone|abandon", text, re.I):
        return None
    m = re.search(r"(\d+)\s*(?:second|sec)", text, re.I)
    duration = float(m.group(1)) if m else 10.0
    return VisualRule(
        id=f"rule-{uuid.uuid4().hex[:8]}",
        name="Unattended object",
        original_text=text,
        description="Warn when an object is left unattended.",
        severity=Severity.WARNING,
        selectors=[Selector(id="object", concept="object", sam_prompt="bag")],
        condition=Condition(
            operator=Operator.PRESENT_FOR, subject="object", duration_seconds=duration
        ),
        explanation=f"An object left in place for {duration:g}s is unattended.",
    )


def mock_compile(text: str) -> VisualRule:
    """Deterministic heuristic compiler for offline development."""
    text = text.strip()
    if not text:
        raise MetaAPIError("Rule text is empty. Describe a rule for this space...")
    metric = re.search(r"\d+\s*(cm|centimeter|meter|metre|inch|ft|feet)", text, re.I)
    for fn in (_compile_spatial_drink_laptop, _compile_zone_clear, _compile_unattended):
        rule = fn(text)
        if rule is not None:
            if metric:
                rule.condition.requires_metric_depth = True
                rule.explanation += " (Metric depth is not available in this MVP.)"
            return rule
    # Generic fallback: proximity rule between two mentioned nouns is ambiguous.
    raise MetaAPIError(
        "Could not compile that rule. Try e.g. 'Keep drinks away from laptops.' "
        "or 'Keep this doorway clear.'"
    )


def _strict_schema(node: object) -> object:
    """Add `additionalProperties: false` to every object schema node.

    The Meta Model API (like OpenAI Structured Output with strict mode)
    requires it; Pydantic does not emit it by default.
    """
    if isinstance(node, dict):
        fixed = dict(node)
        if fixed.get("type") == "object":
            fixed["additionalProperties"] = False
            props = fixed.get("properties")
            if isinstance(props, dict):
                fixed["required"] = sorted(props.keys())
        return {key: _strict_schema(value) for key, value in fixed.items()}
    if isinstance(node, list):
        return [_strict_schema(item) for item in node]
    return node


def compile_with_spark(text: str, client: MetaClient | None = None) -> VisualRule:
    """Compile via Muse Spark Structured Output."""
    from openai import APIError, APITimeoutError

    meta = client or MetaClient()
    oa = meta.openai_client()
    schema = _strict_schema(VisualRule.model_json_schema())
    assert isinstance(schema, dict)

    def _call() -> VisualRule:
        try:
            resp = oa.responses.create(
                model=settings.rule_model,
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "visual_rule",
                        "schema": schema,
                        "strict": True,
                    }
                },
            )
        except APITimeoutError as exc:
            raise MetaAPIError(f"Muse Spark timed out: {exc}") from exc
        except APIError as exc:
            raise MetaAPIError(f"Muse Spark request failed: {exc}") from exc
        try:
            payload = resp.output_text
        except Exception as exc:  # defensive: SDK shape drift
            raise MetaAPIError(f"Unexpected Muse Spark response shape: {exc}") from exc
        try:
            return VisualRule.model_validate_json(payload)
        except ValidationError as exc:
            raise MetaAPIError(f"Muse Spark returned an invalid rule: {exc}") from exc

    return call_with_retry(_call)


def compile_rule(text: str, client: MetaClient | None = None) -> tuple[VisualRule, bool]:
    """Compile a rule. Returns (rule, mocked)."""
    if settings.mock_meta_api:
        rule = mock_compile(text)
        rule.explanation = (rule.explanation + " [mock]").strip()
        return rule, True
    return compile_with_spark(text, client), False
