"""Canonical actionable issues without discarding source findings or device evidence."""

from dataclasses import dataclass

from seo_reviewer.detection import Finding, finding_id

# Equivalent concrete checks only; audit scores and lab performance stay device-specific.
SEO_EQUIVALENTS = {'meta-description': 'missing_description', 'document-title': 'missing_title'}


def canonical_issue_id(finding: Finding) -> str:
    rule = finding.rule
    if rule.startswith('lighthouse_seo:'):
        audit = rule.split(':', 1)[1]
        rule = SEO_EQUIVALENTS.get(audit, rule)
    elif rule == 'pagespeed_performance':
        observed = finding.observed if isinstance(finding.observed, dict) else {}
        rule += ':' + str(observed.get('strategy') or next((row.get('strategy') for row in finding.evidence if row.get('strategy')), 'unknown'))
    return finding_id(rule, '\n'.join(sorted(finding.urls)))


def historical_status(finding: Finding) -> str:
    if finding.state == 'resolved':
        return 'resolved'
    if finding.state == 'unverified':
        return 'unverified'
    if finding.regression and finding.state in {'new', 'worsened'}:
        return 'confirmed_regression'
    if finding.state in {'ongoing', 'worsened'}:
        return 'previously_detected'
    # baseline_issue means a starting measurement, not proof the issue existed earlier.
    return 'not_comparable'


@dataclass
class IssueGroup:
    id: str
    representative: Finding
    members: list[Finding]
    history: str

    @property
    def state(self) -> str:
        if self.history == 'previously_detected' and self.representative.state == 'new':
            return 'ongoing'
        return self.representative.state


def group_issues(findings: list[Finding], preferred_ids: set[str] | None = None) -> list[IssueGroup]:
    """Group equivalent active evidence; never merge unknown/resolved with active checks."""
    groups: dict[tuple[str, str], list[Finding]] = {}
    preferred_ids = preferred_ids or set()
    for finding in findings:
        lifecycle = finding.state if finding.state in {'resolved', 'unverified'} else 'active'
        groups.setdefault((canonical_issue_id(finding), lifecycle), []).append(finding)
    result = []
    for (key, _), members in groups.items():
        representative = min(enumerate(members), key=lambda pair: (
            pair[1].id not in preferred_ids,
            pair[1].rule.startswith('lighthouse_seo:'), pair[0],
        ))[1]
        # A repeatable crawler condition anchors cross-source history when available.
        historical_members = [item for item in members if not item.rule.startswith('lighthouse_seo:')] or members
        histories = {historical_status(item) for item in historical_members}
        history = next((value for value in ('previously_detected', 'confirmed_regression', 'resolved', 'unverified') if value in histories), 'not_comparable')
        result.append(IssueGroup(key, representative, members, history))
    return result
