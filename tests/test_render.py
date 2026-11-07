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
    review = Review(run_id=run_id, created_at=date, collection_path=f'runs/{run_id}/collection.json', collection_sha256=hashlib.sha256(raw).hexdigest(), alert_status=alert, collection_status=status, coverage=coverage, baseline_only=baseline, findings=findings, detection={'widespread_change': False}, deterministic_summary='Authoritative code summary', narrative=Narrative(headline='AI summary unavailable' if source == 'deterministic' else 'Review findings', summary='<img src=x onerror=alert(1)>', prioritized_issues=[], verification_items=[]), narrative_source=source, generation=Generation(reason='disabled', requested_model='gpt-6.1-terra', input_sha256='abc', input_bytes=0, included_finding_ids=[], omitted_findings=0))
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
    assert 'Next action:' in latest
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
    for label in ('What happened:', 'Affected pages', 'Why it matters:', 'Next action:'):
        assert label in visible
    assert not tree.xpath('//details[@open]')
    technical_links = tree.xpath('//a[contains(@href, "/data/") or contains(@href, "github.com")]')
    assert technical_links
    assert all(link.xpath('ancestor::details[summary="For specialists"]') for link in technical_links)
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
    assert 'First observed' in main_report_text(tree.xpath('//article')[0])
    assert 'New issue' not in main_report_text(tree.xpath('//article')[0])


def test_newly_checked_page_does_not_imply_issue_existed_in_previous_report(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    save_review(data, baseline=False)
    render_site(data, output)
    text = main_report_text(html.fromstring((output / 'index.html').read_text()))
    assert '0 still present' in text
    assert '1 issue was observed for the first time' in text


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
    assert tree.xpath('//*[@id="assessment-heading"]')[0].text == review.narrative.headline
    assert not tree.xpath('//script')
    assert 'saved assessment' in tree.text_content()
    assert 'AI note' not in tree.text_content()
    plan = tree.xpath('//ol[@class="action-plan"]')[0]
    assert 'Write a useful homepage description.' in plan.text_content()
    assert 'Content team' in plan.text_content() and 'Done when:' in plan.text_content()
    target = plan.xpath('.//a/@href')[0][1:]
    assert tree.xpath('//*[@id=$target]', target=target)
    assert tree.xpath('//article/p[@class="issue-assessment"]')[0].text == 'Start with the homepage description.'


def test_action_plan_excludes_resolved_and_rechecks_unverified(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    findings = [Finding(id=state, rule='http_error', urls=['https://example.com/' + state], severity='critical', state=state, first_seen_run='run-1', last_seen_run='run-1') for state in ('resolved', 'unverified')]
    save_review(data, findings=findings)
    render_site(data, output)
    tree = html.fromstring((output / 'index.html').read_text())
    plan = tree.xpath('//ol[@class="action-plan"]')[0]
    assert len(plan.xpath('./li')) == 1
    assert 'Verify first' in plan.text_content()
    assert 'Complete a reliable follow-up check' in plan.text_content()
