"""Synthetic scenarios; these are never presented as collected site history."""
from datetime import UTC, datetime

from seo_reviewer.detection import Finding, detect, finding_id, restrictions
from seo_reviewer.models import FetchEvidence
from seo_reviewer.observations import Observation


def page(url='https://example.com/', run='run', **changes):
    item = Observation(run_id=run, outcome='success', title='Title', description='Description', h1s=['Heading'], canonicals=[url], json_ld_count=1, evidence=FetchEvidence(requested_url=url, final_url=url, fetched_at=datetime.now(UTC), status_code=200, body_path='responses/example.body'))
    return item.model_copy(update=changes)


def active(result):
    return {raw['id']: Finding.model_validate(raw) for raw in result['findings'] if raw['state'] != 'resolved'}


def test_baseline_persistence_failure_recovery():
    item = page(title=None)
    first = detect([item], {}, {}, {}, 'first')
    issue = first['findings'][0]
    assert issue['rule'] == 'missing_title' and issue['state'] == 'new'
    assert issue['baseline_issue'] and not issue['regression']
    ongoing = detect([item], {}, active(first), {}, 'second')
    assert ongoing['findings'][0]['state'] == 'ongoing'
    failed = detect([item.model_copy(update={'outcome': 'collection_failed'})], {}, active(ongoing), {}, 'third')
    assert failed['findings'][0]['state'] == 'unverified'
    recovered = detect([page()], {}, active(failed), {}, 'fourth')
    assert recovered['findings'][0]['state'] == 'resolved'
    assert recovered['alert_status'] == 'healthy'


def test_confirmed_http_regression_and_unconfirmed_failure():
    previous = page(run='before')
    item = page(outcome='http_error')
    item.evidence.status_code = 404
    url = item.evidence.requested_url
    uncertain = detect([item], {url: previous}, {}, {}, 'now')
    assert uncertain['findings'][0]['state'] == 'unverified'
    assert uncertain['alert_status'] == 'verification_required'
    confirmed = detect([item], {url: previous}, {}, {url: item}, 'now')
    issue = confirmed['findings'][0]
    assert issue['regression'] and issue['state'] == 'new'
    assert confirmed['alert_status'] == 'critical'
    assert len(issue['evidence']) == 2
    conflict = detect([item], {url: previous}, {}, {url: previous}, 'now')
    assert conflict['findings'][0]['state'] == 'unverified'


def test_noindex_regression_persists_and_recovers():
    before = page()
    restricted = page(robots_meta=['robots: noindex, follow'])
    url = before.evidence.requested_url
    first = detect([restricted], {url: before}, {}, {url: restricted}, 'r1')
    assert first['alert_status'] == 'critical'
    second = detect([restricted], {url: restricted}, active(first), {url: restricted}, 'r2')
    assert second['findings'][0]['state'] == 'ongoing'
    assert second['findings'][0]['regression']
    recovered = detect([before], {url: restricted}, active(second), {}, 'r3')
    assert recovered['findings'][0]['state'] == 'resolved'


def test_existing_noindex_baseline_is_warning():
    item = page(x_robots_tag='noindex')
    result = detect([item], {}, {}, {}, 'baseline')
    assert result['alert_status'] == 'warning'
    assert result['findings'][0]['baseline_issue']


def test_index_directives_normalize_order_case_none_and_bot_scope():
    assert restrictions(page(robots_meta=['robots: FOLLOW, NOINDEX'])) == restrictions(page(x_robots_tag='none'))
    assert restrictions(page(robots_meta=['googlebot: noindex'])) == {'googlebot:noindex'}
    assert restrictions(page(x_robots_tag='nofollow')) == set()


def test_malformed_json_worsens_without_becoming_critical():
    first = detect([page(json_ld_errors=['bad'])], {}, {}, {}, 'r1')
    second = detect([page(json_ld_errors=['bad', 'bad'])], {}, active(first), {}, 'r2')
    assert second['findings'][0]['state'] == 'worsened'
    assert second['findings'][0]['severity'] == 'warning'


def test_canonical_change_stays_open_until_original_returns():
    before = page()
    after = page(canonicals=['https://example.com/other'])
    url = before.evidence.requested_url
    first = detect([after], {url: before}, {}, {}, 'r1')
    second = detect([after], {url: after}, active(first), {}, 'r2')
    assert second['findings'][0]['state'] == 'ongoing'
    assert second['findings'][0]['before'] == before.canonicals
    assert detect([before], {url: after}, active(second), {}, 'r3')['findings'][0]['state'] == 'resolved'


def test_duplicate_recovery_requires_observations_for_original_peers():
    a, b = page(), page('https://example.com/b')
    first = detect([a, b], {}, {}, {}, 'r1')
    assert len(first['findings']) == 2
    partial = detect([a], {a.evidence.requested_url: a, b.evidence.requested_url: b}, active(first), {}, 'r2')
    assert all(issue['state'] == 'unverified' for issue in partial['findings'])
    unique = b.model_copy(update={'title': 'Unique'})
    recovered = detect([a, unique], {}, active(first), {}, 'r3')
    assert all(issue['state'] == 'resolved' for issue in recovered['findings'])


def test_widespread_changes_flag_investigation_without_suppressing_issues():
    before = [page(f'https://example.com/{i}', title=f'Title {i}') for i in range(4)]
    previous = {item.evidence.requested_url: item for item in before}
    after = [item.model_copy(update={'title': None}) if i < 2 else item for i, item in enumerate(before)]
    result = detect(after, previous, {}, {}, 'r')
    assert result['widespread_change'] and result['changed_pages'] == 2
    assert len(result['findings']) == 2 and all(issue['regression'] for issue in result['findings'])
    boundary = detect([after[0], *before[1:]], previous, {}, {}, 'r')
    assert not boundary['widespread_change']


def test_context_does_not_create_critical_findings():
    before = page()
    after = page(title='Changed', h1s=['one', 'two'], json_ld_count=0)
    after.evidence.redirects = ['https://example.com/final']
    result = detect([after], {before.evidence.requested_url: before}, {}, {}, 'r')
    assert result['findings'] == []
    assert {item['rule'] for item in result['context']} == {'title_changed', 'multiple_h1s', 'structured_data_absent', 'redirect'}
    assert finding_id('missing_title', 'https://example.com/A') != finding_id('missing_title', 'https://example.com/a')


def test_max_image_preview_none_is_not_noindex():
    assert restrictions(page(robots_meta=['robots: max-image-preview:none'])) == set()
    assert restrictions(page(robots_meta=['robots: max-image-preview:none, noindex'])) == {'all:noindex'}


def test_unchanged_existing_issue_is_not_claimed_as_regression():
    item = page(description=None)
    result = detect([item], {item.evidence.requested_url: item}, {}, {}, 'first-detection')
    assert result['findings'][0]['baseline_issue']
    assert not result['findings'][0]['regression']


def test_site_wide_confirmed_http_errors_are_not_suppressed():
    before = [page(f'https://example.com/{i}') for i in range(4)]
    after = [item.model_copy(deep=True, update={'outcome': 'http_error'}) for item in before]
    for item in after:
        item.evidence.status_code = 500
    result = detect(after, {item.evidence.requested_url: item for item in before}, {}, {item.evidence.requested_url: item for item in after}, 'outage')
    assert result['alert_status'] == 'critical'
    assert result['widespread_change']
    assert result['changed_pages'] == result['comparable_pages'] == 4
