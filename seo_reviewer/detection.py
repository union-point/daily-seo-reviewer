"""Deterministic findings. Collection evidence is authoritative; no model decisions."""

import hashlib
from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field

from seo_reviewer.observations import Observation, normalize

Severity = Literal['info', 'warning', 'critical']
Lifecycle = Literal['new', 'ongoing', 'worsened', 'resolved', 'unverified']
RANK = {'info': 0, 'warning': 1, 'critical': 2}


class Finding(BaseModel):
    schema_version: int = 1
    id: str
    rule: str
    urls: list[str]
    severity: Severity
    confidence: Literal['high', 'low'] = 'high'
    state: Lifecycle = 'new'
    first_seen_run: str
    last_seen_run: str
    baseline_issue: bool = False
    regression: bool = False
    evidence: list[dict] = Field(default_factory=list)
    before: object = None
    observed: object = None
    magnitude: int = 1
    related_urls: list[str] = Field(default_factory=list)


def finding_id(rule: str, url: str) -> str:
    return hashlib.sha256(f'{rule}\n{url}'.encode()).hexdigest()[:24]


def restrictions(item: Observation) -> set[str]:
    result: set[str] = set()
    for value in [*item.robots_meta, item.x_robots_tag or '']:
        scope = 'all'
        for part in value.lower().split(','):
            if ':' in part:
                agent, part = part.split(':', 1)
                if agent.strip() in {'max-image-preview', 'max-snippet', 'max-video-preview', 'unavailable_after'}:
                    continue
                scope = 'all' if agent.strip() in {'robots', 'all'} else agent.strip()
            if part.strip() in {'noindex', 'none'}:
                result.add(f'{scope}:noindex')
    return result


def critical_signature(item: Observation) -> tuple | None:
    if item.outcome == 'http_error':
        return ('http_error', item.evidence.status_code)
    if item.evidence.error == 'robots_disallowed':
        return ('robots_excluded',)
    if item.outcome == 'success' and restrictions(item):
        return ('indexing_restricted', tuple(sorted(restrictions(item))))
    return None


def needs_confirmation(item: Observation, previous: Observation | None) -> bool:
    signature = critical_signature(item)
    return signature is not None and (
        signature[0] == 'http_error' or (previous is not None and signature != critical_signature(previous))
    )


def detect(
    observations: list[Observation], previous: dict[str, Observation],
    active: dict[str, Finding], confirmations: dict[str, Observation], run_id: str,
) -> dict:
    current = {item.evidence.requested_url: item for item in observations}
    titles = Counter(normalize(item.title) for item in observations if item.outcome == 'success' and item.title)
    candidates: dict[str, Finding] = {}
    context: list[dict] = []
    comparable = {url for url, item in current.items() if url in previous and (item.outcome == 'success' or (critical_signature(item) is not None and url in confirmations and critical_signature(item) == critical_signature(confirmations[url])))}
    changed: set[str] = set()

    def add(item: Observation, rule: str, severity: Severity, observed: object, before: object = None, magnitude: int = 1) -> None:
        url = item.evidence.requested_url
        key = finding_id(rule, url)
        old = active.get(key)
        prior = previous.get(url)
        introduced = prior is not None and (
            (rule == 'http_error') or (rule == 'robots_excluded')
            or (rule == 'indexing_restricted' and bool(restrictions(item) - restrictions(prior)))
            or (rule == 'canonical_changed' and before != observed)
            or (rule == 'missing_title' and bool(prior.title))
            or (rule == 'missing_description' and bool(prior.description))
            or (rule == 'missing_h1' and any(prior.h1s))
            or (rule == 'malformed_json_ld' and len(item.json_ld_errors) > len(prior.json_ld_errors))
            or (rule == 'duplicate_title' and sum(other.title == item.title for other in previous.values()) < magnitude)
        )
        regression = (old.regression if old else False) or introduced or (
            old is not None and not old.baseline_issue and rule == 'indexing_restricted' and old.before == []
        )
        critical = severity == 'critical'
        confirmation = confirmations.get(url)
        verified = not critical or (confirmation is not None and critical_signature(confirmation) == critical_signature(item))
        evidence = [{'run_id': item.run_id, **item.evidence.model_dump(mode='json')}]
        if confirmation is not None:
            evidence.append({'run_id': confirmation.run_id, **confirmation.evidence.model_dump(mode='json')})
        candidates[key] = Finding(
            id=key, rule=rule, urls=[url], severity=severity,
            confidence='high' if verified else 'low',
            state='unverified' if not verified else (
                'worsened' if old and (RANK[severity] > RANK[old.severity] or magnitude > old.magnitude)
                else 'ongoing' if old else 'new'
            ),
            first_seen_run=old.first_seen_run if old else run_id, last_seen_run=run_id,
            baseline_issue=old.baseline_issue if old else not introduced,
            regression=regression and verified,
            evidence=evidence, observed=observed, before=old.before if old else before,
            magnitude=magnitude,
            related_urls=sorted(other_url for other_url, other in current.items() if rule == 'duplicate_title' and other.outcome == 'success' and other.title == item.title),
        )

    for url, item in current.items():
        prior = previous.get(url)
        if item.outcome == 'http_error':
            add(item, 'http_error', 'critical', item.evidence.status_code, prior.evidence.status_code if prior else None)
        if item.evidence.error == 'robots_disallowed':
            add(item, 'robots_excluded', 'critical' if prior else 'warning', 'disallowed', 'allowed' if prior else None)
        if item.outcome != 'success':
            if url in comparable:
                changed.add(url)
            continue
        if not item.title:
            add(item, 'missing_title', 'warning', item.title, prior.title if prior else None)
        elif titles[normalize(item.title)] > 1:
            add(item, 'duplicate_title', 'warning', item.title, magnitude=titles[normalize(item.title)])
        if not item.description:
            add(item, 'missing_description', 'warning', item.description, prior.description if prior else None)
        if not item.h1s or not any(item.h1s):
            add(item, 'missing_h1', 'warning', item.h1s, prior.h1s if prior else None)
        if item.json_ld_errors:
            add(item, 'malformed_json_ld', 'warning', item.json_ld_errors, prior.json_ld_errors if prior else None, magnitude=len(item.json_ld_errors))
        old_index = active.get(finding_id('indexing_restricted', url))
        if restrictions(item):
            introduced = (prior is not None and bool(restrictions(item) - restrictions(prior))) or (old_index is not None and old_index.severity == 'critical')
            add(item, 'indexing_restricted', 'critical' if introduced else 'warning', sorted(restrictions(item)), sorted(restrictions(prior)) if prior else None)
        old_canonical = active.get(finding_id('canonical_changed', url))
        canonical_before = old_canonical.before if old_canonical else prior.canonicals if prior else None
        if canonical_before is not None and item.canonicals != canonical_before:
            add(item, 'canonical_changed', 'warning', item.canonicals, canonical_before)
        if prior:
            fields = ['title', 'description', 'h1s', 'canonicals', 'robots_meta', 'x_robots_tag', 'json_ld_count', 'json_ld_errors']
            if any(getattr(item, field) != getattr(prior, field) for field in fields) or item.evidence.final_url != prior.evidence.final_url or item.evidence.redirects != prior.evidence.redirects:
                changed.add(url)
            if item.title != prior.title:
                context.append({'rule': 'title_changed', 'url': url, 'before': prior.title, 'observed': item.title})
        if len(item.h1s) > 1:
            context.append({'rule': 'multiple_h1s', 'url': url, 'observed': item.h1s})
        if item.json_ld_count == 0:
            context.append({'rule': 'structured_data_absent', 'url': url})
        if item.evidence.redirects:
            context.append({'rule': 'redirect', 'url': url, 'observed': item.evidence.redirects})

    for key, old in active.items():
        if key in candidates:
            continue
        url = old.urls[0]
        item = current.get(url)
        verified_recovery = item is not None and item.outcome == 'success'
        if old.rule == 'duplicate_title':
            # A missing peer could still share this title. Partial checks cannot prove uniqueness.
            verified_recovery = verified_recovery and all(current.get(peer) is not None and current[peer].outcome == 'success' for peer in (old.related_urls or old.urls))
        candidates[key] = old.model_copy(update={
            'state': 'resolved' if verified_recovery else 'unverified',
            'confidence': 'high' if verified_recovery else 'low',
            'last_seen_run': run_id,
            'evidence': [{'run_id': item.run_id, **item.evidence.model_dump(mode='json')}] if item else old.evidence,
        })
    findings = sorted(candidates.values(), key=lambda value: (-RANK[value.severity], value.rule, value.urls))
    open_findings = [item for item in findings if item.state != 'resolved']
    status = 'critical' if any(item.severity == 'critical' and item.state != 'unverified' for item in open_findings) else 'warning' if any(item.state != 'unverified' for item in open_findings) else 'verification_required' if open_findings else 'healthy'
    return {
        'schema_version': 1, 'rules_version': '1', 'baseline_only': not previous,
        'alert_status': status, 'findings': [item.model_dump(mode='json') for item in findings],
        'context': context, 'comparable_pages': len(comparable),
        'changed_pages': len(changed),
        'widespread_change': bool(comparable) and len(changed) / len(comparable) > 0.25,
    }
