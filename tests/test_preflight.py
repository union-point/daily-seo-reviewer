import pytest
from lxml import etree

from conftest import response
from seo_reviewer.preflight import site_checks, sitemap_locations

SITEMAP = b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/weblog/2026/nov/07/test/</loc></url></urlset>'
BLOG = b'<html><title>Weblog</title><h1>Weblog</h1><a href="/weblog/2026/nov/07/test/">Article</a></html>'
ARTICLE = b'<html><title>Article</title><h1>Article</h1></html>'
HTML_HEADERS = {"Content-Type": "text/html; charset=utf-8"}


def test_site_probe_validates_all_required_resources(make_collector):
    collector, session = make_collector([
        response(404), response(body=SITEMAP),
        response(body=BLOG, **HTML_HEADERS), response(body=ARTICLE, **HTML_HEADERS),
    ])
    checks = site_checks(collector)
    assert [check.name for check in checks] == ["robots", "sitemap", "weblog", "article"]
    assert all(check.status == "passed" for check in checks)
    assert session.calls[-1][0] == "https://example.com/weblog/2026/nov/07/test/"


def test_sitemap_indexes_remain_on_origin(make_collector):
    index = b'<sitemapindex><sitemap><loc>https://other.example/sitemap.xml</loc></sitemap><sitemap><loc>https://example.com/blog.xml</loc></sitemap></sitemapindex>'
    collector, session = make_collector([
        response(404), response(body=index), response(body=SITEMAP),
        response(body=BLOG, **HTML_HEADERS), response(body=ARTICLE, **HTML_HEADERS),
    ])
    assert all(check.status == "passed" for check in site_checks(collector))
    assert all("other.example" not in url for url, _ in session.calls)


def test_challenge_stops_further_site_development(make_collector):
    collector, session = make_collector([
        response(404), response(body=b"<title>Just a moment...</title>"),
    ])
    assert site_checks(collector)[-1].status == "failed"
    assert len(session.calls) == 2


@pytest.mark.parametrize("body", [
    b"<html>error</html>", b"<urlset/>", b"<broken",
    b'<!DOCTYPE urlset [<!ENTITY secret SYSTEM "file:///etc/passwd">]><urlset><url><loc>&secret;</loc></url></urlset>',
])
def test_reject_invalid_or_unsafe_sitemaps(body):
    with pytest.raises((ValueError, etree.LxmlError)):
        sitemap_locations(body)


def test_weblog_with_no_dated_article_fails_gate(make_collector):
    collector, _ = make_collector([
        response(404), response(body=SITEMAP),
        response(body=b"<title>Weblog</title><h1>Weblog</h1>", **HTML_HEADERS),
    ])
    check = site_checks(collector)[-1]
    assert check.name == "article"
    assert check.status == "failed"
