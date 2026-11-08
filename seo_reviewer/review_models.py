"""Versioned review contracts; AI prose cannot supply authoritative facts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from seo_reviewer.detection import Finding


class AIItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    finding_id: str
    evidence_ids: list[str] = Field(min_length=1, max_length=3)
    explanation: str = Field(min_length=1, max_length=800)
    recommended_action: str = Field(min_length=1, max_length=800)
    # Absent only in historical artifacts; new model output uses TriageItem.
    title: str | None = None
    completion_criterion: str | None = None


class Narrative(BaseModel):
    model_config = ConfigDict(extra='forbid')
    headline: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=1200)
    prioritized_issues: list[AIItem]
    verification_items: list[AIItem]


class TriageItem(AIItem):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=160)
    completion_criterion: str = Field(min_length=1, max_length=800)


class TriageNarrative(Narrative):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    prioritized_issues: list[TriageItem] = Field(max_length=5)
    verification_items: list[TriageItem] = Field(max_length=5)


class GenerationAttempt(BaseModel):
    outcome: str
    returned_model: str | None = None
    response_id: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)


class Generation(BaseModel):
    outcome: Literal['success', 'unavailable'] = 'unavailable'
    reason: str
    requested_model: str
    prompt_version: str = 'triage-v5'
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

    @model_validator(mode='after')
    def validate_current_ai_narrative(self) -> 'Review':
        if self.narrative_source == 'ai' and self.generation.prompt_version in {'triage-v4', 'triage-v5'}:
            if self.generation.outcome != 'success':
                raise ValueError('AI mode requires successful generation')
            TriageNarrative.model_validate(self.narrative.model_dump())
        return self
