"""Prove collection and model access before expanding site-specific work."""

import os
import re
from datetime import UTC, datetime
from urllib.parse import urldefrag, urljoin, urlsplit

from lxml import etree, html

from seo_reviewer.collection import Collector, Fetch
from seo_reviewer.config import Config
from seo_reviewer.models import Check, Preflight
from seo_reviewer.storage import RunStore
from seo_reviewer.triage import probe_model

ARTICLE_PATH = re.compile(r"^/weblog/\d{4}/[a-zA-Z]{3}/\d{1,2}/[^/]+/$")


def sitemap_locations(body: bytes) -> tuple[str, list[str]]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    root = etree.fromstring(body, parser=parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError("Sitemap DTDs are not accepted")
    kind = etree.QName(root).localname
    if kind not in {"urlset", "sitemapindex"}:
        raise ValueError("Expected sitemap XML")
    locations = [
        value.strip() for value in root.xpath("./*[local-name()='url' or local-name()='sitemap']/*[local-name()='loc']/text()")
        if value.strip()
    ]
    if not locations:
        raise ValueError("Sitemap has no locations")
    return kind, locations


def html_document(result: Fetch) -> html.HtmlElement:
    if not result.ok:
        raise ValueError(result.evidence.error or f"HTTP {result.evidence.status_code}")
    content_type = Collector._header(result.evidence, "content-type") or ""
    if "html" not in content_type.lower():
        raise ValueError("Expected HTML Content-Type")
    document = html.fromstring(result.body)
    title = " ".join(document.xpath("//title/text()"))
    if not title.strip() or not document.xpath("//h1"):
        raise ValueError("Expected an HTML title and H1")
    return document


def site_checks(collector: Collector) -> list[Check]:
    checks: list[Check] = []
    robots = collector.load_robots()
    if collector.robots is None:
        return [Check(
            name="site", status="failed",
            detail=f"Robots policy unavailable: {robots.evidence.error or robots.evidence.status_code}; no pages requested",
        )]
    checks.append(Check(name="robots", status="passed", detail="Robots policy loaded before crawling"))
    pending = [collector.config.site_url + "/sitemap.xml"]
    seen: set[str] = set()
    sitemap_urls: set[str] = set()
    while pending and len(seen) < collector.config.max_sitemaps:
        url = pending.pop(0)
        if url in seen or not collector.in_scope(url):
            continue
        seen.add(url)
        result = collector.fetch(url)
        try:
            if not result.ok:
                raise ValueError(result.evidence.error or f"HTTP {result.evidence.status_code}")
            kind, locations = sitemap_locations(result.body)
        except (ValueError, etree.LxmlError) as exc:
            checks.append(Check(name="sitemap", status="failed", detail=f"Sitemap validation failed: {exc}"))
            return checks  # Includes challenges; never attempt bypasses or additional pages.
        scoped = [location for location in locations if collector.in_scope(location)]
        if kind == "sitemapindex":
            pending.extend(location for location in scoped if location not in seen)
        else:
            sitemap_urls.update(scoped)
    if not sitemap_urls:
        checks.append(Check(name="sitemap", status="failed", detail="No same-origin page URLs within the sitemap probe budget"))
        return checks
    checks.append(Check(
        name="sitemap", status="passed",
        detail=f"Validated {len(seen)} sitemap documents and {len(sitemap_urls)} same-origin URLs; {len(pending)} documents deferred",
    ))
    weblog = collector.fetch(collector.config.site_url + "/weblog/")
    try:
        document = html_document(weblog)
    except (ValueError, etree.LxmlError) as exc:
        checks.append(Check(name="weblog", status="failed", detail=f"Weblog validation failed: {exc}"))
        return checks
    checks.append(Check(name="weblog", status="passed", detail="Weblog contains an HTML title and H1"))
    candidates = [
        urldefrag(urljoin(weblog.evidence.final_url, href))[0]
        for href in document.xpath("//a/@href")
    ]
    candidates = [
        url for url in candidates
        if collector.in_scope(url) and ARTICLE_PATH.fullmatch(urlsplit(url).path)
    ]
    if not candidates:
        checks.append(Check(name="article", status="failed", detail="No dated article link found on the weblog"))
        return checks
    article = collector.fetch(candidates[0])
    try:
        html_document(article)
    except (ValueError, etree.LxmlError) as exc:
        checks.append(Check(name="article", status="failed", detail=f"Article validation failed: {exc}"))
        return checks
    checks.append(Check(name="article", status="passed", detail=f"Article HTML validated: {article.evidence.final_url}"))
    return checks


def run_preflight(config: Config, store: RunStore, *, skip_model: bool = False) -> Preflight:
    started = datetime.now(UTC)
    collector = Collector(config, store)
    try:
        checks = site_checks(collector)
    finally:
        collector.close()
    model = probe_model(config, skip=skip_model)
    checks.append(Check(name="openai", status=model.status, detail=model.detail))
    in_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    workflow_url = None
    if in_actions:
        workflow_url = (
            f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
            f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/"
            f"{os.environ.get('GITHUB_RUN_ID', '')}"
        )
    result = Preflight(
        run_id=store.run_id, started_at=started, completed_at=datetime.now(UTC),
        execution_context="github-actions" if in_actions else "local",
        workflow_url=workflow_url, config=config.model_dump(mode="json"),
        checks=checks, fetches=collector.fetches, model=model,
    )
    store.save_preflight(result)
    return result
