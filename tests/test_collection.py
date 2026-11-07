import hashlib

import pytest
import requests

from conftest import response
from seo_reviewer.collection import retry_delay


def test_no_page_requests_before_robots(make_collector):
    collector, session = make_collector([])
    assert collector.fetch("https://example.com/").evidence.error == "robots_unavailable"
    assert session.calls == []


def test_robots_wildcards_and_allow_precedence(make_collector):
    collector, session = make_collector([
        response(body=b"User-agent: *\nDisallow: /private/*\nAllow: /private/public$\n"),
        response(body=b"allowed"),
    ])
    collector.load_robots()
    assert collector.fetch("https://example.com/private/secret").evidence.error == "robots_disallowed"
    assert collector.fetch("https://example.com/private/public").ok
    assert len(session.calls) == 2


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_unavailable_robots_prevents_crawling(make_collector, status):
    collector, session = make_collector([response(status)], retries=0)
    collector.load_robots()
    assert collector.fetch("https://example.com/").evidence.error == "robots_unavailable"
    assert len(session.calls) == 1


@pytest.mark.parametrize("status", [404, 410])
def test_missing_robots_allows_pages(make_collector, status):
    collector, _ = make_collector([response(status), response()])
    collector.load_robots()
    assert collector.fetch("https://example.com/").ok


@pytest.mark.parametrize("body", [b"<html>login</html>", b"<!DOCTYPE html><title>Error</title>"])
def test_robots_soft_error_does_not_allow_pages(make_collector, body):
    collector, _ = make_collector([response(body=body)])
    collector.load_robots()
    assert collector.robots is None


@pytest.mark.parametrize("target,error", [
    ("https://other.example/", "off_origin"),
    ("http://example.com/", "off_origin"),
    ("https://example.com:444/", "off_origin"),
    ("/secret", "robots_disallowed"),
])
def test_redirect_target_checked_before_request(make_collector, target, error):
    collector, session = make_collector([
        response(body=b"User-agent: *\nDisallow: /secret"),
        response(302, Location=target),
    ])
    collector.load_robots()
    result = collector.fetch("https://example.com/start")
    assert result.evidence.error == error
    assert len(session.calls) == 2


def test_same_origin_redirect_and_raw_evidence(make_collector):
    collector, session = make_collector([
        response(404), response(301, Location="/end"), response(body=b"final"),
    ])
    collector.load_robots()
    result = collector.fetch("https://example.com/start")
    assert result.ok
    assert result.evidence.final_url == "https://example.com/end"
    assert result.evidence.redirects == ["https://example.com/end"]
    assert result.evidence.body_sha256 == hashlib.sha256(b"final").hexdigest()
    assert (collector.store.path / result.evidence.body_path).read_bytes() == b"final"
    assert all(call[1]["allow_redirects"] is False for call in session.calls)
    assert all(call[1]["timeout"] == (5.0, 20.0) for call in session.calls)


def test_timeout_does_not_invent_missing_seo_fields(make_collector):
    collector, _ = make_collector([response(404), requests.Timeout("secret detail")], retries=0)
    collector.load_robots()
    result = collector.fetch("https://example.com/")
    assert result.evidence.error == "Timeout"
    assert not result.ok
    assert result.evidence.status_code is None
    assert "secret" not in result.evidence.model_dump_json()


def test_rate_limit_retry_after_and_crawl_delay(make_collector, clock):
    collector, _ = make_collector([
        response(body=b"User-agent: *\nCrawl-delay: 2\n"),
        response(429, **{"Retry-After": "5"}), response(),
    ])
    collector.load_robots()
    assert collector.fetch("https://example.com/").ok
    assert clock.sleeps == [0, 2, 5]


def test_long_retry_after_defers_instead_of_retrying_early(make_collector):
    collector, session = make_collector([response(404), response(503, **{"Retry-After": "120"})])
    collector.load_robots()
    assert collector.fetch("https://example.com/").evidence.error == "retry_deferred"
    assert len(session.calls) == 2


def test_retry_after_dates_and_invalid_values():
    assert retry_delay("Wed, 01 Jan 2100 00:00:00 GMT", 0) > 60
    assert retry_delay("nonsense", 1) == 2


@pytest.mark.parametrize("body", [b"<title>Just a moment...</title>", b"<script src='/cdn-cgi/challenge-platform/test'>"])
def test_challenge_is_collection_failure(make_collector, body):
    collector, _ = make_collector([response(404), response(body=body)])
    collector.load_robots()
    assert collector.fetch("https://example.com/").evidence.error == "challenge_response"


def test_oversized_response_is_not_a_successful_observation(make_collector):
    collector, _ = make_collector([response(404), response(body=b"12345")], max_body_bytes=4)
    collector.load_robots()
    assert collector.fetch("https://example.com/").evidence.error == "response_too_large"


def test_long_robots_delay_defers_instead_of_violating_policy(make_collector):
    collector, session = make_collector([response(body=b"User-agent: *\nCrawl-delay: 120")])
    collector.load_robots()
    assert collector.fetch("https://example.com/").evidence.error == "robots_rate_deferred"
    assert len(session.calls) == 1


def test_challenge_is_not_retried_even_with_transient_status(make_collector):
    collector, session = make_collector([
        response(404), response(503, body=b"<title>Just a moment...</title>"),
    ])
    collector.load_robots()
    assert collector.fetch("https://example.com/").evidence.error == "challenge_response"
    assert len(session.calls) == 2


def test_timeout_after_retry_does_not_reuse_previous_status(make_collector):
    collector, _ = make_collector([response(404), response(503), requests.Timeout()])
    collector.load_robots()
    result = collector.fetch("https://example.com/")
    assert result.evidence.error == "Timeout"
    assert result.evidence.status_code is None
