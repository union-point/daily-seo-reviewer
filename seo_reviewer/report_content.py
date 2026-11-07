"""Plain-language presentation of saved facts; never change detection or evidence."""

from seo_reviewer.detection import Finding
from seo_reviewer.review_models import Review


# Title, observed condition, business impact, next action. Keep diagnostics in JSON.
ISSUE_COPY = {
    'missing_title': (
        'Page title missing', 'The page has no title.',
        'A clear title helps people understand the page when it appears in search results.',
        'Add a descriptive title that is specific to this page.',
    ),
    'duplicate_title': (
        'Pages share the same title', 'More than one checked page uses this title.',
        'People may struggle to tell these pages apart in search results.',
        'Give these pages distinct titles that describe their content.',
    ),
    'missing_description': (
        'Search description missing', 'The page has no search description.',
        'A useful description can help people decide whether to visit from search results.',
        'Add a concise description that explains what this page offers.',
    ),
    'missing_h1': (
        'Main heading missing', 'The page has no main heading.',
        'A clear heading helps readers understand the subject of the page.',
        'Add a main heading that clearly describes the page.',
    ),
    'malformed_json_ld': (
        'Search information cannot be read', 'Some structured information about the page is incorrectly formatted.',
        'Search engines may be unable to use this information for enhanced search results.',
        'Ask your web team to check and fix the page’s structured data.',
    ),
    'canonical_changed': (
        'Preferred search page changed', 'The page points search engines to a different preferred version.',
        'This can change which version of the page appears in search results.',
        'Confirm which page should appear in search and ask your web team to restore the preferred version if needed.',
    ),
    'http_error': (
        'Page could not be opened', 'The page returned an error instead of its content.',
        'Visitors and search engines may be unable to reach the page.',
        'Ask your web team to restore the page or confirm that its removal was intentional.',
    ),
    'robots_excluded': (
        'Search crawling blocked', 'The site’s crawling instructions block access to this page.',
        'Search engines may be unable to check this page for updates.',
        'Confirm whether this page should be accessible to search engines before asking your web team to change the restriction.',
    ),
    'indexing_restricted': (
        'Page asks to stay out of search', 'The page includes instructions to keep it out of search results.',
        'This page may be excluded from search results even when visitors can open it.',
        'Confirm whether this page should appear in search before asking your web team to remove the restriction.',
    ),
}


def report_presentation(review: Review, collection: dict) -> dict:
    """Derive honest status, coverage and change copy from authoritative values."""
    coverage = review.coverage
    checked = coverage['successful']
    total = coverage['attempted'] + coverage['deferred']
    # A stopped crawl may never attempt its saved cohort. Do not say 0 of 0
    # when the snapshot already identifies pages that should have been checked.
    total = max(total, len(collection.get('cohort', [])))
    incomplete = (
        checked < total or total == 0 or coverage['failed'] > 0
        or review.collection_status != 'collected' or bool(collection.get('errors'))
    )
    active = [item for item in review.findings if item.state not in {'resolved', 'unverified'}]
    unverified = sum(item.state == 'unverified' for item in review.findings)
    resolved = sum(item.state == 'resolved' for item in review.findings)
    new = sum(item.regression and item.state == 'new' for item in active)
    worse = sum(item.state == 'worsened' for item in active)
    existing = sum(item.state == 'ongoing' for item in active)
    first_observed = sum(item.state == 'new' and not item.regression for item in active)
    labels = {
        'critical': ('High-priority issues', 'critical'),
        'warning': ('Needs attention', 'warning'),
        'verification_required': ('Needs verification', 'warning'),
        'healthy': ('No issues found in checked pages', 'healthy'),
    }
    status_label, status_tone = labels.get(review.alert_status, ('Needs verification', 'warning'))
    if review.alert_status == 'healthy' and (incomplete or unverified):
        status_label, status_tone = ('Check incomplete' if incomplete else 'Needs verification', 'warning')
    if active:
        summary = f'{len(active)} issue{"s" if len(active) != 1 else ""} to address on the checked pages. Start with the priority issues below.'
    elif incomplete or unverified:
        summary = 'There is not enough verified information to give the checked pages an all-clear. Complete the checks before drawing conclusions.'
    else:
        summary = 'No current issues were found by these checks. This report covers selected pages, not the whole site.'
    if review.baseline_only:
        changes = 'First report: these checks are the starting point for future comparisons. Issues found today are not confirmed new issues.'
    else:
        changes = f'{new} new issue{"s" if new != 1 else ""}, {worse} worsened, {existing} still present, {resolved} resolved.'
        if first_observed:
            changes += f' {first_observed} issue{"s were" if first_observed != 1 else " was"} observed for the first time; {"they are" if first_observed != 1 else "it is"} not confirmed as {"new issues" if first_observed != 1 else "a new issue"}.'
        if unverified:
            changes += f' {unverified} issue{"s" if unverified != 1 else ""} still need verification.'
        if incomplete:
            changes += ' Changes on unchecked pages are unknown.'
    errors = []
    if coverage['failed']:
        errors.append(f'{coverage["failed"]} page{"s" if coverage["failed"] != 1 else ""} could not be checked successfully.')
    if coverage['deferred']:
        errors.append(f'{coverage["deferred"]} page{"s were" if coverage["deferred"] != 1 else " was"} left for a later check.')
    if collection.get('errors') or collection.get('sitemap_complete') is False:
        errors.append('Some checks or page discovery could not be completed.')
    elif collection.get('request_errors'):
        errors.append('Some requests had problems. Recheck the affected pages before drawing conclusions.')
    return {
        'coverage_text': f'{checked} of {total} pages checked' if total else 'No pages checked',
        'incomplete': incomplete, 'status_label': status_label, 'status_tone': status_tone,
        'summary': summary, 'changes': changes, 'unverified_count': unverified,
        'error_summary': ' '.join(errors),
    }


def observation_text(rule: str, value: object) -> str:
    """Format useful changes without printing JSON or parser diagnostics."""
    if value is None:
        return 'Not recorded'
    if value == '' or value == []:
        return 'Not set'
    if rule == 'malformed_json_ld':
        count = len(value) if isinstance(value, list) else 1
        return f'{count} formatting problem{"s" if count != 1 else ""}'
    if rule == 'http_error':
        return f'Page response: {value}'
    if rule == 'robots_excluded':
        return {'allowed': 'Crawling allowed', 'disallowed': 'Crawling blocked'}.get(str(value), 'Crawling restriction recorded')
    if rule == 'indexing_restricted':
        return 'Kept out of search results'
    if isinstance(value, list):
        return '\n'.join(str(item) for item in value)
    return str(value)


def issue_presentation(finding: Finding) -> dict:
    title, happened, matters, action = ISSUE_COPY.get(finding.rule, (
        'Page needs review', 'A page check found a condition that needs investigation.',
        'This may affect how people find or use the page.',
        'Ask your web team to review the page and the saved check details.',
    ))
    if finding.rule == 'canonical_changed' and finding.observed == []:
        happened = 'The page no longer names a preferred version for search.'
    if finding.state == 'unverified':
        state = 'Needs verification'
        happened = f'Last reported: {happened} This check could not confirm whether it is still happening.'
        action = 'Ask your web team to recheck the affected pages before deciding whether a fix is needed.'
    elif finding.state == 'resolved':
        state = 'Resolved'
        happened = f'Previously: {happened} The latest successful check no longer found this issue.'
        action = 'No fix is needed for this issue now. Monitor the page in the next report.'
    elif finding.state == 'worsened':
        state = 'Worsened'
    elif finding.state == 'ongoing':
        state = 'Still present'
    else:
        state = 'New issue' if finding.regression else 'First observed'
    return {
        'title': title, 'happened': happened, 'matters': matters, 'action': action,
        'state_label': state,
        'priority_label': {'critical': 'High priority', 'warning': 'Needs attention', 'info': 'Note'}[finding.severity],
        'show_change': finding.state not in {'resolved', 'unverified'} and finding.before is not None and finding.before != finding.observed,
        'before': observation_text(finding.rule, finding.before),
        'observed': observation_text(finding.rule, finding.observed),
        'observation_label': 'Last seen' if finding.state in {'resolved', 'unverified'} else 'Now',
        'verification': {
            'missing_title': 'Run a new check and confirm the page has a descriptive title.',
            'duplicate_title': 'Recheck all affected pages and confirm their titles are distinct.',
            'missing_description': 'Run a new check and confirm the page has a useful search description.',
            'missing_h1': 'Run a new check and confirm the main heading is present.',
            'canonical_changed': 'Recheck the page and confirm the preferred search version matches your decision.',
            'http_error': 'Recheck the page and confirm visitors can open it, or verify that its removal was intended.',
            'robots_excluded': 'Recheck crawling access after confirming whether the restriction is intended.',
            'indexing_restricted': 'Recheck the search instructions after confirming whether exclusion is intended.',
            'malformed_json_ld': 'Run a new check and confirm the structured information has no formatting errors.',
        }.get(finding.rule, 'Run a new check and review the result with your web team.') if finding.state != 'unverified' else 'Complete a reliable follow-up check and confirm whether the issue persists or has been resolved.',
    }
