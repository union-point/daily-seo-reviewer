from pathlib import Path

from test_render import save_review
from seo_reviewer.daily_delivery import latest_delivery_review, main, review_comment


def test_daily_comment_uses_code_facts_and_saved_actions(tmp_path):
    review = save_review(tmp_path / 'data')
    from seo_reviewer.review_models import AIItem
    review.narrative.prioritized_issues = [AIItem(finding_id='f1', evidence_ids=['f1:finding'], explanation='Recorded issue', recommended_action='SENTINEL saved action')]
    body = review_comment(review, 'https://example.com/daily-seo-reviewer/', 'https://github.com/owner/repo/actions/runs/123', 'success')
    assert '1/1' in body and '**warning**' in body
    assert '/daily-seo-reviewer/reviews/run-1.html' in body
    assert 'SENTINEL saved action' in body
    assert '<img' not in body and '<script' not in body
    assert 'AI summary unavailable' in body


def test_failed_publication_does_not_link_stale_report(tmp_path):
    review = save_review(tmp_path / 'data')
    body = review_comment(review, 'https://example.com/', 'https://github.com/owner/repo/actions/runs/123', 'failure')
    assert 'Publication unavailable' in body
    assert '[Review report]' not in body


def test_artifact_layouts_and_latest_attempt(tmp_path):
    (tmp_path / 'review.json').write_text('{}')
    assert latest_delivery_review(tmp_path) == tmp_path / 'review.json'
    for number in (2, 10):
        folder = tmp_path / f'daily-delivery-{number}'
        folder.mkdir()
        (folder / 'review.json').write_text('{}')
    assert latest_delivery_review(tmp_path).parent.name == 'daily-delivery-10'


def test_failure_without_artifact_posts_pipeline_failure(monkeypatch, tmp_path):
    calls = []
    class FakeDelivery:
        def __init__(self, *args): self.session = self
        def close(self): pass
        def deliver(self, marker, body): calls.append((marker, body)); return True
    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/repo')
    monkeypatch.setenv('GH_TOKEN', 'test')
    monkeypatch.setattr('seo_reviewer.daily_delivery.GitHubDelivery', FakeDelivery)
    code = main(['--artifact-dir', str(tmp_path), '--workflow-url', 'https://github.com/owner/repo/actions/runs/123', '--workflow-run-id', '123', '--deployment-result', 'skipped'])
    assert code == 1
    assert calls[0][0] == 'workflow-123'
    assert 'No current review' in calls[0][1]


def test_successful_saved_artifact_delivery(monkeypatch, tmp_path):
    review = save_review(tmp_path / 'data')
    artifact = tmp_path / 'downloaded'
    artifact.mkdir()
    (artifact / 'review.json').write_text(review.model_dump_json())
    calls = []
    class FakeDelivery:
        def __init__(self, *args): self.session = self
        def close(self): pass
        def deliver(self, marker, body): calls.append((marker, body)); return False
    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/repo')
    monkeypatch.setenv('GH_TOKEN', 'test')
    monkeypatch.setattr('seo_reviewer.daily_delivery.GitHubDelivery', FakeDelivery)
    assert main(['--artifact-dir', str(artifact), '--workflow-url', 'https://github.com/owner/repo/actions/runs/123', '--workflow-run-id', '123', '--deployment-result', 'success', '--pages-url', 'https://example.com/']) == 0
    assert calls[0][0] == review.run_id
