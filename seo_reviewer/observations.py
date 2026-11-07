"""Extract observed SEO values without assigning findings or alert status."""

import json
import re
from typing import Literal

from lxml import etree, html
from pydantic import BaseModel, Field

from seo_reviewer.collection import Collector, Fetch
from seo_reviewer.models import FetchEvidence


class Observation(BaseModel):
    schema_version: int = 1
    run_id: str
    evidence: FetchEvidence
    outcome: Literal["success", "collection_failed", "http_error", "unsupported_content", "parse_failed"]
    title: str | None = None
    description: str | None = None
    h1s: list[str] = Field(default_factory=list)
    canonicals: list[str] = Field(default_factory=list)
    robots_meta: list[str] = Field(default_factory=list)
    x_robots_tag: str | None = None
    json_ld_count: int = 0
    json_ld_errors: list[str] = Field(default_factory=list)


def normalize(value: str) -> str:
    return ' '.join(value.split())


def observe(fetch: Fetch, run_id: str) -> Observation:
    from urllib.parse import urljoin
    item = Observation(run_id=run_id, evidence=fetch.evidence, outcome='collection_failed')
    item.x_robots_tag = Collector._header(fetch.evidence, 'x-robots-tag')
    if fetch.evidence.error:
        return item
    if not fetch.ok:
        item.outcome = 'http_error'
        return item
    if 'html' not in (Collector._header(fetch.evidence, 'content-type') or '').lower():
        item.outcome = 'unsupported_content'
        return item
    try:
        content_type = Collector._header(fetch.evidence, 'content-type') or ''
        charset = re.search(r'charset\s*=\s*["\']?([^;\s"\']+)', content_type, re.I)
        parser = html.HTMLParser(encoding=charset.group(1) if charset else None, no_network=True)
        tree = html.fromstring(fetch.body, parser=parser)
    except (etree.LxmlError, ValueError, LookupError):
        item.outcome = 'parse_failed'
        return item
    item.outcome = 'success'
    titles = tree.xpath('//title')
    item.title = normalize(titles[0].text_content()) if titles else None
    item.h1s = [normalize(node.text_content()) for node in tree.xpath('//h1')]
    for node in tree.xpath('//meta[@name]'):
        name = node.get('name', '').lower()
        content = normalize(node.get('content', ''))
        if name == 'description' and item.description is None:
            item.description = content
        if name in {'robots', 'googlebot', 'bingbot'}:
            item.robots_meta.append(f'{name}: {content}')
    base = fetch.evidence.final_url
    bases = tree.xpath('//base[@href]/@href')
    if bases:
        base = urljoin(base, bases[0])
    item.canonicals = [urljoin(base, node.get('href', '')) for node in tree.xpath('//link[@href]') if 'canonical' in node.get('rel', '').lower().split()]
    for node in tree.xpath('//script[@type]'):
        if node.get('type', '').lower().split(';')[0].strip() == 'application/ld+json':
            item.json_ld_count += 1
            try:
                json.loads(node.text or '', parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            except (ValueError, RecursionError):
                item.json_ld_errors.append(f'Invalid JSON-LD block {item.json_ld_count}')
    return item
