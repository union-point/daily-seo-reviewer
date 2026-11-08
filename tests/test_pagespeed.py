"""PSI tests are entirely mocked; measurements are synthetic, never live evidence."""

import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from pydantic import ValidationError

from conftest import FakeSession, response
from seo_reviewer.config import Config, PageSpeedConfig
from seo_reviewer.detection import Finding
from seo_reviewer.models import FetchEvidence
from seo_reviewer.observations import Observation
from seo_reviewer.pagespeed import (
    ENDPOINT, MAX_RESPONSE_BYTES, PageSpeedObservation, collect_pagespeed,
    measurement_key, normalize_result, select_pages,
)
from seo_reviewer.pagespeed_detection import detect_pagespeed
from seo_reviewer.storage import RunStore

SITE = 'https://example.com'
URL = SITE + '/'


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr('seo_reviewer.pagespeed.time', SimpleNamespace(sleep=lambda _: None))
    monkeypatch.delenv('PAGESPEED_API_KEY', raising=False)


@pytest.fixture
def payload():
    return json.loads((Path(__file__).parent / 'fixtures/pagespeed.json').read_text())


def page(url=URL, outcome='success', final=None):
    return Observation(run_id='run', outcome=outcome, evidence=FetchEvidence(
        requested_url=url, final_url=final or url, fetched_at=datetime.now(UTC), status_code=200))


def measured(payload, *, strategy='mobile', run='run', score=0.35, lcp=5200):
    raw = copy.deepcopy(payload)
    raw['lighthouseResult']['categories']['performance']['score'] = score
    if 'largest-contentful-paint' in raw['lighthouseResult']['audits']:
        raw['lighthouseResult']['audits']['largest-contentful-paint']['numericValue'] = lcp
    raw['lighthouseResult']['configSettings']['formFactor'] = strategy
    return normalize_result(PageSpeedObservation(run_id=run, url=URL, strategy=strategy, collected_at=datetime.now(UTC)), raw)


def collect(tmp_path, replies, **options):
    session = FakeSession(replies)
    config = Config(site_url=SITE, data_dir=tmp_path, pagespeed=options)
    store = RunStore(tmp_path)
    return collect_pagespeed(config, store, [page()], session=session), session, store


def api_response(payload):
    return response(body=json.dumps(payload).encode())


def test_collect_both_strategies_without_key_and_save_compact_hashed_evidence(tmp_path, payload):
    desktop = copy.deepcopy(payload)
    desktop['lighthouseResult']['configSettings']['formFactor'] = 'desktop'
    items, session, store = collect(tmp_path, [api_response(payload), api_response(desktop)])
    assert [item.strategy for item in items] == ['mobile', 'desktop']
    assert all(item.status == 'success' for item in items)
    assert items[0].performance_score == 35 and items[0].seo_score == 90
    assert items[0].metrics == {'lcp_ms': 5200, 'cls': 0.02, 'fcp_ms': 1500, 'tbt_ms': 150, 'speed_index_ms': 3200}
    audit = items[0].audits['document-title']
    assert audit.failed and audit.score == 0 and audit.title == 'Document has a title'
    assert items[0].crux_page.status == items[0].crux_origin.status == 'unavailable'
    for item, (endpoint, kwargs) in zip(items, session.calls):
        assert endpoint == ENDPOINT
        assert kwargs['params']['strategy'] == item.strategy
        assert kwargs['params']['category'] == ['performance', 'seo']
        assert 'key' not in kwargs['params']
        assert kwargs['allow_redirects'] is False and kwargs['timeout'] == (5, 60)
        body = (store.path / item.body_path).read_bytes()
        assert hashlib.sha256(body).hexdigest() == item.body_sha256
        assert b'data:image' not in body and len(body) < 15000
    (store.path / 'collection.json').write_text('{}')
    with pytest.raises(FileExistsError):
        store.save_diagnostic('pagespeed', b'{}')


def test_optional_key_only_in_request_not_saved(tmp_path, payload, monkeypatch):
    monkeypatch.setenv('PAGESPEED_API_KEY', 'private-api-key')
    items, session, store = collect(tmp_path, [api_response(payload)], strategies=['mobile'])
    assert session.calls[0][1]['params']['key'] == 'private-api-key'
    assert 'private-api-key' not in items[0].model_dump_json()
    assert all(b'private-api-key' not in path.read_bytes() for path in store.path.rglob('*.json'))


def test_echoed_credentials_are_discarded(tmp_path, payload, monkeypatch):
    monkeypatch.setenv('PAGESPEED_API_KEY', 'private-api-key')
    payload['lighthouseResult']['audits']['document-title']['description'] = 'private-api-key'
    items, _, store = collect(tmp_path, [api_response(payload)], strategies=['mobile'])
    assert items[0].status == 'unavailable' and items[0].error == 'sensitive_response'
    assert not list(store.path.rglob('pagespeed/*.json'))


@pytest.mark.parametrize('failure', [requests.Timeout('secret key=private'), requests.ConnectionError('private')])
def test_transport_failure_bounded_retry_and_safe_errors(tmp_path, failure):
    items, session, _ = collect(tmp_path, [failure, failure], strategies=['mobile'])
    assert items[0].status == 'unavailable' and items[0].attempts == 2
    assert items[0].performance_score is None and items[0].metrics == {}
    assert 'private' not in items[0].model_dump_json()
    assert len(session.calls) == 2


def test_transient_failure_recovers(tmp_path, payload):
    items, session, _ = collect(tmp_path, [response(503), api_response(payload)], strategies=['mobile'])
    assert items[0].status == 'success' and items[0].attempts == 2
    assert items[0].error is None and len(session.calls) == 2


@pytest.mark.parametrize('status', [400, 403, 404, 429, 500])
def test_api_errors_do_not_become_zero_scores(tmp_path, status):
    items, session, _ = collect(tmp_path, [response(status), response(status)], strategies=['mobile'])
    assert items[0].status == 'unavailable' and items[0].performance_score is None
    assert len(session.calls) == (2 if status in {429, 500} else 1)


def test_rate_limit_honors_retry_after_and_defers_remaining_requests(tmp_path):
    items, session, _ = collect(tmp_path, [response(429, **{'Retry-After': '120'})])
    assert items[0].error == 'retry_deferred' and items[1].error == 'quota_deferred'
    assert items[1].attempts == 0 and len(session.calls) == 1


def test_short_rate_limit_waits_then_recovers(tmp_path, payload, monkeypatch):
    sleeps = []
    monkeypatch.setattr('seo_reviewer.pagespeed.time', SimpleNamespace(sleep=sleeps.append))
    items, session, _ = collect(tmp_path, [response(429, **{'Retry-After': '3'}), api_response(payload)], strategies=['mobile'])
    assert items[0].status == 'success' and 3 in sleeps and len(session.calls) == 2


@pytest.mark.parametrize('body', [b'not json', b'[]', b'null', b'{"error":{"message":"sensitive"}}', b'{"lighthouseResult":null}'])
def test_invalid_or_missing_lighthouse_response(tmp_path, body):
    items, session, _ = collect(tmp_path, [response(body=body)], strategies=['mobile'])
    assert items[0].status == 'unavailable' and items[0].error
    assert 'sensitive' not in items[0].model_dump_json() and len(session.calls) == 1


def test_response_size_is_bounded(tmp_path):
    items, _, _ = collect(tmp_path, [response(body=b' ' * (MAX_RESPONSE_BYTES + 1))], strategies=['mobile'])
    assert items[0].status == 'unavailable' and items[0].body_path is None


def test_missing_metrics_and_field_data_are_explicit(payload):
    del payload['lighthouseResult']['audits']['largest-contentful-paint']
    payload['lighthouseResult']['audits']['total-blocking-time']['numericValue'] = None
    payload['lighthouseResult']['categories']['seo']['score'] = None
    item = measured(payload)
    assert item.status == 'incomplete'
    assert item.metrics['lcp_ms'] is None and item.metrics['tbt_ms'] is None and item.seo_score is None
    assert {'lcp_ms', 'tbt_ms', 'seo_score'} <= set(item.missing)
    assert item.crux_page.status == 'unavailable'


@pytest.mark.parametrize('value', [True, -1, '123', None, float('nan'), float('inf')])
def test_invalid_metrics_never_substitute_zero(payload, value):
    payload['lighthouseResult']['audits']['total-blocking-time']['numericValue'] = value
    assert measured(payload).metrics['tbt_ms'] is None


def test_field_data_keeps_origin_fallback_and_units_separate(payload):
    payload['loadingExperience'] = {'id': SITE, 'origin_fallback': True, 'metrics': {
        'CUMULATIVE_LAYOUT_SHIFT_SCORE': {'percentile': 17, 'category': 'AVERAGE', 'distributions': [{'min': 0, 'max': 10, 'proportion': 0.5}]}}}
    item = measured(payload)
    assert item.crux_page.scope == 'origin' and item.crux_page.status == 'available'
    assert item.crux_page.metrics['CUMULATIVE_LAYOUT_SHIFT_SCORE']['percentile'] == 17
    assert item.metrics['cls'] == 0.02


@pytest.mark.parametrize('mutation', ['runtime', 'strategy', 'url', 'unit'])
def test_runtime_errors_wrong_strategies_origins_and_units(payload, mutation):
    if mutation == 'runtime': payload['lighthouseResult']['runtimeError'] = {'code': 'ERRORED_DOCUMENT_REQUEST', 'message': 'private'}
    if mutation == 'strategy': payload['lighthouseResult']['configSettings']['formFactor'] = 'tablet'
    if mutation == 'url': payload['lighthouseResult']['finalUrl'] = 'https://other.example/'
    if mutation == 'unit': payload['lighthouseResult']['audits']['total-blocking-time']['numericUnit'] = 'second'
    item = normalize_result(PageSpeedObservation(run_id='run', url=URL, strategy='mobile', collected_at=datetime.now(UTC)), payload)
    assert item.status == ('incomplete' if mutation == 'unit' else 'unavailable')
    assert 'private' not in item.model_dump_json()


def test_selection_is_deterministic_bounded_distinct_and_reuses_collected_urls():
    config = Config(site_url=SITE)
    urls = [SITE + path for path in ['/articles/b/', '/articles/a/', '/articles/', '/shop/item/', '/', '/shop/', '/faq/']]
    items = [page(url) for url in urls] + [page(SITE + '/failed', 'collection_failed'), page('https://other.example/')]
    selected = select_pages(items, config)
    assert selected[0] == URL and len(selected) == 3
    assert selected == select_pages(list(reversed(items)), config)
    assert len({len([part for part in url.split('/')[3:] if part]) for url in selected}) == 3
    assert set(selected) <= set(urls)
    config.pagespeed.max_pages = 1
    assert select_pages(items, config) == [URL]
    assert select_pages([page(SITE + '/alias', final=URL), page(URL)], config) == [URL]


def test_disabled_or_no_eligible_pages_makes_no_requests(tmp_path):
    config = Config(site_url=SITE, pagespeed={'enabled': False})
    session = FakeSession([])
    store = RunStore(tmp_path)
    assert collect_pagespeed(config, store, [page()], session=session) == []
    config.pagespeed.enabled = True
    assert collect_pagespeed(config, store, [page(outcome='http_error')], session=session) == []
    assert session.calls == []


def detect(items, prior=None, active=None, **settings):
    return detect_pagespeed(items, prior or {}, active or {}, 'now', PageSpeedConfig(**settings))


def test_finding_ids_separate_devices_and_baseline_claims(payload):
    mobile, desktop = measured(payload), measured(payload, strategy='desktop')
    findings = detect([mobile, desktop])
    assert len(findings) == 4 and len({item.id for item in findings}) == 4
    assert all(item.baseline_issue and not item.regression for item in findings)
    assert all(item.evidence[0]['strategy'] in {'mobile', 'desktop'} for item in findings)


def test_large_lab_regression_needs_metric_change_same_url_device_and_version(payload):
    prior = measured(payload, run='old', score=0.8, lcp=2000)
    prior.audits['document-title'].score, prior.audits['document-title'].failed = 1, False
    current = measured(payload)
    findings = detect([current], {measurement_key(prior): prior})
    assert len(findings) == 2 and all(item.regression for item in findings)
    desktop = prior.model_copy(update={'strategy': 'desktop'})
    assert all(not item.regression for item in detect([current], {measurement_key(desktop): desktop}))
    prior.lighthouse_version = 'other'
    assert all(not item.regression for item in detect([current], {measurement_key(prior): prior}))


def test_small_score_changes_do_not_create_regressions(payload):
    prior = measured(payload, score=0.51, lcp=4900)
    current = measured(payload, score=0.49, lcp=5000)
    findings = detect([current], {measurement_key(prior): prior})
    assert not any(item.regression for item in findings)
    assert any(item.rule == 'pagespeed_performance' for item in findings)
    # Poor score without poor core lab metrics never creates a performance finding.
    current.metrics['lcp_ms'] = 2000
    assert not any(item.rule == 'pagespeed_performance' for item in detect([current]))


def test_current_ongoing_unavailable_and_resolved_lifecycles(payload):
    current = measured(payload)
    active = {item.id: item for item in detect([current])}
    assert all(item.state == 'ongoing' for item in detect([current], active=active))
    failure = current.model_copy(update={'status': 'unavailable'})
    assert all(item.state == 'unverified' for item in detect([failure], active=active))
    assert all(item.state == 'unverified' for item in detect([], active=active))
    healthy = measured(payload, score=0.9, lcp=2000)
    healthy.audits['document-title'].score, healthy.audits['document-title'].failed = 1, False
    assert all(item.state == 'resolved' for item in detect([healthy], active=active))
    healthy.metrics['tbt_ms'] = None
    del healthy.audits['document-title']
    assert all(item.state == 'unverified' for item in detect([healthy], active=active))


def test_null_manual_and_informative_audits_do_not_fail(payload):
    for mode in ['manual', 'notApplicable', 'informative', 'error']:
        raw = copy.deepcopy(payload)
        raw['lighthouseResult']['audits']['document-title'].update(score=None, scoreDisplayMode=mode)
        assert not any(item.rule.startswith('lighthouse_seo:') for item in detect([measured(raw)]))


def test_configuration_env_and_validation(monkeypatch):
    monkeypatch.setenv('PAGESPEED_ENABLED', 'false')
    monkeypatch.setenv('PAGESPEED_MAX_PAGES', '2')
    monkeypatch.setenv('PAGESPEED_STRATEGIES', 'desktop')
    monkeypatch.setenv('PAGESPEED_API_KEY', 'private')
    config = Config.from_env()
    assert not config.pagespeed.enabled and config.pagespeed.max_pages == 2
    assert config.pagespeed.strategies == ['desktop'] and 'private' not in config.model_dump_json()
    for options in [{'max_pages': 0}, {'strategies': []}, {'strategies': ['mobile', 'mobile']}, {'strategies': ['tablet']}, {'poor_score': 101}, {'retries': 3}]:
        with pytest.raises(ValidationError):
            PageSpeedConfig(**options)


def test_pipeline_persists_measurements_preserves_history_and_reviews_offline(tmp_path, payload, monkeypatch, clock):
    from seo_reviewer.crawl import run_crawl
    from seo_reviewer.review import generate_review
    from seo_reviewer.render import render_site
    from seo_reviewer.state import ComparisonState
    from test_crawl import ARTICLES, sitemap

    healthy_html = b'<title>Page</title><meta name="description" content="Description"><h1>Heading</h1>'
    config = Config(site_url=SITE, data_dir=tmp_path, retries=0, pagespeed={'max_pages': 1})
    # Simulate the state before PSI existed. Its new fields default safely.
    old = ComparisonState(site_url=SITE).model_dump(mode='json')
    del old['pagespeed_successful']
    (tmp_path / 'state.json').write_text(json.dumps(old))

    def run(api_replies):
        crawl = FakeSession([response(404), response(body=sitemap(ARTICLES))] + [response(body=healthy_html, **{'Content-Type': 'text/html'}) for _ in range(50)])
        api = FakeSession(api_replies)
        clients = iter([crawl, api])
        monkeypatch.setattr('seo_reviewer.collection.requests.Session', lambda: next(clients))
        result = run_crawl(config)
        return result, api

    desktop = copy.deepcopy(payload)
    desktop['lighthouseResult']['configSettings']['formFactor'] = 'desktop'
    first, api = run([api_response(payload), api_response(desktop)])
    assert len(api.calls) == 2 and first['status'] == 'collected'
    assert len(first['pagespeed']['observations']) == 2
    prior = json.loads((tmp_path / 'state.json').read_text())['pagespeed_successful']
    assert len(prior) == 2 and all(value['body_sha256'] for value in prior.values())
    second, api = run([requests.Timeout(), requests.Timeout(), requests.Timeout(), requests.Timeout()])
    assert second['status'] == 'collected'  # optional service failure does not fail the crawl
    assert second['pagespeed']['previous_observations'] == prior
    assert json.loads((tmp_path / 'state.json').read_text())['pagespeed_successful'] == prior
    psi = [Finding.model_validate(item) for item in second['detection']['findings'] if item['rule'].startswith(('pagespeed_', 'lighthouse_'))]
    assert len(psi) == 4 and all(item.state == 'unverified' for item in psi)

    def forbid(*args, **kwargs):
        pytest.fail('Saved review/render unexpectedly accessed the network')
    monkeypatch.setattr('requests.Session', forbid)
    source = tmp_path / 'runs' / first['run_id'] / 'collection.json'
    before = source.read_bytes()
    state = (tmp_path / 'state.json').read_bytes()
    review = generate_review(config, first['run_id'], skip_ai=True)
    assert review.narrative_source == 'deterministic'
    assert generate_review(config, first['run_id'], skip_ai=True) == review
    render_site(tmp_path, tmp_path.parent / (tmp_path.name + '-site'))
    assert source.read_bytes() == before and (tmp_path / 'state.json').read_bytes() == state
    with pytest.raises(ValueError, match='digest mismatch'):
        source.write_bytes(before + b'\n')
        generate_review(config, first['run_id'], skip_ai=True)


def test_pagespeed_findings_use_existing_bounded_ai_validation_and_fallback(tmp_path, payload, monkeypatch):
    from seo_reviewer.review import generate_review
    from seo_reviewer.review_models import AIItem, Narrative
    from seo_reviewer.triage import build_triage_input, triage_findings
    from test_review import client, response as model_response

    item = measured(payload)
    item.body_path, item.body_sha256 = 'pagespeed/x.json', 'abc'
    findings = detect([item])
    data = {
        'schema_version': 1, 'run_id': 'run', 'status': 'collected',
        'coverage': {'attempted': 1, 'successful': 1, 'failed': 0, 'deferred': 0},
        'observations': [page().model_dump(mode='json')],
        'pagespeed': {'enabled': True, 'observations': [item.model_dump(mode='json')]},
        'detection': {'alert_status': 'warning', 'baseline_only': True, 'comparable_pages': 0,
                      'changed_pages': 0, 'widespread_change': False,
                      'findings': [finding.model_dump(mode='json') for finding in findings]},
    }
    config = Config(site_url=SITE, data_dir=tmp_path)
    bounded = build_triage_input(config, data, findings)
    row = next(row for row in bounded['findings'] if row['rule'] == 'pagespeed_performance')
    assert row['evidence'][0]['strategy'] == 'mobile'
    assert row['evidence'][0]['body_path'] == 'pagespeed/x.json'
    assert row['supporting_audits'][0]['id'] in item.audits
    assert len(json.dumps(bounded, ensure_ascii=False, separators=(',', ':')).encode()) <= config.ai_max_input_bytes
    narrative = Narrative(headline='Review lab loading performance', summary='Investigate the measured lab result.', prioritized_issues=[
        AIItem(title='Unique issue title', completion_criterion='Unique completion check', finding_id=row['id'], evidence_ids=[row['id'] + ':finding'], explanation='Lighthouse reports poor lab loading.', recommended_action='Inspect the recorded failed audits.')], verification_items=[])
    calls = client(monkeypatch, [model_response(narrative)])
    result, metadata = triage_findings(config, data, findings)
    assert result and metadata.outcome == 'success' and len(calls) == 2
    # A different device/finding's evidence is rejected by the existing validator.
    narrative.prioritized_issues[0].evidence_ids = [next(f.id for f in findings if f.id != row['id']) + ':finding']
    client(monkeypatch, [model_response(narrative), model_response(narrative)])
    assert triage_findings(config, data, findings)[0] is None
    directory = tmp_path / 'runs/run'
    directory.mkdir(parents=True)
    (directory / 'collection.json').write_text(json.dumps(data))
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    review = generate_review(config, 'run')
    assert review.narrative_source == 'deterministic' and review.findings == findings
    assert review.narrative.prioritized_issues


def test_pagespeed_unavailable_without_prior_findings_is_not_a_site_problem():
    item = PageSpeedObservation(run_id='run', url=URL, strategy='mobile', collected_at=datetime.now(UTC), error='http_429')
    assert detect([item]) == []


def test_error_audit_with_stale_score_cannot_resolve_old_finding(payload):
    original = measured(payload)
    active = {item.id: item for item in detect([original]) if item.rule.startswith('lighthouse_seo:')}
    payload['lighthouseResult']['audits']['document-title'].update(score=1, scoreDisplayMode='error')
    current = measured(payload, score=0.9, lcp=2000)
    findings = detect([current], active=active)
    assert len(findings) == 1 and findings[0].state == 'unverified'


def test_invalid_shapes_and_unpaired_unicode_do_not_break_collection(tmp_path, payload):
    payload['lighthouseResult']['audits']['document-title']['description'] = '\ud800'
    payload['lighthouseResult']['categories']['seo']['auditRefs'].append({'id': '\ud800'})
    payload['loadingExperience'] = {'metrics': {'\ud800': {'percentile': 10, 'distributions': None}}}
    items, _, store = collect(tmp_path, [api_response(payload)], strategies=['mobile'])
    assert items[0].status == 'incomplete'
    assert items[0].body_path and (store.path / items[0].body_path).is_file()
    items[0].model_dump_json().encode()


def test_wrong_page_within_origin_is_rejected(payload):
    payload['lighthouseResult']['requestedUrl'] = SITE + '/different/'
    assert measured(payload).status == 'unavailable'


def test_huge_json_number_is_incomplete_not_a_collection_crash(tmp_path, payload):
    payload['lighthouseResult']['audits']['total-blocking-time']['numericValue'] = 10 ** 400
    items, _, _ = collect(tmp_path, [api_response(payload)], strategies=['mobile'])
    assert items[0].status == 'incomplete' and items[0].metrics['tbt_ms'] is None


def test_different_lighthouse_version_cannot_claim_recovery(payload):
    original = measured(payload)
    active = {item.id: item for item in detect([original])}
    current = measured(payload, score=0.9, lcp=2000)
    current.audits['document-title'].score, current.audits['document-title'].failed = 1, False
    current.lighthouse_version = 'next-version'
    assert all(item.state == 'unverified' for item in detect([current], {measurement_key(original): original}, active))


def test_default_page_budget_makes_only_six_requests(tmp_path, payload):
    observations = [page(SITE + path) for path in ['/', '/articles/', '/articles/example/', '/other/']]
    config = Config(site_url=SITE)
    selected = select_pages(observations, config)
    replies = []
    for url in selected:
        for strategy in ['mobile', 'desktop']:
            raw = copy.deepcopy(payload)
            raw['lighthouseResult'].update(requestedUrl=url, finalUrl=url)
            raw['lighthouseResult']['configSettings']['formFactor'] = strategy
            replies.append(api_response(raw))
    session = FakeSession(replies)
    result = collect_pagespeed(config, RunStore(tmp_path), observations, session=session)
    assert len(result) == len(session.calls) == 6
    assert all(item.status == 'success' for item in result)
    assert len({(item.url, item.strategy) for item in result}) == 6
