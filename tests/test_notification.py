from seo_reviewer.notification import GitHubDelivery, ISSUE_TITLE


def test_delivery_creates_daily_issue_and_comment(monkeypatch):
    delivery = GitHubDelivery("owner/repo", "test-token")
    calls = []
    replies = iter([[], {"number": 12}, [], {"id": 3}])

    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return next(replies)

    monkeypatch.setattr(delivery, "request", request)
    assert delivery.deliver("run-1", "integration result") is True
    assert calls[1][2]["json"]["title"] == ISSUE_TITLE
    assert calls[-1][1] == "/issues/12/comments"
    assert "<!-- daily-seo-reviewer:run-1 -->" in calls[-1][2]["json"]["body"]


def test_duplicate_run_is_not_posted(monkeypatch):
    delivery = GitHubDelivery("owner/repo", "test-token")
    calls = []
    replies = iter([
        [{"title": ISSUE_TITLE, "number": 4}],
        [{"body": "<!-- daily-seo-reviewer:run-1 -->\nintegration result"}],
    ])

    def request(method, path, **kwargs):
        calls.append(method)
        return next(replies)

    monkeypatch.setattr(delivery, "request", request)
    assert delivery.deliver("run-1", "integration result") is False
    assert calls == ["GET", "GET"]


def test_paginate_deduplication_past_first_hundred_comments(monkeypatch):
    delivery = GitHubDelivery("owner/repo", "test-token")
    calls = []

    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/issues":
            return [{"title": ISSUE_TITLE, "number": 4}]
        if kwargs["params"]["page"] == 1:
            return [{"body": "old run"}] * 100
        return [{"body": "<!-- daily-seo-reviewer:run-1 -->\nintegration result"}]

    monkeypatch.setattr(delivery, "request", request)
    assert delivery.deliver("run-1", "integration result") is False
    assert len(calls) == 3


def test_retry_updates_existing_gate_result_without_duplicate_comment(monkeypatch):
    delivery = GitHubDelivery("owner/repo", "test-token")
    calls = []
    replies = iter([
        [{"title": ISSUE_TITLE, "number": 4}],
        [{"id": 9, "body": "<!-- daily-seo-reviewer:run-1 -->\nfailed"}],
        {"id": 9},
    ])

    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return next(replies)

    monkeypatch.setattr(delivery, "request", request)
    assert delivery.deliver("run-1", "passed") is True
    assert calls[-1][:2] == ("PATCH", "/issues/comments/9")
    assert not any(method == "POST" for method, _, _ in calls)


def test_latest_preflight_handles_flat_extraction(tmp_path):
    from seo_reviewer.notification import latest_preflight
    result = tmp_path / "preflight.json"
    result.write_text("{}")
    assert latest_preflight(tmp_path) == result


def test_latest_preflight_selects_latest_numeric_attempt(tmp_path):
    from seo_reviewer.notification import latest_preflight
    for attempt in (2, 10):
        folder = tmp_path / f"preflight-result-{attempt}"
        folder.mkdir()
        (folder / "preflight.json").write_text("{}")
    assert latest_preflight(tmp_path).parent.name == "preflight-result-10"
