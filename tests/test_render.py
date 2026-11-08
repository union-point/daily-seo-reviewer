import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from lxml import html

from seo_reviewer.detection import Finding
from seo_reviewer.render import render_site, safe_url
from seo_reviewer.review_models import AIItem, Generation, Narrative, Review


def save_review(directory, run_id='run-1', date=None, alert='warning', status='collected', source='deterministic', findings=None, baseline=False, coverage=None, collection_updates=None):
    date = date or datetime(2026, 11, 7, 12, tzinfo=UTC)
    findings = findings if findings is not None else [Finding(id='f1', rule='missing_description', urls=['https://example.com/'], severity='warning', first_seen_run=run_id, last_seen_run=run_id, before='old', observed='<script>alert(1)</script>', evidence=[{'run_id': run_id, 'body_path': 'responses/public.body', 'body_sha256': 'abc'}])]
    coverage = coverage or {'attempted': 1, 'successful': 1 if status == 'collected' else 0, 'failed': 0 if status == 'collected' else 1, 'deferred': 0}
    collection = {'run_id': run_id, 'schema_version': 1, 'completed_at': date.isoformat(), 'observations': [], 'errors': [], 'request_errors': [], 'deferred_urls': [], 'coverage': coverage, 'status': status}
    collection.update(collection_updates or {})
    raw = json.dumps(collection).encode()
    path = directory / 'runs' / run_id
    path.mkdir(parents=True, exist_ok=True)
    (path / 'collection.json').write_bytes(raw)
    (path / 'responses').mkdir(exist_ok=True)
    (path / 'responses/public.body').write_text('<script>doNotPublishRawHTML()</script>')
    review = Review(run_id=run_id, created_at=date, collection_path=f'runs/{run_id}/collection.json', collection_sha256=hashlib.sha256(raw).hexdigest(), alert_status=alert, collection_status=status, coverage=coverage, baseline_only=baseline, findings=findings, detection={'widespread_change': False}, deterministic_summary='Authoritative code summary', narrative=Narrative(headline='AI summary unavailable' if source == 'deterministic' else 'Review findings', summary='<img src=x onerror=alert(1)>', prioritized_issues=[], verification_items=[]), narrative_source=source, generation=Generation(prompt_version='triage-v3', reason='disabled', requested_model='gpt-6.1-terra', input_sha256='abc', input_bytes=0, included_finding_ids=[], omitted_findings=0))
    (directory / 'reviews').mkdir(exist_ok=True)
    (directory / 'reviews' / f'{run_id}.json').write_text(review.model_dump_json())
    return review


def assert_local_links_resolve(output, base):
    for path in output.rglob('*.html'):
        tree = html.fromstring(path.read_text())
        for href in tree.xpath('//a/@href | //link/@href'):
            if href.startswith('#') or '://' in href:
                continue
            target = href.split('#')[0]
            assert target.startswith(base + '/')
            assert (output / target[len(base) + 1:]).is_file(), (path, href)


def test_escaping_shared_template_and_safe_data_links(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    review = save_review(data, source='ai')
    review.narrative.prioritized_issues = [AIItem(finding_id='f1', evidence_ids=['f1:finding'], explanation='<img src=x onerror=alert(1)>', recommended_action='<script>unsafe()</script>')]
    (data / 'reviews/run-1.json').write_text(review.model_dump_json())
    render_site(data, output, base='/daily-seo-reviewer')
    latest = (output / 'index.html').read_text()
    assert latest == (output / 'reviews/run-1.html').read_text()
    tree = html.fromstring(latest)
    assert not tree.xpath('//script | //img')
    assert len(tree.xpath('//h1')) == 1
    assert '&lt;script&gt;' in latest and '&lt;img' in latest
    assert 'Recommended action:' in latest
    assert 'Asia/Yerevan' in latest
    assert not list(output.rglob('*.body'))
    assert_local_links_resolve(output, '/daily-seo-reviewer')


@pytest.mark.parametrize('bad', ['javascript:alert(1)', 'data:text/html,<script>', '//evil.example', 'https://u:p@example.com', 'https://example.com/\nfoo', 'https://example.com\\@evil.com'])
def test_reject_unsafe_external_links(bad):
    assert safe_url(bad) is None


@pytest.mark.parametrize('status,alert,baseline,label', [('collection_failed', 'verification_required', False, 'Needs verification'), ('partial_crawl', 'warning', False, 'Needs attention'), ('collected', 'healthy', True, 'No issues found in checked pages')])
def test_distinct_report_states_and_empty_findings(tmp_path, status, alert, baseline, label):
    data, output = tmp_path / 'data', tmp_path / 'site'
    save_review(data, status=status, alert=alert, baseline=baseline, findings=[])
    render_site(data, output)
    page = (output / 'index.html').read_text()
    assert label in page
    assert 'No priority issues' in page
    if baseline:
        assert 'First report' in page
    else:
        assert 'current condition is unknown' in page
    assert_local_links_resolve(output, '')


def test_archive_pagination_and_collection_time_order(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    start = datetime(2026, 11, 1, tzinfo=UTC)
    for i in range(31):
        save_review(data, run_id=f'run-{i:02d}', date=start + timedelta(minutes=i), findings=[])
    # Regenerating an old narrative does not change which collection is latest.
    path = data / 'reviews/run-00.json'
    review = Review.model_validate_json(path.read_text())
    review.created_at = start + timedelta(days=100)
    path.write_text(review.model_dump_json())
    result = render_site(data, output)
    assert result['latest_run_id'] == 'run-30'
    assert (output / 'archive/page-2.html').exists()
    first = html.fromstring((output / 'archive/index.html').read_text())
    assert len(first.xpath('//tbody/tr')) == 30
    history = html.fromstring((output / 'index.html').read_text())
    assert len(history.xpath('//tbody/tr')) == 5
    for tree in (first, history):
        links = tree.xpath('//tbody/tr/*[1]/a')
        assert links and all('Nov 2026' in item.text_content() for item in links)
        assert 'run-30' not in tree.text_content()
    assert_local_links_resolve(output, '')


def test_empty_archive(tmp_path):
    output = tmp_path / 'site'
    assert render_site(tmp_path / 'data', output)['review_count'] == 0
    assert 'No reports yet' in (output / 'index.html').read_text()
    assert_local_links_resolve(output, '')


def test_stale_freshness_and_unverified_and_resolved(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    findings = [Finding(id=f'f{i}', rule='missing_title', urls=['https://example.com'], severity='warning', state=state, first_seen_run='run-1', last_seen_run='run-1') for i, state in enumerate(['resolved', 'unverified'])]
    save_review(data, findings=findings)
    render_site(data, output, now=datetime(2026, 11, 10, tzinfo=UTC))
    text = (output / 'index.html').read_text()
    assert 'Check is over 36 hours old' in text
    assert 'Resolved issues' in text and 'Needs verification' in text


def test_refuses_evidence_overwrite_and_stale_publication(tmp_path):
    data = tmp_path / 'data'
    save_review(data)
    with pytest.raises(ValueError, match='separate'):
        render_site(data, data)
    with pytest.raises(ValueError, match='no saved review'):
        render_site(data, tmp_path / 'site', require_run_id='not-current')
    assert not (tmp_path / 'site').exists()


def test_refuses_mismatched_evidence_digest(tmp_path):
    data = tmp_path / 'data'
    save_review(data)
    (data / 'runs/run-1/collection.json').write_text('{}')
    with pytest.raises(ValueError, match='digest mismatch'):
        render_site(data, tmp_path / 'site')


def test_render_cli_creates_current_delivery_artifact(tmp_path):
    from seo_reviewer.render import main
    data = tmp_path / 'data'
    save_review(data)
    pointer = tmp_path / 'current.json'
    pointer.write_text('{"run_id": "run-1"}')
    assert main(['--data-dir', str(data), '--output-dir', str(tmp_path / 'site'), '--run-id-file', str(pointer), '--delivery-dir', str(tmp_path / 'delivery')]) == 0
    assert Review.model_validate_json((tmp_path / 'delivery/review.json').read_text()).run_id == 'run-1'


def test_existing_generated_preflight_can_upgrade_without_touching_arbitrary_files(tmp_path):
    from seo_reviewer.storage import publish_probe
    data, output = tmp_path / 'data', tmp_path / 'site'
    save_review(data)
    output.mkdir()
    (output / 'index.txt').write_text('Daily SEO Reviewer integration preflight. See preflight.json.\n')
    (output / 'preflight.json').write_text('{}')
    render_site(data, output)
    assert (output / 'index.html').exists()
    unrelated = tmp_path / 'user-files'
    unrelated.mkdir()
    (unrelated / 'index.html').write_text('user content')
    with pytest.raises(ValueError, match='not owned'):
        render_site(data, unrelated)
    assert (unrelated / 'index.html').read_text() == 'user content'


def main_report_text(tree):
    """Text a reader sees before opening optional technical disclosures."""
    tree = html.fromstring(html.tostring(tree))
    for disclosure in tree.xpath('//details'):
        disclosure.drop_tree()
    return tree.text_content()


def test_marketer_report_hides_internal_details_but_preserves_evidence(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    review = save_review(data, collection_updates={
        'errors': ['InternalTimeout: request /responses/private.body'],
        'request_errors': [{'error': 'robots_rate_deferred', 'attempts': 3}],
    })
    original_review = (data / 'reviews/run-1.json').read_bytes()
    original_collection = (data / review.collection_path).read_bytes()
    render_site(data, output, require_run_id='run-1', workflow_url='https://github.com/example/actions/runs/1')
    tree = html.fromstring((output / 'index.html').read_text())
    visible = main_report_text(tree)
    for internal in ('run-1', 'f1', 'missing_description', 'SHA-256', review.collection_sha256, 'Confidence', 'deterministic', 'InternalTimeout', 'robots_rate_deferred', 'private.body', 'disabled'):
        assert internal not in visible
    assert 'Some checks or page discovery could not be completed.' in visible
    assert visible.count('AI summary unavailable') == 1
    assert 'Search description missing' in visible
    for label in ('Affected pages', 'Recommended action:'):
        assert label in visible
    assert not tree.xpath('//details[@open]')
    technical_links = tree.xpath('//a[contains(@href, "/data/") or contains(@href, "github.com")]')
    assert not technical_links
    assert not tree.xpath("//details")
    assert "For specialists" not in tree.text_content()
    assert not tree.xpath('//*[contains(@class, "coverage-grid")]')
    assert json.loads((output / 'data/reviews/run-1.json').read_bytes()) == json.loads(original_review)
    assert (output / 'data/runs/run-1/collection.json').read_bytes() == original_collection
    assert (data / 'reviews/run-1.json').read_bytes() == original_review
    assert (data / review.collection_path).read_bytes() == original_collection


@pytest.mark.parametrize('status,coverage,updates,statement', [
    ('partial_crawl', {'attempted': 49, 'successful': 48, 'failed': 1, 'deferred': 1}, {}, '48 of 50 pages checked'),
    ('collection_failed', {'attempted': 0, 'successful': 0, 'failed': 0, 'deferred': 0}, {'cohort': ['https://example.com/' + str(i) for i in range(50)]}, '0 of 50 pages checked'),
    ('collected', {'attempted': 50, 'successful': 50, 'failed': 0, 'deferred': 0}, {'errors': ['Sitemap unavailable']}, '50 of 50 pages checked'),
    ('collection_failed', {'attempted': 0, 'successful': 0, 'failed': 0, 'deferred': 0}, {}, 'No pages checked'),
])
def test_incomplete_report_never_gives_all_clear(tmp_path, status, coverage, updates, statement):
    data, output = tmp_path / 'data', tmp_path / 'site'
    save_review(data, status=status, alert='healthy', findings=[], coverage=coverage, collection_updates=updates)
    render_site(data, output)
    tree = html.fromstring((output / 'index.html').read_text())
    visible = main_report_text(tree)
    assert statement in visible
    assert 'Check incomplete' in visible
    assert 'current condition is unknown' in visible
    assert 'No issues found in checked pages' not in visible
    archive = (output / 'archive/index.html').read_text()
    assert 'Check incomplete' in archive and 'status--healthy' not in archive


def test_issue_lifecycle_copy_does_not_claim_unknown_or_old_values_are_current(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    findings = [Finding(id=f'f{i}', rule='missing_title', urls=['https://example.com/' + state], severity='warning', state=state, regression=state == 'new', before='Previous title', observed='', first_seen_run='run-1', last_seen_run='run-1') for i, state in enumerate(['new', 'ongoing', 'worsened', 'resolved', 'unverified'])]
    save_review(data, findings=findings)
    render_site(data, output)
    tree = html.fromstring((output / 'index.html').read_text())
    articles = {article.xpath('.//a')[0].text_content().rsplit('/', 1)[-1]: article for article in tree.xpath('//article')}
    assert 'New issue' in main_report_text(articles['new'])
    assert 'Before' in main_report_text(articles['new']) and 'Not set' in main_report_text(articles['new'])
    assert 'Still present' in main_report_text(articles['ongoing'])
    assert 'Worsened' in main_report_text(articles['worsened'])
    assert 'no longer found this issue' in main_report_text(articles['resolved'])
    assert 'No fix is needed' in main_report_text(articles['resolved'])
    assert 'could not confirm whether it is still happening' in main_report_text(articles['unverified'])
    assert 'recheck the affected pages' in main_report_text(articles['unverified'])
    for state in ('resolved', 'unverified'):
        assert not articles[state].xpath('./dl')
    assert '1 new issue, 1 worsened, 1 still present, 1 resolved' in tree.text_content()
    assert '1 issue needs verification' in tree.text_content()


def test_first_observation_is_not_called_new_issue_without_regression(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    save_review(data, baseline=True)
    render_site(data, output)
    tree = html.fromstring((output / 'index.html').read_text())
    assert 'First report' in main_report_text(tree)
    assert 'First detected' in main_report_text(tree.xpath('//article')[0])
    assert 'New issue' not in main_report_text(tree.xpath('//article')[0])


def test_newly_checked_page_does_not_imply_issue_existed_in_previous_report(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    save_review(data, baseline=False)
    render_site(data, output)
    text = main_report_text(html.fromstring((output / 'index.html').read_text()))
    assert '0 still present' in text
    assert '1 issue was detected for the first time' in text


def test_removed_preferred_page_is_explained_without_claiming_new_target(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    finding = Finding(id='canonical', rule='canonical_changed', urls=['https://example.com/'], severity='warning', before=['https://example.com/preferred'], observed=[], regression=True, first_seen_run='run-1', last_seen_run='run-1')
    save_review(data, findings=[finding])
    render_site(data, output)
    text = main_report_text(html.fromstring((output / 'index.html').read_text()))
    assert 'no longer names a preferred version' in text
    assert 'points search engines to a different' not in text
    assert 'https://example.com/preferred' in text
    assert 'Not set' in text


def test_assessment_and_action_plan_use_saved_analysis_without_note_labels(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    review = save_review(data, source='ai')
    review.narrative.headline = 'Focus on the pages people find first'
    review.narrative.summary = '<script>saved assessment</script>'
    review.narrative.prioritized_issues = [AIItem(finding_id='f1', evidence_ids=['f1:finding'], explanation='Start with the homepage description.', recommended_action='Write a useful homepage description.')]
    (data / 'reviews/run-1.json').write_text(review.model_dump_json())
    render_site(data, output)
    tree = html.fromstring((output / 'index.html').read_text())
    assert tree.xpath('//*[@id="assessment-heading"]')[0].text == "Today's summary"
    assert review.narrative.headline in tree.text_content()
    assert not tree.xpath('//script')
    assert 'saved assessment' in tree.text_content()
    assert 'AI note' not in tree.text_content()
    plan = tree.xpath('//ol[@class="prioritized-list"]')[0]
    assert 'Write a useful homepage description.' in plan.text_content()
    assert 'Suggested owner' not in tree.text_content()
    assert not plan.xpath('.//details')
    visible_issue = main_report_text(plan)
    assert 'What happened:' not in visible_issue and 'Why it matters:' not in visible_issue
    assert 'The page has no search description.' not in visible_issue
    assert 'A useful description can help people decide' not in visible_issue
    assert 'Done when:' not in visible_issue
    assert tree.text_content().count('Write a useful homepage description.') == 1
    assert 'Your action plan' not in tree.text_content()
    assert tree.xpath('//article/p[@class="issue-assessment"]')[0].text == 'Start with the homepage description.'


def test_action_plan_excludes_resolved_and_rechecks_unverified(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    findings = [Finding(id=state, rule='http_error', urls=['https://example.com/' + state], severity='critical', state=state, first_seen_run='run-1', last_seen_run='run-1') for state in ('resolved', 'unverified')]
    save_review(data, findings=findings)
    render_site(data, output)
    tree = html.fromstring((output / 'index.html').read_text())
    assert not tree.xpath('//ol[@class="prioritized-list"]')
    unverified = tree.xpath('//article')[0]
    assert 'Needs verification' in unverified.text_content()
    assert 'Complete a reliable follow-up check' in unverified.text_content()
    assert 'Done when:' not in tree.xpath('//article')[1].text_content()


def test_delivery_and_report_select_same_analysis_revision(tmp_path):
    from seo_reviewer.render import main
    data, output = tmp_path / 'data', tmp_path / 'site'
    original = save_review(data)
    revised = original.model_copy(deep=True)
    revised.created_at = original.created_at + timedelta(days=1)
    revised.narrative_source = 'ai'
    revised.generation.outcome = 'success'
    revised.narrative.headline = 'A refreshed analysis'
    revision = data / 'review_revisions/run-1/revision.json'
    revision.parent.mkdir(parents=True)
    revision.write_text(revised.model_dump_json())
    pointer = tmp_path / 'current.json'
    pointer.write_text('{"run_id":"run-1"}')
    assert main(['--data-dir', str(data), '--output-dir', str(output), '--run-id-file', str(pointer), '--delivery-dir', str(tmp_path / 'delivery')]) == 0
    delivered = Review.model_validate_json((tmp_path / 'delivery/review.json').read_text())
    assert delivered.narrative.headline == 'A refreshed analysis'
    assert 'A refreshed analysis' in (output / 'index.html').read_text()
    assert Review.model_validate_json((data / 'reviews/run-1.json').read_text()) == original


def test_ai_report_omits_optional_stock_copy_and_empty_sections(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    save_review(data, source='ai', findings=[], alert='healthy')
    render_site(data, output)
    tree = html.fromstring((output / 'index.html').read_text())
    assert not tree.xpath('//details')
    assert not tree.xpath('//*[@class="check-results"]')
    assert not tree.xpath('//a[@href="#issues-1"]')
    assert 'No resolved issues' not in tree.text_content()
    assert 'No issues awaiting verification' not in tree.text_content()


@pytest.mark.parametrize('status', ['collected', 'collection_failed'])
def test_report_identifies_configured_website_before_results(tmp_path, status):
    data, output = tmp_path / 'data', tmp_path / 'site'
    save_review(data, status=status, findings=[], collection_updates={'config': {'site_url': 'https://www.djangoproject.com'}})
    render_site(data, output)
    tree = html.fromstring((output / 'index.html').read_text())
    header = tree.xpath('//header[contains(@class,"page-header")]')[0]
    link = header.xpath('.//a[@href="https://www.djangoproject.com"]')[0]
    assert link.text == 'www.djangoproject.com'
    assert 'www.djangoproject.com' in tree.xpath('//title')[0].text
    assert 'Website: Not recorded' not in header.text_content()
    assert_local_links_resolve(output, '')


def test_report_does_not_link_unsafe_website_configuration(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    save_review(data, collection_updates={'config': {'site_url': 'javascript:alert(1)'}})
    render_site(data, output)
    tree = html.fromstring((output / 'index.html').read_text())
    assert 'Website: Not recorded' in tree.text_content()
    assert not tree.xpath('//a[starts-with(@href,"javascript:")]')


def pagespeed_observation(**overrides):
    item = {
        'run_id': 'run-1', 'url': 'https://example.com/', 'strategy': 'mobile',
        'collected_at': '2026-11-07T12:00:00+00:00', 'status': 'success',
        'performance_score': 42, 'seo_score': 90,
        'metrics': {'lcp_ms': 4200, 'cls': 0.3, 'fcp_ms': 1200, 'tbt_ms': 600, 'speed_index_ms': 3500},
        'audits': {'document-title': {'id': 'document-title', 'category': 'seo', 'failed': True,
            'title': '<script>untrusted()</script>', 'description': 'Document has no title.',
            'score': 0, 'display_value': None, 'numeric_value': None, 'numeric_unit': None}},
        'missing': [], 'lighthouse_version': '13.0.0', 'final_url': 'https://example.com/',
        'crux_page': {'status': 'unavailable'}, 'crux_origin': {'status': 'unavailable'},
    }
    item.update(overrides)
    return item


def test_pagespeed_reports_lab_metrics_and_escaped_audits(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    mobile = pagespeed_observation()
    desktop = pagespeed_observation(strategy='desktop', performance_score=88)
    save_review(data, findings=[], collection_updates={'pagespeed': {'enabled': True, 'observations': [mobile, desktop]}})
    render_site(data, output)
    page = (output / 'index.html').read_text()
    tree = html.fromstring(page)
    section = tree.xpath('//section[@aria-labelledby="performance-heading"]')[0]
    assert len(section.xpath('.//tbody/tr')) == 7
    assert section.xpath('.//table[@class="pagespeed-table"]')
    assert section.xpath('.//thead/tr/th/text()') == ['Metric', 'Mobile', 'Desktop']
    assert 'Mobile' in section.text_content() and 'Desktop' in section.text_content()
    for value in ['4.20 s', '0.300', '1.20 s', '600 ms', '3.50 s', '42 / 100', '90 / 100']:
        assert value in section.text_content()
    assert 'laboratory measurements' in section.text_content()
    assert 'CrUX Page field data:' in section.text_content()
    assert 'Unavailable' in section.text_content()
    assert section.xpath('.//details/summary')
    assert not tree.xpath('//script')
    assert '&lt;script&gt;untrusted()&lt;/script&gt;' in page
    assert page == (output / 'reviews/run-1.html').read_text()


@pytest.mark.parametrize('saved,message', [
    (None, 'older report'),
    ({'enabled': False, 'observations': []}, 'disabled'),
    ({'enabled': True, 'observations': []}, 'No successfully collected pages'),
])
def test_pagespeed_empty_states(tmp_path, saved, message):
    from seo_reviewer.render import pagespeed_presentation
    collection = {} if saved is None else {'pagespeed': saved}
    assert message in pagespeed_presentation(collection)['empty']


def test_pagespeed_unavailable_measurement_never_displays_stored_scores(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    item = pagespeed_observation(status='unavailable', error='Timeout')
    save_review(data, findings=[], collection_updates={'pagespeed': {'enabled': True, 'observations': [item]}})
    render_site(data, output)
    tree = html.fromstring((output / 'index.html').read_text())
    section = tree.xpath('//section[@aria-labelledby="performance-heading"]')[0]
    assert 'does not confirm a website performance problem' in section.text_content()
    assert '42' not in section.text_content() and '4.20 s' not in section.text_content()
    assert not section.xpath('.//li/strong[contains(text(), "untrusted")]')


@pytest.mark.parametrize('prior_changes,expected', [
    ({}, 'Performance -10 points'),
    ({'strategy': 'desktop'}, ''),
    ({'url': 'https://example.com/other'}, ''),
    ({'lighthouse_version': '12.0.0'}, ''),
    ({'final_url': 'https://example.com/other'}, ''),
    ({'status': 'unavailable'}, ''),
])
def test_pagespeed_changes_require_matching_measurements(prior_changes, expected):
    from seo_reviewer.render import pagespeed_presentation
    current = pagespeed_observation()
    prior = pagespeed_observation(performance_score=52, **prior_changes)
    result = pagespeed_presentation({'pagespeed': {'enabled': True,
        'observations': [current], 'previous_observations': {'mobile\nhttps://example.com/': prior}}})
    assert expected in result['rows'][0]['changes'] if expected else result['rows'][0]['changes'] == ''


def test_pagespeed_incomplete_preserves_missing_values_and_field_scope(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    item = pagespeed_observation(status='incomplete', performance_score=None,
        metrics={'lcp_ms': None, 'cls': 0}, missing=['performance_score', 'lcp_ms'],
        crux_page={'status': 'available', 'scope': 'origin', 'overall_category': 'FAST',
            'metrics': {'CUMULATIVE_LAYOUT_SHIFT_SCORE': {'percentile': 12, 'category': 'FAST'}}})
    save_review(data, findings=[], collection_updates={'pagespeed': {'enabled': True, 'observations': [item]}})
    render_site(data, output)
    page = html.fromstring((output / 'index.html').read_text()).text_content()
    assert 'Incomplete' in page and 'LCP: Unavailable' not in page and '0.000' in page
    assert 'Performance: Unavailable' not in page
    assert '0 of 1 planned measurements completed' in page and '1 incomplete' in page
    assert 'Some measurements or audit results are missing' in page
    assert 'CrUX Origin fallback field data:' in page and '0.12' in page


def test_pagespeed_all_failures_show_compact_observed_reason_and_no_table(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    rows = [pagespeed_observation(status='unavailable', error='http_429', http_status=429),
        pagespeed_observation(status='unavailable', strategy='desktop', error='quota_deferred')]
    save_review(data, findings=[], collection_updates={'pagespeed': {'enabled': True, 'observations': rows}})
    render_site(data, output)
    tree = html.fromstring((output / 'index.html').read_text())
    section = tree.xpath('//section[@aria-labelledby="performance-heading"]')[0]
    assert not section.xpath('.//table')
    assert 'Performance data unavailable' in section.text_content()
    assert '0 of 2 planned measurements completed' in section.text_content()
    assert 'HTTP 429 (rate limit)' in section.text_content()
    assert 'main SEO audit results above' in section.text_content()
    assert section.xpath('./details/summary')[0].text == 'PageSpeed collection details'
    assert 'Not requested after an earlier API access or rate-limit response.' in section.xpath('./details')[0].text_content()
    assert 'LCP:' not in section.text_content() and 'No comparable measurements' not in section.text_content()
    assert 'CrUX' not in section.text_content()
    assert not tree.xpath('//header[contains(@class,"page-header")]//*[contains(text(),"Some Lighthouse measurements")]')


def test_pagespeed_partial_groups_available_strategies_and_one_warning(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    rows = [pagespeed_observation(strategy='desktop'), pagespeed_observation(),
        pagespeed_observation(url='https://example.com/other', status='unavailable', error='Timeout')]
    save_review(data, findings=[], collection_updates={'pagespeed': {'enabled': True, 'observations': rows}})
    render_site(data, output)
    section = html.fromstring((output / 'index.html').read_text()).xpath('//section[@aria-labelledby="performance-heading"]')[0]
    assert len(section.xpath('./div[@class="check-results"]')) == 1
    main = section.xpath('./div[@class="check-results"]')[0]
    assert len(main.xpath('.//h3/a')) == 1
    assert main.xpath('.//thead/tr/th/text()') == ['Metric', 'Mobile', 'Desktop']
    assert len(section.xpath('./p[contains(@class,"notice")]')) == 1
    assert '2 of 3 planned measurements completed' in section.text_content()
    assert 'https://example.com/other' not in main.text_content()
    assert 'PageSpeed request timed out' in section.xpath('./details')[0].text_content()
    assert 'Unavailable' not in main.text_content()
    assert not main.xpath('.//th[text()="Change"]')


@pytest.mark.parametrize('error,http_status,expected', [
    ('http_403', 403, 'HTTP 403 (access denied)'),
    ('ReadTimeout', None, 'request timed out'),
    ('invalid_response', None, 'invalid response'),
    ('<script>secret-api-key</script>', None, 'did not provide a usable measurement'),
    ('http_429?key=secret-api-key', None, 'did not provide a usable measurement'),
])
def test_pagespeed_errors_use_saved_safe_labels_without_guessing_causes(tmp_path, error, http_status, expected):
    data, output = tmp_path / 'data', tmp_path / 'site'
    item = pagespeed_observation(status='unavailable', error=error, http_status=http_status)
    save_review(data, findings=[], collection_updates={'pagespeed': {'enabled': True, 'observations': [item]}})
    render_site(data, output)
    page = (output / 'index.html').read_text()
    assert expected in page and 'secret-api-key' not in page
    assert 'missing API key' not in page and 'project quota' not in page
    assert not html.fromstring(page).xpath('//script')


def test_pagespeed_failure_does_not_add_header_warning_or_claim_failed_seo_audit_completed(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    item = pagespeed_observation(status='unavailable', error='http_429', http_status=429)
    save_review(data, findings=[], status='collection_failed', alert='verification_required',
        collection_updates={'pagespeed': {'enabled': True, 'observations': [item]}})
    render_site(data, output)
    tree = html.fromstring((output / 'index.html').read_text())
    header = tree.xpath('//header[contains(@class,"page-header")]')[0]
    assert 'Lighthouse' not in header.text_content() and 'PageSpeed' not in header.text_content()
    assert 'Check incomplete' in header.text_content() or 'Needs verification' in header.text_content()
    section = tree.xpath('//section[@aria-labelledby="performance-heading"]')[0]
    assert 'SEO audit completed' not in section.text_content()
    assert 'SEO audit is healthy' not in section.text_content()


def test_pagespeed_failure_summary_prefers_actual_error_over_deferred_rows():
    from seo_reviewer.render import pagespeed_presentation
    rows = [pagespeed_observation(status='unavailable', strategy='desktop', error='quota_deferred'),
        pagespeed_observation(status='unavailable', error='http_429', http_status=429)]
    result = pagespeed_presentation({'pagespeed': {'enabled': True, 'observations': rows}})
    assert 'HTTP 429' in result['reason']


def test_ai_narrative_sentinels_survive_serialization_without_template_calls(tmp_path, monkeypatch):
    data, output = tmp_path / 'data', tmp_path / 'site'
    findings = [Finding(id=state, rule='lighthouse_seo:document-title', urls=['https://example.com/' + state], severity='warning', state=state, first_seen_run='run-1', last_seen_run='run-1', observed={'score': 0}) for state in ('new', 'unverified', 'resolved')]
    review = save_review(data, source='ai', findings=findings)
    review.narrative.headline = 'SENTINEL executive heading'
    review.narrative.summary = 'SENTINEL executive assessment'
    for state, bucket in [('new', review.narrative.prioritized_issues), ('unverified', review.narrative.verification_items)]:
        bucket.append(AIItem(finding_id=state, evidence_ids=[state + ':finding'], title='SENTINEL title ' + state,
            explanation='SENTINEL explanation ' + state, recommended_action='SENTINEL recommendation ' + state,
            completion_criterion='SENTINEL completion ' + state))
    raw = review.model_dump_json()
    (data / 'reviews/run-1.json').write_text(raw)
    def forbidden(*args):
        pytest.fail('AI rendering invoked deterministic fallback narrative generation')
    monkeypatch.setattr('seo_reviewer.render.fallback_issue_presentation', forbidden)
    render_site(data, output)
    tree = html.fromstring((output / 'index.html').read_text())
    assert len(tree.xpath('//article')) == 2
    for state in ('new', 'unverified'):
        for label in ('title', 'explanation', 'recommendation', 'completion'):
            assert 'SENTINEL ' + label + ' ' + state in tree.text_content()
    assert 'SENTINEL executive assessment' in tree.text_content()
    assert 'A Lighthouse SEO audit failed on this page.' not in tree.text_content()
    assert 'Run a new check and review the result with your web team.' not in tree.text_content()
    assert 'Additional technical findings' in tree.text_content()
    assert 'resolved' in tree.xpath('//details[summary="View technical findings"]')[0].text_content().lower()
    saved = Review.model_validate_json((output / 'data/reviews/run-1.json').read_text())
    assert saved.narrative_source == 'ai' and saved.findings == findings
    assert saved.narrative == Review.model_validate_json(raw).narrative


def test_ai_unanalysed_findings_are_facts_without_fallback_cards(tmp_path, monkeypatch):
    data, output = tmp_path / 'data', tmp_path / 'site'
    save_review(data, source='ai')
    monkeypatch.setattr('seo_reviewer.render.fallback_issue_presentation', lambda _: pytest.fail('mixed AI/fallback mode'))
    render_site(data, output)
    tree = html.fromstring((output / 'index.html').read_text())
    assert not tree.xpath('//article')
    assert 'Additional technical findings' in tree.text_content()
    assert 'missing_description' in tree.text_content()
    assert 'Ask your web team' not in tree.text_content()


def test_complete_saved_fallback_is_rendered_without_generating_new_prose(tmp_path, monkeypatch):
    data, output = tmp_path / 'data', tmp_path / 'site'
    review = save_review(data)
    review.narrative.summary = 'SAVED deterministic summary'
    review.narrative.prioritized_issues = [AIItem(finding_id='f1', evidence_ids=['f1:finding'], title='SAVED fallback title',
        explanation='SAVED fallback explanation', recommended_action='SAVED fallback action', completion_criterion='SAVED fallback completion')]
    (data / 'reviews/run-1.json').write_text(review.model_dump_json())
    monkeypatch.setattr('seo_reviewer.render.fallback_issue_presentation', lambda _: pytest.fail('new fallback prose in renderer'))
    render_site(data, output)
    page = html.fromstring((output / 'index.html').read_text()).text_content()
    for label in ('summary', 'title', 'explanation', 'action', 'completion'):
        assert 'SAVED ' + ('deterministic summary' if label == 'summary' else 'fallback ' + label) in page
    assert 'AI summary unavailable' in page
