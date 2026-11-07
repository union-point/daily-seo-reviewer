import json
from datetime import UTC, datetime

import pytest
import requests

from conftest import FakeSession, response
from seo_reviewer.collection import Fetch
from seo_reviewer.config import Config
from seo_reviewer.crawl import observe, run_crawl, select_cohort
from seo_reviewer.models import FetchEvidence

SITE = 'https://example.com'
ARTICLES = [f'{SITE}/weblog/2026/oct/{day:02d}/post-{number}/' for number, day in enumerate([1 + i % 28 for i in range(60)])]
HTML = b'<html><title> A  Title </title><h1>Heading</h1></html>'


def sitemap(urls):
    return ('<urlset>' + ''.join(f'<url><loc>{url}</loc></url>' for url in urls) + '</urlset>').encode()


def setup_run(monkeypatch, tmp_path, urls, page_responses=None, sitemap_response=None, **config):
    if page_responses is None:
        page_responses = [response(body=HTML, **{'Content-Type': 'text/html'}) for _ in range(100)]
    session = FakeSession([response(404), sitemap_response or response(body=sitemap(urls)), *page_responses])
    monkeypatch.setattr('seo_reviewer.collection.requests.Session', lambda: session)
    result = run_crawl(Config(site_url=SITE, data_dir=tmp_path, pagespeed={'enabled': False}, retries=0, **config))
    return result, session


def test_cohort_is_exact_recent_and_order_independent():
    cohort = select_cohort(SITE, ARTICLES + [ARTICLES[0]])
    assert len(cohort) == len(set(cohort)) == 50
    assert cohort[:2] == [SITE + '/', SITE + '/weblog/']
    assert cohort == select_cohort(SITE, list(reversed(ARTICLES)))
    assert '/oct/28/' in cohort[2]


def test_small_discovery_does_not_establish_short_cohort():
    with pytest.raises(ValueError):
        select_cohort(SITE, ARTICLES[:47])


def test_extract_fields_normalizes_text_and_resolves_urls():
    evidence = FetchEvidence(requested_url=SITE + '/start', final_url=SITE + '/end/', fetched_at=datetime.now(UTC), status_code=200, headers={'Content-Type': 'text/html', 'X-Robots-Tag': 'noindex'})
    body = b'''<title>A  <b>title</b></title><meta name="DESCRIPTION" content=" A  description ">
    <meta name="robots" content="noindex, follow"><base href="/base/">
    <link rel="alternate canonical" href="../Canonical"><h1>One <span>heading</span></h1><h1>Two</h1>
    <script type="application/ld+json">{"@type":"Article"}</script>
    <script type="application/ld+json">broken</script>'''
    item = observe(Fetch(evidence, body), 'run')
    assert item.outcome == 'success'
    assert item.description == 'A description'
    assert item.h1s == ['One heading', 'Two']
    assert item.canonicals == [SITE + '/Canonical']
    assert item.robots_meta == ['robots: noindex, follow']
    assert item.x_robots_tag == 'noindex'
    assert item.json_ld_count == 2 and len(item.json_ld_errors) == 1


def test_missing_fields_are_successfully_observed():
    evidence = FetchEvidence(requested_url=SITE, final_url=SITE, fetched_at=datetime.now(UTC), status_code=200, headers={'Content-Type': 'text/html'})
    item = observe(Fetch(evidence, b'<html><body>plain</body></html>'), 'run')
    assert item.outcome == 'success'
    assert item.title is None and item.description is None and item.h1s == []


def test_fixed_cohort_new_pages_and_deferred_queue(monkeypatch, tmp_path, clock):
    baseline, _ = setup_run(monkeypatch, tmp_path, ARTICLES)
    assert baseline['baseline_only'] and baseline['coverage']['successful'] == 50
    added = [f'{SITE}/new/{i:03d}/' for i in range(55)]
    result, session = setup_run(monkeypatch, tmp_path, ARTICLES + added)
    assert result['cohort'] == baseline['cohort']
    assert result['coverage'] == {'attempted': 100, 'successful': 100, 'failed': 0, 'deferred': 5}
    assert len(result['sitemap_added']) == 55
    assert not result['baseline_only']
    assert len(result['previous_observations']) == 50
    assert len(session.calls) == 102
    next_result, _ = setup_run(monkeypatch, tmp_path, ARTICLES + added)
    assert next_result['coverage']['attempted'] == 55
    assert next_result['deferred_urls'] == []


def test_failure_preserves_previous_success_and_recovery(monkeypatch, tmp_path, clock):
    baseline, _ = setup_run(monkeypatch, tmp_path, ARTICLES)
    original = json.loads((tmp_path / 'state.json').read_text())['latest_successful']
    failures = [requests.Timeout() for _ in range(50)]
    failed, _ = setup_run(monkeypatch, tmp_path, ARTICLES, failures)
    assert failed['status'] == 'collection_failed'
    assert json.loads((tmp_path / 'state.json').read_text())['latest_successful'] == original
    recovered, _ = setup_run(monkeypatch, tmp_path, ARTICLES)
    assert recovered['coverage']['successful'] == 50
    assert all(item['run_id'] == baseline['run_id'] for item in recovered['previous_observations'].values())
    assert len(list(tmp_path.glob('runs/*/collection.json'))) == 3


def test_sitemap_failure_still_checks_cohort_without_false_removals(monkeypatch, tmp_path, clock):
    baseline, _ = setup_run(monkeypatch, tmp_path, ARTICLES)
    result, _ = setup_run(monkeypatch, tmp_path, [], sitemap_response=response(503))
    assert result['status'] == 'partial_crawl'
    assert result['sitemap_removed'] == []
    assert result['coverage']['attempted'] == 50
    assert json.loads((tmp_path / 'state.json').read_text())['sitemap_urls'] == baseline['sitemap_urls']


def test_removed_cohort_urls_remain_in_cohort(monkeypatch, tmp_path, clock):
    baseline, _ = setup_run(monkeypatch, tmp_path, ARTICLES)
    removed = baseline['cohort'][2]
    result, _ = setup_run(monkeypatch, tmp_path, [url for url in ARTICLES if url != removed])
    assert result['sitemap_removed'] == [removed]
    assert removed in result['cohort']
    assert removed in [item['evidence']['requested_url'] for item in result['observations']]


def test_failed_new_url_is_retried(monkeypatch, tmp_path, clock):
    setup_run(monkeypatch, tmp_path, ARTICLES)
    added = SITE + '/new/'
    pages = [response(body=HTML, **{'Content-Type': 'text/html'}) for _ in range(50)] + [response(404), response(404)]
    failed, _ = setup_run(monkeypatch, tmp_path, ARTICLES + [added], pages)
    assert failed['observations'][-1]['outcome'] == 'http_error'
    recovered, _ = setup_run(monkeypatch, tmp_path, ARTICLES + [added])
    assert recovered['coverage']['attempted'] == 51
    assert json.loads((tmp_path / 'state.json').read_text())['pending_urls'] == []


def test_robots_failure_cannot_replace_state(monkeypatch, tmp_path, clock):
    setup_run(monkeypatch, tmp_path, ARTICLES)
    original = json.loads((tmp_path / 'state.json').read_text())
    session = FakeSession([response(403)])
    monkeypatch.setattr('seo_reviewer.collection.requests.Session', lambda: session)
    result = run_crawl(Config(site_url=SITE, data_dir=tmp_path, pagespeed={'enabled': False}, retries=0))
    state = json.loads((tmp_path / 'state.json').read_text())
    assert state['latest_successful'] == original['latest_successful']
    assert state['sitemap_urls'] == original['sitemap_urls']
    assert result['status'] == 'collection_failed'
    assert len(session.calls) == 1


def test_challenge_stops_remaining_pages(monkeypatch, tmp_path, clock):
    result, session = setup_run(monkeypatch, tmp_path, ARTICLES, [response(body=b'<title>Just a moment...</title>')])
    assert result['coverage']['attempted'] == 1
    assert result['coverage']['deferred'] == 49
    assert len(session.calls) == 3


def test_origin_change_requires_separate_state(monkeypatch, tmp_path, clock):
    setup_run(monkeypatch, tmp_path, ARTICLES)
    with pytest.raises(ValueError, match='mismatch'):
        run_crawl(Config(site_url='https://other.example', data_dir=tmp_path))


def test_run_cli(monkeypatch, tmp_path, clock):
    monkeypatch.setenv('PAGESPEED_ENABLED', 'false')
    from seo_reviewer.__main__ import main
    session = FakeSession([response(404), response(body=sitemap(ARTICLES))] + [response(body=HTML, **{'Content-Type': 'text/html'}) for _ in range(50)])
    monkeypatch.setattr('seo_reviewer.collection.requests.Session', lambda: session)
    assert main(['run', '--site-url', SITE, '--data-dir', str(tmp_path)]) == 0


def test_http_charset_preserves_unicode():
    evidence = FetchEvidence(requested_url=SITE, final_url=SITE, fetched_at=datetime.now(UTC), status_code=200, headers={'Content-Type': 'text/html; charset=utf-8'})
    item = observe(Fetch(evidence, '<title>Հայերեն café</title>'.encode()), 'run')
    assert item.title == 'Հայերեն café'


def test_page_limit_preserves_new_url_queue(monkeypatch, tmp_path, clock):
    setup_run(monkeypatch, tmp_path, ARTICLES)
    result, _ = setup_run(monkeypatch, tmp_path, ARTICLES + [SITE + '/added'], max_pages=50)
    assert result['coverage']['attempted'] == 50
    assert result['deferred_urls'] == [SITE + '/added']
    assert json.loads((tmp_path / 'state.json').read_text())['pending_urls'] == [SITE + '/added']


def test_insufficient_articles_preserves_failure_evidence(monkeypatch, tmp_path, clock):
    result, session = setup_run(monkeypatch, tmp_path, ARTICLES[:47])
    assert result['cohort'] == []
    assert result['status'] == 'collection_failed'
    assert len(session.calls) == 2
    assert next(tmp_path.glob('runs/*/collection.json')).exists()


def test_first_success_after_robots_failure_is_baseline(monkeypatch, tmp_path, clock):
    session = FakeSession([response(403)])
    monkeypatch.setattr('seo_reviewer.collection.requests.Session', lambda: session)
    run_crawl(Config(site_url=SITE, data_dir=tmp_path, pagespeed={'enabled': False}, retries=0))
    result, _ = setup_run(monkeypatch, tmp_path, ARTICLES)
    assert result['baseline_only']
    assert result['sitemap_added'] == []
    assert result['sitemap_removed'] == []


def test_failed_atomic_state_write_preserves_old_index(monkeypatch, tmp_path, clock):
    setup_run(monkeypatch, tmp_path, ARTICLES)
    before = (tmp_path / 'state.json').read_bytes()
    def fail(*args):
        raise OSError('disk failure')
    monkeypatch.setattr('seo_reviewer.crawl.atomic_json', fail)
    with pytest.raises(OSError):
        setup_run(monkeypatch, tmp_path, ARTICLES)
    assert (tmp_path / 'state.json').read_bytes() == before
    assert len(list(tmp_path.glob('runs/*/collection.json'))) == 2


def test_finalized_collection_cannot_receive_more_responses(tmp_path):
    from seo_reviewer.storage import RunStore
    store = RunStore(tmp_path)
    (store.path / 'collection.json').write_text('{}')
    evidence = FetchEvidence(requested_url=SITE, final_url=SITE, fetched_at=datetime.now(UTC))
    with pytest.raises(FileExistsError):
        store.save_response(evidence, b'changed')


def test_confirmed_critical_is_saved_with_both_observations(monkeypatch, tmp_path, clock):
    setup_run(monkeypatch, tmp_path, ARTICLES)
    pages = [response(404)] + [response(body=HTML, **{'Content-Type': 'text/html'}) for _ in range(49)] + [response(404)]
    result, session = setup_run(monkeypatch, tmp_path, ARTICLES, pages)
    issue = next(item for item in result['detection']['findings'] if item['rule'] == 'http_error')
    assert issue['severity'] == 'critical' and issue['regression']
    assert len(issue['evidence']) == 2
    assert len(result['confirmations']) == 1
    assert len(session.calls) == 53
    assert issue['id'] in json.loads((tmp_path / 'state.json').read_text())['active_findings']


def test_conflicting_noindex_recheck_preserves_successful_baseline(monkeypatch, tmp_path, clock):
    setup_run(monkeypatch, tmp_path, ARTICLES)
    old = json.loads((tmp_path / 'state.json').read_text())['latest_successful'][SITE + '/']
    restricted = b'<title>A Title</title><meta name="robots" content="noindex"><h1>Heading</h1>'
    pages = [response(body=restricted, **{'Content-Type': 'text/html'})] + [response(body=HTML, **{'Content-Type': 'text/html'}) for _ in range(50)]
    result, _ = setup_run(monkeypatch, tmp_path, ARTICLES, pages)
    issue = next(item for item in result['detection']['findings'] if item['rule'] == 'indexing_restricted')
    assert issue['state'] == 'unverified' and not issue['regression']
    assert result['coverage']['successful'] == 50
    assert result['status'] == 'partial_crawl'
    assert json.loads((tmp_path / 'state.json').read_text())['latest_successful'][SITE + '/'] == old


def test_robots_regression_rechecks_policy_without_crawling_excluded_urls(monkeypatch, tmp_path, clock):
    setup_run(monkeypatch, tmp_path, ARTICLES)
    policy = b'User-agent: *\nDisallow: /weblog/'
    session = FakeSession([response(body=policy), response(body=sitemap(ARTICLES)), response(body=HTML, **{'Content-Type': 'text/html'}), response(body=policy)])
    monkeypatch.setattr('seo_reviewer.collection.requests.Session', lambda: session)
    result = run_crawl(Config(site_url=SITE, data_dir=tmp_path, pagespeed={'enabled': False}, retries=0))
    issues = [item for item in result['detection']['findings'] if item['rule'] == 'robots_excluded']
    assert len(issues) == 49
    assert all(item['state'] == 'new' and item['regression'] for item in issues)
    assert len(session.calls) == 4
