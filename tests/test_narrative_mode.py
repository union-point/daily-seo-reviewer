import copy
import json

import pytest

from test_review import collection, client, narrative, response
from seo_reviewer.render import render_site
from seo_reviewer.review import generate_review
from seo_reviewer.review_models import Review


def test_ai_sentinels_survive_serialization_and_html_without_fallback(collection, monkeypatch, tmp_path):
    config, data, findings = collection
    data['completed_at'] = '2026-11-08T09:00:00+00:00'
    data['config'] = {'site_url': 'https://example.com'}
    source = config.data_dir / 'runs/run1/collection.json'
    source.write_text(json.dumps(data))
    before = source.read_bytes()
    output = narrative()
    issue = output.prioritized_issues[0]
    issue.title = 'SENTINEL precise issue title'
    issue.explanation = 'SENTINEL observed issue explanation'
    issue.recommended_action = 'SENTINEL concrete action'
    issue.completion_criterion = 'SENTINEL observable completion'
    output.summary = 'SENTINEL executive summary'
    client(monkeypatch, [response(output)])
    review = generate_review(config, 'run1')
    saved = Review.model_validate_json((config.data_dir / 'reviews/run1.json').read_text())
    assert saved.narrative_source == 'ai' and saved.generation.outcome == 'success'
    assert saved.findings == findings and saved.detection == data['detection']
    render_site(config.data_dir, tmp_path.parent / (tmp_path.name + '-site'))
    page = (tmp_path.parent / (tmp_path.name + '-site') / 'index.html').read_text()
    for value in [issue.title, issue.explanation, issue.recommended_action, issue.completion_criterion, output.summary]:
        assert value in page
    for value in ['Run a new check and review the result with your web team.', 'Search description missing', 'Ask your web team']:
        assert value not in page
    assert source.read_bytes() == before and saved.narrative == review.narrative


@pytest.mark.parametrize('field,value', [('title', None), ('title', ''), ('completion_criterion', None), ('completion_criterion', '  '), ('explanation', ''), ('recommended_action', '')])
def test_required_ai_fields_trigger_retry_then_whole_fallback(collection, monkeypatch, field, value):
    config, data, findings = collection
    output = narrative().model_dump()
    output['prioritized_issues'][0][field] = value
    calls = client(monkeypatch, [response(output), response(output)])
    review = generate_review(config, 'run1')
    assert review.narrative_source == 'deterministic'
    assert review.generation.outcome == 'unavailable'
    assert len(review.generation.attempts) == 2
    assert review.narrative.prioritized_issues[0].title
    assert review.narrative.prioritized_issues[0].completion_criterion
    assert review.findings == findings
    assert len([call for call in calls if 'input' in call]) == 2


def test_disabled_ai_saves_complete_fallback_once(collection):
    config, data, findings = collection
    review = generate_review(config, 'run1', skip_ai=True)
    assert review.narrative_source == 'deterministic' and review.generation.reason == 'disabled'
    assert review.narrative.prioritized_issues[0].title == 'Search description missing'
    assert generate_review(config, 'run1') == review


def test_new_ai_artifact_rejects_missing_title_on_load(collection, monkeypatch):
    from pydantic import ValidationError
    config, _, _ = collection
    client(monkeypatch, [response(narrative())])
    review = generate_review(config, 'run1')
    raw = review.model_dump()
    del raw['narrative']['prioritized_issues'][0]['title']
    with pytest.raises(ValidationError):
        Review.model_validate(raw)


def test_new_fallback_resolved_findings_do_not_generate_prose_in_renderer(collection, monkeypatch, tmp_path):
    config, data, findings = collection
    data['completed_at'] = '2026-11-08T09:00:00+00:00'
    data['detection']['findings'][0]['state'] = 'resolved'
    (config.data_dir / 'runs/run1/collection.json').write_text(json.dumps(data))
    generate_review(config, 'run1', skip_ai=True)
    def forbidden(*args):
        pytest.fail('New artifact attempted renderer fallback generation')
    monkeypatch.setattr('seo_reviewer.render.fallback_issue_presentation', forbidden)
    render_site(config.data_dir, tmp_path.parent / (tmp_path.name + '-site'))
