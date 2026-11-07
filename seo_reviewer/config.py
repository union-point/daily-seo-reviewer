"""Versioned, non-secret runtime configuration."""

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_validator


def origin(url: str) -> str:
    """Return an HTTP origin, rejecting credentials and ambiguous URLs."""
    parts = urlsplit(url)
    if parts.scheme not in {"https", "http"} or not parts.hostname:
        raise ValueError("Expected an absolute HTTP(S) URL")
    if parts.username or parts.password or "\\" in url or any(c.isspace() for c in url):
        raise ValueError("Credentials, backslashes, and whitespace are not allowed in URLs")
    port = parts.port
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if port and port != {"http": 80, "https": 443}[parts.scheme]:
        host += f":{port}"
    return urlunsplit((parts.scheme, host, "", "", ""))


class Config(BaseModel):
    schema_version: int = 1
    site_url: str = "https://www.djangoproject.com"
    user_agent: str = (
        "DailySEOReviewer/0.1 (+https://github.com/union-point/daily-seo-reviewer)"
    )
    model: str = "gpt-6.1-terra"
    request_interval: float = Field(default=1.0, ge=1.0, le=60)
    connect_timeout: float = Field(default=5, gt=0, le=60)
    read_timeout: float = Field(default=20, gt=0, le=60)
    retries: int = Field(default=1, ge=0, le=2)
    max_body_bytes: int = Field(default=4_000_000, gt=0, le=10_000_000)
    max_pages: int = Field(default=100, ge=50, le=100)
    max_sitemaps: int = Field(default=6, ge=1, le=20)
    ai_max_input_bytes: int = Field(default=32000, ge=4000, le=64000)
    ai_max_findings: int = Field(default=50, ge=1, le=100)
    ai_max_output_tokens: int = Field(default=2048, ge=512, le=4096)
    ai_timeout: float = Field(default=30, gt=0, le=60)
    data_dir: Path = Path("data")

    @field_validator("site_url")
    @classmethod
    def validate_site_url(cls, value: str) -> str:
        result = origin(value)
        parts = urlsplit(value)
        if parts.path not in {"", "/"} or parts.query or parts.fragment:
            raise ValueError("SITE_URL must be an origin without a path, query, or fragment")
        return result

    @classmethod
    def from_env(cls, **overrides: object) -> "Config":
        values = {
            field: os.environ[env]
            for field, env in {
                "site_url": "SITE_URL",
                "model": "OPENAI_MODEL",
                "user_agent": "SEO_USER_AGENT",
                "request_interval": "SEO_REQUEST_INTERVAL",
                "max_pages": "SEO_MAX_PAGES",
                "max_sitemaps": "SEO_MAX_SITEMAPS",
                "data_dir": "SEO_DATA_DIR",
            }.items()
            if env in os.environ
        }
        values.update({key: value for key, value in overrides.items() if value is not None})
        return cls.model_validate(values)
