"""Generate an immutable review from a saved collection without crawling again."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from seo_reviewer.config import Config
from seo_reviewer.detection import Finding, RANK
from seo_reviewer.review_models import AIItem, Narrative, Review
from seo_reviewer.triage import triage_findings

ACTIONS = {
    'missing_title': 'Add a descriptive, page-specific title.',
    'duplicate_title': 'Give these pages distinct titles that describe their content.',
    'missing_description': 'Add a concise, page-specific meta description.',
    'missing_h1': 'Add a meaningful primary heading.',
    'malformed_json_ld': 'Validate and correct the malformed JSON-LD blocks.',
    'canonical_changed': 'Verify the canonical target and restore it if the change was unintended.',
    'http_error': 'Verify the response and restore the page or confirm the intended removal.',
    'robots_excluded': 'Check whether the robots exclusion was intended before changing the policy.',
    'indexing_restricted': 'Verify whether the indexing restriction is intended before removing it.',
}


def fallback_narrative(findings: list[Finding], summary: str) -> Narrative:
    def item(finding: Finding) -> AIItem:
        return AIItem(
            finding_id=finding.id, evidence_ids=[finding.id + ':finding'],
            explanation=f'{finding.rule.replace("_", " ")} ({finding.state}).',
            recommended_action=ACTIONS.get(finding.rule, 'Review the stored evidence and verify the condition.'),
        )
    ranked = sorted(findings, key=lambda finding: (-RANK[finding.severity], finding.rule, finding.id))
    return Narrative(
        headline='AI summary unavailable', summary=summary,
        prioritized_issues=[item(finding) for finding in ranked if finding.state not in {'resolved', 'unverified'}][:5],
        verification_items=[item(finding) for finding in ranked if finding.state == 'unverified'][:5],
    )


def generate_review(config: Config, run_id: str, *, skip_ai: bool = False) -> Review:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', run_id):
        raise ValueError('Invalid run ID')
    source = config.data_dir / 'runs' / run_id / 'collection.json'
    target = config.data_dir / 'reviews' / f'{run_id}.json'
    # Idempotent retries preserve the original model result and avoid another paid call.
    if target.exists():
        existing = Review.model_validate_json(target.read_text())
        if existing.collection_sha256 != hashlib.sha256(source.read_bytes()).hexdigest():
            raise ValueError('Saved review source digest mismatch')
        return existing
    target.parent.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (target.parent / '.review.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if target.exists():
            return Review.model_validate_json(target.read_text())
        raw = source.read_bytes()
        collection = json.loads(raw)
        if collection.get('schema_version') != 1 or collection.get('run_id') != run_id or 'detection' not in collection:
            raise ValueError('Review requires a matching collection snapshot with detection')
        findings = [Finding.model_validate(value) for value in collection['detection']['findings']]
        count = sum(finding.state != 'resolved' for finding in findings)
        coverage = collection['coverage']
        summary = (
            f"SEO status: {collection['detection']['alert_status']}. "
            f"Collected {coverage['successful']} of {coverage['attempted']} attempted pages; "
            f"{coverage['deferred']} deferred. {count} active findings. "
            + ('Baseline only; no historical regression claims.' if collection['detection']['baseline_only'] else 'Compared with stored successful observations.')
        )
        narrative, generation = triage_findings(config, collection, findings, skip=skip_ai)
        result = Review(
            run_id=run_id, created_at=datetime.now(UTC),
            collection_path=f'runs/{run_id}/collection.json',
            collection_sha256=hashlib.sha256(raw).hexdigest(),
            alert_status=collection['detection']['alert_status'], collection_status=collection['status'],
            coverage=coverage, baseline_only=collection['detection']['baseline_only'],
            findings=findings, detection=collection['detection'], deterministic_summary=summary,
            narrative=narrative or fallback_narrative(findings, summary),
            narrative_source='ai' if narrative else 'deterministic', generation=generation,
        )
        # Atomic exclusive publication: readers never see an incomplete review.
        import os
        import tempfile
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=target.parent, delete=False, encoding='utf-8') as output:
                temporary = Path(output.name)
                output.write(result.model_dump_json(indent=2) + '\n')
                output.flush()
                os.fsync(output.fileno())
            os.link(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return result
