"""FastAPI routes: health, rule compile/list, frame analysis."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

logger = logging.getLogger("world-debugger")

from app.api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    CompileRequest,
    CompileResponse,
    RuleListResponse,
)
from app.config import settings
from app.models.dsl import VisualRule
from app.services import rule_engine, rule_store, scene_graph, segmentation
from app.services.meta_client import MetaAPIError
from app.services.rule_compiler import compile_rule

router = APIRouter()

_rules: dict[str, VisualRule] = rule_store.load_rules()


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "mock_meta_api": settings.mock_meta_api,
        "rule_model": settings.rule_model,
        "segmentation_model": settings.segmentation_model,
    }


@router.post("/rules/compile", response_model=CompileResponse)
def compile_endpoint(body: CompileRequest) -> CompileResponse:
    try:
        rule, mocked = compile_rule(body.text)
    except MetaAPIError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _rules[rule.id] = rule
    rule_store.save_rules(_rules)
    return CompileResponse(rule=rule, mocked=mocked)


@router.get("/rules", response_model=RuleListResponse)
def list_rules() -> RuleListResponse:
    return RuleListResponse(rules=list(_rules.values()))


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str) -> dict:
    if rule_id not in _rules:
        raise HTTPException(status_code=404, detail="Unknown rule id")
    del _rules[rule_id]
    rule_store.save_rules(_rules)
    return {"deleted": rule_id}


def clear_rules() -> None:
    _rules.clear()


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(body: AnalyzeRequest) -> AnalyzeResponse:
    rules = [r for rid, r in _rules.items() if body.rule_ids is None or rid in body.rule_ids]
    # Dedupe identical prompts: one SAM request per concept, fanned out to
    # every selector that uses it. Avoids duplicate detections (which draw
    # overlapping red+green overlays) and needless API cost.
    unique_prompts: list[str] = []
    prompt_selectors: dict[str, list[str]] = {}
    for rule in rules:
        for sel in rule.selectors:
            if sel.sam_prompt not in prompt_selectors:
                prompt_selectors[sel.sam_prompt] = []
                unique_prompts.append(sel.sam_prompt)
            prompt_selectors[sel.sam_prompt].append(sel.id)
    detections: list[dict] = []
    mocked = False
    try:
        for prompt in unique_prompts:
            per_prompt, was_mocked = segmentation.segment(
                body.image_base64, [prompt], image_variant=body.image_variant
            )
            mocked = mocked or was_mocked
            for det in per_prompt:
                for sel_id in prompt_selectors[prompt]:
                    clone = dict(det)
                    clone["selector_id"] = sel_id
                    detections.append(clone)
    except MetaAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    logger.info(
        "analyze: %d rule(s), prompts=%s, detections=%s",
        len(rules),
        unique_prompts,
        [
            (d.get("concept"), d.get("bbox"), round(float(d.get("confidence", 0)), 2))
            for d in detections
        ],
    )
    scene = scene_graph.build_scene_graph(detections, body.zones)
    violations = rule_engine.evaluate_rules(rules, scene, body.zones)
    return AnalyzeResponse(
        scene=scene, violations=violations, mocked=mocked, rule_ids=[r.id for r in rules]
    )
