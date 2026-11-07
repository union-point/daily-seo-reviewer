"""Conservative lab checks using the existing finding and lifecycle contract."""

from seo_reviewer.config import PageSpeedConfig
from seo_reviewer.detection import Finding, finding_id
from seo_reviewer.pagespeed import PageSpeedObservation, measurement_key

LIMITS = {'lcp_ms': (4000, 1000), 'cls': (0.25, 0.1), 'tbt_ms': (600, 300)}


def is_pagespeed(finding: Finding) -> bool:
    return finding.rule == 'pagespeed_performance' or finding.rule.startswith('lighthouse_seo:')


def comparable(current: PageSpeedObservation, previous: PageSpeedObservation | None) -> bool:
    return bool(previous and previous.status != 'unavailable' and current.status != 'unavailable'
                and measurement_key(current) == measurement_key(previous)
                and current.lighthouse_version and current.lighthouse_version == previous.lighthouse_version
                and current.final_url and current.final_url == previous.final_url)


def performance_problem(item: PageSpeedObservation, config: PageSpeedConfig) -> bool:
    return item.performance_score is not None and item.performance_score < config.poor_score and any(
        item.metrics.get(name) is not None and item.metrics[name] > limit
        for name, (limit, _) in LIMITS.items()
    )


def performance_complete(item: PageSpeedObservation) -> bool:
    return item.status != 'unavailable' and item.performance_score is not None and all(item.metrics.get(name) is not None for name in LIMITS)


def detect_pagespeed(observations: list[PageSpeedObservation], previous: dict[str, PageSpeedObservation], active: dict[str, Finding], run_id: str, config: PageSpeedConfig) -> list[Finding]:
    candidates = {}
    current = {measurement_key(item): item for item in observations}

    def evidence(item: PageSpeedObservation) -> dict:
        return {key: value for key, value in item.model_dump(mode='json').items() if key in {
            'run_id', 'url', 'strategy', 'collected_at', 'status', 'body_path', 'body_sha256', 'lighthouse_version', 'final_url',
        }}

    def add(item: PageSpeedObservation, rule: str, observed: dict, before: object, introduced: bool) -> None:
        key = finding_id(rule + ':' + item.strategy, item.url)
        old = active.get(key)
        candidates[key] = Finding(
            id=key, rule=rule, urls=[item.url], severity='warning', state='ongoing' if old else 'new',
            first_seen_run=old.first_seen_run if old else run_id, last_seen_run=run_id,
            baseline_issue=old.baseline_issue if old else not introduced,
            regression=old.regression if old else introduced,
            observed=observed, before=old.before if old else before, evidence=[evidence(item)],
        )

    for item in observations:
        if item.status == 'unavailable':
            continue
        prior = previous.get(measurement_key(item))
        can_compare = comparable(item, prior)
        if performance_problem(item, config):
            introduced = bool(can_compare and performance_complete(prior) and not performance_problem(prior, config) and any(
                item.metrics.get(name) is not None and prior.metrics.get(name) is not None
                and item.metrics[name] > limit and prior.metrics[name] <= limit
                and item.metrics[name] - prior.metrics[name] >= max(margin, prior.metrics[name] * 0.3)
                for name, (limit, margin) in LIMITS.items()
            ))
            add(item, 'pagespeed_performance', {'strategy': item.strategy, 'score': item.performance_score, **item.metrics},
                {'strategy': prior.strategy, 'score': prior.performance_score, **prior.metrics} if can_compare else None, introduced)
        for audit in item.audits.values():
            if audit.category != 'seo' or not audit.failed:
                continue
            prior_audit = prior.audits.get(audit.id) if can_compare else None
            add(item, 'lighthouse_seo:' + audit.id, {'strategy': item.strategy, **audit.model_dump(mode='json')},
                {'strategy': prior.strategy, **prior_audit.model_dump(mode='json')} if prior_audit else None,
                bool(prior_audit and prior_audit.score == 1))

    for key, old in active.items():
        if key in candidates:
            continue
        strategy = old.evidence[0].get('strategy') if old.evidence else None
        item = current.get(str(strategy) + '\n' + old.urls[0])
        recovered = False
        prior = previous.get(measurement_key(item)) if item else None
        reference = old.evidence[0] if old.evidence else {}
        same_environment = comparable(item, prior) if item and prior else bool(item
            and item.lighthouse_version and item.lighthouse_version == reference.get('lighthouse_version')
            and item.final_url and item.final_url == reference.get('final_url'))
        if item and item.status != 'unavailable' and same_environment:
            if old.rule == 'pagespeed_performance':
                recovered = performance_complete(item) and not performance_problem(item, config)
            else:
                audit = item.audits.get(old.rule.split(':', 1)[1])
                recovered = bool(audit and audit.score == 1)
        candidates[key] = old.model_copy(update={
            'state': 'resolved' if recovered else 'unverified', 'confidence': 'high' if recovered else 'low',
            'last_seen_run': run_id, 'evidence': [evidence(item)] if item else old.evidence,
        })
    return sorted(candidates.values(), key=lambda item: (item.rule, item.urls, item.id))
