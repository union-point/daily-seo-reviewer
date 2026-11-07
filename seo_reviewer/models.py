"""Evidence types for the initial integration gate, not SEO findings."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CheckStatus = Literal["passed", "failed", "skipped"]


class FetchEvidence(BaseModel):
    requested_url: str
    final_url: str
    fetched_at: datetime
    status_code: int | None = None
    redirects: list[str] = Field(default_factory=list)
    attempts: int = 0
    duration_seconds: float = 0
    headers: dict[str, str] = Field(default_factory=dict)
    body_path: str | None = None
    body_sha256: str | None = None
    error: str | None = None


class Check(BaseModel):
    name: str
    status: CheckStatus
    detail: str


class ModelProbe(BaseModel):
    status: CheckStatus
    requested_model: str
    returned_model: str | None = None
    prompt_version: str = "preflight-v1"
    response_id: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    detail: str


class Preflight(BaseModel):
    schema_version: int = 1
    kind: Literal["integration-preflight"] = "integration-preflight"
    run_id: str
    started_at: datetime
    completed_at: datetime
    execution_context: Literal["local", "github-actions"]
    workflow_url: str | None = None
    config: dict[str, object]
    checks: list[Check]
    fetches: list[FetchEvidence]
    model: ModelProbe

    @property
    def passed(self) -> bool:
        return all(check.status == "passed" for check in self.checks)
