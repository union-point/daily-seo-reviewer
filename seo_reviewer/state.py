"""Versioned comparison index; run snapshots remain the source of evidence."""

from typing import Literal

from pydantic import BaseModel, Field

from seo_reviewer.observations import Observation


class ComparisonState(BaseModel):
    schema_version: Literal[1] = 1
    site_url: str
    cohort: list[str] = Field(default_factory=list)
    latest_successful: dict[str, Observation] = Field(default_factory=dict)
    sitemap_urls: list[str] = Field(default_factory=list)
    sitemap_run_id: str | None = None
    known_sitemap_urls: list[str] = Field(default_factory=list)
    pending_urls: list[str] = Field(default_factory=list)
    history: list[dict[str, object]] = Field(default_factory=list)
    latest_run_id: str | None = None
