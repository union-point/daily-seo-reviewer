"""Bounded model connectivity probe; no crawled text or SEO decisions yet."""

import os
from typing import Literal

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict, ValidationError

from seo_reviewer.config import Config
from seo_reviewer.models import ModelProbe


class ProbeReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: Literal["ok"]
    evidence_ids: list[str]


def probe_model(config: Config, *, skip: bool = False) -> ModelProbe:
    if skip or not os.environ.get("OPENAI_API_KEY"):
        return ModelProbe(
            status="skipped", requested_model=config.model,
            detail="Model probe disabled" if skip else "OPENAI_API_KEY is not configured",
        )
    try:
        with OpenAI(timeout=30.0, max_retries=1) as client:
            response = client.responses.parse(
                model=config.model,
                reasoning={"effort": "low"},
                instructions=(
                    "This is a connectivity test, not an SEO assessment. "
                    "Return result ok and only the supplied evidence ID."
                ),
                input='{"evidence_id":"integration-probe"}',
                text_format=ProbeReply,
                max_output_tokens=512,
                store=False,
            )
        parsed = response.output_parsed
        valid = (
            response.status == "completed" and isinstance(parsed, ProbeReply)
            and parsed.evidence_ids == ["integration-probe"]
        )
        usage = response.usage
        return ModelProbe(
            status="passed" if valid else "failed", requested_model=config.model,
            returned_model=response.model, response_id=response.id,
            usage={
                key: getattr(usage, key) for key in ("input_tokens", "output_tokens", "total_tokens")
            } if usage else {},
            detail="Schema and evidence references validated" if valid else "Refusal, incomplete output, or invalid evidence references",
        )
    except (OpenAIError, ValidationError, ValueError) as exc:
        return ModelProbe(
            status="failed", requested_model=config.model,
            detail=f"Model probe failed ({type(exc).__name__})",
        )
