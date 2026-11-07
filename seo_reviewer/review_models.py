"""Versioned review contracts; AI prose cannot supply authoritative facts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from seo_reviewer.detection import Finding


class AIItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    finding_id: str
    evidence_ids: list[str] = Field(min_length=1, max_length=3)
    explanation: str = Field(min_length=1, max_length=800)
    recommended_action: str = Field(min_length=1, max_length=800)


class Narrative(BaseModel):
    model_config = ConfigDict(extra='forbid')
    headline: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=1200)
    prioritized_issues: list[AIItem] = Field(max_length=5)
    verification_items: list[AIItem] = Field(max_length=5)


class GenerationAttempt(BaseModel):
    outcome: str
    returned_model: str | None = None
    response_id: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)


class Generation(BaseModel):
    outcome: Literal['success', 'unavailable'] = 'unavailable'
    reason: str
    requested_model: str
    prompt_version: str = 'triage-v3'
    input_sha256: str
    input_bytes: int
    included_finding_ids: list[str]
    omitted_findings: int
    attempts: list[GenerationAttempt] = Field(default_factory=list)


class Review(BaseModel):
    schema_version: Literal[1] = 1
    run_id: str
    created_at: datetime
    collection_path: str
    collection_sha256: str
    alert_status: str
    collection_status: str
    coverage: dict[str, int]
    baseline_only: bool
    findings: list[Finding]
    detection: dict
    deterministic_summary: str
    narrative: Narrative
    narrative_source: Literal['ai', 'deterministic']
    generation: Generation
