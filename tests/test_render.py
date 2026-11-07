import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from lxml import html

from seo_reviewer.detection import Finding
from seo_reviewer.render import render_site, safe_url
from seo_reviewer.review_models import Generation, Narrative, Review


def save_review(directory, run_id='run-1', date=None, alert='warning', status='collected', source='deterministic', findings=None, baseline=False):
    date = date or datetime(2026, 11, 7, 12, tzinfo=UTC)
    findings = findings if findings is not None else [Finding(id='f1', rule='missing_description', urls=['https://example.com/'], severity='warning', first_seen_run=run_id, last_seen_run=run_id, before='old', observed='<script>alert(1)</script>', evidence=[{'run_id': run_id, 'body_path': 'responses/public.body', 'body_sha256': 'abc'}])]
    coverage = {'attempted': 1, 'successful': 1 if status == 'collected' else 0, 'failed': 0 if status == 'collected' else 1, 'deferred': 0}
    collection = {'run_id': run_id, 'schema_version': 1, 'completed_at': date.isoformat(), 'observations': [], 'errors': [], 'request_errors': [], 'deferred_urls': [], 'coverage': coverage, 'status': status}
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
    review = save_review(data)
    render_site(data, output, base='/daily-seo-reviewer')
    latest = (output / 'index.html').read_text()
    assert latest == (output / 'reviews/run-1.html').read_text()
    tree = html.fromstring(latest)
    assert not tree.xpath('//script | //img')
    assert len(tree.xpath('//h1')) == 1
    assert '&lt;script&gt;' in latest and '&lt;img' in latest
    assert 'AI summary unavailable' in latest
    assert 'Asia/Yerevan' in latest
    assert not list(output.rglob('*.body'))
    assert_local_links_resolve(output, '/daily-seo-reviewer')


@pytest.mark.parametrize('bad', ['javascript:alert(1)', 'data:text/html,<script>', '//evil.example', 'https://u:p@example.com', 'https://example.com/\nfoo', 'https://example.com\\@evil.com'])
def test_reject_unsafe_external_links(bad):
    assert safe_url(bad) is None


@pytest.mark.parametrize('status,alert,baseline', [('collection_failed', 'verification_required', False), ('partial_crawl', 'warning', False), ('collected', 'healthy', True)])
def test_distinct_report_states_and_empty_findings(tmp_path, status, alert, baseline):
    data, output = tmp_path / 'data', tmp_path / 'site'
    save_review(data, status=status, alert=alert, baseline=baseline, findings=[])
    render_site(data, output)
    page = (output / 'index.html').read_text()
    assert status in page and alert in page
    assert 'No prioritized issues' in page
    if baseline:
        assert 'Baseline only' in page
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
    assert len(history.xpath('//tbody/tr')) == 20
    assert_local_links_resolve(output, '')


def test_empty_archive(tmp_path):
    output = tmp_path / 'site'
    assert render_site(tmp_path / 'data', output)['review_count'] == 0
    assert 'No reviews yet' in (output / 'index.html').read_text()
    assert_local_links_resolve(output, '')


def test_stale_freshness_and_unverified_and_resolved(tmp_path):
    data, output = tmp_path / 'data', tmp_path / 'site'
    findings = [Finding(id=f'f{i}', rule='missing_title', urls=['https://example.com'], severity='warning', state=state, first_seen_run='run-1', last_seen_run='run-1') for i, state in enumerate(['resolved', 'unverified'])]
    save_review(data, findings=findings)
    render_site(data, output, now=datetime(2026, 11, 10, tzinfo=UTC))
    text = (output / 'index.html').read_text()
    assert 'Stale at publication' in text
    assert 'Resolved issues' in text and 'Verification items' in text


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
